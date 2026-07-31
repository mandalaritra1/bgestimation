#!/bin/bash
# Combine the 2025 central + forward per-region cards into one card per signal
# mass, build the workspace, and run a BLINDED AsymptoticLimits. Output lands in
# output/cards_combined_25/<signame>_area/ so that plot_limits_mpl.py can find it.
#
# Identical method to combine_cards24.sh (masked b-only snapshot -> Asimov, floating
# ttagSF rateParam) so the 2025 limit is apples-to-apples with 2024. Only the
# year-specific dir/region/process names change (cen2025=2x2, fwd2025=2x1; regions
# Cen25Pass/Fwd25Pass; MC processes 25_TTbar/25_<sig>).
#
# Prereq: run3/run_fit_2025.sh first (per-region cards must exist), at:
#   output/ttbarfits_{cen2025_2x2,fwd2025_2x1}_<signame>/<signame>_area/card.txt
#
# Run from src/bgestimation inside the combine/CMSSW env.
#   bash run3/combine_cards25.sh           # 4 cores (default)
#   NPROC=8 bash run3/combine_cards25.sh   # override

NPROC="${NPROC:-4}"

# UNBLINDING SWITCH. Default blinded (expected-only). UNBLIND=1 also computes the
# OBSERVED limit (conveners' approval required).
UNBLIND="${UNBLIND:-0}"
if [[ "$UNBLIND" == "1" ]]; then BLIND_OPT=""; echo "*** UNBLINDED run (observed + expected) ***";
else BLIND_OPT="--run blind"; fi

# FLOATING TOP-TAG SF — DEFAULT OFF. The freely-floating ttagSF rateParam [0.2,2.0] on
# the tagged signal in Pass is DEGENERATE with r (both scale the signal-in-Pass), and at
# low mass — where the signal sits on the ttbar bulk that pins ttagSF — that degeneracy
# washes out the r constraint and AsymptoticLimits cannot bracket the limit (silent empty
# trees at 1.4/1.6 TeV). The top-tag SF uncertainty is instead carried by the per-cat
# cards' `ttbar_xsec` 30% lnN (rate) + `ttag_pt1` shape nuisance. Set FLOAT_TTAGSF=1 to
# restore the old injection (ttbar+signal Pass rateParam).
FLOAT_TTAGSF="${FLOAT_TTAGSF:-0}"

# rMax for AsymptoticLimits (1% -> r=1<->as-run, r~O(1)).
RMAX="${RMAX:-6}"

# WIDTH selector: 1 (default), 10, or 30.
WIDTH="${WIDTH:-1}"
case "$WIDTH" in
    1)  TAG="" ;;
    10) TAG="_10" ;;
    30) TAG="_30" ;;
    *)  echo "Unknown WIDTH=$WIDTH (use 1|10|30)"; exit 1 ;;
esac

# Per-mass project dirs: TF orders are cen2025=2x2, fwd2025=2x1 (TransferFunctions.json).
CEN_BASE="output/ttbarfits_cen2025_2x2"
FWD_BASE="output/ttbarfits_fwd2025_2x1"
COMB_DIR="output/cards_combined_25${COMB_SUFFIX:-}"

MASSES="${MASSES:-1000 1200 1400 1600 1800 2000 2500 3000 3500 4000 4500 5000 6000}"
SIGNALS=""
for m in $MASSES; do SIGNALS="$SIGNALS signalZPrime${m}${TAG}"; done

