#!/usr/bin/env python3
"""Static contract test for the interior-start staged all-systematic diagnostic.

v3 is byte-identical to v2 except for (a) the version naming, (b) the
stage-2 interior start, which now moves the four boundary-adjacent forward
RPF coefficients (par1=+40, par2=-40) instead of only par2=-45, and (c) the
header comment documenting that change. Everything else -- model, masks,
ranges, solver flags, validation gates -- must match v2 exactly.
"""

from __future__ import annotations

from pathlib import Path
import re


HERE = Path(__file__).resolve().parent
WORKER = HERE / "combine_theory_seed_allfloat_v3_job.sh"
V2_WORKER = HERE / "combine_theory_seed_allfloat_v2_job.sh"
MATRIX = HERE / "combine_theory_seed_allfloat_v3.tsv"
SUBMIT = HERE / "combine_theory_seed_allfloat_v3.sub"
V2_SUBMIT = HERE / "combine_theory_seed_allfloat_v2.sub"

V2_START = "QCD_Fwd24rpf_par2=-45,QCD_Fwd25rpf_par2=-45"
V3_START = (
    "QCD_Fwd24rpf_par1=40,QCD_Fwd25rpf_par1=40,"
    "QCD_Fwd24rpf_par2=-40,QCD_Fwd25rpf_par2=-40"
)
V2_COMMENT = "# nuisances in the standard masked physical-range refit.\n"
V3_COMMENT = (
    "# nuisances in the standard masked physical-range refit.\n"
    "# v3: the four boundary-adjacent forward RPF coefficients start in the\n"
    "# interior (par1=+40, par2=-40); physical ranges are unchanged.\n"
)


def assignment(script: str, name: str) -> str:
    match = re.search(rf'^\s*{name}="([^"]+)"$', script, flags=re.MULTILINE)
    assert match, f"missing {name} assignment"
    return match.group(1)


def main() -> int:
    worker = WORKER.read_text()
    v2_worker = V2_WORKER.read_text()
    submit = SUBMIT.read_text()
    v2_submit = V2_SUBMIT.read_text()
    matrix_bytes = MATRIX.read_bytes()

    assert matrix_bytes == b"theory_seed_allfloat_v3 1 2000 1\n"
    assert matrix_bytes.count(b"\n") == 1

    # The whole worker must be the v2 worker plus exactly the three intended
    # changes: naming, interior start, header comment.
    transformed = (
        v2_worker
        .replace("theory_seed_allfloat_v2", "theory_seed_allfloat_v3")
        .replace("THEORY_SEED_ALLFLOAT_V2", "THEORY_SEED_ALLFLOAT_V3")
        .replace(V2_START, V3_START)
        .replace(V2_COMMENT, V3_COMMENT)
    )
    assert worker == transformed, "v3 worker deviates from v2 beyond the intended changes"

    # Same for the submit description: naming only.
    assert submit == v2_submit.replace(
        "theory_seed_allfloat_v2", "theory_seed_allfloat_v3"
    ), "v3 submit deviates from v2 beyond the version rename"

    # Spot-check the physics-critical facts directly rather than trusting the
    # transform alone.
    assert set(re.findall(r'^    ([a-z0-9_]+)\)', worker, flags=re.MULTILINE)) == {
        "theory_seed_allfloat_v3"
    }
    assert assignment(worker, "INTERIOR_BOUNDARY_START") == V3_START
    assert assignment(worker, "STAGE2_FLOAT_NUISANCES") == "jes,jer,pileup,pdf,q2,ttag_pt1"
    assert '--setParameters "r=0,${M_ON},${INTERIOR_BOUNDARY_START}"' in worker
    assert '--freezeParameters "r,${M_FRZ}"' in worker
    assert "--setParameterRanges 'rgx{.*rpf_par.*}=-50,50'" in worker
    assert "--setParameterRanges 'rgx{.*rpf_par0}=0.001,50'" in worker
    assert worker.count("--setParameterRanges") == 2, "no new range overrides allowed"
    assert "rpf_par1=40" in assignment(worker, "INTERIOR_BOUNDARY_START")
    assert "AsymptoticLimits" not in worker
    assert "--run blind" not in worker
    assert "--run observed" not in worker
    assert "sed " not in worker
    assert worker.count("validate_fit_result.py") == 2
    assert worker.count("--min-cov-qual 3 --max-edm 0.01") == 2

    assert "combine_theory_seed_allfloat_v3.tsv" in submit
    assert "fullsyst_canary_v2/payloads/combine_payload_w1_m2000.tgz" in submit
    assert "workspace_runtime_overlay_20260811_v1.tgz" in submit
    namespace = "fullsyst_canary_v2/diagnostics/theory_seed_allfloat_v3"
    assert f'{namespace}/w$(width)_m$(mass).tgz"' in submit
    log_lines = [
        line for line in submit.splitlines()
        if line.startswith(("output =", "error =", "log ="))
    ]
    assert len(log_lines) == 3
    assert all(f"/{namespace}/logs/" in line for line in log_lines)

    print("COMBINE_THEORY_SEED_ALLFLOAT_V3_CONTRACT_TEST_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
