#!/usr/bin/env python3
"""Synthetic success and fail-closed tests for the portable GoF harvester."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tarfile
import tempfile


HERE = Path(__file__).resolve().parent


def load_harvester():
    path = HERE / "harvest_portable_gof.py"
    spec = importlib.util.spec_from_file_location("harvest_portable_gof", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_archive(path: Path, unsafe_log: bool = False, omit_toy: bool = False) -> None:
    seed = 314159
    snapshot_sha = "a" * 64
    files: dict[str, bytes] = {
        "area/runtime_setup.log": b"runtime setup ok\n",
        "area/runtime_preflight.log": b"GOF_RUNTIME_OK 6.30\n",
        "area/combine_logger.out": b"Minimization success! status=0\n",
        "area/snapshot_validation.log": b"snapshot validation ok\n",
        "area/snapshot_validation.json": json.dumps({
            "schema_version": 1,
            "snapshot": "/scratch/final_snapshot.root",
            "snapshot_sha256": snapshot_sha,
            "snapshot_name": "MultiDimFit",
            "r_range": [0.0, 1.0],
            "required_masks": list(load_harvester().MASK_NAMES),
            "rpf_count": 18,
            "positive_rpf_par0_count": 4,
        }).encode() + b"\n",
        "area/gof_data.log": (
            b"mask_cen_Cen24Pass_Region1=0\n" if unsafe_log else b"observed sideband statistic ok\n"
        ),
        "area/gof_toys.log": b"five masked toys ok\n",
        "area/gof_validation.log": b"result validation ok\n",
        "area/gof_validation.json": json.dumps({
            "schema_version": 1,
            "algorithm": "saturated",
            "data_scope": "observed_sideband_only",
            "pass_region_masks": "all_on_frozen",
            "r_state": "fixed_zero",
            "toy_seed": seed,
            "toy_count": 5,
            "observed_statistic": 12.5,
            "toy_statistics": [8.0, 9.0, 10.0, 11.0, 13.0],
        }).encode() + b"\n",
        "area/higgsCombine_gof_masked_data.GoodnessOfFit.mH0.root": b"rootFAKE-DATA",
        f"area/higgsCombine_gof_masked_toys.GoodnessOfFit.mH0.{seed}.root": b"rootFAKE-TOYS",
    }
    if omit_toy:
        del files[f"area/higgsCombine_gof_masked_toys.GoodnessOfFit.mH0.{seed}.root"]
    hashes = "".join(
        f"{hashlib.sha256(payload).hexdigest()}  {name}\n"
        for name, payload in sorted(files.items())
    ).encode()
    status = {
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
        "toy_seed": str(seed),
        "toy_count": "5",
        "snapshot_sha256": snapshot_sha,
        "payload_sha256": "b" * 64,
        "runtime_sha256": "c" * 64,
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


def expect_failure(harvester, path: Path) -> None:
    try:
        harvester.validate_archive(path, 314159, 5)
    except ValueError:
        return
    raise AssertionError(f"unsafe archive was accepted: {path}")


def main() -> int:
    harvester = load_harvester()
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        good = root / "good.tgz"
        make_archive(good)
        validated = harvester.validate_archive(good, 314159, 5)
        campaign = root / "campaign"
        destination = harvester.extract_atomic(validated, campaign, 314159, 5)
        assert (destination / "area/gof_validation.json").is_file()
        try:
            harvester.extract_atomic(validated, campaign, 314159, 5)
        except ValueError:
            pass
        else:
            raise AssertionError("existing GoF destination was overwritten")

        unsafe = root / "unsafe.tgz"
        make_archive(unsafe, unsafe_log=True)
        expect_failure(harvester, unsafe)
        missing = root / "missing.tgz"
        make_archive(missing, omit_toy=True)
        expect_failure(harvester, missing)
    print("HARVEST_PORTABLE_GOF_TEST_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
