#!/bin/bash
# Per-mass r-range sweep for the combined 24+25 2DAlphabet fit.
# Usage: rsweep.sh <cat> <signal> <rMax1> [rMax2 ...]
#   e.g. rsweep.sh cen2425 signalZPrime2000 0.05 0.1 0.3
# Emits one RESULT line per rMax with neg-event-error count + observed/expected limit.
aklog 2>/dev/null
source /cvmfs/cms.cern.ch/cmsset_default.sh >/dev/null 2>&1
cd ~/CMSSW_14_1_0_pre4/src && eval `scramv1 runtime -sh` 2>/dev/null
source ~/CMSSW_14_1_0_pre4/src/twoD-env/bin/activate
cd ~/CMSSW_14_1_0_pre4/src/bgestimation
B="root://eosuser.cern.ch//eos/user/a/amandal/ttbarhad_root_files/2dAlphabetInputs_2425"

cat="$1"; sig="$2"; shift 2
for rmax in "$@"; do
  log="/tmp/rsweep_${cat}_${sig}_rmax${rmax}.log"
  python -u ttbar.py --cat "$cat" --senario ZPrime_1 --input "$B" $RSWEEP_TTBAR_ARGS \
      --signal "$sig" --study limit --rMax "$rmax" > "$log" 2>&1
  rc=$?
  ne=$(grep -c "negative or error" "$log")
  obs=$(grep "Observed Limit" "$log" | tail -1 | tr -d '\n')
  e50=$(grep "Expected 50" "$log" | tail -1 | tr -d '\n')
  e025=$(grep "Expected  2.5" "$log" | tail -1 | tr -d '\n')
  e975=$(grep "Expected 97.5" "$log" | tail -1 | tr -d '\n')
  echo "RESULT cat=$cat sig=$sig rMax=$rmax rc=$rc neg_err=$ne || $obs || $e025 || $e50 || $e975"
done
echo "__SWEEP_DONE__"
