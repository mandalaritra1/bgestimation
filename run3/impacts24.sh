#!/bin/bash
# Systematic impact plot on the COMBINED 2024 workspace, BLINDED (Asimov dataset).
# Impacts are a per-mass diagnostic -- run it for one representative mass (default
# 3 TeV), not the whole grid.
#
#   bash impacts24.sh                          # signalZPrime3000, MODE=apriori
#   bash impacts24.sh signalZPrime2500         # another mass
#   bash impacts24.sh signalZPrime3000 0       # background-only Asimov (expectSignal=0)
#   MODE=masked bash impacts24.sh              # two-sided TF impacts (see below)
#
# MODE (env var):
#   apriori (default): a-priori Asimov (--bypassFrequentistFit). Fast & robust, but
#     the UNCONSTRAINED rpf (TF) params come out ONE-SIDED, because the Asimov sits
#     at the prefit TF point where the polynomial directions are partly degenerate.
#   masked: two-sided TF impacts, still blinded. Two stages:
#     (1) b-only MultiDimFit to DATA with the Pass signal window (Region1) masked
#         -> snapshot pins the TF params at their DATA-DRIVEN values (signal region
#         never seen -> blinded);
#     (2) impacts on an Asimov generated FROM that snapshot (--snapshotName +
#         --bypassFrequentistFit, so no re-fit to data -> stays blinded), full
#         regions present so r is constrained -> rpf impacts come out TWO-SIDED.
#   NOTE: MODE=masked is the publication-quality path but is NOT testable outside
#   the combine env (custom RooParametricHist2D). Validate on a single mass first.
#
# Prereq: combine_cards24.sh has built output/cards_combined_24/<SIG>_area/workspace.root
# Run from src/bgestimation in the combine/CMSSW env.
set -e

SIG="${1:-signalZPrime3000}"
EXPECTSIG="${2:-1}"
NPROC="${NPROC:-4}"          # parallel per-nuisance fits (the slow step)
MODE="${MODE:-apriori}"
AREA="output/cards_combined_24/${SIG}_area"

# Pass signal-window channels to mask in the blinded b-only fit (MODE=masked).
MASKS="mask_cen_Cen24Pass_Region1=1,mask_fwd_Fwd24Pass_Region1=1"
FREEZE_MASKS="mask_cen_Cen24Pass_Region1,mask_fwd_Fwd24Pass_Region1"

if [[ ! -f "${AREA}/workspace.root" ]]; then
    echo "No ${AREA}/workspace.root -- run combine_cards24.sh first."; exit 1
fi
echo "Impacts for ${SIG}  (MODE=${MODE}, expectSignal=${EXPECTSIG})"

cd "$AREA"
rm -f *_paramFit_*.root *_initialFit_*.root

# Common knobs. Bound the unconstrained rpf params so robustFit converges (default
# range +/-1000 makes it wander/hang; +/-100 is wide enough that no param piles up
# on the bound). Exclude the hundreds of per-bin QCD params.
# Array form so the regexes (* {} =) are passed literally, not glob-expanded.
COMMON=( -m 0 --rMin 0 --rMax 6
  --cminDefaultMinimizerStrategy 0 --cminDefaultMinimizerTolerance 0.1
  --robustFit 1
  --setParameterRanges 'rgx{.*rpf_par.*}=-100,100'
  --X-rtd MINIMIZER_freezeDisassociatedParams
  --exclude 'rgx{.*_bin_.*}' )

if [[ "$MODE" == "masked" ]]; then
    # --- Stage 1: blinded b-only fit to data -> data-driven TF snapshot ----------
    echo "=== Stage 1: masked b-only fit (snapshot) ==="
    combine -M MultiDimFit -d workspace.root -m 0 --rMin 0 --rMax 6 \
        --setParameters r=0,${MASKS} \
        --freezeParameters r,${FREEZE_MASKS} \
        --cminDefaultMinimizerStrategy 0 \
        --setParameterRanges 'rgx{.*rpf_par.*}=-50,50' \
        --saveWorkspace -n _maskedBonly
    SNAP="higgsCombine_maskedBonly.MultiDimFit.mH0.root"
    # Asimov is generated FROM the snapshot (data-driven TF, no data re-fit). The
    # snapshot carries mask=1 from Stage 1, so we explicitly UNMASK here: the Asimov
    # is synthetic, so including the signal window does NOT unblind, and it lets r be
    # properly constrained (otherwise sigma(r) is inflated by the masked region).
    DCARD=( -d "$SNAP" --snapshotName MultiDimFit
            -t -1 --expectSignal "${EXPECTSIG}" --bypassFrequentistFit
            --setParameters mask_cen_Cen24Pass_Region1=0,mask_fwd_Fwd24Pass_Region1=0
            --freezeParameters mask_cen_Cen24Pass_Region1,mask_fwd_Fwd24Pass_Region1 )
else
    # --- a-priori Asimov (default): blinded via --bypassFrequentistFit -----------
    DCARD=( -d workspace.root
            -t -1 --expectSignal "${EXPECTSIG}" --bypassFrequentistFit )
fi

OPTS=( -M Impacts "${DCARD[@]}" "${COMMON[@]}" )

echo "=== Step 1/3: initial fit ===";      combineTool.py "${OPTS[@]}" --doInitialFit
echo "=== Step 2/3: per-nuisance fits (${NPROC} parallel) ==="; combineTool.py "${OPTS[@]}" --doFits --parallel "${NPROC}"
echo "=== Step 3/3: collect + plot ===";    combineTool.py "${OPTS[@]}" -o impacts.json
plotImpacts.py -i impacts.json -o "impacts_${SIG}"

echo "DONE -> ${AREA}/impacts_${SIG}.pdf"
