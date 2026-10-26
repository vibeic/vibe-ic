---
name: vibe-ic-benchmark
description: Run any known open IC-design benchmark (VerilogEval-v2/Human, RTLLM, CVDP, …) through the same general IC-design path, then invoke its official scorer. Use when "run benchmark X", "score benchmark X", "benchmark this", "reproduce X benchmark", "跑 benchmark", "重跑 RTLLM", "score VerilogEval".
argument-hint: <bench> [--solve|--resume|--score --dataset <path> --run <path>] [--shape D] [--list]
---

**First: determine the requested output.** Open RTL evaluations (CVDP, VerilogEval, RTLLM) proceed through `--solve` and the per-record AI task-nature handoff below; do not ask the operator **"IC path or IP path?"** for an RTL answer. Read [IC Expert § 0.0](../agents/ic-expert-agent.md) before Phase 1: that question applies when a whole-chip or hardmacro benchmark requests physical delivery and the visible prompt leaves its route unclear. Preserve the owner's stated delivery choice for those physical runs.

# /vibe-ic-benchmark — turnkey benchmark runner

This command is the **general-flow front door** for dispatchable Shape B/C/D open
benchmarks and the registry guide for the other open run shapes. It enforces the
methodology from `open-benchmark-methodology` skill (§ 2 decision matrix → § 3
substitution disclosure → § 4 triage rubric) by routing to the correct run-shape
per the registry at `${CLAUDE_PLUGIN_ROOT}/benchmark/BENCHMARK_REGISTRY.json`.

`--solve` begins the route-and-solve lifecycle; it is not a direct solver entry.
For every problem, general Program code in `task_nature_route` makes an
input-only advisory proposal from the visible prompt and supplied-RTL state.
`--solve` then stops with `needs_ai_routing.jsonl`; a named AI actor must confirm
or override that proposal before any design runner starts. `--resume` validates
all hash-bound AI decisions. A whole-IC dispatch is current only when its saved
runner argv enters `vibe_ic_one_shot_runner.py` with `--flow 109`, an explicit
`--flow109-manifest`, a stable-ID `--entry-step`/`--exit-step` window, and
`--execution-mode default`. If the dispatcher cannot express that exact public
entry, it must refuse; it may not fall back to a former route. Benchmark name,
problem id, and dataset metadata never select a route. The proposal's
`needs_ai_parse` value is advisory and never bypasses this mandatory AI handoff.

## Modes

```bash
# 1. List all known benchmarks + their shape + status
python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py --list

# 2. Show plan for one benchmark (env check + recommended commands)
python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py <bench>

# 3. Stage visible input, make the Program routing proposal, and emit
#    needs_ai_routing.jsonl. No design runner starts in this invocation.
python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py <bench> \
    --solve --dataset <path-to-dataset> --run <run-dir>

# 3D. Explicit generic Shape-D JSONL I/O (for any dispatchable <bench>).
#     The selector chooses the protocol only, never the task nature.
python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py <bench> \
    --shape D --solve --dataset <agentic-jsonl-dir> --run <fresh-run-dir>

# 4. After a named AI actor completes needs_ai_routing.jsonl, validate every
#    route and run Program First. Repeat --resume for declared AI backup,
#    exact-candidate semantic review, and any evidence-backed repair.
python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py <bench> \
    --resume --dataset <path-to-dataset> --run <run-dir>

# 5. B/C score only after program_first_ai_review_acceptance.json says COMPLETE.
#    Shape-D official scoring is external/NOT_MEASURED; --score refuses agentic runs.
python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py <bench> \
    --score --dataset <path-to-dataset> --run <run-dir>
```

## Mandatory AI task-nature handoff

The canonical sequence for every dispatchable protocol is:

```text
Shape D: agentic_jsonl_to_shape_d.extract_dataset / extract_row
  -> separate coordinator/scorer extraction root
benchmark_io_adapter.stage (visible prompt/context only; B/C/D)
  -> task_nature_route Program proposal
  -> needs_ai_routing.jsonl
  -> named AI CONFIRM / OVERRIDE / NEEDS_CLARIFICATION
  -> --resume validates the complete route population
  -> normal runner entry/evidence exit
  -> Program candidate or declared AI backup
  -> independent AI semantic review of the exact candidate hash
```

