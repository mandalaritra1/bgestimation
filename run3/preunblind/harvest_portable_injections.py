#!/usr/bin/env python3
"""Fail-closed harvester for portable Asimov-injection result archives."""

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
from typing import Any


LABELS = {"bkg", "half", "one", "two"}
FIT_LINE = re.compile(r"^FIT CHECK: status=(\d+) covQual=(\d+) EDM=([^\s]+)$")
RANGE_LINE = "INJECTION RANGE CHECK: status=0 r_floating=1 masks_off_frozen=4 rpf_count=18 positive_par0=4"
HASH_LINE = re.compile(r"^([0-9a-f]{64})  (area/.+)$")


@dataclass(frozen=True)
class Injection:
    width: int
    mass: int
    rmax: str
    label: str
    injected: str
    start_zero: str
    start_injected: str
    third_start_label: str
    start_third: str

    @property
    def signal(self) -> str:
        suffix = "" if self.width == 1 else f"_{self.width}"
        return f"signalZPrime{self.mass}{suffix}"

    @property
    def key(self) -> str:
        return f"w{self.width}_m{self.mass}_{self.label}"

    @property
    def starts(self) -> dict[str, str]:
        return {
            "zero": self.start_zero,
            "injected": self.start_injected,
            self.third_start_label: self.start_third,
        }


def finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} is not numeric: {value!r}") from error
    if not math.isfinite(result):
        raise ValueError(f"{label} is not finite: {value!r}")
    return result


def parse_row(fields: list[str], third_start_label: str = "halfmax") -> Injection:
    if len(fields) != 8:
        raise ValueError(f"expected 8 injection columns, found {len(fields)}")
    width, mass, rmax, label, injected, start_zero, start_injected, start_third = fields
    width_int, mass_int = int(width), int(mass)
    if width_int not in {1, 10, 30} or mass_int <= 0 or label not in LABELS:
        raise ValueError(f"invalid injection row: {' '.join(fields)}")
    for name, value in (("rMax", rmax), ("injected", injected), ("start_zero", start_zero),
                        ("start_injected", start_injected),
                        (f"start_{third_start_label}", start_third)):
        finite(value, name)
    if third_start_label not in {"high", "halfmax"}:
        raise ValueError(f"unsupported third start label: {third_start_label}")
    return Injection(
        width_int, mass_int, rmax, label, injected, start_zero, start_injected,
        third_start_label, start_third,
    )


def load_matrix(path: Path, third_start_label: str = "halfmax") -> list[Injection]:
    rows = [parse_row(line.split(), third_start_label) for raw in path.read_text().splitlines()
            if (line := raw.strip()) and not line.startswith("#")]
    if len(rows) != 48 or len(set(rows)) != 48:
        raise ValueError(f"matrix must contain exactly 48 unique rows: {path}")
    by_point: dict[tuple[int, int], set[str]] = {}
    for row in rows:
        by_point.setdefault((row.width, row.mass), set()).add(row.label)
    if len(by_point) != 12 or any(labels != LABELS for labels in by_point.values()):
        raise ValueError("matrix is not exactly 12 points x 4 injections")
    return rows


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


def parse_status(raw: bytes, source: Path, third_start_label: str) -> dict[str, str]:
    expected = {"exit_code", "terminal_stage", "width", "mass_GeV", "rMax", "injection_label",
                "injected_r", "start_zero", "start_injected",
                f"start_{third_start_label}", "bootstrap_seed_policy", "final_nuisance_start",
                "payload_sha256", "runtime_sha256"}
    expected.add("fit_start_mode")
    values: dict[str, str] = {}
    for line in raw.decode("utf-8", errors="strict").splitlines():
        key, separator, value = line.partition("=")
        if not separator or key not in expected or key in values:
            raise ValueError(f"malformed or duplicate status line in {source}: {line!r}")
        values[key] = value
    if set(values) != expected:
        raise ValueError(f"status keys mismatch in {source}: {sorted(set(expected) - set(values))}")
    return values


def contains_observed_marker(value: Any) -> bool:
    if isinstance(value, str):
        lowered = value.lower()
        return "observed" in lowered or "data_obs" in lowered
    if isinstance(value, dict):
        return any(contains_observed_marker(key) or contains_observed_marker(item) for key, item in value.items())
    if isinstance(value, list):
        return any(contains_observed_marker(item) for item in value)
    return False


