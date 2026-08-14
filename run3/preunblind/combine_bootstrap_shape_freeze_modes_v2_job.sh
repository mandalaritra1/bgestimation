#!/bin/bash
# Isolated numerical diagnostics for two prescribed shape-nuisance freeze
# modes.  Each job builds the standard combined masked workspace and runs only
# the wide-RPF background bootstrap.
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

ALL_SHAPE_NUISANCES="jes,jer,pileup,pdf,q2,ttag_pt1"
case "${MODE}" in
    theory_plus_jesjer)
        FROZEN_SHAPES="pileup,ttag_pt1"
        FROZEN_SHAPE_VALUES="pileup=0,ttag_pt1=0"
        FLOATING_SHAPES="pdf,q2,jes,jer"
        ;;
    theory_plus_pileup_ttag)
        FROZEN_SHAPES="jes,jer"
        FROZEN_SHAPE_VALUES="jes=0,jer=0"
        FLOATING_SHAPES="pdf,q2,pileup,ttag_pt1"
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
CAMPAIGN="${SCRATCH}/shape_freeze_modes_v2_${MODE}_campaign"
RESULT="${SCRATCH}/shape_freeze_modes_v2_result"
RESULT_ARCHIVE="${SCRATCH}/shape_freeze_modes_v2_result.tgz"
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
        echo "diagnostic=shape_freeze_modes_v2"
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
        echo "all_shape_nuisances=${ALL_SHAPE_NUISANCES}"
        echo "frozen_shape_nuisances=${FROZEN_SHAPES}"
        echo "frozen_shape_values=${FROZEN_SHAPE_VALUES}"
        echo "floating_shape_nuisances=${FLOATING_SHAPES}"
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
    echo "SHAPE_FREEZE_MODES_V2_DONE mode=${MODE} rc=${wrapper_rc} result=$(basename "${RESULT_ARCHIVE}")"
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
        echo "SHAPE_FREEZE_MODES_V2_INVALID payload_provenance=${expected}" >&2
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
print("SHAPE_FREEZE_MODES_V2_RUNTIME_OK", ROOT.gROOT.GetVersion(), PhysicsModel.__name__)
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
        echo "SHAPE_FREEZE_MODES_V2_INVALID missing_or_empty=${required}" >&2
        exit 10
    fi
done
if [[ -e "${AREA}" ]]; then
    echo "SHAPE_FREEZE_MODES_V2_REFUSE_EXISTING area=${AREA}" >&2
    exit 11
fi

mkdir -p "${AREA}/cen/${SIGNAL}_area" "${AREA}/fwd/${SIGNAL}_area"
cp -a "${CEN_AREA}/base.root" "${AREA}/cen/base.root"
cp -a "${FWD_AREA}/base.root" "${AREA}/fwd/base.root"
cp -a "${CEN_CARD_SOURCE}" "${AREA}/cen/${SIGNAL}_area/card.txt"
cp -a "${FWD_CARD_SOURCE}" "${AREA}/fwd/${SIGNAL}_area/card.txt"

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
        --setParameters "r=0,${M_ON},${FROZEN_SHAPE_VALUES}" \
        --freezeParameters "r,${M_FRZ},${FROZEN_SHAPES}" \
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
        echo "SHAPE_FREEZE_MODES_V2_INVALID missing_or_empty=${required}" >&2
        exit 12
    fi
done

echo "SHAPE_FREEZE_MODES_V2_BOOTSTRAP_OK mode=${MODE} width=${WIDTH} mass=${MASS}"

