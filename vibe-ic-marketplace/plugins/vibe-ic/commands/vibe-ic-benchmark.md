---
name: vibe-ic-benchmark
description: Run any known open IC-design benchmark (VerilogEval-v2/Human, RTLLM, CVDP, …) through the same general IC-design path, then invoke its official scorer. Use when "run benchmark X", "score benchmark X", "benchmark this", "reproduce X benchmark", "跑 benchmark", "重跑 RTLLM", "score VerilogEval".
argument-hint: <bench> [--solve|--resume|--score --dataset <path> --run <path>] [--list]
---

# /vibe-ic-benchmark — turnkey benchmark runner

This command is the **front door** for every open IC-design benchmark. It enforces
the methodology from `open-benchmark-methodology` skill (§ 2 decision matrix → § 3
substitution disclosure → § 4 triage rubric) by routing to the correct run-shape
per the registry at `${CLAUDE_PLUGIN_ROOT}/benchmark/BENCHMARK_REGISTRY.json`.

`--solve` names the complete route-and-solve lifecycle; it is not a direct
solver entry.  For every problem, the first decision is made by the general
`task_nature_route` from the visible prompt and supplied-RTL state.  Only after
that route selects the normal flow entry/evidence boundary may
`vibe_ic_one_shot_runner` run.  Benchmark name, problem id, and dataset metadata
never select a route.

## Modes

```bash
# 1. List all known benchmarks + their shape + status
python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py --list

# 2. Show plan for one benchmark (env check + recommended commands)
python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py <bench>

# 3. Run Program First through the general flow; this creates a fresh run dir
#    and emits AI backup/review worklists
python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py <bench> \
    --solve --dataset <path-to-dataset> --run <run-dir>

# 4. Complete blind AI review; a FAIL also needs an executable challenge
python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py <bench> \
    --resume --dataset <path-to-dataset> --run <run-dir>

# 5. Score only after program_first_ai_review_acceptance.json says COMPLETE
python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py <bench> \
    --score --dataset <path-to-dataset> --run <run-dir>
```

## What the AI must do BEFORE invoking this command

**MANDATORY first step** (per the open-benchmark-keyword hook in this plugin):
1. Invoke `Skill(skill="vibe-ic:open-benchmark-methodology")` to load:
   - § 2 the run-shape decision matrix (so you don't repeat the 2026-05-28 RTLLM mistake)
   - § 3 the tool-substitution disclosure obligations
   - § 4 the triage rubric (A-H) — never label a fail "benchmark floor" without it
   - § 5 the per-benchmark cheat sheet (current shape + status + any TARGET RE-RUN)
2. Then call `benchmark_dispatch.py <bench>` to see the env check + recommended commands.
3. Then follow the right per-shape blind instructions from
   `${CLAUDE_PLUGIN_ROOT}/benchmark/blind_instructions_shape_<shape>.md`.

## Shape-routing summary (from the registry)

| Shape | Author | Scorer | Example benchmarks |
|---|---|---|---|
| **A** | `vibe_ic_one_shot_runner.py` (full chain) | `benchmark-verify` skill (six pillars) | benchmark_clean ICs (spm, sha256, subservient, u_hawaii_adc) |
| **B** | general `benchmark_dispatch --solve` → `task_nature_route` → `vibe_ic_one_shot_runner` | `benchmark/score_iverilog_tb.py` | RTLLM |
| **C** | the same general solve path; shape affects only scorer-facing packaging | `benchmark/score_iverilog_tb.py` | VerilogEval-v2, VerilogEval-Human |
| **C/D** | the same general solve path; CVDP JSONL is a thin I/O adapter only | official `run_benchmark.py` via `benchmark/score_cvdp_open.py` | CVDP open |
| **D** | `vibe_ic_one_shot_runner.py` (with `catalog-glue-author` if REUSED-IP) | `benchmark/score_cocotb_mcp.py` (MCP eda_cocotb / docker exec) | CVDP example, subservient-class |
| **E** | n/a — blocked / out-of-scope, document only | n/a | PyHDL-Eval (golden gated), RTL-Repo (wrong metric), MetRex / ResBench (different task / toolchain), CVDP-full (gated) |

For every runnable open evaluation driven by `--solve`, Program emits the first candidate and
an independent, blind AI reviews that exact hash. This is sequential Program
First + AI Backup, not two authors racing. AI is the final semantic authority,
but a semantic FAIL must include a self-contained prompt-derived executable
test: the frozen Program candidate must actually fail it before repair is
authorized. The repaired candidate must pass the same immutable test, all
Program gates, and a fresh AI review. A hash-bound repair record names the AI
author/model, rationale, parent/repaired RTL, and challenge. `--score`
hard-blocks missing/stale proof or provenance.
The challenge and both candidate hashes remain in
`program_enhancement_candidates.jsonl` as a reusable regression fixture.

## Honesty (mandatory in any RESULT.md)
- Disclose every tool substitution (VCS → iverilog, DC → yosys+OpenROAD, nvidia/cvdp-sim → vibeic-eda).
- Run the scorer with `cwd=design_dir` so `$readmemh` relative paths resolve.
- Classify every residual fail into rubric category A-H (skill § 4); FLOOR ≠ "I gave up".
- Never publish a number from Shape E.
