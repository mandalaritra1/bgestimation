#!/usr/bin/env python3
"""Strict validator and atomic harvester for the two-start b-only closure."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import tempfile


PREFIX = "background_closure_result"
STARTS = ("zero", "halfmax")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
FIT_LINE = re.compile(r"^FIT CHECK: status=(-?\d+) covQual=(-?\d+) EDM=([0-9.eE+-]+)$")


def safe_name(member: tarfile.TarInfo) -> str:
    path = PurePosixPath(member.name)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe archive member: {member.name}")
    return path.as_posix().lstrip("./")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def member_bytes(archive: tarfile.TarFile, members: dict[str, tarfile.TarInfo], name: str) -> bytes:
    member = members.get(name)
    if not member or not member.isfile():
        raise ValueError(f"missing regular member: {name}")
    stream = archive.extractfile(member)
    if stream is None:
        raise ValueError(f"cannot read member: {name}")
    payload = stream.read()
    if not payload:
        raise ValueError(f"empty member: {name}")
    return payload


def status_map(payload: bytes) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in payload.decode().splitlines():
        key, separator, value = line.partition("=")
        if not separator or not key or key in result:
            raise ValueError(f"malformed status line: {line!r}")
        result[key] = value
    return result


def expected_area() -> set[str]:
    files = {
        "runtime_setup.log", "runtime_preflight.log", "combine_logger.out",
        "generate.log", "higgsCombine_gen.GenerateOnly.mH0.123456.root",
    }
    for start in STARTS:
        name = f"background_closure_w1_m2000_{start}"
        files.update({
            f"fit_{start}.log", f"fit_{start}_validation.log", f"fit_{start}.json",
            f"multidimfit_initialFit_{name}.root",
            f"higgsCombine_initialFit_{name}.MultiDimFit.mH0.root",
        })
    return files


def finite(value: object, label: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"non-finite {label}")
    return result


def validate_fit(payload: bytes, start: str) -> dict[str, float | int]:
    record = json.loads(payload)
    if set(record) != {"fit", "fit_key", "floating_parameters", "input", "metadata", "r"} or record.get("fit_key") != "fit_mdf":
        raise ValueError(f"unexpected fit JSON schema for {start}")
    expected_metadata = {
        "width_percent": "1", "mass_GeV": "2000", "rMax": "1",
        "closure_hypothesis": "background_only", "injected_r": "0",
        "start_label": start, "start_r": "0" if start == "zero" else "0.5",
    }
    if record.get("metadata") != expected_metadata:
        raise ValueError(f"fit metadata mismatch for {start}")
    fit = record["fit"]
    status, cov_qual = int(fit["status"]), int(fit["cov_qual"])
    edm, min_nll = finite(fit["edm"], "EDM"), finite(fit["min_nll"], "minNLL")
    if status != 0 or cov_qual < 3 or edm > 0.01:
        raise ValueError(f"fit quality failed for {start}")
    r = record["r"]
    r_value = finite(r["value"], "r value")
    r_error = finite(r["error"], "r error")
    r_error_high = finite(r["error_high"], "r upper error")
    if r.get("name") != "r" or r.get("constant") is not False or r.get("min") != 0.0 or r.get("max") != 1.0:
        raise ValueError(f"r is not floating on [0,1] for {start}")
    if r_value < 0.0 or r_value > 1.0 or r_error <= 0.0 or max(r_error, r_error_high) <= 0.0:
        raise ValueError(f"invalid r result for {start}")
    if r.get("boundary", {}).get("outside_bounds") is not False:
        raise ValueError(f"r outside bounds for {start}")
    floating_r = [item for item in record["floating_parameters"] if item.get("name") == "r"]
    if len(floating_r) != 1 or floating_r[0] != r:
        raise ValueError(f"no unique floating r parameter for {start}")
    zero_pull = r_value / max(r_error, r_error_high)
    if zero_pull > 0.1:
        raise ValueError(f"background closure exceeds 0.1 sigma for {start}: {zero_pull}")
    return {
        "status": status, "cov_qual": cov_qual, "edm": edm, "min_nll": min_nll,
        "r": r_value, "r_error": r_error, "r_error_high": r_error_high,
        "zero_compatibility_pull": zero_pull,
    }


def validate_archive(source: Path) -> dict[str, object]:
    if not source.is_file() or source.stat().st_size == 0:
        raise ValueError(f"missing closure archive: {source}")
    area_files = expected_area()
    expected = {f"{PREFIX}/status.txt", f"{PREFIX}/artifact_hashes.sha256"}
    expected.update(f"{PREFIX}/area/{name}" for name in area_files)
    with tarfile.open(source, "r:gz") as archive:
        raw = archive.getmembers()
        names = [safe_name(member) for member in raw]
        if len(names) != len(set(names)) or any(member.issym() or member.islnk() for member in raw):
            raise ValueError("duplicate or linked archive member")
        members = {safe_name(member): member for member in raw if member.isfile()}
        if set(members) != expected:
            raise ValueError(f"closure archive file set mismatch; missing={sorted(expected-set(members))} extra={sorted(set(members)-expected)}")
        payloads = {name: member_bytes(archive, members, name) for name in expected}
    status = status_map(payloads[f"{PREFIX}/status.txt"])
    expected_status = {
        "exit_code": "0", "terminal_stage": "complete", "width": "1", "mass_GeV": "2000",
        "rMax": "1", "closure_hypothesis": "background_only", "rInject": "0",
        "dataset_scope": "synthetic_asimov_only", "pass_region_masks": "all_off_frozen",
        "r_floating": "1", "rMin": "0", "start_zero": "0", "start_halfmax": "0.5",
        "fit_count": "2", "fit_start_mode": "independent_requested_seed_robust_impacts_initialfit",
        "bootstrap_seed_policy": "no_bootstrap_independent_per_start",
        "final_nuisance_start": "physical_masked_snapshot_no_override",
        "rpf_range_override": "none", "toy_seed": "123456",
    }
    hash_keys = {"snapshot_sha256", "payload_sha256", "runtime_sha256"}
    if set(status) != set(expected_status) | hash_keys or any(status.get(key) != value for key, value in expected_status.items()):
        raise ValueError("closure status contract mismatch")
    if any(not SHA256.fullmatch(status.get(key, "")) for key in hash_keys):
        raise ValueError("invalid closure provenance hash")
    hashes: dict[str, str] = {}
    for line in payloads[f"{PREFIX}/artifact_hashes.sha256"].decode().splitlines():
        digest, separator, relative = line.partition("  ")
        if not separator or not SHA256.fullmatch(digest) or relative in hashes:
            raise ValueError("malformed closure hash manifest")
        hashes[relative] = digest
    if set(hashes) != {f"area/{name}" for name in area_files}:
        raise ValueError("closure hash coverage mismatch")
    for relative, digest in hashes.items():
        if sha256_bytes(payloads[f"{PREFIX}/{relative}"]) != digest:
            raise ValueError(f"closure hash mismatch: {relative}")
    for name in area_files:
        if name.endswith(".root") and not payloads[f"{PREFIX}/area/{name}"].startswith(b"root"):
            raise ValueError(f"closure ROOT magic mismatch: {name}")
    executed_text = b"\n".join(
        payload for name, payload in payloads.items()
        if name.endswith((".log", ".json", ".txt")) and not name.endswith("runtime_preflight.log")
    ).decode(errors="strict").lower()
    if "data_obs" in executed_text or "observed" in executed_text:
        raise ValueError("forbidden observed marker in closure artifacts")
    fits: dict[str, dict[str, float | int]] = {}
    for start in STARTS:
        log = payloads[f"{PREFIX}/area/fit_{start}_validation.log"].decode().splitlines()
        matches = [FIT_LINE.fullmatch(line) for line in log if line.startswith("FIT CHECK:")]
        matches = [match for match in matches if match]
        if len(matches) != 1:
            raise ValueError(f"no unique fit-quality line for {start}")
        fits[start] = validate_fit(payloads[f"{PREFIX}/area/fit_{start}.json"], start)
    combined_error = math.hypot(float(fits["zero"]["r_error"]), float(fits["halfmax"]["r_error"]))
    seed_delta_sigma = abs(float(fits["zero"]["r"]) - float(fits["halfmax"]["r"])) / combined_error
    delta_min_nll = abs(float(fits["zero"]["min_nll"]) - float(fits["halfmax"]["min_nll"]))
    if seed_delta_sigma > 0.1 or delta_min_nll > 1.0e-3:
        raise ValueError(f"closure start invariance failed: dr={seed_delta_sigma} dNLL={delta_min_nll}")
    return {
        "source": source, "source_sha256": sha256_file(source), "status": status,
        "artifact_hashes": hashes, "fits": fits,
        "seed_delta_combined_sigma": seed_delta_sigma, "delta_min_nll": delta_min_nll,
    }


def harvest(validated: dict[str, object], campaign: Path, ledger: Path) -> Path:
    destination = campaign / "background_closure" / "w1" / "signalZPrime2000_area" / "bkg_asimov"
    if destination.exists() or ledger.exists():
        raise ValueError("refusing to overwrite closure harvest")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".background-closure-", dir=destination.parent))
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
                target = staged / name.name
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError(f"cannot extract {member.name}")
                with target.open("xb") as handle:
                    shutil.copyfileobj(stream, handle)
        os.rename(staged, destination)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("x") as handle:
        json.dump({key: value for key, value in validated.items() if key != "source"}, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    if args.validate_only and args.ledger:
        parser.error("--validate-only does not write a ledger")
    if not args.validate_only and not args.ledger:
        parser.error("harvesting requires --ledger")
    validated = validate_archive(args.archive)
    destination = None if args.validate_only else harvest(validated, args.campaign, args.ledger)
    print(json.dumps({
        "BACKGROUND_CLOSURE_HARVEST_OK": True,
        "destination": str(destination) if destination else None,
        "fits": validated["fits"],
        "seed_delta_combined_sigma": validated["seed_delta_combined_sigma"],
        "delta_min_nll": validated["delta_min_nll"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        print(f"BACKGROUND_CLOSURE_HARVEST_FAILED: {error}")
        raise SystemExit(2)
