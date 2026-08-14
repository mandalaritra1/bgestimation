#!/bin/bash
# GATE 1 (UNBLINDING) — saturated GoF on the UNMASKED data + a frequentist
# toy block, from the Gate-1 b-only snapshot. Criterion 1.2: p >= 0.05 over
# the aggregated 500-toy ensemble (25 jobs x 20 toys; the observed statistic
# is recomputed identically in every job and cross-checked at harvest).
# No signal quantity is computed. INTERLOCK: argument 4 must be GATE0-PASSED.
set -euo pipefail

if [[ "$#" -ne 4 ]]; then
    echo "usage: $0 <mode> <seed> <ntoys> GATE0-PASSED" >&2
    exit 2
fi
MODE="$1"
SEED="$2"
NTOYS="$3"
INTERLOCK="$4"
case "${MODE}" in gate1_gof_data) ;; *) echo "bad mode" >&2; exit 4 ;; esac
[[ "${SEED}" =~ ^[0-9]+$ && "${NTOYS}" =~ ^[0-9]+$ ]] || { echo "bad seed/ntoys" >&2; exit 3; }
[[ "${INTERLOCK}" == "GATE0-PASSED" ]] || {
    echo "GATE1_INTERLOCK: refusing to open the SR — Gate 0 not confirmed" >&2
    exit 90
}

SCRATCH="${_CONDOR_SCRATCH_DIR:?missing _CONDOR_SCRATCH_DIR}"
# Input = the Gate-1 fit result archive (produced by gate1_bonly_unmasked_job.sh).
FITRESULT="${SCRATCH}/gate1_bonly_result.tgz"
RUNTIME="${SCRATCH}/workspace_runtime_overlay_20260811_v1.tgz"
RUNTIME_WORK="${SCRATCH}/gof_runtime"
AREA="${SCRATCH}/gof_area"
RESULT="${SCRATCH}/gate1_gof_result"
RESULT_ARCHIVE="${SCRATCH}/gate1_gof_result.tgz"
CMSSW_VERSION="${CMSSW_VERSION:-CMSSW_14_1_0_pre4}"
SCRAM_ARCH="${SCRAM_ARCH:-el9_amd64_gcc12}"

finalize_result() {
    local rc=$?
    trap - EXIT
    set +e
    mkdir -p "${RESULT}"
    for f in "${AREA}"/gof_observed.log "${AREA}"/gof_toys.log \
             "${AREA}"/higgsCombine_gofObs.GoodnessOfFit.mH0*.root \
             "${AREA}"/higgsCombine_gofToys.GoodnessOfFit.mH0*.root; do
        [[ -f "$f" ]] && cp -a "$f" "${RESULT}/"
    done
    {
        echo "campaign=gate1_gof_data"
        echo "exit_code=${rc}"
        [[ "${rc}" -eq 0 ]] && echo "status=success" || echo "status=failure"
        echo "seed=${SEED}"
        echo "ntoys=${NTOYS}"
        echo "scope=unmasked_data_saturated_gof_bonly"
        [[ -s "${FITRESULT}" ]] && echo "fitresult_sha256=$(sha256sum "${FITRESULT}" | awk '{print $1}')"
    } > "${RESULT}/diagnostic.status"
    tar -C "${SCRATCH}" -czf "${RESULT_ARCHIVE}" "$(basename "${RESULT}")"
    echo "GATE1_GOF_DONE rc=${rc}"
    exit "${rc}"
}
trap finalize_result EXIT

[[ -s "${FITRESULT}" && -s "${RUNTIME}" ]] || { echo "missing inputs" >&2; exit 5; }
mkdir -p "${RUNTIME_WORK}" "${AREA}" "${RESULT}"
tar -xzf "${FITRESULT}" -C "${SCRATCH}"
SNAPSHOT="${SCRATCH}/gate1_bonly_result/artifacts/higgsCombine_gate1BonlyUnmasked.MultiDimFit.mH0.root"
[[ -s "${SNAPSHOT}" ]] || { echo "missing Gate-1 snapshot in fit archive" >&2; exit 6; }
grep -Fxq "status=success" "${SCRATCH}/gate1_bonly_result/diagnostic.status" || {
    echo "GATE1_GOF_INVALID: upstream Gate-1 fit was not successful" >&2; exit 7; }
tar -xzf "${RUNTIME}" -C "${RUNTIME_WORK}"
( cd "${RUNTIME_WORK}" && sha256sum -c runtime.sha256 > /dev/null )

source /cvmfs/cms.cern.ch/cmsset_default.sh
export SCRAM_ARCH
cd "${SCRATCH}"
scramv1 project CMSSW "${CMSSW_VERSION}" > /dev/null 2>&1
cp -a "${RUNTIME_WORK}/." "${SCRATCH}/${CMSSW_VERSION}/"
cd "${SCRATCH}/${CMSSW_VERSION}"
eval "$(scram runtime -sh)"
cd "${AREA}"

M_OFF="mask_cen_Cen24Pass_Region1=0,mask_cen_Cen25Pass_Region1=0,mask_fwd_Fwd24Pass_Region1=0,mask_fwd_Fwd25Pass_Region1=0"
M_FRZ="mask_cen_Cen24Pass_Region1,mask_cen_Cen25Pass_Region1,mask_fwd_Fwd24Pass_Region1,mask_fwd_Fwd25Pass_Region1"

combine -M GoodnessOfFit -d "${SNAPSHOT}" --snapshotName MultiDimFit -m 0 \
    --algo saturated --rMin 0 --rMax 1 \
    --setParameters "r=0,${M_OFF}" --freezeParameters "r,${M_FRZ}" \
    --X-rtd MINIMIZER_MaxCalls=5000000 \
    -n _gofObs > gof_observed.log 2>&1

combine -M GoodnessOfFit -d "${SNAPSHOT}" --snapshotName MultiDimFit -m 0 \
    --algo saturated --rMin 0 --rMax 1 \
    -t "${NTOYS}" -s "${SEED}" --toysFrequentist \
    --setParameters "r=0,${M_OFF}" --freezeParameters "r,${M_FRZ}" \
    --X-rtd MINIMIZER_MaxCalls=5000000 \
    -n _gofToys > gof_toys.log 2>&1

ls higgsCombine_gofObs.GoodnessOfFit.mH0*.root > /dev/null
ls higgsCombine_gofToys.GoodnessOfFit.mH0*.root > /dev/null
echo "GATE1_GOF_OK seed=${SEED} ntoys=${NTOYS}"
