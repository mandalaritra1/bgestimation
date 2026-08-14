#!/bin/bash
set -euo pipefail

if [[ "$#" -ne 0 ]]; then
    echo "usage: $0" >&2
    exit 1
fi

WIDTH=1
MASS=2000
RMAX=1
REPO="${REPO:-/uscms/home/amandal2/nobackup/bg_ttbar/CMSSW_14_1_0_pre4/src/bgestimation}"
CAMPAIGN="${CAMPAIGN:-/uscms/home/amandal2/nobackup/bg_ttbar/preunblind_validation_20260811}"
SNAPSHOT="${CAMPAIGN}/workspaces/combined/w1/signalZPrime2000_area/higgsCombine_maskedBonly.MultiDimFit.mH0.root"
FIT_RESULT="${CAMPAIGN}/workspaces/combined/w1/signalZPrime2000_area/multidimfit_maskedBonly.root"
SNAPSHOT_VALIDATOR="${REPO}/run3/preunblind/validate_portable_asimov_impacts.py"
SOURCE_VALIDATOR="${REPO}/run3/preunblind/validate_masked_postfit_source.py"
FIT_VALIDATOR="${REPO}/run3/validate_fit_result.py"
SANITIZER="${REPO}/run3/preunblind/sanitize_masked_postfit_2d.py"
HARVESTER="${REPO}/run3/preunblind/harvest_portable_masked_postfit_2d.py"
PAYLOAD="${CAMPAIGN}/payloads/masked_postfit_payload_w1_m2000_v8.tgz"

for required in "${SNAPSHOT}" "${FIT_RESULT}" "${SNAPSHOT_VALIDATOR}" "${SOURCE_VALIDATOR}" "${FIT_VALIDATOR}" "${SANITIZER}" "${HARVESTER}"; do
    [[ -s "${required}" ]] || { echo "missing masked-postfit source: ${required}" >&2; exit 2; }
done
[[ ! -e "${PAYLOAD}" ]] || { echo "refusing to overwrite payload: ${PAYLOAD}" >&2; exit 3; }
stage=$(mktemp -d "${CAMPAIGN}/state/masked-postfit-payload.XXXXXX")
payload_tmp="${PAYLOAD}.tmp.$$"
cleanup() { rm -rf "${stage}"; rm -f "${payload_tmp}"; }
trap cleanup EXIT
mkdir -p "${stage}/bgestimation/run3/preunblind" "${stage}/bgestimation/run3" "${stage}/combined_area"
cp -a "${SNAPSHOT_VALIDATOR}" "${SOURCE_VALIDATOR}" "${SANITIZER}" "${HARVESTER}" "${stage}/bgestimation/run3/preunblind/"
cp -a "${FIT_VALIDATOR}" "${stage}/bgestimation/run3/"
cp -a "${SNAPSHOT}" "${FIT_RESULT}" "${stage}/combined_area/"
python3 "${SNAPSHOT_VALIDATOR}" snapshot "${SNAPSHOT}" --rmax "${RMAX}" \
    --output "${stage}/source_snapshot_validation.json"
python3 "${SOURCE_VALIDATOR}" "${SNAPSHOT}" "${FIT_RESULT}" --rmax "${RMAX}" \
    --output "${stage}/source_masked_postfit_validation.json"
{
    echo "created_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "bgestimation_git=$(git -C "${REPO}" rev-parse HEAD)"
    echo "width=${WIDTH}"
    echo "mass_GeV=${MASS}"
    echo "rMax=${RMAX}"
    echo "snapshot_sha256=$(sha256sum "${SNAPSHOT}" | awk '{print $1}')"
    echo "fit_result_sha256=$(sha256sum "${FIT_RESULT}" | awk '{print $1}')"
    echo "fit_dataset_scope=masked_observed_sidebands_only"
    echo "pass_region_masks=all_four_on_frozen"
    echo "shape_extractor=PostFit2DShapesFromWorkspace"
    echo "shape_extractor_mask_handling=workspace_masks_one_constant_no_override"
    echo "safe_export_scope=unmasked_channels_only"
    echo "allowed_channels=20"
    echo "denied_channels=4"
} > "${stage}/payload_provenance.txt"
(
    cd "${stage}"
    find bgestimation combined_area source_snapshot_validation.json source_masked_postfit_validation.json payload_provenance.txt \
        -type f -print0 | sort -z | xargs -0 sha256sum > payload.sha256
    sha256sum -c payload.sha256
    tar -czf "${payload_tmp}" .
)
mv "${payload_tmp}" "${PAYLOAD}"
echo "MASKED_POSTFIT_PAYLOAD_OK path=${PAYLOAD}"
echo "MASKED_POSTFIT_PAYLOAD_SHA256=$(sha256sum "${PAYLOAD}" | awk '{print $1}')"
