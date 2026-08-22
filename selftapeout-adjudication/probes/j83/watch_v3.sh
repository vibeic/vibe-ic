#!/bin/bash
D=/home/reyerchu/_jself_priv/meas/_j83
for i in $(seq 1 360); do
  grep -qa 'PROBE_DONE' $D/posthold_probe_3800_v3.log 2>/dev/null && break
  docker ps --format '{{.Names}}' | grep -q jself-j83-posthold-v3 || break
  sleep 15
done
{ echo "=== $(date -Is) ==="
  grep -a 'Violations remain\|swapped=\|PROBE_PRESWAP\|PROBE_POSTSWAP\|PROBE_DONE\|DPL-0007\|DPL-0009\|^END' $D/posthold_probe_3800_v3.log
} >> $D/watch_v3.log
