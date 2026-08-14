#!/usr/bin/env python3
"""Static contract test for the raised-call-budget staged all-systematic diagnostic.

v4 is the v3 worker with exactly four intended changes: (a) version naming,
(b) the interior start is removed (v3 proved the minimum is start-independent),
so stage 2 sets only r and the masks, (c) both combine calls raise the Minuit2
call budget with --X-rtd MINIMIZER_MaxCalls=5000000 (the default 500*npar=290k
budget was the sole cause of the v1/v2/v3 stage-2 status-4 failures), and
(d) the header comment documents this. Model, masks, ranges, solver strategy,
and validation gates are unchanged.
"""

from __future__ import annotations

from pathlib import Path
import re


HERE = Path(__file__).resolve().parent
WORKER = HERE / "combine_theory_seed_allfloat_v4_job.sh"
V3_WORKER = HERE / "combine_theory_seed_allfloat_v3_job.sh"
MATRIX = HERE / "combine_theory_seed_allfloat_v4.tsv"
SUBMIT = HERE / "combine_theory_seed_allfloat_v4.sub"
V3_SUBMIT = HERE / "combine_theory_seed_allfloat_v3.sub"

V3_START_LINE = (
    'INTERIOR_BOUNDARY_START="QCD_Fwd24rpf_par1=40,QCD_Fwd25rpf_par1=40,'
    'QCD_Fwd24rpf_par2=-40,QCD_Fwd25rpf_par2=-40"\n'
)
V3_COMMENT = (
    "# v3: the four boundary-adjacent forward RPF coefficients start in the\n"
    "# interior (par1=+40, par2=-40); physical ranges are unchanged.\n"
)
V4_COMMENT = (
    "# v4: the snapshot start is restored (v3 proved start-independence) and the\n"
    "# Minuit2 call budget is raised: the default 500*npar=290k calls is exceeded\n"
    "# by this 580-parameter fit (~360k calls incl. one Hesse update), which was\n"
    '# the sole cause of the v1/v2/v3 stage-2 "failures" (status 4 = call limit).\n'
)
MAXCALLS = "--X-rtd MINIMIZER_MaxCalls=5000000"


def main() -> int:
    worker = WORKER.read_text()
    v3_worker = V3_WORKER.read_text()
    submit = SUBMIT.read_text()
    v3_submit = V3_SUBMIT.read_text()
    matrix_bytes = MATRIX.read_bytes()

    assert matrix_bytes == b"theory_seed_allfloat_v4 1 2000 1\n"
    assert matrix_bytes.count(b"\n") == 1

    transformed = (
        v3_worker
        .replace("theory_seed_allfloat_v3", "theory_seed_allfloat_v4")
        .replace("THEORY_SEED_ALLFLOAT_V3", "THEORY_SEED_ALLFLOAT_V4")
        .replace(V3_COMMENT, V4_COMMENT)
        .replace(V3_START_LINE, "")
        .replace(
            '--setParameters "r=0,${M_ON},${INTERIOR_BOUNDARY_START}"',
            '--setParameters "r=0,${M_ON}"',
        )
        .replace(
            "--cminDefaultMinimizerStrategy 1 --cminPreScan --cminPreFit 1 \\",
            f"--cminDefaultMinimizerStrategy 1 --cminPreScan --cminPreFit 1 {MAXCALLS} \\",
        )
        .replace(
            "--cminPreScan --cminPreFit 1 --cminDefaultMinimizerStrategy 2 \\",
            f"--cminPreScan --cminPreFit 1 --cminDefaultMinimizerStrategy 2 {MAXCALLS} \\",
        )
    )
    assert worker == transformed, "v4 worker deviates from v3 beyond the intended changes"

    assert submit == v3_submit.replace(
        "theory_seed_allfloat_v3", "theory_seed_allfloat_v4"
    ), "v4 submit deviates from v3 beyond the version rename"

    # Direct spot-checks of the physics-critical facts.
    assert "INTERIOR_BOUNDARY_START" not in worker
    assert "rpf_par1=" not in worker and "rpf_par2=" not in worker
    assert worker.count(MAXCALLS) == 2
    assert '--setParameters "r=0,${M_ON}"' in worker
    assert '--freezeParameters "r,${M_FRZ}"' in worker
    assert '--floatParameters "jes,jer,pileup,pdf,q2,ttag_pt1"' in worker
    assert "--setParameterRanges 'rgx{.*rpf_par.*}=-50,50'" in worker
    assert "--setParameterRanges 'rgx{.*rpf_par0}=0.001,50'" in worker
    assert worker.count("--setParameterRanges") == 2
    assert "AsymptoticLimits" not in worker
    assert "--run blind" not in worker
    assert "--run observed" not in worker
    assert "sed " not in worker
    assert worker.count("validate_fit_result.py") == 2
    assert worker.count("--min-cov-qual 3 --max-edm 0.01") == 2
    assert set(re.findall(r'^    ([a-z0-9_]+)\)', worker, flags=re.MULTILINE)) == {
        "theory_seed_allfloat_v4"
    }

    assert "combine_theory_seed_allfloat_v4.tsv" in submit
    namespace = "fullsyst_canary_v2/diagnostics/theory_seed_allfloat_v4"
    assert f'{namespace}/w$(width)_m$(mass).tgz"' in submit
    log_lines = [
        line for line in submit.splitlines()
        if line.startswith(("output =", "error =", "log ="))
    ]
    assert len(log_lines) == 3
    assert all(f"/{namespace}/logs/" in line for line in log_lines)

    print("COMBINE_THEORY_SEED_ALLFLOAT_V4_CONTRACT_TEST_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
