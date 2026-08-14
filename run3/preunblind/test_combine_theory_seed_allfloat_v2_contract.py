#!/usr/bin/env python3
"""Static contract test for the staged all-systematic masked-fit diagnostic."""

from __future__ import annotations

from pathlib import Path
import re


HERE = Path(__file__).resolve().parent
WORKER = HERE / "combine_theory_seed_allfloat_v2_job.sh"
V1_WORKER = HERE / "combine_theory_seed_allfloat_v1_job.sh"
MATRIX = HERE / "combine_theory_seed_allfloat_v2.tsv"
SUBMIT = HERE / "combine_theory_seed_allfloat_v2.sub"


def assignment(script: str, name: str) -> str:
    match = re.search(rf'^\s*{name}="([^"]+)"$', script, flags=re.MULTILINE)
    assert match, f"missing {name} assignment"
    return match.group(1)


def inclusive_block(script: str, start: str, end: str) -> str:
    block_start = script.index(start)
    block_end = script.index(end, block_start) + len(end)
    return script[block_start:block_end]


def main() -> int:
    worker = WORKER.read_text()
    v1_worker = V1_WORKER.read_text()
    submit = SUBMIT.read_text()
    matrix_bytes = MATRIX.read_bytes()

    assert matrix_bytes == b"theory_seed_allfloat_v2 1 2000 1\n"
    assert matrix_bytes.count(b"\n") == 1
    assert b"\n\n" not in matrix_bytes
    assert set(re.findall(r'^    ([a-z0-9_]+)\)', worker, flags=re.MULTILINE)) == {
        "theory_seed_allfloat_v2"
    }
    assert assignment(worker, "STAGE1_FIXED_NUISANCES") == "jes,jer,pileup,ttag_pt1"
    assert assignment(worker, "STAGE1_FLOAT_NUISANCES") == "pdf,q2"
    assert assignment(worker, "STAGE2_FLOAT_NUISANCES") == "jes,jer,pileup,pdf,q2,ttag_pt1"

    mask_names = assignment(worker, "M_FRZ").split(",")
    assert mask_names == [
        "mask_cen_Cen24Pass_Region1",
        "mask_cen_Cen25Pass_Region1",
        "mask_fwd_Fwd24Pass_Region1",
        "mask_fwd_Fwd25Pass_Region1",
    ]
    assert assignment(worker, "M_ON").split(",") == [f"{name}=1" for name in mask_names]
    assert "mask_cen_Cen24Pass_Region1=0" not in worker
    assert "mask_cen_Cen25Pass_Region1=0" not in worker
    assert "mask_fwd_Fwd24Pass_Region1=0" not in worker
    assert "mask_fwd_Fwd25Pass_Region1=0" not in worker

    assert worker.count("combine -M MultiDimFit") == 2
    assert worker.count("--freezeParameters") == 2
    assert worker.count("--floatParameters") == 2
    assert '--setParameters "r=0,${M_ON},jes=0,jer=0,pileup=0,ttag_pt1=0"' in worker
    assert '--freezeParameters "r,${M_FRZ},jes,jer,pileup,ttag_pt1"' in worker
    assert '--floatParameters "pdf,q2"' in worker
    assert "--setParameterRanges 'rgx{.*rpf_par.*}=-50,50'" in worker

    stage1_start = "    combine -M MultiDimFit -d workspace.root -m 0 \\\n"
    stage1_end = "        > stage1_bootstrap_validation.log 2>&1"
    assert inclusive_block(worker, stage1_start, stage1_end) == inclusive_block(
        v1_worker, stage1_start, stage1_end
    )

    assert "-d higgsCombine_stage1.MultiDimFit.mH0.root" in worker
    assert "--snapshotName MultiDimFit -m 0" in worker
    assert assignment(worker, "INTERIOR_BOUNDARY_START") == (
        "QCD_Fwd24rpf_par2=-45,QCD_Fwd25rpf_par2=-45"
    )
    assert '--setParameters "r=0,${M_ON},${INTERIOR_BOUNDARY_START}"' in worker
    assert '--freezeParameters "r,${M_FRZ}"' in worker
    assert '--floatParameters "jes,jer,pileup,pdf,q2,ttag_pt1"' in worker
    assert "--setParameterRanges 'rgx{.*rpf_par0}=0.001,50'" in worker
    solver_line_v1 = "        --cminDefaultMinimizerStrategy 1 \\\n"
    solver_line_v2 = (
        "        --cminPreScan --cminPreFit 1 "
        "--cminDefaultMinimizerStrategy 2 \\\n"
    )
    stage2_start = (
        "    combine -M MultiDimFit \\\n"
        "        -d higgsCombine_stage1.MultiDimFit.mH0.root \\\n"
    )
    stage2_end = "        > stage2_allfloat.log 2>&1"
    v1_stage2 = inclusive_block(v1_worker, stage2_start, stage2_end)
    assert v1_stage2.count(solver_line_v1) == 1
    expected_stage2 = v1_stage2.replace(solver_line_v1, solver_line_v2)
    assert inclusive_block(worker, stage2_start, stage2_end) == expected_stage2
    assert worker.count(solver_line_v2) == 1
    assert "rpf_par1=" not in worker

    assert worker.count("validate_fit_result.py") == 2
    assert worker.count("--min-cov-qual 3 --max-edm 0.01") == 2
    assert 'nuisance_names = ("jes", "jer", "pileup", "pdf", "q2", "ttag_pt1")' in worker
    assert "if variable.isConstant():" in worker
    assert 'raise RuntimeError(f"stage-2 nuisance remained constant: {name}")' in worker
    assert 'if len(rpf_variables) != 18:' in worker
    assert 'expected_min = 0.001 if name.endswith("rpf_par0") else -50.0' in worker
    assert "if positive_constants != 4:" in worker

    assert 'combineCards.py cen="${CEN_CARD}" fwd="${FWD_CARD}" > "${CARD_NAME}"' in worker
    assert 'text2workspace.py "${CARD_NAME}" -o workspace.root --channel-masks --X-no-jmax' in worker
    assert "AsymptoticLimits" not in worker
    assert "--run observed" not in worker
    assert "--run blind" not in worker
    assert "M_OFF=" not in worker
    assert "sanitize" not in worker.lower()
    assert "card_change" not in worker
    assert "sed " not in worker
    assert "trap finalize_result EXIT" in worker
    assert '"${AREA}"/*stage1*.root' in worker
    assert '"${AREA}"/*stage2*.root' in worker
    assert 'THEORY_SEED_ALLFLOAT_V2_REFUSE_EXISTING area=${AREA}' in worker

    assert (
        "arguments = combine_theory_seed_allfloat_v2_job.sh "
        "$(mode) $(width) $(mass) $(rmax)"
    ) in submit
    assert "fullsyst_canary_v2/payloads/combine_payload_w1_m2000.tgz" in submit
    assert "fullsyst_canary_v1/payloads" not in submit
    assert "workspace_runtime_overlay_20260811_v1.tgz" in submit
    assert "combine_theory_seed_allfloat_v2.tsv" in submit

    namespace = "fullsyst_canary_v2/diagnostics/theory_seed_allfloat_v2"
    remap_lines = [line for line in submit.splitlines() if line.startswith("transfer_output_remaps")]
    assert remap_lines == [
        'transfer_output_remaps = "theory_seed_allfloat_v2_result.tgz = '
        f'{namespace}/w$(width)_m$(mass).tgz"'
    ]
    log_lines = [
        line for line in submit.splitlines()
        if line.startswith(("output =", "error =", "log ="))
    ]
    assert len(log_lines) == 3
    assert all(f"/{namespace}/logs/" in line for line in log_lines)

    print("COMBINE_THEORY_SEED_ALLFLOAT_V2_CONTRACT_TEST_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
