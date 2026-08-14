#!/bin/bash
# Portable masked saturated-GoF worker.  The EXIT trap always returns a
# diagnostic archive, including partial logs/ROOT files and their hashes.
set -euo pipefail

if [[ "$#" -ne 5 ]]; then
    echo "usage: $0 <width> <mass> <rMax> <toy_seed> <toy_count>" >&2
    exit 2
fi
WIDTH="$1"
MASS="$2"
RMAX="$3"
TOY_SEED="$4"
TOY_COUNT="$5"
if [[ "${WIDTH}" != 1 || "${MASS}" != 2000 || "${RMAX}" != 1 ]]; then
    echo "this reviewed canary is restricted to width=1 mass=2000 rMax=1" >&2
    exit 3
fi
if ! [[ "${TOY_SEED}" =~ ^[1-9][0-9]*$ && "${TOY_COUNT}" =~ ^[1-9][0-9]*$ ]] \
        || (( TOY_COUNT > 200 )); then
    echo "toy seed/count must be positive integers and toy_count must be <=200" >&2
    exit 4
fi

SIGNAL="signalZPrime2000"
SCRATCH="${_CONDOR_SCRATCH_DIR:?missing _CONDOR_SCRATCH_DIR}"
PAYLOAD="${SCRATCH}/gof_payload_w1_m2000.tgz"
RUNTIME="${SCRATCH}/workspace_runtime_overlay_20260811_v1.tgz"
PAYLOAD_WORK="${SCRATCH}/gof_payload"
RUNTIME_WORK="${SCRATCH}/gof_runtime"
AREA="${SCRATCH}/gof_area"
REPO="${PAYLOAD_WORK}/bgestimation"
VALIDATOR="${REPO}/run3/preunblind/validate_portable_gof.py"
SNAPSHOT="${PAYLOAD_WORK}/combined_area/higgsCombine_maskedBonly.MultiDimFit.mH0.root"
CMSSW_VERSION="${CMSSW_VERSION:-CMSSW_14_1_0_pre4}"
SCRAM_ARCH="${SCRAM_ARCH:-el9_amd64_gcc12}"
CURRENT_STAGE="initialization"

finalize_result() {
    local payload_rc=$?
    trap - EXIT
    set +e
    mkdir -p "${SCRATCH}/gof_result/area"
    if [[ -d "${AREA}" ]]; then
        cp -a "${AREA}/." "${SCRATCH}/gof_result/area/"
    fi
    {
        echo "exit_code=${payload_rc}"
        echo "terminal_stage=${CURRENT_STAGE}"
        echo "width=${WIDTH}"
        echo "mass_GeV=${MASS}"
        echo "signal=${SIGNAL}"
        echo "rMax=${RMAX}"
        echo "algorithm=saturated"
        echo "data_scope=observed_sideband_only"
        echo "pass_region_masks=all_on_frozen"
        echo "r_state=fixed_zero"
        echo "toy_seed=${TOY_SEED}"
        echo "toy_count=${TOY_COUNT}"
        [[ -s "${SNAPSHOT}" ]] && echo "snapshot_sha256=$(sha256sum "${SNAPSHOT}" | awk '{print $1}')"
        [[ -s "${PAYLOAD}" ]] && echo "payload_sha256=$(sha256sum "${PAYLOAD}" | awk '{print $1}')"
        [[ -s "${RUNTIME}" ]] && echo "runtime_sha256=$(sha256sum "${RUNTIME}" | awk '{print $1}')"
    } > "${SCRATCH}/gof_result/status.txt"
    (
        cd "${SCRATCH}/gof_result"
        find area -type f -print0 | sort -z | xargs -0 -r sha256sum > artifact_hashes.sha256
    )
    tar -C "${SCRATCH}" -czf "${SCRATCH}/.gof_result.tgz.tmp" gof_result
    mv "${SCRATCH}/.gof_result.tgz.tmp" "${SCRATCH}/gof_result.tgz"
    echo "GOF_PORTABLE_RESULT exit_code=${payload_rc} stage=${CURRENT_STAGE} archive=gof_result.tgz"
    exit "${payload_rc}"
}
trap finalize_result EXIT

