#!/bin/bash
# Portable Asimov injection worker (v14 = v13 + MINIMIZER_MaxCalls, run on
# the FULL-SYSTEMATICS stage-2 snapshots of fullsyst_matrix_20260813).  An EXIT trap always returns a diagnostic
# archive, including partial ROOT/log/JSON outputs and their hashes.
set -euo pipefail

if [[ "$#" -ne 8 ]]; then
    echo "usage: $0 <width> <mass> <rMax> <label> <rInject> <start0> <startInject> <startHalfMax>" >&2
    exit 2
fi
WIDTH="$1"
MASS="$2"
RMAX="$3"
INJECTION_LABEL="$4"
RINJECT="$5"
START_ZERO="$6"
START_INJECTED="$7"
START_HALFMAX="$8"
SCRATCH="${_CONDOR_SCRATCH_DIR:?missing _CONDOR_SCRATCH_DIR}"
PAYLOAD="${SCRATCH}/injection_payload_w${WIDTH}_m${MASS}.tgz"
RUNTIME="${SCRATCH}/workspace_runtime_overlay_20260811_v1.tgz"
PAYLOAD_WORK="${SCRATCH}/injection_payload"
RUNTIME_WORK="${SCRATCH}/injection_runtime"
AREA="${SCRATCH}/injection_area"
REPO="${PAYLOAD_WORK}/bgestimation"
CMSSW_VERSION="${CMSSW_VERSION:-CMSSW_14_1_0_pre4}"
SCRAM_ARCH="${SCRAM_ARCH:-el9_amd64_gcc12}"
CURRENT_STAGE="initialization"
FIT_START_MODE="snapshot_direct_requested_seed_multidimfit_poionly_prefit"

finalize_result() {
    local payload_rc=$?
    trap - EXIT
    set +e
    mkdir -p "${SCRATCH}/injection_result/area"
    if [[ -d "${AREA}" ]]; then
        cp -a "${AREA}/." "${SCRATCH}/injection_result/area/"
    fi
    {
        echo "exit_code=${payload_rc}"
        echo "terminal_stage=${CURRENT_STAGE}"
        echo "width=${WIDTH}"
        echo "mass_GeV=${MASS}"
        echo "rMax=${RMAX}"
        echo "injection_label=${INJECTION_LABEL}"
        echo "injected_r=${RINJECT}"
        echo "start_zero=${START_ZERO}"
        echo "start_injected=${START_INJECTED}"
        echo "start_halfmax=${START_HALFMAX}"
        echo "bootstrap_seed_policy=no_bootstrap_independent_per_start"
        echo "final_nuisance_start=physical_masked_snapshot_no_override"
        echo "fit_start_mode=${FIT_START_MODE}"
        [[ -s "${PAYLOAD}" ]] && echo "payload_sha256=$(sha256sum "${PAYLOAD}" | awk '{print $1}')"
        [[ -s "${RUNTIME}" ]] && echo "runtime_sha256=$(sha256sum "${RUNTIME}" | awk '{print $1}')"
    } > "${SCRATCH}/injection_result/status.txt"
    (
        cd "${SCRATCH}/injection_result"
        find area -type f \( -name '*.root' -o -name '*.log' -o -name '*.json' \) -print0 \
            | sort -z | xargs -0 -r sha256sum > artifact_hashes.sha256
    )
    tar -C "${SCRATCH}" -czf "${SCRATCH}/.injection_result.tgz.tmp" injection_result
    mv "${SCRATCH}/.injection_result.tgz.tmp" "${SCRATCH}/injection_result.tgz"
    echo "INJECTION_PORTABLE_RESULT exit_code=${payload_rc} stage=${CURRENT_STAGE} archive=injection_result.tgz"
    exit "${payload_rc}"
}
trap finalize_result EXIT

case "${WIDTH}" in
    1) SIGNAL="signalZPrime${MASS}" ;;
    10) SIGNAL="signalZPrime${MASS}_10" ;;
    30) SIGNAL="signalZPrime${MASS}_30" ;;
    *) echo "unsupported width: ${WIDTH}" >&2; exit 3 ;;
esac
mkdir -p "${AREA}" "${PAYLOAD_WORK}" "${RUNTIME_WORK}"
[[ -s "${PAYLOAD}" ]] || { echo "missing point payload: ${PAYLOAD}" >&2; exit 4; }
[[ -s "${RUNTIME}" ]] || { echo "missing runtime overlay: ${RUNTIME}" >&2; exit 5; }
[[ -r /cvmfs/cms.cern.ch/cmsset_default.sh ]] || { echo "missing CVMFS CMS setup" >&2; exit 6; }

CURRENT_STAGE="payload_validation"
tar -xzf "${PAYLOAD}" -C "${PAYLOAD_WORK}"
tar -xzf "${RUNTIME}" -C "${RUNTIME_WORK}"
( cd "${PAYLOAD_WORK}" && sha256sum -c payload.sha256 )
( cd "${RUNTIME_WORK}" && sha256sum -c runtime.sha256 )
SNAPSHOT="${PAYLOAD_WORK}/combined_area/higgsCombine_maskedBonly.MultiDimFit.mH0.root"
[[ -s "${SNAPSHOT}" ]] || { echo "missing snapshot in point payload" >&2; exit 7; }

