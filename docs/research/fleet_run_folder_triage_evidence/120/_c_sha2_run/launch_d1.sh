#!/bin/bash
export CLAUDE_PLUGIN_ROOT=/home/reyerchu/_c_plugin97_lecfix/vibe-ic-marketplace/plugins/vibe-ic
export OMP_NUM_THREADS=6
export PDK_ROOT=/foss/pdks
export PYTHONUNBUFFERED=1
cd /home/reyerchu/_c_sha2_run/d1
exec nice -n 10 python3 /home/reyerchu/_c_plugin97_lecfix/vibe-ic-marketplace/plugins/vibe-ic/programs/vibe_ic_one_shot_runner.py \
  /home/reyerchu/_c_sha2_run/d1 \
  --pdk sky130A --ic-name sha256 \
  --container vibeic-eda-d256 \
  --require-image ghcr.io/vibeic/vibeic-eda:0.2.47 \
  --no-dashboard