mkdir -p "${AREA}" "${PAYLOAD_WORK}" "${RUNTIME_WORK}"
[[ -s "${PAYLOAD}" ]] || { echo "missing point payload: ${PAYLOAD}" >&2; exit 5; }
[[ -s "${RUNTIME}" ]] || { echo "missing runtime overlay: ${RUNTIME}" >&2; exit 6; }
[[ -r /cvmfs/cms.cern.ch/cmsset_default.sh ]] || { echo "missing CVMFS CMS setup" >&2; exit 7; }

CURRENT_STAGE="payload_validation"
tar -xzf "${PAYLOAD}" -C "${PAYLOAD_WORK}"
tar -xzf "${RUNTIME}" -C "${RUNTIME_WORK}"
( cd "${PAYLOAD_WORK}" && sha256sum -c payload.sha256 )
( cd "${RUNTIME_WORK}" && sha256sum -c runtime.sha256 )
[[ -s "${SNAPSHOT}" ]] || { echo "missing final snapshot in point payload" >&2; exit 8; }

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
print("GOF_RUNTIME_OK", ROOT.gROOT.GetVersion())
PY
combine --help >> "${AREA}/runtime_preflight.log" 2>&1

CURRENT_STAGE="snapshot_validation"
python3 "${VALIDATOR}" snapshot "${SNAPSHOT}" --rmax "${RMAX}" \
    --output "${AREA}/snapshot_validation.json" \
    > "${AREA}/snapshot_validation.log" 2>&1

cd "${AREA}"
M_ON="mask_cen_Cen24Pass_Region1=1,mask_cen_Cen25Pass_Region1=1,mask_fwd_Fwd24Pass_Region1=1,mask_fwd_Fwd25Pass_Region1=1"
M_FRZ="mask_cen_Cen24Pass_Region1,mask_cen_Cen25Pass_Region1,mask_fwd_Fwd24Pass_Region1,mask_fwd_Fwd25Pass_Region1"
DATA_ROOT="higgsCombine_gof_masked_data.GoodnessOfFit.mH0.root"
TOY_ROOT="higgsCombine_gof_masked_toys.GoodnessOfFit.mH0.${TOY_SEED}.root"

echo "GOF_JOB_START width=${WIDTH} mass=${MASS} toys=${TOY_COUNT} seed=${TOY_SEED}"
CURRENT_STAGE="observed_sideband_statistic"
combine -M GoodnessOfFit -d "${SNAPSHOT}" --snapshotName MultiDimFit -m 0 \
    --algo saturated --rMin 0 --rMax "${RMAX}" \
    --setParameters "r=0,${M_ON}" --freezeParameters "r,${M_FRZ}" \
    -n _gof_masked_data > gof_data.log 2>&1
[[ -s "${DATA_ROOT}" ]] || { echo "missing observed-sideband GoF ROOT" >&2; exit 10; }

CURRENT_STAGE="masked_toy_shard"
combine -M GoodnessOfFit -d "${SNAPSHOT}" --snapshotName MultiDimFit -m 0 \
    --algo saturated --rMin 0 --rMax "${RMAX}" \
    --setParameters "r=0,${M_ON}" --freezeParameters "r,${M_FRZ}" \
    --toysFrequentist -t "${TOY_COUNT}" -s "${TOY_SEED}" \
    -n _gof_masked_toys > gof_toys.log 2>&1
[[ -s "${TOY_ROOT}" ]] || { echo "missing masked-toy GoF ROOT" >&2; exit 11; }

CURRENT_STAGE="result_validation"
python3 "${VALIDATOR}" results --data "${DATA_ROOT}" --toys "${TOY_ROOT}" \
    --toy-count "${TOY_COUNT}" --seed "${TOY_SEED}" \
    --output gof_validation.json > gof_validation.log 2>&1
CURRENT_STAGE="complete"
echo "GOF_JOB_OK width=${WIDTH} mass=${MASS} toys=${TOY_COUNT} seed=${TOY_SEED}"
