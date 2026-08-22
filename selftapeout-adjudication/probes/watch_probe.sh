#!/bin/bash
# Wait for the probe to print its post-swap verdict, or for its container to vanish.
D=/home/reyerchu/_jself_priv/meas/_j80
for i in $(seq 1 720); do
  if grep -qa 'PROBE_DONE' $D/probe_3800.log 2>/dev/null; then
    echo "DONE at $(date -Is)" >> $D/watch.log; break
  fi
  if ! docker ps --format '{{.Names}}' | grep -q jself-j80-3800; then
    echo "CONTAINER GONE at $(date -Is)" >> $D/watch.log; break
  fi
  sleep 20
done
{ echo "=== $(date -Is) ==="
  grep -a 'PROBE_STAGE\|PROBE_LEGALIZE\|PROBE_PRESWAP\|PROBE_POSTSWAP\|POST_HOLD_CLKBUF\|Violations remain\|PROBE_DONE\|END ' $D/probe_3800.log
} >> $D/watch.log
