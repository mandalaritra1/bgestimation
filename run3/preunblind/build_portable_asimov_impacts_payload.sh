#!/bin/bash
# Build one immutable point payload for the synthetic-Asimov Impacts matrix.
# It contains only the reviewed final snapshot and portable validation code.
set -euo pipefail

if [[ "$#" -ne 4 ]]; then
    echo "usage: $0 <width> <mass_GeV> <rMax> <rInject>" >&2
    exit 1
fi

WIDTH="$1"
MASS="$2"
RMAX="$3"
RINJECT="$4"
case "${WIDTH}" in
    1) SIGNAL="signalZPrime${MASS}" ;;
    10) SIGNAL="signalZPrime${MASS}_10" ;;
    30) SIGNAL="signalZPrime${MASS}_30" ;;
    *) echo "unsupported width: ${WIDTH}" >&2; exit 1 ;;
esac
REPO="${REPO:-/uscms/home/amandal2/nobackup/bg_ttbar/CMSSW_14_1_0_pre4/src/bgestimation}"
CAMPAIGN="${CAMPAIGN:-/uscms/home/amandal2/nobackup/bg_ttbar/preunblind_validation_20260811}"
COMBINED_AREA="${CAMPAIGN}/workspaces/combined/w${WIDTH}/${SIGNAL}_area"
SNAPSHOT="${COMBINED_AREA}/higgsCombine_maskedBonly.MultiDimFit.mH0.root"
VALIDATOR="${REPO}/run3/preunblind/validate_portable_asimov_impacts.py"
HARVESTER="${REPO}/run3/preunblind/harvest_portable_asimov_impacts.py"
FIT_VALIDATOR="${REPO}/run3/validate_fit_result.py"
PAYLOAD="${PAYLOAD:-${CAMPAIGN}/payloads/asimov_impacts_payload_w${WIDTH}_m${MASS}_v2.tgz}"

for required in "${SNAPSHOT}" "${VALIDATOR}" "${HARVESTER}" "${FIT_VALIDATOR}"; do
    [[ -s "${required}" ]] || { echo "missing required Asimov-Impacts source: ${required}" >&2; exit 2; }
done
[[ "$(head -c 4 "${SNAPSHOT}")" == "root" ]] || {
    echo "snapshot lacks ROOT magic bytes: ${SNAPSHOT}" >&2
    exit 3
}
[[ ! -e "${PAYLOAD}" ]] || { echo "refusing to overwrite payload: ${PAYLOAD}" >&2; exit 4; }

mkdir -p "$(dirname "${PAYLOAD}")" "${CAMPAIGN}/state"
stage=$(mktemp -d "${CAMPAIGN}/state/asimov-impacts-payload.XXXXXX")
payload_tmp="${PAYLOAD}.tmp.$$"
cleanup() { rm -rf "${stage}"; rm -f "${payload_tmp}"; }
trap cleanup EXIT

mkdir -p "${stage}/bgestimation/run3/preunblind" "${stage}/bgestimation/run3" "${stage}/combined_area"
cp -a "${VALIDATOR}" "${HARVESTER}" "${stage}/bgestimation/run3/preunblind/"
cp -a "${FIT_VALIDATOR}" "${stage}/bgestimation/run3/"
cp -a "${SNAPSHOT}" "${stage}/combined_area/"
python3 "${VALIDATOR}" snapshot "${SNAPSHOT}" --rmax "${RMAX}" \
    --output "${stage}/source_snapshot_validation.json"
{
    echo "created_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "bgestimation_git=$(git -C "${REPO}" rev-parse HEAD)"
    echo "width=${WIDTH}"
    echo "mass_GeV=${MASS}"
    echo "signal=${SIGNAL}"
    echo "production_rMax=${RMAX}"
    echo "rInject=${RINJECT}"
    echo "model_nuisances=lumi24,lumi25,ttbar_xsec"
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
echo "ASIMOV_IMPACTS_PAYLOAD_OK path=${PAYLOAD}"
echo "ASIMOV_IMPACTS_PAYLOAD_SHA256=$(sha256sum "${PAYLOAD}" | awk '{print $1}')"
echo "ASIMOV_IMPACTS_PAYLOAD_SIZE_BYTES=$(stat -c %s "${PAYLOAD}")"
