#!/bin/bash
# Worker-side workspace construction.  All mutable files and the local CMSSW
# project live below _CONDOR_SCRATCH_DIR.  The only site dependency is CVMFS.
set -euo pipefail

if [[ "$#" -lt 3 || "$#" -gt 4 ]]; then
    echo "usage: $0 <cen2425|fwd2425> <1|10|30> <mass_GeV> [tf_order]" >&2
    exit 2
fi

CATEGORY="$1"
WIDTH="$2"
MASS="$3"
SCRATCH="${_CONDOR_SCRATCH_DIR:?missing _CONDOR_SCRATCH_DIR}"
PAYLOAD="${SCRATCH}/workspace_payload_${CATEGORY}_w${WIDTH}_m${MASS}.tgz"
RUNTIME="${SCRATCH}/workspace_runtime_overlay_20260811_v1.tgz"
WORK="${SCRATCH}/workspace_payload"
RUNTIME_WORK="${SCRATCH}/workspace_runtime"
RESULT="${SCRATCH}/workspace_result"
CMSSW_VERSION="${CMSSW_VERSION:-CMSSW_14_1_0_pre4}"
SCRAM_ARCH="${SCRAM_ARCH:-el9_amd64_gcc12}"

case "${CATEGORY}" in
    cen2425) TF_ORDER="2x2" ;;
    fwd2425) TF_ORDER="2x1" ;;
    *) echo "unsupported category: ${CATEGORY}" >&2; exit 3 ;;
esac
# v2: optional 4th argument overrides the category-default TF order (used for
# the F-test-selected fwd order); validated against the same grid as the
# ftest jobs, then imposed on the scratch payload before the build.
if [[ "$#" -eq 4 ]]; then
    TF_ORDER="$4"
    case "${TF_ORDER}" in
        0x0|0x1|0x2|1x0|1x1|1x2|2x0|2x1|2x2|3x0|3x1) ;;
        *) echo "unsupported TF order: ${TF_ORDER}" >&2; exit 3 ;;
    esac
fi

case "${WIDTH}" in
    1)  SCENARIO="ZPrime_1";  SIGNAL="signalZPrime${MASS}" ;;
    10) SCENARIO="ZPrime_10"; SIGNAL="signalZPrime${MASS}_10" ;;
    30) SCENARIO="ZPrime_30"; SIGNAL="signalZPrime${MASS}_30" ;;
    *) echo "unsupported width: ${WIDTH}" >&2; exit 4 ;;
esac

[[ -s "${PAYLOAD}" ]] || { echo "missing payload: ${PAYLOAD}" >&2; exit 5; }
[[ -s "${RUNTIME}" ]] || { echo "missing runtime overlay: ${RUNTIME}" >&2; exit 6; }
[[ -r /cvmfs/cms.cern.ch/cmsset_default.sh ]] || {
    echo "missing CVMFS CMS setup" >&2
    exit 7
}

mkdir -p "${WORK}" "${RUNTIME_WORK}" "${RESULT}"
tar -xzf "${PAYLOAD}" -C "${WORK}"
(
    cd "${WORK}"
    sha256sum -c payload.sha256
)

input_files=(
    "TTbarAllHadComb_Data.root"
    "TTbarAllHad24_TTbar.root"
    "TTbarAllHad25_TTbar.root"
    "TTbarAllHad24_${SIGNAL}.root"
    "TTbarAllHad25_${SIGNAL}.root"
)
for filename in "${input_files[@]}"; do
    [[ -s "${WORK}/inputs/${filename}" ]] || {
        echo "WORKSPACE_JOB_INVALID missing_point_input=${filename}" >&2
        exit 8
    }
done
input_count=$(find "${WORK}/inputs" -maxdepth 1 -type f -name '*.root' | wc -l)
[[ "${input_count}" -eq 5 ]] || {
    echo "WORKSPACE_JOB_INVALID input_root_files=${input_count}" >&2
    exit 8
}

source /cvmfs/cms.cern.ch/cmsset_default.sh
export SCRAM_ARCH
cd "${SCRATCH}"
scramv1 project CMSSW "${CMSSW_VERSION}"
CMS_RELEASE="${SCRATCH}/${CMSSW_VERSION}"
tar -xzf "${RUNTIME}" -C "${RUNTIME_WORK}"
(
    cd "${RUNTIME_WORK}"
    sha256sum -c runtime.sha256
)
cp -a "${RUNTIME_WORK}/." "${CMS_RELEASE}/"
cd "${CMS_RELEASE}"
eval "$(scram runtime -sh)"
export PYTHONPATH="${WORK}/2DAlphabet:${PYTHONPATH:-}"
python3 - <<'PY'
import ROOT
status = ROOT.gSystem.Load("libHiggsAnalysisCombinedLimit.so")
if status < 0 or not hasattr(ROOT, "RooParametricHist2D"):
    raise RuntimeError("CombinedLimit overlay failed to load RooParametricHist2D")
from HiggsAnalysis.CombinedLimit.PhysicsModel import PhysicsModel
print("WORKSPACE_RUNTIME_PREFLIGHT_OK", ROOT.gROOT.GetVersion(), PhysicsModel.__name__)
PY
combine --help >/dev/null
text2workspace.py --help >/dev/null
cd "${WORK}/bgestimation"

OUTPUT_DIR="${SCRATCH}/workspace_output"
AREA="${OUTPUT_DIR}/ttbarfits_${CATEGORY}_${TF_ORDER}_${SIGNAL}"
CARD="${AREA}/${SIGNAL}_area/card.txt"
BASE="${AREA}/base.root"

