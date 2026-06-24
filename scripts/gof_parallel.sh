#!/usr/bin/env bash
# Parallel local saturated-GoF toys for one signal area (no condor, no tarball).
# Splits the toys across local cores, matching 2DAlphabet's toy command, then
# leaves higgsCombine_gof_toys.GoodnessOfFit.mH120.*.root in the area for
# scripts/gof_pvalue.py to read alongside the existing _gof_data file.
#
# Usage: bash scripts/gof_parallel.sh <area_dir> [ntoys_total] [njobs]
set -u
AREA="$1"; NTOTAL="${2:-100}"; NJOBS="${3:-10}"
PER=$(( (NTOTAL + NJOBS - 1) / NJOBS ))

cd "$AREA" || { echo "no such area: $AREA"; exit 1; }
[ -f card.txt ] || { echo "no card.txt in $AREA"; exit 1; }
echo "Area: $AREA"
echo "Launching $NJOBS jobs x $PER toys (= $((NJOBS*PER)) toys) ..."
rm -f higgsCombine_gof_toys.GoodnessOfFit.mH120.*.root gof_toys_*.log

for s in $(seq 1 "$NJOBS"); do
  combine -M GoodnessOfFit -d card.txt --algo=saturated -n _gof_toys -v 0 \
    --toysFrequentist -t "$PER" -s "$s" > "gof_toys_${s}.log" 2>&1 &
done
wait

n=$(ls higgsCombine_gof_toys.GoodnessOfFit.mH120.*.root 2>/dev/null | wc -l)
echo "DONE: produced $n toy files"
