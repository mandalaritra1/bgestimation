#!/usr/bin/env python3
"""Static contract test for the sigma1 interpolation-token diagnostics."""

from __future__ import annotations

from pathlib import Path
import re


HERE = Path(__file__).resolve().parent
WORKER = HERE / "combine_bootstrap_interpolation_modes_v1_job.sh"
MATRIX = HERE / "combine_bootstrap_interpolation_modes_v1.tsv"
SUBMIT = HERE / "combine_bootstrap_interpolation_modes_v1.sub"


def assignment(script: str, name: str) -> str:
    match = re.search(rf'^\s*{name}="([^"]+)"$', script, flags=re.MULTILINE)
    assert match, f"missing {name} assignment"
    return match.group(1)


def main() -> int:
    worker = WORKER.read_text()
    submit = SUBMIT.read_text()
    matrix_text = MATRIX.read_text()
    assert matrix_text == (
        "official_shape_sigma1 1 2000 1\n"
        "legacy_shapes_sigma1 1 2000 1\n"
    )
    points = [tuple(line.split()) for line in matrix_text.splitlines()]

    assert points == [
        ("official_shape_sigma1", "1", "2000", "1"),
        ("legacy_shapes_sigma1", "1", "2000", "1"),
    ]
    assert len(points) == len(set(points)) == 2
    assert assignment(worker, "NUISANCE_NAMES") == "jes,jer,pileup,pdf,q2,ttag_pt1"
    case_modes = set(re.findall(r'^    ([a-z0-9_]+)\)$', worker, flags=re.MULTILINE))
    assert case_modes == {"official_shape_sigma1", "legacy_shapes_sigma1"}
    assert re.search(
        r'^    official_shape_sigma1\).*?NUISANCE_TOKEN_AFTER="shape".*?^        ;;$',
        worker,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert re.search(
        r'^    legacy_shapes_sigma1\).*?NUISANCE_TOKEN_AFTER="shapes".*?^        ;;$',
        worker,
        flags=re.MULTILINE | re.DOTALL,
    )

    assert 'nuisance_names = ("jes", "jer", "pileup", "pdf", "q2", "ttag_pt1")' in worker
    assert 'tokens[1] != "shapes"' in worker
    assert 'value not in {"-", "1.0"}' in worker
    assert 'ttag_coefficients_changed": 0' in worker
    assert 'expected_token_changes = 6 if target_token == "shape" else 0' in worker
    assert r'pattern = rf"^(\s*{re.escape(nuisance)}\s+)shapes(\s+)"' in worker
    assert r'rf"\1{target_token}\2"' in worker
    assert '"pre_sha256": digest(before_bytes)' in worker
    assert '"post_sha256": digest(after_bytes)' in worker
    assert '"changed_lines": changes' in worker
    assert 'if after_bytes != before_bytes:' in worker
    assert "ttag_pt1_rewritten=no" in worker
    assert "5.0" not in worker

    mask_names = assignment(worker, "M_FRZ").split(",")
    assert mask_names == [
        "mask_cen_Cen24Pass_Region1",
        "mask_cen_Cen25Pass_Region1",
        "mask_fwd_Fwd24Pass_Region1",
        "mask_fwd_Fwd25Pass_Region1",
    ]
    assert assignment(worker, "M_ON").split(",") == [f"{name}=1" for name in mask_names]
    assert worker.count("combine -M MultiDimFit") == 1
    assert worker.count("--freezeParameters") == 1
    assert '--freezeParameters "r,${M_FRZ}"' in worker
    assert '--setParameters "r=0,${M_ON}"' in worker
    assert "--setParameterRanges 'rgx{.*rpf_par.*}=-50,50'" in worker
    assert "AsymptoticLimits" not in worker
    assert "--run observed" not in worker
    assert "--run blind" not in worker
    assert "--snapshotName" not in worker
    assert "trap finalize_result EXIT" in worker
    assert '"${AREA}/card_change_audit.json"' in worker
    assert '"${AREA}/card_audit"/*.txt' in worker
    assert '"${AREA}"/*bootstrap*.root' in worker

    assert (
        "arguments = combine_bootstrap_interpolation_modes_v1_job.sh "
        "$(mode) $(width) $(mass) $(rmax)"
    ) in submit
    assert "fullsyst_canary_v2/payloads/combine_payload_w1_m2000.tgz" in submit
    assert "fullsyst_canary_v1/payloads" not in submit
    assert "workspace_runtime_overlay_20260811_v1.tgz" in submit
    assert "combine_bootstrap_interpolation_modes_v1.tsv" in submit

    namespace = "fullsyst_canary_v2/diagnostics/interpolation_modes_v1"
    remap_template = f"{namespace}/$(mode)/w$(width)_m$(mass).tgz"
    remap_lines = [line for line in submit.splitlines() if line.startswith("transfer_output_remaps")]
    assert remap_lines == [
        'transfer_output_remaps = "interpolation_modes_v1_result.tgz = '
        f'{remap_template}"'
    ]
    remaps = {
        remap_template.replace("$(mode)", mode)
        .replace("$(width)", width)
        .replace("$(mass)", mass)
        for mode, width, mass, _rmax in points
    }
    assert remaps == {
        f"{namespace}/official_shape_sigma1/w1_m2000.tgz",
        f"{namespace}/legacy_shapes_sigma1/w1_m2000.tgz",
    }
    assert len(remaps) == 2
    log_lines = [
        line for line in submit.splitlines()
        if line.startswith(("output =", "error ="))
    ]
    assert len(log_lines) == 2
    assert all(f"/{namespace}/$(mode)/logs/" in line for line in log_lines)

    print("COMBINE_BOOTSTRAP_INTERPOLATION_MODES_V1_CONTRACT_TEST_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
