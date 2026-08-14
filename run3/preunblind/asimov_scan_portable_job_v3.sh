#!/bin/bash
# Portable synthetic-Asimov 1D likelihood-scan canary.  The EXIT trap always
# returns a diagnostic archive, including partial artifacts and their hashes.
set -euo pipefail

if [[ "$#" -ne 0 ]]; then
    echo "usage: $0" >&2
    exit 2
fi

WIDTH=1
MASS=2000
PRODUCTION_RMAX=1
RINJECT="0.0169433597475"
SCAN_RMAX="0.0847167987375"  # reviewed diagnostic range = 5 * RINJECT.
GRID_POINTS=41
TOY_SEED=123456
SCRATCH="${_CONDOR_SCRATCH_DIR:?missing _CONDOR_SCRATCH_DIR}"
PAYLOAD="${SCRATCH}/asimov_scan_payload_w1_m2000.tgz"
RUNTIME="${SCRATCH}/workspace_runtime_overlay_20260811_v1.tgz"
PAYLOAD_WORK="${SCRATCH}/asimov_scan_payload"
RUNTIME_WORK="${SCRATCH}/asimov_scan_runtime"
AREA="${SCRATCH}/asimov_scan_area"
REPO="${PAYLOAD_WORK}/bgestimation"
VALIDATOR="${REPO}/run3/preunblind/validate_portable_asimov_scan.py"
SNAPSHOT="${PAYLOAD_WORK}/combined_area/higgsCombine_maskedBonly.MultiDimFit.mH0.root"
CMSSW_VERSION="${CMSSW_VERSION:-CMSSW_14_1_0_pre4}"
SCRAM_ARCH="${SCRAM_ARCH:-el9_amd64_gcc12}"
CURRENT_STAGE="initialization"

