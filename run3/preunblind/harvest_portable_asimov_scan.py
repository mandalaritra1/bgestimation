#!/usr/bin/env python3
"""Fail-closed harvester for the single portable synthetic-Asimov scan archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile


PREFIX = "asimov_scan_result"
TOY = "higgsCombine_asimov.GenerateOnly.mH0.123456.root"
SCAN = "higgsCombine_asimov_scan.MultiDimFit.mH0.root"
REQUIRED_ROOTS = {TOY, SCAN}
REQUIRED_JSON = {"snapshot_validation.json", "asimov_scan_validation.json"}
EXPECTED_STATUS = {
    "exit_code": "0", "terminal_stage": "complete", "width": "1", "mass_GeV": "2000",
    "production_rMax": "1", "diagnostic_scan_rMax": "0.0847167987375",
    "rInject": "0.0169433597475", "grid_points": "41", "toy_seed": "123456",
    "dataset_scope": "synthetic_asimov_only", "pass_region_masks": "all_off_frozen",
}


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_name(member: tarfile.TarInfo) -> str:
    path = PurePosixPath(member.name)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe archive member: {member.name}")
    return path.as_posix().lstrip("./")


def member_bytes(archive: tarfile.TarFile, name: str) -> bytes:
    matches = [member for member in archive.getmembers() if safe_name(member) == name]
    if len(matches) != 1 or not matches[0].isfile():
        raise ValueError(f"expected one regular archive member: {name}")
    stream = archive.extractfile(matches[0])
    if stream is None:
        raise ValueError(f"cannot read archive member: {name}")
    payload = stream.read()
    if not payload:
        raise ValueError(f"empty archive member: {name}")
    return payload


def parse_key_value(payload: bytes, label: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in payload.decode("utf-8", errors="strict").splitlines():
        key, separator, value = raw.partition("=")
        if not separator or not key or key in result:
            raise ValueError(f"malformed {label} line: {raw!r}")
        result[key] = value
    return result


def validate_archive(source: Path) -> dict[str, object]:
    if not source.is_file() or source.stat().st_size == 0:
        raise ValueError(f"missing or empty archive: {source}")
    with tarfile.open(source, "r:gz") as archive:
        members = archive.getmembers()
        names = [safe_name(member) for member in members]
        if len(names) != len(set(names)) or any(member.issym() or member.islnk() for member in members):
            raise ValueError("duplicate or link archive member")
        if any(name != PREFIX and not name.startswith(f"{PREFIX}/") for name in names):
            raise ValueError("unexpected archive top-level member")
        if any("observed" in name.lower() or "data_obs" in name.lower() for name in names):
            raise ValueError("forbidden non-synthetic path in archive")
        area_prefix = f"{PREFIX}/area/"
        roots = {name.removeprefix(area_prefix) for name in names if name.startswith(area_prefix) and name.endswith(".root")}
        if roots != REQUIRED_ROOTS:
            raise ValueError(f"ROOT artifact set mismatch: {sorted(roots)}")
        for root_name in roots:
            if not member_bytes(archive, f"{area_prefix}{root_name}").startswith(b"root"):
                raise ValueError(f"ROOT magic mismatch: {root_name}")
        jsons = {name.removeprefix(area_prefix) for name in names if name.startswith(area_prefix) and name.endswith(".json")}
        if jsons != REQUIRED_JSON:
            raise ValueError(f"JSON artifact set mismatch: {sorted(jsons)}")
        status = parse_key_value(member_bytes(archive, f"{PREFIX}/status.txt"), "status")
        if set(status) != set(EXPECTED_STATUS) | {"snapshot_sha256", "payload_sha256", "runtime_sha256"}:
            raise ValueError("status key set mismatch")
        if any(status[key] != value for key, value in EXPECTED_STATUS.items()):
            raise ValueError("status contract mismatch")
        # sha256sum manifests use the digest as the first word, so normalize them separately.
        hash_lines = member_bytes(archive, f"{PREFIX}/artifact_hashes.sha256").decode("utf-8", errors="strict").splitlines()
        parsed_hashes: dict[str, str] = {}
        for line in hash_lines:
            digest, separator, relative = line.partition("  ")
            if not separator or len(digest) != 64 or relative in parsed_hashes:
                raise ValueError("malformed artifact hash manifest")
            parsed_hashes[relative] = digest
        area_files = {name.removeprefix(f"{PREFIX}/") for name in names if name.startswith(area_prefix) and name != area_prefix}
        area_files = {name for name in area_files if not name.endswith("/")}
        if set(parsed_hashes) != area_files:
            raise ValueError("artifact hash coverage mismatch")
        for relative, digest in parsed_hashes.items():
            if sha256_bytes(member_bytes(archive, f"{PREFIX}/{relative}")) != digest:
                raise ValueError(f"artifact hash mismatch: {relative}")
        snapshot = json.loads(member_bytes(archive, f"{area_prefix}snapshot_validation.json").decode("utf-8"))
        if snapshot.get("schema_version") != 1 or snapshot.get("snapshot_name") != "MultiDimFit":
            raise ValueError("snapshot validation schema mismatch")
        if snapshot.get("production_r_range") != [0.0, 1.0] or snapshot.get("required_masks") != [
            "mask_cen_Cen24Pass_Region1", "mask_cen_Cen25Pass_Region1",
            "mask_fwd_Fwd24Pass_Region1", "mask_fwd_Fwd25Pass_Region1",
        ]:
            raise ValueError("snapshot mask or production-range mismatch")
        if snapshot.get("rpf_count") != 18 or snapshot.get("positive_rpf_par0_count") != 4:
            raise ValueError("snapshot does not preserve final physical RPF ranges")
        if snapshot.get("snapshot_sha256") != status["snapshot_sha256"]:
            raise ValueError("snapshot hash mismatch")
        validation = json.loads(member_bytes(archive, f"{area_prefix}asimov_scan_validation.json").decode("utf-8"))
        expected_validation = {
            "method": "MultiDimFit_grid", "dataset_scope": "synthetic_asimov_only",
            "production_rMax": 1.0, "diagnostic_scan_rMax": 0.0847167987375,
            "grid_points": 41, "limit_tree_entries": 42, "scan_point_count": 41,
        }
        if any(validation.get(key) != value for key, value in expected_validation.items()):
            raise ValueError("scan validation contract mismatch")
        for key in ("deltaNLL_min", "deltaNLL_max"):
            value = validation.get(key)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"invalid {key}")
        return {"source": source, "source_sha256": sha256_file(source), "status": status,
                "scan_validation": validation, "artifact_hashes": parsed_hashes}


def extract_atomic(validated: dict[str, object], campaign: Path) -> Path:
    destination = campaign / "asimov_scans" / "w1" / "signalZPrime2000_area" / "rInject_0p0169433597475"
    if destination.exists():
        raise ValueError(f"refusing to overwrite harvest destination: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".asimov-scan-harvest-", dir=destination.parent))
    source = validated["source"]
    assert isinstance(source, Path)
    try:
        staged = temporary / destination.name
        staged.mkdir()
        with tarfile.open(source, "r:gz") as archive:
            for member in archive.getmembers():
                name = PurePosixPath(safe_name(member))
                if not member.isfile() or not str(name).startswith(f"{PREFIX}/area/"):
                    continue
                relative = name.relative_to(f"{PREFIX}/area")
                target = staged.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError(f"cannot extract {member.name}")
                with target.open("xb") as handle:
                    shutil.copyfileobj(stream, handle)
        staged.replace(destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--no-extract", action="store_true")
    args = parser.parse_args()
    validated = validate_archive(args.archive)
    destination = None if args.no_extract else extract_atomic(validated, args.campaign)
    print(json.dumps({"ASIMOV_SCAN_HARVEST_OK": True, "destination": str(destination) if destination else None,
                      "scan_sha256": validated["scan_validation"]["scan_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
