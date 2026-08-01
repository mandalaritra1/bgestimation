#!/bin/bash
# v1.1 signal-normalization refits: affected masses only.
# Phase A: per-cat fits+limits (adaptive rMax, unseeded).
# Phase B: combined blinded per point, RMAX = 30x the smaller per-cat e50.
export RSWEEP_NOPLOT=1
aklog 2>/dev/null
source /cvmfs/cms.cern.ch/cmsset_default.sh >/dev/null 2>&1
cd ~/CMSSW_14_1_0_pre4/src && eval `scramv1 runtime -sh` 2>/dev/null
source ~/CMSSW_14_1_0_pre4/src/twoD-env/bin/activate
cd ~/CMSSW_14_1_0_pre4/src/bgestimation
B="root://eosuser.cern.ch//eos/user/a/amandal/ttbarhad_root_files/2dAlphabetInputs_2425"

start_rmax () { # width mass
  w=$1; m=$2
  if [ "$m" -ge 5000 ]; then echo 1; return; fi
  case $w in
    1)  if [ "$m" -le 700 ]; then echo 3000; else echo 500; fi ;;
    10) if [ "$m" -le 700 ]; then echo 300;  else echo 60;  fi ;;
    30) if [ "$m" -le 700 ]; then echo 100;  else echo 30;  fi ;;
  esac
}

run_pt () { # cat width mass
  cat=$1; w=$2; m=$3
  if [ "$w" = "1" ]; then sig="ZPrime${m}"; sen="ZPrime_1"; else sig="ZPrime${m}_${w}"; sen="ZPrime_${w}"; fi
  rmax=$(start_rmax $w $m); tries=0
  while [ $tries -lt 4 ]; do
    log="/tmp/refit_${cat}_w${w}_M${m}.log"
    python -u ttbar.py --cat "$cat" --senario "$sen" --input "$B" --signal "$sig" --study limit --rMax "$rmax" > "$log" 2>&1
    rc=$?
    obs=$(grep "Observed Limit" "$log" | tail -1 | sed -n "s/.*r < \([0-9.]*\).*/\1/p")
    e50=$(grep "Expected 50" "$log" | tail -1 | sed -n "s/.*r < \([0-9.]*\).*/\1/p")
    e975=$(grep "Expected 97.5" "$log" | tail -1 | sed -n "s/.*r < \([0-9.]*\).*/\1/p")
    echo "RESULT cat=$cat w=$w M=$m rMax=$rmax rc=$rc obs=$obs e50=$e50 e975=$e975"
    if [ "$rc" != "0" ] || [ -z "$obs" ]; then rmax=$(python3 -c "print($rmax/5)")
    elif [ -n "$e975" ] && python3 -c "import sys; sys.exit(0 if max($obs,$e975) > 0.6*$rmax else 1)"; then rmax=$(python3 -c "print($rmax*5)")
    else break; fi
    tries=$((tries+1))
  done
}

echo "PHASE_A per-cat"
for w in 1 10 30; do
  if [ "$w" = "1" ]; then MS="400 500 600 700 800 900 5000 6000"; else MS="400 500 600 700 800 900"; fi
  for m in $MS; do
    run_pt cen2425 $w $m &
    run_pt fwd2425 $w $m &
    wait
  done
done
echo "PHASE_B combined blinded"
for w in 1 10 30; do
  if [ "$w" = "1" ]; then MS="400 500 600 700 800 900 5000 6000"; SUF=""; else MS="400 500 600 700 800 900"; SUF="_w${w}"; fi
  for m in $MS; do
    ce=$(grep "cat=cen2425 w=$w M=$m " /dev/null 2>/dev/null; true)
    e1=$(grep -h "RESULT cat=cen2425 w=$w M=$m .*rc=0" ~/refit_sigfix.log | tail -1 | sed -n "s/.*e50=\([0-9.]*\).*/\1/p")
    e2=$(grep -h "RESULT cat=fwd2425 w=$w M=$m .*rc=0" ~/refit_sigfix.log | tail -1 | sed -n "s/.*e50=\([0-9.]*\).*/\1/p")
    RM=$(python3 -c "
a=[x for x in ('$e1','$e2') if x]
print(round(30*min(float(x) for x in a)/1.5, 4) if a else 10)")
    export COMB_SUFFIX="$SUF"
    WIDTH=$w MASSES="$m" RMAX=$RM NPROC=1 bash run3/combine_cards2425.sh
    echo "COMB w=$w M=$m RMAX=$RM done"
  done
done
echo "__REFIT_SIGFIX_DONE__"
