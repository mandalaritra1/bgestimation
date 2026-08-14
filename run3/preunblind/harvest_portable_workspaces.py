#!/usr/bin/env python3
"""Fail-closed harvester for portable workspace-only Condor result tarballs.

The worker archive is not trusted: validate its expected point, checksums, and
blinding boundary before atomically moving the per-category workspace into the
campaign.  This tool never replaces an existing workspace or ledger.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import tarfile
import tempfile
from dataclasses import dataclass


FIT_OUTPUT_TOKENS = ("fitDiagnostics", "multidimfit", "AsymptoticLimits")


@dataclass(frozen=True)
class Point:
    category: str
    width: int
    mass: int

    @property
    def tf_order(self) -> str:
        return {"cen2425": "2x2", "fwd2425": "2x1"}[self.category]

    @property
    def signal(self) -> str:
        suffix = "" if self.width == 1 else f"_{self.width}"
        return f"signalZPrime{self.mass}{suffix}"

    @property
    def area_name(self) -> str:
        return f"ttbarfits_{self.category}_{self.tf_order}_{self.signal}"

    @property
    def key(self) -> str:
        return f"{self.category}_w{self.width}_m{self.mass}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_point(category: str, width: str, mass: str) -> Point:
    if category not in {"cen2425", "fwd2425"}:
        raise ValueError(f"unsupported category: {category}")
    width_int = int(width)
    if width_int not in {1, 10, 30}:
        raise ValueError(f"unsupported width: {width}")
    mass_int = int(mass)
    if mass_int <= 0:
        raise ValueError(f"invalid mass: {mass}")
    return Point(category, width_int, mass_int)


def load_matrix(path: Path) -> list[Point]:
    points: list[Point] = []
    for line_number, raw_line in enumerate(path.read_text().splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 3:
            raise ValueError(f"{path}:{line_number}: expected 3 columns")
        points.append(parse_point(*fields))
    if not points:
        raise ValueError(f"matrix is empty: {path}")
    if len(set(points)) != len(points):
        raise ValueError(f"matrix has duplicate points: {path}")
    return points


def parse_metadata(raw: bytes, source: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in raw.decode("utf-8", errors="strict").splitlines():
        if not line:
            continue
        key, separator, value = line.partition("=")
        if not separator or not key or key in values:
            raise ValueError(f"malformed workspace.ok in {source}")
        values[key] = value
    return values


def member_name(member: tarfile.TarInfo) -> str:
    candidate = PurePosixPath(member.name)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"unsafe archive member: {member.name}")
    return candidate.as_posix().lstrip("./")


def read_member(archive: tarfile.TarFile, name: str, source: Path) -> bytes:
    matches = [member for member in archive.getmembers() if member_name(member) == name]
    if len(matches) != 1 or not matches[0].isfile():
        raise ValueError(f"expected exactly one regular {name} in {source}")
    handle = archive.extractfile(matches[0])
    if handle is None:
        raise ValueError(f"cannot read {name} in {source}")
    payload = handle.read()
    if not payload:
        raise ValueError(f"empty {name} in {source}")
    return payload


def validate_archive(source: Path, point: Point) -> dict[str, object]:
    if not source.is_file() or source.stat().st_size == 0:
        raise ValueError(f"missing or empty result archive: {source}")
    prefix = "workspace_result"
    base_member = f"{prefix}/area/base.root"
    config_member = f"{prefix}/area/runConfig.json"
    card_member = f"{prefix}/area/{point.signal}_area/card.txt"
    metadata_member = f"{prefix}/workspace.ok"

    try:
        with tarfile.open(source, "r:gz") as archive:
            members = archive.getmembers()
            names = [member_name(member) for member in members]
            if len(names) != len(set(names)):
                raise ValueError(f"duplicate archive member in {source}")
            if any(name != prefix and not name.startswith(f"{prefix}/") for name in names):
                raise ValueError(f"unexpected top-level member in {source}")
            if any(any(token in name for token in FIT_OUTPUT_TOKENS) for name in names):
                raise ValueError(f"blinding violation: fit/limit output in {source}")

            metadata = parse_metadata(read_member(archive, metadata_member, source), source)
            expected = {
                "category": point.category,
                "width": str(point.width),
                "mass_GeV": str(point.mass),
                "signal": point.signal,
                "input_root_files": "5",
                "base_root": "area/base.root",
                "card": f"area/{point.signal}_area/card.txt",
            }
            for key, value in expected.items():
                if metadata.get(key) != value:
                    raise ValueError(
                        f"{source}: workspace.ok {key}={metadata.get(key)!r}, expected {value!r}"
                    )

            base = read_member(archive, base_member, source)
            config = read_member(archive, config_member, source)
            card = read_member(archive, card_member, source)
            if not base.startswith(b"root"):
                raise ValueError(f"{source}: base.root does not have ROOT magic bytes")
            try:
                json.loads(config.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError(f"{source}: invalid runConfig.json") from error
            if point.signal not in card.decode("utf-8", errors="strict"):
                raise ValueError(f"{source}: signal missing from card")

            checksums = {
                "base_sha256": hashlib.sha256(base).hexdigest(),
                "runConfig_sha256": hashlib.sha256(config).hexdigest(),
                "card_sha256": hashlib.sha256(card).hexdigest(),
            }
            for key, value in checksums.items():
                if metadata.get(key) != value:
                    raise ValueError(f"{source}: workspace.ok checksum mismatch for {key}")

            area_members = [member for member in members if member_name(member).startswith(f"{prefix}/area/")]
            if not area_members:
                raise ValueError(f"{source}: missing workspace area")
    except tarfile.TarError as error:
        raise ValueError(f"cannot read result archive {source}: {error}") from error

    return {
        "point": point,
        "source": source,
        "tar_sha256": sha256_file(source),
        "metadata": metadata,
        "members": area_members,
        "checksums": checksums,
    }


def archive_for_point(input_dir: Path, point: Point) -> Path:
    matches = sorted(input_dir.glob(f"{point.key}.tgz"))
    if len(matches) != 1:
        raise ValueError(f"expected exactly one archive for {point.key} in {input_dir}")
    return matches[0]


def extract_one(validated: dict[str, object], destination_root: Path) -> dict[str, object]:
    point = validated["point"]
    assert isinstance(point, Point)
    source = validated["source"]
    assert isinstance(source, Path)
    members = validated["members"]
    assert isinstance(members, list)
    destination = destination_root / point.area_name
    if destination.exists():
        raise ValueError(f"refusing to overwrite existing workspace: {destination}")

    temporary = Path(tempfile.mkdtemp(prefix=f".harvest-{point.key}-", dir=destination_root))
    try:
        staged_area = temporary / point.area_name
        with tarfile.open(source, "r:gz") as archive:
            for member in members:
                assert isinstance(member, tarfile.TarInfo)
                name = member_name(member)
                relative = PurePosixPath(name).relative_to("workspace_result/area")
                target = staged_area.joinpath(*relative.parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    payload = archive.extractfile(member)
                    if payload is None:
                        raise ValueError(f"cannot extract {name} from {source}")
                    with target.open("wb") as handle:
                        shutil.copyfileobj(payload, handle)
                else:
                    raise ValueError(f"unsupported archive member type: {name}")
        if destination.exists():
            raise ValueError(f"refusing to overwrite existing workspace: {destination}")
        os.rename(staged_area, destination)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)

    checksums = validated["checksums"]
    assert isinstance(checksums, dict)
    for filename, metadata_key in (("base.root", "base_sha256"), ("runConfig.json", "runConfig_sha256")):
        if sha256_file(destination / filename) != checksums[metadata_key]:
            raise RuntimeError(f"post-extraction checksum mismatch: {destination / filename}")
    card = destination / f"{point.signal}_area/card.txt"
    if sha256_file(card) != checksums["card_sha256"]:
        raise RuntimeError(f"post-extraction checksum mismatch: {card}")

    return {
        "category": point.category,
        "width": point.width,
        "mass_GeV": point.mass,
        "signal": point.signal,
        "source_tar": str(source),
        "source_tar_sha256": validated["tar_sha256"],
        "destination": str(destination),
        **checksums,
    }


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
    mode.add_argument("--matrix", type=Path, help="24-point matrix mode")
    mode.add_argument("--category", choices=("cen2425", "fwd2425"), help="one-point canary mode")
    parser.add_argument("--width", choices=("1", "10", "30"))
    parser.add_argument("--mass")
    parser.add_argument("--input", type=Path, action="append", help="result tarball in canary mode")
    parser.add_argument("--input-dir", type=Path, help="directory of <category>_w<width>_m<mass>.tgz in matrix mode")
    args = parser.parse_args()

    if args.matrix:
        if args.input or not args.input_dir or args.width or args.mass:
            parser.error("matrix mode requires only --matrix and --input-dir")
        points = load_matrix(args.matrix)
        archives = [(point, archive_for_point(args.input_dir, point)) for point in points]
    else:
        if not args.width or not args.mass or not args.input or args.input_dir:
            parser.error("canary mode requires --category --width --mass and one --input")
        if len(args.input) != 1:
            parser.error("canary mode accepts exactly one --input")
        point = parse_point(args.category, args.width, args.mass)
        points = [point]
        archives = [(point, args.input[0])]

    if len(set(point.key for point in points)) != len(points):
        raise ValueError("duplicate point requested")
    destination_root = args.campaign / "workspaces" / "percat"
    destination_root.mkdir(parents=True, exist_ok=True)
    for point in points:
        if (destination_root / point.area_name).exists():
            raise ValueError(f"refusing to overwrite existing workspace: {destination_root / point.area_name}")

    validated = [validate_archive(source, point) for point, source in archives]
    records = [extract_one(item, destination_root) for item in validated]
    write_ledger(args.ledger, records)
    print(json.dumps({"harvested": len(records), "ledger": str(args.ledger)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, RuntimeError) as error:
        print(f"HARVEST_PORTABLE_WORKSPACES_FAILED: {error}", file=sys.stderr)
        raise SystemExit(2)