CURRENT_STAGE="runtime_setup"
source /cvmfs/cms.cern.ch/cmsset_default.sh
export SCRAM_ARCH
cd "${SCRATCH}"
scramv1 project CMSSW "${CMSSW_VERSION}" > "${AREA}/runtime_setup.log" 2>&1
CMS_RELEASE="${SCRATCH}/${CMSSW_VERSION}"
cp -a "${RUNTIME_WORK}/." "${CMS_RELEASE}/"
cd "${CMS_RELEASE}"
eval "$(scram runtime -sh)"
python3 - <<'PY' > "${AREA}/runtime_preflight.log" 2>&1
import ROOT
status = ROOT.gSystem.Load("libHiggsAnalysisCombinedLimit.so")
if status < 0:
    raise RuntimeError("CombinedLimit overlay failed to load")
from HiggsAnalysis.CombinedLimit.PhysicsModel import PhysicsModel
print("INJECTION_RUNTIME_OK", ROOT.gROOT.GetVersion(), PhysicsModel.__name__)
PY
combine --help >> "${AREA}/runtime_preflight.log" 2>&1
cd "${AREA}"

M_OFF="mask_cen_Cen24Pass_Region1=0,mask_cen_Cen25Pass_Region1=0,mask_fwd_Fwd24Pass_Region1=0,mask_fwd_Fwd25Pass_Region1=0"
M_FRZ="mask_cen_Cen24Pass_Region1,mask_cen_Cen25Pass_Region1,mask_fwd_Fwd24Pass_Region1,mask_fwd_Fwd25Pass_Region1"
TOY="higgsCombine_gen.GenerateOnly.mH0.123456.root"

echo "INJECTION_JOB_START width=${WIDTH} mass=${MASS} rMax=${RMAX} label=${INJECTION_LABEL} rInject=${RINJECT}"
CURRENT_STAGE="generate_asimov"
combine -M GenerateOnly -d "${SNAPSHOT}" --snapshotName MultiDimFit -m 0 \
    -t -1 -s 123456 --saveToys --toysFrequentist --bypassFrequentistFit \
    --expectSignal "${RINJECT}" \
    --setParameters "r=${RINJECT},${M_OFF}" \
    --freezeParameters "${M_FRZ}" \
    -n _gen > generate.log 2>&1
[[ -s "${TOY}" ]] || { echo "missing generated Asimov dataset" >&2; exit 12; }

run_fit() {
    local start_label="$1"
    local start_value="$2"
    local fit_root="multidimfit_fit_${start_label}.root"
    local result_root="higgsCombine_fit_${start_label}.MultiDimFit.mH0.root"

    # Each requested r seed gets an independent, identical numerical path.
    # The POI-only prefit starts at that exact r before the unchanged physical
    # nuisance model is released.  No start borrows a nuisance optimum from
    # another, and no RPF range or nuisance start is overridden.  The toy file
    # already defines the injected dataset, so the fit must not pass the
    # expectSignal option that would replace the requested initial value.
    CURRENT_STAGE="fit_${start_label}"
    combine -M MultiDimFit -d "${SNAPSHOT}" --snapshotName MultiDimFit -m 0 \
        -t -1 -s 123456 --toysFile "${TOY}" \
        --algo none \
        --rMin 0 --rMax "${RMAX}" \
        --setParameters "r=${start_value},${M_OFF}" \
        --freezeParameters "${M_FRZ}" \
        --cminPoiOnlyFit --cminDefaultMinimizerStrategy 1 \
        --cminPreScan --cminPreFit 1 --X-rtd MINIMIZER_MaxCalls=5000000 \
        --cminFallbackAlgo Minuit2,Simplex,0:0.1 \
        --saveNLL --saveWorkspace --saveFitResult -n "_fit_${start_label}" \
        > "fit_${start_label}.log" 2>&1
    [[ -s "${fit_root}" ]] || { echo "missing POI-prefit MultiDimFit result: ${fit_root}" >&2; exit 14; }
    [[ -s "${result_root}" ]] || { echo "missing POI-prefit workspace result: ${result_root}" >&2; exit 15; }

    CURRENT_STAGE="validate_${start_label}"
    python3 "${REPO}/run3/validate_fit_result.py" \
        "${fit_root}" --key fit_mdf --min-cov-qual 3 \
        > "fit_${start_label}_validation.log" 2>&1
    CURRENT_STAGE="harvest_${start_label}"
    python3 "${REPO}/run3/preunblind/harvest_fit_result.py" \
        "${fit_root}" --key fit_mdf \
        --metadata "width_percent=${WIDTH}" \
        --metadata "mass_GeV=${MASS}" \
        --metadata "rMax=${RMAX}" \
        --metadata "injection_label=${INJECTION_LABEL}" \
        --metadata "injected_r=${RINJECT}" \
        --metadata "start_label=${start_label}" \
        --metadata "start_r=${start_value}" \
        --output "fit_${start_label}.json"

}

run_fit zero "${START_ZERO}"
run_fit injected "${START_INJECTED}"
run_fit halfmax "${START_HALFMAX}"

CURRENT_STAGE="success_validation"
for required in \
    fit_zero.json fit_injected.json fit_halfmax.json \
    fit_zero_validation.log fit_injected_validation.log fit_halfmax_validation.log; do
    [[ -s "${required}" ]] || { echo "missing or empty successful artifact: ${required}" >&2; exit 13; }
done
CURRENT_STAGE="complete"
echo "INJECTION_JOB_OK width=${WIDTH} mass=${MASS} label=${INJECTION_LABEL}"
