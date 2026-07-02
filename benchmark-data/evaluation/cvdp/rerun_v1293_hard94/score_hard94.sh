#!/usr/bin/env bash
set -euo pipefail
RUN=/home/reyerchu/vibe-ic/benchmark-data/evaluation/cvdp/rerun_v1293_hard94
HARNESS=/home/reyerchu/AI_IC_design/_extbench/cvdp_benchmark
cd "$HARNESS"
OSS_SIM_IMAGE=cvdp-sim-pinned:latest OSS_PNR_IMAGE=cvdp-sim-pinned:latest \
  python3 run_benchmark.py -f "$RUN/dataset_hard94.jsonl" --llm -m local_import \
    --prompts-responses-file "$RUN/responses_hard94_final.jsonl" \
    -t 6 -p "$RUN/score_hard94" 2>&1 | tee "$RUN/score_hard94.log"
