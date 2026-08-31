# CVDP open quickstart

Use the HF v1.1.0 open JSONL and the general benchmark entry. The historical
N=1 project wrapper and per-cid authoring paths are superseded.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py cvdp-open

python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py cvdp-open \
  --solve --dataset <cvdp-open.jsonl> --run <fresh-run-dir>

# Complete only the runner-owned backup/review/repair queues, then:
python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py cvdp-open \
  --resume --dataset <cvdp-open.jsonl> --run <run-dir>

OSS_SIM_IMAGE=<official-compatible-image> \
OSS_PNR_IMAGE=<official-compatible-image> \
python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py cvdp-open \
  --score --dataset <cvdp-open.jsonl> --run <run-dir> \
  --scorer-root <cvdp-benchmark-root>
```

No benchmark-specific router or solver is part of this recipe. CVDP-aware code
is limited to staging its JSONL input and packaging accepted bytes for the
official scorer.
