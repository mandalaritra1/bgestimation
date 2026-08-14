#!/usr/bin/env python3
"""Fail-closed validator/harvester for sanitized 2D masked-postfit shapes."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import tempfile


PREFIX = "masked_postfit_result"
FIT_LINE = re.compile(r"^FIT CHECK: status=(-?\d+) covQual=(-?\d+) EDM=([0-9.eE+-]+)$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
AREA_FILES = {
    "runtime_setup.log", "runtime_preflight.log", "snapshot_validation.log",
    "snapshot_validation.json", "source_fit_validation.log", "postfit2d.log", "sanitize2d.log",
    "masked_postfit_source_validation.log", "masked_postfit_source_validation.json",
    "masked_postfit_2d_safe.root", "masked_postfit_2d_safe.json",
}


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


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


def validate_root(payload: bytes, allowed: set[str], denied: set[str]) -> None:
    try:
        import ROOT
    except ImportError as error:
        raise ValueError("PyROOT is required to validate safe 2D postfit ROOT") from error
    ROOT.gROOT.SetBatch(True)
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "safe.root"
        path.write_bytes(payload)
        root_file = ROOT.TFile.Open(str(path))
        if not root_file or root_file.IsZombie():
            raise ValueError("cannot open safe 2D postfit ROOT")
        try:
            directories = {key.GetName() for key in root_file.GetListOfKeys()}
            expected = {f"{channel}_postfit" for channel in allowed}
            if directories != expected or any(name.removesuffix("_postfit") in denied for name in directories):
                raise ValueError("unsafe 2D postfit directory set")
            for directory_name in directories:
                directory = root_file.Get(directory_name)
                objects = {key.GetName() for key in directory.GetListOfKeys()}
                if objects != {"TotalBkg", "data_obs"}:
                    raise ValueError(f"unexpected safe objects in {directory_name}: {sorted(objects)}")
                for name in objects:
                    obj = directory.Get(name)
                    if not obj or not obj.InheritsFrom("TH1"):
                        raise ValueError(f"non-histogram safe object: {directory_name}/{name}")
        finally:
            root_file.Close()


def validate_archive(source: Path) -> dict[str, object]:
    if not source.is_file() or source.stat().st_size == 0:
        raise ValueError(f"missing or empty archive: {source}")
    expected = {f"{PREFIX}/status.txt", f"{PREFIX}/artifact_hashes.sha256"}
    expected.update(f"{PREFIX}/area/{name}" for name in AREA_FILES)
    with tarfile.open(source, "r:gz") as archive:
        raw = archive.getmembers()
        names = [safe_name(member) for member in raw]
        if len(names) != len(set(names)) or any(member.issym() or member.islnk() for member in raw):
            raise ValueError("duplicate or link archive member")
        if any("fitdiagnostics" in name.lower() or "postfitshapes" in name.lower() or "higgscombine" in name.lower() for name in names):
            raise ValueError("raw fit or shape artifact entered sanitized archive")
        members = {safe_name(member): member for member in raw if member.isfile()}
        if set(members) != expected:
            raise ValueError(f"archive file set mismatch; missing={sorted(expected-set(members))} extra={sorted(set(members)-expected)}")
        payloads = {name: member_bytes(archive, members, name) for name in expected}
    status = key_values(payloads[f"{PREFIX}/status.txt"])
    expected_status = {
        "exit_code": "0", "terminal_stage": "complete", "width": "1", "mass_GeV": "2000",
        "rMax": "1", "fit_dataset_scope": "masked_observed_sidebands_only",
        "fit_hypothesis": "background_only_r_fixed_zero",
        "pass_region_masks": "all_four_on_frozen", "allowed_channels": "20", "denied_channels": "4",
        "shape_extractor": "PostFit2DShapesFromWorkspace",
        "shape_dataset": "data_obs", "safe_export_scope": "unmasked_channels_only",
        "raw_postfit2d_disposition": "worker_scratch_only",
        "shape_extractor_mask_handling": "workspace_masks_one_constant_no_override",
    }
    hash_keys = {"fit_result_sha256", "raw_postfit2d_sha256", "snapshot_sha256", "payload_sha256", "runtime_sha256"}
    if set(status) != set(expected_status) | hash_keys or any(status.get(key) != value for key, value in expected_status.items()):
        raise ValueError("status contract mismatch")
    if any(not SHA256.fullmatch(status.get(key, "")) for key in hash_keys):
        raise ValueError("invalid status hash")
    hashes: dict[str, str] = {}
    for line in payloads[f"{PREFIX}/artifact_hashes.sha256"].decode().splitlines():
        value, separator, relative = line.partition("  ")
        if not separator or not SHA256.fullmatch(value) or relative in hashes:
            raise ValueError("malformed artifact hash manifest")
        hashes[relative] = value
    if set(hashes) != {f"area/{name}" for name in AREA_FILES}:
        raise ValueError("artifact hash coverage mismatch")
    for relative, value in hashes.items():
        if sha256_bytes(payloads[f"{PREFIX}/{relative}"]) != value:
            raise ValueError(f"artifact hash mismatch: {relative}")
    fit_matches = [
        FIT_LINE.fullmatch(line)
        for line in payloads[f"{PREFIX}/area/source_fit_validation.log"].decode().splitlines()
        if line.startswith("FIT CHECK:")
    ]
    fit_matches = [match for match in fit_matches if match]
    if len(fit_matches) != 1:
        raise ValueError("no unique masked fit quality line")
    status_code, cov_qual, edm = fit_matches[0].groups()
    if int(status_code) != 0 or int(cov_qual) < 3 or float(edm) > 0.01:
        raise ValueError("masked postfit fit quality failed")
    source_validation = json.loads(payloads[f"{PREFIX}/area/masked_postfit_source_validation.json"])
    if source_validation.get("shape_extractor_mask_handling") != "workspace_masks_one_constant_no_override":
        raise ValueError("masked postfit source-state contract mismatch")
    if source_validation.get("snapshot_sha256") != status["snapshot_sha256"] or source_validation.get("fit_result_sha256") != status["fit_result_sha256"]:
        raise ValueError("masked postfit source hash mismatch")
    if source_validation.get("r_range") != [0.0, 1.0]:
        raise ValueError("masked postfit source r range mismatch")
    for key in ("workspace_current_masks", "workspace_snapshot_masks"):
        states = source_validation.get(key)
        if not isinstance(states, dict) or len(states) != 4:
            raise ValueError(f"masked postfit source {key} mismatch")
        if any(state != {"value": 1.0, "constant": True} for state in states.values()):
            raise ValueError(f"unsafe source mask state in {key}")
    for key in ("workspace_current_r", "workspace_snapshot_r"):
        if source_validation.get(key) != {"value": 0.0, "constant": True}:
            raise ValueError(f"unsafe source r state in {key}")
    record = json.loads(payloads[f"{PREFIX}/area/masked_postfit_2d_safe.json"])
    allowed = set(record.get("allowed_channels", []))
    denied = set(record.get("denied_channels", []))
    if record.get("dataset_scope") != "masked_observed_sidebands_only" or record.get("source_tool") != "PostFit2DShapesFromWorkspace":
        raise ValueError("safe 2D postfit JSON scope mismatch")
    if len(allowed) != 20 or len(denied) != 4 or allowed.intersection(denied):
        raise ValueError("safe 2D postfit channel policy mismatch")
    if set(record.get("channels", {})) != allowed:
        raise ValueError("safe 2D postfit JSON channel mismatch")
    if record.get("source_postfit2d_sha256") != status["raw_postfit2d_sha256"]:
        raise ValueError("raw 2D postfit provenance mismatch")
    for channel, objects in record["channels"].items():
        if set(objects) != {"TotalBkg", "data_obs"}:
            raise ValueError(f"safe JSON object mismatch in {channel}")
        if objects["TotalBkg"].get("kind") not in {"TH1", "TH2"}:
            raise ValueError(f"invalid TotalBkg kind in {channel}")
        if objects["data_obs"].get("kind") != objects["TotalBkg"].get("kind"):
            raise ValueError(f"model/data kind mismatch in {channel}")
    safe_root = payloads[f"{PREFIX}/area/masked_postfit_2d_safe.root"]
    if not safe_root.startswith(b"root"):
        raise ValueError("safe 2D postfit ROOT magic mismatch")
    validate_root(safe_root, allowed, denied)
    return {"source": source, "fit": {"status": int(status_code), "cov_qual": int(cov_qual), "edm": float(edm)}, "record": record}


def extract_atomic(validated: dict[str, object], campaign: Path) -> Path:
    destination = campaign / "masked_postfit_2d" / "w1" / "signalZPrime2000_area"
    if destination.exists():
        raise ValueError(f"refusing to overwrite destination: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".masked-postfit-2d-", dir=destination.parent))
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
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError(f"cannot extract {member.name}")
                with target.open("xb") as handle:
                    shutil.copyfileobj(stream, handle)
        staged.replace(destination)
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
    print(json.dumps({"MASKED_POSTFIT_2D_HARVEST_OK": True, "destination": str(destination) if destination else None, "fit": validated["fit"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        print(f"MASKED_POSTFIT_2D_HARVEST_FAILED: {error}")
        raise SystemExit(2)
