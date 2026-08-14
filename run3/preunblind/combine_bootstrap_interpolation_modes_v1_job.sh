#!/bin/bash
# Isolated interpolation diagnostics for two prescribed scratch-only card
# modes.  Each job builds the standard combined masked workspace and runs only
# the wide-RPF background bootstrap with every nuisance floating.
set -euo pipefail

if [[ "$#" -ne 4 ]]; then
    echo "usage: $0 <mode> <width> <mass_GeV> <rMax>" >&2
    exit 2
fi

MODE="$1"
WIDTH="$2"
MASS="$3"
RMAX="$4"
if [[ "${WIDTH}" != "1" || "${MASS}" != "2000" || "${RMAX}" != "1" ]]; then
    echo "unsupported diagnostic point: width=${WIDTH} mass=${MASS} rMax=${RMAX}" >&2
    exit 3
fi

NUISANCE_NAMES="jes,jer,pileup,pdf,q2,ttag_pt1"
case "${MODE}" in
    official_shape_sigma1)
        NUISANCE_TOKEN_AFTER="shape"
        ;;
    legacy_shapes_sigma1)
        NUISANCE_TOKEN_AFTER="shapes"
        ;;
    *)
        echo "unsupported diagnostic mode: ${MODE}" >&2
        exit 4
        ;;
esac

SCRATCH="${_CONDOR_SCRATCH_DIR:?missing _CONDOR_SCRATCH_DIR}"
PAYLOAD="${SCRATCH}/combine_payload_w${WIDTH}_m${MASS}.tgz"
RUNTIME="${SCRATCH}/workspace_runtime_overlay_20260811_v1.tgz"
PAYLOAD_WORK="${SCRATCH}/combine_payload"
RUNTIME_WORK="${SCRATCH}/combine_runtime"
CAMPAIGN="${SCRATCH}/interpolation_modes_v1_${MODE}_campaign"
RESULT="${SCRATCH}/interpolation_modes_v1_result"
RESULT_ARCHIVE="${SCRATCH}/interpolation_modes_v1_result.tgz"
CMSSW_VERSION="${CMSSW_VERSION:-CMSSW_14_1_0_pre4}"
SCRAM_ARCH="${SCRAM_ARCH:-el9_amd64_gcc12}"
SIGNAL="signalZPrime${MASS}"
AREA=""

