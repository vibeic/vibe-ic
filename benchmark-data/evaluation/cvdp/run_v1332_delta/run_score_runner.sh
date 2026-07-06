#!/bin/bash
set +e
for id in cvdp_copilot_axi_stream_upscale_0001 cvdp_copilot_cont_adder_0042; do
  emit=$(ls /home/reyerchu/vibe-ic/benchmark-data/evaluation/cvdp/run_v1332_delta/runner_path/$id/phase2/stage1/rtl/*.sv 2>/dev/null | head -1)
  ( python3 /home/reyerchu/vibe-ic/vibe-ic-marketplace/plugins/vibe-ic/benchmark/score_one.py --id $id --draft "$emit" \
      --dataset /home/reyerchu/vibe-ic/benchmark-data/evaluation/cvdp/run_v1332_delta/ds_single/$id.jsonl --bench /home/reyerchu/AI_IC_design/_extbench/cvdp_benchmark \
      --sim-image cvdp-sim-pinned:latest --workdir /home/reyerchu/vibe-ic/benchmark-data/evaluation/cvdp/run_v1332_delta/score_runner/$id \
      > /home/reyerchu/vibe-ic/benchmark-data/evaluation/cvdp/run_v1332_delta/score_runner/$id.verdict 2>&1 ; echo "RC=$?" >> /home/reyerchu/vibe-ic/benchmark-data/evaluation/cvdp/run_v1332_delta/score_runner/$id.verdict ) &
done
wait
echo DONE > /home/reyerchu/vibe-ic/benchmark-data/evaluation/cvdp/run_v1332_delta/score_runner/DONE.flag
