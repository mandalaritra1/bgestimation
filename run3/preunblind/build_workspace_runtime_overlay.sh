#!/bin/bash
# Build the one-per-campaign Combine overlay.  Workers construct the standard
# CMSSW release from CVMFS, then unpack only these locally-built Combine files.
set -euo pipefail

CAMPAIGN="${CAMPAIGN:-/uscms/home/amandal2/nobackup/bg_ttbar/preunblind_validation_20260811}"
USER_CMSSW="${USER_CMSSW:-/uscms_data/d3/amandal2/bg_ttbar/CMSSW_14_1_0_pre4}"
SCRAM_ARCH="${SCRAM_ARCH:-el9_amd64_gcc12}"
CMSSW_VERSION="${CMSSW_VERSION:-CMSSW_14_1_0_pre4}"
RUNTIME="${RUNTIME:-${CAMPAIGN}/payloads/workspace_runtime_overlay_20260811_v1.tgz}"

required=(
    "bin/${SCRAM_ARCH}"
    "lib/${SCRAM_ARCH}"
    "python"
    "src/HiggsAnalysis/CombinedLimit/python"
    "src/HiggsAnalysis/CombinedLimit/interface"
    "src/CombineHarvester/CombineTools/python"
)
for relative in "${required[@]}"; do
    [[ -e "${USER_CMSSW}/${relative}" ]] || {
        echo "missing required Combine runtime file: ${USER_CMSSW}/${relative}" >&2
        exit 2
    }
done
[[ ! -e "${RUNTIME}" ]] || {
    echo "refusing to overwrite existing runtime overlay: ${RUNTIME}" >&2
    exit 3
}

mkdir -p "$(dirname "${RUNTIME}")"
stage=$(mktemp -d "${CAMPAIGN}/state/workspace-runtime.XXXXXX")
runtime_tmp="${RUNTIME}.tmp.$$"
cleanup() {
    rm -rf "${stage}"
    rm -f "${runtime_tmp}"
}
trap cleanup EXIT

mkdir -p "${stage}/bin" "${stage}/lib" "${stage}/src/HiggsAnalysis/CombinedLimit" \
    "${stage}/src/CombineHarvester/CombineTools"
cp -a "${USER_CMSSW}/bin/${SCRAM_ARCH}" "${stage}/bin/"
cp -a "${USER_CMSSW}/lib/${SCRAM_ARCH}" "${stage}/lib/"
cp -a "${USER_CMSSW}/python" "${stage}/"
cp -a "${USER_CMSSW}/src/HiggsAnalysis/CombinedLimit/python" \
    "${USER_CMSSW}/src/HiggsAnalysis/CombinedLimit/interface" \
    "${stage}/src/HiggsAnalysis/CombinedLimit/"
cp -a "${USER_CMSSW}/src/CombineHarvester/CombineTools/python" \
    "${stage}/src/CombineHarvester/CombineTools/"
{
    echo "created_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "cmssw_version=${CMSSW_VERSION}"
    echo "scram_arch=${SCRAM_ARCH}"
    echo "source_user_cmssw=${USER_CMSSW}"
} > "${stage}/runtime_provenance.txt"
(
    cd "${stage}"
    find bin lib python src -type f -print0 | sort -z | xargs -0 sha256sum > runtime.sha256
    sha256sum -c runtime.sha256
    tar -czf "${runtime_tmp}" .
)
mv "${runtime_tmp}" "${RUNTIME}"
echo "WORKSPACE_RUNTIME_OVERLAY_OK path=${RUNTIME}"
echo "WORKSPACE_RUNTIME_OVERLAY_SHA256=$(sha256sum "${RUNTIME}" | awk '{print $1}')"
echo "WORKSPACE_RUNTIME_OVERLAY_SIZE_BYTES=$(stat -c %s "${RUNTIME}")"
