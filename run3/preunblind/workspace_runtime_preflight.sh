#!/bin/bash
# One worker-local, zero-analysis check before submitting the workspace matrix.
set -euo pipefail

SCRATCH="${_CONDOR_SCRATCH_DIR:?missing _CONDOR_SCRATCH_DIR}"
RUNTIME="${SCRATCH}/workspace_runtime_overlay_20260811_v1.tgz"
RUNTIME_WORK="${SCRATCH}/workspace_runtime"
CMSSW_VERSION="${CMSSW_VERSION:-CMSSW_14_1_0_pre4}"
SCRAM_ARCH="${SCRAM_ARCH:-el9_amd64_gcc12}"

[[ -s "${RUNTIME}" ]] || { echo "missing runtime overlay: ${RUNTIME}" >&2; exit 2; }
[[ -r /cvmfs/cms.cern.ch/cmsset_default.sh ]] || { echo "missing CVMFS CMS setup" >&2; exit 3; }

mkdir -p "${RUNTIME_WORK}"
tar -xzf "${RUNTIME}" -C "${RUNTIME_WORK}"
(
    cd "${RUNTIME_WORK}"
    sha256sum -c runtime.sha256
)
source /cvmfs/cms.cern.ch/cmsset_default.sh
export SCRAM_ARCH
cd "${SCRATCH}"
scramv1 project CMSSW "${CMSSW_VERSION}"
CMS_RELEASE="${SCRATCH}/${CMSSW_VERSION}"
cp -a "${RUNTIME_WORK}/." "${CMS_RELEASE}/"
cd "${CMS_RELEASE}"
eval "$(scram runtime -sh)"
python3 - <<'PY'
import ROOT
status = ROOT.gSystem.Load("libHiggsAnalysisCombinedLimit.so")
if status < 0 or not hasattr(ROOT, "RooParametricHist2D"):
    raise RuntimeError("CombinedLimit overlay failed to load RooParametricHist2D")
from HiggsAnalysis.CombinedLimit.PhysicsModel import PhysicsModel
print("WORKER_RUNTIME_PREFLIGHT_OK", ROOT.gROOT.GetVersion(), PhysicsModel.__name__)
PY
combine --help >/dev/null
text2workspace.py --help >/dev/null
{
    echo "cmssw_version=${CMSSW_VERSION}"
    echo "scram_arch=${SCRAM_ARCH}"
    echo "runtime_sha256=$(sha256sum "${RUNTIME}" | awk '{print $1}')"
    echo "runtime_overlay=loaded"
} > "${SCRATCH}/runtime_preflight.ok"
(
    cd "${SCRATCH}"
    tar -czf runtime_preflight.tgz runtime_preflight.ok
)
echo "WORKER_RUNTIME_PREFLIGHT_OK result=runtime_preflight.tgz"
