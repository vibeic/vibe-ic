# VerilogEval-v2 / -Human quickstart

```bash
git clone https://github.com/NVlabs/verilog-eval <dataset-root>
python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py verilogeval-v2

python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py verilogeval-v2 \
  --solve --dataset <dataset-root>/dataset_spec-to-rtl \
  --run <fresh-run-dir>

# Complete only needs_ai_backup/review/repair worklists, then:
python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py verilogeval-v2 \
  --resume --dataset <dataset-root>/dataset_spec-to-rtl --run <run-dir>

python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py verilogeval-v2 \
  --score --dataset <dataset-root>/dataset_spec-to-rtl --run <run-dir>
```

Use `verilogeval-human` and `dataset_code-complete-iccad2023` for the Human
track. Shape C no longer authorizes a direct per-problem author/gate path; it
only controls the final sample contract and host scorer.
