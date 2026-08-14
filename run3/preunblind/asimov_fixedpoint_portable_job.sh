#!/bin/bash
# One independent synthetic-Asimov fixed-r profile point.  No observed-data
# input is used; the EXIT trap returns a diagnostic archive on every outcome.
set -euo pipefail

if [[ "$#" -ne 2 ]]; then
    echo "usage: $0 POINT_INDEX TARGET_R" >&2
    exit 2
fi
POINT_INDEX="$1"
TARGET_R="$2"
[[ "${POINT_INDEX}" =~ ^[0-9]{3}$ ]] || { echo "invalid point index" >&2; exit 2; }

WIDTH=1
MASS=2000
PRODUCTION_RMAX=1
RINJECT="0.0169433597475"
SCAN_RMAX="0.0847167987375"
TOY_SEED=123456
SCRATCH="${_CONDOR_SCRATCH_DIR:?missing _CONDOR_SCRATCH_DIR}"
PAYLOAD="${SCRATCH}/asimov_scan_payload_w1_m2000.tgz"
RUNTIME="${SCRATCH}/workspace_runtime_overlay_20260811_v1.tgz"
VALIDATOR_SOURCE="${SCRATCH}/validate_portable_asimov_fixedpoint.py"
PAYLOAD_WORK="${SCRATCH}/asimov_fixedpoint_payload"
RUNTIME_WORK="${SCRATCH}/asimov_fixedpoint_runtime"
AREA="${SCRATCH}/asimov_fixedpoint_area"
REPO="${PAYLOAD_WORK}/bgestimation"
SNAPSHOT_VALIDATOR="${REPO}/run3/preunblind/validate_portable_asimov_scan.py"
SNAPSHOT="${PAYLOAD_WORK}/combined_area/higgsCombine_maskedBonly.MultiDimFit.mH0.root"
CMSSW_VERSION="${CMSSW_VERSION:-CMSSW_14_1_0_pre4}"
SCRAM_ARCH="${SCRAM_ARCH:-el9_amd64_gcc12}"
CURRENT_STAGE="initialization"

finalize_result() {
    local payload_rc=$?
    trap - EXIT
    set +e
    mkdir -p "${SCRATCH}/asimov_fixedpoint_result/area"
    [[ -d "${AREA}" ]] && cp -a "${AREA}/." "${SCRATCH}/asimov_fixedpoint_result/area/"
    {
        echo "exit_code=${payload_rc}"
        echo "terminal_stage=${CURRENT_STAGE}"
        echo "width=${WIDTH}"
        echo "mass_GeV=${MASS}"
        echo "production_rMax=${PRODUCTION_RMAX}"
        echo "diagnostic_scan_rMax=${SCAN_RMAX}"
        echo "rInject=${RINJECT}"
        echo "point_index=${POINT_INDEX}"
        echo "target_r=${TARGET_R}"
        echo "toy_seed=${TOY_SEED}"
        echo "dataset_scope=synthetic_asimov_only"
        echo "pass_region_masks=all_off_frozen"
        echo "fit_method=independent_fixed_point_robust"
        [[ -s "${SNAPSHOT}" ]] && echo "snapshot_sha256=$(sha256sum "${SNAPSHOT}" | awk '{print $1}')"
        [[ -s "${PAYLOAD}" ]] && echo "payload_sha256=$(sha256sum "${PAYLOAD}" | awk '{print $1}')"
        [[ -s "${RUNTIME}" ]] && echo "runtime_sha256=$(sha256sum "${RUNTIME}" | awk '{print $1}')"
    } > "${SCRATCH}/asimov_fixedpoint_result/status.txt"
    (
        cd "${SCRATCH}/asimov_fixedpoint_result"
        find area -type f -print0 | sort -z | xargs -0 -r sha256sum > artifact_hashes.sha256
    )
    tar -C "${SCRATCH}" -czf "${SCRATCH}/.asimov_fixedpoint_result.tgz.tmp" asimov_fixedpoint_result
    mv "${SCRATCH}/.asimov_fixedpoint_result.tgz.tmp" "${SCRATCH}/asimov_fixedpoint_result.tgz"
    echo "ASIMOV_FIXEDPOINT_RESULT exit_code=${payload_rc} stage=${CURRENT_STAGE} index=${POINT_INDEX}"
    exit "${payload_rc}"
}
trap finalize_result EXIT

