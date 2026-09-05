#!/usr/bin/env bash
# Waits for the slippage stress test to write its CSV, then runs the two
# measurements that were queued behind it for the machine.
cd "$(dirname "$0")"
for i in $(seq 1 240); do
  [ -f loadtest_slippage.csv ] && break
  sleep 15
done
python measure_tail_fatness.py > tail_fatness_clustered.log 2>&1
python measure_tail_capture.py > tail_capture.log 2>&1
echo "CHAIN DONE"
