#!/bin/bash
# Portable worker wrapper.  The Combine physics options below match
# combine_job.sh; only paths and output transport are made scratch-local.
set -euo pipefail

if [[ "$#" -ne 3 ]]; then
    echo "usage: $0 <1|10|30> <mass_GeV> <rMax>" >&2
    exit 2
fi
WIDTH="$1"
MASS="$2"
RMAX="$3"
SCRATCH="${_CONDOR_SCRATCH_DIR:?missing _CONDOR_SCRATCH_DIR}"
PAYLOAD="${SCRATCH}/combine_payload_w${WIDTH}_m${MASS}.tgz"
RUNTIME="${SCRATCH}/workspace_runtime_overlay_20260811_v1.tgz"
PAYLOAD_WORK="${SCRATCH}/combine_payload"
RUNTIME_WORK="${SCRATCH}/combine_runtime"
CMSSW_VERSION="${CMSSW_VERSION:-CMSSW_14_1_0_pre4}"
SCRAM_ARCH="${SCRAM_ARCH:-el9_amd64_gcc12}"

finalize_result() {
    local wrapper_rc="$?"
    trap - EXIT
    set +e
    rm -f "${SCRATCH}/combine_result.tgz"
    mkdir -p "${SCRATCH}/combine_result"
    if [[ -d "${AREA:-}" ]]; then
        mkdir -p "${SCRATCH}/combine_result/area"
        cp -a "${AREA}/." "${SCRATCH}/combine_result/area/"
    fi
    if [[ -s "${MARKER:-}" ]]; then
        cp -a "${MARKER}" "${SCRATCH}/combine_result/combined.ok"
    else
        {
            echo "wrapper_exit_code=${wrapper_rc}"
            echo "width=${WIDTH}"
            echo "mass_GeV=${MASS}"
            echo "rMax=${RMAX}"
        } > "${SCRATCH}/combine_result/wrapper_failure.txt"
    fi
    if [[ -s "${SCRATCH}/cmssw_project.log" ]]; then
        cp -a "${SCRATCH}/cmssw_project.log" "${SCRATCH}/combine_result/"
    fi
    (
        cd "${SCRATCH}"
        tar -czf combine_result.tgz combine_result
    )
    if [[ "${wrapper_rc}" -eq 0 ]]; then
        echo "COMBINE_PORTABLE_JOB_OK result=combine_result.tgz"
    else
        echo "COMBINE_PORTABLE_JOB_FAILED rc=${wrapper_rc} diagnostics=combine_result.tgz" >&2
    fi
    exit "${wrapper_rc}"
}
trap finalize_result EXIT

case "${WIDTH}" in
    1) SIGNAL="signalZPrime${MASS}" ;;
    10) SIGNAL="signalZPrime${MASS}_10" ;;
    30) SIGNAL="signalZPrime${MASS}_30" ;;
    *) echo "unsupported width: ${WIDTH}" >&2; exit 3 ;;
esac
[[ -s "${PAYLOAD}" ]] || { echo "missing point payload: ${PAYLOAD}" >&2; exit 4; }
[[ -s "${RUNTIME}" ]] || { echo "missing runtime overlay: ${RUNTIME}" >&2; exit 5; }
[[ -r /cvmfs/cms.cern.ch/cmsset_default.sh ]] || { echo "missing CVMFS CMS setup" >&2; exit 6; }

mkdir -p "${PAYLOAD_WORK}" "${RUNTIME_WORK}"
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
        echo "COMBINE_JOB_INVALID payload_provenance=${expected}" >&2
        exit 7
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
print("COMBINE_RUNTIME_PREFLIGHT_OK", ROOT.gROOT.GetVersion(), PhysicsModel.__name__)
PY
combine --help >/dev/null
text2workspace.py --help >/dev/null

REPO="${PAYLOAD_WORK}/bgestimation"
CAMPAIGN="${SCRATCH}/combine_campaign"
PERCAT="${PAYLOAD_WORK}/workspaces/percat"
COMBINED="${CAMPAIGN}/workspaces/combined/w${WIDTH}"
STATE_DIR="${CAMPAIGN}/state/combined"
CEN_AREA="${PERCAT}/ttbarfits_cen2425_2x2_${SIGNAL}"
FWD_AREA="${PERCAT}/ttbarfits_fwd2425_2x1_${SIGNAL}"
CEN_CARD_SOURCE="${CEN_AREA}/${SIGNAL}_area/card.txt"
FWD_CARD_SOURCE="${FWD_AREA}/${SIGNAL}_area/card.txt"
AREA="${COMBINED}/${SIGNAL}_area"
MARKER="${STATE_DIR}/w${WIDTH}_m${MASS}.ok"

