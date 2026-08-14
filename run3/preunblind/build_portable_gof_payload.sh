#!/bin/bash
# Build the immutable w1/M2000 masked-GoF canary payload from the already
# harvested final physical-range snapshot.  No card or base templates enter it.
set -euo pipefail

if [[ "$#" -ne 0 ]]; then
    echo "usage: $0" >&2
    exit 1
fi
WIDTH=1
MASS=2000
RMAX=1
SIGNAL="signalZPrime2000"
REPO="${REPO:-/uscms/home/amandal2/nobackup/bg_ttbar/CMSSW_14_1_0_pre4/src/bgestimation}"
CAMPAIGN="${CAMPAIGN:-/uscms/home/amandal2/nobackup/bg_ttbar/preunblind_validation_20260811}"
COMBINED_AREA="${CAMPAIGN}/workspaces/combined/w${WIDTH}/${SIGNAL}_area"
SNAPSHOT="${COMBINED_AREA}/higgsCombine_maskedBonly.MultiDimFit.mH0.root"
VALIDATOR="${REPO}/run3/preunblind/validate_portable_gof.py"
PAYLOAD="${PAYLOAD:-${CAMPAIGN}/payloads/gof_payload_w${WIDTH}_m${MASS}.tgz}"

for required in "${SNAPSHOT}" "${VALIDATOR}"; do
    [[ -s "${required}" ]] || { echo "missing required GoF payload source: ${required}" >&2; exit 2; }
done
[[ "$(head -c 4 "${SNAPSHOT}")" == "root" ]] || {
    echo "snapshot lacks ROOT magic bytes: ${SNAPSHOT}" >&2
    exit 3
}
[[ ! -e "${PAYLOAD}" ]] || { echo "refusing to overwrite payload: ${PAYLOAD}" >&2; exit 4; }

mkdir -p "$(dirname "${PAYLOAD}")" "${CAMPAIGN}/state"
stage=$(mktemp -d "${CAMPAIGN}/state/gof-payload.XXXXXX")
payload_tmp="${PAYLOAD}.tmp.$$"
cleanup() { rm -rf "${stage}"; rm -f "${payload_tmp}"; }
trap cleanup EXIT

mkdir -p "${stage}/bgestimation/run3/preunblind" "${stage}/combined_area"
cp -a "${VALIDATOR}" "${stage}/bgestimation/run3/preunblind/"
cp -a "${SNAPSHOT}" "${stage}/combined_area/"
python3 "${VALIDATOR}" snapshot "${SNAPSHOT}" --rmax "${RMAX}" \
    --output "${stage}/source_snapshot_validation.json"
{
    echo "created_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "bgestimation_git=$(git -C "${REPO}" rev-parse HEAD)"
    echo "width=${WIDTH}"
    echo "mass_GeV=${MASS}"
    echo "signal=${SIGNAL}"
    echo "rMax=${RMAX}"
    echo "source_combined_area=${COMBINED_AREA}"
    echo "snapshot_sha256=$(sha256sum "${SNAPSHOT}" | awk '{print $1}')"
    echo "data_scope=observed_sideband_only"
    echo "pass_region_masks=all_on_frozen"
    echo "r_state=fixed_zero"
    echo "algorithm=saturated"
} > "${stage}/payload_provenance.txt"
(
    cd "${stage}"
    find bgestimation combined_area source_snapshot_validation.json payload_provenance.txt \
        -type f -print0 | sort -z | xargs -0 sha256sum > payload.sha256
    sha256sum -c payload.sha256
    tar -czf "${payload_tmp}" .
)
mv "${payload_tmp}" "${PAYLOAD}"
echo "GOF_PAYLOAD_OK path=${PAYLOAD}"
echo "GOF_PAYLOAD_SHA256=$(sha256sum "${PAYLOAD}" | awk '{print $1}')"
echo "GOF_PAYLOAD_SIZE_BYTES=$(stat -c %s "${PAYLOAD}")"
