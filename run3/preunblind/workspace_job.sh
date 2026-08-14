#!/bin/bash
set -euo pipefail

if [[ "$#" -ne 3 ]]; then
    echo "usage: $0 <cen2425|fwd2425> <1|10|30> <mass_GeV>" >&2
    exit 2
fi

CATEGORY="$1"
WIDTH="$2"
MASS="$3"

REPO="/uscms/home/amandal2/nobackup/bg_ttbar/CMSSW_14_1_0_pre4/src/bgestimation"
CAMPAIGN="/uscms/home/amandal2/nobackup/bg_ttbar/preunblind_validation_20260811"
INPUT_DIR="${CAMPAIGN}/inputs"
OUTPUT_DIR="${CAMPAIGN}/workspaces/percat"
STATE_DIR="${CAMPAIGN}/state/workspaces"

case "${CATEGORY}" in
    cen2425) TF_ORDER="2x2" ;;
    fwd2425) TF_ORDER="2x1" ;;
    *) echo "unsupported category: ${CATEGORY}" >&2; exit 3 ;;
esac

case "${WIDTH}" in
    1)  SCENARIO="ZPrime_1";  SIGNAL="signalZPrime${MASS}" ;;
    10) SCENARIO="ZPrime_10"; SIGNAL="signalZPrime${MASS}_10" ;;
    30) SCENARIO="ZPrime_30"; SIGNAL="signalZPrime${MASS}_30" ;;
    *) echo "unsupported width: ${WIDTH}" >&2; exit 4 ;;
esac

AREA="${OUTPUT_DIR}/ttbarfits_${CATEGORY}_${TF_ORDER}_${SIGNAL}"
CARD="${AREA}/${SIGNAL}_area/card.txt"
BASE="${AREA}/base.root"
MARKER="${STATE_DIR}/${CATEGORY}_w${WIDTH}_m${MASS}.ok"

mkdir -p "${OUTPUT_DIR}" "${STATE_DIR}"
rm -f "${MARKER}"

source /cvmfs/cms.cern.ch/cmsset_default.sh
cd /uscms/home/amandal2/nobackup/bg_ttbar/CMSSW_14_1_0_pre4
eval "$(scram runtime -sh)"
export PYTHONPATH="/uscms/home/amandal2/nobackup/bg_ttbar/CMSSW_14_1_0_pre4/src/2DAlphabet:${PYTHONPATH:-}"
cd "${REPO}"

echo "WORKSPACE_JOB_START category=${CATEGORY} width=${WIDTH} mass=${MASS}"
echo "repo_head=$(git rev-parse HEAD)"
echo "ttbar_sha256=$(sha256sum ttbar.py | awk '{print $1}')"

python3 -u ttbar.py \
    --cat "${CATEGORY}" \
    --scenario "${SCENARIO}" \
    --input "${INPUT_DIR}" \
    --output "${OUTPUT_DIR}" \
    --signal "${SIGNAL#signal}" \
    --study workspace

for required in "${BASE}" "${CARD}" "${AREA}/runConfig.json"; do
    if [[ ! -s "${required}" ]]; then
        echo "WORKSPACE_JOB_INVALID missing_or_empty=${required}" >&2
        exit 10
    fi
done

if find "${AREA}" -type f \( -name 'fitDiagnostics*.root' -o -name 'multidimfit*.root' -o -name '*AsymptoticLimits*.root' \) | grep -q .; then
    echo "WORKSPACE_JOB_INVALID unexpected_fit_output=${AREA}" >&2
    exit 11
fi

if ! grep -q "${SIGNAL}" "${CARD}"; then
    echo "WORKSPACE_JOB_INVALID signal_missing_from_card=${CARD}" >&2
    exit 12
fi

{
    echo "category=${CATEGORY}"
    echo "width=${WIDTH}"
    echo "mass_GeV=${MASS}"
    echo "signal=${SIGNAL}"
    echo "base_root=${BASE}"
    echo "base_sha256=$(sha256sum "${BASE}" | awk '{print $1}')"
    echo "card=${CARD}"
    echo "card_sha256=$(sha256sum "${CARD}" | awk '{print $1}')"
} > "${MARKER}"

echo "WORKSPACE_JOB_OK marker=${MARKER}"
