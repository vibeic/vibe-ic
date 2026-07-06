#!/bin/bash
set +e
export VIBE_IC_RCVAR_WHITEBOX_FLAT=1
for id in cvdp_copilot_axi_stream_upscale_0001 cvdp_copilot_cont_adder_0042; do
  pj=/home/reyerchu/vibe-ic/benchmark-data/evaluation/cvdp/run_v1332_delta/runner_path/$id
  python3 /home/reyerchu/vibe-ic/vibe-ic-marketplace/plugins/vibe-ic/programs/vibe_ic_one_shot_runner.py $pj --pdk sky130A --skip-phase3 --skip-analog --skip-hardware \
     > $pj/runner.log 2>&1
  echo "RC=$? id=$id" >> $pj/runner.log
done
echo DONE > /home/reyerchu/vibe-ic/benchmark-data/evaluation/cvdp/run_v1332_delta/runner_path/DONE.flag
