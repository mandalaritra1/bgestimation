#!/usr/bin/env python3
"""Synthetic structure and static command-boundary tests for portable injections."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile


HERE = Path(__file__).resolve().parent


def load_validator():
    path = HERE / "validate_injection_matrix.py"
    spec = importlib.util.spec_from_file_location("validate_injection_matrix", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    wrapper = (HERE / "injection_portable_job.sh").read_text()
    assert "/uscms" not in wrapper and "/uscms_data" not in wrapper
    assert wrapper.count("combine -M GenerateOnly") == 1
    assert wrapper.count("combine -M MultiDimFit") == 1
    assert "--algo none" in wrapper and "--cminPoiOnlyFit" in wrapper
    assert "--cminPreScan --cminPreFit 1" in wrapper
    assert "FitDiagnostics" not in wrapper
    assert "snapshot_direct_requested_seed_multidimfit_poionly_robusthesse" in wrapper
    assert '--setParameters "r=${start_value},${M_OFF}"' in wrapper
    fit_block = wrapper.split("run_fit() {", 1)[1].split("run_fit zero", 1)[0]
    assert "--expectSignal" not in fit_block
    assert wrapper.count("--expectSignal") == 1
    assert "bootstrap_seed_policy=no_bootstrap_independent_per_start" in wrapper
    assert "final_nuisance_start=physical_masked_snapshot_no_override" in wrapper
    assert "INTERIOR_BOUNDARY_START" not in wrapper
    assert "-t -1 -s 123456 --saveToys" in wrapper
    assert '-t -1 -s 123456 --toysFile "${TOY}"' in wrapper
    assert "--robustHesse 1" in wrapper
    assert '--freezeParameters "r,${M_FRZ}"' not in wrapper
    assert wrapper.count('--freezeParameters "${M_FRZ}"') == 2
    assert "setParameterRanges" not in wrapper
    assert 'higgsCombine_fit_${start_label}.MultiDimFit.mH0.root' in wrapper
    assert wrapper.count("run_fit zero") == 1
    assert wrapper.count("run_fit injected") == 1
    assert wrapper.count("run_fit halfmax") == 1
    assert 'trap finalize_result EXIT' in wrapper
    assert "artifact_hashes.sha256" in wrapper
    assert "observed" not in wrapper.lower()

    validator = load_validator()
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        points = root / "points.tsv"
        matrix = root / "matrix.tsv"
        source_points = (HERE / "points.tsv").read_text()
        points.write_text(source_points)
        rows = []
        for raw in source_points.splitlines():
            if not raw.strip():
                continue
            width, mass, rmax = raw.split()
            numeric_rmax = float(rmax)
            for label, scale in (("bkg", 0.0), ("half", 0.05), ("one", 0.1), ("two", 0.2)):
                injected = f"{scale * numeric_rmax:.12g}"
                rows.append(f"{width} {mass} {rmax} {label} {injected} 0 {injected} {0.5 * numeric_rmax:.12g}\n")
        matrix.write_text("".join(rows))
        assert validator.validate(points, matrix) == (48, 144)
        matrix.write_text("".join(rows[:-1]))
        try:
            validator.validate(points, matrix)
        except ValueError:
            pass
        else:
            raise AssertionError("47-row matrix was not rejected")
    print("INJECTION_PORTABLE_CONTRACT_TEST_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
