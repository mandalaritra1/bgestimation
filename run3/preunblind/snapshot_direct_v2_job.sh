#!/bin/bash
# Direct masked background-only snapshot builder (v2 snapshot foundation).
# One fit on the freshly built workspace with ALL nine nuisances floating from
# the start (no stage-1 freeze, no refloat): the 2026-08-13 MaxCalls fix makes
# the direct fit converge, and the saved workspace keeps the COMPLETE
# ModelConfig nuisance set. This retires the two-stage freeze/refloat snapshot
# whose ModelConfig had silently lost jes/jer/pileup/ttag_pt1 (discovered by
# the impacts v4 validator, 2026-08-14) — frequentist toys built on those
# snapshots under-fluctuate the dropped constraints.
set -euo pipefail

if [[ "$#" -ne 4 ]]; then
    echo "usage: $0 <mode> <width> <mass_GeV> <rMax>" >&2
    exit 2
fi
MODE="$1"
WIDTH="$2"
MASS="$3"
RMAX="$4"
case "${MODE}" in snapshot_direct_v2) ;; *) echo "bad mode" >&2; exit 4 ;; esac
case "${WIDTH}" in 1|10|30) ;; *) echo "bad width" >&2; exit 3 ;; esac
case "${MASS}" in 2000|4000|6000|7000) ;; *) echo "bad mass" >&2; exit 3 ;; esac

SCRATCH="${_CONDOR_SCRATCH_DIR:?missing _CONDOR_SCRATCH_DIR}"
PAYLOAD="${SCRATCH}/combine_payload_w${WIDTH}_m${MASS}.tgz"
RUNTIME="${SCRATCH}/workspace_runtime_overlay_20260811_v1.tgz"
PAYLOAD_WORK="${SCRATCH}/combine_payload"
RUNTIME_WORK="${SCRATCH}/combine_runtime"
RESULT="${SCRATCH}/snapshot_direct_v2_result"
RESULT_ARCHIVE="${SCRATCH}/snapshot_direct_v2_result.tgz"
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
        for f in "${AREA}/direct_fit.log" "${AREA}/direct_fit_validation.log" \
                 "${AREA}/modelconfig_validation.log" \
                 "${AREA}"/higgsCombine_maskedBonlyDirect*.root \
                 "${AREA}"/multidimfit_maskedBonlyDirect*.root; do
            [[ -f "$f" ]] && cp -a "$f" "${RESULT}/artifacts/"
        done
    fi
    {
        echo "campaign=snapshot_direct_v2"
        echo "exit_code=${rc}"
        [[ "${rc}" -eq 0 ]] && echo "status=success" || echo "status=failure"
        echo "width=${WIDTH}"
        echo "mass_GeV=${MASS}"
        echo "rMax=${RMAX}"
        echo "signal=${SIGNAL}"
        echo "fit=direct_masked_bonly_all_nine_nuisances_floating"
        echo "solver=strategy2_prescan_prefit_maxcalls5M"
        [[ -s "${PAYLOAD}" ]] && echo "payload_sha256=$(sha256sum "${PAYLOAD}" | awk '{print $1}')"
    } > "${RESULT}/diagnostic.status"
    tar -C "${SCRATCH}" -czf "${RESULT_ARCHIVE}" "$(basename "${RESULT}")"
    echo "SNAPSHOT_DIRECT_V2_DONE rc=${rc}"
    exit "${rc}"
}
trap finalize_result EXIT

[[ -s "${PAYLOAD}" && -s "${RUNTIME}" ]] || { echo "missing inputs" >&2; exit 5; }
mkdir -p "${PAYLOAD_WORK}" "${RUNTIME_WORK}" "${RESULT}"
tar -xzf "${PAYLOAD}" -C "${PAYLOAD_WORK}"
tar -xzf "${RUNTIME}" -C "${RUNTIME_WORK}"
( cd "${PAYLOAD_WORK}" && sha256sum -c payload.sha256 > /dev/null )
( cd "${RUNTIME_WORK}" && sha256sum -c runtime.sha256 > /dev/null )
for expected in "width=${WIDTH}" "mass_GeV=${MASS}" "signal=${SIGNAL}" "rMax=${RMAX}"; do
    grep -Fxq "${expected}" "${PAYLOAD_WORK}/payload_provenance.txt" || {
        echo "SNAPSHOT_DIRECT_V2_INVALID provenance=${expected}" >&2; exit 8; }
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
FWD_AREA="${PERCAT}/ttbarfits_fwd2425_2x1_${SIGNAL}"
AREA="${SCRATCH}/direct_area/${SIGNAL}_area"
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

    M_ON="mask_cen_Cen24Pass_Region1=1,mask_cen_Cen25Pass_Region1=1,mask_fwd_Fwd24Pass_Region1=1,mask_fwd_Fwd25Pass_Region1=1"
    M_FRZ="mask_cen_Cen24Pass_Region1,mask_cen_Cen25Pass_Region1,mask_fwd_Fwd24Pass_Region1,mask_fwd_Fwd25Pass_Region1"

    combine -M MultiDimFit -d workspace.root -m 0 \
        --rMin 0 --rMax "${RMAX}" \
        --setParameters "r=0,${M_ON}" \
        --freezeParameters "r,${M_FRZ}" \
        --setParameterRanges 'rgx{.*rpf_par.*}=-50,50:rgx{.*rpf_par0}=0.001,50' \
        --cminDefaultMinimizerStrategy 2 --cminPreScan --cminPreFit 1 \
        --X-rtd MINIMIZER_MaxCalls=5000000 \
        --saveWorkspace --saveFitResult -n _maskedBonlyDirect \
        > direct_fit.log 2>&1
    python3 "${REPO}/run3/validate_fit_result.py" \
        multidimfit_maskedBonlyDirect.root --key fit_mdf \
        --min-cov-qual 3 --max-edm 0.01 > direct_fit_validation.log 2>&1

    python3 - <<'PY' > modelconfig_validation.log 2>&1
import ROOT
f = ROOT.TFile.Open("higgsCombine_maskedBonlyDirect.MultiDimFit.mH0.root")
w = f.Get("w")
mc = w.genobj("ModelConfig")
nuis = sorted(p.GetName() for p in mc.GetNuisanceParameters())
expected = sorted(["jes", "jer", "pileup", "pdf", "q2", "ttag_pt1",
                   "lumi24", "lumi25", "ttbar_xsec"])
if nuis != expected:
    raise RuntimeError(f"ModelConfig nuisances {nuis} != {expected}")
for name in expected:
    v = w.var(name)
    if not v or v.isConstant():
        raise RuntimeError(f"nuisance not floating: {name}")
print("MODELCONFIG CHECK: nine_nuisances_present_and_floating=1 status=0")
PY
)

for required in \
    "${AREA}/higgsCombine_maskedBonlyDirect.MultiDimFit.mH0.root" \
    "${AREA}/multidimfit_maskedBonlyDirect.root" \
    "${AREA}/direct_fit_validation.log" \
    "${AREA}/modelconfig_validation.log"; do
    [[ -s "${required}" ]] || { echo "SNAPSHOT_DIRECT_V2_INVALID missing=${required}" >&2; exit 12; }
done
echo "SNAPSHOT_DIRECT_V2_OK width=${WIDTH} mass=${MASS}"
