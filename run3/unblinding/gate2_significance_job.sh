#!/bin/bash
# GATE 2 EXCESS PROTOCOL — asymptotic significance (q0, r >= 0) + best-fit r,
# ONLY at the six pre-identified protocol points (3.5/4 TeV, hard-guarded).
# Runs on the Gate-2 unmasked b-only snapshot. Interlock: last argument must
# be the literal GATE2-EXCESS-PROTOCOL.
set -euo pipefail

if [[ "$#" -ne 5 ]]; then
    echo "usage: $0 <mode> <width> <mass_GeV> <rMax> GATE2-EXCESS-PROTOCOL" >&2
    exit 2
fi
MODE="$1"
WIDTH="$2"
MASS="$3"
RMAX="$4"
INTERLOCK="$5"
case "${MODE}" in gate2_significance) ;; *) echo "bad mode" >&2; exit 4 ;; esac
case "${WIDTH}" in 1|10|30) ;; *) echo "bad width" >&2; exit 3 ;; esac
# Pre-registered restriction: significance ONLY at the protocol points.
case "${MASS}" in 3500|4000) ;; *) echo "mass ${MASS} is not an excess-protocol point" >&2; exit 3 ;; esac
[[ "${INTERLOCK}" == "GATE2-EXCESS-PROTOCOL" ]] || {
    echo "GATE2_SIG_INTERLOCK: excess protocol not confirmed" >&2
    exit 90
}

SCRATCH="${_CONDOR_SCRATCH_DIR:?missing _CONDOR_SCRATCH_DIR}"
GATE2_ARCHIVE="${SCRATCH}/w${WIDTH}_m${MASS}.tgz"
RUNTIME="${SCRATCH}/workspace_runtime_overlay_20260811_v1.tgz"
RUNTIME_WORK="${SCRATCH}/sig_runtime"
AREA="${SCRATCH}/sig_area"
RESULT="${SCRATCH}/gate2_sig_result"
RESULT_ARCHIVE="${SCRATCH}/gate2_sig_result.tgz"
CMSSW_VERSION="${CMSSW_VERSION:-CMSSW_14_1_0_pre4}"
SCRAM_ARCH="${SCRAM_ARCH:-el9_amd64_gcc12}"

finalize_result() {
    local rc=$?
    trap - EXIT
    set +e
    mkdir -p "${RESULT}"
    for f in "${AREA}"/sig.log "${AREA}"/rhat.log \
             "${AREA}"/higgsCombine_gate2sig.Significance.mH0*.root \
             "${AREA}"/higgsCombine_gate2rhat.MultiDimFit.mH0*.root \
             "${AREA}"/multidimfit_gate2rhat.root; do
        [[ -f "$f" ]] && cp -a "$f" "${RESULT}/"
    done
    {
        echo "campaign=gate2_significance"
        echo "exit_code=${rc}"
        [[ "${rc}" -eq 0 ]] && echo "status=success" || echo "status=failure"
        echo "width=${WIDTH}"
        echo "mass_GeV=${MASS}"
        echo "rMax=${RMAX}"
        echo "scope=asymptotic_q0_r_ge_0_plus_rhat_protocol_points_only"
    } > "${RESULT}/diagnostic.status"
    tar -C "${SCRATCH}" -czf "${RESULT_ARCHIVE}" "$(basename "${RESULT}")"
    echo "GATE2_SIG_DONE rc=${rc}"
    exit "${rc}"
}
trap finalize_result EXIT

[[ -s "${GATE2_ARCHIVE}" && -s "${RUNTIME}" ]] || { echo "missing inputs" >&2; exit 5; }
mkdir -p "${RUNTIME_WORK}" "${AREA}" "${RESULT}"
tar -xzf "${GATE2_ARCHIVE}" -C "${SCRATCH}"
SNAPSHOT="${SCRATCH}/gate2_observed_result/artifacts/higgsCombine_maskedBonlyDirect.MultiDimFit.mH0.root"
[[ -s "${SNAPSHOT}" ]] || { echo "missing Gate-2 snapshot" >&2; exit 6; }
grep -Fxq "status=success" "${SCRATCH}/gate2_observed_result/diagnostic.status" || {
    echo "upstream Gate-2 point not successful" >&2; exit 7; }
grep -Fxq "fit=direct_UNMASKED_bonly_all_nine_nuisances_floating" \
    "${SCRATCH}/gate2_observed_result/diagnostic.status" || {
    echo "snapshot is not the unmasked Gate-2 fit" >&2; exit 7; }
tar -xzf "${RUNTIME}" -C "${RUNTIME_WORK}"
( cd "${RUNTIME_WORK}" && sha256sum -c runtime.sha256 > /dev/null )

source /cvmfs/cms.cern.ch/cmsset_default.sh
export SCRAM_ARCH
cd "${SCRATCH}"
scramv1 project CMSSW "${CMSSW_VERSION}" > /dev/null 2>&1
cp -a "${RUNTIME_WORK}/." "${SCRATCH}/${CMSSW_VERSION}/"
cd "${SCRATCH}/${CMSSW_VERSION}"
eval "$(scram runtime -sh)"
cd "${AREA}"

M_OFF="mask_cen_Cen24Pass_Region1=0,mask_cen_Cen25Pass_Region1=0,mask_fwd_Fwd24Pass_Region1=0,mask_fwd_Fwd25Pass_Region1=0"
M_FRZ="mask_cen_Cen24Pass_Region1,mask_cen_Cen25Pass_Region1,mask_fwd_Fwd24Pass_Region1,mask_fwd_Fwd25Pass_Region1"

combine -M Significance -d "${SNAPSHOT}" --snapshotName MultiDimFit -m 0 \
    --rMin 0 --rMax "${RMAX}" \
    --setParameters "${M_OFF}" --freezeParameters "${M_FRZ}" \
    --setParameterRanges 'rgx{.*rpf_par.*}=-50,50:rgx{.*rpf_par0}=0.001,50' \
    --cminDefaultMinimizerStrategy 0 --X-rtd MINIMIZER_MaxCalls=5000000 \
    -n _gate2sig > sig.log 2>&1

combine -M MultiDimFit -d "${SNAPSHOT}" --snapshotName MultiDimFit -m 0 \
    --algo singles --rMin 0 --rMax "${RMAX}" \
    --setParameters "${M_OFF}" --freezeParameters "${M_FRZ}" \
    --setParameterRanges 'rgx{.*rpf_par.*}=-50,50:rgx{.*rpf_par0}=0.001,50' \
    --robustFit 1 \
    --cminDefaultMinimizerStrategy 0 --X-rtd MINIMIZER_MaxCalls=5000000 \
    --saveFitResult -n _gate2rhat > rhat.log 2>&1

ls higgsCombine_gate2sig.Significance.mH0*.root > /dev/null
ls higgsCombine_gate2rhat.MultiDimFit.mH0*.root > /dev/null
echo "GATE2_SIG_OK w=${WIDTH} m=${MASS}"
