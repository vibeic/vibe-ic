---
name: vibe-ic-benchmark
description: Run any known open IC-design benchmark (VerilogEval-v2/Human, RTLLM, CVDP, …) the CORRECT way per the open-benchmark-methodology skill. Auto-routes to the right run-shape (A/B/C/D), sets up the run dir scaffold, points at the blind instructions, and invokes the scorer. Use when "run benchmark X", "score benchmark X", "benchmark this", "reproduce X benchmark", "跑 benchmark", "重跑 RTLLM", "score VerilogEval".
argument-hint: <bench> [--solve|--resume|--score --dataset <path> --run <path>] [--list]
---

# /vibe-ic-benchmark — turnkey benchmark runner

This command is the **front door** for every open IC-design benchmark. It enforces
the methodology from `open-benchmark-methodology` skill (§ 2 decision matrix → § 3
substitution disclosure → § 4 triage rubric) by routing to the correct run-shape
per the registry at `${CLAUDE_PLUGIN_ROOT}/benchmark/BENCHMARK_REGISTRY.json`.

## Modes

```bash
# 1. List all known benchmarks + their shape + status
python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py --list

# 2. Show plan for one benchmark (env check + recommended commands)
python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py <bench>

# 3. Set up a run dir (clones the registry's expected layout into <run>)
python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py <bench> \
    --setup --dataset <path-to-dataset> --run <run-dir>

# 4. Solve through the PROGRAM rail; this emits AI backup/review worklists
python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py <bench> \
    --solve --dataset <path-to-dataset> --run <run-dir>

# 5. After completing needs_ai_backup.jsonl / needs_ai_review.jsonl, converge
python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py <bench> \
    --resume --dataset <path-to-dataset> --run <run-dir>

# 6. Score only after dual_track_acceptance.json says COMPLETE
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
| **B** | `vibe_ic_one_shot_runner.py --skip-phase3 --skip-analog --skip-hardware` | `benchmark/score_iverilog_tb.py` | RTLLM |
| **C** | LLM authors per problem + `benchmark/gates_atomic.py` (each gate is a plugin program) | `benchmark/score_iverilog_tb.py` | VerilogEval-v2, VerilogEval-Human |
| **D** | `vibe_ic_one_shot_runner.py` (with `catalog-glue-author` if REUSED-IP) | `benchmark/score_cocotb_mcp.py` (MCP eda_cocotb / docker exec) | CVDP example, subservient-class |
| **E** | n/a — blocked / out-of-scope, document only | n/a | PyHDL-Eval (golden gated), RTL-Repo (wrong metric), MetRex / ResBench (different task / toolchain), CVDP-full (gated) |

For Shape B/C runs driven by `--solve`, the author column is only the first
rail. Every candidate must also receive an independent, blind AI routing and
semantic review. AI is the final semantic authority: it may accept the Program
route or issue an evidence-backed `OVERRIDE_PROGRAM`. If it rejects the RTL,
the result is `REPAIR_REQUIRED`, not permanent disagreement: AI repairs, the
Program gates re-run, and AI reviews the new hash. Program gates PASS + AI
semantic PASS is the sole scoreable acceptance state; `--score` hard-blocks
every incomplete or stale review. Reusable Program limitations remain visible
in `program_enhancement_candidates.jsonl` without blocking an evidenced item.

## Honesty (mandatory in any RESULT.md)
- Disclose every tool substitution (VCS → iverilog, DC → yosys+OpenROAD, nvidia/cvdp-sim → vibeic-eda).
- Run the scorer with `cwd=design_dir` so `$readmemh` relative paths resolve.
- Classify every residual fail into rubric category A-H (skill § 4); FLOOR ≠ "I gave up".
- Never publish a number from Shape E.
