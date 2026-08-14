#!/bin/bash
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

REPO="/uscms/home/amandal2/nobackup/bg_ttbar/CMSSW_14_1_0_pre4/src/bgestimation"
CAMPAIGN="/uscms/home/amandal2/nobackup/bg_ttbar/preunblind_validation_20260811"
STATE_DIR="${CAMPAIGN}/state/injections"

case "${WIDTH}" in
    1)  SIGNAL="signalZPrime${MASS}" ;;
    10) SIGNAL="signalZPrime${MASS}_10" ;;
    30) SIGNAL="signalZPrime${MASS}_30" ;;
    *) echo "unsupported width: ${WIDTH}" >&2; exit 3 ;;
esac

COMBINED_AREA="${CAMPAIGN}/workspaces/combined/w${WIDTH}/${SIGNAL}_area"
SNAPSHOT="${COMBINED_AREA}/higgsCombine_maskedBonly.MultiDimFit.mH0.root"
AREA="${CAMPAIGN}/injections/asimov/w${WIDTH}/m${MASS}/${INJECTION_LABEL}"
MARKER="${STATE_DIR}/w${WIDTH}_m${MASS}_${INJECTION_LABEL}.ok"

if [[ ! -s "${SNAPSHOT}" ]]; then
    echo "INJECTION_JOB_INVALID missing_snapshot=${SNAPSHOT}" >&2
    exit 10
fi
if [[ -e "${AREA}" ]]; then
    echo "INJECTION_JOB_REFUSE_EXISTING area=${AREA}" >&2
    exit 11
fi

mkdir -p "${AREA}" "${STATE_DIR}"
rm -f "${MARKER}"

source /cvmfs/cms.cern.ch/cmsset_default.sh
cd /uscms/home/amandal2/nobackup/bg_ttbar/CMSSW_14_1_0_pre4
eval "$(scram runtime -sh)"
cd "${AREA}"

M_OFF="mask_cen_Cen24Pass_Region1=0,mask_cen_Cen25Pass_Region1=0,mask_fwd_Fwd24Pass_Region1=0,mask_fwd_Fwd25Pass_Region1=0"
M_FRZ="mask_cen_Cen24Pass_Region1,mask_cen_Cen25Pass_Region1,mask_fwd_Fwd24Pass_Region1,mask_fwd_Fwd25Pass_Region1"
TOY="higgsCombine_gen.GenerateOnly.mH0.123456.root"

echo "INJECTION_JOB_START width=${WIDTH} mass=${MASS} rMax=${RMAX} label=${INJECTION_LABEL} rInject=${RINJECT}"

combine -M GenerateOnly -d "${SNAPSHOT}" --snapshotName MultiDimFit -m 0 \
    -t -1 -s 123456 --saveToys --toysFrequentist --bypassFrequentistFit \
    --expectSignal "${RINJECT}" \
    --setParameters "r=${RINJECT},${M_OFF}" \
    --freezeParameters "${M_FRZ}" \
    -n _gen > generate.log 2>&1

if [[ ! -s "${TOY}" ]]; then
    echo "INJECTION_JOB_INVALID missing_generated_asimov=${AREA}/${TOY}" >&2
    exit 12
fi

run_fit() {
    local start_label="$1"
    local start_value="$2"
    local fit_root="fitDiagnostics_fit_${start_label}.root"

    combine -M FitDiagnostics -d "${SNAPSHOT}" --snapshotName MultiDimFit -m 0 \
        -t 1 -s 123456 --toysFile "${TOY}" \
        --rMin 0 --rMax "${RMAX}" \
        --setParameters "r=${start_value},${M_OFF}" \
        --freezeParameters "${M_FRZ}" \
        --robustFit 1 --cminDefaultMinimizerStrategy 1 \
        --cminPreScan --cminPreFit 1 --saveNLL --saveWorkspace \
        -n "_fit_${start_label}" \
        > "fit_${start_label}.log" 2>&1

    python3 "${REPO}/run3/validate_fit_result.py" \
        "${fit_root}" --key fit_s --min-cov-qual 3 \
        > "fit_${start_label}_validation.log" 2>&1
    python3 "${REPO}/run3/preunblind/harvest_fit_result.py" \
        "${fit_root}" --key fit_s \
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

for required in \
    fit_zero.json fit_injected.json fit_halfmax.json \
    fit_zero_validation.log fit_injected_validation.log fit_halfmax_validation.log; do
    if [[ ! -s "${required}" ]]; then
        echo "INJECTION_JOB_INVALID missing_or_empty=${AREA}/${required}" >&2
        exit 13
    fi
done

{
    echo "width=${WIDTH}"
    echo "mass_GeV=${MASS}"
    echo "rMax=${RMAX}"
    echo "injection_label=${INJECTION_LABEL}"
    echo "injected_r=${RINJECT}"
    echo "area=${AREA}"
    echo "toy_sha256=$(sha256sum "${TOY}" | awk '{print $1}')"
    for start_label in zero injected halfmax; do
        echo "fit_${start_label}_sha256=$(sha256sum "fitDiagnostics_fit_${start_label}.root" | awk '{print $1}')"
        cat "fit_${start_label}_validation.log"
    done
} > "${MARKER}"

echo "INJECTION_JOB_OK marker=${MARKER}"
