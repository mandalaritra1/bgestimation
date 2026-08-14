#!/bin/bash
# Portable frequentist toy-injection worker for the full-systematics
# fullsyst_matrix_20260813 snapshots. One shard: generate COUNT frequentist
# toys at r=RINJECT from the masked-b-only snapshot (Pass windows unmasked),
# then fit every toy with MultiDimFit --algo singles (best-fit r and the
# +-1 sigma profile crossings per toy) at strategy 0 with the MaxCalls fix.
# Per-toy fit failures are tolerated and counted at harvest; the shard fails
# only if the toy file or the fit tree is missing entirely.
set -euo pipefail

if [[ "$#" -ne 6 ]]; then
    echo "usage: $0 <width> <mass> <rMax> <rInject> <seed> <count>" >&2
    exit 2
fi
WIDTH="$1"
MASS="$2"
RMAX="$3"
RINJECT="$4"
TOY_SEED="$5"
TOY_COUNT="$6"
case "${WIDTH}" in 1|10|30) ;; *) echo "bad width" >&2; exit 3 ;; esac
case "${MASS}" in 2000|4000|6000|7000) ;; *) echo "bad mass" >&2; exit 3 ;; esac

SCRATCH="${_CONDOR_SCRATCH_DIR:?missing _CONDOR_SCRATCH_DIR}"
PAYLOAD="${SCRATCH}/injection_payload_w${WIDTH}_m${MASS}.tgz"
RUNTIME="${SCRATCH}/workspace_runtime_overlay_20260811_v1.tgz"
PAYLOAD_WORK="${SCRATCH}/toys_payload"
RUNTIME_WORK="${SCRATCH}/toys_runtime"
AREA="${SCRATCH}/toys_area"
SNAPSHOT="${PAYLOAD_WORK}/combined_area/higgsCombine_maskedBonly.MultiDimFit.mH0.root"
CMSSW_VERSION="${CMSSW_VERSION:-CMSSW_14_1_0_pre4}"
SCRAM_ARCH="${SCRAM_ARCH:-el9_amd64_gcc12}"
CURRENT_STAGE="initialization"

finalize_result() {
    local rc=$?
    trap - EXIT
    set +e
    mkdir -p "${SCRATCH}/toys_result/area"
    [[ -d "${AREA}" ]] && cp -a "${AREA}/." "${SCRATCH}/toys_result/area/"
    {
        echo "exit_code=${rc}"
        echo "terminal_stage=${CURRENT_STAGE}"
        echo "width=${WIDTH}"
        echo "mass_GeV=${MASS}"
        echo "rMax=${RMAX}"
        echo "injected_r=${RINJECT}"
        echo "toy_seed=${TOY_SEED}"
        echo "toy_count=${TOY_COUNT}"
        echo "fit_algo=singles_strategy0_maxcalls"
        [[ -s "${PAYLOAD}" ]] && echo "payload_sha256=$(sha256sum "${PAYLOAD}" | awk '{print $1}')"
    } > "${SCRATCH}/toys_result/status.txt"
    (
        cd "${SCRATCH}/toys_result"
        find area -type f -print0 | sort -z | xargs -0 -r sha256sum > artifact_hashes.sha256
    )
    tar -C "${SCRATCH}" -czf "${SCRATCH}/.toys_result.tgz.tmp" toys_result
    mv "${SCRATCH}/.toys_result.tgz.tmp" "${SCRATCH}/toys_result.tgz"
    echo "INJECTION_TOYS_RESULT exit_code=${rc} stage=${CURRENT_STAGE}"
    exit "${rc}"
}
trap finalize_result EXIT

mkdir -p "${AREA}" "${PAYLOAD_WORK}" "${RUNTIME_WORK}"
[[ -s "${PAYLOAD}" ]] || { echo "missing point payload" >&2; exit 5; }
[[ -s "${RUNTIME}" ]] || { echo "missing runtime overlay" >&2; exit 6; }

CURRENT_STAGE="payload_validation"
tar -xzf "${PAYLOAD}" -C "${PAYLOAD_WORK}"
tar -xzf "${RUNTIME}" -C "${RUNTIME_WORK}"
( cd "${PAYLOAD_WORK}" && sha256sum -c payload.sha256 > /dev/null )
( cd "${RUNTIME_WORK}" && sha256sum -c runtime.sha256 > /dev/null )
[[ -s "${SNAPSHOT}" ]] || { echo "missing snapshot" >&2; exit 8; }

CURRENT_STAGE="runtime_setup"
source /cvmfs/cms.cern.ch/cmsset_default.sh
export SCRAM_ARCH
cd "${SCRATCH}"
scramv1 project CMSSW "${CMSSW_VERSION}" > "${AREA}/runtime_setup.log" 2>&1
cp -a "${RUNTIME_WORK}/." "${SCRATCH}/${CMSSW_VERSION}/"
cd "${SCRATCH}/${CMSSW_VERSION}"
eval "$(scram runtime -sh)"
cd "${AREA}"

M_OFF="mask_cen_Cen24Pass_Region1=0,mask_cen_Cen25Pass_Region1=0,mask_fwd_Fwd24Pass_Region1=0,mask_fwd_Fwd25Pass_Region1=0"
M_FRZ="mask_cen_Cen24Pass_Region1,mask_cen_Cen25Pass_Region1,mask_fwd_Fwd24Pass_Region1,mask_fwd_Fwd25Pass_Region1"
TOY_FILE="higgsCombine_gen.GenerateOnly.mH0.${TOY_SEED}.root"
FIT_FILE="higgsCombine_toyfits.MultiDimFit.mH0.${TOY_SEED}.root"

echo "TOYS_JOB_START w=${WIDTH} m=${MASS} rInject=${RINJECT} seed=${TOY_SEED} n=${TOY_COUNT}"
CURRENT_STAGE="generate_toys"
combine -M GenerateOnly -d "${SNAPSHOT}" --snapshotName MultiDimFit -m 0 \
    -t "${TOY_COUNT}" -s "${TOY_SEED}" --saveToys --toysFrequentist --bypassFrequentistFit \
    --expectSignal "${RINJECT}" \
    --setParameters "r=${RINJECT},${M_OFF}" \
    --freezeParameters "${M_FRZ}" \
    -n _gen > generate.log 2>&1
[[ -s "${TOY_FILE}" ]] || { echo "missing generated toys" >&2; exit 12; }

CURRENT_STAGE="fit_toys"
combine -M MultiDimFit -d "${SNAPSHOT}" --snapshotName MultiDimFit -m 0 \
    -t "${TOY_COUNT}" -s "${TOY_SEED}" --toysFile "${TOY_FILE}" \
    --algo singles \
    --rMin 0 --rMax "${RMAX}" \
    --setParameters "r=${RINJECT},${M_OFF}" \
    --freezeParameters "${M_FRZ}" \
    --cminPoiOnlyFit --cminDefaultMinimizerStrategy 0 \
    --cminPreScan --cminPreFit 1 --X-rtd MINIMIZER_MaxCalls=5000000 \
    --cminFallbackAlgo Minuit2,Simplex,0:0.1 \
    --saveNLL -n _toyfits > toyfits.log 2>&1
[[ -s "${FIT_FILE}" ]] || { echo "missing toy-fit tree" >&2; exit 14; }

CURRENT_STAGE="complete"
echo "TOYS_JOB_OK w=${WIDTH} m=${MASS} seed=${TOY_SEED}"
