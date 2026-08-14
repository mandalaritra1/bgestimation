#!/usr/bin/env python3
"""Static command-boundary tests for the one-nuisance Asimov Impacts canary."""

from __future__ import annotations

from pathlib import Path
import re


HERE = Path(__file__).resolve().parent


def main() -> int:
    worker = (HERE / "asimov_impacts_portable_job.sh").read_text()
    builder = (HERE / "build_portable_asimov_impacts_payload.sh").read_text()
    validator = (HERE / "validate_portable_asimov_impacts.py").read_text()
    harvester = (HERE / "harvest_portable_asimov_impacts.py").read_text()
    submit = (HERE / "asimov_impacts_portable_canary.sub").read_text()

    assert "/uscms" not in worker and "/uscms_data" not in worker
    assert worker.count("combineTool.py \"${COMMON[@]}\"") == 3
    assert "--doInitialFit" in worker and "--doFits" in worker and "-o impacts_lumi24.json" in worker
    assert "--named \"${NUISANCE}\"" in worker and "--redefineSignalPOIs r" in worker
    assert "-t -1 -s \"${TOY_SEED}\" --expectSignal \"${RINJECT}\" --bypassFrequentistFit" in worker
    assert '--setParameters "r=${RINJECT},${M_OFF}"' in worker
    assert worker.count('--freezeParameters "${M_FRZ}"') == 1
    assert '--freezeParameters "r,' not in worker
    assert '--rMin 0 --rMax "${RMAX}"' in worker and "setParameterRanges" not in worker
    assert "text2workspace" not in worker and "card.txt" not in worker
    assert "observed" not in worker.lower() and "data_obs" not in worker.lower()
    assert worker.count("normalize_seeded_result") == 3  # definition plus two required normalizations
    assert "multidimfit_initialFit_${IMPACTS_NAME}.root" in worker
    assert "multidimfit_paramFit_${IMPACTS_NAME}_${NUISANCE}.root" not in worker
    assert 'parameter-fit "${PARAM_ROOT}"' in worker
    assert "trap finalize_result EXIT" in worker and "artifact_hashes.sha256" in worker

    assert builder.count("higgsCombine_maskedBonly.MultiDimFit.mH0.root") == 1
    assert "card.txt" not in builder and "base.root" not in builder
    assert "validate_portable_asimov_impacts.py" in builder
    assert "refusing to overwrite payload" in builder
    assert "MODEL_NUISANCES = (\"lumi24\", \"lumi25\", \"ttbar_xsec\")" in validator
    assert "expected 18 RPF variables" in validator
    assert "Impacts POI is not exactly r" in validator
    assert "Impacts nuisance is not exactly lumi24" in validator
    assert "unexpected archive file set" in harvester
    assert "forbidden non-synthetic marker" in harvester
    assert "queue 1" in submit
    assert "asimov_impacts_payload_w1_m2000.tgz" in submit
    assert "workspace_runtime_overlay_20260811_v1.tgz" in submit
    assert "use_x509userproxy = false" in submit
    print("ASIMOV_IMPACTS_PORTABLE_CONTRACT_TEST_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
