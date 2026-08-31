# benchmark-harness — turnkey runners for every open IC-design benchmark

This directory ships everything a new plugin user needs to run open
benchmarks (VerilogEval-v2/Human, RTLLM, CVDP, …) **correctly** — i.e.
program-first per the `open-benchmark-methodology` skill, not by hand-rolling
a harness.

## What's here

| File | Purpose |
|---|---|
| `BENCHMARK_REGISTRY.json` | Single source of truth: every known open benchmark → run-shape (A/B/C/D/E), dataset URL, on-disk layout, scorer choice |
| `score_iverilog_tb.py` | Generic Shape B + C scorer — iverilog substituting for VCS / Xcelium, runs vvp from the design dir so `$readmemh` resolves |
| `score_cocotb_mcp.py` | Generic Shape D scorer — wraps `docker exec vibeic-eda … cocotb` (substitutes the gated `nvidia/cvdp-sim` image) |
| `score_cvdp_open.py` | CVDP official-scorer adapter — validates the two OSS images and invokes upstream `run_benchmark.py` on accepted general-flow responses |
| `blind_instructions_shape_b.md` | Per-shape blind-agent instructions (runner-driven, RTLLM-class) |
| `blind_instructions_shape_c.md` | Per-shape blind-agent instructions (atomic micro-problems, VerilogEval-class) |
| `blind_instructions_shape_d.md` | Per-shape blind-agent instructions (agentic SoC, CVDP-class) |
| `examples/` | Per-benchmark quickstart (one tiny worked example per shape) |

## How to use (from a fresh plugin install)

The front door is the `/vibe-ic-benchmark` slash command, which delegates to
`programs/benchmark_dispatch.py`:

```bash
# 1. See what's known
python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py --list

# 2. Show plan for a benchmark (with env check + recommended commands)
python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py rtllm

# 3. Solve every problem through the general IC-design path
git clone https://github.com/hkust-zhiyao/RTLLM /path/to/RTLLM
python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py rtllm \
    --solve --dataset /path/to/RTLLM --run /path/to/run_blind_001

# 4. Complete the runner-owned AI backup/review/repair worklists, then resume
python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py rtllm \
    --resume --dataset /path/to/RTLLM --run /path/to/run_blind_001

# 5. Score
python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py rtllm \
    --score --dataset /path/to/RTLLM --run /path/to/run_blind_001
```

## The doctrine you MUST internalize first

This harness only works correctly if you've loaded the
`open-benchmark-methodology` skill. A `UserPromptSubmit` hook auto-injects a
reminder when any benchmark keyword appears in your message — but the skill is
the source of truth for:

- § 1 Where Vibe-IC is a program vs an LLM (spec→RTL itself is an AI skill;
  every gate around it is a program)
- § 2 The five scorer/evidence shapes. Runnable open evaluations still share
  one authoring entry: dispatcher → general router → one-shot runner.
- § 3 Tool-substitution disclosure (VCS→iverilog, DC→yosys+OpenROAD, etc.) +
  the `cwd=design_dir` rule
- § 4 Triage rubric A-H (FLOOR vs agent-fixable) — never label a fail
  "benchmark defect" without going through it
- § 5 Per-benchmark cheat sheet (status + TARGET RE-RUN flags)
- § 6 Mandatory RESULT.md sections
- § 7 Tie-breakers; § 8 re-run obligations

## What this harness deliberately does NOT do

- It does NOT clone datasets automatically (you confirm + run `git clone`
  yourself — explicit consent for third-party data).
- It does NOT bypass the per-shape blind rules (each blind_instructions_*.md
  file is the contract).
- For Shape E (blocked/out-of-scope) benchmarks (PyHDL-Eval, RTL-Repo,
  MetRex, ResBench, CVDP-full), it prints the blocker honestly and refuses to
  emit a number.

## Adding a new benchmark

1. Add an entry to `BENCHMARK_REGISTRY.json` (pick the shape; declare layout).
2. If the scorer needs new pass/fail regex or layout knobs, extend
   `score_iverilog_tb.py` (Shape B/C) or `score_cocotb_mcp.py` (Shape D).
3. Update the methodology skill's § 5 cheat sheet.
4. Bump plugin version.

## Honest history

This harness exists because the 2026-05-28 sweep ran RTLLM as Shape C (direct
agent authoring) instead of Shape B (runner-driven) and published 37/50 — a
number that measured "Opus + MCP-EDA generic capability", not "Vibe-IC runner
capability". The skill + this harness + the hook are three layers of insurance
against repeating that mistake. See
`benchmark_external/rtllm/RESULT.md` for the worked example.