for required in \
    "${CEN_AREA}/base.root" "${CEN_CARD_SOURCE}" \
    "${FWD_AREA}/base.root" "${FWD_CARD_SOURCE}"; do
    if [[ ! -s "${required}" ]]; then
        echo "COMBINE_JOB_INVALID missing_or_empty=${required}" >&2
        exit 10
    fi
done
if [[ -e "${AREA}" ]]; then
    echo "COMBINE_JOB_REFUSE_EXISTING area=${AREA}" >&2
    exit 11
fi
mkdir -p "${AREA}" "${STATE_DIR}"
rm -f "${MARKER}"

# Keep the returned combined card self-contained.  combineCards.py prefixes
# relative shape paths with the input card directory; staging the two cards and
# base workspaces below AREA therefore avoids embedding worker-scratch paths.
mkdir -p "${AREA}/cen/${SIGNAL}_area" "${AREA}/fwd/${SIGNAL}_area"
cp -a "${CEN_AREA}/base.root" "${AREA}/cen/base.root"
cp -a "${FWD_AREA}/base.root" "${AREA}/fwd/base.root"
cp -a "${CEN_CARD_SOURCE}" "${AREA}/cen/${SIGNAL}_area/card.txt"
cp -a "${FWD_CARD_SOURCE}" "${AREA}/fwd/${SIGNAL}_area/card.txt"
CEN_CARD="cen/${SIGNAL}_area/card.txt"
FWD_CARD="fwd/${SIGNAL}_area/card.txt"
CARD_NAME="${SIGNAL}_card_combined.txt"

cd "${REPO}"
echo "COMBINE_JOB_START width=${WIDTH} mass=${MASS} rMax=${RMAX}"
echo "payload_sha256=$(sha256sum "${PAYLOAD}" | awk '{print $1}')"

# The card paths are scratch-local and self-contained; the Combine options,
# masking, parameter ranges, and validation settings match combine_job.sh.
(
    cd "${AREA}"
    combineCards.py cen="${CEN_CARD}" fwd="${FWD_CARD}" > "${CARD_NAME}"
    text2workspace.py "${CARD_NAME}" -o workspace.root --channel-masks --X-no-jmax
)

M_ON="mask_cen_Cen24Pass_Region1=1,mask_cen_Cen25Pass_Region1=1,mask_fwd_Fwd24Pass_Region1=1,mask_fwd_Fwd25Pass_Region1=1"
M_OFF="mask_cen_Cen24Pass_Region1=0,mask_cen_Cen25Pass_Region1=0,mask_fwd_Fwd24Pass_Region1=0,mask_fwd_Fwd25Pass_Region1=0"
M_FRZ="mask_cen_Cen24Pass_Region1,mask_cen_Cen25Pass_Region1,mask_fwd_Fwd24Pass_Region1,mask_fwd_Fwd25Pass_Region1"
# The historical wide-range fit is used only as a numerical bootstrap.  The
# accepted fit below reloads that snapshot, restores every constant RPF term to
# its physical positive range, and is independently validated before limits.
BKG_SEED_SOURCE="wide_rpf_bootstrap_snapshot"
BKG_FIT_START_MODE="wide_bootstrap_then_physical_refit"
INTERIOR_BOUNDARY_START="QCD_Fwd24rpf_par2=-45,QCD_Fwd25rpf_par2=-45"

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

    combine -M MultiDimFit \
        -d higgsCombine_bootstrap.MultiDimFit.mH0.root \
        --snapshotName MultiDimFit -m 0 \
        --rMin 0 --rMax "${RMAX}" \
        --setParameters "r=0,${M_ON},${INTERIOR_BOUNDARY_START}" \
        --freezeParameters "r,${M_FRZ}" \
        --setParameterRanges 'rgx{.*rpf_par0}=0.001,50' \
        --cminDefaultMinimizerStrategy 1 \
        --saveWorkspace --saveFitResult -n _maskedBonly \
        > masked_bonly.log 2>&1
    python3 "${REPO}/run3/validate_fit_result.py" \
        multidimfit_maskedBonly.root --key fit_mdf --min-cov-qual 3 \
        > masked_bonly_validation.log 2>&1
    python3 - <<'PY' > final_range_validation.log 2>&1
import math
import ROOT

root_file = ROOT.TFile.Open("higgsCombine_maskedBonly.MultiDimFit.mH0.root")
if not root_file or root_file.IsZombie():
    raise RuntimeError("cannot open final masked snapshot")
workspace = root_file.Get("w")
if not workspace:
    raise RuntimeError("final masked snapshot has no workspace w")
