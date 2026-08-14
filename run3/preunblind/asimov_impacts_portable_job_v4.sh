#!/bin/bash
# Portable one-nuisance synthetic-Asimov Impacts worker (v4: nine-nuisance
# full-systematics model on fullsyst_matrix_20260813 snapshots, strategy 2
# + MaxCalls, injection-payload reuse).  The EXIT trap always
# returns diagnostics and checksums; it neither creates a card nor accesses data.
set -euo pipefail

if [[ "$#" -ne 5 ]]; then
    echo "usage: $0 <width> <mass_GeV> <rMax> <rInject> <named_nuisance>" >&2
    exit 2
fi

WIDTH="$1"
MASS="$2"
RMAX="$3"
RINJECT="$4"
NUISANCE="$5"
case "${WIDTH}" in 1|10|30) ;; *) echo "unsupported width: ${WIDTH}" >&2; exit 2 ;; esac
case "${NUISANCE}" in jes|jer|pileup|pdf|q2|ttag_pt1|lumi24|lumi25|ttbar_xsec) ;; *) echo "unsupported nuisance: ${NUISANCE}" >&2; exit 2 ;; esac
IMPACTS_NAME="asimov_w${WIDTH}_m${MASS}_${NUISANCE}"
TOY_SEED=123456
SCRATCH="${_CONDOR_SCRATCH_DIR:?missing _CONDOR_SCRATCH_DIR}"
PAYLOAD="${SCRATCH}/injection_payload_w${WIDTH}_m${MASS}.tgz"
RUNTIME="${SCRATCH}/workspace_runtime_overlay_20260811_v1.tgz"
PAYLOAD_WORK="${SCRATCH}/asimov_impacts_payload"
RUNTIME_WORK="${SCRATCH}/asimov_impacts_runtime"
AREA="${SCRATCH}/asimov_impacts_area"
REPO="${PAYLOAD_WORK}/bgestimation"
VALIDATOR="${SCRATCH}/validate_portable_asimov_impacts_v2.py"
FIT_VALIDATOR="${REPO}/run3/validate_fit_result.py"
SNAPSHOT="${PAYLOAD_WORK}/combined_area/higgsCombine_maskedBonly.MultiDimFit.mH0.root"
CMSSW_VERSION="${CMSSW_VERSION:-CMSSW_14_1_0_pre4}"
SCRAM_ARCH="${SCRAM_ARCH:-el9_amd64_gcc12}"
CURRENT_STAGE="initialization"

finalize_result() {
    local payload_rc=$?
    trap - EXIT
    set +e
    mkdir -p "${SCRATCH}/asimov_impacts_result/area"
    if [[ -d "${AREA}" ]]; then
        cp -a "${AREA}/." "${SCRATCH}/asimov_impacts_result/area/"
    fi
    {
        echo "exit_code=${payload_rc}"
        echo "terminal_stage=${CURRENT_STAGE}"
        echo "width=${WIDTH}"
        echo "mass_GeV=${MASS}"
        echo "production_rMax=${RMAX}"
        echo "rInject=${RINJECT}"
        echo "named_nuisance=${NUISANCE}"
        echo "named_fit_quality=not_available_in_impact_mode"
        echo "toy_seed=${TOY_SEED}"
        echo "dataset_scope=synthetic_asimov_only"
        echo "pass_region_masks=all_off_frozen"
        [[ -s "${SNAPSHOT}" ]] && echo "snapshot_sha256=$(sha256sum "${SNAPSHOT}" | awk '{print $1}')"
        [[ -s "${PAYLOAD}" ]] && echo "payload_sha256=$(sha256sum "${PAYLOAD}" | awk '{print $1}')"
        [[ -s "${RUNTIME}" ]] && echo "runtime_sha256=$(sha256sum "${RUNTIME}" | awk '{print $1}')"
    } > "${SCRATCH}/asimov_impacts_result/status.txt"
    (
        cd "${SCRATCH}/asimov_impacts_result"
        find area -type f -print0 | sort -z | xargs -0 -r sha256sum > artifact_hashes.sha256
    )
    tar -C "${SCRATCH}" -czf "${SCRATCH}/.asimov_impacts_result.tgz.tmp" asimov_impacts_result
    mv "${SCRATCH}/.asimov_impacts_result.tgz.tmp" "${SCRATCH}/asimov_impacts_result.tgz"
    echo "ASIMOV_IMPACTS_PORTABLE_RESULT exit_code=${payload_rc} stage=${CURRENT_STAGE} archive=asimov_impacts_result.tgz"
    exit "${payload_rc}"
}
trap finalize_result EXIT

mkdir -p "${AREA}" "${PAYLOAD_WORK}" "${RUNTIME_WORK}"
[[ -s "${PAYLOAD}" ]] || { echo "missing point payload: ${PAYLOAD}" >&2; exit 3; }
[[ -s "${RUNTIME}" ]] || { echo "missing runtime overlay: ${RUNTIME}" >&2; exit 4; }
[[ -r /cvmfs/cms.cern.ch/cmsset_default.sh ]] || { echo "missing CVMFS CMS setup" >&2; exit 5; }

