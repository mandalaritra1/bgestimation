#!/bin/bash
# Per-mass limit campaign on the tight-WP 2425 inputs.
# Usage: campaign_tight.sh <cat>   (cen2425 | fwd2425)
export RSWEEP_NOPLOT=1
export RSWEEP_TTBAR_ARGS=""
cat="$1"
export TTBAR_INIT_PARAMS=/tmp/fp_seed_${cat}.json

rmax_for () {
  m=$1
  if   [ "$m" -le 700 ];  then echo 100
  elif [ "$m" -le 1200 ]; then echo 30
  elif [ "$m" -le 2000 ]; then echo 8
  else echo 3; fi
}

for m in 400 500 600 700 800 900 1000 1200 1400 1600 1800 2000 2500 3000 3500 4000 4500 5000 6000; do
  rmax=$(rmax_for $m)
  tries=0
  while [ $tries -lt 3 ]; do
    line=$(~/rsweep.sh $cat signalZPrime${m} $rmax | grep "^RESULT")
    echo "$line"
    rc=$(echo "$line" | sed -n "s/.*rc=\([0-9]*\).*/\1/p")
    obs=$(echo "$line" | sed -n "s/.*Observed Limit: r < \([0-9.]*\).*/\1/p")
    e975=$(echo "$line" | sed -n "s/.*Expected 97.5%: r < \([0-9.]*\).*/\1/p")
    if [ "$rc" != "0" ] || [ -z "$obs" ]; then
      rmax=$(python3 -c "print($rmax/4)")
      echo "RETRY $cat M=$m with smaller rMax=$rmax"
    elif [ -n "$e975" ] && python3 -c "import sys; sys.exit(0 if max($obs,$e975) > 0.5*$rmax else 1)"; then
      rmax=$(python3 -c "print($rmax*4)")
      echo "RETRY $cat M=$m with larger rMax=$rmax"
    else
      break
    fi
    tries=$((tries+1))
  done
done
echo "__CAMPAIGN_${cat}_DONE__"
