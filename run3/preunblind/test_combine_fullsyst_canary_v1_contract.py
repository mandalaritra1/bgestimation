#!/usr/bin/env python3
"""Static contract test for the one-point full-systematics combined canary."""

from __future__ import annotations

from pathlib import Path


HERE = Path(__file__).resolve().parent
MATRIX = HERE / "combine_fullsyst_canary_v1.tsv"
SUBMIT = HERE / "combine_portable_fullsyst_canary_v1.sub"
WORKER = HERE / "combine_portable_job_fullsyst_v1.sh"
if not WORKER.exists():
    # The reviewed source stays generic locally; deployment pins an immutable
    # versioned copy so the submit descriptor cannot pick up a stale worker.
    WORKER = HERE / "combine_portable_job.sh"


def main() -> int:
    points = [tuple(line.split()) for line in MATRIX.read_text().splitlines() if line.strip()]
    assert points == [("1", "2000", "1")]
    assert len(points) == len(set(points)) == 1

    submit = SUBMIT.read_text()
    assert "arguments = combine_portable_job_fullsyst_v1.sh $(width) $(mass) $(rmax)" in submit
    assert "combine_portable_job_fullsyst_v1.sh," in submit
    assert (
        "fullsyst_canary_v1/payloads/"
        "combine_payload_w$(width)_m$(mass).tgz"
    ) in submit
    assert "workspace_runtime_overlay_20260811_v1.tgz" in submit
    assert "combine_fullsyst_canary_v1.tsv" in submit

    remap_template = (
        "fullsyst_canary_v1/workspaces/portable_combined_results/"
        "w$(width)_m$(mass).tgz"
    )
    remap_lines = [line for line in submit.splitlines() if line.startswith("transfer_output_remaps")]
    assert remap_lines == [f'transfer_output_remaps = "combine_result.tgz = {remap_template}"']
    remaps = {
        remap_template.replace("$(width)", width).replace("$(mass)", mass)
        for width, mass, _rmax in points
    }
    assert remaps == {
        "fullsyst_canary_v1/workspaces/portable_combined_results/w1_m2000.tgz"
    }
    assert len(remaps) == 1
    log_lines = [
        line for line in submit.splitlines()
        if line.startswith(("output =", "error =", "log ="))
    ]
    assert len(log_lines) == 3
    assert all("/fullsyst_canary_v1/logs/" in line for line in log_lines)

    worker = WORKER.read_text()
    assert "BKG_FIT_START_MODE=\"wide_bootstrap_then_physical_refit\"" in worker
    assert "higgsCombine_bootstrap.MultiDimFit.mH0.root" in worker
    assert "rgx{.*rpf_par0}=0.001,50" in worker
    assert worker.count("--run blind") == 1
    assert "--snapshotName MultiDimFit --run blind --bypassFrequentistFit" in worker
    assert "--run observed" not in worker

    print("COMBINE_FULLSYST_CANARY_V1_CONTRACT_TEST_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
