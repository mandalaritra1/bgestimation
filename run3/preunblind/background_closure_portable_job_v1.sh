#!/bin/bash
# Blinded background-only Asimov closure with two independent free-r fits.
set -euo pipefail

if [[ "$#" -ne 0 ]]; then
    echo "usage: $0" >&2
    exit 2
fi

WIDTH=1
MASS=2000
RMAX=1
RINJECT=0
START_ZERO=0
START_HALFMAX=0.5
TOY_SEED=123456
FIT_START_MODE="independent_robust_impacts_initialfit"
SCRATCH="${_CONDOR_SCRATCH_DIR:?missing _CONDOR_SCRATCH_DIR}"
PAYLOAD="${SCRATCH}/injection_payload_w1_m2000.tgz"
RUNTIME="${SCRATCH}/workspace_runtime_overlay_20260811_v1.tgz"
PAYLOAD_WORK="${SCRATCH}/background_closure_payload"
RUNTIME_WORK="${SCRATCH}/background_closure_runtime"
AREA="${SCRATCH}/background_closure_area"
REPO="${PAYLOAD_WORK}/bgestimation"
SNAPSHOT="${PAYLOAD_WORK}/combined_area/higgsCombine_maskedBonly.MultiDimFit.mH0.root"
CMSSW_VERSION="${CMSSW_VERSION:-CMSSW_14_1_0_pre4}"
SCRAM_ARCH="${SCRAM_ARCH:-el9_amd64_gcc12}"
CURRENT_STAGE="initialization"

finalize_result() {
    local payload_rc=$?
    trap - EXIT
    set +e
    mkdir -p "${SCRATCH}/background_closure_result/area"
    if [[ -d "${AREA}" ]]; then
        cp -a "${AREA}/." "${SCRATCH}/background_closure_result/area/"
    fi
    {
        echo "exit_code=${payload_rc}"
        echo "terminal_stage=${CURRENT_STAGE}"
        echo "width=${WIDTH}"
        echo "mass_GeV=${MASS}"
        echo "rMax=${RMAX}"
        echo "closure_hypothesis=background_only"
        echo "rInject=${RINJECT}"
        echo "dataset_scope=synthetic_asimov_only"
        echo "pass_region_masks=all_off_frozen"
        echo "r_floating=1"
        echo "rMin=0"
        echo "start_zero=${START_ZERO}"
        echo "start_halfmax=${START_HALFMAX}"
        echo "fit_count=2"
        echo "fit_start_mode=${FIT_START_MODE}"
        echo "bootstrap_seed_policy=no_bootstrap_independent_per_start"
        echo "final_nuisance_start=physical_masked_snapshot_no_override"
        echo "rpf_range_override=none"
        echo "toy_seed=${TOY_SEED}"
        [[ -s "${SNAPSHOT}" ]] && echo "snapshot_sha256=$(sha256sum "${SNAPSHOT}" | awk '{print $1}')"
        [[ -s "${PAYLOAD}" ]] && echo "payload_sha256=$(sha256sum "${PAYLOAD}" | awk '{print $1}')"
        [[ -s "${RUNTIME}" ]] && echo "runtime_sha256=$(sha256sum "${RUNTIME}" | awk '{print $1}')"
    } > "${SCRATCH}/background_closure_result/status.txt"
    (
        cd "${SCRATCH}/background_closure_result"
        find area -type f \( -name '*.root' -o -name '*.log' -o -name '*.json' \) -print0 \
            | sort -z | xargs -0 -r sha256sum > artifact_hashes.sha256
    )
    tar -C "${SCRATCH}" -czf "${SCRATCH}/.background_closure_result.tgz.tmp" background_closure_result
    mv "${SCRATCH}/.background_closure_result.tgz.tmp" "${SCRATCH}/background_closure_result.tgz"
    echo "BACKGROUND_CLOSURE_RESULT exit_code=${payload_rc} stage=${CURRENT_STAGE}"
    exit "${payload_rc}"
}
trap finalize_result EXIT

mkdir -p "${AREA}" "${PAYLOAD_WORK}" "${RUNTIME_WORK}"
[[ -s "${PAYLOAD}" ]] || { echo "missing point payload" >&2; exit 3; }
[[ -s "${RUNTIME}" ]] || { echo "missing runtime overlay" >&2; exit 4; }
[[ -r /cvmfs/cms.cern.ch/cmsset_default.sh ]] || { echo "missing CVMFS CMS setup" >&2; exit 5; }

