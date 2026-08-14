#!/usr/bin/env python3
"""Synthetic success and bias-rejection tests for the closure harvester."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tarfile
import tempfile

from harvest_portable_background_closure import PREFIX, expected_area, validate_archive


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def fit_record(start: str, r_value: float) -> dict[str, object]:
    r = {
        "name": "r", "value": r_value, "error": 0.01, "error_low": -0.01,
        "error_high": 0.01, "min": 0.0, "max": 1.0, "constant": False,
        "boundary": {"accessible": True, "at_max": False, "at_min": r_value == 0.0,
                     "near_max": False, "near_min": r_value == 0.0,
                     "outside_bounds": False, "tolerance": 1e-6},
    }
    return {
        "fit_key": "fit_mdf",
        "input": f"/srv/background_closure_area/multidimfit_{start}.root",
        "metadata": {
            "width_percent": "1", "mass_GeV": "2000", "rMax": "1",
            "closure_hypothesis": "background_only", "injected_r": "0",
            "start_label": start, "start_r": "0" if start == "zero" else "0.5",
        },
        "fit": {"status": 0, "cov_qual": 3, "edm": 1e-6, "min_nll": 0.0},
        "r": r,
        "floating_parameters": [r],
    }


def make_archive(base: Path, *, halfmax_r: float) -> Path:
    result = base / PREFIX
    area = result / "area"
    area.mkdir(parents=True)
    payloads: dict[str, bytes] = {}
    for name in expected_area():
        if name.endswith(".root"):
            payloads[name] = b"root synthetic\n"
        elif name == "fit_zero.json":
            payloads[name] = (json.dumps(fit_record("zero", 0.0)) + "\n").encode()
        elif name == "fit_halfmax.json":
            payloads[name] = (json.dumps(fit_record("halfmax", halfmax_r)) + "\n").encode()
        elif name.endswith("_validation.log"):
            payloads[name] = b"FIT CHECK: status=0 covQual=3 EDM=1e-06\n"
        else:
            payloads[name] = f"synthetic {name}\n".encode()
        (area / name).write_bytes(payloads[name])
    status = {
        "exit_code": "0", "terminal_stage": "complete", "width": "1", "mass_GeV": "2000",
        "rMax": "1", "closure_hypothesis": "background_only", "rInject": "0",
        "dataset_scope": "synthetic_asimov_only", "pass_region_masks": "all_off_frozen",
        "r_floating": "1", "rMin": "0", "start_zero": "0", "start_halfmax": "0.5",
        "fit_count": "2", "fit_start_mode": "independent_requested_seed_robust_impacts_initialfit",
        "bootstrap_seed_policy": "no_bootstrap_independent_per_start",
        "final_nuisance_start": "physical_masked_snapshot_no_override",
        "rpf_range_override": "none", "toy_seed": "123456",
        "snapshot_sha256": "1" * 64, "payload_sha256": "2" * 64, "runtime_sha256": "3" * 64,
    }
    (result / "status.txt").write_text("".join(f"{key}={value}\n" for key, value in status.items()))
    (result / "artifact_hashes.sha256").write_text(
        "".join(f"{digest(payloads[name])}  area/{name}\n" for name in sorted(payloads))
    )
    archive = base / "result.tgz"
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(result, arcname=PREFIX)
    return archive


def main() -> int:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        good = make_archive(base / "good", halfmax_r=0.0)
        validated = validate_archive(good)
        assert validated["seed_delta_combined_sigma"] == 0.0
        bad = make_archive(base / "bad", halfmax_r=0.02)
        try:
            validate_archive(bad)
        except ValueError:
            pass
        else:
            raise AssertionError("biased closure archive was accepted")
    print("BACKGROUND_CLOSURE_HARVEST_TEST_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
