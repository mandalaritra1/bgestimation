#!/bin/bash
# Combined blinded stage only, SERIAL (the 4-wide AsymptoticLimits OOMs the 8GB VM
# into 387-byte empty stubs -- July's documented trap).
cd /cms/bgestimation
LOGD=/cms/bgestimation/v1local_logs
MASSES="400 500 600 700" RMAX=100 NPROC=1 bash run3/combine_cards2425.sh >> "$LOGD/comb_serial.log" 2>&1
echo "GROUP lowmass done" >> "$LOGD/progress.log"
MASSES="800 900 1000 1200" RMAX=30 NPROC=1 bash run3/combine_cards2425.sh >> "$LOGD/comb_serial.log" 2>&1
echo "GROUP mid done" >> "$LOGD/progress.log"
MASSES="1400 1600 1800 2000" RMAX=8 NPROC=1 bash run3/combine_cards2425.sh >> "$LOGD/comb_serial.log" 2>&1
echo "GROUP high done" >> "$LOGD/progress.log"
MASSES="2500 3000 3500 4000 4500 5000 6000" RMAX=6 NPROC=1 bash run3/combine_cards2425.sh >> "$LOGD/comb_serial.log" 2>&1
grep -E "^OK|^FAIL|^SKIP" "$LOGD/comb_serial.log" >> "$LOGD/progress.log"
echo "__COMB2425_DONE__" >> "$LOGD/progress.log"
