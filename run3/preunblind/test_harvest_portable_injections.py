#!/usr/bin/env python3
"""Synthetic success and failure tests for the injection result harvester."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile


HERE = Path(__file__).resolve().parent
HARVESTER = HERE / "harvest_portable_injections.py"
ROW = ["1", "2000", "1", "one", "0.2", "0", "0.2", "0.5"]


def fit_json(
    start: str, start_r: str, constant: bool = False, fit_key: str = "fit_s"
) -> bytes:
    r = {"name": "r", "value": 0.21, "error": 0.03, "error_low": None, "error_high": None,
         "min": 0.0, "max": 1.0, "constant": constant, "boundary": {}}
    record = {
        "fit_key": fit_key,
        "input": f"/scratch/fitDiagnostics_fit_{start}.root",
        "metadata": {"width_percent": "1", "mass_GeV": "2000", "rMax": "1",
                     "injection_label": "one", "injected_r": "0.2", "start_label": start, "start_r": start_r},
        "fit": {"status": 0, "cov_qual": 3, "edm": 0.0001, "min_nll": 12.3},
        "r": r,
        "floating_parameters": [r],
    }
    return (json.dumps(record, sort_keys=True) + "\n").encode()


def add(archive: tarfile.TarFile, name: str, payload: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    archive.addfile(info, io.BytesIO(payload))


def write_result(
    path: Path,
    constant_start: str | None = None,
    corrupt_hash: bool = False,
    third_start_label: str = "halfmax",
    fit_method: str = "fitdiagnostics",
) -> None:
    starts = {"zero": "0", "injected": "0.2", third_start_label: "0.5"}
    artifacts: dict[str, bytes] = {
        "area/higgsCombine_gen.GenerateOnly.mH0.123456.root": b"root toy",
    }
    for start, start_r in starts.items():
        if fit_method == "fitdiagnostics":
            fit_root = f"area/fitDiagnostics_fit_{start}.root"
            ancillary = f"area/higgsCombine_fit_{start}.FitDiagnostics.mH0.root"
            fit_key = "fit_s"
            fit_start_mode = "snapshot_direct_no_prescan"
        elif fit_method in {"robustinitial", "robustinitial_noexpect"}:
            fit_name = f"injection_w1_m2000_one_{start}"
            fit_root = f"area/multidimfit_initialFit_{fit_name}.root"
            ancillary = f"area/higgsCombine_initialFit_{fit_name}.MultiDimFit.mH0.root"
            fit_key = "fit_mdf"
            fit_start_mode = (
                "independent_requested_seed_robust_impacts_initialfit"
                if fit_method == "robustinitial_noexpect"
                else "independent_robust_impacts_initialfit"
            )
        else:
            fit_root = f"area/multidimfit_fit_{start}.root"
            ancillary = f"area/higgsCombine_fit_{start}.MultiDimFit.mH0.root"
            fit_key = "fit_mdf"
            fit_start_mode = (
                "independent_fixed_r_bootstrap_then_physical_multidimfit"
                if fit_method == "twostage"
                else (
                    "snapshot_direct_requested_seed_multidimfit_poionly_robusthesse"
                    if fit_method == "multidimfit_poionly_robusthesse"
                    else (
                        "snapshot_direct_requested_seed_multidimfit_poionly_prefit"
                        if fit_method == "multidimfit_poionly"
                        else "snapshot_direct_multidimfit_algo_none"
                    )
                )
            )
        artifacts[fit_root] = b"root fit " + start.encode()
        artifacts[ancillary] = b"root ancillary " + start.encode()
        artifacts[f"area/fit_{start}_validation.log"] = b"FIT CHECK: status=0 covQual=3 EDM=0.0001\n"
        artifacts[f"area/fit_{start}.json"] = fit_json(
            start, start_r, constant=start == constant_start, fit_key=fit_key
        )
        if fit_method == "twostage":
            artifacts[f"area/fit_{start}_range_validation.log"] = (
                b"INJECTION RANGE CHECK: status=0 r_floating=1 masks_off_frozen=4 "
                b"rpf_count=18 positive_par0=4\n"
            )
    if fit_method == "twostage":
        for start in starts:
            artifacts[f"area/multidimfit_bootstrap_{start}.root"] = b"root bootstrap fit " + start.encode()
            artifacts[f"area/higgsCombine_bootstrap_{start}.MultiDimFit.mH0.root"] = b"root bootstrap snapshot " + start.encode()
            artifacts[f"area/bootstrap_{start}_validation.log"] = b"FIT CHECK: status=0 covQual=3 EDM=0.0001\n"
    hashes = []
    for index, (name, payload) in enumerate(sorted(artifacts.items())):
        digest = hashlib.sha256(payload).hexdigest()
        if corrupt_hash and index == 0:
            digest = "0" * 64
        hashes.append(f"{digest}  {name}")
    status = {
        "exit_code": "0", "terminal_stage": "complete", "width": "1", "mass_GeV": "2000",
        "rMax": "1", "injection_label": "one", "injected_r": "0.2", "start_zero": "0",
        "start_injected": "0.2", f"start_{third_start_label}": "0.5",
        "bootstrap_seed_policy": (
            "no_bootstrap_independent_per_start"
            if fit_method in {"robustinitial", "robustinitial_noexpect", "multidimfit_poionly", "multidimfit_poionly_robusthesse"}
            else "independent_per_start"
        ),
        "final_nuisance_start": (
            "physical_masked_snapshot_no_override"
            if fit_method in {"robustinitial", "robustinitial_noexpect", "multidimfit_poionly", "multidimfit_poionly_robusthesse"}
            else "matching_bootstrap_snapshot_no_override"
        ),
        "payload_sha256": "synthetic",
        "runtime_sha256": "synthetic", "fit_start_mode": fit_start_mode,
    }
    with tarfile.open(path, "w:gz") as archive:
        add(archive, "injection_result/status.txt", "\n".join(f"{k}={v}" for k, v in status.items()).encode())
        add(archive, "injection_result/artifact_hashes.sha256", ("\n".join(hashes) + "\n").encode())
        for name, payload in artifacts.items():
            add(archive, f"injection_result/{name}", payload)


def run(campaign: Path, ledger: Path, source: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(HARVESTER), "--campaign", str(campaign), "--ledger", str(ledger),
                           "--fit-method", "fitdiagnostics", "--row", *ROW,
                           "--input", str(source)], text=True, capture_output=True, check=False)


def validate_only(campaign: Path, source: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HARVESTER), "--campaign", str(campaign), "--validate-only",
         "--fit-method", "fitdiagnostics", "--row", *ROW, "--input", str(source)],
        text=True, capture_output=True, check=False,
    )


def validate_legacy_high(campaign: Path, source: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HARVESTER), "--campaign", str(campaign), "--validate-only",
         "--third-start-label", "high", "--fit-method", "fitdiagnostics",
         "--row", *ROW, "--input", str(source)],
        text=True, capture_output=True, check=False,
    )


def main() -> int:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        good = root / "good.tgz"
        write_result(good)
        checked = validate_only(root / "validation_campaign", good)
        assert checked.returncode == 0, checked.stderr
        assert not (root / "validation_campaign/injections").exists()
        legacy = root / "legacy_high.tgz"
        write_result(legacy, third_start_label="high")
        checked_legacy = validate_legacy_high(root / "legacy_validation", legacy)
        assert checked_legacy.returncode == 0, checked_legacy.stderr
        multidimfit = root / "multidimfit.tgz"
        write_result(multidimfit, fit_method="multidimfit")
        checked_multidimfit = subprocess.run(
            [sys.executable, str(HARVESTER), "--campaign", str(root / "mdf_validation"),
             "--validate-only", "--fit-method", "multidimfit",
             "--row", *ROW, "--input", str(multidimfit)],
            text=True, capture_output=True, check=False,
        )
        assert checked_multidimfit.returncode == 0, checked_multidimfit.stderr
        multidimfit_poionly = root / "multidimfit_poionly.tgz"
        write_result(multidimfit_poionly, fit_method="multidimfit_poionly")
        checked_multidimfit_poionly = subprocess.run(
            [sys.executable, str(HARVESTER), "--campaign", str(root / "mdf_poionly_validation"),
             "--validate-only", "--fit-method", "multidimfit_poionly",
             "--row", *ROW, "--input", str(multidimfit_poionly)],
            text=True, capture_output=True, check=False,
        )
        assert checked_multidimfit_poionly.returncode == 0, checked_multidimfit_poionly.stderr
        multidimfit_poionly_robusthesse = root / "multidimfit_poionly_robusthesse.tgz"
        write_result(multidimfit_poionly_robusthesse, fit_method="multidimfit_poionly_robusthesse")
        checked_multidimfit_poionly_robusthesse = subprocess.run(
            [sys.executable, str(HARVESTER), "--campaign", str(root / "mdf_poionly_robusthesse_validation"),
             "--validate-only", "--fit-method", "multidimfit_poionly_robusthesse",
             "--row", *ROW, "--input", str(multidimfit_poionly_robusthesse)],
            text=True, capture_output=True, check=False,
        )
        assert checked_multidimfit_poionly_robusthesse.returncode == 0, checked_multidimfit_poionly_robusthesse.stderr
        robustinitial = root / "robustinitial.tgz"
        write_result(robustinitial, fit_method="robustinitial")
        checked_robustinitial = subprocess.run(
            [sys.executable, str(HARVESTER), "--campaign", str(root / "robust_validation"),
             "--validate-only", "--fit-method", "robustinitial",
             "--row", *ROW, "--input", str(robustinitial)],
            text=True, capture_output=True, check=False,
        )
        assert checked_robustinitial.returncode == 0, checked_robustinitial.stderr
        robustinitial_noexpect = root / "robustinitial_noexpect.tgz"
        write_result(robustinitial_noexpect, fit_method="robustinitial_noexpect")
        checked_robustinitial_noexpect = subprocess.run(
            [sys.executable, str(HARVESTER), "--campaign", str(root / "robust_noexpect_validation"),
             "--validate-only", "--fit-method", "robustinitial_noexpect",
             "--row", *ROW, "--input", str(robustinitial_noexpect)],
            text=True, capture_output=True, check=False,
        )
        assert checked_robustinitial_noexpect.returncode == 0, checked_robustinitial_noexpect.stderr
        twostage = root / "twostage.tgz"
        write_result(twostage, fit_method="twostage")
        checked_twostage = subprocess.run(
            [sys.executable, str(HARVESTER), "--campaign", str(root / "twostage_validation"),
             "--validate-only", "--fit-method", "twostage",
             "--row", *ROW, "--input", str(twostage)],
            text=True, capture_output=True, check=False,
        )
        assert checked_twostage.returncode == 0, checked_twostage.stderr
        result = run(root / "campaign", root / "ledger.json", good)
        assert result.returncode == 0, result.stderr
        destination = root / "campaign/injections/asimov/w1/m2000/one"
        assert (destination / "fit_zero.json").is_file()
        assert json.loads((root / "ledger.json").read_text())["records"][0]["fits"]["zero"]["r"] == 0.21

        constant = root / "constant.tgz"
        write_result(constant, constant_start="injected")
        rejected = run(root / "constant_campaign", root / "constant.json", constant)
        assert rejected.returncode == 2 and "constant" in rejected.stderr

        bad_hash = root / "bad_hash.tgz"
        write_result(bad_hash, corrupt_hash=True)
        rejected = run(root / "hash_campaign", root / "hash.json", bad_hash)
        assert rejected.returncode == 2 and "hash mismatch" in rejected.stderr
    print("HARVEST_PORTABLE_INJECTIONS_TEST_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