# --- one mass: combineCards -> text2workspace -> blinded AsymptoticLimits -------
process_signal() {
    local sig="$1"
    local cen_card="${CEN_BASE}_${sig}/${sig}_area/card.txt"
    local fwd_card="${FWD_BASE}_${sig}/${sig}_area/card.txt"
    if [[ ! -f "$cen_card" || ! -f "$fwd_card" ]]; then
        echo "SKIP ${sig}: missing per-region card ($cen_card or $fwd_card)"
        return 0
    fi

    local area="${COMB_DIR}/${sig}_area"
    mkdir -p "$area"
    local comb_card="${area}/${sig}_card_combined.txt"
    local log="${area}/combine25.log"

    {
        echo "=== ${sig}: combineCards ==="
        combineCards.py cen="$cen_card" fwd="$fwd_card" > "$comb_card"

        if [[ "$FLOAT_TTAGSF" == "1" ]]; then
            echo "=== ${sig}: inject freely-floating ttagSF rateParam (Pass regions) ==="
            {
                echo "ttagSF rateParam *Pass* 25_TTbar 1.0 [0.2,2.0]"
                echo "ttagSF rateParam *Pass* 25_${sig} 1.0 [0.2,2.0]"
            } >> "$comb_card"
        fi

        echo "=== ${sig}: text2workspace ==="
        text2workspace.py "$comb_card" -o "${area}/workspace.root" --channel-masks --X-no-jmax

        # Pass signal window (Region1) masks (workspace built with --channel-masks).
        MASK_ON="mask_cen_Cen25Pass_Region1=1,mask_fwd_Fwd25Pass_Region1=1"
        MASK_OFF="mask_cen_Cen25Pass_Region1=0,mask_fwd_Fwd25Pass_Region1=0"
        MASK_FRZ="mask_cen_Cen25Pass_Region1,mask_fwd_Fwd25Pass_Region1"
        if [[ "$UNBLIND" == "1" ]]; then
            echo "=== ${sig}: UNBLINDED AsymptoticLimits ==="
            ( cd "$area" && rm -f higgsCombine*.AsymptoticLimits.*.root && \
              combine -M AsymptoticLimits workspace.root --rMin 0 --rMax ${RMAX} --setParameters r=0 \
                --cminDefaultMinimizerStrategy 1 --rRelAcc 0.005 --rAbsAcc 1e-7 -v 0 )
        else
            echo "=== ${sig}: blinded expected limit via masked b-only snapshot ==="
            # (1) b-only fit to DATA with the Pass signal window masked -> data-driven TF
            # snapshot (SR never seen); (2) AsymptoticLimits with the Asimov built FROM
            # that snapshot. (Same fix as 2024: avoids prefit-TF Asimov band instability.)
            ( cd "$area" && rm -f higgsCombine*.AsymptoticLimits.*.root higgsCombine_maskedBonly*.root && \
              combine -M MultiDimFit -d workspace.root -m 0 --rMin 0 --rMax ${RMAX} \
                --setParameters r=0,${MASK_ON} --freezeParameters r,${MASK_FRZ} \
                --cminDefaultMinimizerStrategy 0 --setParameterRanges 'rgx{.*rpf_par.*}=-50,50' \
                --saveWorkspace -n _maskedBonly > mdf.log 2>&1 && \
              combine -M AsymptoticLimits -d higgsCombine_maskedBonly.MultiDimFit.mH0.root \
                --snapshotName MultiDimFit --run blind --bypassFrequentistFit -m 0 \
                --setParameters ${MASK_OFF} --freezeParameters ${MASK_FRZ} \
                --rMin 0 --rMax ${RMAX} --cminDefaultMinimizerStrategy 1 --rRelAcc 0.005 --rAbsAcc 1e-7 -v 0 )
        fi
    } > "$log" 2>&1

    if ls "${area}"/higgsCombine*.AsymptoticLimits.*.root >/dev/null 2>&1; then
        echo "OK   ${sig}  (log: ${log})"
    else
        echo "FAIL ${sig}  -- see ${log}"
    fi
}
export -f process_signal
export CEN_BASE FWD_BASE COMB_DIR BLIND_OPT FLOAT_TTAGSF RMAX

echo "Running ${NPROC} masses in parallel...  (WIDTH=${WIDTH}, FLOAT_TTAGSF=${FLOAT_TTAGSF}, UNBLIND=${UNBLIND})"
printf '%s\n' $SIGNALS | xargs -P "$NPROC" -I{} bash -c 'process_signal "$@"' _ {}

echo "DONE. Plot with:"
echo "  python plot_limits_mpl.py --year 2025 --signal ZPrime --width ${WIDTH} --blind True --output limits --xmin 1 --xmax 6 --lumi 110.59 --limit-dir ${COMB_DIR}"
