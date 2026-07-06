#!/bin/bash
python3 /home/reyerchu/vibe-ic/vibe-ic-marketplace/plugins/vibe-ic/benchmark/score_one.py --id cvdp_copilot_axi_stream_upscale_0001 --draft /home/reyerchu/vibe-ic/benchmark-data/evaluation/cvdp/run_v1332_delta/runner_path_fixed/cvdp_copilot_axi_stream_upscale_0001/phase2/stage1/rtl/axis_upscale.sv \
  --dataset /home/reyerchu/vibe-ic/benchmark-data/evaluation/cvdp/run_v1332_delta/ds_single/cvdp_copilot_axi_stream_upscale_0001.jsonl --bench /home/reyerchu/AI_IC_design/_extbench/cvdp_benchmark \
  --sim-image cvdp-sim-pinned:latest --workdir /home/reyerchu/vibe-ic/benchmark-data/evaluation/cvdp/run_v1332_delta/runner_path_fixed/wd > /home/reyerchu/vibe-ic/benchmark-data/evaluation/cvdp/run_v1332_delta/runner_path_fixed/axi_fixed.verdict 2>&1
echo "RC=$?" >> /home/reyerchu/vibe-ic/benchmark-data/evaluation/cvdp/run_v1332_delta/runner_path_fixed/axi_fixed.verdict
echo DONE > /home/reyerchu/vibe-ic/benchmark-data/evaluation/cvdp/run_v1332_delta/runner_path_fixed/DONE.flag
