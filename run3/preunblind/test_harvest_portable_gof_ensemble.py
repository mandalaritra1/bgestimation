#!/usr/bin/env python3
"""Synthetic success and fail-closed tests for the 10x20 GoF ensemble harvester."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tarfile
import tempfile


HERE = Path(__file__).resolve().parent


def load_module(name: str):
    path = HERE / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_archive(path: Path, seed: int, toy_values: list[float], observed: float = 12.5) -> None:
    single = load_module("harvest_portable_gof")
    snapshot_sha = "a" * 64
    files: dict[str, bytes] = {
        "area/runtime_setup.log": b"runtime setup ok\n",
        "area/runtime_preflight.log": b"GOF_RUNTIME_OK 6.30\n",
        "area/combine_logger.out": b"Minimization success! status=0\n",
        "area/snapshot_validation.log": b"snapshot validation ok\n",
        "area/snapshot_validation.json": json.dumps({
            "schema_version": 1, "snapshot": "/scratch/final_snapshot.root",
            "snapshot_sha256": snapshot_sha, "snapshot_name": "MultiDimFit", "r_range": [0.0, 1.0],
            "required_masks": list(single.MASK_NAMES), "rpf_count": 18, "positive_rpf_par0_count": 4,
        }).encode(),
        "area/gof_data.log": b"masked sideband statistic ok\n",
        "area/gof_toys.log": b"masked toy shard ok\n",
        "area/gof_validation.log": b"result validation ok\n",
        "area/gof_validation.json": json.dumps({
            "schema_version": 1, "algorithm": "saturated", "data_scope": "observed_sideband_only",
            "pass_region_masks": "all_on_frozen", "r_state": "fixed_zero", "toy_seed": seed,
            "toy_count": 20, "observed_statistic": observed, "toy_statistics": toy_values,
        }).encode(),
        "area/higgsCombine_gof_masked_data.GoodnessOfFit.mH0.root": b"rootFAKE-DATA",
        f"area/higgsCombine_gof_masked_toys.GoodnessOfFit.mH0.{seed}.root": b"rootFAKE-TOYS" + str(seed).encode(),
    }
    hashes = "".join(
        f"{hashlib.sha256(payload).hexdigest()}  {name}\n" for name, payload in sorted(files.items())
    ).encode()
    status = {
        "exit_code": "0", "terminal_stage": "complete", "width": "1", "mass_GeV": "2000",
        "signal": "signalZPrime2000", "rMax": "1", "algorithm": "saturated",
        "data_scope": "observed_sideband_only", "pass_region_masks": "all_on_frozen",
        "r_state": "fixed_zero", "toy_seed": str(seed), "toy_count": "20",
        "snapshot_sha256": snapshot_sha, "payload_sha256": "b" * 64, "runtime_sha256": "c" * 64,
    }
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "gof_result"
        for name, payload in files.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        (root / "status.txt").write_text("".join(f"{key}={value}\n" for key, value in status.items()))
        (root / "artifact_hashes.sha256").write_bytes(hashes)
        with tarfile.open(path, "w:gz") as archive:
            archive.add(root, arcname="gof_result")


def expect_failure(action) -> None:
    try:
        action()
    except ValueError:
        return
    raise AssertionError("unsafe ensemble was accepted")


def main() -> int:
    ensemble = load_module("harvest_portable_gof_ensemble")
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        inputs = root / "inputs"
        inputs.mkdir()
        values = [10.0] * 10 + [15.0] * 10
        for seed in ensemble.SEEDS:
            make_archive(inputs / ensemble.ARCHIVE_TEMPLATE.format(seed=seed), seed, values)
        validated = ensemble.validate_ensemble(inputs)
        assert len(validated) == 10
        ledger = ensemble.build_ledger(validated, inputs)
        payload = ledger["ensemble"]
        assert payload["total_toys"] == 200 and payload["tail_count_k"] == 100
        assert payload["raw_k_over_200"]["value"] == 0.5
        assert payload["add_one_k_plus_1_over_201"]["value"] == 101 / 201
        destination = ensemble.write_ensemble_atomic(validated, ledger, root / "campaign")
        assert (destination / "aggregate_ledger.json").is_file()
        assert len(list(destination.glob("seed*_n20/area/gof_validation.json"))) == 10
        expect_failure(lambda: ensemble.write_ensemble_atomic(validated, ledger, root / "campaign"))

        extra = inputs / "unexpected.tgz"
        extra.write_bytes(b"not an archive")
        expect_failure(lambda: ensemble.validate_ensemble(inputs))
        extra.unlink()
        (inputs / ensemble.ARCHIVE_TEMPLATE.format(seed=ensemble.SEEDS[0])).unlink()
        expect_failure(lambda: ensemble.validate_ensemble(inputs))
        make_archive(inputs / ensemble.ARCHIVE_TEMPLATE.format(seed=ensemble.SEEDS[0]), ensemble.SEEDS[0], values)
        make_archive(inputs / ensemble.ARCHIVE_TEMPLATE.format(seed=ensemble.SEEDS[1]), ensemble.SEEDS[1], values, observed=12.6)
        expect_failure(lambda: ensemble.validate_ensemble(inputs))
    print("HARVEST_PORTABLE_GOF_ENSEMBLE_TEST_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
