#!/bin/bash
# Worker-side workspace construction.  All mutable files and the local CMSSW
# project live below _CONDOR_SCRATCH_DIR.  The only site dependency is CVMFS.
set -euo pipefail

if [[ "$#" -ne 4 ]]; then
    echo "usage: $0 <fwd2425> <1|10|30> <mass_GeV> <tf_order>" >&2
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

TF_ORDER="${4:?missing TF order argument}"
case "${TF_ORDER}" in
    0x0|0x1|0x2|1x0|1x1|1x2|2x0|2x1|2x2|3x0|3x1) ;;
    *) echo "unsupported TF order: ${TF_ORDER}" >&2; exit 3 ;;
esac
case "${CATEGORY}" in
    fwd2425) ;;
    *) echo "ftest variant is fwd2425-only: ${CATEGORY}" >&2; exit 3 ;;
esac

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

# v2: ttbar.py only honors --tf when --study ftest (which would run its own
# unmasked fits). In --study workspace mode the TF order comes from
# jsons/TransferFunctions.json, so v1 silently built 2x1 for every requested
# order. Patch the SCRATCH copies only: point the category at the requested
# order, and add the 2x0 form missing from _rpf_options. Both patches are
# fail-closed (exceptions abort the job before any fit runs).
FTEST_TF_ORDER="${TF_ORDER}" FTEST_CATEGORY="${CATEGORY}" python3 - <<'PY'
import json, os, pathlib

order = os.environ["FTEST_TF_ORDER"]
cat = os.environ["FTEST_CATEGORY"]

tf_path = pathlib.Path("jsons/TransferFunctions.json")
tf = json.loads(tf_path.read_text())
assert cat in tf, "category %s absent from TransferFunctions.json" % cat
tf[cat] = order
tf_path.write_text(json.dumps(tf, indent=4))

# v3: generate any missing AxB entry in _rpf_options from the order itself,
# following the existing form conventions: 0.1*(poly in x)*(1+poly in y).
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
    print("FTEST_TF_GENERATED order=%s form=%s nparams=%d" % (order, form, nparams))
assert "'%s'" % order in src_path.read_text(), "order %s absent from _rpf_options" % order
print("FTEST_TF_PATCH_OK category=%s order=%s" % (cat, order))
PY
echo "ttbar_patched_sha256=$(sha256sum ttbar.py | awk '{print $1}')"

# --study workspace is intentionally the only analysis action here: it makes a
# base workspace and signal card, and must never fit observed data.
python3 -u ttbar.py \
    --cat "${CATEGORY}" \
    --tf "${TF_ORDER}" \
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

# ---- blinded F-test stages: masked b-only fit + masked saturated GoF ----
FAREA="${SCRATCH}/ftest_area"
mkdir -p "${FAREA}"
cp -a "${BASE}" "${FAREA}/base.root"
mkdir -p "${FAREA}/${SIGNAL}_area"
cp -a "${CARD}" "${FAREA}/${SIGNAL}_area/card.txt"
cd "${FAREA}"
text2workspace.py "${SIGNAL}_area/card.txt" -o workspace.root --channel-masks --X-no-jmax

M_ON="mask_Fwd24Pass_Region1=1,mask_Fwd25Pass_Region1=1"
M_FRZ="mask_Fwd24Pass_Region1,mask_Fwd25Pass_Region1"

combine -M MultiDimFit -d workspace.root -m 0 \
    --rMin 0 --rMax 1 \
    --setParameters "r=0,${M_ON}" \
    --freezeParameters "r,${M_FRZ}" \
    --setParameterRanges 'rgx{.*rpf_par.*}=-50,50:rgx{.*rpf_par0}=0.001,50' \
    --cminDefaultMinimizerStrategy 2 --cminPreScan --cminPreFit 1 \
    --X-rtd MINIMIZER_MaxCalls=5000000 \
    --saveWorkspace --saveFitResult -n _ftestfit > ftest_fit.log 2>&1

combine -M GoodnessOfFit -d higgsCombine_ftestfit.MultiDimFit.mH0.root \
    --snapshotName MultiDimFit -m 0 \
    --algo saturated --rMin 0 --rMax 1 \
    --setParameters "r=0,${M_ON}" --freezeParameters "r,${M_FRZ}" \
    --X-rtd MINIMIZER_MaxCalls=5000000 \
    -n _ftestgof > ftest_gof.log 2>&1

python3 - <<'PYEOF' > ftest_summary.json
import glob, json
import ROOT
rec = {}
f = ROOT.TFile.Open("multidimfit_ftestfit.root")
fr = f.Get("fit_mdf")
rec["fit"] = {"status": fr.status(), "covQual": fr.covQual(), "edm": fr.edm(),
              "minNll": fr.minNll()}
rec["n_rpf_params"] = sum(1 for i in range(fr.floatParsFinal().getSize())
                          if "rpf_par" in fr.floatParsFinal().at(i).GetName())
g = ROOT.TFile.Open(glob.glob("higgsCombine_ftestgof.GoodnessOfFit.mH0*.root")[0])
tree = g.Get("limit")
tree.GetEntry(0)
rec["gof_saturated"] = float(tree.limit)
print(json.dumps(rec))
PYEOF
cat ftest_summary.json

RESULT_DIR="${SCRATCH}/ftest_result"
mkdir -p "${RESULT_DIR}"
cp -a ftest_fit.log ftest_gof.log ftest_summary.json \
    multidimfit_ftestfit.root "${RESULT_DIR}/" 2>/dev/null || true
{
    echo "tf_order=${TF_ORDER}"
    echo "category=${CATEGORY}"
    echo "signal=${SIGNAL}"
    echo "fit_dataset_scope=masked_observed_sidebands_only"
} >> "${RESULT_DIR}/ftest_summary.json.meta"
tar -C "${SCRATCH}" -czf "${SCRATCH}/ftest_result.tgz" ftest_result
echo "FTEST_JOB_OK tf=${TF_ORDER}"
