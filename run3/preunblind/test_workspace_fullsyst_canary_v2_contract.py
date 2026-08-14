#!/usr/bin/env python3
"""Static contract test for the two-point full-systematics workspace canary."""

from __future__ import annotations

from pathlib import Path


HERE = Path(__file__).resolve().parent
MATRIX = HERE / "workspace_fullsyst_canary_v2.tsv"
SUBMIT = HERE / "workspace_portable_fullsyst_canary_v2.sub"


def main() -> int:
    matrix_text = MATRIX.read_text()
    assert matrix_text == "cen2425 1 2000\nfwd2425 1 2000\n"
    points = [tuple(line.split()) for line in matrix_text.splitlines()]
    assert points == [("cen2425", "1", "2000"), ("fwd2425", "1", "2000")]
    assert len(points) == len(set(points)) == 2

    submit = SUBMIT.read_text()
    assert "arguments = workspace_portable_job.sh $(category) $(width) $(mass)" in submit
    assert (
        "fullsyst_canary_v2/payloads/"
        "workspace_payload_$(category)_w$(width)_m$(mass).tgz"
    ) in submit
    assert "workspace_runtime_overlay_20260811_v1.tgz" in submit
    assert "workspace_fullsyst_canary_v2.tsv" in submit

    remap_template = (
        "fullsyst_canary_v2/workspaces/portable_results/"
        "$(category)_w$(width)_m$(mass).tgz"
    )
    assert remap_template in submit
    remaps = {
        remap_template.replace("$(category)", category)
        .replace("$(width)", width)
        .replace("$(mass)", mass)
        for category, width, mass in points
    }
    assert remaps == {
        "fullsyst_canary_v2/workspaces/portable_results/cen2425_w1_m2000.tgz",
        "fullsyst_canary_v2/workspaces/portable_results/fwd2425_w1_m2000.tgz",
    }
    assert len(remaps) == 2

    print("WORKSPACE_FULLSYST_CANARY_V2_CONTRACT_TEST_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
