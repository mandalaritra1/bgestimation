#!/bin/bash
# Build one immutable, combined-fit payload from already-harvested per-category
# workspaces.  It does not create, fit, or alter a workspace.
set -euo pipefail

if [[ "$#" -lt 3 || "$#" -gt 4 ]]; then
    echo "usage: $0 <1|10|30> <mass_GeV> <rMax> [fwd_tf]" >&2
    exit 1
fi
WIDTH="$1"
MASS="$2"
RMAX="$3"
# v2: F-test-selected fwd TF order (2026-08-14 verdict: 2x0); default keeps
# the original 2x1 behaviour.
FWD_TF="${4:-2x1}"
case "${FWD_TF}" in
    0x0|0x1|0x2|1x0|1x1|1x2|2x0|2x1|2x2|3x0|3x1) ;;
    *) echo "unsupported fwd TF order: ${FWD_TF}" >&2; exit 2 ;;
esac
REPO="${REPO:-/uscms/home/amandal2/nobackup/bg_ttbar/CMSSW_14_1_0_pre4/src/bgestimation}"
CAMPAIGN="${CAMPAIGN:-/uscms/home/amandal2/nobackup/bg_ttbar/preunblind_validation_20260811}"
PERCAT="${PERCAT:-${CAMPAIGN}/workspaces/percat}"
PAYLOAD="${PAYLOAD:-${CAMPAIGN}/payloads/combine_payload_w${WIDTH}_m${MASS}.tgz}"

case "${WIDTH}" in
    1) SIGNAL="signalZPrime${MASS}" ;;
    10) SIGNAL="signalZPrime${MASS}_10" ;;
    30) SIGNAL="signalZPrime${MASS}_30" ;;
    *) echo "unsupported width: ${WIDTH}" >&2; exit 2 ;;
esac
CEN_AREA="ttbarfits_cen2425_2x2_${SIGNAL}"
FWD_AREA="ttbarfits_fwd2425_${FWD_TF}_${SIGNAL}"

for required in \
    "${PERCAT}/${CEN_AREA}/base.root" \
    "${PERCAT}/${CEN_AREA}/runConfig.json" \
    "${PERCAT}/${CEN_AREA}/${SIGNAL}_area/card.txt" \
    "${PERCAT}/${FWD_AREA}/base.root" \
    "${PERCAT}/${FWD_AREA}/runConfig.json" \
    "${PERCAT}/${FWD_AREA}/${SIGNAL}_area/card.txt" \
    "${REPO}/run3/validate_fit_result.py" \
    "${REPO}/run3/validate_expected_limit.py"; do
    [[ -s "${required}" ]] || { echo "missing required payload source: ${required}" >&2; exit 3; }
done
for area in "${PERCAT}/${CEN_AREA}" "${PERCAT}/${FWD_AREA}"; do
    if find "${area}" -type f \( -name 'fitDiagnostics*.root' -o -name 'multidimfit*.root' -o -name '*AsymptoticLimits*.root' \) | grep -q .; then
        echo "refusing per-category fit/limit output in workspace payload: ${area}" >&2
        exit 4
    fi
done
[[ ! -e "${PAYLOAD}" ]] || { echo "refusing to overwrite payload: ${PAYLOAD}" >&2; exit 5; }

mkdir -p "$(dirname "${PAYLOAD}")"
stage=$(mktemp -d "${CAMPAIGN}/state/combine-payload.XXXXXX")
payload_tmp="${PAYLOAD}.tmp.$$"
cleanup() { rm -rf "${stage}"; rm -f "${payload_tmp}"; }
trap cleanup EXIT

mkdir -p "${stage}/bgestimation/run3" "${stage}/workspaces/percat"
cp -a "${REPO}/run3/validate_fit_result.py" "${REPO}/run3/validate_expected_limit.py" \
    "${stage}/bgestimation/run3/"
cp -a "${PERCAT}/${CEN_AREA}" "${PERCAT}/${FWD_AREA}" "${stage}/workspaces/percat/"
{
    echo "created_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "bgestimation_git=$(git -C "${REPO}" rev-parse HEAD)"
    echo "width=${WIDTH}"
    echo "mass_GeV=${MASS}"
    echo "signal=${SIGNAL}"
    echo "rMax=${RMAX}"
    echo "fwd_tf=${FWD_TF}"
    echo "cen_area=${CEN_AREA}"
    echo "fwd_area=${FWD_AREA}"
} > "${stage}/payload_provenance.txt"
(
    cd "${stage}"
    find bgestimation workspaces -type f -print0 | sort -z | xargs -0 sha256sum > payload.sha256
    sha256sum -c payload.sha256
    tar -czf "${payload_tmp}" .
)
mv "${payload_tmp}" "${PAYLOAD}"
echo "COMBINE_PAYLOAD_OK path=${PAYLOAD}"
echo "COMBINE_PAYLOAD_SHA256=$(sha256sum "${PAYLOAD}" | awk '{print $1}')"
echo "COMBINE_PAYLOAD_SIZE_BYTES=$(stat -c %s "${PAYLOAD}")"
