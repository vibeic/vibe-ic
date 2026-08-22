#!/bin/bash
# Fresh container via `docker run` (never `docker exec`), so this cannot disturb the
# five live arms sharing this host.
D=/home/reyerchu/_jself_priv/meas/_j83
echo "START $(date -Is)  loadavg=$(cut -d' ' -f1-3 /proc/loadavg)  free=$(free -g|awk 'NR==2{print $7}')GB" > $D/posthold_probe_3800.log
docker run --rm -u 1000:1000 \
  -v /home/reyerchu/_gf180_priv/pdk/gf180mcuD:/foss/pdks/gf180mcuD:ro \
  -v /home/reyerchu:/home/reyerchu \
  -m 24g --memory-swap 24g --cpus=8 \
  --name jself-j83-posthold \
  ghcr.io/vibeic/vibeic-eda:0.3.13 \
  --skip bash -lc "openroad -no_init -exit $D/posthold_probe_3800.tcl" \
  >> $D/posthold_probe_3800.log 2>&1
rc=$?
echo "END $(date -Is)  rc=$rc  loadavg=$(cut -d' ' -f1-3 /proc/loadavg)" >> $D/posthold_probe_3800.log