def validate_fit_json(
    payload: bytes,
    injection: Injection,
    start: str,
    source: Path,
    fit_key: str,
) -> dict[str, object]:
    try:
        record = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid fit_{start}.json in {source}") from error
    if contains_observed_marker(record):
        raise ValueError(f"observed-data marker in fit_{start}.json: {source}")
    if record.get("fit_key") != fit_key or not isinstance(record.get("metadata"), dict):
        raise ValueError(f"invalid fit schema for {start} in {source}")
    expected_metadata = {"width_percent": str(injection.width), "mass_GeV": str(injection.mass),
                         "rMax": injection.rmax, "injection_label": injection.label,
                         "injected_r": injection.injected, "start_label": start,
                         "start_r": injection.starts[start]}
    if record["metadata"] != expected_metadata:
        raise ValueError(f"fit metadata mismatch for {start} in {source}")
    fit = record.get("fit")
    if not isinstance(fit, dict) or set(fit) != {"status", "cov_qual", "edm", "min_nll"}:
        raise ValueError(f"invalid fit diagnostic schema for {start} in {source}")
    if fit["status"] != 0 or int(fit["cov_qual"]) < 3 or finite(fit["edm"], "EDM") > 0.01:
        raise ValueError(f"untrusted fit diagnostics for {start} in {source}")
    finite(fit["min_nll"], "minNll")
    r = record.get("r")
    if not isinstance(r, dict) or r.get("name") != "r" or r.get("constant") is not False:
        raise ValueError(f"r is missing or constant for {start} in {source}")
    if not math.isclose(finite(r.get("min"), "r.min"), 0.0, rel_tol=0, abs_tol=1e-12):
        raise ValueError(f"r minimum is not zero for {start} in {source}")
    if not math.isclose(finite(r.get("max"), "r.max"), float(injection.rmax), rel_tol=0, abs_tol=1e-12):
        raise ValueError(f"r maximum mismatch for {start} in {source}")
    r_value = finite(r.get("value"), "r.value")
    r_error = finite(r.get("error"), "r.error")
    if r_value < 0.0 or r_value > float(injection.rmax):
        raise ValueError(f"fitted r outside [0,rMax] for {start} in {source}")
    if r_error <= 0.0:
        raise ValueError(f"non-positive r error for {start} in {source}")
    parameters = record.get("floating_parameters")
    if not isinstance(parameters, list) or len([item for item in parameters if isinstance(item, dict) and item.get("name") == "r"]) != 1:
        raise ValueError(f"floating r record mismatch for {start} in {source}")
    return {"status": fit["status"], "cov_qual": fit["cov_qual"], "edm": fit["edm"],
            "min_nll": fit["min_nll"], "r": r["value"], "r_error": r["error"]}


