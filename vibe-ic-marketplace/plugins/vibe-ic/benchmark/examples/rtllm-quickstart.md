# RTLLM v2.0 quickstart

```bash
git clone https://github.com/hkust-zhiyao/RTLLM <dataset>
python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py rtllm

python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py rtllm \
  --solve --dataset <dataset> --run <fresh-run-dir>

# Complete only needs_ai_backup/review/repair worklists, then:
python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py rtllm \
  --resume --dataset <dataset> --run <run-dir>

python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py rtllm \
  --score --dataset <dataset> --run <run-dir>
```

The dispatcher stages each description, uses the general task-nature router,
and invokes the same one-shot runner used by ordinary IC-design work. Shape B
only controls scorer-facing packaging and the host testbench invocation.