The five selectable product natures and their default execution windows are:

| AI-selected nature | Entry | Default evidence / exit |
|---|---:|---:|
| `spec_generation` | `D1` | `lint_validated` / `2` |
| `completion` | `D1` | `lint_validated` / `2` |
| `functional_modification` | `D1` | `behaviour` / `4` |
| `optimization` | `2` | `area` / `9` |
| `debug` | `4` | `behaviour` / `4` |

Open RTL evaluations enter the runner with `--route ip` and stop at the
AI-selected RTL evidence window. Here `ip` means the module/IP evaluation
delivery path; it is not a hardmacro-readiness claim. Whole-chip benchmark
subjects continue to follow their owner-declared IC/DIE route and full flow.

An AI route response binds the issued task, visible prompt, staged public-input
snapshot, and current nature/entry/evidence tables by SHA-256. It also names the
AI model, states that no oracle was accessed, and supplies a rationale. An
`OVERRIDE` additionally cites an exact visible-input excerpt whose claim names
the selected nature. A missing, stale, unattributed, ungrounded, or
`NEEDS_CLARIFICATION` response keeps the whole issued batch pending and launches
zero design runners.

For Shape D, the coordinator owns `<run-dir>.shape_d_scorer/` beside the run
directory. Only extracted prompt/context/supplied RTL reaches
`<run-dir>/projects/<id>/`, the public-input manifest, and the runner project.
Harness, score and other row metadata remain in the separate coordinator tree.
`--resume` takes the I/O protocol from the hash-bound route task, verifies that
task against its immutable coordinator issue, and requires `.bench_config.json`
and `solve_report.json` to agree with it; omit `--shape` on resume. Issuances
created before `io_format` was bound into the route task are refused and require
a fresh `--solve` issuance. Debug and optimization reuse normal D1 provenance
before their fixed mid-flow entries. Official Shape-D scoring is external and
`NOT_MEASURED`, independent of routing completion.

Visible partial RTL remains input evidence. In particular, a VerilogEval-Human
prompt that asks to complete supplied partial HDL is preserved byte-for-byte in
the staged prompt; the Program may propose `completion`, but the AI still makes
the binding decision before the runner. For mid-flow `optimization` or `debug`,
the dispatcher first materializes or verifies hash-bound D1 provenance without
changing the prompt or supplied RTL, then retains the selected entry at `2` or
`4`. The runner receives the selected exit and skips Phase 3 when that exit is
before step `15`.

`benchmark_dispatch.py` does not call an LLM itself. The AI actor consumes the
worklist, writes the schema-bound response, and invokes `--resume`. Repository
tests using synthetic prompts prove these guards and transitions only; they are
not VerilogEval, RTLLM, or CVDP evaluation results.

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
| **A** | Flow109 public-entry window through `vibe_ic_one_shot_runner.py` | `benchmark-verify` skill (six pillars) | benchmark_clean ICs (spm, sha256, subservient, u_hawaii_adc) |
| **B** | general `benchmark_dispatch --solve` → `task_nature_route` → `vibe_ic_one_shot_runner` | `benchmark/score_iverilog_tb.py` | RTLLM |
| **C** | the same general solve path; shape affects only scorer-facing packaging | `benchmark/score_iverilog_tb.py` | VerilogEval-v2, VerilogEval-Human |
| **C (CVDP nonagentic)** | the same general solve path; CVDP JSONL is a thin I/O adapter only | official `run_benchmark.py` via `benchmark/score_cvdp_open.py` | CVDP open nonagentic tracks |
| **D (agentic JSONL)** | general `benchmark_dispatch --shape D --solve` → general extractor → the same named-AI handoff and runner lifecycle | external official Shape-D scorer, NOT_MEASURED; dispatcher scoring refused | CVDP open agentic tracks |
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
- `--allow-direct-agent` and `--allow-ungated` are explicitly non-canonical
  exploratory score overrides; never use their output as a published canonical result.
- Never publish a number from Shape E.