CURRENT_STAGE="payload_validation"
tar -xzf "${PAYLOAD}" -C "${PAYLOAD_WORK}"
tar -xzf "${RUNTIME}" -C "${RUNTIME_WORK}"
( cd "${PAYLOAD_WORK}" && sha256sum -c payload.sha256 )
( cd "${RUNTIME_WORK}" && sha256sum -c runtime.sha256 )
[[ -s "${SNAPSHOT}" ]] || { echo "missing masked physical snapshot" >&2; exit 6; }
for expected in "width=1" "mass_GeV=2000" "rMax=1"; do
    grep -Fxq "${expected}" "${PAYLOAD_WORK}/payload_provenance.txt" || {
        echo "BACKGROUND_CLOSURE_INVALID provenance=${expected}" >&2; exit 7;
    }
done

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
print("BACKGROUND_CLOSURE_RUNTIME_OK", ROOT.gROOT.GetVersion())
PY
combine --help >> "${AREA}/runtime_preflight.log" 2>&1
cd "${AREA}"

M_OFF="mask_cen_Cen24Pass_Region1=0,mask_cen_Cen25Pass_Region1=0,mask_fwd_Fwd24Pass_Region1=0,mask_fwd_Fwd25Pass_Region1=0"
M_FRZ="mask_cen_Cen24Pass_Region1,mask_cen_Cen25Pass_Region1,mask_fwd_Fwd24Pass_Region1,mask_fwd_Fwd25Pass_Region1"
TOY="higgsCombine_gen.GenerateOnly.mH0.${TOY_SEED}.root"
CURRENT_STAGE="generate_asimov"
combine -M GenerateOnly -d "${SNAPSHOT}" --snapshotName MultiDimFit -m 0 \
    -t -1 -s "${TOY_SEED}" --saveToys --toysFrequentist --bypassFrequentistFit \
    --expectSignal 0 --setParameters "r=0,${M_OFF}" --freezeParameters "${M_FRZ}" \
    -n _gen > generate.log 2>&1
[[ -s "${TOY}" ]] || { echo "missing background-only Asimov toy" >&2; exit 10; }

run_fit() {
    local start_label="$1"
    local start_value="$2"
    local fit_name="background_closure_w1_m2000_${start_label}"
    local fit_root="multidimfit_initialFit_${fit_name}.root"
    local result_root="higgsCombine_initialFit_${fit_name}.MultiDimFit.mH0.root"
    CURRENT_STAGE="fit_${start_label}"
    combineTool.py -M Impacts -d "${SNAPSHOT}" --snapshotName MultiDimFit -m 0 \
        -t -1 -s "${TOY_SEED}" --toysFile "${TOY}" \
        --expectSignal 0 --bypassFrequentistFit --rMin 0 --rMax "${RMAX}" \
        --setParameters "r=${start_value},${M_OFF}" --freezeParameters "${M_FRZ}" \
        --redefineSignalPOIs r --named lumi24 --robustFit 1 --saveFitResult \
        -n "${fit_name}" --doInitialFit > "fit_${start_label}.log" 2>&1
    [[ -s "${fit_root}" ]] || { echo "missing closure fit ROOT: ${fit_root}" >&2; exit 11; }
    [[ -s "${result_root}" ]] || { echo "missing closure result ROOT: ${result_root}" >&2; exit 12; }
    CURRENT_STAGE="validate_${start_label}"
    python3 "${REPO}/run3/validate_fit_result.py" "${fit_root}" \
        --key fit_mdf --min-cov-qual 3 --max-edm 0.01 \
        > "fit_${start_label}_validation.log" 2>&1
    CURRENT_STAGE="harvest_${start_label}"
    python3 "${REPO}/run3/preunblind/harvest_fit_result.py" "${fit_root}" --key fit_mdf \
        --metadata "width_percent=1" --metadata "mass_GeV=2000" \
        --metadata "rMax=1" --metadata "closure_hypothesis=background_only" \
        --metadata "injected_r=0" --metadata "start_label=${start_label}" \
        --metadata "start_r=${start_value}" --output "fit_${start_label}.json"
}

run_fit zero "${START_ZERO}"
run_fit halfmax "${START_HALFMAX}"
CURRENT_STAGE="success_validation"
for required in fit_zero.json fit_halfmax.json fit_zero_validation.log fit_halfmax_validation.log; do
    [[ -s "${required}" ]] || { echo "missing successful closure artifact: ${required}" >&2; exit 13; }
done
CURRENT_STAGE="complete"
echo "BACKGROUND_CLOSURE_JOB_OK"