def validate_archive(
    source: Path, injection: Injection, fit_method: str = "multidimfit"
) -> dict[str, object]:
    if not source.is_file() or source.stat().st_size == 0:
        raise ValueError(f"missing or empty archive: {source}")
    prefix = "injection_result"
    starts = tuple(injection.starts)
    required_roots = {f"{prefix}/area/higgsCombine_gen.GenerateOnly.mH0.123456.root"}
    if fit_method in {"multidimfit", "multidimfit_poionly", "multidimfit_poionly_robusthesse", "twostage", "robustinitial", "robustinitial_noexpect"}:
        fit_key = "fit_mdf"
        if fit_method == "twostage":
            fit_start_mode = "independent_fixed_r_bootstrap_then_physical_multidimfit"
        elif fit_method == "multidimfit_poionly_robusthesse":
            fit_start_mode = "snapshot_direct_requested_seed_multidimfit_poionly_robusthesse"
        elif fit_method == "multidimfit_poionly":
            fit_start_mode = "snapshot_direct_requested_seed_multidimfit_poionly_prefit"
        elif fit_method == "robustinitial_noexpect":
            fit_start_mode = "independent_requested_seed_robust_impacts_initialfit"
        elif fit_method == "robustinitial":
            fit_start_mode = "independent_robust_impacts_initialfit"
        else:
            fit_start_mode = "snapshot_direct_multidimfit_algo_none"
        if fit_method in {"robustinitial", "robustinitial_noexpect"}:
            fit_names = {
                start: f"injection_w{injection.width}_m{injection.mass}_{injection.label}_{start}"
                for start in starts
            }
            required_roots.update(
                f"{prefix}/area/multidimfit_initialFit_{fit_names[start]}.root"
                for start in starts
            )
            required_roots.update(
                f"{prefix}/area/higgsCombine_initialFit_{fit_names[start]}.MultiDimFit.mH0.root"
                for start in starts
            )
        else:
            required_roots.update(
                f"{prefix}/area/multidimfit_fit_{start}.root" for start in starts
            )
            required_roots.update(
                f"{prefix}/area/higgsCombine_fit_{start}.MultiDimFit.mH0.root"
                for start in starts
            )
        if fit_method == "twostage":
            required_roots.update(
                f"{prefix}/area/multidimfit_bootstrap_{start}.root"
                for start in starts
            )
            required_roots.update(
                f"{prefix}/area/higgsCombine_bootstrap_{start}.MultiDimFit.mH0.root"
                for start in starts
            )
    elif fit_method == "fitdiagnostics":
        fit_key = "fit_s"
        fit_start_mode = "snapshot_direct_no_prescan"
        required_roots.update(
            f"{prefix}/area/fitDiagnostics_fit_{start}.root" for start in starts
        )
        required_roots.update(
            f"{prefix}/area/higgsCombine_fit_{start}.FitDiagnostics.mH0.root"
            for start in starts
        )
    else:
        raise ValueError(f"unsupported fit method: {fit_method}")
    required_logs = {f"{prefix}/area/fit_{start}_validation.log" for start in starts}
    if fit_method == "twostage":
        required_logs.update(
            f"{prefix}/area/bootstrap_{start}_validation.log" for start in starts
        )
        required_logs.update(
            f"{prefix}/area/fit_{start}_range_validation.log" for start in starts
        )
    required_json = {f"{prefix}/area/fit_{start}.json" for start in starts}
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
            if any("observed" in name.lower() or "data_obs" in name.lower() for name in names):
                raise ValueError(f"observed-data path in {source}")
            root_members = {name for name in names if name.startswith(f"{prefix}/area/") and name.endswith(".root")}
            if root_members != required_roots:
                raise ValueError(f"ROOT artifact set mismatch in {source}: {sorted(root_members)}")
            for root_member in required_roots:
                if not member_bytes(archive, root_member, source).startswith(b"root"):
                    raise ValueError(f"ROOT magic mismatch for {root_member} in {source}")
            json_members = {name for name in names if name.startswith(f"{prefix}/area/") and name.endswith(".json")}
            if json_members != required_json:
                raise ValueError(f"JSON artifact set mismatch in {source}: {sorted(json_members)}")
            if not required_logs.issubset(names):
                raise ValueError(f"missing validator logs in {source}")

            status = parse_status(
                member_bytes(archive, f"{prefix}/status.txt", source),
                source,
                injection.third_start_label,
            )
            seed_policy = (
                "no_bootstrap_independent_per_start"
                if fit_method in {"robustinitial", "robustinitial_noexpect", "multidimfit_poionly", "multidimfit_poionly_robusthesse"}
                else "independent_per_start"
            )
            nuisance_start = (
                "physical_masked_snapshot_no_override"
                if fit_method in {"robustinitial", "robustinitial_noexpect", "multidimfit_poionly", "multidimfit_poionly_robusthesse"}
                else "matching_bootstrap_snapshot_no_override"
            )
            expected_status = {"exit_code": "0", "terminal_stage": "complete", "width": str(injection.width),
                               "mass_GeV": str(injection.mass), "rMax": injection.rmax,
                               "injection_label": injection.label, "injected_r": injection.injected,
                               "start_zero": injection.start_zero, "start_injected": injection.start_injected,
                               f"start_{injection.third_start_label}": injection.start_third,
                               "bootstrap_seed_policy": seed_policy,
                               "final_nuisance_start": nuisance_start,
                               "fit_start_mode": fit_start_mode}
            for key, value in expected_status.items():
                if status[key] != value:
                    raise ValueError(f"status {key} mismatch in {source}: {status[key]!r} != {value!r}")

            hash_payload = member_bytes(archive, f"{prefix}/artifact_hashes.sha256", source).decode("utf-8")
            hashes: dict[str, str] = {}
            for line in hash_payload.splitlines():
                match = HASH_LINE.match(line)
                if not match or match.group(2) in hashes:
                    raise ValueError(f"malformed or duplicate artifact hash in {source}: {line!r}")
                hashes[match.group(2)] = match.group(1)
            hashed_members = {name.removeprefix(f"{prefix}/") for name in names
                              if name.startswith(f"{prefix}/area/") and name.endswith((".root", ".log", ".json"))}
            if set(hashes) != hashed_members:
                raise ValueError(f"artifact hash coverage mismatch in {source}")
            for relative, digest in hashes.items():
                payload = member_bytes(archive, f"{prefix}/{relative}", source)
                if hashlib.sha256(payload).hexdigest() != digest:
                    raise ValueError(f"artifact hash mismatch for {relative} in {source}")

            fits: dict[str, object] = {}
            for start in starts:
                if fit_method == "twostage":
                    bootstrap_raw = member_bytes(
                        archive,
                        f"{prefix}/area/bootstrap_{start}_validation.log",
                        source,
                    )
                    bootstrap_matches = [
                        FIT_LINE.match(line)
                        for line in bootstrap_raw.decode("utf-8", errors="strict").splitlines()
                        if line.startswith("FIT CHECK:")
                    ]
                    bootstrap_matches = [match for match in bootstrap_matches if match]
                    if len(bootstrap_matches) != 1:
                        raise ValueError(
                            f"invalid bootstrap validator log for {start} in {source}"
                        )
                    status_value, cov_qual, edm = bootstrap_matches[0].groups()
                    if (
                        int(status_value) != 0
                        or int(cov_qual) < 3
                        or finite(edm, "bootstrap EDM") > 0.01
                    ):
                        raise ValueError(
                            f"failed bootstrap validator log for {start} in {source}"
                        )
                validation_raw = member_bytes(archive, f"{prefix}/area/fit_{start}_validation.log", source)
                lines = validation_raw.decode("utf-8", errors="strict").splitlines()
                matches = [FIT_LINE.match(line) for line in lines if line.startswith("FIT CHECK:")]
                matches = [match for match in matches if match]
                if len(matches) != 1:
                    raise ValueError(f"invalid validator log for {start} in {source}")
                status_value, cov_qual, edm = matches[0].groups()
                if int(status_value) != 0 or int(cov_qual) < 3 or finite(edm, "validator EDM") > 0.01:
                    raise ValueError(f"failed validator log for {start} in {source}")
                if fit_method == "twostage":
                    range_lines = member_bytes(
                        archive,
                        f"{prefix}/area/fit_{start}_range_validation.log",
                        source,
                    ).decode("utf-8", errors="strict").splitlines()
                    if range_lines != [RANGE_LINE]:
                        raise ValueError(f"invalid physical range log for {start} in {source}")
                fits[start] = validate_fit_json(
                    member_bytes(archive, f"{prefix}/area/fit_{start}.json", source),
                    injection,
                    start,
                    source,
                    fit_key,
                )
            area_members = [member for member in members if safe_name(member).startswith(f"{prefix}/area/")]
    except tarfile.TarError as error:
        raise ValueError(f"cannot read archive {source}: {error}") from error
    return {"injection": injection, "source": source, "tar_sha256": sha256_file(source),
            "status": status, "artifact_hashes": hashes, "fits": fits, "members": area_members}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def archive_for(directory: Path, injection: Injection) -> Path:
    path = directory / f"{injection.key}.tgz"
    if not path.is_file():
        raise ValueError(f"missing expected archive: {path}")
    return path


