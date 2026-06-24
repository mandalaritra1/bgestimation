#!/bin/bash
# Combine the 2024 central + forward per-region cards into one card per signal
# mass, build the workspace, and run a BLINDED AsymptoticLimits. Output lands in
# output/cards_combined_24/<signame>_area/ so that plot_limits.py can find it.
#
# Runs NPROC masses in parallel by default (each mass is independent). Per-mass
# stdout/stderr goes to <area>/combine24.log so the parallel streams don't
# interleave on the terminal.
#
# Prereq: the per-region cards must already exist (run ttbar.py --study limit for
#   cat=cen2024 and cat=fwd2024 first), at:
#   output/ttbarfits_{cen,fwd}2024_2x1_<signame>/<signame>_area/card.txt
#
# Run from src/bgestimation inside the combine/CMSSW env.
#   bash combine_cards24.sh           # 4 cores (default)
#   NPROC=8 bash combine_cards24.sh   # override

NPROC="${NPROC:-4}"

# UNBLINDING SWITCH. Default blinded (expected-only). Set UNBLIND=1 to also
# compute the OBSERVED limit (drops --run blind, fits the real signal-window
# data). Only do this with conveners' approval to unblind.
UNBLIND="${UNBLIND:-0}"
if [[ "$UNBLIND" == "1" ]]; then BLIND_OPT=""; echo "*** UNBLINDED run (observed + expected) ***";
else BLIND_OPT="--run blind"; fi

# FLOATING TOP-TAG SF. Default ON: inject a single freely-floating rateParam
# `ttagSF` on the tagged MC (ttbar + signal) in the Pass regions, so the fit
# determines the effective top-tag SF from data instead of trusting the baked-in
# flat-0.90 placeholder. The high-stats ttbar Pass pins it, breaking the
# r-degeneracy. Set FLOAT_TTAGSF=0 to reproduce the old (placeholder-trusting) limit.
FLOAT_TTAGSF="${FLOAT_TTAGSF:-1}"

# rMax for AsymptoticLimits. Default 6 (1% with r=1<->as-run, r~O(1)). For 10/30
# with r=1<->1fb, r95 reaches ~1e3-1e4 at low mass, so pass a large RMAX, e.g.
# RMAX=200000.
RMAX="${RMAX:-6}"

# WIDTH selector: 1 (default), 10, or 30. Picks the per-mass signal tag and the
# matching mass grid. ttbar.py names single-signal project dirs by the full signal
# name (signalZPrime<mass>[_<width>]), so the per-region card path just needs the tag.
WIDTH="${WIDTH:-1}"
case "$WIDTH" in
    1)  TAG="" ;;
    10) TAG="_10" ;;
    30) TAG="_30" ;;
    *)  echo "Unknown WIDTH=$WIDTH (use 1|10|30)"; exit 1 ;;
esac

# Per-mass project dirs: ttbar.py appends the signal name to the project dir for
# single-signal runs, so each mass has its own intact base.root.
CEN_BASE="output/ttbarfits_cen2024_2x1"
FWD_BASE="output/ttbarfits_fwd2024_2x1"
# COMB_SUFFIX lets two variants (e.g. with/without the floating ttagSF) coexist
# in separate output dirs without clobbering each other.
COMB_DIR="output/cards_combined_24${COMB_SUFFIX:-}"

# ZPrime mass grid. Capped at 6 TeV: the m_tt fit window ends at 6500 GeV, so
# resonances >~6.5 TeV (7000/8000/9000) have ~no signal in-range and the limit
# hangs. Theory xsec for 1200/1400/1800 are log interpolations. Same grid for all
# widths (the 10/30 NanoAOD samples exist at every point).
MASSES="1000 1200 1400 1600 1800 2000 2500 3000 3500 4000 4500 5000 6000"
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
    local log="${area}/combine24.log"

    {
        echo "=== ${sig}: combineCards ==="
        # combineCards.py rewrites each region card's relative shape paths to absolute.
        combineCards.py cen="$cen_card" fwd="$fwd_card" > "$comb_card"

        if [[ "$FLOAT_TTAGSF" == "1" ]]; then
            echo "=== ${sig}: inject freely-floating ttagSF rateParam (Pass regions) ==="
            # One correlated rateParam on tagged MC (ttbar + this signal) in the Pass
            # regions only. *Pass* matches cen_*Pass_Region* and fwd_*Pass_Region*
            # (robust to Cen24Pass vs Cen2024Pass naming). Range [0.2,2.0] easily
            # covers any plausible per-jet SF correction on top of the baked-in 0.90.
            {
                echo "ttagSF rateParam *Pass* 24_TTbar 1.0 [0.2,2.0]"
                echo "ttagSF rateParam *Pass* 24_${sig} 1.0 [0.2,2.0]"
            } >> "$comb_card"
        fi

        echo "=== ${sig}: text2workspace ==="
        text2workspace.py "$comb_card" -o "${area}/workspace.root" --channel-masks --X-no-jmax

        # Pass signal window (Region1) masks (workspace built with --channel-masks).
        MASK_ON="mask_cen_Cen24Pass_Region1=1,mask_fwd_Fwd24Pass_Region1=1"
        MASK_OFF="mask_cen_Cen24Pass_Region1=0,mask_fwd_Fwd24Pass_Region1=0"
        MASK_FRZ="mask_cen_Cen24Pass_Region1,mask_fwd_Fwd24Pass_Region1"
        if [[ "$UNBLIND" == "1" ]]; then
            echo "=== ${sig}: UNBLINDED AsymptoticLimits ==="
            ( cd "$area" && rm -f higgsCombine*.AsymptoticLimits.*.root && \
              combine -M AsymptoticLimits workspace.root --rMin 0 --rMax ${RMAX} --setParameters r=0 \
                --cminDefaultMinimizerStrategy 1 --rRelAcc 0.005 --rAbsAcc 1e-7 -v 0 )
        else
            echo "=== ${sig}: blinded expected limit via masked b-only snapshot ==="
            # Proper blinded expected limit: (1) b-only fit to DATA with the Pass signal
            # window masked -> data-driven TF snapshot (SR never seen); (2) AsymptoticLimits
            # with the Asimov built FROM that snapshot. Using the raw workspace + --run blind
            # instead builds the Asimov from the PREFIT TF, which made the expected median and
            # -1/-2 sigma bands unstable (collapse/dips at 1.8-2.5 TeV). -m 0 throughout.
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

# --- run NPROC at a time --------------------------------------------------------
echo "Running ${NPROC} masses in parallel...  (WIDTH=${WIDTH}, FLOAT_TTAGSF=${FLOAT_TTAGSF}, UNBLIND=${UNBLIND})"
printf '%s\n' $SIGNALS | xargs -P "$NPROC" -I{} bash -c 'process_signal "$@"' _ {}

echo "DONE. Plot with:"
echo "  python plot_limits_mpl.py --year 2024 --signal ZPrime --width ${WIDTH} --blind True --output limits --xmin 1 --xmax 6"
