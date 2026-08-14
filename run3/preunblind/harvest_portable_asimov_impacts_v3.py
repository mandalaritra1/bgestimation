#!/usr/bin/env python3
"""Fail-closed harvester for the portable one-nuisance Asimov Impacts canary."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
PREFIX = "asimov_impacts_result"
NAME = "asimov_lumi24"
NUISANCE = "lumi24"
FIT_LINE = re.compile(r"^FIT CHECK: status=(\d+) covQual=(\d+) EDM=([^\s]+)$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
TEXT_MARKER_EXEMPTIONS = {"area/runtime_preflight.log"}


def load_validator():
    path = HERE / "validate_portable_asimov_impacts.py"
    spec = importlib.util.spec_from_file_location("validate_portable_asimov_impacts", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"cannot load impacts validator: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def member_bytes(archive: tarfile.TarFile, members: dict[str, tarfile.TarInfo], name: str) -> bytes:
    member = members.get(name)
    if not member or not member.isfile():
        raise ValueError(f"expected one regular archive member: {name}")
    stream = archive.extractfile(member)
    if stream is None:
        raise ValueError(f"cannot read archive member: {name}")
    payload = stream.read()
    if not payload:
        raise ValueError(f"empty archive member: {name}")
    return payload


def parse_status(payload: bytes) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in payload.decode("utf-8", errors="strict").splitlines():
        key, separator, value = raw.partition("=")
        if not separator or not key or key in values:
            raise ValueError(f"malformed or duplicate status line: {raw!r}")
        values[key] = value
    return values


def parse_hashes(payload: bytes) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in payload.decode("utf-8", errors="strict").splitlines():
        digest, separator, path = raw.partition("  ")
        if not separator or not SHA256.fullmatch(digest) or path in result or not path.startswith("area/"):
            raise ValueError(f"malformed artifact hash line: {raw!r}")
        result[path] = digest
    return result


def require_fit_log(payload: bytes, label: str) -> dict[str, object]:
    lines = payload.decode("utf-8", errors="strict").splitlines()
    matches = [FIT_LINE.match(line) for line in lines if line.startswith("FIT CHECK:")]
    matches = [match for match in matches if match]
    if len(matches) != 1:
        raise ValueError(f"{label} fit validation log does not contain exactly one fit check")
    status, covariance, edm = matches[0].groups()
    edm_value = float(edm)
    if int(status) != 0 or int(covariance) < 3 or not math.isfinite(edm_value) or edm_value > 0.01:
        raise ValueError(f"{label} fit quality gate failed")
    return {"status": int(status), "cov_qual": int(covariance), "edm": edm_value}


def validate_archive(source: Path) -> dict[str, Any]:
    if not source.is_file() or source.stat().st_size == 0:
        raise ValueError(f"missing or empty impacts archive: {source}")
    initial_root = f"area/higgsCombine_initialFit_{NAME}.MultiDimFit.mH0.root"
    parameter_root = f"area/higgsCombine_paramFit_{NAME}_{NUISANCE}.MultiDimFit.mH0.root"
    initial_fit = f"area/multidimfit_initialFit_{NAME}.root"
    area_files = {
        "area/runtime_setup.log", "area/runtime_preflight.log", "area/combine_logger.out",
        "area/snapshot_validation.log", "area/snapshot_validation.json",
        "area/initial_fit.log", "area/initial_fit_validation.log", "area/named_nuisance_fit.log",
        "area/named_fit_validation.log", "area/named_fit_validation.json",
        "area/collect_impacts.log", "area/impacts_validation.log",
        "area/impacts_lumi24.json", "area/impacts_validation.json",
        initial_root, parameter_root, initial_fit,
    }
    expected_files = {f"{PREFIX}/status.txt", f"{PREFIX}/artifact_hashes.sha256"}
    expected_files.update(f"{PREFIX}/{name}" for name in area_files)
    with tarfile.open(source, "r:gz") as archive:
        raw_members = archive.getmembers()
        names = [safe_name(member) for member in raw_members]
        if len(names) != len(set(names)) or any(not (member.isfile() or member.isdir()) for member in raw_members):
            raise ValueError("duplicate or unsupported archive member")
        allowed_directories = {PREFIX, f"{PREFIX}/area"}
        directories = {safe_name(member) for member in raw_members if member.isdir()}
        if not directories.issubset(allowed_directories):
            raise ValueError(f"unexpected archive directories: {sorted(directories)}")
        members = {safe_name(member): member for member in raw_members if member.isfile()}
        if set(members) != expected_files:
            raise ValueError(f"unexpected archive file set; missing={sorted(expected_files - set(members))} extra={sorted(set(members) - expected_files)}")
        if any("observed" in name.lower() or "data_obs" in name.lower() for name in names):
            raise ValueError("forbidden non-synthetic archive path")
        payloads = {name: member_bytes(archive, members, name) for name in expected_files}

    status = parse_status(payloads[f"{PREFIX}/status.txt"])
    expected_status = {
        "exit_code": "0", "terminal_stage": "complete", "width": "1", "mass_GeV": "2000",
        "production_rMax": "1", "rInject": "0.0169433597475", "named_nuisance": NUISANCE,
        "named_fit_quality": "not_available_in_impact_mode",
        "toy_seed": "123456", "dataset_scope": "synthetic_asimov_only",
        "pass_region_masks": "all_off_frozen",
    }
    if set(status) != set(expected_status) | {"snapshot_sha256", "payload_sha256", "runtime_sha256"}:
        raise ValueError("status key set mismatch")
    if any(status[key] != value for key, value in expected_status.items()):
        raise ValueError("status contract mismatch")
    if any(not SHA256.fullmatch(status[key]) for key in ("snapshot_sha256", "payload_sha256", "runtime_sha256")):
        raise ValueError("invalid provenance SHA-256")

    hashes = parse_hashes(payloads[f"{PREFIX}/artifact_hashes.sha256"])
    if set(hashes) != area_files:
        raise ValueError("artifact checksum manifest does not exactly cover area files")
    for relative, digest in hashes.items():
        if sha256_bytes(payloads[f"{PREFIX}/{relative}"]) != digest:
            raise ValueError(f"artifact checksum mismatch: {relative}")
    for root in (initial_root, parameter_root, initial_fit):
        if not payloads[f"{PREFIX}/{root}"].startswith(b"root"):
            raise ValueError(f"ROOT magic mismatch: {root}")
    # The runtime preflight captures ``combine --help`` and ``combineTool.py
    # --help``.  Those upstream help pages describe the default ``data_obs``
    # dataset and observed-limit modes even though the worker never invokes
    # either one.  Keep the path-level ban above and scan every executed-command
    # log and machine-readable artifact, but do not mistake static tool help for
    # evidence that observed data were accessed.
    text = b"\n".join(
        payload
        for name, payload in payloads.items()
        if name.endswith((".log", ".json", ".txt", ".sha256"))
        and PurePosixPath(name).relative_to(PREFIX).as_posix()
        not in TEXT_MARKER_EXEMPTIONS
    ).decode("utf-8", errors="strict")
    if "observed" in text.lower() or "data_obs" in text.lower():
        raise ValueError("forbidden non-synthetic marker in impacts artifacts")
    if "Minimization success! status=0" not in payloads[f"{PREFIX}/area/combine_logger.out"].decode("utf-8", errors="strict"):
        raise ValueError("Combine logger does not record status-0 minimization success")

    initial_quality = require_fit_log(payloads[f"{PREFIX}/area/initial_fit_validation.log"], "initial")
    named_fit_validation = json.loads(
        payloads[f"{PREFIX}/area/named_fit_validation.json"]
    )
    named_records = named_fit_validation.get("records")
    if (
        named_fit_validation.get("schema_version") != 1
        or named_fit_validation.get("dataset_scope") != "synthetic_asimov_only"
        or named_fit_validation.get("named_nuisance") != NUISANCE
        or named_fit_validation.get("tree_entries") != 3
        or named_fit_validation.get("required_branches") != ["deltaNLL", "lumi24", "r"]
        or named_fit_validation.get("root_sha256")
        != sha256_bytes(payloads[f"{PREFIX}/{parameter_root}"])
        or not isinstance(named_records, list)
        or len(named_records) != 3
    ):
        raise ValueError("named-nuisance ROOT validation contract mismatch")
    for record in named_records:
        if not isinstance(record, dict) or set(record) != {"r", NUISANCE, "deltaNLL"}:
            raise ValueError("malformed named-nuisance ROOT validation record")
        values = [record["r"], record[NUISANCE], record["deltaNLL"]]
        if any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in values):
            raise ValueError("non-finite named-nuisance ROOT validation record")
        if not 0.0 <= float(record["r"]) <= 1.0 or float(record["deltaNLL"]) < -1.0e-6:
            raise ValueError("unphysical named-nuisance ROOT validation record")
    snapshot = json.loads(payloads[f"{PREFIX}/area/snapshot_validation.json"])
    if snapshot.get("r_range") != [0.0, 1.0] or snapshot.get("model_nuisances") != ["lumi24", "lumi25", "ttbar_xsec"]:
        raise ValueError("snapshot production range or nuisance contract mismatch")
    if snapshot.get("rpf_count") != 18 or snapshot.get("positive_rpf_par0_count") != 4:
        raise ValueError("snapshot physical RPF range contract mismatch")
    if snapshot.get("snapshot_sha256") != status["snapshot_sha256"]:
        raise ValueError("snapshot hash mismatch")
    raw_impacts = json.loads(payloads[f"{PREFIX}/area/impacts_lumi24.json"])
    validation = load_validator().validate_impacts_payload(raw_impacts, NUISANCE)
    saved_validation = json.loads(payloads[f"{PREFIX}/area/impacts_validation.json"])
    if saved_validation != validation:
        raise ValueError("saved impacts validation JSON does not match strict validation")
    return {
        "source": source, "source_sha256": sha256_file(source), "status": status,
        "artifact_hashes": hashes, "initial_fit": initial_quality,
        "named_fit_quality": named_fit_validation,
        "impacts": validation,
    }


def extract_atomic(validated: dict[str, Any], campaign: Path) -> Path:
    destination = campaign / "asimov_impacts" / "w1" / "signalZPrime2000_area" / "lumi24_rInject_0p0169433597475"
    if destination.exists():
        raise ValueError(f"refusing to overwrite impacts destination: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".asimov-impacts-harvest-", dir=destination.parent))
    source = validated["source"]
    assert isinstance(source, Path)
    try:
        staged = temporary / destination.name
        staged.mkdir()
        with tarfile.open(source, "r:gz") as archive:
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                name = PurePosixPath(safe_name(member))
                if not str(name).startswith(f"{PREFIX}/area/"):
                    continue
                relative = name.relative_to(f"{PREFIX}/area")
                target = staged.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError(f"cannot extract archive member: {member.name}")
                with target.open("xb") as handle:
                    shutil.copyfileobj(stream, handle)
        os.rename(staged, destination)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--no-extract", action="store_true")
    args = parser.parse_args()
    validated = validate_archive(args.archive)
    destination = None if args.no_extract else extract_atomic(validated, args.campaign)
    print(json.dumps({"ASIMOV_IMPACTS_HARVEST_OK": True,
                      "destination": str(destination) if destination else None,
                      "impact_r": validated["impacts"]["impact_r"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
