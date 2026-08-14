#!/usr/bin/env python3
"""Static contract test for the isolated ttag_pt1-freeze diagnostic."""

from __future__ import annotations

from pathlib import Path
import re


HERE = Path(__file__).resolve().parent
WORKER = HERE / "combine_bootstrap_freeze_ttag_pt1_v1_job.sh"
SUBMIT = HERE / "combine_bootstrap_freeze_ttag_pt1_v1.sub"


def assignment(script: str, name: str) -> str:
    match = re.search(rf'^{name}="([^"]+)"$', script, flags=re.MULTILINE)
    assert match, f"missing {name} assignment"
    return match.group(1)


def main() -> int:
    worker = WORKER.read_text()
    submit = SUBMIT.read_text()

    assert worker.count("combine -M MultiDimFit") == 1
    assert "AsymptoticLimits" not in worker
    assert "--run observed" not in worker
    assert "--run blind" not in worker
    assert "--snapshotName" not in worker

    mask_names = assignment(worker, "M_FRZ").split(",")
    assert mask_names == [
        "mask_cen_Cen24Pass_Region1",
        "mask_cen_Cen25Pass_Region1",
        "mask_fwd_Fwd24Pass_Region1",
        "mask_fwd_Fwd25Pass_Region1",
    ]
    freeze_match = re.search(r'--freezeParameters "([^"]+)"', worker)
    assert freeze_match
    frozen = freeze_match.group(1).replace("${M_FRZ}", ",".join(mask_names)).split(",")
    baseline_frozen = {"r", *mask_names}
    assert set(frozen) - baseline_frozen == {"ttag_pt1"}
    assert len(frozen) == len(baseline_frozen) + 1

    mask_values = assignment(worker, "M_ON").split(",")
    assert mask_values == [f"{name}=1" for name in mask_names]
    assert '--setParameters "r=0,${M_ON},ttag_pt1=0"' in worker
    assert "--setParameterRanges 'rgx{.*rpf_par.*}=-50,50'" in worker
    assert worker.count("--freezeParameters") == 1
    assert "trap finalize_result EXIT" in worker
    assert '"${AREA}"/*bootstrap*.root' in worker
    assert "diagnostic.status" in worker
    assert "artifact_sha256[" in worker

    assert "arguments = combine_bootstrap_freeze_ttag_pt1_v1_job.sh 1 2000 1" in submit
    assert submit.count("queue 1") == 1
    assert (
        "fullsyst_canary_v1/payloads/combine_payload_w1_m2000.tgz"
    ) in submit
    assert "workspace_runtime_overlay_20260811_v1.tgz" in submit
    namespace = "fullsyst_canary_v1/diagnostics/freeze_ttag_pt1_v1"
    remap_lines = [line for line in submit.splitlines() if line.startswith("transfer_output_remaps")]
    assert remap_lines == [
        'transfer_output_remaps = "freeze_ttag_pt1_v1_result.tgz = '
        f'{namespace}/w1_m2000.tgz"'
    ]
    log_lines = [
        line for line in submit.splitlines()
        if line.startswith(("output =", "error =", "log ="))
    ]
    assert len(log_lines) == 3
    assert all(f"/{namespace}/logs/" in line for line in log_lines)

    print("COMBINE_BOOTSTRAP_FREEZE_TTAG_PT1_V1_CONTRACT_TEST_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
