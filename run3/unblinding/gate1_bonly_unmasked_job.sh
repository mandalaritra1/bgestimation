#!/bin/bash
# GATE 1 (UNBLINDING) — unmasked b-only fit on data. r frozen at 0. No s+b
# fit, no limit, no significance. Pre-registered criteria: PLAN.md gates
# 1.1/1.4 checked in-job; 1.2 (GoF), 1.3/1.5 (pulls/constraints) at harvest.
#
# INTERLOCK: argument 5 must be the literal string GATE0-PASSED. The sub
# template ships with a placeholder so accidental submission exits here.
set -euo pipefail

if [[ "$#" -ne 5 ]]; then
    echo "usage: $0 <mode> <width> <mass_GeV> <fwd_tf> GATE0-PASSED" >&2
    exit 2
fi
MODE="$1"
WIDTH="$2"
MASS="$3"
FWD_TF="$4"
INTERLOCK="$5"
case "${MODE}" in gate1_bonly_unmasked) ;; *) echo "bad mode" >&2; exit 4 ;; esac
case "${WIDTH}" in 1|10|30) ;; *) echo "bad width" >&2; exit 3 ;; esac
case "${FWD_TF}" in 2x0) ;; *) echo "fwd TF frozen at 2x0 for unblinding" >&2; exit 3 ;; esac
[[ "${INTERLOCK}" == "GATE0-PASSED" ]] || {
    echo "GATE1_INTERLOCK: refusing to open the SR — Gate 0 not confirmed" >&2
    echo "(pass the literal argument GATE0-PASSED only after PLAN.md Gate 0 is fully checked)" >&2
    exit 90
}

SCRATCH="${_CONDOR_SCRATCH_DIR:?missing _CONDOR_SCRATCH_DIR}"
PAYLOAD="${SCRATCH}/combine_payload_w${WIDTH}_m${MASS}.tgz"
RUNTIME="${SCRATCH}/workspace_runtime_overlay_20260811_v1.tgz"
PAYLOAD_WORK="${SCRATCH}/combine_payload"
RUNTIME_WORK="${SCRATCH}/combine_runtime"
RESULT="${SCRATCH}/gate1_bonly_result"
RESULT_ARCHIVE="${SCRATCH}/gate1_bonly_result.tgz"
CMSSW_VERSION="${CMSSW_VERSION:-CMSSW_14_1_0_pre4}"
SCRAM_ARCH="${SCRAM_ARCH:-el9_amd64_gcc12}"
case "${WIDTH}" in
    1) SIGNAL="signalZPrime${MASS}" ;;
    *) SIGNAL="signalZPrime${MASS}_${WIDTH}" ;;
esac
AREA=""

finalize_result() {
    local rc=$?
    trap - EXIT
    set +e
    mkdir -p "${RESULT}/artifacts"
    if [[ -n "${AREA}" && -d "${AREA}" ]]; then
        for f in "${AREA}/gate1_fit.log" "${AREA}/gate1_fit_validation.log" \
                 "${AREA}/gate1_rpf_bounds.log" "${AREA}/gate1_pulls.json" \
                 "${AREA}"/higgsCombine_gate1BonlyUnmasked*.root \
                 "${AREA}"/multidimfit_gate1BonlyUnmasked*.root; do
            [[ -f "$f" ]] && cp -a "$f" "${RESULT}/artifacts/"
        done
    fi
    {
        echo "campaign=gate1_bonly_unmasked"
        echo "fwd_tf=${FWD_TF}"
        echo "exit_code=${rc}"
        [[ "${rc}" -eq 0 ]] && echo "status=success" || echo "status=failure"
        echo "width=${WIDTH}"
        echo "mass_GeV=${MASS}"
        echo "signal=${SIGNAL}"
        echo "fit=UNMASKED_bonly_r_frozen_0_all_nine_nuisances_floating"
        echo "sr_channels_open=Cen24Pass_Region1,Cen25Pass_Region1,Fwd24Pass_Region1,Fwd25Pass_Region1"
        [[ -s "${PAYLOAD}" ]] && echo "payload_sha256=$(sha256sum "${PAYLOAD}" | awk '{print $1}')"
    } > "${RESULT}/diagnostic.status"
    tar -C "${SCRATCH}" -czf "${RESULT_ARCHIVE}" "$(basename "${RESULT}")"
    echo "GATE1_BONLY_DONE rc=${rc}"
    exit "${rc}"
}
trap finalize_result EXIT

[[ -s "${PAYLOAD}" && -s "${RUNTIME}" ]] || { echo "missing inputs" >&2; exit 5; }
mkdir -p "${PAYLOAD_WORK}" "${RUNTIME_WORK}" "${RESULT}"
tar -xzf "${PAYLOAD}" -C "${PAYLOAD_WORK}"
tar -xzf "${RUNTIME}" -C "${RUNTIME_WORK}"
( cd "${PAYLOAD_WORK}" && sha256sum -c payload.sha256 > /dev/null )
( cd "${RUNTIME_WORK}" && sha256sum -c runtime.sha256 > /dev/null )
for expected in "width=${WIDTH}" "mass_GeV=${MASS}" "signal=${SIGNAL}" "fwd_tf=${FWD_TF}"; do
    grep -Fxq "${expected}" "${PAYLOAD_WORK}/payload_provenance.txt" || {
        echo "GATE1_INVALID provenance=${expected}" >&2; exit 8; }
done

