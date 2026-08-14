#!/bin/bash
# Build one deliberately small, immutable per-point input bundle.  This script
# runs on the LPC submit host, never on a worker.
set -euo pipefail

if [[ "$#" -ne 3 ]]; then
    echo "usage: $0 <cen2425|fwd2425> <1|10|30> <mass_GeV>" >&2
    exit 1
fi
CATEGORY="$1"
WIDTH="$2"
MASS="$3"

REPO="${REPO:-/uscms/home/amandal2/nobackup/bg_ttbar/CMSSW_14_1_0_pre4/src/bgestimation}"
TWOD="${TWOD:-/uscms/home/amandal2/nobackup/bg_ttbar/CMSSW_14_1_0_pre4/src/2DAlphabet}"
CAMPAIGN="${CAMPAIGN:-/uscms/home/amandal2/nobackup/bg_ttbar/preunblind_validation_20260811}"
INPUT_DIR="${INPUT_DIR:-${CAMPAIGN}/inputs}"
PAYLOAD="${PAYLOAD:-${CAMPAIGN}/payloads/workspace_payload_${CATEGORY}_w${WIDTH}_m${MASS}.tgz}"

case "${CATEGORY}" in cen2425|fwd2425) ;; *) echo "unsupported category: ${CATEGORY}" >&2; exit 2 ;; esac
case "${WIDTH}" in
    1) SIGNAL="signalZPrime${MASS}" ;;
    10|30) SIGNAL="signalZPrime${MASS}_${WIDTH}" ;;
    *) echo "unsupported width: ${WIDTH}" >&2; exit 3 ;;
esac

for required in \
    "${REPO}/ttbar.py" \
    "${REPO}/header.py" \
    "${REPO}/jsons/TransferFunctions.json" \
    "${REPO}/jsons/signal_xs.json" \
    "${REPO}/jsons/config/ttbar_cen2425.json" \
    "${REPO}/jsons/config/ttbar_fwd2425.json" \
    "${TWOD}/TwoDAlphabet" \
    "${INPUT_DIR}"; do
    [[ -e "${required}" ]] || { echo "missing required source: ${required}" >&2; exit 4; }
done

input_files=(
    "TTbarAllHadComb_Data.root"
    "TTbarAllHad24_TTbar.root"
    "TTbarAllHad25_TTbar.root"
    "TTbarAllHad24_${SIGNAL}.root"
    "TTbarAllHad25_${SIGNAL}.root"
)
for filename in "${input_files[@]}"; do
    [[ -s "${INPUT_DIR}/${filename}" ]] || {
        echo "missing required point input: ${INPUT_DIR}/${filename}" >&2
        exit 5
    }
done
input_count="${#input_files[@]}"

[[ ! -e "${PAYLOAD}" ]] || {
    echo "refusing to overwrite existing payload: ${PAYLOAD}" >&2
    exit 6
}

mkdir -p "$(dirname "${PAYLOAD}")" "${CAMPAIGN}/workspaces/portable_results"
stage=$(mktemp -d "${CAMPAIGN}/state/workspace-payload.XXXXXX")
payload_tmp="${PAYLOAD}.tmp.$$"
cleanup() {
    rm -rf "${stage}"
    rm -f "${payload_tmp}"
}
trap cleanup EXIT

mkdir -p \
    "${stage}/bgestimation/jsons/config" \
    "${stage}/2DAlphabet" \
    "${stage}/inputs"

cp -a "${REPO}/ttbar.py" "${REPO}/header.py" "${stage}/bgestimation/"
cp -a "${REPO}/jsons/TransferFunctions.json" "${REPO}/jsons/signal_xs.json" \
    "${stage}/bgestimation/jsons/"
cp -a "${REPO}/jsons/config/ttbar_cen2425.json" \
    "${REPO}/jsons/config/ttbar_fwd2425.json" \
    "${stage}/bgestimation/jsons/config/"
cp -a "${TWOD}/TwoDAlphabet" "${stage}/2DAlphabet/"
for filename in "${input_files[@]}"; do
    cp -a "${INPUT_DIR}/${filename}" "${stage}/inputs/"
done

{
    echo "created_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "bgestimation_git=$(git -C "${REPO}" rev-parse HEAD)"
    echo "twodalphabet_git=$(git -C "${TWOD}" rev-parse HEAD)"
    echo "category=${CATEGORY}"
    echo "width=${WIDTH}"
    echo "mass_GeV=${MASS}"
    echo "signal=${SIGNAL}"
    echo "input_root_files=${input_count}"
    printf 'input_file=%s\n' "${input_files[@]}"
    echo "source_repo=${REPO}"
    echo "source_twodalphabet=${TWOD}"
    echo "source_inputs=${INPUT_DIR}"
} > "${stage}/payload_provenance.txt"

(
    cd "${stage}"
    find bgestimation 2DAlphabet inputs -type f -print0 | sort -z | xargs -0 sha256sum > payload.sha256
    sha256sum -c payload.sha256
    tar -czf "${payload_tmp}" .
)

mv "${payload_tmp}" "${PAYLOAD}"
echo "WORKSPACE_PAYLOAD_OK path=${PAYLOAD}"
echo "WORKSPACE_PAYLOAD_SHA256=$(sha256sum "${PAYLOAD}" | awk '{print $1}')"
echo "WORKSPACE_PAYLOAD_SIZE_BYTES=$(stat -c %s "${PAYLOAD}")"
