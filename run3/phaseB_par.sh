#!/bin/bash
# Parallel remainder of v1.1 Phase B (combined blinded), 4-wide.
aklog 2>/dev/null
source /cvmfs/cms.cern.ch/cmsset_default.sh >/dev/null 2>&1
cd ~/CMSSW_14_1_0_pre4/src && eval `scramv1 runtime -sh` 2>/dev/null
source ~/CMSSW_14_1_0_pre4/src/twoD-env/bin/activate
cd ~/CMSSW_14_1_0_pre4/src/bgestimation

run_comb () { # "w:mass"
  w="${1%%:*}"; m="${1##*:}"
  e1=$(grep -h "RESULT cat=cen2425 w=$w M=$m .*rc=0" ~/refit_sigfix.log | tail -1 | sed -n "s/.*e50=\([0-9.]*\).*/\1/p")
  e2=$(grep -h "RESULT cat=fwd2425 w=$w M=$m .*rc=0" ~/refit_sigfix.log | tail -1 | sed -n "s/.*e50=\([0-9.]*\).*/\1/p")
  RM=$(python3 -c "
a=[float(x) for x in ('$e1','$e2') if x]
print(round(20*min(a), 4) if a else 1)")
  SUF=""; [ "$w" != "1" ] && SUF="_w${w}"
  COMB_SUFFIX="$SUF" WIDTH=$w MASSES="$m" RMAX=$RM NPROC=1 bash run3/combine_cards2425.sh > /tmp/phaseB_w${w}_M${m}.log 2>&1
  ok=$(grep -c "^OK" /tmp/phaseB_w${w}_M${m}.log)
  echo "COMBPAR w=$w M=$m RMAX=$RM ok=$ok"
}
export -f run_comb

printf '%s\n' 1:700 1:800 1:900 1:6000 10:400 10:500 10:600 10:700 10:800 10:900 30:400 30:500 30:600 30:700 30:800 30:900 | xargs -P 4 -I{} bash -c 'run_comb "$@"' _ {}
echo "__PHASEB_PAR_DONE__"
