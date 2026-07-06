#!/bin/bash
python3 /home/reyerchu/vibe-ic/vibe-ic-marketplace/plugins/vibe-ic/benchmark/score_one.py --id cvdp_copilot_axi_stream_upscale_0001 --draft /home/reyerchu/vibe-ic/benchmark-data/evaluation/cvdp/run_v1332_delta/exp/axis_upscale_noadd.sv \
  --dataset /home/reyerchu/vibe-ic/benchmark-data/evaluation/cvdp/run_v1332_delta/ds_single/cvdp_copilot_axi_stream_upscale_0001.jsonl --bench /home/reyerchu/AI_IC_design/_extbench/cvdp_benchmark \
  --sim-image cvdp-sim-pinned:latest --workdir /home/reyerchu/vibe-ic/benchmark-data/evaluation/cvdp/run_v1332_delta/exp/wd_noadd > /home/reyerchu/vibe-ic/benchmark-data/evaluation/cvdp/run_v1332_delta/exp/noadd.verdict 2>&1
echo "RC=$?" >> /home/reyerchu/vibe-ic/benchmark-data/evaluation/cvdp/run_v1332_delta/exp/noadd.verdict
echo DONE > /home/reyerchu/vibe-ic/benchmark-data/evaluation/cvdp/run_v1332_delta/exp/DONE.flag