def extract_one(validated: dict[str, object], campaign: Path) -> dict[str, object]:
    injection, source, members = validated["injection"], validated["source"], validated["members"]
    assert isinstance(injection, Injection) and isinstance(source, Path) and isinstance(members, list)
    parent = campaign / "injections" / "asimov" / f"w{injection.width}" / f"m{injection.mass}"
    parent.mkdir(parents=True, exist_ok=True)
    destination = parent / injection.label
    if destination.exists():
        raise ValueError(f"refusing to overwrite injection area: {destination}")
    temporary = Path(tempfile.mkdtemp(prefix=f".harvest-{injection.key}-", dir=parent))
    try:
        staged = temporary / injection.label
        with tarfile.open(source, "r:gz") as archive:
            for member in members:
                assert isinstance(member, tarfile.TarInfo)
                relative = PurePosixPath(safe_name(member)).relative_to("injection_result/area")
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
                    raise ValueError(f"unsupported member type: {member.name}")
        if destination.exists():
            raise ValueError(f"refusing to overwrite injection area: {destination}")
        os.rename(staged, destination)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    return {"width": injection.width, "mass_GeV": injection.mass, "signal": injection.signal,
            "rMax": injection.rmax, "injection_label": injection.label, "injected_r": injection.injected,
            "source_tar": str(source), "source_tar_sha256": validated["tar_sha256"],
            "destination": str(destination), "artifact_hashes": validated["artifact_hashes"], "fits": validated["fits"]}


