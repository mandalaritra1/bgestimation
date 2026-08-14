#!/bin/bash
# Isolated two-stage numerical diagnostic.  Stage 1 seeds with experimental
# shapes fixed and theory shapes floating; stage 2 restores all six shape
# nuisances in the standard masked physical-range refit.
# v3: the four boundary-adjacent forward RPF coefficients start in the
# interior (par1=+40, par2=-40); physical ranges are unchanged.
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

STAGE1_FIXED_NUISANCES="jes,jer,pileup,ttag_pt1"
STAGE1_FLOAT_NUISANCES="pdf,q2"
STAGE2_FLOAT_NUISANCES="jes,jer,pileup,pdf,q2,ttag_pt1"
case "${MODE}" in
    theory_seed_allfloat_v3) ;;
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
CAMPAIGN="${SCRATCH}/theory_seed_allfloat_v3_${MODE}_campaign"
RESULT="${SCRATCH}/theory_seed_allfloat_v3_result"
RESULT_ARCHIVE="${SCRATCH}/theory_seed_allfloat_v3_result.tgz"
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
            "${AREA}/stage1_bootstrap.log" \
            "${AREA}/stage1_bootstrap_validation.log" \
            "${AREA}/stage2_allfloat.log" \
            "${AREA}/stage2_allfloat_validation.log" \
            "${AREA}/stage2_workspace_validation.log" \
            "${AREA}"/*stage1*.root \
            "${AREA}"/*stage2*.root; do
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
        echo "diagnostic=theory_seed_allfloat_v3"
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
        echo "stage1_fixed_nuisances=${STAGE1_FIXED_NUISANCES}"
        echo "stage1_floating_nuisances=${STAGE1_FLOAT_NUISANCES}"
        echo "stage2_fixed_nuisances=none"
        echo "stage2_floating_nuisances=${STAGE2_FLOAT_NUISANCES}"
        echo "stage1_rpf_range=-50,50"
        echo "stage2_rpf_par0_range=0.001,50"
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
    echo "THEORY_SEED_ALLFLOAT_V3_DONE mode=${MODE} rc=${wrapper_rc} result=$(basename "${RESULT_ARCHIVE}")"
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
        echo "THEORY_SEED_ALLFLOAT_V3_INVALID payload_provenance=${expected}" >&2
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
print("THEORY_SEED_ALLFLOAT_V3_RUNTIME_OK", ROOT.gROOT.GetVersion(), PhysicsModel.__name__)
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
        echo "THEORY_SEED_ALLFLOAT_V3_INVALID missing_or_empty=${required}" >&2
        exit 10
    fi
done
if [[ -e "${AREA}" ]]; then
    echo "THEORY_SEED_ALLFLOAT_V3_REFUSE_EXISTING area=${AREA}" >&2
    exit 11
fi

mkdir -p "${AREA}/cen/${SIGNAL}_area" "${AREA}/fwd/${SIGNAL}_area"
cp -a "${CEN_AREA}/base.root" "${AREA}/cen/base.root"
cp -a "${FWD_AREA}/base.root" "${AREA}/fwd/base.root"
cp -a "${CEN_CARD_SOURCE}" "${AREA}/cen/${SIGNAL}_area/card.txt"
cp -a "${FWD_CARD_SOURCE}" "${AREA}/fwd/${SIGNAL}_area/card.txt"
CEN_CARD="cen/${SIGNAL}_area/card.txt"
FWD_CARD="fwd/${SIGNAL}_area/card.txt"
CARD_NAME="${SIGNAL}_card_combined.txt"

(
    cd "${AREA}"
    combineCards.py cen="${CEN_CARD}" fwd="${FWD_CARD}" > "${CARD_NAME}"
    text2workspace.py "${CARD_NAME}" -o workspace.root --channel-masks --X-no-jmax
)

M_ON="mask_cen_Cen24Pass_Region1=1,mask_cen_Cen25Pass_Region1=1,mask_fwd_Fwd24Pass_Region1=1,mask_fwd_Fwd25Pass_Region1=1"
M_FRZ="mask_cen_Cen24Pass_Region1,mask_cen_Cen25Pass_Region1,mask_fwd_Fwd24Pass_Region1,mask_fwd_Fwd25Pass_Region1"
INTERIOR_BOUNDARY_START="QCD_Fwd24rpf_par1=40,QCD_Fwd25rpf_par1=40,QCD_Fwd24rpf_par2=-40,QCD_Fwd25rpf_par2=-40"

(
    cd "${AREA}"
    combine -M MultiDimFit -d workspace.root -m 0 \
        --rMin 0 --rMax "${RMAX}" \
        --setParameters "r=0,${M_ON},jes=0,jer=0,pileup=0,ttag_pt1=0" \
        --freezeParameters "r,${M_FRZ},jes,jer,pileup,ttag_pt1" \
        --floatParameters "pdf,q2" \
        --cminDefaultMinimizerStrategy 1 --cminPreScan --cminPreFit 1 \
        --setParameterRanges 'rgx{.*rpf_par.*}=-50,50' \
        --saveWorkspace --saveFitResult -n _stage1 \
        > stage1_bootstrap.log 2>&1
    python3 "${REPO}/run3/validate_fit_result.py" \
        multidimfit_stage1.root --key fit_mdf \
        --min-cov-qual 3 --max-edm 0.01 \
        > stage1_bootstrap_validation.log 2>&1

    combine -M MultiDimFit \
        -d higgsCombine_stage1.MultiDimFit.mH0.root \
        --snapshotName MultiDimFit -m 0 \
        --rMin 0 --rMax "${RMAX}" \
        --setParameters "r=0,${M_ON},${INTERIOR_BOUNDARY_START}" \
        --freezeParameters "r,${M_FRZ}" \
        --floatParameters "jes,jer,pileup,pdf,q2,ttag_pt1" \
        --setParameterRanges 'rgx{.*rpf_par0}=0.001,50' \
        --cminPreScan --cminPreFit 1 --cminDefaultMinimizerStrategy 2 \
        --saveWorkspace --saveFitResult -n _stage2 \
        > stage2_allfloat.log 2>&1
    python3 "${REPO}/run3/validate_fit_result.py" \
        multidimfit_stage2.root --key fit_mdf \
        --min-cov-qual 3 --max-edm 0.01 \
        > stage2_allfloat_validation.log 2>&1
    python3 - <<'PY' > stage2_workspace_validation.log 2>&1
import math
import ROOT

root_file = ROOT.TFile.Open("higgsCombine_stage2.MultiDimFit.mH0.root")
if not root_file or root_file.IsZombie():
    raise RuntimeError("cannot open stage-2 masked snapshot")
workspace = root_file.Get("w")
if not workspace:
    raise RuntimeError("stage-2 masked snapshot has no workspace w")

nuisance_names = ("jes", "jer", "pileup", "pdf", "q2", "ttag_pt1")
for name in nuisance_names:
    variable = workspace.var(name)
    if not variable:
        raise RuntimeError(f"missing stage-2 nuisance {name}")
    if variable.isConstant():
        raise RuntimeError(f"stage-2 nuisance remained constant: {name}")

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
print(
    "STAGE2 WORKSPACE CHECK:",
    "all_six_nuisances_nonconstant=1",
    "rpf_count=18",
    "positive_par0=4",
    "status=0",
)
PY
)

for required in \
    "${AREA}/workspace.root" \
    "${AREA}/higgsCombine_stage1.MultiDimFit.mH0.root" \
    "${AREA}/multidimfit_stage1.root" \
    "${AREA}/higgsCombine_stage2.MultiDimFit.mH0.root" \
    "${AREA}/multidimfit_stage2.root" \
    "${AREA}/stage1_bootstrap.log" \
    "${AREA}/stage1_bootstrap_validation.log" \
    "${AREA}/stage2_allfloat.log" \
    "${AREA}/stage2_allfloat_validation.log" \
    "${AREA}/stage2_workspace_validation.log"; do
    if [[ ! -s "${required}" ]]; then
        echo "THEORY_SEED_ALLFLOAT_V3_INVALID missing_or_empty=${required}" >&2
        exit 12
    fi
done

echo "THEORY_SEED_ALLFLOAT_V3_OK mode=${MODE} width=${WIDTH} mass=${MASS}"

