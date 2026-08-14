#!/usr/bin/env python3
"""Fail-closed harvester for the sanitized masked-sideband postfit canary."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import tempfile
from typing import Any


PREFIX = "masked_postfit_result"
AREA_FILES = {
    "runtime_setup.log",
    "runtime_preflight.log",
    "snapshot_validation.log",
    "snapshot_validation.json",
    "masked_postfit_fit.log",
    "masked_postfit_fit_validation.log",
    "sanitize.log",
    "masked_postfit_safe.root",
    "masked_postfit_safe.json",
}
SHA256 = re.compile(r"^[0-9a-f]{64}$")
FIT_LINE = re.compile(r"^FIT CHECK: status=(\d+) covQual=(\d+) EDM=([^\s]+)$")


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


def member_bytes(archive: tarfile.TarFile, members: dict[str, tarfile.TarInfo], name: str) -> bytes:
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


def parse_hashes(payload: bytes) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in payload.decode("utf-8", errors="strict").splitlines():
        digest, separator, path = line.partition("  ")
        if not separator or not SHA256.fullmatch(digest) or path in result:
            raise ValueError(f"malformed artifact hash: {line!r}")
        result[path] = digest
    return result


def validate_safe_root(payload: bytes, allowed: set[str], denied: set[str]) -> None:
    try:
        import ROOT
    except ImportError as error:
        raise ValueError("PyROOT is required to validate safe postfit ROOT") from error
    ROOT.gROOT.SetBatch(True)
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "masked_postfit_safe.root"
        path.write_bytes(payload)
        root_file = ROOT.TFile.Open(str(path))
        if not root_file or root_file.IsZombie():
            raise ValueError("cannot open sanitized postfit ROOT")
        try:
            top = {key.GetName() for key in root_file.GetListOfKeys()}
            if top != {"shapes_fit_b"}:
                raise ValueError(f"unexpected safe ROOT top-level keys: {sorted(top)}")
            for shape_set in top:
                directory = root_file.Get(shape_set)
                channels = {key.GetName() for key in directory.GetListOfKeys()}
                if channels != allowed or channels.intersection(denied):
                    raise ValueError(f"unsafe channel set in {shape_set}")
                for channel in channels:
                    names = {key.GetName() for key in directory.Get(channel).GetListOfKeys()}
                    required = {"total", "data"}
                    if not required.issubset(names):
                        raise ValueError(f"safe ROOT lacks required objects in {shape_set}/{channel}")
        finally:
            root_file.Close()


def validate_archive(source: Path) -> dict[str, Any]:
    if not source.is_file() or source.stat().st_size == 0:
        raise ValueError(f"missing or empty masked-postfit archive: {source}")
    expected = {f"{PREFIX}/status.txt", f"{PREFIX}/artifact_hashes.sha256"}
    expected.update(f"{PREFIX}/area/{name}" for name in AREA_FILES)
    with tarfile.open(source, "r:gz") as archive:
        raw_members = archive.getmembers()
        names = [safe_name(member) for member in raw_members]
        if len(names) != len(set(names)) or any(not (member.isfile() or member.isdir()) for member in raw_members):
            raise ValueError("duplicate or unsupported archive member")
        if any("fitdiagnostics" in name.lower() or "higgscombine" in name.lower() for name in names):
            raise ValueError("raw Combine artifact entered sanitized archive")
        members = {safe_name(member): member for member in raw_members if member.isfile()}
        if set(members) != expected:
            raise ValueError(f"archive file set mismatch; missing={sorted(expected-set(members))} extra={sorted(set(members)-expected)}")
        payloads = {name: member_bytes(archive, members, name) for name in expected}

    status = key_values(payloads[f"{PREFIX}/status.txt"])
    expected_status = {
        "exit_code": "0", "terminal_stage": "complete", "width": "1", "mass_GeV": "2000",
        "rMax": "1", "dataset_scope": "masked_observed_sidebands_only",
        "fit_hypothesis": "background_only_r_fixed_zero",
        "pass_region_masks": "all_four_on_frozen", "allowed_channels": "20", "denied_channels": "4",
    }
    if set(status) != set(expected_status) | {
        "raw_fitdiagnostics_sha256", "snapshot_sha256", "payload_sha256", "runtime_sha256"
    }:
        raise ValueError("status key set mismatch")
    if any(status[key] != value for key, value in expected_status.items()):
        raise ValueError("status contract mismatch")
    if any(not SHA256.fullmatch(status[key]) for key in (
        "raw_fitdiagnostics_sha256", "snapshot_sha256", "payload_sha256", "runtime_sha256"
    )):
        raise ValueError("invalid status SHA-256")

    hashes = parse_hashes(payloads[f"{PREFIX}/artifact_hashes.sha256"])
    if set(hashes) != {f"area/{name}" for name in AREA_FILES}:
        raise ValueError("artifact hash coverage mismatch")
    for relative, digest in hashes.items():
        if sha256_bytes(payloads[f"{PREFIX}/{relative}"]) != digest:
            raise ValueError(f"artifact hash mismatch: {relative}")

    fit_lines = [
        FIT_LINE.match(line)
        for line in payloads[f"{PREFIX}/area/masked_postfit_fit_validation.log"].decode().splitlines()
        if line.startswith("FIT CHECK:")
    ]
    fit_lines = [match for match in fit_lines if match]
    if len(fit_lines) != 1:
        raise ValueError("masked postfit validation has no unique fit check")
    fit_status, cov_qual, edm = fit_lines[0].groups()
    if int(fit_status) != 0 or int(cov_qual) < 3 or float(edm) > 0.01:
        raise ValueError("masked postfit fit quality failed")

    record = json.loads(payloads[f"{PREFIX}/area/masked_postfit_safe.json"])
    allowed = set(record.get("allowed_channels", []))
    denied = set(record.get("denied_channels", []))
    if record.get("dataset_scope") != "masked_observed_sidebands_only":
        raise ValueError("safe postfit JSON scope mismatch")
    if record.get("fit_hypothesis") != "background_only_r_fixed_zero":
        raise ValueError("safe postfit fit-hypothesis mismatch")
    if len(allowed) != 20 or len(denied) != 4 or allowed.intersection(denied):
        raise ValueError("safe postfit channel policy mismatch")
    shape_sets = record.get("shape_sets", {})
    if set(shape_sets) != {"shapes_fit_b"}:
        raise ValueError("safe JSON shape-set mismatch")
    channels = set(shape_sets.get("shapes_fit_b", {}))
    if channels != allowed or channels.intersection(denied):
        raise ValueError("safe JSON channel mismatch in shapes_fit_b")
    if record.get("source_fitdiagnostics_sha256") != status["raw_fitdiagnostics_sha256"]:
        raise ValueError("raw FitDiagnostics provenance hash mismatch")
    safe_root = payloads[f"{PREFIX}/area/masked_postfit_safe.root"]
    if not safe_root.startswith(b"root"):
        raise ValueError("safe postfit ROOT magic mismatch")
    validate_safe_root(safe_root, allowed, denied)
    return {
        "source": source,
        "source_sha256": sha256_file(source),
        "status": status,
        "fit": {"status": int(fit_status), "cov_qual": int(cov_qual), "edm": float(edm)},
        "record": record,
    }


def extract_atomic(validated: dict[str, Any], campaign: Path) -> Path:
    destination = campaign / "masked_postfit" / "w1" / "signalZPrime2000_area"
    if destination.exists():
        raise ValueError(f"refusing to overwrite destination: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".masked-postfit-harvest-", dir=destination.parent))
    source = validated["source"]
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
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError(f"cannot extract {member.name}")
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
    print(json.dumps({
        "MASKED_POSTFIT_HARVEST_OK": True,
        "destination": str(destination) if destination else None,
        "fit": validated["fit"],
        "allowed_channels": 20,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (json.JSONDecodeError, OSError, ValueError) as error:
        print(f"MASKED_POSTFIT_HARVEST_FAILED: {error}")
        raise SystemExit(2)
