#!/bin/bash
# Build one immutable point payload reused by its four Asimov injections.
set -euo pipefail

if [[ "$#" -ne 3 ]]; then
    echo "usage: $0 <1|10|30> <mass_GeV> <rMax>" >&2
    exit 1
fi
WIDTH="$1"
MASS="$2"
RMAX="$3"
REPO="${REPO:-/uscms/home/amandal2/nobackup/bg_ttbar/CMSSW_14_1_0_pre4/src/bgestimation}"
CAMPAIGN="${CAMPAIGN:-/uscms/home/amandal2/nobackup/bg_ttbar/preunblind_validation_20260811}"
PAYLOAD="${PAYLOAD:-${CAMPAIGN}/payloads/injection_payload_w${WIDTH}_m${MASS}.tgz}"

case "${WIDTH}" in
    1) SIGNAL="signalZPrime${MASS}" ;;
    10) SIGNAL="signalZPrime${MASS}_10" ;;
    30) SIGNAL="signalZPrime${MASS}_30" ;;
    *) echo "unsupported width: ${WIDTH}" >&2; exit 2 ;;
esac
COMBINED_AREA="${CAMPAIGN}/workspaces/combined/w${WIDTH}/${SIGNAL}_area"
SNAPSHOT="${COMBINED_AREA}/higgsCombine_maskedBonly.MultiDimFit.mH0.root"
for required in \
    "${SNAPSHOT}" \
    "${REPO}/run3/validate_fit_result.py" \
    "${REPO}/run3/preunblind/harvest_fit_result.py"; do
    [[ -s "${required}" ]] || { echo "missing required payload source: ${required}" >&2; exit 3; }
done
[[ "$(head -c 4 "${SNAPSHOT}")" == "root" ]] || {
    echo "snapshot lacks ROOT magic bytes: ${SNAPSHOT}" >&2
    exit 4
}
[[ ! -e "${PAYLOAD}" ]] || { echo "refusing to overwrite payload: ${PAYLOAD}" >&2; exit 5; }

mkdir -p "$(dirname "${PAYLOAD}")"
stage=$(mktemp -d "${CAMPAIGN}/state/injection-payload.XXXXXX")
payload_tmp="${PAYLOAD}.tmp.$$"
cleanup() { rm -rf "${stage}"; rm -f "${payload_tmp}"; }
trap cleanup EXIT
mkdir -p "${stage}/bgestimation/run3/preunblind" "${stage}/combined_area"
cp -a "${REPO}/run3/validate_fit_result.py" "${stage}/bgestimation/run3/"
cp -a "${REPO}/run3/preunblind/harvest_fit_result.py" "${stage}/bgestimation/run3/preunblind/"
cp -a "${SNAPSHOT}" "${stage}/combined_area/"
{
    echo "created_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "bgestimation_git=$(git -C "${REPO}" rev-parse HEAD)"
    echo "width=${WIDTH}"
    echo "mass_GeV=${MASS}"
    echo "signal=${SIGNAL}"
    echo "rMax=${RMAX}"
    echo "source_combined_area=${COMBINED_AREA}"
    echo "snapshot_sha256=$(sha256sum "${SNAPSHOT}" | awk '{print $1}')"
} > "${stage}/payload_provenance.txt"
(
    cd "${stage}"
    find bgestimation combined_area -type f -print0 | sort -z | xargs -0 sha256sum > payload.sha256
    sha256sum -c payload.sha256
    tar -czf "${payload_tmp}" .
)
mv "${payload_tmp}" "${PAYLOAD}"
echo "INJECTION_PAYLOAD_OK path=${PAYLOAD}"
echo "INJECTION_PAYLOAD_SHA256=$(sha256sum "${PAYLOAD}" | awk '{print $1}')"
echo "INJECTION_PAYLOAD_SIZE_BYTES=$(stat -c %s "${PAYLOAD}")"
