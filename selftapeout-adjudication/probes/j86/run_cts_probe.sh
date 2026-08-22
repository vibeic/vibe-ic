#!/bin/bash
TAG=$1
D=/home/reyerchu/_jself_priv/meas/_j86
echo "START $(date -Is)  loadavg=$(cut -d' ' -f1-3 /proc/loadavg)  free=$(free -g|awk 'NR==2{print $7}')GB" > $D/cts_probe_${TAG}.log
docker run --rm -u 1000:1000 \
  -v /home/reyerchu/_gf180_priv/pdk/gf180mcuD:/foss/pdks/gf180mcuD:ro \
  -v /home/reyerchu:/home/reyerchu \
  -m 24g --memory-swap 24g --cpus=6 \
  --name jself-j86-${TAG} \
  ghcr.io/vibeic/vibeic-eda:0.3.13 \
  --skip bash -lc "openroad -no_init -exit $D/cts_probe_${TAG}.tcl" \
  >> $D/cts_probe_${TAG}.log 2>&1
echo "END $(date -Is)  rc=$?  loadavg=$(cut -d' ' -f1-3 /proc/loadavg)" >> $D/cts_probe_${TAG}.log
