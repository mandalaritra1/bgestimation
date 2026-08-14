#!/usr/bin/env python3
"""Fail-closed, all-or-nothing harvest of the 10x20 portable masked-GoF ensemble.

The output ledger records empirical tail-count bookkeeping only.  It does not
make a statistical interpretation or a claim about the GoF result.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
SEEDS = tuple(range(314160, 314170))
TOYS_PER_SHARD = 20
TOTAL_TOYS = len(SEEDS) * TOYS_PER_SHARD
ARCHIVE_TEMPLATE = "w1_m2000_seed{seed}_n20.tgz"


def load_single_harvester():
    path = HERE / "harvest_portable_gof.py"
    spec = importlib.util.spec_from_file_location("harvest_portable_gof", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"cannot load existing GoF harvester: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def expected_archives(input_dir: Path) -> dict[int, Path]:
    if not input_dir.is_dir():
        raise ValueError(f"ensemble input directory does not exist: {input_dir}")
    entries = {entry.name for entry in input_dir.iterdir()}
    expected = {ARCHIVE_TEMPLATE.format(seed=seed) for seed in SEEDS}
    if entries != expected:
        raise ValueError(
            f"ensemble archive set mismatch; missing={sorted(expected - entries)} extra={sorted(entries - expected)}"
        )
    return {seed: input_dir / ARCHIVE_TEMPLATE.format(seed=seed) for seed in SEEDS}


def validate_ensemble(input_dir: Path) -> list[dict[str, Any]]:
    """Validate every exact archive before returning any extractable result."""
    single = load_single_harvester()
    sources = expected_archives(input_dir)
    validated: list[dict[str, Any]] = []
    for seed in SEEDS:
        record = single.validate_archive(sources[seed], seed, TOYS_PER_SHARD)
        validated.append(record)
    observed = {record["observed_statistic"] for record in validated}
    if len(observed) != 1:
        raise ValueError("masked observed sideband statistic is not identical across shards")
    source_hashes = [record["source_sha256"] for record in validated]
    if len(set(source_hashes)) != len(source_hashes):
        raise ValueError("duplicate archive SHA-256 across deterministic seeds")
    statuses = [record["status"] for record in validated]
    for status_key in ("snapshot_sha256", "payload_sha256", "runtime_sha256"):
        if len({status[status_key] for status in statuses}) != 1:
            raise ValueError(f"shards do not share one {status_key}")
    toys = [toy for record in validated for toy in record["toy_statistics"]]
    if len(toys) != TOTAL_TOYS or any(not math.isfinite(toy) or toy < 0 for toy in toys):
        raise ValueError("ensemble does not contain exactly 200 finite non-negative toy values")
    return validated


def safe_name(member: tarfile.TarInfo) -> str:
    name = PurePosixPath(member.name)
    if name.is_absolute() or ".." in name.parts:
        raise ValueError(f"unsafe archive member: {member.name}")
    return name.as_posix().lstrip("./")


def copy_validated_archive(source: Path, destination: Path) -> None:
    """Copy one already-validated gof_result archive into a private staging tree."""
    with tarfile.open(source, "r:gz") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            name = PurePosixPath(safe_name(member))
            relative = name.relative_to("gof_result")
            target = destination.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError(f"cannot extract archive member: {member.name}")
            with target.open("xb") as handle:
                shutil.copyfileobj(stream, handle)


def build_ledger(validated: list[dict[str, Any]], input_dir: Path) -> dict[str, object]:
    observed = float(validated[0]["observed_statistic"])
    toy_values = [float(value) for record in validated for value in record["toy_statistics"]]
    tail_count = sum(value >= observed for value in toy_values)
    statuses = [record["status"] for record in validated]
    return {
        "schema_version": 1,
        "scope": "masked_observed_sideband_only",
        "interpretation": "Empirical tail-count bookkeeping only; no statistical interpretation is claimed.",
        "ensemble": {
            "width": 1,
            "mass_GeV": 2000,
            "signal": "signalZPrime2000",
            "rMax": 1,
            "algorithm": "saturated",
            "pass_region_masks": "all_on_frozen",
            "r_state": "fixed_zero",
            "shard_count": len(SEEDS),
            "toys_per_shard": TOYS_PER_SHARD,
            "total_toys": TOTAL_TOYS,
            "seeds": list(SEEDS),
            "observed_statistic": observed,
            "toy_statistics": toy_values,
            "tail_definition": "toy_statistic >= observed_statistic",
            "tail_count_k": tail_count,
            "raw_k_over_200": {"numerator_k": tail_count, "denominator": TOTAL_TOYS,
                               "value": tail_count / TOTAL_TOYS},
            "add_one_k_plus_1_over_201": {"numerator_k_plus_1": tail_count + 1,
                                             "denominator": TOTAL_TOYS + 1,
                                             "value": (tail_count + 1) / (TOTAL_TOYS + 1)},
        },
        "common_provenance": {
            "snapshot_sha256": statuses[0]["snapshot_sha256"],
            "payload_sha256": statuses[0]["payload_sha256"],
            "runtime_sha256": statuses[0]["runtime_sha256"],
        },
        "shards": [
            {
                "seed": seed,
                "toy_count": TOYS_PER_SHARD,
                "archive": str(input_dir / ARCHIVE_TEMPLATE.format(seed=seed)),
                "archive_sha256": record["source_sha256"],
                "artifact_hashes": record["artifact_hashes"],
            }
            for seed, record in zip(SEEDS, validated)
        ],
    }


def write_ensemble_atomic(validated: list[dict[str, Any]], ledger: dict[str, object], campaign: Path) -> Path:
    parent = campaign / "gof" / "masked" / "w1" / "signalZPrime2000_area"
    destination = parent / "ensemble_200_n20"
    if destination.exists():
        raise ValueError(f"refusing to overwrite ensemble destination: {destination}")
    parent.mkdir(parents=True, exist_ok=True)
    stage_root = Path(tempfile.mkdtemp(prefix=".ensemble-harvest-", dir=parent))
    try:
        staged = stage_root / destination.name
        staged.mkdir()
        for seed, record in zip(SEEDS, validated):
            source = record["source"]
            assert isinstance(source, Path)
            copy_validated_archive(source, staged / f"seed{seed}_n{TOYS_PER_SHARD}")
        ledger_path = staged / "aggregate_ledger.json"
        with ledger_path.open("x", encoding="utf-8") as handle:
            json.dump(ledger, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.rename(staged, destination)
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--no-extract", action="store_true")
    args = parser.parse_args()
    validated = validate_ensemble(args.input_dir)
    ledger = build_ledger(validated, args.input_dir)
    destination = None if args.no_extract else write_ensemble_atomic(validated, ledger, args.campaign)
    print(json.dumps({"GOF_ENSEMBLE_HARVEST_OK": True, "shards": len(validated),
                      "toys": TOTAL_TOYS, "destination": str(destination) if destination else None}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
