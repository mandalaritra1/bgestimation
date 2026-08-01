#!/bin/bash
# Blind-Asimov expected-band rescue for high-mass points (July recipe):
# combine -M AsymptoticLimits card.txt --run blind --setParameters <fit_b rpf params>
aklog 2>/dev/null
source /cvmfs/cms.cern.ch/cmsset_default.sh >/dev/null 2>&1
cd ~/CMSSW_14_1_0_pre4/src && eval `scramv1 runtime -sh` 2>/dev/null
source ~/CMSSW_14_1_0_pre4/src/twoD-env/bin/activate
BG=~/CMSSW_14_1_0_pre4/src/bgestimation

rescue_one () {
  cat=$1; m=$2; rmax=$3
  tf=2x2; [ "${cat#fwd}" != "$cat" ] && tf=2x1
  area=$BG/output/ttbarfits_${cat}_${tf}_signalZPrime${m}/ttbar-signalZPrime${m}_area
  [ -d "$area" ] || area=$BG/output/ttbarfits_${cat}_2x2_signalZPrime${m}/ttbar-signalZPrime${m}_area
  if [ ! -d "$area" ]; then echo "RESCUE cat=$cat M=$m MISSING_AREA"; return; fi
  cd "$area"
  mkdir -p obs_backup && cp -n higgsCombine*.root obs_backup/ 2>/dev/null
  params=$(python - <<PYEOF
import ROOT
f = ROOT.TFile.Open("fitDiagnosticsTest.root")
r = f.Get("fit_b")
pars = r.floatParsFinal()
out = []
for i in range(pars.getSize()):
    p = pars.at(i)
    if "rpf" in p.GetName():
        out.append("%s=%.10g" % (p.GetName(), p.getVal()))
print(",".join(out))
PYEOF
)
  if [ -z "$params" ]; then echo "RESCUE cat=$cat M=$m NO_FITB_PARAMS"; return; fi
  combine -M AsymptoticLimits card.txt --run blind --setParameters "$params" \
      --rMin 0 --rMax "$rmax" --rAbsAcc 0.0000001 --rRelAcc 0.005 \
      > blind_rescue.log 2>&1
  rc=$?
  e50=$(grep "Expected 50" blind_rescue.log | tail -1 | tr -d '\n')
  e025=$(grep "Expected  2.5" blind_rescue.log | tail -1 | tr -d '\n')
  e975=$(grep "Expected 97.5" blind_rescue.log | tail -1 | tr -d '\n')
  echo "RESCUE cat=$cat M=$m rc=$rc || $e025 || $e50 || $e975"
}

for spec in cen2425:1800:8 cen2425:2000:8 cen2425:2500:3 cen2425:3000:3 cen2425:3500:3 cen2425:4000:3 cen2425:4500:3 cen2425:5000:3 cen2425:6000:3 fwd2425:3000:3 fwd2425:3500:3 fwd2425:4000:3 fwd2425:4500:3 fwd2425:5000:3 fwd2425:6000:3; do
  IFS=: read cat m rmax <<< "$spec"
  rescue_one "$cat" "$m" "$rmax"
done
echo "__RESCUE_DONE__"
