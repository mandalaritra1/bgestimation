#!/usr/bin/env bash
# Blind saturated GoF with the m_top signal window (Pass Region1) masked,
# matching the Run2 procedure (Fig. 14: "m_top signal region is masked").
# Local parallel toys (no condor). Produces a plotGof.py PNG with the p-value.
#
# Usage: bash scripts/gof_masked.sh <area_dir> <mass> [ntoys] [njobs]
set -u
AREA="$1"; MASS="$2"; NTOTAL="${3:-200}"; NJOBS="${4:-20}"
PER=$(( (NTOTAL + NJOBS - 1) / NJOBS ))

cd "$AREA" || { echo "no area $AREA"; exit 1; }
[ -f card.txt ] || { echo "no card.txt in $AREA"; exit 1; }

echo "[1/5] Building channel-mask workspace..."
text2workspace.py card.txt -o workspace_masked.root --channel-masks > t2w.log 2>&1 || { echo "text2workspace failed; see $AREA/t2w.log"; exit 1; }

# Mask the m_top signal window = Pass Region1 channels.
MASKS=$(python -c '
import ROOT
w = ROOT.TFile("workspace_masked.root").Get("w")
items = []
for v in ROOT.RooArgList(w.allVars()):
    n = v.GetName()
    if n.startswith("mask_") and "Pass" in n and "Region1" in n:
        items.append(n + "=1")
print(",".join(items))')
if [ -z "$MASKS" ]; then echo "no Pass Region1 masks found in workspace"; exit 1; fi
echo "      masking: $MASKS"

RANGE="--setParameterRanges r=-5,5"

echo "[2/5] Data GoF (signal window masked)..."
combine -M GoodnessOfFit -d workspace_masked.root --algo saturated -n _gofmask_data -m "$MASS" \
  $RANGE --setParameters "$MASKS" > gofmask_data.log 2>&1

echo "[3/5] Toys: $NJOBS jobs x $PER (= $((NJOBS*PER))) ..."
rm -f higgsCombine_gofmask_toys.GoodnessOfFit.mH${MASS}.*.root gofmask_toys_*.log
for s in $(seq 1 "$NJOBS"); do
  combine -M GoodnessOfFit -d workspace_masked.root --algo saturated -n _gofmask_toys -m "$MASS" \
    $RANGE --setParameters "$MASKS" --toysFrequentist -t "$PER" -s "$s" > "gofmask_toys_${s}.log" 2>&1 &
done
wait

echo "[4/5] Collecting..."
combineTool.py -M CollectGoodnessOfFit \
  --input higgsCombine_gofmask_data.GoodnessOfFit.mH${MASS}.root higgsCombine_gofmask_toys.GoodnessOfFit.mH${MASS}.*.root \
  -m "$MASS" -o gofmask.json > collect.log 2>&1

echo "[5/5] Plotting..."
plotGof.py gofmask.json --statistic saturated --mass "${MASS}.0" \
  -o gof_plot_masked_${MASS} --title-right="m_{top} sideband, signal masked" > plotgof.log 2>&1

echo "DONE"
ls -la gof_plot_masked_${MASS}.* 2>/dev/null
echo "PNG: $AREA/gof_plot_masked_${MASS}.png"