echo "WORKSPACE_PORTABLE_JOB_START category=${CATEGORY} width=${WIDTH} mass=${MASS}"
echo "payload_sha256=$(sha256sum "${PAYLOAD}" | awk '{print $1}')"
echo "runtime_sha256=$(sha256sum "${RUNTIME}" | awk '{print $1}')"
echo "ttbar_sha256=$(sha256sum ttbar.py | awk '{print $1}')"
echo "twodalphabet_sha256=$(sha256sum "${WORK}/2DAlphabet/TwoDAlphabet/twoDalphabet.py" | awk '{print $1}')"

# v2: --study workspace takes the TF order from jsons/TransferFunctions.json
# (the --tf flag only applies to --study ftest), so impose the requested order
# on the SCRATCH payload copies. Missing AxB forms are generated following the
# existing 0.1*(poly x)*(1+poly y) convention. Fail-closed: any exception
# aborts before the build. Idempotent when the order equals the json default.
FTEST_TF_ORDER="${TF_ORDER}" FTEST_CATEGORY="${CATEGORY}" python3 - <<'PY'
import json, os, pathlib

order = os.environ["FTEST_TF_ORDER"]
cat = os.environ["FTEST_CATEGORY"]

tf_path = pathlib.Path("jsons/TransferFunctions.json")
tf = json.loads(tf_path.read_text())
assert cat in tf, "category %s absent from TransferFunctions.json" % cat
tf[cat] = order
tf_path.write_text(json.dumps(tf, indent=4))

src_path = pathlib.Path("ttbar.py")
src = src_path.read_text()
if "'%s'" % order not in src:
    nx, ny = (int(v) for v in order.split("x"))
    xterms = ["@0"] + ["@%d*x%s" % (i, "" if i == 1 else "**%d" % i)
                       for i in range(1, nx + 1)]
    yterms = ["@%d*y%s" % (nx + j, "" if j == 1 else "**%d" % j)
              for j in range(1, ny + 1)]
    form = "0.1*(%s)" % "+".join(xterms)
    if yterms:
        form += "*(1+%s)" % "+".join(yterms)
    nparams = nx + ny + 1
    anchor = "_rpf_options = {\n"
    assert anchor in src, "_rpf_options anchor not found in ttbar.py"
    entry = (anchor
             + "    '%s': {\n" % order
             + "        'form': '%s',\n" % form
             + "        'constraints': _generate_constraints(%d)\n" % nparams
             + "    },\n")
    src_path.write_text(src.replace(anchor, entry, 1))
    print("WORKSPACE_TF_GENERATED order=%s form=%s nparams=%d" % (order, form, nparams))
assert "'%s'" % order in src_path.read_text(), "order %s absent from _rpf_options" % order
print("WORKSPACE_TF_PATCH_OK category=%s order=%s" % (cat, order))
PY
echo "ttbar_patched_sha256=$(sha256sum ttbar.py | awk '{print $1}')"

# --study workspace is intentionally the only analysis action here: it makes a
# base workspace and signal card, and must never fit observed data.
python3 -u ttbar.py \
    --cat "${CATEGORY}" \
    --scenario "${SCENARIO}" \
    --input "${WORK}/inputs" \
    --output "${OUTPUT_DIR}" \
    --signal "${SIGNAL#signal}" \
    --study workspace

for required in "${BASE}" "${CARD}" "${AREA}/runConfig.json"; do
    [[ -s "${required}" ]] || {
        echo "WORKSPACE_JOB_INVALID missing_or_empty=${required}" >&2
        exit 10
    }
done

python3 - "${BASE}" <<'PY'
import ROOT
import sys

workspace_file = ROOT.TFile.Open(sys.argv[1])
if not workspace_file or workspace_file.IsZombie() or not workspace_file.Get("w"):
    raise RuntimeError("invalid base.root or missing RooWorkspace key w")
print("WORKSPACE_ROOT_VALID", workspace_file.GetNkeys())
workspace_file.Close()
PY

if find "${AREA}" -type f \( -name 'fitDiagnostics*.root' -o -name 'multidimfit*.root' -o -name '*AsymptoticLimits*.root' \) | grep -q .; then
    echo "WORKSPACE_JOB_INVALID unexpected_fit_output=${AREA}" >&2
    exit 11
fi

grep -q "${SIGNAL}" "${CARD}" || {
    echo "WORKSPACE_JOB_INVALID signal_missing_from_card=${CARD}" >&2
    exit 12
}

mkdir -p "${RESULT}/area"
cp -a "${AREA}/." "${RESULT}/area/"
{
    echo "category=${CATEGORY}"
    echo "width=${WIDTH}"
    echo "mass_GeV=${MASS}"
    echo "tf_order=${TF_ORDER}"
    echo "signal=${SIGNAL}"
    echo "input_root_files=${input_count}"
    echo "base_root=area/base.root"
    echo "base_sha256=$(sha256sum "${BASE}" | awk '{print $1}')"
    echo "card=area/${SIGNAL}_area/card.txt"
    echo "card_sha256=$(sha256sum "${CARD}" | awk '{print $1}')"
    echo "runConfig_sha256=$(sha256sum "${AREA}/runConfig.json" | awk '{print $1}')"
    echo "payload_sha256=$(sha256sum "${PAYLOAD}" | awk '{print $1}')"
    echo "runtime_sha256=$(sha256sum "${RUNTIME}" | awk '{print $1}')"
} > "${RESULT}/workspace.ok"
(
    cd "${SCRATCH}"
    tar -czf workspace_result.tgz workspace_result
)

echo "WORKSPACE_PORTABLE_JOB_OK result=workspace_result.tgz"
