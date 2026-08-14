#!/usr/bin/env python3
"""Synthetic success and fail-closed tests for the Asimov Impacts harvester."""

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


def make_archive(path: Path, bad_marker: bool = False) -> None:
    harvester = load_module("harvest_portable_asimov_impacts")
    snapshot_sha = "a" * 64
    impacts = {
        "POIs": [{"name": "r", "fit": [0.01, 0.0169433597475, 0.03]}],
        "params": [{"name": "lumi24", "fit": [0.97, 1.0, 1.03], "prefit": [0.97, 1.0, 1.03],
                    "type": "Gaussian", "groups": [], "r": [0.01, 0.0169433597475, 0.03], "impact_r": 0.002}],
        "method": "default",
    }
    validation = load_module("validate_portable_asimov_impacts").validate_impacts_payload(impacts, "lumi24")
    parameter_root_name = f"area/higgsCombine_paramFit_{harvester.NAME}_{harvester.NUISANCE}.MultiDimFit.mH0.root"
    parameter_root_payload = b"root-param"
    files: dict[str, bytes] = {
        "area/runtime_setup.log": b"runtime setup ok\n",
        "area/runtime_preflight.log": b"runtime preflight ok\n",
        "area/combine_logger.out": b"Minimization success! status=0\n",
        "area/snapshot_validation.log": b"snapshot valid\n",
        "area/snapshot_validation.json": json.dumps({
            "schema_version": 1, "snapshot_name": "MultiDimFit", "snapshot_sha256": snapshot_sha,
            "r_range": [0.0, 1.0],
            "required_masks": ["mask_cen_Cen24Pass_Region1", "mask_cen_Cen25Pass_Region1",
                               "mask_fwd_Fwd24Pass_Region1", "mask_fwd_Fwd25Pass_Region1"],
            "model_nuisances": ["lumi24", "lumi25", "ttbar_xsec"],
            "rpf_count": 18, "positive_rpf_par0_count": 4,
        }).encode(),
        "area/initial_fit.log": b"initial fit ok\n",
        "area/initial_fit_validation.log": b"FIT CHECK: status=0 covQual=3 EDM=0.001\n",
        "area/named_nuisance_fit.log": b"named fit ok\n",
        "area/named_fit_validation.log": b"named fit ROOT validation ok\n",
        "area/named_fit_validation.json": json.dumps({
            "schema_version": 1, "dataset_scope": "synthetic_asimov_only",
            "named_nuisance": "lumi24", "tree_entries": 3,
            "required_branches": ["deltaNLL", "lumi24", "r"],
            "fit_status_checked": True,
            "root_sha256": hashlib.sha256(parameter_root_payload).hexdigest(),
            "records": [
                {"r": 0.015, "lumi24": -1.0, "deltaNLL": 0.5},
                {"r": 0.0169433597475, "lumi24": 0.0, "deltaNLL": 0.0},
                {"r": 0.019, "lumi24": 1.0, "deltaNLL": 0.5},
            ],
        }).encode(),
        "area/collect_impacts.log": b"collection ok\n",
        "area/impacts_validation.log": b"validation ok\n",
        "area/impacts_lumi24.json": json.dumps(impacts).encode(),
        "area/impacts_validation.json": json.dumps(validation).encode(),
        f"area/higgsCombine_initialFit_{harvester.NAME}.MultiDimFit.mH0.root": b"root-initial",
        parameter_root_name: parameter_root_payload,
        f"area/multidimfit_initialFit_{harvester.NAME}.root": b"root-initial-fit",
    }
    if bad_marker:
        files["area/collect_impacts.log"] = b"data_obs forbidden\n"
    hashes = "".join(f"{hashlib.sha256(payload).hexdigest()}  {name}\n" for name, payload in sorted(files.items())).encode()
    status = {
        "exit_code": "0", "terminal_stage": "complete", "width": "1", "mass_GeV": "2000",
        "production_rMax": "1", "rInject": "0.0169433597475", "named_nuisance": "lumi24",
        "named_fit_quality": "not_available_in_impact_mode",
        "toy_seed": "123456", "dataset_scope": "synthetic_asimov_only", "pass_region_masks": "all_off_frozen",
        "snapshot_sha256": snapshot_sha, "payload_sha256": "b" * 64, "runtime_sha256": "c" * 64,
    }
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / harvester.PREFIX
        for name, payload in files.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        (root / "status.txt").write_text("".join(f"{key}={value}\n" for key, value in status.items()))
        (root / "artifact_hashes.sha256").write_bytes(hashes)
        with tarfile.open(path, "w:gz") as archive:
            archive.add(root, arcname=harvester.PREFIX)


def expect_failure(action) -> None:
    try:
        action()
    except ValueError:
        return
    raise AssertionError("unsafe archive was accepted")


def main() -> int:
    harvester = load_module("harvest_portable_asimov_impacts")
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        good = root / "good.tgz"
        make_archive(good)
        validated = harvester.validate_archive(good)
        assert validated["impacts"]["impact_r"] == 0.002
        destination = harvester.extract_atomic(validated, root / "campaign")
        assert (destination / "impacts_lumi24.json").is_file()
        expect_failure(lambda: harvester.extract_atomic(validated, root / "campaign"))
        unsafe = root / "unsafe.tgz"
        make_archive(unsafe, bad_marker=True)
        expect_failure(lambda: harvester.validate_archive(unsafe))
    print("HARVEST_PORTABLE_ASIMOV_IMPACTS_TEST_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
