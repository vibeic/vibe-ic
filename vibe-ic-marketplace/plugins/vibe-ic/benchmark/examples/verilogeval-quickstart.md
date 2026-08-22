# VerilogEval-v2 / -Human quickstart (Shape C)

```bash
# 1. Clone (one-time; ~2 MB)
git clone https://github.com/NVlabs/verilog-eval ~/datasets/verilog-eval

# 2. Plan + env check
python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py verilogeval-v2

# 3. Set up run dir
python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py verilogeval-v2 \
    --setup --dataset ~/datasets/verilog-eval/dataset_spec-to-rtl \
    --run ~/runs/verilogeval_v2_001

# 4. Drive batches per blind_instructions_shape_c.md
#    Per problem: LLM authors spec.yaml + sample.sv from the prompt only,
#    then run:
#    python3 ${CLAUDE_PLUGIN_ROOT}/benchmark/gates_atomic.py \\
#        --prob <Prob> \\
#        --workdir ~/runs/verilogeval_v2_001/work \\
#        --dataset ~/datasets/verilog-eval/dataset_spec-to-rtl \\
#        --bench verilogeval-v2
#    Hard gates: phase1_run_all + iverilog_compile. The gate auto-runs
#    rtl_hygiene_lint --fix (power-up determinism) before emit.

# 5. Score
python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py verilogeval-v2 \
    --score --run ~/runs/verilogeval_v2_001
```

Replace `verilogeval-v2` with `verilogeval-human` and `dataset_spec-to-rtl`
with `dataset_code-complete-iccad2023` for the Human track.

## Honest expectations
- 156 problems. ~3-5 are dataset defects (e.g. Prob062 mux-polarity arbitrary,
  Prob093 K-map vs reference contradiction, Prob099 testbench wires the wrong
  port name) → skill § 4 Cat A FLOOR, unrecoverable without contradicting the
  prompt. The 2026-05-28 baseline: v2 152/156 = 97.44%, Human 153/156 = 98.08%.
