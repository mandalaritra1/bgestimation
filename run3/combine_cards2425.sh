#!/bin/bash
# Combine the COMBINED-year central + forward cards into one card per signal mass,
# build the workspace, and run a BLINDED AsymptoticLimits. This is the FULL 24+25
# result: cen2425 (4 regions: Cen24/25 Pass/Fail) + fwd2425 (Fwd24/25 Pass/Fail)
# = 8 regions total, 4 of them signal-window Pass regions to mask for blinding.
# Output lands in output/cards_combined_2425/<signame>_area/.
#
# Same masked b-only snapshot method + floating ttagSF as combine_cards24/25.sh.
# The ttagSF is a SINGLE correlated rateParam across both years (2025 MC is the
# lumi-scaled 2024 MC, so they share the same placeholder top-tag SF).
#
# Prereq: run3/run_fit_2425.sh first, producing:
#   output/ttbarfits_{cen2425_2x2,fwd2425_2x1}_<signame>/<signame>_area/card.txt
#
# Run from src/bgestimation inside the combine/CMSSW env.
#   bash run3/combine_cards2425.sh           # 4 cores (default)

NPROC="${NPROC:-4}"
REPO_DIR="$PWD"

UNBLIND="${UNBLIND:-0}"
if [[ "$UNBLIND" == "1" ]]; then echo "*** UNBLINDED run (observed + expected) ***"; fi

# DEFAULT OFF — see combine_cards25.sh: the floating ttagSF on the signal-in-Pass is
# degenerate with r and kills low-mass limits. Top-tag SF uncertainty is carried by the
# per-cat `ttbar_xsec` 30% lnN + `ttag_pt1` shape. FLOAT_TTAGSF=1 restores the injection.
FLOAT_TTAGSF="${FLOAT_TTAGSF:-0}"
RMAX="${RMAX:-6}"

WIDTH="${WIDTH:-1}"
case "$WIDTH" in
    1)  TAG="" ;;
    10) TAG="_10" ;;
    30) TAG="_30" ;;
    *)  echo "Unknown WIDTH=$WIDTH (use 1|10|30)"; exit 1 ;;
esac

# TF orders: cen2425=2x2, fwd2425=2x1 (TransferFunctions.json).
CEN_BASE="output/ttbarfits_cen2425_2x2"
FWD_BASE="output/ttbarfits_fwd2425_2x1"
COMB_DIR="output/cards_combined_2425${COMB_SUFFIX:-}"

MASSES="${MASSES:-1000 1200 1400 1600 1800 2000 2500 3000 3500 4000 4500 5000 6000}"
SIGNALS=""
for m in $MASSES; do SIGNALS="$SIGNALS signalZPrime${m}${TAG}"; done

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
    local log="${area}/combine2425.log"

    {
        echo "=== ${sig}: combineCards (cen2425 + fwd2425) ==="
        combineCards.py cen="$cen_card" fwd="$fwd_card" > "$comb_card"

        if [[ "$FLOAT_TTAGSF" == "1" ]]; then
            echo "=== ${sig}: inject single correlated ttagSF rateParam (all Pass, both years) ==="
            {
                echo "ttagSF rateParam *Pass* 24_TTbar 1.0 [0.2,2.0]"
                echo "ttagSF rateParam *Pass* 25_TTbar 1.0 [0.2,2.0]"
                echo "ttagSF rateParam *Pass* 24_${sig} 1.0 [0.2,2.0]"
                echo "ttagSF rateParam *Pass* 25_${sig} 1.0 [0.2,2.0]"
            } >> "$comb_card"
        fi

        echo "=== ${sig}: text2workspace ==="
        text2workspace.py "$comb_card" -o "${area}/workspace.root" --channel-masks --X-no-jmax

        # FOUR Pass signal-window (Region1) masks: both years, both regions.
        M_ON="mask_cen_Cen24Pass_Region1=1,mask_cen_Cen25Pass_Region1=1,mask_fwd_Fwd24Pass_Region1=1,mask_fwd_Fwd25Pass_Region1=1"
        M_OFF="mask_cen_Cen24Pass_Region1=0,mask_cen_Cen25Pass_Region1=0,mask_fwd_Fwd24Pass_Region1=0,mask_fwd_Fwd25Pass_Region1=0"
        M_FRZ="mask_cen_Cen24Pass_Region1,mask_cen_Cen25Pass_Region1,mask_fwd_Fwd24Pass_Region1,mask_fwd_Fwd25Pass_Region1"
        if [[ "$UNBLIND" == "1" ]]; then
            echo "=== ${sig}: UNBLINDED AsymptoticLimits ==="
            ( cd "$area" && rm -f higgsCombine*.AsymptoticLimits.*.root && \
              combine -M AsymptoticLimits workspace.root --rMin 0 --rMax ${RMAX} --setParameters r=0 \
                --cminDefaultMinimizerStrategy 1 --rRelAcc 0.005 --rAbsAcc 1e-7 -v 0 )
        else
            echo "=== ${sig}: blinded expected limit via masked b-only snapshot ==="
            ( cd "$area" && rm -f higgsCombine*.AsymptoticLimits.*.root higgsCombine_maskedBonly*.root && \
              combine -M MultiDimFit -d workspace.root -m 0 --rMin 0 --rMax ${RMAX} \
                --setParameters r=0,${M_ON} --freezeParameters r,${M_FRZ} \
                --cminDefaultMinimizerStrategy 1 --cminPreScan --cminPreFit 1 \
                --setParameterRanges 'rgx{.*rpf_par.*}=-50,50' \
                --saveWorkspace --saveFitResult -n _maskedBonly > mdf.log 2>&1 && \
              python "${REPO_DIR}/run3/validate_fit_result.py" \
                multidimfit_maskedBonly.root --key fit_mdf --min-cov-qual 3 >> mdf.log 2>&1 && \
              combine -M AsymptoticLimits -d higgsCombine_maskedBonly.MultiDimFit.mH0.root \
                --snapshotName MultiDimFit --run blind --bypassFrequentistFit -m 0 \
                --setParameters ${M_OFF} --freezeParameters ${M_FRZ} \
                --rMin 0 --rMax ${RMAX} --cminDefaultMinimizerStrategy 0 \
                --rRelAcc 0.0005 --rAbsAcc 1e-9 -v 0 )
        fi
    } > "$log" 2>&1

    if ls "${area}"/higgsCombine*.AsymptoticLimits.*.root >/dev/null 2>&1; then
        echo "OK   ${sig}  (log: ${log})"
    else
        echo "FAIL ${sig}  -- see ${log}"
    fi
}
export -f process_signal
export CEN_BASE FWD_BASE COMB_DIR FLOAT_TTAGSF RMAX UNBLIND REPO_DIR

echo "Running ${NPROC} masses in parallel...  (WIDTH=${WIDTH}, FLOAT_TTAGSF=${FLOAT_TTAGSF}, UNBLIND=${UNBLIND})"
printf '%s\n' $SIGNALS | xargs -P "$NPROC" -I{} bash -c 'process_signal "$@"' _ {}

echo "DONE. Plot with:"
echo "  python plot_limits_mpl.py --year 2425 --signal ZPrime --width ${WIDTH} --blind True --output limits --xmin 1.2 --xmax 6 --lumi 220.54 --com 13.6 --norm onepb --ref-pb 1.0 --limit-dir ${COMB_DIR}"