def write_ledger(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ValueError(f"refusing to overwrite ledger: {path}")
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump({"schema_version": 1, "records": records}, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.link(temporary, path)
    except FileExistsError as error:
        raise ValueError(f"refusing to overwrite ledger: {path}") from error
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument(
        "--third-start-label", choices=("high", "halfmax"), default="halfmax",
        help="Canonical validation uses halfmax; high is retained only for old diagnostics.",
    )
    parser.add_argument(
        "--fit-method", choices=("twostage", "robustinitial", "robustinitial_noexpect", "multidimfit", "multidimfit_poionly", "multidimfit_poionly_robusthesse", "fitdiagnostics"),
        default="twostage",
        help="robustinitial_noexpect is the canonical requested-seed recovery; older methods are diagnostic-only.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--matrix", type=Path)
    mode.add_argument("--row", nargs=8, metavar=("W", "M", "RMAX", "LABEL", "RINJ", "S0", "SI", "SH"))
    parser.add_argument("--input", type=Path)
    parser.add_argument("--input-dir", type=Path)
    args = parser.parse_args()
    if args.validate_only and args.ledger:
        parser.error("--validate-only does not write --ledger")
    if not args.validate_only and not args.ledger:
        parser.error("harvesting requires --ledger")
    if args.matrix:
        if args.input or not args.input_dir:
            parser.error("matrix mode requires --matrix and --input-dir")
        injections = load_matrix(args.matrix, args.third_start_label)
        expected_paths = {args.input_dir / f"{injection.key}.tgz" for injection in injections}
        actual_paths = set(args.input_dir.glob("*.tgz"))
        if actual_paths != expected_paths:
            raise ValueError(f"point archive set mismatch: missing={sorted(map(str, expected_paths-actual_paths))} extra={sorted(map(str, actual_paths-expected_paths))}")
        archives = [(injection, archive_for(args.input_dir, injection)) for injection in injections]
    else:
        if not args.input or args.input_dir:
            parser.error("canary mode requires --row and --input")
        injection = parse_row(list(args.row), args.third_start_label)
        injections, archives = [injection], [(injection, args.input)]
    validated = [
        validate_archive(source, injection, args.fit_method)
        for injection, source in archives
    ]
    if args.validate_only:
        print(json.dumps({"validated": len(validated), "mode": "validate-only"}, sort_keys=True))
        return 0
    assert args.ledger is not None
    if args.ledger.exists():
        raise ValueError(f"refusing to overwrite ledger: {args.ledger}")
    for item in validated:
        injection = item["injection"]
        assert isinstance(injection, Injection)
        destination = args.campaign / "injections" / "asimov" / f"w{injection.width}" / f"m{injection.mass}" / injection.label
        if destination.exists():
            raise ValueError(f"refusing to overwrite injection area: {destination}")
    records = [extract_one(item, args.campaign) for item in validated]
    write_ledger(args.ledger, records)
    print(json.dumps({"harvested": len(records), "ledger": str(args.ledger)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, RuntimeError) as error:
        print(f"HARVEST_PORTABLE_INJECTIONS_FAILED: {error}", file=sys.stderr)
        raise SystemExit(2)
