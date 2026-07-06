#!/bin/bash
set +e
for id in cvdp_copilot_axi_stream_upscale_0001 cvdp_copilot_cache_lru_0001 cvdp_copilot_cont_adder_0042; do
  ( python3 /home/reyerchu/vibe-ic/vibe-ic-marketplace/plugins/vibe-ic/benchmark/score_one.py --id $id --draft /home/reyerchu/vibe-ic/benchmark-data/evaluation/cvdp/run_v1332_delta/drafts/$id.sv \
      --dataset /home/reyerchu/vibe-ic/benchmark-data/evaluation/cvdp/run_v1332_delta/ds_single/$id.jsonl --bench /home/reyerchu/AI_IC_design/_extbench/cvdp_benchmark \
      --sim-image cvdp-sim-pinned:latest --workdir /home/reyerchu/vibe-ic/benchmark-data/evaluation/cvdp/run_v1332_delta/score_raw/$id \
      > /home/reyerchu/vibe-ic/benchmark-data/evaluation/cvdp/run_v1332_delta/score_raw/$id.verdict 2>&1 ; echo "RC=$?" >> /home/reyerchu/vibe-ic/benchmark-data/evaluation/cvdp/run_v1332_delta/score_raw/$id.verdict ) &
done
wait
echo ALL_DONE > /home/reyerchu/vibe-ic/benchmark-data/evaluation/cvdp/run_v1332_delta/score_raw/DONE.flag
