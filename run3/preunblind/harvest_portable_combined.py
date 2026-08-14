#!/usr/bin/env python3
"""Fail-closed harvester for portable masked combined-fit result archives."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tarfile
import tempfile
from dataclasses import dataclass


FIT_LINE = re.compile(r"^FIT CHECK: status=(\d+) covQual=(\d+) EDM=([^\s]+)$")
BOOTSTRAP_FIT_LINE = re.compile(r"^BOOTSTRAP FIT CHECK: status=(\d+) covQual=(\d+) EDM=([^\s]+)$")
LIMIT_LINE = re.compile(
    r"^LIMIT CHECK: q0\.025=([^\s]+) q0\.16=([^\s]+) q0\.5=([^\s]+) "
    r"q0\.84=([^\s]+) q0\.975=([^\s]+) p97/rMax=([^\s]+)$"
)
RANGE_LINE = re.compile(r"^RPF RANGE CHECK: count=18 positive_par0=4 status=0$")
UNSAFE_CARD_TOKENS = ("/srv", "/storage/local", "_CONDOR_SCRATCH", "/uscms")


@dataclass(frozen=True)
class Point:
    width: int
    mass: int
    rmax: str

    @property
    def signal(self) -> str:
        suffix = "" if self.width == 1 else f"_{self.width}"
        return f"signalZPrime{self.mass}{suffix}"

    @property
    def key(self) -> str:
        return f"w{self.width}_m{self.mass}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_point(width: str, mass: str, rmax: str) -> Point:
    width_int, mass_int = int(width), int(mass)
    if width_int not in {1, 10, 30}:
        raise ValueError(f"unsupported width: {width}")
    if mass_int <= 0:
        raise ValueError(f"invalid mass: {mass}")
    value = float(rmax)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"invalid rMax: {rmax}")
    return Point(width_int, mass_int, rmax)


def load_points(path: Path) -> list[Point]:
    points: list[Point] = []
    for line_number, raw_line in enumerate(path.read_text().splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        columns = line.split()
        if len(columns) != 3:
            raise ValueError(f"{path}:{line_number}: expected width mass rMax")
        points.append(parse_point(*columns))
    if not points or len(set(points)) != len(points):
        raise ValueError(f"invalid or duplicate points in {path}")
    return points


def safe_name(member: tarfile.TarInfo) -> str:
    name = PurePosixPath(member.name)
    if name.is_absolute() or ".." in name.parts:
        raise ValueError(f"unsafe archive member: {member.name}")
    return name.as_posix().lstrip("./")


def member_bytes(archive: tarfile.TarFile, name: str, source: Path) -> bytes:
    matches = [member for member in archive.getmembers() if safe_name(member) == name]
    if len(matches) != 1 or not matches[0].isfile():
        raise ValueError(f"expected exactly one regular {name} in {source}")
    stream = archive.extractfile(matches[0])
    if stream is None:
        raise ValueError(f"cannot read {name} in {source}")
    payload = stream.read()
    if not payload:
        raise ValueError(f"empty {name} in {source}")
    return payload


def parse_metadata(payload: bytes, source: Path) -> tuple[dict[str, str], str]:
    raw = payload.decode("utf-8", errors="strict")
    expected_keys = {
        "width", "mass_GeV", "signal", "rMax", "area", "workspace_sha256",
        "bootstrap_snapshot_sha256", "bootstrap_fit_sha256", "snapshot_sha256", "fit_sha256",
        "limit_sha256", "payload_sha256", "runtime_sha256",
        "background_seed_source", "background_fit_start_mode",
    }
    values: dict[str, str] = {}
    for line in raw.splitlines():
        key, separator, value = line.partition("=")
        if separator and key in expected_keys:
            if key in values:
                raise ValueError(f"duplicate {key} in combined.ok: {source}")
            values[key] = value
    missing = expected_keys.difference(values)
    if missing:
        raise ValueError(f"combined.ok missing {sorted(missing)} in {source}")
    return values, raw


def check_fit_and_limit_lines(raw: str, point: Point, source: Path) -> dict[str, object]:
    if "observed" in raw.lower():
        raise ValueError(f"observed output marker in {source}")
    fit_matches = [FIT_LINE.match(line) for line in raw.splitlines() if line.startswith("FIT CHECK:")]
    fit_matches = [match for match in fit_matches if match]
    if len(fit_matches) != 1:
        raise ValueError(f"expected exactly one valid FIT CHECK line in {source}")
    status, cov_qual, edm = fit_matches[0].groups()
    edm_value = float(edm)
    if int(status) != 0 or int(cov_qual) < 3 or not math.isfinite(edm_value) or edm_value > 0.01:
        raise ValueError(f"untrusted masked fit in {source}: status={status} covQual={cov_qual} EDM={edm}")
    bootstrap_matches = [
        BOOTSTRAP_FIT_LINE.match(line)
        for line in raw.splitlines()
        if line.startswith("BOOTSTRAP FIT CHECK:")
    ]
    bootstrap_matches = [match for match in bootstrap_matches if match]
    if len(bootstrap_matches) != 1:
        raise ValueError(f"expected exactly one valid BOOTSTRAP FIT CHECK line in {source}")
    bootstrap_status, bootstrap_cov_qual, bootstrap_edm = bootstrap_matches[0].groups()
    bootstrap_edm_value = float(bootstrap_edm)
    if (int(bootstrap_status) != 0 or int(bootstrap_cov_qual) < 3
            or not math.isfinite(bootstrap_edm_value) or bootstrap_edm_value > 0.01):
        raise ValueError(
            f"untrusted bootstrap fit in {source}: status={bootstrap_status} "
            f"covQual={bootstrap_cov_qual} EDM={bootstrap_edm}"
        )
    range_matches = [RANGE_LINE.match(line) for line in raw.splitlines() if line.startswith("RPF RANGE CHECK:")]
    range_matches = [match for match in range_matches if match]
    if len(range_matches) != 1:
        raise ValueError(f"expected exactly one valid RPF RANGE CHECK line in {source}")

    limit_matches = [LIMIT_LINE.match(line) for line in raw.splitlines() if line.startswith("LIMIT CHECK:")]
    limit_matches = [match for match in limit_matches if match]
    if len(limit_matches) != 1:
        raise ValueError(f"expected exactly one valid LIMIT CHECK line in {source}")
    values = [float(value) for value in limit_matches[0].groups()[:5]]
    p97_fraction = float(limit_matches[0].group(6))
    if any(not math.isfinite(value) or value <= 0 for value in values):
        raise ValueError(f"non-positive expected limit in {source}: {values}")
    if any(right <= left for left, right in zip(values, values[1:])):
        raise ValueError(f"unordered expected quantiles in {source}: {values}")
    if not math.isfinite(p97_fraction) or p97_fraction >= 0.9:
        raise ValueError(f"p97/rMax lacks headroom in {source}: {p97_fraction}")
    if values[-1] >= 0.9 * float(point.rmax):
        raise ValueError(f"p97 violates rMax headroom in {source}: {values[-1]}")
    return {
        "bootstrap_fit_status": int(bootstrap_status),
        "bootstrap_fit_covQual": int(bootstrap_cov_qual),
        "bootstrap_fit_edm": bootstrap_edm_value,
        "fit_status": int(status), "fit_covQual": int(cov_qual), "fit_edm": edm_value,
        "expected": values,
    }


def validate_archive(source: Path, point: Point) -> dict[str, object]:
    if not source.is_file() or source.stat().st_size == 0:
        raise ValueError(f"missing or empty result archive: {source}")
    prefix = "combine_result"
    area_prefix = f"{prefix}/area"
    workspace = f"{area_prefix}/workspace.root"
    bootstrap_snapshot = f"{area_prefix}/higgsCombine_bootstrap.MultiDimFit.mH0.root"
    bootstrap_fit = f"{area_prefix}/multidimfit_bootstrap.root"
    snapshot = f"{area_prefix}/higgsCombine_maskedBonly.MultiDimFit.mH0.root"
    fit = f"{area_prefix}/multidimfit_maskedBonly.root"
    limit = f"{area_prefix}/higgsCombine_expected.AsymptoticLimits.mH0.root"
    card = f"{area_prefix}/{point.signal}_card_combined.txt"
    metadata_name = f"{prefix}/combined.ok"
    try:
        with tarfile.open(source, "r:gz") as archive:
            members = archive.getmembers()
            names = [safe_name(member) for member in members]
            if len(names) != len(set(names)):
                raise ValueError(f"duplicate archive member in {source}")
            if any(name != prefix and not name.startswith(f"{prefix}/") for name in names):
                raise ValueError(f"unexpected top-level member in {source}")
            if any(member.issym() or member.islnk() for member in members):
                raise ValueError(f"link member forbidden in {source}")
            limit_roots = [name for name in names if "AsymptoticLimits" in name and name.endswith(".root")]
            if limit_roots != [limit]:
                raise ValueError(f"unexpected or missing AsymptoticLimits ROOT output in {source}: {limit_roots}")

            metadata, raw_metadata = parse_metadata(member_bytes(archive, metadata_name, source), source)
            expected = {"width": str(point.width), "mass_GeV": str(point.mass), "signal": point.signal,
                        "rMax": point.rmax, "area": "area"}
            for key, value in expected.items():
                if metadata[key] != value:
                    raise ValueError(f"{source}: combined.ok {key}={metadata[key]!r}, expected {value!r}")
            workspace_bytes = member_bytes(archive, workspace, source)
            bootstrap_snapshot_bytes = member_bytes(archive, bootstrap_snapshot, source)
            bootstrap_fit_bytes = member_bytes(archive, bootstrap_fit, source)
            snapshot_bytes = member_bytes(archive, snapshot, source)
            fit_bytes = member_bytes(archive, fit, source)
            limit_bytes = member_bytes(archive, limit, source)
            card_bytes = member_bytes(archive, card, source)
            for name, payload in (
                (workspace, workspace_bytes), (bootstrap_snapshot, bootstrap_snapshot_bytes),
                (bootstrap_fit, bootstrap_fit_bytes), (snapshot, snapshot_bytes),
                (fit, fit_bytes), (limit, limit_bytes),
            ):
                if not payload.startswith(b"root"):
                    raise ValueError(f"{source}: {name} lacks ROOT magic bytes")
            card_text = card_bytes.decode("utf-8", errors="strict")
            if point.signal not in card_text:
                raise ValueError(f"{source}: signal missing from combined card")
            if any(token in card_text for token in UNSAFE_CARD_TOKENS):
                raise ValueError(f"{source}: combined card is not self-contained")
            checksums = {
                "workspace_sha256": hashlib.sha256(workspace_bytes).hexdigest(),
                "bootstrap_snapshot_sha256": hashlib.sha256(bootstrap_snapshot_bytes).hexdigest(),
                "bootstrap_fit_sha256": hashlib.sha256(bootstrap_fit_bytes).hexdigest(),
                "snapshot_sha256": hashlib.sha256(snapshot_bytes).hexdigest(),
                "fit_sha256": hashlib.sha256(fit_bytes).hexdigest(),
                "limit_sha256": hashlib.sha256(limit_bytes).hexdigest(),
            }
            for key, value in checksums.items():
                if metadata[key] != value:
                    raise ValueError(f"{source}: checksum mismatch for {key}")
            fit_limit = check_fit_and_limit_lines(raw_metadata, point, source)
            area_members = [member for member in members if safe_name(member).startswith(f"{area_prefix}/")]
            if not area_members:
                raise ValueError(f"missing area in {source}")
    except tarfile.TarError as error:
        raise ValueError(f"cannot read archive {source}: {error}") from error
    return {"point": point, "source": source, "tar_sha256": sha256_file(source), "members": area_members,
            "background_seed_source": metadata["background_seed_source"],
            "background_fit_start_mode": metadata["background_fit_start_mode"],
            "checksums": checksums, "fit_limit": fit_limit, "card_sha256": hashlib.sha256(card_bytes).hexdigest()}


def archive_for_point(directory: Path, point: Point) -> Path:
    matches = sorted(directory.glob(f"{point.key}.tgz"))
    if len(matches) != 1:
        raise ValueError(f"expected exactly one archive for {point.key} in {directory}")
    return matches[0]


def extract_one(validated: dict[str, object], campaign: Path) -> dict[str, object]:
    point = validated["point"]
    source = validated["source"]
    members = validated["members"]
    assert isinstance(point, Point) and isinstance(source, Path) and isinstance(members, list)
    root = campaign / "workspaces" / "combined" / f"w{point.width}"
    root.mkdir(parents=True, exist_ok=True)
    destination = root / f"{point.signal}_area"
    if destination.exists():
        raise ValueError(f"refusing to overwrite existing combined area: {destination}")
    temporary = Path(tempfile.mkdtemp(prefix=f".harvest-{point.key}-", dir=root))
    try:
        staged = temporary / destination.name
        with tarfile.open(source, "r:gz") as archive:
            for member in members:
                assert isinstance(member, tarfile.TarInfo)
                relative = PurePosixPath(safe_name(member)).relative_to("combine_result/area")
                target = staged.joinpath(*relative.parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    stream = archive.extractfile(member)
                    if stream is None:
                        raise ValueError(f"cannot extract {member.name}")
                    with target.open("wb") as handle:
                        shutil.copyfileobj(stream, handle)
                else:
                    raise ValueError(f"unsupported archive member type: {member.name}")
        if destination.exists():
            raise ValueError(f"refusing to overwrite existing combined area: {destination}")
        os.rename(staged, destination)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    checksums = validated["checksums"]
    assert isinstance(checksums, dict)
    names = {"workspace_sha256": "workspace.root",
             "bootstrap_snapshot_sha256": "higgsCombine_bootstrap.MultiDimFit.mH0.root",
             "bootstrap_fit_sha256": "multidimfit_bootstrap.root",
             "snapshot_sha256": "higgsCombine_maskedBonly.MultiDimFit.mH0.root",
             "fit_sha256": "multidimfit_maskedBonly.root", "limit_sha256": "higgsCombine_expected.AsymptoticLimits.mH0.root"}
    for key, name in names.items():
        if sha256_file(destination / name) != checksums[key]:
            raise RuntimeError(f"post-extraction checksum mismatch: {destination / name}")
    return {"width": point.width, "mass_GeV": point.mass, "signal": point.signal, "rMax": point.rmax,
            "background_seed_source": validated["background_seed_source"],
            "background_fit_start_mode": validated["background_fit_start_mode"],
            "source_tar": str(source), "source_tar_sha256": validated["tar_sha256"], "destination": str(destination),
            "card_sha256": validated["card_sha256"], **checksums, **validated["fit_limit"]}


def write_ledger(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ValueError(f"refusing to overwrite existing ledger: {path}")
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump({"schema_version": 1, "records": records}, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.link(temporary, path)
    except FileExistsError as error:
        raise ValueError(f"refusing to overwrite existing ledger: {path}") from error
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--points", type=Path, help="all points.tsv mode")
    mode.add_argument("--width", choices=("1", "10", "30"), help="one-point canary mode")
    parser.add_argument("--mass")
    parser.add_argument("--rmax")
    parser.add_argument("--input", type=Path, action="append")
    parser.add_argument("--input-dir", type=Path)
    args = parser.parse_args()
    if args.points:
        if args.width or args.mass or args.rmax or args.input or not args.input_dir:
            parser.error("points mode requires --points and --input-dir only")
        points = load_points(args.points)
        archives = [(point, archive_for_point(args.input_dir, point)) for point in points]
    else:
        if not args.mass or not args.rmax or not args.input or len(args.input) != 1 or args.input_dir:
            parser.error("canary mode requires --width --mass --rmax and one --input")
        point = parse_point(args.width, args.mass, args.rmax)
        points, archives = [point], [(point, args.input[0])]
    validated = [validate_archive(source, point) for point, source in archives]
    campaign = args.campaign
    for item in validated:
        point = item["point"]
        assert isinstance(point, Point)
        if (campaign / "workspaces" / "combined" / f"w{point.width}" / f"{point.signal}_area").exists():
            raise ValueError("refusing to overwrite existing combined area")
    records = [extract_one(item, campaign) for item in validated]
    write_ledger(args.ledger, records)
    print(json.dumps({"harvested": len(records), "ledger": str(args.ledger)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, RuntimeError) as error:
        print(f"HARVEST_PORTABLE_COMBINED_FAILED: {error}", file=sys.stderr)
        raise SystemExit(2)
