#!/usr/bin/env python3
"""Static command-boundary tests for the portable masked-GoF canary."""

from __future__ import annotations

from pathlib import Path
import re


HERE = Path(__file__).resolve().parent


def main() -> int:
    worker = (HERE / "gof_portable_job.sh").read_text()
    builder = (HERE / "build_portable_gof_payload.sh").read_text()
    submit = (HERE / "gof_portable_canary.sub").read_text()

    assert "/uscms" not in worker and "/uscms_data" not in worker
    assert worker.count("combine -M GoodnessOfFit") == 2
    assert worker.count("--algo saturated") == 2
    assert worker.count('--snapshotName MultiDimFit') == 2
    assert worker.count('--setParameters "r=0,${M_ON}"') == 2
    assert worker.count('--freezeParameters "r,${M_FRZ}"') == 2
    assert worker.count("--toysFrequentist") == 1
    assert "text2workspace" not in worker
    assert "setParameterRanges" not in worker
    assert "M_OFF" not in worker
    assert "unmask" not in worker.lower()
    assert not re.search(r"mask_(?:cen|fwd)_[A-Za-z0-9_]*Pass_Region1\s*=\s*0", worker)
    for mask in (
        "mask_cen_Cen24Pass_Region1=1",
        "mask_cen_Cen25Pass_Region1=1",
        "mask_fwd_Fwd24Pass_Region1=1",
        "mask_fwd_Fwd25Pass_Region1=1",
    ):
        assert worker.count(mask) == 1
    assert "trap finalize_result EXIT" in worker
    assert "artifact_hashes.sha256" in worker
    assert "data_scope=observed_sideband_only" in worker
    assert "pass_region_masks=all_on_frozen" in worker
    assert "r_state=fixed_zero" in worker

    assert "card.txt" not in builder and "base.root" not in builder
    assert builder.count("higgsCombine_maskedBonly.MultiDimFit.mH0.root") == 1
    assert "validate_portable_gof.py" in builder
    assert "refusing to overwrite payload" in builder

    assert "arguments = gof_portable_job.sh 1 2000 1 314159 5" in submit
    assert "queue 1" in submit
    arguments = next(line for line in submit.splitlines() if line.startswith("arguments"))
    assert arguments.split()[-1] == "5"
    assert "use_x509userproxy = false" in submit
    assert "when_to_transfer_output = ON_EXIT" in submit
    print("PORTABLE_GOF_CONTRACT_TEST_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