finalize_result() {
    local payload_rc=$?
    trap - EXIT
    set +e
    mkdir -p "${SCRATCH}/asimov_scan_result/area"
    if [[ -d "${AREA}" ]]; then
        cp -a "${AREA}/." "${SCRATCH}/asimov_scan_result/area/"
    fi
    {
        echo "exit_code=${payload_rc}"
        echo "terminal_stage=${CURRENT_STAGE}"
        echo "width=${WIDTH}"
        echo "mass_GeV=${MASS}"
        echo "production_rMax=${PRODUCTION_RMAX}"
        echo "diagnostic_scan_rMax=${SCAN_RMAX}"
        echo "rInject=${RINJECT}"
        echo "grid_points=${GRID_POINTS}"
        echo "toy_seed=${TOY_SEED}"
        echo "dataset_scope=synthetic_asimov_only"
        echo "pass_region_masks=all_off_frozen"
        [[ -s "${SNAPSHOT}" ]] && echo "snapshot_sha256=$(sha256sum "${SNAPSHOT}" | awk '{print $1}')"
        [[ -s "${PAYLOAD}" ]] && echo "payload_sha256=$(sha256sum "${PAYLOAD}" | awk '{print $1}')"
        [[ -s "${RUNTIME}" ]] && echo "runtime_sha256=$(sha256sum "${RUNTIME}" | awk '{print $1}')"
    } > "${SCRATCH}/asimov_scan_result/status.txt"
    (
        cd "${SCRATCH}/asimov_scan_result"
        find area -type f -print0 | sort -z | xargs -0 -r sha256sum > artifact_hashes.sha256
    )
    tar -C "${SCRATCH}" -czf "${SCRATCH}/.asimov_scan_result.tgz.tmp" asimov_scan_result
    mv "${SCRATCH}/.asimov_scan_result.tgz.tmp" "${SCRATCH}/asimov_scan_result.tgz"
    echo "ASIMOV_SCAN_PORTABLE_RESULT exit_code=${payload_rc} stage=${CURRENT_STAGE} archive=asimov_scan_result.tgz"
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
    "width=${WIDTH}" "mass_GeV=${MASS}" "production_rMax=${PRODUCTION_RMAX}" \
    "diagnostic_scan_rMax=${SCAN_RMAX}" "rInject=${RINJECT}" "grid_points=${GRID_POINTS}" \
    "dataset_scope=synthetic_asimov_only" "pass_region_masks=all_off_frozen"; do
    grep -Fxq "${expected}" "${PAYLOAD_WORK}/payload_provenance.txt" || {
        echo "ASIMOV_SCAN_INVALID payload_provenance=${expected}" >&2; exit 7;
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
print("ASIMOV_SCAN_RUNTIME_OK", ROOT.gROOT.GetVersion())
PY
combine --help >> "${AREA}/runtime_preflight.log" 2>&1

CURRENT_STAGE="snapshot_validation"
python3 "${VALIDATOR}" snapshot "${SNAPSHOT}" --production-rmax "${PRODUCTION_RMAX}" \
    --output "${AREA}/snapshot_validation.json" > "${AREA}/snapshot_validation.log" 2>&1

cd "${AREA}"
M_OFF="mask_cen_Cen24Pass_Region1=0,mask_cen_Cen25Pass_Region1=0,mask_fwd_Fwd24Pass_Region1=0,mask_fwd_Fwd25Pass_Region1=0"
M_FRZ="mask_cen_Cen24Pass_Region1,mask_cen_Cen25Pass_Region1,mask_fwd_Fwd24Pass_Region1,mask_fwd_Fwd25Pass_Region1"
TOY="higgsCombine_asimov.GenerateOnly.mH0.${TOY_SEED}.root"
# MultiDimFit names this output with mH0 but does not append the toy seed.
SCAN="higgsCombine_asimov_scan.MultiDimFit.mH0.root"

echo "ASIMOV_SCAN_JOB_START width=${WIDTH} mass=${MASS} rInject=${RINJECT} diagnostic_rMax=${SCAN_RMAX}"
CURRENT_STAGE="generate_asimov"
combine -M GenerateOnly -d "${SNAPSHOT}" --snapshotName MultiDimFit -m 0 \
    -t -1 -s "${TOY_SEED}" --saveToys --toysFrequentist --bypassFrequentistFit \
    --expectSignal "${RINJECT}" \
    --setParameters "r=${RINJECT},${M_OFF}" --freezeParameters "${M_FRZ}" \
    -n _asimov > generate_asimov.log 2>&1
[[ -s "${TOY}" ]] || { echo "missing generated synthetic Asimov ROOT" >&2; exit 10; }

CURRENT_STAGE="scan_asimov"
combine -M MultiDimFit -d "${SNAPSHOT}" --snapshotName MultiDimFit -m 0 \
    -t -1 -s "${TOY_SEED}" --toysFile "${TOY}" \
    --algo grid --points "${GRID_POINTS}" --alignEdges 1 \
    --rMin 0 --rMax "${SCAN_RMAX}" \
    --setParameters "r=${RINJECT},${M_OFF}" --freezeParameters "${M_FRZ}" \
    --cminDefaultMinimizerStrategy 1 --cminPreScan --cminPreFit 1 \
    --cminFallbackAlgo Minuit2,Simplex,0:0.1 \
    --saveNLL -n _asimov_scan > asimov_scan.log 2>&1
[[ -s "${SCAN}" ]] || { echo "missing synthetic Asimov scan ROOT" >&2; exit 11; }

CURRENT_STAGE="result_validation"
python3 "${VALIDATOR}" scan "${SCAN}" --diagnostic-rmax "${SCAN_RMAX}" \
    --grid-points "${GRID_POINTS}" --output asimov_scan_validation.json \
    > asimov_scan_validation.log 2>&1
CURRENT_STAGE="complete"
echo "ASIMOV_SCAN_JOB_OK width=${WIDTH} mass=${MASS} rInject=${RINJECT}"