finalize_result() {
    local wrapper_rc="$?"
    local source_path artifact_name
    trap - EXIT
    set +e

    mkdir -p "${RESULT}/artifacts"
    if [[ -n "${AREA}" && -d "${AREA}" ]]; then
        for source_path in \
            "${AREA}/bootstrap_bonly.log" \
            "${AREA}/bootstrap_bonly_validation.log" \
            "${AREA}/card_change_audit.json" \
            "${AREA}/card_audit"/*.txt \
            "${AREA}"/*bootstrap*.root; do
            if [[ -f "${source_path}" ]]; then
                artifact_name="$(basename "${source_path}")"
                cp -a "${source_path}" "${RESULT}/artifacts/${artifact_name}"
            fi
        done
    fi
    if [[ -s "${SCRATCH}/cmssw_project.log" ]]; then
        cp -a "${SCRATCH}/cmssw_project.log" "${RESULT}/artifacts/"
    fi

    {
        echo "diagnostic=interpolation_modes_v1"
        echo "mode=${MODE}"
        echo "wrapper_exit_code=${wrapper_rc}"
        if [[ "${wrapper_rc}" -eq 0 ]]; then
            echo "status=success"
        else
            echo "status=failure"
        fi
        echo "width=${WIDTH}"
        echo "mass_GeV=${MASS}"
        echo "rMax=${RMAX}"
        echo "signal=${SIGNAL}"
        echo "nuisance_names=${NUISANCE_NAMES}"
        echo "nuisance_pdf_token_before=shapes"
        echo "nuisance_pdf_token_after=${NUISANCE_TOKEN_AFTER}"
        echo "ttag_pt1_sigma_expected=1.0"
        echo "ttag_pt1_rewritten=no"
        echo "shape_nuisances_frozen=none"
        echo "poi_fixed=r=0"
        echo "pass_region1_masks=on_and_frozen"
        echo "rpf_bootstrap_range=-50,50"
        if [[ -s "${PAYLOAD}" ]]; then
            echo "payload_sha256=$(sha256sum "${PAYLOAD}" | awk '{print $1}')"
        fi
        if [[ -s "${RUNTIME}" ]]; then
            echo "runtime_sha256=$(sha256sum "${RUNTIME}" | awk '{print $1}')"
        fi
        while IFS= read -r source_path; do
            artifact_name="${source_path#${RESULT}/}"
            echo "artifact_sha256[${artifact_name}]=$(sha256sum "${source_path}" | awk '{print $1}')"
        done < <(find "${RESULT}/artifacts" -maxdepth 1 -type f | sort)
    } > "${RESULT}/diagnostic.status"

    rm -f "${RESULT_ARCHIVE}"
    (
        cd "${SCRATCH}"
        tar -czf "${RESULT_ARCHIVE}" "$(basename "${RESULT}")"
    )
    echo "INTERPOLATION_MODES_V1_DONE mode=${MODE} rc=${wrapper_rc} result=$(basename "${RESULT_ARCHIVE}")"
    exit "${wrapper_rc}"
}
trap finalize_result EXIT

[[ -s "${PAYLOAD}" ]] || { echo "missing point payload: ${PAYLOAD}" >&2; exit 5; }
[[ -s "${RUNTIME}" ]] || { echo "missing runtime overlay: ${RUNTIME}" >&2; exit 6; }
[[ -r /cvmfs/cms.cern.ch/cmsset_default.sh ]] || {
    echo "missing CVMFS CMS setup" >&2
    exit 7
}

mkdir -p "${PAYLOAD_WORK}" "${RUNTIME_WORK}" "${RESULT}"
tar -xzf "${PAYLOAD}" -C "${PAYLOAD_WORK}"
tar -xzf "${RUNTIME}" -C "${RUNTIME_WORK}"
(
    cd "${PAYLOAD_WORK}"
    sha256sum -c payload.sha256
)
for expected in \
    "width=${WIDTH}" \
    "mass_GeV=${MASS}" \
    "signal=${SIGNAL}" \
    "rMax=${RMAX}"; do
    grep -Fxq "${expected}" "${PAYLOAD_WORK}/payload_provenance.txt" || {
        echo "INTERPOLATION_MODES_V1_INVALID payload_provenance=${expected}" >&2
        exit 8
    }
done
(
    cd "${RUNTIME_WORK}"
    sha256sum -c runtime.sha256
)

source /cvmfs/cms.cern.ch/cmsset_default.sh
export SCRAM_ARCH
cd "${SCRATCH}"
scramv1 project CMSSW "${CMSSW_VERSION}" > "${SCRATCH}/cmssw_project.log" 2>&1
CMS_RELEASE="${SCRATCH}/${CMSSW_VERSION}"
cp -a "${RUNTIME_WORK}/." "${CMS_RELEASE}/"
cd "${CMS_RELEASE}"
eval "$(scram runtime -sh)"
python3 - <<'PY'
import ROOT
status = ROOT.gSystem.Load("libHiggsAnalysisCombinedLimit.so")
if status < 0 or not hasattr(ROOT, "RooParametricHist2D"):
    raise RuntimeError("CombinedLimit overlay failed to load RooParametricHist2D")
from HiggsAnalysis.CombinedLimit.PhysicsModel import PhysicsModel
print("INTERPOLATION_MODES_V1_RUNTIME_OK", ROOT.gROOT.GetVersion(), PhysicsModel.__name__)
PY
combine --help >/dev/null
text2workspace.py --help >/dev/null

REPO="${PAYLOAD_WORK}/bgestimation"
PERCAT="${PAYLOAD_WORK}/workspaces/percat"
COMBINED="${CAMPAIGN}/workspaces/combined/w${WIDTH}"
CEN_AREA="${PERCAT}/ttbarfits_cen2425_2x2_${SIGNAL}"
FWD_AREA="${PERCAT}/ttbarfits_fwd2425_2x1_${SIGNAL}"
CEN_CARD_SOURCE="${CEN_AREA}/${SIGNAL}_area/card.txt"
FWD_CARD_SOURCE="${FWD_AREA}/${SIGNAL}_area/card.txt"
AREA="${COMBINED}/${SIGNAL}_area"

for required in \
    "${CEN_AREA}/base.root" "${CEN_CARD_SOURCE}" \
    "${FWD_AREA}/base.root" "${FWD_CARD_SOURCE}"; do
    if [[ ! -s "${required}" ]]; then
        echo "INTERPOLATION_MODES_V1_INVALID missing_or_empty=${required}" >&2
        exit 10
    fi
done
if [[ -e "${AREA}" ]]; then
    echo "INTERPOLATION_MODES_V1_REFUSE_EXISTING area=${AREA}" >&2
    exit 11
fi

mkdir -p "${AREA}/cen/${SIGNAL}_area" "${AREA}/fwd/${SIGNAL}_area"
cp -a "${CEN_AREA}/base.root" "${AREA}/cen/base.root"
cp -a "${FWD_AREA}/base.root" "${AREA}/fwd/base.root"
cp -a "${CEN_CARD_SOURCE}" "${AREA}/cen/${SIGNAL}_area/card.txt"
cp -a "${FWD_CARD_SOURCE}" "${AREA}/fwd/${SIGNAL}_area/card.txt"

mkdir -p "${AREA}/card_audit"
cp -a "${AREA}/cen/${SIGNAL}_area/card.txt" "${AREA}/card_audit/cen_before.txt"
cp -a "${AREA}/fwd/${SIGNAL}_area/card.txt" "${AREA}/card_audit/fwd_before.txt"
python3 - "${MODE}" \
    "${AREA}/cen/${SIGNAL}_area/card.txt" \
    "${AREA}/fwd/${SIGNAL}_area/card.txt" \
    "${AREA}/card_change_audit.json" <<'PY'
import hashlib
import json
from pathlib import Path
import re
import sys


mode = sys.argv[1]
card_specs = (("cen", Path(sys.argv[2])), ("fwd", Path(sys.argv[3])))
audit_path = Path(sys.argv[4])
nuisance_names = ("jes", "jer", "pileup", "pdf", "q2", "ttag_pt1")
target_token = {
    "official_shape_sigma1": "shape",
    "legacy_shapes_sigma1": "shapes",
}.get(mode)
if target_token is None:
    raise RuntimeError(f"unsupported mode: {mode}")


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def rewrite_card(label: str, path: Path) -> dict[str, object]:
    before_bytes = path.read_bytes()
    before_text = before_bytes.decode("utf-8")
    found: dict[str, int] = {}
    changes: list[dict[str, object]] = []
    token_rows_changed = 0
    ttag_rows_validated = 0
    ttag_coefficients_validated = 0
    after_lines: list[str] = []

    for line_number, full_line in enumerate(before_text.splitlines(keepends=True), start=1):
        newline = "\n" if full_line.endswith("\n") else ""
        body = full_line[:-1] if newline else full_line
        tokens = body.split()
        if not tokens or tokens[0] not in nuisance_names:
            after_lines.append(full_line)
            continue

        nuisance = tokens[0]
        if nuisance in found:
            raise RuntimeError(f"{label}: duplicate nuisance row {nuisance}")
        found[nuisance] = line_number
        if len(tokens) < 3 or tokens[1] != "shapes":
            raise RuntimeError(
                f"{label}: nuisance {nuisance} has PDF token "
                f"{tokens[1] if len(tokens) > 1 else '<missing>'}, expected shapes"
            )

        if nuisance == "ttag_pt1":
            unexpected = [value for value in tokens[2:] if value not in {"-", "1.0"}]
            if unexpected:
                raise RuntimeError(
                    f"{label}: ttag_pt1 contains non-sigma1 tokens {unexpected}"
                )
            coefficient_count = sum(value == "1.0" for value in tokens[2:])
            if coefficient_count < 1:
                raise RuntimeError(f"{label}: ttag_pt1 has no 1.0 coefficient")
            ttag_rows_validated += 1
            ttag_coefficients_validated += coefficient_count

        after_body = body
        token_changed = False
        if target_token == "shape":
            pattern = rf"^(\s*{re.escape(nuisance)}\s+)shapes(\s+)"
            after_body, replacements = re.subn(
                pattern,
                rf"\1{target_token}\2",
                after_body,
                count=1,
            )
            if replacements != 1:
                raise RuntimeError(f"{label}: failed to rewrite token for {nuisance}")
            token_changed = True
            token_rows_changed += 1

        after_line = after_body + newline
        if after_line != full_line:
            changes.append(
                {
                    "line_number": line_number,
                    "nuisance": nuisance,
                    "pdf_token_changed": token_changed,
                    "before": body,
                    "after": after_body,
                }
            )
        after_lines.append(after_line)

    if set(found) != set(nuisance_names) or len(found) != 6:
        raise RuntimeError(
            f"{label}: expected exactly six nuisance rows {nuisance_names}, found {found}"
        )
    if ttag_rows_validated != 1:
        raise RuntimeError(
            f"{label}: expected one sigma1 ttag_pt1 row, found {ttag_rows_validated}"
        )
    expected_token_changes = 6 if target_token == "shape" else 0
    if token_rows_changed != expected_token_changes:
        raise RuntimeError(
            f"{label}: changed {token_rows_changed} PDF tokens, "
            f"expected {expected_token_changes}"
        )
    if len(changes) != expected_token_changes:
        raise RuntimeError(
            f"{label}: changed {len(changes)} lines, expected {expected_token_changes}"
        )

    after_text = "".join(after_lines)
    after_bytes = after_text.encode("utf-8")
    if target_token == "shape" and before_bytes == after_bytes:
        raise RuntimeError(f"{label}: official mode produced no card change")
    if target_token == "shapes" and before_bytes != after_bytes:
        raise RuntimeError(f"{label}: legacy mode changed the card")
    if after_bytes != before_bytes:
        path.write_bytes(after_bytes)
    return {
        "label": label,
        "path": str(path),
        "pre_sha256": digest(before_bytes),
        "post_sha256": digest(after_bytes),
        "nuisance_rows_found": len(found),
        "nuisance_row_lines": found,
        "pdf_token_before": "shapes",
        "pdf_token_after": target_token,
        "pdf_token_rows_changed": token_rows_changed,
        "ttag_sigma_expected": "1.0",
        "ttag_rows_validated": ttag_rows_validated,
        "ttag_coefficients_validated": ttag_coefficients_validated,
        "ttag_coefficients_changed": 0,
        "changed_line_count": len(changes),
        "changed_lines": changes,
    }


records = [rewrite_card(label, path) for label, path in card_specs]
audit = {
    "schema_version": 1,
    "mode": mode,
    "nuisance_names": list(nuisance_names),
    "cards": records,
}
audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n")
print(
    "INTERPOLATION_CARD_AUDIT_OK",
    f"mode={mode}",
    *[
        (
            f"{record['label']}:pre={record['pre_sha256']}:"
            f"post={record['post_sha256']}:"
            f"lines={record['changed_line_count']}:"
            f"ttag_sigma1={record['ttag_coefficients_validated']}"
        )
        for record in records
    ],
)
PY
cp -a "${AREA}/cen/${SIGNAL}_area/card.txt" "${AREA}/card_audit/cen_after.txt"
cp -a "${AREA}/fwd/${SIGNAL}_area/card.txt" "${AREA}/card_audit/fwd_after.txt"

(
    cd "${AREA}"
    combineCards.py \
        cen="cen/${SIGNAL}_area/card.txt" \
        fwd="fwd/${SIGNAL}_area/card.txt" \
        > "${SIGNAL}_card_combined.txt"
    text2workspace.py "${SIGNAL}_card_combined.txt" \
        -o workspace.root --channel-masks --X-no-jmax
)

M_ON="mask_cen_Cen24Pass_Region1=1,mask_cen_Cen25Pass_Region1=1,mask_fwd_Fwd24Pass_Region1=1,mask_fwd_Fwd25Pass_Region1=1"
M_FRZ="mask_cen_Cen24Pass_Region1,mask_cen_Cen25Pass_Region1,mask_fwd_Fwd24Pass_Region1,mask_fwd_Fwd25Pass_Region1"

(
    cd "${AREA}"
    combine -M MultiDimFit -d workspace.root -m 0 \
        --rMin 0 --rMax "${RMAX}" \
        --setParameters "r=0,${M_ON}" \
        --freezeParameters "r,${M_FRZ}" \
        --cminDefaultMinimizerStrategy 1 --cminPreScan --cminPreFit 1 \
        --setParameterRanges 'rgx{.*rpf_par.*}=-50,50' \
        --saveWorkspace --saveFitResult -n _bootstrap \
        > bootstrap_bonly.log 2>&1
    python3 "${REPO}/run3/validate_fit_result.py" \
        multidimfit_bootstrap.root --key fit_mdf --min-cov-qual 3 \
        > bootstrap_bonly_validation.log 2>&1
)

for required in \
    "${AREA}/higgsCombine_bootstrap.MultiDimFit.mH0.root" \
    "${AREA}/multidimfit_bootstrap.root" \
    "${AREA}/bootstrap_bonly.log" \
    "${AREA}/bootstrap_bonly_validation.log"; do
    if [[ ! -s "${required}" ]]; then
        echo "INTERPOLATION_MODES_V1_INVALID missing_or_empty=${required}" >&2
        exit 12
    fi
done

echo "INTERPOLATION_MODES_V1_BOOTSTRAP_OK mode=${MODE} width=${WIDTH} mass=${MASS}"
