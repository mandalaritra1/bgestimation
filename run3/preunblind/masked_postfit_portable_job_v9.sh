#!/bin/bash
# Evaluate the already validated masked background-only fit with the dedicated
# 2D shape extractor, then return only an explicit 20-channel sanitized
# projection package.  The raw 24-channel file stays in worker scratch and is
# never transferred.
set -euo pipefail

if [[ "$#" -ne 0 ]]; then
    echo "usage: $0" >&2
    exit 2
fi

WIDTH=1
MASS=2000
RMAX=0.5
SCRATCH="${_CONDOR_SCRATCH_DIR:?missing _CONDOR_SCRATCH_DIR}"
PAYLOAD="${SCRATCH}/masked_postfit_payload_w1_m2000_v9.tgz"
RUNTIME="${SCRATCH}/workspace_runtime_overlay_20260811_v1.tgz"
PAYLOAD_WORK="${SCRATCH}/masked_postfit_payload"
RUNTIME_WORK="${SCRATCH}/masked_postfit_runtime"
RAW_AREA="${SCRATCH}/masked_postfit_raw"
SAFE_AREA="${SCRATCH}/masked_postfit_safe"
REPO="${PAYLOAD_WORK}/bgestimation"
SNAPSHOT="${PAYLOAD_WORK}/combined_area/higgsCombine_maskedBonly.MultiDimFit.mH0.root"
FIT_RESULT="${PAYLOAD_WORK}/combined_area/multidimfit_maskedBonly.root"
SNAPSHOT_VALIDATOR="${REPO}/run3/preunblind/validate_portable_asimov_impacts_v2.py"
SOURCE_VALIDATOR="${REPO}/run3/preunblind/validate_masked_postfit_source.py"
FIT_VALIDATOR="${REPO}/run3/validate_fit_result.py"
SANITIZER="${REPO}/run3/preunblind/sanitize_masked_postfit_2d.py"
CMSSW_VERSION="${CMSSW_VERSION:-CMSSW_14_1_0_pre4}"
SCRAM_ARCH="${SCRAM_ARCH:-el9_amd64_gcc12}"
CURRENT_STAGE="initialization"

finalize_result() {
    local payload_rc=$?
    trap - EXIT
    set +e
    mkdir -p "${SCRATCH}/masked_postfit_result/area"
    if [[ -d "${SAFE_AREA}" ]]; then
        cp -a "${SAFE_AREA}/." "${SCRATCH}/masked_postfit_result/area/"
    fi
    {
        echo "exit_code=${payload_rc}"
        echo "terminal_stage=${CURRENT_STAGE}"
        echo "width=${WIDTH}"
        echo "mass_GeV=${MASS}"
        echo "rMax=${RMAX}"
        echo "fit_dataset_scope=masked_observed_sidebands_only"
        echo "fit_hypothesis=background_only_r_fixed_zero"
        echo "pass_region_masks=all_four_on_frozen"
        echo "shape_dataset=data_obs"
        echo "safe_export_scope=unmasked_channels_only"
        echo "raw_postfit2d_disposition=worker_scratch_only"
        echo "shape_extractor_mask_handling=workspace_masks_one_constant_no_override"
        echo "allowed_channels=20"
        echo "denied_channels=4"
        echo "shape_extractor=PostFit2DShapesFromWorkspace"
        [[ -s "${FIT_RESULT}" ]] && \
            echo "fit_result_sha256=$(sha256sum "${FIT_RESULT}" | awk '{print $1}')"
        [[ -s "${RAW_AREA}/postfitshapes_b.root" ]] && \
            echo "raw_postfit2d_sha256=$(sha256sum "${RAW_AREA}/postfitshapes_b.root" | awk '{print $1}')"
        [[ -s "${SNAPSHOT}" ]] && echo "snapshot_sha256=$(sha256sum "${SNAPSHOT}" | awk '{print $1}')"
        [[ -s "${PAYLOAD}" ]] && echo "payload_sha256=$(sha256sum "${PAYLOAD}" | awk '{print $1}')"
        [[ -s "${RUNTIME}" ]] && echo "runtime_sha256=$(sha256sum "${RUNTIME}" | awk '{print $1}')"
    } > "${SCRATCH}/masked_postfit_result/status.txt"
    (
        cd "${SCRATCH}/masked_postfit_result"
        find area -type f -print0 | sort -z | xargs -0 -r sha256sum > artifact_hashes.sha256
    )
    tar -C "${SCRATCH}" -czf "${SCRATCH}/.masked_postfit_result.tgz.tmp" masked_postfit_result
    mv "${SCRATCH}/.masked_postfit_result.tgz.tmp" "${SCRATCH}/masked_postfit_result.tgz"
    echo "MASKED_POSTFIT_PORTABLE_RESULT exit_code=${payload_rc} stage=${CURRENT_STAGE} archive=masked_postfit_result.tgz"
    exit "${payload_rc}"
}
trap finalize_result EXIT

mkdir -p "${PAYLOAD_WORK}" "${RUNTIME_WORK}" "${RAW_AREA}" "${SAFE_AREA}"
[[ -s "${PAYLOAD}" ]] || { echo "missing masked-postfit payload" >&2; exit 3; }
[[ -s "${RUNTIME}" ]] || { echo "missing runtime overlay" >&2; exit 4; }
[[ -r /cvmfs/cms.cern.ch/cmsset_default.sh ]] || { echo "missing CVMFS CMS setup" >&2; exit 5; }

