#!/usr/bin/env python3
"""Fail-closed harvester for one portable masked saturated-GoF archive."""

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


MASK_NAMES = (
    "mask_cen_Cen24Pass_Region1",
    "mask_cen_Cen25Pass_Region1",
    "mask_fwd_Fwd24Pass_Region1",
    "mask_fwd_Fwd25Pass_Region1",
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")
MASK_OFF = re.compile(r"mask_(?:cen|fwd)_[A-Za-z0-9_]*Pass_Region1\s*=\s*0")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_name(member: tarfile.TarInfo) -> str:
    name = PurePosixPath(member.name)
    if name.is_absolute() or ".." in name.parts:
        raise ValueError(f"unsafe archive member: {member.name}")
    return name.as_posix().lstrip("./")


def member_payload(archive: tarfile.TarFile, members: dict[str, tarfile.TarInfo], name: str) -> bytes:
    member = members.get(name)
    if member is None or not member.isfile():
        raise ValueError(f"expected one regular archive member: {name}")
    stream = archive.extractfile(member)
    if stream is None:
        raise ValueError(f"cannot read archive member: {name}")
    return stream.read()


def parse_key_values(payload: bytes) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in payload.decode("utf-8", errors="strict").splitlines():
        key, separator, value = raw_line.partition("=")
        if not separator or not key or key in values:
            raise ValueError(f"malformed or duplicate status line: {raw_line!r}")
        values[key] = value
    return values


def parse_hashes(payload: bytes) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for raw_line in payload.decode("utf-8", errors="strict").splitlines():
        columns = raw_line.split(None, 1)
        if len(columns) != 2 or not SHA256.fullmatch(columns[0]):
            raise ValueError(f"malformed artifact hash line: {raw_line!r}")
        name = columns[1].lstrip("*")
        if name in hashes or not name.startswith("area/") or ".." in PurePosixPath(name).parts:
            raise ValueError(f"unsafe or duplicate artifact hash path: {name}")
        hashes[name] = columns[0]
    return hashes


def validate_archive(source: Path, toy_seed: int, toy_count: int) -> dict[str, object]:
    if not source.is_file() or source.stat().st_size == 0:
        raise ValueError(f"missing or empty GoF result archive: {source}")
    toy_root = f"area/higgsCombine_gof_masked_toys.GoodnessOfFit.mH0.{toy_seed}.root"
    data_root = "area/higgsCombine_gof_masked_data.GoodnessOfFit.mH0.root"
    area_files = {
        "area/runtime_setup.log",
        "area/runtime_preflight.log",
        # Combine writes its minimizer summary here even when stdout is
        # redirected.  It is an expected, checksummed diagnostic artifact.
        "area/combine_logger.out",
        "area/snapshot_validation.log",
        "area/snapshot_validation.json",
        "area/gof_data.log",
        "area/gof_toys.log",
        "area/gof_validation.log",
        "area/gof_validation.json",
        data_root,
        toy_root,
    }
    expected_files = {"gof_result/status.txt", "gof_result/artifact_hashes.sha256"}
    expected_files.update(f"gof_result/{name}" for name in area_files)
    with tarfile.open(source, "r:gz") as archive:
        raw_members = archive.getmembers()
        names = [safe_name(member) for member in raw_members]
        if len(names) != len(set(names)):
            raise ValueError("duplicate archive member")
        if any(not (member.isfile() or member.isdir()) for member in raw_members):
            raise ValueError("only regular files and directories are allowed")
        allowed_directories = {"gof_result", "gof_result/area"}
        archive_directories = {safe_name(member) for member in raw_members if member.isdir()}
        if not archive_directories.issubset(allowed_directories):
            raise ValueError(f"unexpected archive directories: {sorted(archive_directories)}")
        members = {safe_name(member): member for member in raw_members if member.isfile()}
        if set(members) != expected_files:
            missing = sorted(expected_files.difference(members))
            extra = sorted(set(members).difference(expected_files))
            raise ValueError(f"unexpected GoF archive file set; missing={missing} extra={extra}")
        if any(
            token in name
            for name in names
            for token in ("FitDiagnostics", "AsymptoticLimits", "MultiDimFit", "GenerateOnly")
        ):
            raise ValueError("forbidden fit/limit output in GoF archive")

        payloads = {name: member_payload(archive, members, name) for name in expected_files}

    status = parse_key_values(payloads["gof_result/status.txt"])
    expected_status = {
        "exit_code": "0",
        "terminal_stage": "complete",
        "width": "1",
        "mass_GeV": "2000",
        "signal": "signalZPrime2000",
        "rMax": "1",
        "algorithm": "saturated",
        "data_scope": "observed_sideband_only",
        "pass_region_masks": "all_on_frozen",
        "r_state": "fixed_zero",
        "toy_seed": str(toy_seed),
        "toy_count": str(toy_count),
    }
    if set(status) != set(expected_status).union({"snapshot_sha256", "payload_sha256", "runtime_sha256"}):
        raise ValueError(f"unexpected status keys: {sorted(status)}")
    for key, expected in expected_status.items():
        if status[key] != expected:
            raise ValueError(f"status {key}={status[key]!r}, expected {expected!r}")
    for key in ("snapshot_sha256", "payload_sha256", "runtime_sha256"):
        if not SHA256.fullmatch(status[key]):
            raise ValueError(f"invalid {key} in status")

    hashes = parse_hashes(payloads["gof_result/artifact_hashes.sha256"])
    if set(hashes) != area_files:
        raise ValueError("artifact hash manifest does not exactly cover area files")
    for name in area_files:
        archive_name = f"gof_result/{name}"
        if sha256_bytes(payloads[archive_name]) != hashes[name]:
            raise ValueError(f"artifact checksum mismatch: {name}")

    for root_name in (data_root, toy_root):
        payload = payloads[f"gof_result/{root_name}"]
        if len(payload) <= 4 or not payload.startswith(b"root"):
            raise ValueError(f"missing ROOT magic or empty output: {root_name}")

    text_payload = b"\n".join(
        payload
        for name, payload in payloads.items()
        if name.endswith((".txt", ".log", ".json", ".sha256"))
    ).decode("utf-8", errors="strict")
    if "unmask" in text_payload.lower() or "observed_pass" in text_payload.lower() or MASK_OFF.search(text_payload):
        raise ValueError("unmasked observed-pass marker found in GoF archive")
    combine_logger = payloads["gof_result/area/combine_logger.out"].decode(
        "utf-8", errors="strict"
    )
    if "Minimization success! status=0" not in combine_logger:
        raise ValueError("Combine minimizer logger does not record status-0 success")

    snapshot = json.loads(payloads["gof_result/area/snapshot_validation.json"])
    if snapshot.get("schema_version") != 1 or snapshot.get("snapshot_name") != "MultiDimFit":
        raise ValueError("invalid snapshot-validation schema")
    if snapshot.get("r_range") != [0.0, 1.0]:
        raise ValueError(f"unexpected snapshot r range: {snapshot.get('r_range')}")
    if snapshot.get("required_masks") != list(MASK_NAMES):
        raise ValueError("snapshot validation does not contain the four exact masks")
    if snapshot.get("rpf_count") != 18 or snapshot.get("positive_rpf_par0_count") != 4:
        raise ValueError("snapshot does not preserve final physical RPF ranges")
    if snapshot.get("snapshot_sha256") != status["snapshot_sha256"]:
        raise ValueError("snapshot hash mismatch between validation and status")

    result = json.loads(payloads["gof_result/area/gof_validation.json"])
    result_contract = {
        "schema_version": 1,
        "algorithm": "saturated",
        "data_scope": "observed_sideband_only",
        "pass_region_masks": "all_on_frozen",
        "r_state": "fixed_zero",
        "toy_seed": toy_seed,
        "toy_count": toy_count,
    }
    for key, expected in result_contract.items():
        if result.get(key) != expected:
            raise ValueError(f"GoF JSON {key}={result.get(key)!r}, expected {expected!r}")
    observed = result.get("observed_statistic")
    toys = result.get("toy_statistics")
    if not isinstance(observed, (int, float)) or not math.isfinite(observed) or observed < 0:
        raise ValueError("invalid observed sideband statistic")
    if not isinstance(toys, list) or len(toys) != toy_count:
        raise ValueError("wrong number of toy statistics")
    if any(not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 for value in toys):
        raise ValueError("invalid toy statistic")

    return {
        "source": source,
        "source_sha256": sha256_file(source),
        "members": raw_members,
        "status": status,
        "artifact_hashes": hashes,
        "observed_statistic": float(observed),
        "toy_statistics": [float(value) for value in toys],
    }


def extract_atomic(validated: dict[str, object], campaign: Path, toy_seed: int, toy_count: int) -> Path:
    destination = (
        campaign / "gof" / "masked" / "w1" / "signalZPrime2000_area"
        / f"seed{toy_seed}_n{toy_count}"
    )
    if destination.exists():
        raise ValueError(f"refusing to overwrite GoF destination: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".gof-harvest-", dir=destination.parent))
    source = validated["source"]
    assert isinstance(source, Path)
    try:
        staged = temporary / destination.name
        staged.mkdir()
        with tarfile.open(source, "r:gz") as archive:
            for member in archive.getmembers():
                name = PurePosixPath(safe_name(member))
                if member.isdir():
                    continue
                relative = name.relative_to("gof_result")
                target = staged.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError(f"cannot extract {member.name}")
                with target.open("xb") as handle:
                    shutil.copyfileobj(stream, handle)
        os.rename(staged, destination)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    return destination


def write_ledger(path: Path, record: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ValueError(f"refusing to overwrite GoF ledger: {path}")
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump({"schema_version": 1, "records": [record]}, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.link(temporary, path)
    except FileExistsError as error:
        raise ValueError(f"refusing to overwrite GoF ledger: {path}") from error
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--toy-seed", type=int, default=314159)
    parser.add_argument("--toy-count", type=int, default=5)
    args = parser.parse_args()
    if args.toy_seed <= 0 or args.toy_count <= 0 or args.toy_count > 200:
        raise ValueError("toy seed/count must be positive and toy count <=200")
    validated = validate_archive(args.input, args.toy_seed, args.toy_count)
    destination = extract_atomic(validated, args.campaign, args.toy_seed, args.toy_count)
    status = validated["status"]
    hashes = validated["artifact_hashes"]
    assert isinstance(status, dict) and isinstance(hashes, dict)
    record = {
        "width": 1,
        "mass_GeV": 2000,
        "signal": "signalZPrime2000",
        "rMax": "1",
        "algorithm": "saturated",
        "data_scope": "observed_sideband_only",
        "pass_region_masks": "all_on_frozen",
        "r_state": "fixed_zero",
        "toy_seed": args.toy_seed,
        "toy_count": args.toy_count,
        "observed_statistic": validated["observed_statistic"],
        "toy_statistics": validated["toy_statistics"],
        "source_tar": str(args.input),
        "source_tar_sha256": validated["source_sha256"],
        "snapshot_sha256": status["snapshot_sha256"],
        "payload_sha256": status["payload_sha256"],
        "runtime_sha256": status["runtime_sha256"],
        "artifact_hashes": hashes,
        "destination": str(destination),
    }
    write_ledger(args.ledger, record)
    print(json.dumps({"harvested": 1, "destination": str(destination), "ledger": str(args.ledger)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (json.JSONDecodeError, OSError, tarfile.TarError, ValueError) as error:
        print(f"HARVEST_PORTABLE_GOF_FAILED: {error}", file=sys.stderr)
        raise SystemExit(2)