source /cvmfs/cms.cern.ch/cmsset_default.sh
export SCRAM_ARCH
cd "${SCRATCH}"
scramv1 project CMSSW "${CMSSW_VERSION}" > /dev/null 2>&1
cp -a "${RUNTIME_WORK}/." "${SCRATCH}/${CMSSW_VERSION}/"
cd "${SCRATCH}/${CMSSW_VERSION}"
eval "$(scram runtime -sh)"

REPO="${PAYLOAD_WORK}/bgestimation"
PERCAT="${PAYLOAD_WORK}/workspaces/percat"
CEN_AREA="${PERCAT}/ttbarfits_cen2425_2x2_${SIGNAL}"
FWD_AREA="${PERCAT}/ttbarfits_fwd2425_${FWD_TF}_${SIGNAL}"
AREA="${SCRATCH}/gate1_area/${SIGNAL}_area"
mkdir -p "${AREA}/cen/${SIGNAL}_area" "${AREA}/fwd/${SIGNAL}_area"
cp -a "${CEN_AREA}/base.root" "${AREA}/cen/base.root"
cp -a "${FWD_AREA}/base.root" "${AREA}/fwd/base.root"
cp -a "${CEN_AREA}/${SIGNAL}_area/card.txt" "${AREA}/cen/${SIGNAL}_area/card.txt"
cp -a "${FWD_AREA}/${SIGNAL}_area/card.txt" "${AREA}/fwd/${SIGNAL}_area/card.txt"

(
    cd "${AREA}"
    combineCards.py cen="cen/${SIGNAL}_area/card.txt" fwd="fwd/${SIGNAL}_area/card.txt" \
        > "${SIGNAL}_card_combined.txt"
    text2workspace.py "${SIGNAL}_card_combined.txt" -o workspace.root --channel-masks --X-no-jmax

    # GATE 1: masks explicitly OFF — the four SR channels ENTER the
    # likelihood. r is frozen at 0 (b-only). Same solver settings as the
    # validated blinded production fit.
    M_OFF="mask_cen_Cen24Pass_Region1=0,mask_cen_Cen25Pass_Region1=0,mask_fwd_Fwd24Pass_Region1=0,mask_fwd_Fwd25Pass_Region1=0"
    M_FRZ="mask_cen_Cen24Pass_Region1,mask_cen_Cen25Pass_Region1,mask_fwd_Fwd24Pass_Region1,mask_fwd_Fwd25Pass_Region1"

    combine -M MultiDimFit -d workspace.root -m 0 \
        --rMin 0 --rMax 1 \
        --setParameters "r=0,${M_OFF}" \
        --freezeParameters "r,${M_FRZ}" \
        --setParameterRanges 'rgx{.*rpf_par.*}=-50,50:rgx{.*rpf_par0}=0.001,50' \
        --cminDefaultMinimizerStrategy 2 --cminPreScan --cminPreFit 1 \
        --X-rtd MINIMIZER_MaxCalls=5000000 \
        --saveWorkspace --saveFitResult -n _gate1BonlyUnmasked \
        > gate1_fit.log 2>&1

    # Hard gate 1.1
    python3 "${REPO}/run3/validate_fit_result.py" \
        multidimfit_gate1BonlyUnmasked.root --key fit_mdf \
        --min-cov-qual 3 --max-edm 0.01 > gate1_fit_validation.log 2>&1

    # Hard gate 1.4 (rpf bounds) + full floating-parameter dump for 1.3/1.5
    python3 - <<'PY' > gate1_rpf_bounds.log 2>&1
import json
import ROOT
f = ROOT.TFile.Open("multidimfit_gate1BonlyUnmasked.root")
fr = f.Get("fit_mdf")
pars = fr.floatParsFinal()
dump, bad = [], []
for i in range(pars.getSize()):
    p = pars.at(i)
    rec = {"name": p.GetName(), "value": p.getVal(), "error": p.getError(),
           "min": p.getMin(), "max": p.getMax()}
    dump.append(rec)
    if "rpf_par" in p.GetName():
        lo, hi, v = p.getMin(), p.getMax(), p.getVal()
        span = hi - lo
        if (hi - v) < 0.05 * span or (v - lo) < 0.05 * span:
            bad.append(rec)
        if p.GetName().endswith("rpf_par0") and abs(v - 0.001) < 1e-6:
            bad.append({**rec, "pinned_par0": True})
with open("gate1_pulls.json", "w") as out:
    json.dump({"fit": {"status": fr.status(), "covQual": fr.covQual(),
                       "edm": fr.edm(), "minNll": fr.minNll()},
               "floating_parameters": dump,
               "rpf_bound_violations": bad}, out)
if bad:
    raise RuntimeError(f"GATE 1.4 FAIL: rpf params near bounds: {[b['name'] for b in bad]}")
print(f"GATE 1.4 OK: {sum(1 for d in dump if 'rpf_par' in d['name'])} rpf params, none within 5% of bounds")
PY
)

for required in \
    "${AREA}/higgsCombine_gate1BonlyUnmasked.MultiDimFit.mH0.root" \
    "${AREA}/multidimfit_gate1BonlyUnmasked.root" \
    "${AREA}/gate1_fit_validation.log" \
    "${AREA}/gate1_pulls.json"; do
    [[ -s "${required}" ]] || { echo "GATE1_INVALID missing=${required}" >&2; exit 12; }
done
echo "GATE1_BONLY_OK width=${WIDTH} mass=${MASS}"
