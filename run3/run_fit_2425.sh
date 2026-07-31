#!/usr/bin/env bash
# Full ZPrime mass scan for the COMBINED 24+25 categories (cen2425, fwd2425).
# Each of these is itself a simultaneous per-year-region fit (Cen24/25 Pass/Fail,
# Fwd24/25 Pass/Fail) with its own per-year transfer function. `--study limit`
# per (category, mass) produces the per-region card that combine_cards2425.sh
# then merges into the cen+fwd 24+25 limit:
#   output/ttbarfits_{cen2425_2x2,fwd2425_2x1}_signalZPrime<mass>/signalZPrime<mass>_area/card.txt
#
# NOTE cen2425 needs ttbar_xsec at 30% (already set in jsons/config/ttbar_cen2425.json)
# for the b-only fit to converge; otherwise fit_b is not saved.
#
# Run from src/bgestimation inside the combine/CMSSW env:
#   bash run3/run_fit_2425.sh
#   NPROC=4 bash run3/run_fit_2425.sh

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

MASSES="${MASSES:-1000 1200 1400 1600 1800 2000 2500 3000 3500 4000 4500 5000 6000}"
CATS="${CATS:-cen2425 fwd2425}"

LOGDIR="logs_2425_w${WIDTH}"
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

JOBLIST="$(mktemp)"
for m in $MASSES; do
  for cat in $CATS; do
    printf '%s signalZPrime%s%s\n' "$cat" "$m" "$TAG" >> "$JOBLIST"
  done
done

njobs=$(wc -l < "$JOBLIST")
echo "Launching ${njobs} (cat,mass) combined-year fits, ${NPROC} at a time  (SCENARIO=${SCENARIO}, WIDTH=${WIDTH})"
xargs -P "$NPROC" -L1 bash -c 'run_one "$@"' _ < "$JOBLIST"
rm -f "$JOBLIST"

echo "DONE per-cat 24+25 scan. Next: bash run3/combine_cards2425.sh"
