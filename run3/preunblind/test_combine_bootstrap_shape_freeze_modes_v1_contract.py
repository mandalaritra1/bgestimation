#!/usr/bin/env python3
"""Static contract test for the three prescribed shape-freeze diagnostics."""

from __future__ import annotations

from pathlib import Path
import re


HERE = Path(__file__).resolve().parent
WORKER = HERE / "combine_bootstrap_shape_freeze_modes_v1_job.sh"
MATRIX = HERE / "combine_bootstrap_shape_freeze_modes_v1.tsv"
SUBMIT = HERE / "combine_bootstrap_shape_freeze_modes_v1.sub"

EXPECTED = {
    "all_shapes_frozen": {
        "frozen": "jes,jer,pileup,pdf,q2,ttag_pt1",
        "values": "jes=0,jer=0,pileup=0,pdf=0,q2=0,ttag_pt1=0",
        "floating": "none",
    },
    "theory_only_floating": {
        "frozen": "jes,jer,pileup,ttag_pt1",
        "values": "jes=0,jer=0,pileup=0,ttag_pt1=0",
        "floating": "pdf,q2",
    },
    "experimental_only_floating": {
        "frozen": "pdf,q2",
        "values": "pdf=0,q2=0",
        "floating": "jes,jer,pileup,ttag_pt1",
    },
}


def assignment(block: str, name: str) -> str:
    match = re.search(rf'^\s*{name}="([^"]+)"$', block, flags=re.MULTILINE)
    assert match, f"missing {name} assignment"
    return match.group(1)


def main() -> int:
    worker = WORKER.read_text()
    submit = SUBMIT.read_text()
    points = [tuple(line.split()) for line in MATRIX.read_text().splitlines() if line.strip()]

    assert points == [
        ("all_shapes_frozen", "1", "2000", "1"),
        ("theory_only_floating", "1", "2000", "1"),
        ("experimental_only_floating", "1", "2000", "1"),
    ]
    assert len(points) == len(set(points)) == 3
    assert assignment(worker, "ALL_SHAPE_NUISANCES") == "jes,jer,pileup,pdf,q2,ttag_pt1"

    case_modes = set(re.findall(r'^    ([a-z_]+)\)$', worker, flags=re.MULTILINE))
    assert case_modes == set(EXPECTED)
    for mode, expected in EXPECTED.items():
        match = re.search(
            rf'^    {mode}\)$(.*?)^        ;;$',
            worker,
            flags=re.MULTILINE | re.DOTALL,
        )
        assert match, f"missing case block for {mode}"
        block = match.group(1)
        assert assignment(block, "FROZEN_SHAPES") == expected["frozen"]
        assert assignment(block, "FROZEN_SHAPE_VALUES") == expected["values"]
        assert assignment(block, "FLOATING_SHAPES") == expected["floating"]
        frozen_names = expected["frozen"].split(",")
        frozen_values = [item.split("=", 1)[0] for item in expected["values"].split(",")]
        assert frozen_names == frozen_values

    mask_names = assignment(worker, "M_FRZ").split(",")
    assert mask_names == [
        "mask_cen_Cen24Pass_Region1",
        "mask_cen_Cen25Pass_Region1",
        "mask_fwd_Fwd24Pass_Region1",
        "mask_fwd_Fwd25Pass_Region1",
    ]
    assert assignment(worker, "M_ON").split(",") == [
        f"{name}=1" for name in mask_names
    ]
    assert worker.count("combine -M MultiDimFit") == 1
    assert worker.count("--freezeParameters") == 1
    assert '--freezeParameters "r,${M_FRZ},${FROZEN_SHAPES}"' in worker
    assert '--setParameters "r=0,${M_ON},${FROZEN_SHAPE_VALUES}"' in worker
    assert "--setParameterRanges 'rgx{.*rpf_par.*}=-50,50'" in worker
    assert "AsymptoticLimits" not in worker
    assert "--run observed" not in worker
    assert "--run blind" not in worker
    assert "--snapshotName" not in worker
    assert "trap finalize_result EXIT" in worker
    assert '"${AREA}"/*bootstrap*.root' in worker
    assert "mode=${MODE}" in worker
    assert "all_shape_nuisances=${ALL_SHAPE_NUISANCES}" in worker
    assert "frozen_shape_nuisances=${FROZEN_SHAPES}" in worker
    assert "frozen_shape_values=${FROZEN_SHAPE_VALUES}" in worker
    assert "floating_shape_nuisances=${FLOATING_SHAPES}" in worker

    assert (
        "arguments = combine_bootstrap_shape_freeze_modes_v1_job.sh "
        "$(mode) $(width) $(mass) $(rmax)"
    ) in submit
    assert "fullsyst_canary_v1/payloads/combine_payload_w1_m2000.tgz" in submit
    assert "workspace_runtime_overlay_20260811_v1.tgz" in submit
    assert "combine_bootstrap_shape_freeze_modes_v1.tsv" in submit

    namespace = "fullsyst_canary_v1/diagnostics/shape_freeze_modes_v1"
    remap_template = f"{namespace}/$(mode)/w$(width)_m$(mass).tgz"
    remap_lines = [line for line in submit.splitlines() if line.startswith("transfer_output_remaps")]
    assert remap_lines == [
        'transfer_output_remaps = "shape_freeze_modes_v1_result.tgz = '
        f'{remap_template}"'
    ]
    remaps = {
        remap_template.replace("$(mode)", mode)
        .replace("$(width)", width)
        .replace("$(mass)", mass)
        for mode, width, mass, _rmax in points
    }
    assert remaps == {
        f"{namespace}/all_shapes_frozen/w1_m2000.tgz",
        f"{namespace}/theory_only_floating/w1_m2000.tgz",
        f"{namespace}/experimental_only_floating/w1_m2000.tgz",
    }
    assert len(remaps) == 3
    log_lines = [
        line for line in submit.splitlines()
        if line.startswith(("output =", "error ="))
    ]
    assert len(log_lines) == 2
    assert all(f"/{namespace}/$(mode)/logs/" in line for line in log_lines)

    print("COMBINE_BOOTSTRAP_SHAPE_FREEZE_MODES_V1_CONTRACT_TEST_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
