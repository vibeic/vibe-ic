#!/bin/bash
python3 /home/reyerchu/vibe-ic/vibe-ic-marketplace/plugins/vibe-ic/benchmark/score_one.py --id cvdp_copilot_cache_lru_0001 --draft /home/reyerchu/vibe-ic/benchmark-data/evaluation/cvdp/run_v1332_delta/drafts/cvdp_copilot_cache_lru_0001_v2.sv \
  --dataset /home/reyerchu/vibe-ic/benchmark-data/evaluation/cvdp/run_v1332_delta/ds_single/cvdp_copilot_cache_lru_0001.jsonl --bench /home/reyerchu/AI_IC_design/_extbench/cvdp_benchmark \
  --sim-image cvdp-sim-pinned:latest --workdir /home/reyerchu/vibe-ic/benchmark-data/evaluation/cvdp/run_v1332_delta/score_raw/cache_lru_v2 \
  > /home/reyerchu/vibe-ic/benchmark-data/evaluation/cvdp/run_v1332_delta/score_raw/cache_lru_v2.verdict 2>&1
echo "RC=$?" >> /home/reyerchu/vibe-ic/benchmark-data/evaluation/cvdp/run_v1332_delta/score_raw/cache_lru_v2.verdict
echo DONE > /home/reyerchu/vibe-ic/benchmark-data/evaluation/cvdp/run_v1332_delta/score_raw/LRUV2_DONE.flag
