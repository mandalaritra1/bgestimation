#!/bin/bash
# Per-mass limit campaign, width-general. Usage: campaign_tight_w.sh <cat> <width>
#   cat = cen2425 | fwd2425 ; width = 10 | 30
# UNSEEDED (v1 finding: TTBAR_INIT_PARAMS seeding breaks cen2425 fit_b).
export RSWEEP_NOPLOT=1
cat="$1"; w="$2"
aklog 2>/dev/null
source /cvmfs/cms.cern.ch/cmsset_default.sh >/dev/null 2>&1
cd ~/CMSSW_14_1_0_pre4/src && eval `scramv1 runtime -sh` 2>/dev/null
source ~/CMSSW_14_1_0_pre4/src/twoD-env/bin/activate
cd ~/CMSSW_14_1_0_pre4/src/bgestimation
B="root://eosuser.cern.ch//eos/user/a/amandal/ttbarhad_root_files/2dAlphabetInputs_2425"

rmax_for () {
  m=$1
  if   [ "$m" -le 700 ];  then echo 100
  elif [ "$m" -le 1200 ]; then echo 30
  elif [ "$m" -le 2000 ]; then echo 8
  else echo 3; fi
}

for m in 400 500 600 700 800 900 1000 1200 1400 1600 1800 2000 2500 3000 3500 4000 4500 5000 6000; do
  rmax=$(rmax_for $m)
  sig="ZPrime${m}_${w}"
  tries=0
  while [ $tries -lt 3 ]; do
    log="/tmp/w${w}_${cat}_M${m}_rmax${rmax}.log"
    python -u ttbar.py --cat "$cat" --senario "ZPrime_${w}" --input "$B" \
        --signal "$sig" --study limit --rMax "$rmax" > "$log" 2>&1
    rc=$?
    obs=$(grep "Observed Limit" "$log" | tail -1 | tr -d '\n')
    e50=$(grep "Expected 50" "$log" | tail -1 | tr -d '\n')
    e975=$(grep "Expected 97.5" "$log" | tail -1 | tr -d '\n')
    echo "RESULT cat=$cat w=$w M=$m rMax=$rmax rc=$rc || $obs || $e50 || $e975"
    obsval=$(echo "$obs" | sed -n "s/.*r < \([0-9.]*\).*/\1/p")
    e975val=$(echo "$e975" | sed -n "s/.*r < \([0-9.]*\).*/\1/p")
    if [ "$rc" != "0" ] || [ -z "$obsval" ]; then
      rmax=$(python3 -c "print($rmax/4)")
      echo "RETRY $cat w=$w M=$m smaller rMax=$rmax"
    elif [ -n "$e975val" ] && python3 -c "import sys; sys.exit(0 if max($obsval,$e975val) > 0.5*$rmax else 1)"; then
      rmax=$(python3 -c "print($rmax*4)")
      echo "RETRY $cat w=$w M=$m larger rMax=$rmax"
    else
      break
    fi
    tries=$((tries+1))
  done
done
echo "__CAMPAIGN_${cat}_w${w}_DONE__"
