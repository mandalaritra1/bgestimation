#!/bin/bash
# Build the immutable local payload for the single reviewed Asimov likelihood
# scan canary.  It carries only the final validated snapshot and local
# validator/harvester code: no card, workspace template, or observed data path.
set -euo pipefail

if [[ "$#" -ne 0 ]]; then
    echo "usage: $0" >&2
    exit 1
fi

WIDTH=1
MASS=2000
PRODUCTION_RMAX=1
RINJECT="0.0169433597475"
SCAN_RMAX="0.0847167987375"  # 5 * RINJECT; diagnostic only, not production rMax.
GRID_POINTS=41
REPO="${REPO:-/uscms/home/amandal2/nobackup/bg_ttbar/CMSSW_14_1_0_pre4/src/bgestimation}"
CAMPAIGN="${CAMPAIGN:-/uscms/home/amandal2/nobackup/bg_ttbar/preunblind_validation_20260811}"
COMBINED_AREA="${CAMPAIGN}/workspaces/combined/w${WIDTH}/signalZPrime${MASS}_area"
SNAPSHOT="${COMBINED_AREA}/higgsCombine_maskedBonly.MultiDimFit.mH0.root"
VALIDATOR="${REPO}/run3/preunblind/validate_portable_asimov_scan.py"
HARVESTER="${REPO}/run3/preunblind/harvest_portable_asimov_scan.py"
PAYLOAD="${PAYLOAD:-${CAMPAIGN}/payloads/asimov_scan_payload_w${WIDTH}_m${MASS}.tgz}"

for required in "${SNAPSHOT}" "${VALIDATOR}" "${HARVESTER}"; do
    [[ -s "${required}" ]] || { echo "missing required Asimov-scan source: ${required}" >&2; exit 2; }
done
[[ "$(head -c 4 "${SNAPSHOT}")" == "root" ]] || {
    echo "snapshot lacks ROOT magic bytes: ${SNAPSHOT}" >&2
    exit 3
}
[[ ! -e "${PAYLOAD}" ]] || { echo "refusing to overwrite payload: ${PAYLOAD}" >&2; exit 4; }

mkdir -p "$(dirname "${PAYLOAD}")" "${CAMPAIGN}/state"
stage=$(mktemp -d "${CAMPAIGN}/state/asimov-scan-payload.XXXXXX")
payload_tmp="${PAYLOAD}.tmp.$$"
cleanup() { rm -rf "${stage}"; rm -f "${payload_tmp}"; }
trap cleanup EXIT

mkdir -p "${stage}/bgestimation/run3/preunblind" "${stage}/combined_area"
cp -a "${VALIDATOR}" "${HARVESTER}" "${stage}/bgestimation/run3/preunblind/"
cp -a "${SNAPSHOT}" "${stage}/combined_area/"
python3 "${VALIDATOR}" snapshot "${SNAPSHOT}" --production-rmax "${PRODUCTION_RMAX}" \
    --output "${stage}/source_snapshot_validation.json"
{
    echo "created_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "bgestimation_git=$(git -C "${REPO}" rev-parse HEAD)"
    echo "width=${WIDTH}"
    echo "mass_GeV=${MASS}"
    echo "signal=signalZPrime${MASS}"
    echo "production_rMax=${PRODUCTION_RMAX}"
    echo "diagnostic_scan_rMax=${SCAN_RMAX}"
    echo "rInject=${RINJECT}"
    echo "grid_points=${GRID_POINTS}"
    echo "source_combined_area=${COMBINED_AREA}"
    echo "snapshot_sha256=$(sha256sum "${SNAPSHOT}" | awk '{print $1}')"
    echo "dataset_scope=synthetic_asimov_only"
    echo "pass_region_masks=all_off_frozen"
} > "${stage}/payload_provenance.txt"
(
    cd "${stage}"
    find bgestimation combined_area source_snapshot_validation.json payload_provenance.txt \
        -type f -print0 | sort -z | xargs -0 sha256sum > payload.sha256
    sha256sum -c payload.sha256
    tar -czf "${payload_tmp}" .
)
mv "${payload_tmp}" "${PAYLOAD}"
echo "ASIMOV_SCAN_PAYLOAD_OK path=${PAYLOAD}"
echo "ASIMOV_SCAN_PAYLOAD_SHA256=$(sha256sum "${PAYLOAD}" | awk '{print $1}')"
echo "ASIMOV_SCAN_PAYLOAD_SIZE_BYTES=$(stat -c %s "${PAYLOAD}")"
