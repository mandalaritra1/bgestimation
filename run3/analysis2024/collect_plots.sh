#!/bin/bash
# Collect the canonical 2024 result plots from their scattered output locations
# into analysis2024/plots/<category>/ with clean, stable names. Idempotent.
#
#   bash analysis2024/collect_plots.sh        # (run from src/bgestimation OR anywhere)
#
# Benchmark signal for per-mass plots (impacts, prefit/postfit, projections): 3 TeV.
set -u

# Resolve to the bgestimation root (parent of this script's dir) regardless of cwd.
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
cd "$ROOT"
P="$HERE/plots"

mkdir -p "$P"/{ftest,gof,limits,impacts,transfer_functions,prefit_postfit,projections}

cp_ () {  # cp_ <src> <dst>   -- copy if src exists, else warn
  if [[ -f "$1" ]]; then cp -f "$1" "$2"; echo "  + $(basename "$2")";
  else echo "  ! MISSING $1"; fi
}
pdf2png () { [[ -f "$1" ]] && pdftoppm -png -r 200 -singlefile "$1" "${2%.png}" 2>/dev/null && echo "  + $(basename "$2")" || echo "  ! MISSING $1"; }

FT=ftest_results_zprime2000_r0to6
echo "[ftest]"
cp_ "$FT/FTest_1x1_2x1_2024_cen.png" "$P/ftest/ftest_cen_1x1_to_2x1.png"
cp_ "$FT/FTest_2x1_2x2_2024_cen.png" "$P/ftest/ftest_cen_2x1_to_2x2.png"
cp_ "$FT/FTest_1x1_2x1_2024_fwd.png" "$P/ftest/ftest_fwd_1x1_to_2x1.png"
cp_ "$FT/FTest_2x1_2x2_2024_fwd.png" "$P/ftest/ftest_fwd_2x1_to_2x2.png"
cp_ "$FT/FTest_pairwise_results_2024.pdf" "$P/ftest/ftest_all_pairwise.pdf"

echo "[gof]"
cp_ "ftest_zprime2000_r0to6/2024/cen/ttbarfits_cen2024_ftest2x1/ttbar-signalZPrime2000_area/gof_plot_masked_2000.png" "$P/gof/gof_cen_2x1.png"
cp_ "output_clamp_fwd_zprime2000_r0to6/ttbarfits_fwd2024_ftest2x1/ttbar-signalZPrime2000_area/gof_plot_masked_2000.png" "$P/gof/gof_fwd_2x1_clamp.png"

echo "[limits]"
cp_ "limits/limits_ZPrime1_2024_mpl.png" "$P/limits/limits_zprime_1pct.png"
cp_ "limits/limits_ZPrime1_2024_mpl.pdf" "$P/limits/limits_zprime_1pct.pdf"

echo "[impacts]"
pdf2png "output/cards_combined_24/signalZPrime3000_area/impacts_signalZPrime3000.pdf" "$P/impacts/impacts_zprime3000.png"
cp_ "output/cards_combined_24/signalZPrime3000_area/impacts_signalZPrime3000.pdf" "$P/impacts/impacts_zprime3000.pdf"

echo "[transfer_functions]"
cp_ "qcd_fail_2d/qcd_fail_2d_cen2024.png" "$P/transfer_functions/qcd_fail_2d_cen.png"
cp_ "qcd_fail_2d/qcd_fail_2d_fwd2024.png" "$P/transfer_functions/qcd_fail_2d_fwd.png"

echo "[prefit_postfit]"
for s in cen fwd; do for st in prefit postfit; do
  cp_ "prefit_postfit_2d/QCD_Pass_${st}_${s}2024.png" "$P/prefit_postfit/qcd_pass_${st}_${s}.png"
done; done

echo "[projections]"
cp_ "slide_plots/postfit_projy_cen2024_300dpi.png" "$P/projections/postfit_projy_cen.png"
cp_ "slide_plots/postfit_projy_fwd2024_300dpi.png" "$P/projections/postfit_projy_fwd.png"

echo "DONE -> $P"
