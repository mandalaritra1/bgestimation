#!/bin/bash
aklog 2>/dev/null
source /cvmfs/cms.cern.ch/cmsset_default.sh >/dev/null 2>&1
cd ~/CMSSW_14_1_0_pre4/src && eval `scramv1 runtime -sh` 2>/dev/null
source ~/CMSSW_14_1_0_pre4/src/twoD-env/bin/activate
cd ~/CMSSW_14_1_0_pre4/src/bgestimation
for W in 10 30; do
  echo "WIDTH $W combined blinded"
  COMB_SUFFIX="_w${W}" ; export COMB_SUFFIX
  WIDTH=$W MASSES="400 500 600 700 800 900 1200" RMAX=10 NPROC=4 bash run3/combine_cards2425.sh
  WIDTH=$W MASSES="1000" RMAX=30 NPROC=1 bash run3/combine_cards2425.sh
  WIDTH=$W MASSES="1400 1600" RMAX=4 NPROC=2 bash run3/combine_cards2425.sh
  WIDTH=$W MASSES="1800 2000" RMAX=1 NPROC=2 bash run3/combine_cards2425.sh
  WIDTH=$W MASSES="2500" RMAX=0.5 NPROC=1 bash run3/combine_cards2425.sh
  WIDTH=$W MASSES="3000" RMAX=0.2 NPROC=1 bash run3/combine_cards2425.sh
  WIDTH=$W MASSES="3500 4000 4500" RMAX=0.1 NPROC=1 bash run3/combine_cards2425.sh
  WIDTH=$W MASSES="5000 6000" RMAX=0.05 NPROC=1 bash run3/combine_cards2425.sh
  echo "__COMB_W${W}_DONE__"
done
echo "__COMB_ALLWIDTHS_DONE__"
