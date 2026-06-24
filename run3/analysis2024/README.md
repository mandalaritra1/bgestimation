# 2024 ttbar all-hadronic — 2DAlphabet workflow (reusable)

End-to-end recipe for the Run-3 **2024** ZPrime (1% width) all-hadronic resonance
search: F-test → goodness-of-fit → per-mass fits → combined blinded limits →
plots → impacts. All commands run from `src/bgestimation/` inside the
**combine / 2DAlphabet CMSSW environment** (on cmslpc; tmux session `ttbar`).

> Scope: **2024 only**. The legacy Run-2 scripts in the parent directory are not
> part of this workflow. Throwaway test outputs from development live in
> `../archive/`.

---

## 0. Key choices baked in (don't re-derive)

- **Transfer-function order = `2x1`** for both central and forward (F-test selected).
  Registered in `jsons/TransferFunctions.json` (`cen2024`, `fwd2024`).
- **Signal strength: r ≥ 0, rInit = 0.** Allowing r<0 / starting at r=1 caused fit
  failures. `ttbar.py` defaults are `--rMin 0 --rInit 0`; combine uses
  `--rMin 0 --setParameters r=0`.
- **lumi 109.95 fb⁻¹ (13.6 TeV)**; placeholder 2024 top-tag SF 0.90/tag; clamp-to-data
  floor on empty QCD cells (fixes forward GoF).
- **Mass grid capped at 6 TeV** — the m_tt window ends at 6500 GeV, so heavier
  resonances have ~no signal in range and AsymptoticLimits hangs.
- Per-mass runs write their **own project dir** (`output/ttbarfits_<cat>_2x1_<signal>/`)
  and **own runtime config** (`jsons/config/ttbar_<cat>__<signal>.json`), so masses
  can run in parallel without clobbering the shared `base.root` / racing on configs.

`$INPUT` below = the EOS clamp-to-data template directory:
```
INPUT=root://eosuser.cern.ch//eos/user/a/amandal/ttbarhad_root_files/2dAlphabetInputs
```

---

## 1. F-test — choose the TF order

```bash
# scan TF orders per region (produces ftest_results_*/ CSVs + FTest_*.png comparison plots)
python ttbar.py --cat cen2024 --scenario ZPrime_1 --signal ZPrime2000 --study ftest --tf <NxM> --input $INPUT --output output
# ... repeat over orders; results_ftest.py / fit_ftest.py assemble the CSV + plots.
```
Decision rule: step up while the lower→higher comparison has p < 0.05; stop where the
next order is no longer preferred. **Both regions → 2x1.**
Plots: `analysis2024/plots/ftest/` (the deciding `1x1→2x1` and `2x1→2x2` pairs).

## 2. Goodness of fit (blinded, masked signal window)

Saturated GoF, background-only, top-mass signal window masked, 200 toys, at 2x1.
Passes: **cen p=0.485, fwd p=0.180** (forward needs clamp-to-data).
Plots: `analysis2024/plots/gof/`.

## 3. Per-mass fits + per-region limits

Loop per mass (parallel, 4-wide). Each mass gets its own project dir.
```bash
run_one() {
  python ttbar.py --cat "$1" --scenario ZPrime_1 --signal ZPrime$2 \
    --study limit --input "$INPUT" --output output --rInit 0 --rMin 0 --rMax 6 \
    > "logs/$1_ZPrime$2.log" 2>&1 && echo "OK $1 $2" || echo "FAIL $1 $2"
}
export -f run_one; export INPUT; mkdir -p logs
for cat in cen2024 fwd2024; do
  for m in 1000 1200 1400 1600 1800 2000 2500 3000 3500 4000 4500 5000 6000; do echo "$cat $m"; done
done | xargs -P 4 -n 2 bash -c 'run_one "$0" "$1"'
```

## 4. Combine cen+fwd → blinded limits

```bash
bash combine_cards24.sh        # NPROC=4 parallel; combineCards -> text2workspace -> AsymptoticLimits --run blind
```
(For the eventual **observed** line, re-run without `--run blind` — that is UNBLINDING,
only after approval.)

## 5. Limit (brazil) plot

```bash
python plot_limits_mpl.py --year 2024 --signal ZPrime --width 1 --blind True --output limits --xmin 1 --xmax 6
```
→ `limits/limits_ZPrime1_2024_mpl.{png,pdf}`. Expected exclusion **≈ 5.32 TeV**.

## 6. Impacts (blinded, two-sided data-driven TF)

```bash
MODE=masked bash impacts24.sh signalZPrime3000      # two-sided TF via masked-snapshot Asimov
# MODE=apriori (default) is faster but rpf params come out one-sided
```
→ `output/cards_combined_24/signalZPrime3000_area/impacts_signalZPrime3000.pdf`.

## 7. Supporting plots for slides/docs

```bash
python plot_qcd_fail_2d.py                 # Fail-QCD colz 2D (TF input), cen+fwd
python plot_prefit_postfit_2d.py           # QCD Pass prefit vs postfit colz 2D
# postfit projections (data vs bkg in m_tt) are produced by --study plot:
for cat in cen2024 fwd2024; do
  python ttbar.py --cat $cat --scenario ZPrime_1 --signal ZPrime3000 --study plot --input $INPUT --output output
done
```

## 8. Collect everything + view

```bash
bash analysis2024/collect_plots.sh         # gather canonical plots -> analysis2024/plots/<category>/
python analysis2024/viewer/generate_viewer.py   # build the HTML plot viewer
open analysis2024/viewer/index.html        # (or: python -m http.server in viewer/ then browse)
```

---

## Script reference (in `src/bgestimation/`)

| script | purpose |
|--------|---------|
| `ttbar.py` | driver: workspace, ML fit, plots, per-region limit, GoF (`--study ftest/limit/plot/all`) |
| `combine_cards24.sh` | combine cen+fwd cards → blinded AsymptoticLimits per mass (parallel) |
| `plot_limits_mpl.py` | mplhep brazil-band limit plot |
| `impacts24.sh` | combined-workspace impacts; `MODE=apriori` / `MODE=masked` |
| `plot_qcd_fail_2d.py` | Fail-QCD colz 2D (transfer-function input distribution) |
| `plot_prefit_postfit_2d.py` | QCD Pass prefit vs postfit colz 2D |
| `analysis2024/collect_plots.sh` | gather canonical plots into `analysis2024/plots/` |
| `analysis2024/viewer/generate_viewer.py` | build the HTML plot viewer |

## TODO before unblinding / publication
- Measured 2024 GloParT-v3 top-tag SF (0.90 is a placeholder).
- Real theory xsec for interpolated masses (1.2/1.4 TeV interpolated).
- Recover 1.8/2.0 TeV limit points (HybridNew toys).
- Observed limits + full systematics, then unblind.
