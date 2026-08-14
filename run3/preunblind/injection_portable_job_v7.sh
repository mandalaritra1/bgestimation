#!/bin/bash
# Portable Asimov injection worker.  An EXIT trap always returns a diagnostic
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
START_HIGH="$8"
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
FIT_START_MODE="wide_bootstrap_then_physical_multidimfit"

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
        echo "start_high=${START_HIGH}"
        echo "bootstrap_start_r=${RINJECT}"
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
INTERIOR_BOUNDARY_START="QCD_Fwd24rpf_par2=-45,QCD_Fwd25rpf_par2=-45"
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

# Use one common numerical nuisance seed for all three signal-strength starts.
# This bootstrap is diagnostic only: its RPF ranges are deliberately wide and
# are not accepted as the physical injection result.
CURRENT_STAGE="bootstrap"
combine -M MultiDimFit -d "${SNAPSHOT}" --snapshotName MultiDimFit -m 0 \
    -t -1 -s 123456 --toysFile "${TOY}" \
    --algo none \
    --rMin 0 --rMax "${RMAX}" \
    --setParameters "r=${RINJECT},${M_OFF}" \
    --freezeParameters "${M_FRZ}" \
    --setParameterRanges 'rgx{.*rpf_par.*}=-50,50' \
    --cminDefaultMinimizerStrategy 1 --cminPreScan --cminPreFit 1 \
    --saveNLL --saveWorkspace --saveFitResult \
    -n _bootstrap > bootstrap.log 2>&1

CURRENT_STAGE="validate_bootstrap"
python3 "${REPO}/run3/validate_fit_result.py" \
    multidimfit_bootstrap.root --key fit_mdf --min-cov-qual 3 \
    > bootstrap_validation.log 2>&1

run_fit() {
    local start_label="$1"
    local start_value="$2"
    local fit_root="multidimfit_fit_${start_label}.root"
    local snapshot_root="higgsCombine_fit_${start_label}.MultiDimFit.mH0.root"
    CURRENT_STAGE="fit_${start_label}"
    combine -M MultiDimFit \
        -d higgsCombine_bootstrap.MultiDimFit.mH0.root \
        --snapshotName MultiDimFit -m 0 \
        -t -1 -s 123456 --toysFile "${TOY}" \
        --algo none \
        --rMin 0 --rMax "${RMAX}" \
        --setParameters "r=${start_value},${M_OFF},${INTERIOR_BOUNDARY_START}" \
        --freezeParameters "${M_FRZ}" \
        --setParameterRanges 'rgx{.*rpf_par0}=0.001,50' \
        --cminDefaultMinimizerStrategy 1 \
        --saveNLL --saveWorkspace --saveFitResult \
        -n "_fit_${start_label}" \
        > "fit_${start_label}.log" 2>&1

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

    CURRENT_STAGE="range_${start_label}"
    python3 - "${snapshot_root}" "${RMAX}" \
        > "fit_${start_label}_range_validation.log" 2>&1 <<'PY'
import math
import sys
import ROOT

path, expected_rmax = sys.argv[1], float(sys.argv[2])
root_file = ROOT.TFile.Open(path)
if not root_file or root_file.IsZombie():
    raise RuntimeError(f"cannot open final injection fit: {path}")
workspace = root_file.Get("w")
if not workspace:
    raise RuntimeError("final injection fit has no workspace w")

r = workspace.var("r")
if not r or r.isConstant():
    raise RuntimeError("r is missing or constant in final injection fit")
if not math.isclose(r.getMin(), 0.0, rel_tol=0.0, abs_tol=1e-12):
    raise RuntimeError(f"r min={r.getMin()} expected=0")
if not math.isclose(r.getMax(), expected_rmax, rel_tol=0.0, abs_tol=1e-12):
    raise RuntimeError(f"r max={r.getMax()} expected={expected_rmax}")

masks = (
    "mask_cen_Cen24Pass_Region1", "mask_cen_Cen25Pass_Region1",
    "mask_fwd_Fwd24Pass_Region1", "mask_fwd_Fwd25Pass_Region1",
)
for name in masks:
    variable = workspace.var(name)
    if not variable or not variable.isConstant() or not math.isclose(variable.getVal(), 0.0, abs_tol=1e-12):
        raise RuntimeError(f"{name} is not present, zero, and frozen")

iterator = workspace.allVars().createIterator()
rpf_variables = []
while True:
    variable = iterator.Next()
    if not variable:
        break
    if "rpf_par" in variable.GetName():
        rpf_variables.append(variable)
if len(rpf_variables) != 18:
    raise RuntimeError(f"expected 18 RPF variables, found {len(rpf_variables)}")
positive_par0 = 0
for variable in rpf_variables:
    name = variable.GetName()
    expected_min = 0.001 if name.endswith("rpf_par0") else -50.0
    positive_par0 += int(name.endswith("rpf_par0"))
    if not math.isclose(variable.getMin(), expected_min, rel_tol=0.0, abs_tol=1e-9):
        raise RuntimeError(f"{name} min={variable.getMin()} expected={expected_min}")
    if not math.isclose(variable.getMax(), 50.0, rel_tol=0.0, abs_tol=1e-9):
        raise RuntimeError(f"{name} max={variable.getMax()} expected=50")
if positive_par0 != 4:
    raise RuntimeError(f"expected four positive par0 variables, found {positive_par0}")
print("INJECTION RANGE CHECK: status=0 r_floating=1 masks_off_frozen=4 rpf_count=18 positive_par0=4")
PY
}

run_fit zero "${START_ZERO}"
run_fit injected "${START_INJECTED}"
run_fit high "${START_HIGH}"

CURRENT_STAGE="success_validation"
for required in \
    fit_zero.json fit_injected.json fit_high.json \
    bootstrap_validation.log \
    fit_zero_validation.log fit_injected_validation.log fit_high_validation.log \
    fit_zero_range_validation.log fit_injected_range_validation.log fit_high_range_validation.log; do
    [[ -s "${required}" ]] || { echo "missing or empty successful artifact: ${required}" >&2; exit 13; }
done
CURRENT_STAGE="complete"
echo "INJECTION_JOB_OK width=${WIDTH} mass=${MASS} label=${INJECTION_LABEL}"