CURRENT_STAGE="payload_validation"
tar -xzf "${PAYLOAD}" -C "${PAYLOAD_WORK}"
tar -xzf "${RUNTIME}" -C "${RUNTIME_WORK}"
( cd "${PAYLOAD_WORK}" && sha256sum -c payload.sha256 )
( cd "${RUNTIME_WORK}" && sha256sum -c runtime.sha256 )
[[ -s "${SNAPSHOT}" ]] || { echo "missing final snapshot in point payload" >&2; exit 6; }
for expected in \
    "width=${WIDTH}" "mass_GeV=${MASS}" "rMax=${RMAX}"; do
    grep -Fxq "${expected}" "${PAYLOAD_WORK}/payload_provenance.txt" || {
        echo "ASIMOV_IMPACTS_INVALID payload_provenance=${expected}" >&2; exit 7;
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
print("ASIMOV_IMPACTS_RUNTIME_OK", ROOT.gROOT.GetVersion())
PY
combine --help >> "${AREA}/runtime_preflight.log" 2>&1
combineTool.py --help >> "${AREA}/runtime_preflight.log" 2>&1

CURRENT_STAGE="snapshot_validation"
python3 "${VALIDATOR}" snapshot "${SNAPSHOT}" --rmax "${RMAX}" \
    --output "${AREA}/snapshot_validation.json" > "${AREA}/snapshot_validation.log" 2>&1

cd "${AREA}"
M_OFF="mask_cen_Cen24Pass_Region1=0,mask_cen_Cen25Pass_Region1=0,mask_fwd_Fwd24Pass_Region1=0,mask_fwd_Fwd25Pass_Region1=0"
M_FRZ="mask_cen_Cen24Pass_Region1,mask_cen_Cen25Pass_Region1,mask_fwd_Fwd24Pass_Region1,mask_fwd_Fwd25Pass_Region1"
INITIAL_ROOT="higgsCombine_initialFit_${IMPACTS_NAME}.MultiDimFit.mH0.root"
INITIAL_FIT="multidimfit_initialFit_${IMPACTS_NAME}.root"
PARAM_ROOT="higgsCombine_paramFit_${IMPACTS_NAME}_${NUISANCE}.MultiDimFit.mH0.root"

# Keep r free: it is set only as an initial value for the synthetic Asimov fit.
COMMON=( -M Impacts -d "${SNAPSHOT}" --snapshotName MultiDimFit -m 0
    -t -1 -s "${TOY_SEED}" --expectSignal "${RINJECT}" --bypassFrequentistFit
    --rMin 0 --rMax "${RMAX}"
    --setParameters "r=${RINJECT},${M_OFF}" --freezeParameters "${M_FRZ}"
    --redefineSignalPOIs r --named "${NUISANCE}" -n "${IMPACTS_NAME}"
    --robustFit 1 --saveFitResult --cminDefaultMinimizerStrategy 2
    --cminPreScan --cminPreFit 1 --X-rtd MINIMIZER_MaxCalls=5000000 )

echo "ASIMOV_IMPACTS_JOB_START width=${WIDTH} mass=${MASS} nuisance=${NUISANCE} rInject=${RINJECT}"
CURRENT_STAGE="initial_fit"
combineTool.py "${COMMON[@]}" --doInitialFit > initial_fit.log 2>&1
[[ -s "${INITIAL_ROOT}" ]] || { echo "missing initial-fit Impacts ROOT" >&2; exit 10; }
CURRENT_STAGE="validate_initial_fit"
python3 "${FIT_VALIDATOR}" "${INITIAL_FIT}" --key fit_mdf --min-cov-qual 3 --max-edm 0.01 \
    > initial_fit_validation.log 2>&1

CURRENT_STAGE="named_nuisance_fit"
# In this local CombinedLimit source, MultiDimFit::Impact does not call
# saveResult(), so the named fit has no RooFitResult/covQual/EDM artifact.
# Its exact ROOT result and the finite collected impact are gated downstream.
combineTool.py "${COMMON[@]}" --doFits > named_nuisance_fit.log 2>&1
[[ -s "${PARAM_ROOT}" ]] || { echo "missing named-nuisance Impacts ROOT" >&2; exit 11; }
python3 "${VALIDATOR}" parameter-fit "${PARAM_ROOT}" --nuisance "${NUISANCE}" \
    --rmax "${RMAX}" --output named_fit_validation.json \
    > named_fit_validation.log 2>&1

CURRENT_STAGE="collect_impacts_json"
combineTool.py "${COMMON[@]}" -o "impacts_${NUISANCE}.json" > collect_impacts.log 2>&1
CURRENT_STAGE="validate_impacts_json"
python3 "${VALIDATOR}" impacts "impacts_${NUISANCE}.json" --nuisance "${NUISANCE}" \
    --output impacts_validation.json > impacts_validation.log 2>&1
CURRENT_STAGE="complete"
echo "ASIMOV_IMPACTS_JOB_OK width=${WIDTH} mass=${MASS} nuisance=${NUISANCE}"
