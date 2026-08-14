#!/usr/bin/env python3
"""Static physics-boundary checks for the two-start b-only closure canary."""

from pathlib import Path


HERE = Path(__file__).resolve().parent


def main() -> int:
    worker = (HERE / "background_closure_portable_job.sh").read_text()
    harvester = (HERE / "harvest_portable_background_closure.py").read_text()
    submit = (HERE / "background_closure_portable_canary.sub").read_text()
    assert "/uscms" not in worker and "/uscms_data" not in worker
    assert worker.count("combine -M GenerateOnly") == 1
    assert '--expectSignal 0' in worker
    assert worker.count("run_fit zero") == 1
    assert worker.count("run_fit halfmax") == 1
    assert "run_fit injected" not in worker
    assert worker.count("combineTool.py -M Impacts") == 1
    assert "--robustFit 1 --saveFitResult" in worker and "--doInitialFit" in worker
    assert '--setParameters "r=${start_value},${M_OFF}"' in worker
    fit_block = worker.split("run_fit() {", 1)[1].split("run_fit zero", 1)[0]
    assert "--expectSignal" not in fit_block
    assert worker.count("--expectSignal") == 1
    assert "independent_requested_seed_robust_impacts_initialfit" in worker
    assert '--freezeParameters "${M_FRZ}"' in worker
    assert "freezeParameters r" not in worker and "setParameterRanges" not in worker
    assert "rpf_range_override=none" in worker
    assert "fit_count=2" in worker
    assert "data_obs" not in worker and "observed" not in worker.lower()
    assert "zero_pull > 0.1" in harvester
    assert "seed_delta_sigma > 0.1" in harvester and "delta_min_nll > 1.0e-3" in harvester
    assert 'STARTS = ("zero", "halfmax")' in harvester
    assert "queue 1" in submit and "background_closure_portable_job_v1.sh" in submit
    print("BACKGROUND_CLOSURE_CONTRACT_TEST_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