mkdir -p "${AREA}" "${PAYLOAD_WORK}" "${RUNTIME_WORK}"
for required in "${PAYLOAD}" "${RUNTIME}" "${VALIDATOR_SOURCE}"; do
    [[ -s "${required}" ]] || { echo "missing worker input: ${required}" >&2; exit 3; }
done
CURRENT_STAGE="payload_validation"
tar -xzf "${PAYLOAD}" -C "${PAYLOAD_WORK}"
tar -xzf "${RUNTIME}" -C "${RUNTIME_WORK}"
( cd "${PAYLOAD_WORK}" && sha256sum -c payload.sha256 )
( cd "${RUNTIME_WORK}" && sha256sum -c runtime.sha256 )
for expected in \
    "width=${WIDTH}" "mass_GeV=${MASS}" "production_rMax=${PRODUCTION_RMAX}" \
    "diagnostic_scan_rMax=${SCAN_RMAX}" "rInject=${RINJECT}" \
    "dataset_scope=synthetic_asimov_only" "pass_region_masks=all_off_frozen"; do
    grep -Fxq "${expected}" "${PAYLOAD_WORK}/payload_provenance.txt" || {
        echo "ASIMOV_FIXEDPOINT_INVALID provenance=${expected}" >&2; exit 4;
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
print("ASIMOV_FIXEDPOINT_RUNTIME_OK", ROOT.gROOT.GetVersion())
PY

CURRENT_STAGE="snapshot_validation"
python3 "${SNAPSHOT_VALIDATOR}" snapshot "${SNAPSHOT}" --production-rmax "${PRODUCTION_RMAX}" \
    --output "${AREA}/snapshot_validation.json" > "${AREA}/snapshot_validation.log" 2>&1

cd "${AREA}"
M_OFF="mask_cen_Cen24Pass_Region1=0,mask_cen_Cen25Pass_Region1=0,mask_fwd_Fwd24Pass_Region1=0,mask_fwd_Fwd25Pass_Region1=0"
M_FRZ="mask_cen_Cen24Pass_Region1,mask_cen_Cen25Pass_Region1,mask_fwd_Fwd24Pass_Region1,mask_fwd_Fwd25Pass_Region1"
TOY="higgsCombine_asimov.GenerateOnly.mH0.${TOY_SEED}.root"
FIXED="higgsCombine_fixedpoint_${POINT_INDEX}.MultiDimFit.mH0.root"

CURRENT_STAGE="generate_asimov"
combine -M GenerateOnly -d "${SNAPSHOT}" --snapshotName MultiDimFit -m 0 \
    -t -1 -s "${TOY_SEED}" --saveToys --toysFrequentist --bypassFrequentistFit \
    --expectSignal "${RINJECT}" --setParameters "r=${RINJECT},${M_OFF}" \
    --freezeParameters "${M_FRZ}" -n _asimov > generate_asimov.log 2>&1
[[ -s "${TOY}" ]] || { echo "missing synthetic Asimov toy" >&2; exit 10; }

CURRENT_STAGE="profile_fixed_point"
combine -M MultiDimFit -d "${SNAPSHOT}" --snapshotName MultiDimFit -m 0 \
    -t -1 -s "${TOY_SEED}" --toysFile "${TOY}" \
    --algo fixed --fixedPointPOIs "r=${TARGET_R}" \
    --rMin 0 --rMax "${SCAN_RMAX}" \
    --setParameters "r=${TARGET_R},${M_OFF}" --freezeParameters "${M_FRZ}" \
    --robustFit 1 --cminDefaultMinimizerStrategy 1 --cminPreScan --cminPreFit 1 \
    --cminFallbackAlgo Minuit2,Simplex,0:0.1 --saveNLL \
    -n "_fixedpoint_${POINT_INDEX}" > fixedpoint.log 2>&1
[[ -s "${FIXED}" ]] || { echo "missing fixed-point ROOT" >&2; exit 11; }

CURRENT_STAGE="result_validation"
python3 "${VALIDATOR_SOURCE}" "${FIXED}" --target-r "${TARGET_R}" \
    --scan-rmax "${SCAN_RMAX}" --output fixedpoint_validation.json \
    > fixedpoint_validation.log 2>&1
CURRENT_STAGE="complete"
echo "ASIMOV_FIXEDPOINT_OK index=${POINT_INDEX} target_r=${TARGET_R}"
