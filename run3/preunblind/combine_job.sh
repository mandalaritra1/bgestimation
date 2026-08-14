#!/bin/bash
set -euo pipefail

if [[ "$#" -ne 3 ]]; then
    echo "usage: $0 <1|10|30> <mass_GeV> <rMax>" >&2
    exit 2
fi

WIDTH="$1"
MASS="$2"
RMAX="$3"

REPO="/uscms/home/amandal2/nobackup/bg_ttbar/CMSSW_14_1_0_pre4/src/bgestimation"
CAMPAIGN="/uscms/home/amandal2/nobackup/bg_ttbar/preunblind_validation_20260811"
PERCAT="${CAMPAIGN}/workspaces/percat"
COMBINED="${CAMPAIGN}/workspaces/combined/w${WIDTH}"
STATE_DIR="${CAMPAIGN}/state/combined"

case "${WIDTH}" in
    1)  SIGNAL="signalZPrime${MASS}" ;;
    10) SIGNAL="signalZPrime${MASS}_10" ;;
    30) SIGNAL="signalZPrime${MASS}_30" ;;
    *) echo "unsupported width: ${WIDTH}" >&2; exit 3 ;;
esac

CEN_AREA="${PERCAT}/ttbarfits_cen2425_2x2_${SIGNAL}"
FWD_AREA="${PERCAT}/ttbarfits_fwd2425_2x1_${SIGNAL}"
CEN_CARD="${CEN_AREA}/${SIGNAL}_area/card.txt"
FWD_CARD="${FWD_AREA}/${SIGNAL}_area/card.txt"
AREA="${COMBINED}/${SIGNAL}_area"
CARD="${AREA}/${SIGNAL}_card_combined.txt"
MARKER="${STATE_DIR}/w${WIDTH}_m${MASS}.ok"

for required in "${CEN_CARD}" "${FWD_CARD}"; do
    if [[ ! -s "${required}" ]]; then
        echo "COMBINE_JOB_INVALID missing_or_empty=${required}" >&2
        exit 10
    fi
done

if [[ -e "${AREA}" ]]; then
    echo "COMBINE_JOB_REFUSE_EXISTING area=${AREA}" >&2
    exit 11
fi

mkdir -p "${AREA}" "${STATE_DIR}"
rm -f "${MARKER}"

source /cvmfs/cms.cern.ch/cmsset_default.sh
cd /uscms/home/amandal2/nobackup/bg_ttbar/CMSSW_14_1_0_pre4
eval "$(scram runtime -sh)"
cd "${REPO}"

echo "COMBINE_JOB_START width=${WIDTH} mass=${MASS} rMax=${RMAX}"
echo "repo_head=$(git rev-parse HEAD)"

combineCards.py cen="${CEN_CARD}" fwd="${FWD_CARD}" > "${CARD}"
text2workspace.py "${CARD}" -o "${AREA}/workspace.root" --channel-masks --X-no-jmax

M_ON="mask_cen_Cen24Pass_Region1=1,mask_cen_Cen25Pass_Region1=1,mask_fwd_Fwd24Pass_Region1=1,mask_fwd_Fwd25Pass_Region1=1"
M_OFF="mask_cen_Cen24Pass_Region1=0,mask_cen_Cen25Pass_Region1=0,mask_fwd_Fwd24Pass_Region1=0,mask_fwd_Fwd25Pass_Region1=0"
M_FRZ="mask_cen_Cen24Pass_Region1,mask_cen_Cen25Pass_Region1,mask_fwd_Fwd24Pass_Region1,mask_fwd_Fwd25Pass_Region1"

(
    cd "${AREA}"
    combine -M MultiDimFit -d workspace.root -m 0 \
        --rMin 0 --rMax "${RMAX}" \
        --setParameters "r=0,${M_ON}" \
        --freezeParameters "r,${M_FRZ}" \
        --cminDefaultMinimizerStrategy 1 --cminPreScan --cminPreFit 1 \
        --saveWorkspace --saveFitResult -n _maskedBonly \
        > masked_bonly.log 2>&1
    python3 "${REPO}/run3/validate_fit_result.py" \
        multidimfit_maskedBonly.root --key fit_mdf --min-cov-qual 3 \
        > masked_bonly_validation.log 2>&1

    combine -M AsymptoticLimits \
        -d higgsCombine_maskedBonly.MultiDimFit.mH0.root \
        --snapshotName MultiDimFit --run blind --bypassFrequentistFit -m 0 \
        --setParameters "${M_OFF}" --freezeParameters "${M_FRZ}" \
        --rMin 0 --rMax "${RMAX}" \
        --cminDefaultMinimizerStrategy 0 \
        --rRelAcc 0.0005 --rAbsAcc 1e-9 -v 0 -n _expected \
        > expected_limit.log 2>&1
    python3 "${REPO}/run3/validate_expected_limit.py" \
        higgsCombine_expected.AsymptoticLimits.mH0.root --rmax "${RMAX}" \
        > expected_limit_validation.log 2>&1
)

for required in \
    "${AREA}/workspace.root" \
    "${AREA}/higgsCombine_maskedBonly.MultiDimFit.mH0.root" \
    "${AREA}/multidimfit_maskedBonly.root" \
    "${AREA}/higgsCombine_expected.AsymptoticLimits.mH0.root"; do
    if [[ ! -s "${required}" ]]; then
        echo "COMBINE_JOB_INVALID missing_or_empty=${required}" >&2
        exit 12
    fi
done

{
    echo "width=${WIDTH}"
    echo "mass_GeV=${MASS}"
    echo "signal=${SIGNAL}"
    echo "rMax=${RMAX}"
    echo "area=${AREA}"
    echo "workspace_sha256=$(sha256sum "${AREA}/workspace.root" | awk '{print $1}')"
    echo "snapshot_sha256=$(sha256sum "${AREA}/higgsCombine_maskedBonly.MultiDimFit.mH0.root" | awk '{print $1}')"
    echo "fit_sha256=$(sha256sum "${AREA}/multidimfit_maskedBonly.root" | awk '{print $1}')"
    echo "limit_sha256=$(sha256sum "${AREA}/higgsCombine_expected.AsymptoticLimits.mH0.root" | awk '{print $1}')"
    cat "${AREA}/masked_bonly_validation.log"
    cat "${AREA}/expected_limit_validation.log"
} > "${MARKER}"

echo "COMBINE_JOB_OK marker=${MARKER}"
