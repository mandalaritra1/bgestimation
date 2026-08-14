#!/usr/bin/env python3
"""Fail-closed single-archive harvester for the parameterized expected impacts matrix."""

from __future__ import annotations

import argparse
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
MODEL_NUISANCES = ("lumi24", "lumi25", "ttbar_xsec")


def load_legacy():
    path = HERE / "harvest_portable_asimov_impacts.py"
    spec = importlib.util.spec_from_file_location("harvest_portable_asimov_impacts", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"cannot load impacts helpers: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def signal_name(width: int, mass: int) -> str:
    suffix = "" if width == 1 else f"_{width}"
    return f"signalZPrime{mass}{suffix}"


def validate_archive(
    source: Path,
    width: int,
    mass: int,
    rmax_text: str,
    rinject_text: str,
    nuisance: str,
) -> dict[str, Any]:
    helper = load_legacy()
    if width not in (1, 10, 30) or mass not in (2000, 4000, 6000, 7000):
        raise ValueError("point is outside the reviewed expected-impacts grid")
    if nuisance not in MODEL_NUISANCES:
        raise ValueError(f"unregistered nuisance: {nuisance}")
    rmax = float(rmax_text)
    rinject = float(rinject_text)
    if not all(math.isfinite(value) and value > 0 for value in (rmax, rinject)) or rinject >= 0.9 * rmax:
        raise ValueError("invalid rMax/rInject or missing headroom")
    if not source.is_file() or source.stat().st_size == 0:
        raise ValueError(f"missing or empty impacts archive: {source}")

    name = f"asimov_w{width}_m{mass}_{nuisance}"
    initial_root = f"area/higgsCombine_initialFit_{name}.MultiDimFit.mH0.root"
    parameter_root = f"area/higgsCombine_paramFit_{name}_{nuisance}.MultiDimFit.mH0.root"
    initial_fit = f"area/multidimfit_initialFit_{name}.root"
    impacts_json = f"area/impacts_{nuisance}.json"
    area_files = {
        "area/runtime_setup.log", "area/runtime_preflight.log", "area/combine_logger.out",
        "area/snapshot_validation.log", "area/snapshot_validation.json",
        "area/initial_fit.log", "area/initial_fit_validation.log", "area/named_nuisance_fit.log",
        "area/named_fit_validation.log", "area/named_fit_validation.json",
        "area/collect_impacts.log", "area/impacts_validation.log",
        impacts_json, "area/impacts_validation.json",
        initial_root, parameter_root, initial_fit,
    }
    expected_files = {f"{PREFIX}/status.txt", f"{PREFIX}/artifact_hashes.sha256"}
    expected_files.update(f"{PREFIX}/{name}" for name in area_files)
    with tarfile.open(source, "r:gz") as archive:
        raw_members = archive.getmembers()
        names = [helper.safe_name(member) for member in raw_members]
        if len(names) != len(set(names)) or any(not (member.isfile() or member.isdir()) for member in raw_members):
            raise ValueError("duplicate or unsupported archive member")
        if any("observed" in item.lower() or "data_obs" in item.lower() for item in names):
            raise ValueError("forbidden non-synthetic archive path")
        members = {helper.safe_name(member): member for member in raw_members if member.isfile()}
        if set(members) != expected_files:
            raise ValueError(f"unexpected archive file set; missing={sorted(expected_files-set(members))} extra={sorted(set(members)-expected_files)}")
        payloads = {name: helper.member_bytes(archive, members, name) for name in expected_files}

    status = helper.parse_status(payloads[f"{PREFIX}/status.txt"])
    expected_status = {
        "exit_code": "0", "terminal_stage": "complete", "width": str(width),
        "mass_GeV": str(mass), "named_nuisance": nuisance,
        "named_fit_quality": "not_available_in_impact_mode", "toy_seed": "123456",
        "dataset_scope": "synthetic_asimov_only", "pass_region_masks": "all_off_frozen",
    }
    if set(status) != set(expected_status) | {
        "production_rMax", "rInject", "snapshot_sha256", "payload_sha256", "runtime_sha256"
    }:
        raise ValueError("status key set mismatch")
    if any(status[key] != value for key, value in expected_status.items()):
        raise ValueError("status contract mismatch")
    if not math.isclose(float(status["production_rMax"]), rmax, rel_tol=0, abs_tol=1e-15):
        raise ValueError("status rMax mismatch")
    if not math.isclose(float(status["rInject"]), rinject, rel_tol=0, abs_tol=1e-15):
        raise ValueError("status rInject mismatch")
    if any(not helper.SHA256.fullmatch(status[key]) for key in ("snapshot_sha256", "payload_sha256", "runtime_sha256")):
        raise ValueError("invalid provenance SHA-256")

    hashes = helper.parse_hashes(payloads[f"{PREFIX}/artifact_hashes.sha256"])
    if set(hashes) != area_files:
        raise ValueError("artifact checksum manifest does not cover the exact area")
    for relative, digest in hashes.items():
        if helper.sha256_bytes(payloads[f"{PREFIX}/{relative}"]) != digest:
            raise ValueError(f"artifact checksum mismatch: {relative}")
    for root in (initial_root, parameter_root, initial_fit):
        if not payloads[f"{PREFIX}/{root}"].startswith(b"root"):
            raise ValueError(f"ROOT magic mismatch: {root}")
    text = b"\n".join(
        payload
        for member, payload in payloads.items()
        if member.endswith((".log", ".json", ".txt", ".sha256"))
        and not member.endswith("area/runtime_preflight.log")
    ).decode("utf-8", errors="strict")
    if "observed" in text.lower() or "data_obs" in text.lower():
        raise ValueError("forbidden non-synthetic marker in executed artifacts")
    if "Minimization success! status=0" not in payloads[f"{PREFIX}/area/combine_logger.out"].decode():
        raise ValueError("Combine logger lacks status-0 minimization success")

    initial_quality = helper.require_fit_log(
        payloads[f"{PREFIX}/area/initial_fit_validation.log"], "initial"
    )
    named = json.loads(payloads[f"{PREFIX}/area/named_fit_validation.json"])
    records = named.get("records")
    if (
        named.get("schema_version") != 1
        or named.get("dataset_scope") != "synthetic_asimov_only"
        or named.get("named_nuisance") != nuisance
        or named.get("tree_entries") != 3
        or named.get("required_branches") != sorted(["deltaNLL", nuisance, "r"])
        or named.get("root_sha256") != helper.sha256_bytes(payloads[f"{PREFIX}/{parameter_root}"])
        or not isinstance(records, list)
        or len(records) != 3
    ):
        raise ValueError("named-nuisance ROOT validation contract mismatch")
    for record in records:
        if not isinstance(record, dict) or set(record) != {"r", nuisance, "deltaNLL"}:
            raise ValueError("malformed named-nuisance ROOT record")
        values = [float(record["r"]), float(record[nuisance]), float(record["deltaNLL"])]
        if not all(math.isfinite(value) for value in values) or not 0 <= values[0] <= rmax or values[2] < -1e-6:
            raise ValueError("unphysical named-nuisance ROOT record")
    snapshot = json.loads(payloads[f"{PREFIX}/area/snapshot_validation.json"])
    if snapshot.get("r_range") != [0.0, rmax] or snapshot.get("model_nuisances") != list(MODEL_NUISANCES):
        raise ValueError("snapshot range or nuisance contract mismatch")
    if snapshot.get("rpf_count") != 18 or snapshot.get("positive_rpf_par0_count") != 4:
        raise ValueError("snapshot physical RPF range contract mismatch")
    if snapshot.get("snapshot_sha256") != status["snapshot_sha256"]:
        raise ValueError("snapshot provenance mismatch")
    raw_impacts = json.loads(payloads[f"{PREFIX}/{impacts_json}"])
    validation = helper.load_validator().validate_impacts_payload(raw_impacts, nuisance)
    saved_validation = json.loads(payloads[f"{PREFIX}/area/impacts_validation.json"])
    if saved_validation != validation:
        raise ValueError("saved impacts validation does not match strict revalidation")
    return {
        "source": source,
        "source_sha256": helper.sha256_file(source),
        "point": {"width": width, "mass": mass, "rMax": rmax, "rInject": rinject, "nuisance": nuisance},
        "status": status,
        "fit": initial_quality,
        "named_fit": named,
        "impacts": validation,
    }


def extract_atomic(validated: dict[str, Any], campaign: Path) -> Path:
    point = validated["point"]
    width, mass, nuisance = point["width"], point["mass"], point["nuisance"]
    signal = signal_name(width, mass)
    rinject_label = f"{point['rInject']:.16g}".replace(".", "p")
    destination = campaign / "asimov_impacts" / f"w{width}" / f"{signal}_area" / f"{nuisance}_rInject_{rinject_label}"
    if destination.exists():
        raise ValueError(f"refusing to overwrite impacts destination: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".asimov-impacts-v2-", dir=destination.parent))
    source = validated["source"]
    try:
        staged = temporary / destination.name
        staged.mkdir()
        with tarfile.open(source, "r:gz") as archive:
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                name = PurePosixPath(load_legacy().safe_name(member))
                if not str(name).startswith(f"{PREFIX}/area/"):
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
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--mass", type=int, required=True)
    parser.add_argument("--rmax", required=True)
    parser.add_argument("--rinject", required=True)
    parser.add_argument("--nuisance", choices=MODEL_NUISANCES, required=True)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--no-extract", action="store_true")
    args = parser.parse_args()
    validated = validate_archive(
        args.archive, args.width, args.mass, args.rmax, args.rinject, args.nuisance
    )
    destination = None if args.no_extract else extract_atomic(validated, args.campaign)
    print(json.dumps({
        "ASIMOV_IMPACTS_V2_HARVEST_OK": True,
        "destination": str(destination) if destination else None,
        "impact_r": validated["impacts"]["impact_r"],
        "point": validated["point"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (json.JSONDecodeError, OSError, ValueError) as error:
        print(f"ASIMOV_IMPACTS_V2_HARVEST_FAILED: {error}")
        raise SystemExit(2)
