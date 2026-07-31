#!/usr/bin/env bash
# Full ZPrime mass scan for the 2025 STANDALONE categories (cen2025, fwd2025).
# Runs `ttbar.py --study limit` per (category, mass): each produces the per-region
#   output/ttbarfits_{cen2025_2x2,fwd2025_2x1}_signalZPrime<mass>/signalZPrime<mass>_area/card.txt
# that combine_cards25.sh then merges into the cen+fwd limit.
#
# Each (cat,mass) writes its OWN per-signal config jsons/config/ttbar_<cat>__signal<sig>.json
# and its OWN per-mass project dir, so distinct cat+mass pairs are safe to run in
# parallel (the F-test race only bit identical cat+signal across TF orders).
#
# Run from src/bgestimation inside the combine/CMSSW env:
#   bash run3/run_fit_2025.sh            # 4 jobs at a time (default)
#   NPROC=6 bash run3/run_fit_2025.sh
#   WIDTH=10 bash run3/run_fit_2025.sh   # 10% width grid (signalZPrime<mass>_10)

NPROC="${NPROC:-4}"
BASE_INPUT="${BASE_INPUT:-/uscms/home/amandal2/nobackup/rootfiles/recomb_ttag}"
SCENARIO="${SCENARIO:-ZPrime_1}"

WIDTH="${WIDTH:-1}"
case "$WIDTH" in
  1)  TAG="" ;;
  10) TAG="_10" ;;
  30) TAG="_30" ;;
  *)  echo "Unknown WIDTH=$WIDTH (use 1|10|30)"; exit 1 ;;
esac

# Same 13-point grid as the 2024 scan (m_tt window ends at 6500, so cap at 6 TeV).
MASSES="${MASSES:-1000 1200 1400 1600 1800 2000 2500 3000 3500 4000 4500 5000 6000}"
CATS="${CATS:-cen2025 fwd2025}"

LOGDIR="logs_2025_w${WIDTH}"
mkdir -p "$LOGDIR"

run_one() {
  local cat="$1" sig="$2"
  local log="${LOGDIR}/${cat}_${sig}.log"
  echo "START ${cat} ${sig}"
  if python -u ttbar.py --cat "${cat}" --senario "${SCENARIO}" \
        --input "${BASE_INPUT}" --signal "${sig}" --study limit > "${log}" 2>&1; then
    echo "OK    ${cat} ${sig}"
  else
    echo "FAIL  ${cat} ${sig}  -- see ${log}"
  fi
}
export -f run_one
export BASE_INPUT SCENARIO LOGDIR

# Build the (cat, signal) job list, one per line.
JOBLIST="$(mktemp)"
for m in $MASSES; do
  for cat in $CATS; do
    printf '%s signalZPrime%s%s\n' "$cat" "$m" "$TAG" >> "$JOBLIST"
  done
done

njobs=$(wc -l < "$JOBLIST")
echo "Launching ${njobs} (cat,mass) fits, ${NPROC} at a time  (SCENARIO=${SCENARIO}, WIDTH=${WIDTH})"
xargs -P "$NPROC" -L1 bash -c 'run_one "$@"' _ < "$JOBLIST"
rm -f "$JOBLIST"

echo "DONE per-cat 2025 scan. Next: bash run3/combine_cards25.sh"