variables = workspace.allVars()
iterator = variables.createIterator()
rpf_variables = []
while True:
    variable = iterator.Next()
    if not variable:
        break
    if "rpf_par" in variable.GetName():
        rpf_variables.append(variable)
if len(rpf_variables) != 18:
    raise RuntimeError(f"expected 18 RPF variables, found {len(rpf_variables)}")
positive_constants = 0
for variable in rpf_variables:
    name = variable.GetName()
    expected_min = 0.001 if name.endswith("rpf_par0") else -50.0
    expected_max = 50.0
    if name.endswith("rpf_par0"):
        positive_constants += 1
    if not math.isclose(variable.getMin(), expected_min, rel_tol=0.0, abs_tol=1e-9):
        raise RuntimeError(f"{name} min={variable.getMin()} expected={expected_min}")
    if not math.isclose(variable.getMax(), expected_max, rel_tol=0.0, abs_tol=1e-9):
        raise RuntimeError(f"{name} max={variable.getMax()} expected={expected_max}")
if positive_constants != 4:
    raise RuntimeError(f"expected four positive par0 variables, found {positive_constants}")
print("RPF RANGE CHECK: count=18 positive_par0=4 status=0")
PY

    combine -M AsymptoticLimits \
        -d higgsCombine_maskedBonly.MultiDimFit.mH0.root \
        --snapshotName MultiDimFit --run blind --bypassFrequentistFit -m 0 \
        --setParameters "${M_OFF}" --freezeParameters "${M_FRZ}" \
        --rMin 0 --rMax "${RMAX}" \
        --cminDefaultMinimizerStrategy 0 \
        --rRelAcc 0.0005 --rAbsAcc 1e-9 -v 0 -n _expected \
        > expected_limit.log 2>&1
    python3 "${REPO}/run3/validate_expected_limit.py" \
        higgsCombine_expected.AsymptoticLimits.mH0.root --rmax "${RMAX}" \
        > expected_limit_validation.log 2>&1
)

for required in \
    "${AREA}/workspace.root" \
    "${AREA}/higgsCombine_bootstrap.MultiDimFit.mH0.root" \
    "${AREA}/multidimfit_bootstrap.root" \
    "${AREA}/higgsCombine_maskedBonly.MultiDimFit.mH0.root" \
    "${AREA}/multidimfit_maskedBonly.root" \
    "${AREA}/higgsCombine_expected.AsymptoticLimits.mH0.root"; do
    if [[ ! -s "${required}" ]]; then
        echo "COMBINE_JOB_INVALID missing_or_empty=${required}" >&2
        exit 12
    fi
done
if find "${AREA}" -type f -name 'higgsCombine*.AsymptoticLimits*.root' ! -name 'higgsCombine_expected.AsymptoticLimits.mH0.root' | grep -q .; then
    echo "COMBINE_JOB_INVALID unexpected_limit_output=${AREA}" >&2
    exit 13
fi

{
    echo "width=${WIDTH}"
    echo "mass_GeV=${MASS}"
    echo "signal=${SIGNAL}"
    echo "rMax=${RMAX}"
    echo "background_seed_source=${BKG_SEED_SOURCE}"
    echo "background_fit_start_mode=${BKG_FIT_START_MODE}"
    echo "area=area"
    echo "workspace_sha256=$(sha256sum "${AREA}/workspace.root" | awk '{print $1}')"
    echo "bootstrap_snapshot_sha256=$(sha256sum "${AREA}/higgsCombine_bootstrap.MultiDimFit.mH0.root" | awk '{print $1}')"
    echo "bootstrap_fit_sha256=$(sha256sum "${AREA}/multidimfit_bootstrap.root" | awk '{print $1}')"
    echo "snapshot_sha256=$(sha256sum "${AREA}/higgsCombine_maskedBonly.MultiDimFit.mH0.root" | awk '{print $1}')"
    echo "fit_sha256=$(sha256sum "${AREA}/multidimfit_maskedBonly.root" | awk '{print $1}')"
    echo "limit_sha256=$(sha256sum "${AREA}/higgsCombine_expected.AsymptoticLimits.mH0.root" | awk '{print $1}')"
    echo "payload_sha256=$(sha256sum "${PAYLOAD}" | awk '{print $1}')"
    echo "runtime_sha256=$(sha256sum "${RUNTIME}" | awk '{print $1}')"
    sed 's/^FIT CHECK:/BOOTSTRAP FIT CHECK:/' "${AREA}/bootstrap_bonly_validation.log"
    cat "${AREA}/masked_bonly_validation.log"
    cat "${AREA}/final_range_validation.log"
    cat "${AREA}/expected_limit_validation.log"
} > "${MARKER}"