CURRENT_STAGE="payload_validation"
tar -xzf "${PAYLOAD}" -C "${PAYLOAD_WORK}"
tar -xzf "${RUNTIME}" -C "${RUNTIME_WORK}"
( cd "${PAYLOAD_WORK}" && sha256sum -c payload.sha256 )
( cd "${RUNTIME_WORK}" && sha256sum -c runtime.sha256 )
for expected in \
    "width=${WIDTH}" "mass_GeV=${MASS}" "rMax=${RMAX}" \
    "fit_dataset_scope=masked_observed_sidebands_only" \
    "pass_region_masks=all_four_on_frozen" \
    "shape_extractor=PostFit2DShapesFromWorkspace" \
    "shape_extractor_mask_handling=workspace_masks_one_constant_no_override" \
    "safe_export_scope=unmasked_channels_only"; do
    grep -Fxq "${expected}" "${PAYLOAD_WORK}/payload_provenance.txt" || {
        echo "MASKED_POSTFIT_INVALID payload_provenance=${expected}" >&2; exit 6;
    }
done

CURRENT_STAGE="runtime_setup"
source /cvmfs/cms.cern.ch/cmsset_default.sh
export SCRAM_ARCH
cd "${SCRATCH}"
scramv1 project CMSSW "${CMSSW_VERSION}" > "${SAFE_AREA}/runtime_setup.log" 2>&1
CMS_RELEASE="${SCRATCH}/${CMSSW_VERSION}"
cp -a "${RUNTIME_WORK}/." "${CMS_RELEASE}/"
cd "${CMS_RELEASE}"
eval "$(scram runtime -sh)"
python3 - <<'PY' > "${SAFE_AREA}/runtime_preflight.log" 2>&1
import ROOT
status = ROOT.gSystem.Load("libHiggsAnalysisCombinedLimit.so")
if status < 0:
    raise RuntimeError("CombinedLimit overlay failed to load")
print("MASKED_POSTFIT_RUNTIME_OK", ROOT.gROOT.GetVersion())
PY
combine --help >> "${SAFE_AREA}/runtime_preflight.log" 2>&1
command -v PostFit2DShapesFromWorkspace >> "${SAFE_AREA}/runtime_preflight.log"

CURRENT_STAGE="snapshot_validation"
python3 "${SNAPSHOT_VALIDATOR}" snapshot "${SNAPSHOT}" --rmax "${RMAX}" \
    --output "${SAFE_AREA}/snapshot_validation.json" \
    > "${SAFE_AREA}/snapshot_validation.log" 2>&1
python3 "${SOURCE_VALIDATOR}" "${SNAPSHOT}" "${FIT_RESULT}" --rmax "${RMAX}" \
    --output "${SAFE_AREA}/masked_postfit_source_validation.json" \
    > "${SAFE_AREA}/masked_postfit_source_validation.log" 2>&1

CURRENT_STAGE="fit_validation"
[[ -s "${FIT_RESULT}" ]] || { echo "missing validated masked fit result" >&2; exit 9; }
python3 "${FIT_VALIDATOR}" "${FIT_RESULT}" --key fit_mdf --min-cov-qual 3 --max-edm 0.01 \
    > "${SAFE_AREA}/source_fit_validation.log" 2>&1

CURRENT_STAGE="postfit2d"
RAW_POSTFIT2D="${RAW_AREA}/postfitshapes_b.root"
PostFit2DShapesFromWorkspace --workspace "${SNAPSHOT}" --dataset data_obs \
    --output "${RAW_POSTFIT2D}" --fitresult "${FIT_RESULT}:fit_mdf" \
    --postfit --skip-prefit --skip-proc-errs \
    --samples 200 --print \
    > "${SAFE_AREA}/postfit2d.log" 2>&1
[[ -s "${RAW_POSTFIT2D}" ]] || { echo "missing raw 2D postfit ROOT" >&2; exit 10; }

CURRENT_STAGE="sanitize"
python3 "${SANITIZER}" "${RAW_POSTFIT2D}" \
    --output-root "${SAFE_AREA}/masked_postfit_2d_safe.root" \
    --output-json "${SAFE_AREA}/masked_postfit_2d_safe.json" \
    > "${SAFE_AREA}/sanitize2d.log" 2>&1
[[ -s "${SAFE_AREA}/masked_postfit_2d_safe.root" ]] || { echo "missing sanitized 2D ROOT" >&2; exit 11; }
[[ -s "${SAFE_AREA}/masked_postfit_2d_safe.json" ]] || { echo "missing sanitized 2D JSON" >&2; exit 12; }
if find "${SAFE_AREA}" -type f \( -name 'fitDiagnostics*.root' -o -name 'higgsCombine*.root' -o -name 'postfitshapes*.root' \) | grep -q .; then
    echo "unsafe raw fit or 2D shape artifact entered transfer area" >&2
    exit 13
fi
CURRENT_STAGE="complete"
echo "MASKED_POSTFIT_JOB_OK allowed_channels=20 denied_channels=4"
