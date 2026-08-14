#!/usr/bin/env python3
"""Fail-closed validator for one portable synthetic-Asimov fixed-r archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import tarfile


PREFIX = "asimov_fixedpoint_result"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
AREA_FILES = {
    "runtime_setup.log", "runtime_preflight.log", "snapshot_validation.log",
    "snapshot_validation.json", "generate_asimov.log",
    "higgsCombine_asimov.GenerateOnly.mH0.123456.root", "fixedpoint.log",
    "fixedpoint_validation.log", "fixedpoint_validation.json",
}


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def safe_name(member: tarfile.TarInfo) -> str:
    path = PurePosixPath(member.name)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe archive member: {member.name}")
    return path.as_posix().lstrip("./")


def read_member(archive: tarfile.TarFile, members: dict[str, tarfile.TarInfo], name: str) -> bytes:
    member = members.get(name)
    if not member or not member.isfile():
        raise ValueError(f"missing regular archive member: {name}")
    stream = archive.extractfile(member)
    if stream is None:
        raise ValueError(f"cannot read archive member: {name}")
    payload = stream.read()
    if not payload:
        raise ValueError(f"empty archive member: {name}")
    return payload


def key_values(payload: bytes) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in payload.decode("utf-8", errors="strict").splitlines():
        key, separator, value = line.partition("=")
        if not separator or not key or key in result:
            raise ValueError(f"malformed status line: {line!r}")
        result[key] = value
    return result


def validate(source: Path, point_index: str, target_r: float) -> dict[str, object]:
    if not source.is_file() or source.stat().st_size == 0:
        raise ValueError(f"missing or empty archive: {source}")
    fixed_root = f"higgsCombine_fixedpoint_{point_index}.MultiDimFit.mH0.root"
    expected_area = set(AREA_FILES) | {fixed_root}
    with tarfile.open(source, "r:gz") as archive:
        raw = archive.getmembers()
        names = [safe_name(member) for member in raw]
        if len(names) != len(set(names)) or any(member.issym() or member.islnk() for member in raw):
            raise ValueError("duplicate or link archive member")
        members = {safe_name(member): member for member in raw if member.isfile()}
        expected = {f"{PREFIX}/status.txt", f"{PREFIX}/artifact_hashes.sha256"}
        expected.update(f"{PREFIX}/area/{name}" for name in expected_area)
        if set(members) != expected:
            raise ValueError(f"archive file set mismatch; missing={sorted(expected-set(members))} extra={sorted(set(members)-expected)}")
        payloads = {name: read_member(archive, members, name) for name in expected}
    status = key_values(payloads[f"{PREFIX}/status.txt"])
    expected_status = {
        "exit_code": "0", "terminal_stage": "complete", "width": "1", "mass_GeV": "2000",
        "production_rMax": "1", "diagnostic_scan_rMax": "0.0847167987375",
        "rInject": "0.0169433597475", "point_index": point_index,
        "toy_seed": "123456",
        "dataset_scope": "synthetic_asimov_only", "pass_region_masks": "all_off_frozen",
        "fit_method": "independent_fixed_point_robust",
    }
    if set(status) != set(expected_status) | {
        "target_r", "snapshot_sha256", "payload_sha256", "runtime_sha256"
    }:
        raise ValueError("status key set mismatch")
    if any(status.get(key) != value for key, value in expected_status.items()):
        raise ValueError("status contract mismatch")
    if not math.isclose(float(status.get("target_r", "nan")), target_r, abs_tol=1e-12):
        raise ValueError("status target-r mismatch")
    for key in ("snapshot_sha256", "payload_sha256", "runtime_sha256"):
        if not SHA256.fullmatch(status.get(key, "")):
            raise ValueError(f"invalid status hash: {key}")
    hashes: dict[str, str] = {}
    for line in payloads[f"{PREFIX}/artifact_hashes.sha256"].decode().splitlines():
        value, separator, relative = line.partition("  ")
        if not separator or not SHA256.fullmatch(value) or relative in hashes:
            raise ValueError("malformed artifact hash manifest")
        hashes[relative] = value
    if set(hashes) != {f"area/{name}" for name in expected_area}:
        raise ValueError("artifact hash coverage mismatch")
    for relative, value in hashes.items():
        if digest(payloads[f"{PREFIX}/{relative}"]) != value:
            raise ValueError(f"artifact hash mismatch: {relative}")
    for root_name in ("higgsCombine_asimov.GenerateOnly.mH0.123456.root", fixed_root):
        if not payloads[f"{PREFIX}/area/{root_name}"].startswith(b"root"):
            raise ValueError(f"ROOT magic mismatch: {root_name}")
    for name in expected_area:
        if name == "runtime_preflight.log" or not name.endswith((".log", ".json")):
            continue
        text = payloads[f"{PREFIX}/area/{name}"].decode("utf-8", errors="ignore").lower()
        if "data_obs" in text or "observed" in text:
            raise ValueError(f"forbidden non-synthetic marker in {name}")
    validation = json.loads(payloads[f"{PREFIX}/area/fixedpoint_validation.json"])
    if validation.get("method") != "MultiDimFit_fixed_independent" or validation.get("dataset_scope") != "synthetic_asimov_only":
        raise ValueError("fixed-point validation schema mismatch")
    if not math.isclose(float(validation.get("target_r")), target_r, abs_tol=1e-12):
        raise ValueError("fixed-point validation target mismatch")
    fixed = validation.get("fixed_entry", {})
    if not math.isclose(float(fixed.get("r")), target_r, abs_tol=1e-9):
        raise ValueError("fixed-point result r mismatch")
    delta = float(fixed.get("deltaNLL"))
    if not math.isfinite(delta) or delta < 0 or delta >= 1000:
        raise ValueError("invalid fixed-point deltaNLL")
    return {"source_sha256": digest(source.read_bytes()), "validation": validation, "status": status}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--point-index", required=True)
    parser.add_argument("--target-r", type=float, required=True)
    args = parser.parse_args()
    validated = validate(args.archive, args.point_index, args.target_r)
    print(json.dumps({"ASIMOV_FIXEDPOINT_HARVEST_OK": True, **validated}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"ASIMOV_FIXEDPOINT_HARVEST_FAILED: {error}")
        raise SystemExit(2)
