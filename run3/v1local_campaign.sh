#!/bin/bash
# Local v1 combined campaign: per-mass cen2425+fwd2425 fit+limit, then the
# blinded combined 24+25 expected limits (combine_cards2425.sh groups).
cd /cms/bgestimation
IN=/cms/bgestimation/local_inputs/tight2425_v1
LOGD=/cms/bgestimation/v1local_logs
mkdir -p "$LOGD"
export RSWEEP_NOPLOT=1

rmax_for () {
  m=$1
  if   [ "$m" -le 700 ];  then echo 100
  elif [ "$m" -le 1200 ]; then echo 30
  elif [ "$m" -le 2000 ]; then echo 8
  else echo 3; fi
}

run_one () {
  spec="$1"; cat="${spec%%:*}"; m="${spec##*:}"
  rmax=$(rmax_for "$m")
  log="$LOGD/${cat}_M${m}.log"
  python -u ttbar.py --cat "$cat" --senario ZPrime_1 --input "$IN" \
      --signal "ZPrime${m}" --study limit --rMax "$rmax" > "$log" 2>&1
  rc=$?
  obs=$(grep "Observed Limit" "$log" | tail -1 | tr -d '\n')
  e50=$(grep "Expected 50" "$log" | tail -1 | tr -d '\n')
  echo "RESULT cat=$cat M=$m rc=$rc || $obs || $e50" >> "$LOGD/progress.log"
}
export -f run_one rmax_for
export IN LOGD RSWEEP_NOPLOT

for m in 400 500 600 700 800 900 1000 1200 1400 1600 1800 2000 2500 3000 3500 4000 4500 5000 6000; do
  echo "cen2425:$m"; echo "fwd2425:$m"
done | xargs -P 4 -I{} bash -c 'run_one "$@"' _ {}
echo "__PERMASS_DONE__" >> "$LOGD/progress.log"

echo "GROUP lowmass" >> "$LOGD/progress.log"
MASSES="400 500 600 700" RMAX=100 NPROC=4 bash run3/combine_cards2425.sh >> "$LOGD/comb.log" 2>&1
MASSES="800 900 1000 1200" RMAX=30 NPROC=4 bash run3/combine_cards2425.sh >> "$LOGD/comb.log" 2>&1
MASSES="1400 1600 1800 2000" RMAX=8 NPROC=4 bash run3/combine_cards2425.sh >> "$LOGD/comb.log" 2>&1
MASSES="2500 3000 3500 4000 4500 5000 6000" RMAX=6 NPROC=2 bash run3/combine_cards2425.sh >> "$LOGD/comb.log" 2>&1
grep -E "^OK|^FAIL|^SKIP" "$LOGD/comb.log" >> "$LOGD/progress.log"
echo "__COMB2425_DONE__" >> "$LOGD/progress.log"
