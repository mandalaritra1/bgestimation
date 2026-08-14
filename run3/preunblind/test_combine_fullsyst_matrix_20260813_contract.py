#!/usr/bin/env python3
"""Static contract test for the full-systematics 12-point limit matrix job.

The matrix job extends the validated theory_seed_allfloat_v4 gate with exactly
three intended deltas: (a) the 12-point width/mass domain with width-dependent
signal naming, (b) a stage-3 blinded AsymptoticLimits from the stage-2 saved
snapshot with the Pass windows unmasked-but-frozen (the v6 production recipe
plus the MaxCalls fix), and (c) the campaign naming/provenance. Stages 1 and 2
must be byte-identical to v4. Blinding: --run blind only, never observed.
"""

from __future__ import annotations

from pathlib import Path
import re


HERE = Path(__file__).resolve().parent
WORKER = HERE / "combine_fullsyst_matrix_20260813_job.sh"
V4_WORKER = HERE / "combine_theory_seed_allfloat_v4_job.sh"
MATRIX = HERE / "combine_fullsyst_matrix_20260813.tsv"
SUBMIT = HERE / "combine_fullsyst_matrix_20260813.sub"
LEDGER = HERE / "rmax_fullsyst_matrix_20260813.tsv"

MAXCALLS = "--X-rtd MINIMIZER_MaxCalls=5000000"


def inclusive_block(script: str, start: str, end: str) -> str:
    block_start = script.index(start)
    block_end = script.index(end, block_start) + len(end)
    return script[block_start:block_end]


def main() -> int:
    worker = WORKER.read_text()
    v4_worker = V4_WORKER.read_text()
    submit = SUBMIT.read_text()
    matrix_rows = MATRIX.read_text().splitlines()
    ledger_rows = LEDGER.read_text().splitlines()

    # The tsv is exactly the rMax ledger with the mode prepended.
    assert len(matrix_rows) == 12
    assert matrix_rows == [
        f"fullsyst_matrix_20260813 {row}" for row in ledger_rows
    ], "matrix tsv deviates from the rMax ledger"
    widths = {row.split()[1] for row in matrix_rows}
    masses = {row.split()[2] for row in matrix_rows}
    assert widths == {"1", "10", "30"} and masses == {"2000", "4000", "6000", "7000"}

    # Stages 1 and 2 are byte-identical to the validated v4 gate.
    stage1_start = "    combine -M MultiDimFit -d workspace.root -m 0 \\\n"
    stage1_end = "        > stage1_bootstrap_validation.log 2>&1"
    assert inclusive_block(worker, stage1_start, stage1_end) == inclusive_block(
        v4_worker, stage1_start, stage1_end
    ), "stage 1 deviates from v4"
    stage2_start = (
        "    combine -M MultiDimFit \\\n"
        "        -d higgsCombine_stage1.MultiDimFit.mH0.root \\\n"
    )
    stage2_end = "        > stage2_allfloat_validation.log 2>&1"
    assert inclusive_block(worker, stage2_start, stage2_end) == inclusive_block(
        v4_worker, stage2_start, stage2_end
    ), "stage 2 deviates from v4"
    ws_check_start = "import math\nimport ROOT"
    ws_check_end = 'positive_par0=4",\n    "status=0",\n)'
    assert inclusive_block(worker, ws_check_start, ws_check_end) == inclusive_block(
        v4_worker, ws_check_start, ws_check_end
    ), "stage-2 workspace validation deviates from v4"

    # Stage 3: blinded expected limit only, from the stage-2 snapshot,
    # masks OFF and frozen, v6 accuracy recipe, MaxCalls present.
    stage3 = inclusive_block(
        worker,
        "    combine -M AsymptoticLimits \\\n",
        "        > stage3_limit_validation.log 2>&1",
    )
    assert "-d higgsCombine_stage2.MultiDimFit.mH0.root" in stage3
    assert "--snapshotName MultiDimFit --run blind --bypassFrequentistFit -m 0" in stage3
    assert '--setParameters "${M_OFF}" --freezeParameters "${M_FRZ}"' in stage3
    assert "--cminDefaultMinimizerStrategy 0" in stage3
    assert "--rRelAcc 0.0005 --rAbsAcc 1e-9" in stage3
    assert MAXCALLS in stage3
    assert 'validate_expected_limit.py' in stage3
    assert '--rmax "${RMAX}"' in stage3

    # Blinding and hygiene (count in code, not the header comment).
    code_lines = "\n".join(
        line for line in worker.splitlines() if not line.lstrip().startswith("#")
    )
    assert code_lines.count("--run blind") == 1
    assert "--run observed" not in worker
    assert "FitDiagnostics" not in worker
    assert worker.count("combine -M MultiDimFit") == 2
    assert worker.count("combine -M AsymptoticLimits") == 1
    assert code_lines.count(MAXCALLS) == 3
    assert worker.count("--setParameterRanges") == 2
    assert "sed " not in worker
    assert "sanitize" not in worker.lower()
    m_off = 'M_OFF="mask_cen_Cen24Pass_Region1=0,mask_cen_Cen25Pass_Region1=0,mask_fwd_Fwd24Pass_Region1=0,mask_fwd_Fwd25Pass_Region1=0"'
    assert m_off in worker
    assert "unexpected_limit_output" in worker
    assert "FULLSYST_MATRIX_20260813_REFUSE_EXISTING" in worker

    # Width-dependent signal naming and the 12-point domain.
    assert 'SIGNAL="signalZPrime${MASS}"' in worker
    assert 'SIGNAL="signalZPrime${MASS}_${WIDTH}"' in worker
    assert "2000|4000|6000|7000" in worker
    assert "1|10|30" in worker
    assert set(re.findall(r'^    ([a-z0-9_]+)\)', worker, flags=re.MULTILINE)) >= {
        "fullsyst_matrix_20260813"
    }

    # Submit description: matrix namespace throughout, no proxy requirement.
    namespace = "fullsyst_matrix_20260813"
    assert f"{namespace}/payloads/combine_payload_w$(width)_m$(mass).tgz" in submit
    assert "workspace_runtime_overlay_20260811_v1.tgz" in submit
    assert f'{namespace}/limits/w$(width)_m$(mass).tgz"' in submit
    assert "use_x509userproxy = false" in submit
    assert "combine_fullsyst_matrix_20260813.tsv" in submit
    log_lines = [
        line for line in submit.splitlines()
        if line.startswith(("output =", "error =", "log ="))
    ]
    assert len(log_lines) == 3
    assert all(f"/{namespace}/logs/" in line for line in log_lines)

    print("COMBINE_FULLSYST_MATRIX_20260813_CONTRACT_TEST_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
