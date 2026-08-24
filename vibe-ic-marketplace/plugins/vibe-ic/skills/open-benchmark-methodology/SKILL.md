---
name: open-benchmark-methodology
description: "MANDATORY consult any time these keywords appear: VerilogEval, VerilogEval-v2, VerilogEval-Human, CVDP, RTLLM, PyHDL-Eval, RTL-Repo, MetRex, ResBench, ChipAgentsBench, vibeic-bench, benchmark, pass@1, doc→RTL, doc→GDS, run benchmark, rerun benchmark, score benchmark, benchmark methodology, benchmark floor, benchmark defect. The doctrine: program-first, agent-only-on-failure — Vibe-IC's product is the deterministic runner chain (vibe_ic_one_shot_runner.py → phase1/2/3 + plugin programs + MCP-EDA), so a benchmark NUMBER must measure what the runner can do, not what a direct AI agent can do with the same MCP tools. This skill encodes (§1) where Vibe-IC is a program vs an LLM in v0.1.26+, (§2) the five canonical run-shapes (A=full-runner / B=runner --skip-phase3 / C=gates.py harness / D=agentic-with-runner / E=blocked-or-out-of-scope), (§3) mandatory tool-substitution disclosure (Synopsys VCS→iverilog, DC→yosys+OpenROAD, NVIDIA cvdp-sim→iic-osic-tools) + the cwd=design_dir rule, (§4) the triage rubric A-H separating FLOOR (benchmark-defect / under-spec / tool-gap / spec-ambiguity) from agent-fixable (description-clue-missed / convention-inference / real-RTL-bug), (§5) per-benchmark cheat sheet with current shape + status + any TARGET RE-RUN flagged, (§6) mandatory RESULT.md sections, (§7) tie-breakers, (§8) re-run obligations. Triggers also on phrases like 'run X benchmark', 'reproduce X', 'rerun X', 'is this the right method', '應該用什麼方法跑這個 benchmark', '怎麼測 X', '是否方法錯誤'. NEVER propose a benchmark run plan, interpret a benchmark result, or call something 'benchmark floor' without consulting this skill first."
---

# Open-Benchmark Methodology — program-first, agent-only-on-failure

This skill records the **canonical method** for driving any open IC-design benchmark through
Vibe-IC. The core doctrine, established by hard-won evidence from the 2026-05-28 benchmark
sweep (see `benchmark_external/RESULT_MCP_EDA_v0125_FRESH.md`, `benchmark_clean/RESULT_v0125_fresh.md`,
`benchmark_external/rtllm/RESULT.md`):

> **Vibe-IC's product is the deterministic runner chain** (`vibe_ic_one_shot_runner.py` →
> `phase1/2/3_one_shot_runner.py` + plugin programs + MCP-EDA tools). The benchmark NUMBER
> we publish must measure **what the runner can do**, not what a fresh AI agent can do with
> the same MCP tools.
>
> Direct-agent authoring (no runner) only tests "Opus + MCP-EDA" generic LLM-with-tools
> capability — that's not Vibe-IC's value proposition.

⛔ **Do not pick the run-shape by feel.** Read § 1 (taxonomy) and § 2 (decision matrix) below
before invoking any benchmark agent or runner.

## 🔒 RULE 0 (BINDING, owner directive 2026-07-03): benchmark ENTRY ≡ general-IC-design ENTRY

> **A benchmark problem MUST be solved through the SAME entry point a general IC design task uses
> — the real product runner (`vibe_ic_one_shot_runner.py <project>` → phase1 doc→L1-L24 → phase2
> spec-to-rtl WAIVE → runner gates).** There is exactly ONE solve entry; the benchmark does not get
> its own authoring path.

- **NEVER** author a benchmark answer through a bespoke benchmark-only harness (a hand-rolled
  `AUTHOR_INSTRUCTIONS.md` + a flat "prompt → drafts/ → gate" subagent loop). That measures
  "an AI agent with a tuned prompt", NOT "what the Vibe-IC runner can do" — the exact anti-pattern
  the program-first doctrine above forbids.
- The **only** benchmark-specific glue permitted is the thin IO shell: (in) stage each record as a
  project — `input.prompt` → `<project>/input/docs/design_description.md`, `input.context` files →
  `<project>/input/docs/` — and (out) the gate/scorer (`cvdp_gate.py` → official `run_benchmark.py`).
  Everything between IN and OUT is the general runner, unchanged.
- The **program-first → AI-backup dual path lives INSIDE the runner**: `design_one_shot_runner.
  step_rtl_gen` tries the deterministic RTL dispatch first (program), and on `rtl_gen=null` WAIVEs to
  the **`spec-to-rtl`** skill (AI-backup) which authors into `phase2/stage1/rtl/` — reading the
  runner's emitted **L1-L24 docs**, not the raw prompt — after which the runner's own gates
  (rtl_hygiene_lint, spec_conformance_check, reference_tb, yosys_synth) fire. Do not reimplement this
  outside the runner.
- **Consequence for scoring:** a number produced by any path other than this shared entry is NOT a
  Vibe-IC product number and must not be published as one (see § 7.5). If the general entry cannot yet
  solve a class, that is a real FLOOR/gap to CAPTURE (per `benchmark-enhancement-capture`), never
  something to paper over with a benchmark-only authoring prompt.

> ⭐ **The Benchmark Agent's #1 mandate is not the score — it is the LOOP** (owner directive
> 2026-06-22): **continuously converge → capture every fail into a solvable case → distill every
> generalizable fix into the deterministic PROGRAM layer**, so the next BLIND run auto-recovers it.
> Producing a number is only half the job; the other (load-bearing) half is closing the gap
> between the blind pass@1 and the converged 100 % by moving recoveries into `programs/*.py`. The
> full doctrine + bucket ladder lives in the **`benchmark-enhancement-capture`** skill — invoke it
> after EVERY benchmark close-loop. A benchmark run that scores but distills nothing has done only
> half the Benchmark Agent's job.

## § 0 — GENERAL-CORE / THIN-ADAPTER: benchmark convergence MUST flow back to general usage (BINDING)

> The reason we converge a benchmark is to make the **general Vibe-IC flow** (Phase-1 design docs,
> any user prompt) better — NOT to win a number. So every benchmark-convergence fix lands as a
> **benchmark-AGNOSTIC GENERAL CORE** (operates on plain prose + a supplied interface — named for
> what it does: `verilog_width_resolve`, `spec_complete_extract`, …) called by a **THIN
> benchmark ADAPTER** (the `cvdp_`/`rtllm_`/`verilogeval_` prefix is correct ONLY for the IO shell
> that maps that benchmark's record format → the general core). A fix trapped inside a
> benchmark-named module, unreachable from the Phase-1 path, has captured only half its value.
>
> **Naming test:** a `cvdp_…`/`rtllm_…`/`verilogeval_…` file whose LOGIC is pure prose/param
> handling (no record-format / dataset literal) is naming debt — rename to a neutral name so the
> next benchmark AND general usage reuse it. **Flow-back test:** a plain Phase-1 doc exercising the
> same spec shape must get the SAME completeness verdict with no harness present. Full doctrine +
> the bucket-A "done right" rule: `benchmark-enhancement-capture` → THE GENERAL-CORE / THIN-ADAPTER
> PRINCIPLE.

## § 1 — Where Vibe-IC is a PROGRAM and where it's an LLM (the boundary every benchmark designer must respect)

In v0.1.26 the plugin's `design_one_shot_runner.step_rtl_gen` for the `digital_arithmetic_primitive`
class (and any class whose `rtl_gen=null`) **WAIVES with `fallback_skill=spec-to-rtl`**. The
spec-to-rtl skill is an AI skill — there is **no deterministic spec→Verilog program**, because
natural language to RTL fundamentally requires a language model. What IS deterministic:

| Step | Deterministic program? | Where |
|---|---|---|
| Phase 1: NL prompt → L1-L27 JSON | ✅ | `phase1_engine` / `phase1_one_shot_runner.py` |
| ic_class detection + dispatch | ✅ | `design_one_shot_runner.py` + `ic_class_profile.py` |
| **spec → RTL authoring** | **❌ AI skill** | `spec-to-rtl` (fallback skill) |
| RTL hygiene (power-up `--fix`, latch repair) | ✅ | `rtl_hygiene_lint.py --fix` |
| Spec-conformance gate (ports/widths/reset) | ✅ | `spec_conformance_check.py` |
| Lint / synth / FPGA / cocotb (MCP-EDA) | ✅ | `eda_lint`, `eda_synth`, `eda_cocotb`, `eda_simulate` |
| Phase 3: PnR / DRC / LVS / STA | ✅ | `phase3_one_shot_runner.py` + OpenROAD/klayout |

The **runner wraps the AI authoring step inside a determined pipeline of gates** (hygiene, conformance,
lint, synth, audit) **and is what Vibe-IC actually delivers**. A benchmark that bypasses the runner
and lets an agent author RTL directly tests only "the LLM under our roof", not "Vibe-IC".

## § 2 — Decision matrix: which run-shape for which benchmark

> **Enforced by `programs/benchmark_shape_classify.py`** — derives the shape (A/B/C/D/E) for a
> NEW benchmark from its on-disk layout (module count, PDK/constraints target, prompt line-count,
> dataset cardinality, cocotb harness, oracle-gated flag). For a benchmark already in
> `benchmark/BENCHMARK_REGISTRY.json`, `programs/benchmark_dispatch.py` reads the recorded
> shape directly. The prose tree below is the human-readable spec the program implements — do not
> hand-pick a shape by feel; run the classifier.

For every new benchmark, answer these questions in order:

1. **Is the benchmark a full IC** (multiple modules, register map, FSM, SoC integration, with a
   constraints / floorplan / PDK target)? → **Shape A: full runner**.
2. **Is the benchmark a substantial standalone design** (counter / FIFO / FSM / ALU / arithmetic
   block with its own testbench) at the single-module level? → **Shape B: lightweight runner-path
   (skip phase3)**.
3. **Is the benchmark an atomic micro-problem** (≤ 30-line spec, single small module, one prompt
   file like VerilogEval `Prob001_zero_prompt.txt`)? Running the full runner is over-fitting the
   overhead; use **Shape C: gates-based lightweight harness**, which still drives plugin PROGRAMS
   for the verification gates (phase1_engine, spec_conformance_check, rtl_hygiene_lint --fix) but
   skips the runner's IC-level chrome.
4. **Is the benchmark an agentic SoC/multi-task problem** (CVDP-style cocotb harness, RTL-Repo,
   ChipAgentsBench)? → **Shape D: agentic-with-runner** (drive through `vibe_ic_one_shot_runner.py`,
   let `catalog-glue-author` fire if it's REUSED-IP shape).
5. **Is the benchmark's oracle gated, removed, or non-functional-metric**? → **Shape E: document
   as blocked / out-of-scope**, do NOT report a fake number.

### The four real shapes — concrete templates

#### Shape A — Full runner (chip-grade)
**When**: benchmark IC includes L1-L27 design-doc-style inputs (or upstream docs you transcribe into
L1-L27), targets a PDK, expects DRC/LVS/STA sign-off. Examples: `benchmark_clean/{spm,sha256,subservient,u_hawaii_adc}`.

```bash
# Path B: vendor docs already in input/docs/L*.md
python3 ${PLUGIN_PROGRAMS}/vibe_ic_one_shot_runner.py <project> \
    --pdk sky130A --ic-name <ic>
# Result: <project>/reports/orchestrator/vibe_ic_one_shot.json
```

Use agents ONLY when a step inside the runner FAILs (close-loop ECO, never as the primary author).

#### Shape B — Lightweight runner-path (substantial standalone, no silicon)
**When**: each problem is a real design with a testbench but you don't need PnR (e.g. RTLLM,
PyHDL-Eval-if-it-becomes-ungated). The `design_description.txt` (NL prose) is the spec.

Per-design setup — stage the prompt in **both** locations to work around the
`ORGANIC-20260528-phase1-prompt-md-not-ingested` gap (v0.1.30 doesn't auto-bridge):
```
<problem-project>/input/phase1_prompt.md          ← exactly the design_description.txt content
<problem-project>/input/docs/design_description.md ← copy of the same (what the ingester actually consumes)
```

Run the runner with phase3 skipped:
```bash
python3 ${PLUGIN_PROGRAMS}/vibe_ic_one_shot_runner.py <problem-project> \
    --skip-phase3 --skip-analog --skip-hardware
# Outputs RTL at <problem-project>/phase2/stage1/rtl/<top>.v
```

**Important** — the runner WAIVES `step_rtl_gen` for IC classes with `rtl_gen=null` in
`ic_class_registry.json` (currently: digital_arithmetic_primitive, digital_cmd_driven,
bare_fpga, processor_cpu, unknown_protocol_class — see
`ORGANIC-20260528-null-rtl-gen-classes-need-bridge`). When WAIVED, the runner explicitly
directs: *"AI invokes skill spec-to-rtl"*. There is no actual `spec-to-rtl` skill file —
the AI plays the spec-to-rtl ROLE: author RTL at `phase2/stage1/rtl/<top>.<v|sv>` using
the L docs the runner just emitted, then RE-INVOKE the runner so its downstream gates
(`chip_top_gate_wrapper_gen` / `rtl_hygiene_lint --fix` / lint / synth /
`spec_conformance_check` / `eco_loop` / `full_stack_tb_gen` / `final_audit`) fire on your
RTL. **This is NOT bypassing the runner — it IS the runner's design.** Bypass means
authoring with MCP only, outside the runner's pipeline (what the 2026-05-28 wrong-shape
RTLLM 37/50 did).

Then run the benchmark's host scorer (its testbench.v + iverilog/etc.) against the emitted
RTL. **The runner orchestrates; the AI fills the spec-to-rtl role inside the pipeline; the
runner's gates fire around it.**

#### Shape C — Lightweight gates-based harness (atomic micro-problems)
**When**: 156-500 atomic micro-problems per dataset, each a 5-30 line prompt yielding a single
small module. Examples: VerilogEval-v2, VerilogEval-Human. Running the full runner per problem
is overhead-dominated and offers no incremental signal.

Use a per-run `gates.py` that drives plugin PROGRAMS directly for verification while letting the
LLM author the RTL:

```python
# benchmark_external/<bench>/run_*/gates.py — canonical template
1. phase1_engine.cli run-all <spec.yaml> -> L*.json    # PROGRAM
2. spec_self_consistency_check.py --spec <prompt>      # PROGRAM
3. iverilog -g2012 compile of sample.sv                # PROGRAM
4. spec_conformance_check.py --rtl-dir . --spec <prompt> --top <module>  # PROGRAM
5a. rtl_hygiene_lint.py --fix <sample>      # PROGRAM (enforced! v0.1.24 lesson)
5b. rtl_hygiene_lint.py --severity WARN <sample>       # PROGRAM
6. MCP eda_lint + eda_synth (gf180 typically)          # PROGRAM
7. emit sample01.sv on hard-gates PASS
```

The agent's only authoring touch: write `spec.yaml` + `sample.sv` per problem. **Every verification
gate is a plugin program** — that's what makes the number meaningful, even though the runner-wrapper
isn't invoked. **The v0.1.25 enforced power-up `--fix` proved this matters**: a fix written into
the gates held across 17 fresh agents; the same fix as free-text guidance regressed.

This shape is documented in `benchmark_external/verilogeval_v2/run_fresh_v0125/gates.py` (canonical).

**Batch-dispatch ORCHESTRATION RULES — Shapes B/C (ORGANIC-20260605, REQUIRED):**
These bind EVERY batch fan-out shape — Shape C here AND Shape B (same
BATCHFILE/batches architecture; Shape D is a single project with no fan-out
and is exempt):
0. **GATE-AS-SOLE-EMIT-PATH（binding，先於其他 orchestration rules，跨
   shape — ORGANIC #529）**: every benchmark authoring / close-loop prompt
   MUST make the designated plugin gate/runner command the **ONLY emit
   path** — an agent that does not execute the program CANNOT produce a
   scoring artifact (the sample/response/report is WRITTEN BY THE GATE,
   never directly by the agent). Writing the program invocation as an
   expectation in prose（「請自驗」「建議跑 lint」）counts as NOT WRITTEN:
   v0.1.25 (17 fresh agents — the in-gate fix held, the same content as
   free-text guidance regressed) and the 2026-06-10 CVDP open-run (31
   fresh batch agents, ZERO spontaneous plugin-program calls; a remedial
   host gate sweep over 200 authored completions caught 20 hygiene fixes
   + 4 real compile breaks the agents' self-verification all missed)
   both prove free-text ALWAYS regresses. For a NEWLY-onboarded benchmark
   flow: if no existing gate program consumes that benchmark's IO format
   (e.g. CVDP's id/completion JSONL), **build the bridge first（gate
   program / format adapter — see `benchmark/cvdp_gate.py`）, then
   dispatch** — "no ready gate" is a harness backlog item, never a reason
   to go agent-first. Before dispatch the orchestrator must self-check:
   is this prompt's emit action program-enforced? If not, the run's number
   measures "LLM with tools", not Vibe-IC, and the RESULT.md must disclose
   that.
1. **Batch granularity** for ≥100-problem datasets: spawn ONE authoring agent per
   pre-split `batches/batchNN.list` — NEVER one agent per problem. A 312-problem
   per-problem fan-out lost ~93% of its agents' structured returns; the same
   problems re-run one-agent-per-batch (32 agents) completed 312/312.
2. **Disk truth**: the deterministic gate writes `samples/<Prob>_sample01.sv`
   regardless of whether the agent's structured return survives — reconcile
   progress by COUNTING on-disk samples, never by tallying agent returns. Resume
   = diff `problems.list` vs on-disk `samples/` and re-dispatch only the missing
   set. The scorer prints this disk-truth inventory up front and warns on a
   partially-authored run.
3. **Emit-blocking structural rules**: `gates_atomic.py` blocks emit on the
   corpus-swept allow-list (`onebased-port-range`, `fsm-output-style-mismatch`,
   and the OR/XOR form of `vector-self-shift-fold` WHEN the prompt requires a
   zero boundary for the assigned output — don't-care boundaries downgrade to
   advisories; the AND form is the legitimate masking idiom, WARN only) — the
   author must fix and re-run the gate; a blocked problem has no sample on
   disk, so disk-truth accounting automatically surfaces it.
4. **Transcript export is the DEFAULT** (ORGANIC-20260605-transcripts-export-default):
   `--setup` pre-creates `<RUNDIR>/transcripts/`; the orchestrator MUST export every
   authoring/close-loop agent's transcript there (named per agent) before scoring —
   `--score` audits them via `programs/blindness_audit.py` and refuses on violations.
   A run scored on the NOTICE branch (no transcripts) MUST disclose
   "blindness audit unavailable" in its RESULT.md.
5. **Rate-limit resilience ladder** (ORGANIC-20260605-ratelimit-resilient-dispatch-ladder):
   burst rate-limiting kills full-width fan-out within seconds (kill signature:
   sub-minute workflow death, zero/near-zero token usage, most agents nulled at once)
   and same-width retries die identically. On a burst kill: 1-agent CANARY completes a
   FULL batch first → resume at narrow width (2–4 concurrent, completion-driven
   dispatch, never barrier fan-out) → disk-truth reconcile remains the resume
   mechanism.
6. **Module-name source priority when prose and directory disagree**
   (ORGANIC-20260606 #482, dataset-agnostic): when the prompt's stated module name and the
   problem's directory / file leaf name DISAGREE (a dataset typo), author the module under the
   **DIRECTORY-LEAF name** as the TB-facing module name — hidden testbenches are generated against
   the file layout, and prose typos are common, so the literal prose name will fail to elaborate.
   Keep the prose name only when no directory/file convention exists. **Note the conflict in the
   sample header comment.** Close-loop / re-author agents MUST NOT "fix" a passing
   directory-leaf module name back to the prose typo (a re-author regressed exactly this way).
   *why_not_bucket_a*: distinguishing a typo from a genuine intended wrapper-name requires
   contextual judgment (read the prose against the file layout) — no regex separates the two.
7. **OWNERSHIP IS READ FROM DISK, NEVER FROM THE ORCHESTRATOR'S MEMORY**
   (2026-08-24 CVDP v1.11.72 run — FIVE assignment collisions in one run, all
   from the same root cause). Driving ~8 concurrent authoring agents, the
   orchestrator decided who owned what from its own dispatch history plus file
   mtimes. Both are unreliable:

   - **mtime is not liveness.** Three times an agent was declared dead after
     5–20 minutes of a quiet file and its batch reassigned; all three were
     alive. These agents take up to **7 minutes before their first write** and
     think for minutes between problems. A quiet file means SLOW, never
     ABANDONED. There is no mtime threshold that separates the two — do not
     look for one.
   - **A handoff needs BOTH sides told AND the old owner's acknowledgement.**
     Inter-agent messages are not synchronous. Twice the new owner was told
     "batch N is yours" and the old owner "drop batch N", and the second
     message landed after the old owner had already started. Correct order:
     tell the OLD owner to stop → wait for its ack → only then release to the
     new owner.
   - **A roster held in the orchestrator's head loses entries.** An agent
     dispatched early still held three batches; the orchestrator forgot and
     re-assigned two of them.

   **What made this survivable — brief every agent with all four:**
   (a) RE-READ the target file before every append and STOP + report if it
   holds lines you did not write — never append, never truncate;
   (b) a PRIVATE scratch dir per agent (a shared scratchpad let one agent's RTL
   be silently overwritten by another's, and the emitted record then paired one
   agent's prose with another's code);
   (c) never gate a file another agent may still be writing — two concurrent
   gate runs write the same responses file;
   (d) count and diff by ID, never by line count (rule 8).
   Every collision in that run was caught by an agent stopping to ask. Zero
   files were corrupted. **The brief saved the data, not the coordination.**

   **Verify a completion CLAIM on disk before recording it.** One agent
   reported a batch "gated 10/10" that existed nowhere in the run directory.
   An agent's report is a hypothesis; `ls` is the evidence.
8. **`wc -l` UNDERCOUNTS A JSONL — count by parsing, diff by id**
   (same run). `wc -l` counts NEWLINES. A JSONL whose last record was appended
   without a trailing `\n` reports one fewer than it holds, and under
   concurrent appends the total visibly oscillates.

   Measured cost in that run: two batches that were COMPLETE at 10/10 read as
   9 and 8, were diagnosed as unfinished, had agents dispatched to "finish"
   them, and one duplicate completion was authored before the id count and the
   line count disagreed loudly enough to notice. A separate 124→119 "drop" was
   read as a truncation that never happened.

   ```python
   n       = sum(1 for l in open(f) if l.strip())            # count
   missing = [i for i in want if i not in have]              # what to author
   ```
   Verify integrity with the id multiset (duplicates / foreign ids), not the
   length — a file can have the right count and the wrong contents. Put this in
   the agents' brief too; they reach for `wc -l` as readily as the orchestrator.

#### Shape D — Agentic with runner (SoC / multi-task)
**When**: agentic benchmarks where the unit-of-work is a full SoC + cocotb harness (CVDP). The
runner is the right tool because (a) the IC needs `ic_class` dispatch, (b) `catalog-glue-author`
should fire for REUSED-IP, (c) the cocotb harness must be invoked via MCP `eda_cocotb`.

```bash
# Same as Shape A; CVDP-style problems differ only in that the hidden scorer is cocotb
python3 ${PLUGIN_PROGRAMS}/vibe_ic_one_shot_runner.py <problem-project> --pdk sky130A
# Then score via MCP eda_cocotb against the hidden harness in score/src/
```

Examples: `benchmark_clean/subservient_v0125_fresh` (REUSED-IP SoC path).

#### Shape E — Blocked / out-of-scope
**When**: the benchmark's golden oracle is gated, removed, or the metric isn't functional generation.

**Document it honestly in the RESULT.md**, do NOT fabricate a number. Examples this session:
- **PyHDL-Eval**: 168 RefModule golden Verilog solutions deliberately removed from the public repo
  (README confirms anti-training-contamination). `_test.v` needs RefModule to elaborate → can't
  score officially. Same gated-oracle situation as CVDP full.
- **RTL-Repo**: next-line autocompletion scored by Edit-Similarity + Exact-Match (string match
  to upstream verbatim). Not spec→RTL functional generation; anti-correlated with vibe-ic's
  correct-by-construction value.
- **CVDP full**: 1,500+ problems gated by NVIDIA/Turing access (only the public N=1 example
  problem runnable).

## § 3 — Tool-substitution disclosure (mandatory in every RESULT)

Open benchmarks frequently mandate commercial EDA tools we don't have. Every RESULT.md MUST
state the substitution explicitly.

> **Enforced by `programs/tool_substitution_disclose.py`** — holds the canonical lookup (Synopsys
> VCS→iverilog 12, Design Compiler→yosys+OpenROAD, Xcelium→iverilog, `nvidia/cvdp-sim`→`hpretl/iic-osic-tools`)
> and (a) emits the mandatory RESULT.md disclosure block (`--all` / `--mandated <csv>`) and
> (b) verifies a produced RESULT.md actually carries the disclosure for the tools it used
> (`--verify RESULT.md --mandated <csv>`, FAILs on an undisclosed substitution or an unknown tool).

> **`cwd=design_dir` rule — enforced by `programs/benchmark_score_cwd_guard.py`.** Run the host
> scorer FROM the design directory (`cwd=<design>`) so the TB's relative-path
> `$readmemh("reference.txt")` etc. resolves; the guard asserts `cwd==design` and that every
> relative `$readmemh/$readmemb/$fopen` target exists under cwd before the TB runs. RTLLM's own
> `auto_run.py` does `os.chdir(design); make vcs`; forgetting this caused 3 false fails in our
> 2026-05-28 RTLLM run.

## § 3.9 — SPEC-FIRST COVERAGE ATTRIBUTION before any FLOOR label (ORGANIC #697, BINDING)

A hidden scoring testbench is generated from the **same specification the author sees**, so
everything the scorer checks is — by construction — a SUBSET of the spec UNLESS the benchmark
couples to something the spec never states. **"Spec" is the ENTIRE input chain** — a requirement
is "in spec" if it exists at ANY station: input prompt (USER) → structured input / fact graph (PM
AGENT) → Design Documents / L1-L27 (IC EXPERT AGENT) → spec-to-rtl authoring (RTL). Therefore a
verification FAILURE is almost always **one of our own gaps**, not an unfixable floor:

  - **(1) SPEC-EXTRACTION GAP** — the requirement EXISTS somewhere in the chain but was not carried
    end-to-end. The fix routes to the **LAST station that still held it**: prompt had it but the
    fact graph dropped it → **ic-expert-agent** elicitation (plain-language register); fact graph had it but the L-docs dropped it →
    **ic-expert-agent** L-doc completion; L-docs/prompt had it but spec-to-rtl didn't read it out →
    **spec-to-rtl** extraction.
  - **(2) TESTBENCH-COVERAGE GAP** — we DID extract it, but our own self-TB never exercised it, so
    the bug passed our gate and only the hidden TB caught it. Fix: enhance our TB coverage.

EVIDENCE (CVDP cvdp-open behavior-level audit, oracle used for RCA only): **80/136 = 59 % of
failing TB checks were IN-SPEC** (our extraction/coverage gap); only 56/136 were genuinely
not-in-spec. A majority of the residual was initially mis-shelved as "FLOOR".

> **PROGRAM-FIRST gate — `programs/spec_coverage_check.py` fires automatically:**
> ```bash
> python3 programs/spec_coverage_check.py \
>     [--prompt PROMPT] [--fact-graph FG] [--ldocs L1-L27_DIR] \
>     [--rtl RTL] [--tb TB] [--failure "<failing behavior>"] [--strict] [--json OUT]
> ```
> (`--spec` is the back-compat alias for `--prompt`.) It extracts a DETERMINISTIC checklist of
> testable requirements from EVERY provided chain station (ports/widths/directions, reset
> value+polarity+sync/async, stated timing/latency, every table row, every worked example,
> **every ENUMERATED SET + its outside-the-set/default boundary**, signed-ness, byte order/packing,
> overflow/saturation/rounding, handshake timing), MERGES identical requirements across stations
> (recording the most-downstream holding station), attributes each to whether the authored TB
> exercises it (TESTBENCH-COVERAGE GAP = WARN default, BLOCK in `--strict` sole-emit), and on a
> failure attributes it to **coverage-gap / extraction-gap (with `route_to:` ic-expert-agent /
> ic-expert-agent / spec-to-rtl) / spec-absent**.

**BINDING RULE: a fail may be labelled FLOOR (Category A–E below) ONLY AFTER `spec_coverage_check
--failure "<behavior>"` returns `spec-absent` with the searched stations cited as evidence** (the
behavior is NOWHERE in the chain — white-box internal name / cross-problem convention / unstated
value). If it returns `extraction-gap`, route the fix to the named station; if `coverage-gap`,
enhance our TB — either way it is OUR gap, NOT a floor. The most-missed pattern is an **ENUMERATED
SET whose outside-the-set/default behavior is stated but untested**: the checklist extractor always
emits that boundary item.

**Judgment boundary (honest, not faked in the program):** the program does the pure-STRUCTURAL
extraction (tables / worked examples / port list / enumerated sets / reset+latency keyword facts),
the cross-station merge, and the per-station routing — all deterministic. The residual READING
judgment — *does THIS prose sentence state a testable requirement* — is the LLM step you perform
here. The program never invents a requirement out of free prose (every checklist item is anchored
to a structural feature), so a white-box internal name the chain never states is NOT charged as
our gap.

## § 4 — Triage rubric: agent-fixable vs FLOOR

Every benchmark run produces residual fails. Categorize each into ONE of these buckets BEFORE
spending compute on close-loop. **This A-H classification is the irreducible LLM core of this
skill** — separating a genuine spec ambiguity (E, FLOOR) from a missed-clue (F), a genre
convention (G), or a real RTL bug (H) requires reading the spec prose against the RTL+TB and
making a meaning judgment; no regex does that.

> **Gate first (§ 3.9):** before assigning Category A–E (FLOOR), run `spec_coverage_check
> --failure`. A `coverage-gap` is Category F (our TB missed an in-spec requirement); an
> `extraction-gap` means enhance extraction (our flow missed an in-spec requirement); only a
> cited `spec-absent` may proceed to A–E FLOOR.

> One mechanical sub-case is extracted: **Category D (tool-substitution gap) detection is
> enforced by `programs/tb_vcs_only_construct_detect.py`** — it scans the failing TB for the
> iverilog-rejecting VCS/Xcelium-only constructs (array-aggregate `'{...}` init, `break;`/`continue;`,
> `std::randomize`, `$urandom_range`, `unique/priority case`, `join_none`, queue ops) and reports
> the offending line as FLOOR-D evidence. Use it to auto-classify D; A/B/C/E-H stay judgment.

| Category | Description | Action |
|---|---|---|
| **A. Benchmark description ↔ TB inconsistency** | Spec says one port name; TB wires a different one | **FLOOR** — unsatisfiable blind without cheating. Document with TB-line evidence. |
| **A2. Harness contradicts the GIVEN context itself** | The GIVEN input (prose + any given/gate-target RTL) is *directly functionally contradicted* by the TB oracle — provable with NO external info (e.g. TB pins opcode 2'b10=NAND/2'b11=NOR, but the only given mapping is the opposite and NAND/NOR are never mentioned) | **FLOOR** — stop converging immediately. Prove it with the floor-proof protocol below (cross-round expected-vs-got + replay under the design's OWN TB); the given context alone is the evidence. |
| **B. Benchmark under-specification** | TB needs a port/param/parameterization the prose never states | **FLOOR** — same |
| **C. Positional-instantiation convention** | TB uses positional with an undocumented port order | **FLOOR** |
| **D. Tool-substitution gap** | TB uses VCS-only / Xcelium-only constructs, or a language feature our OSS substitute (iverilog / Verilator / yosys / OpenROAD / ngspice / magic / netgen) can't yet run or crashes on | **FORK-FIXABLE — NOT a terminal floor.** We FORK the EDA tools (`vibeic/{OpenROAD,yosys,iverilog,verilator,magic,netgen,ngspice}`, shipped as `vibeic-eda`), so a "our tool can't do X" fail is an ENGINEERING BACKLOG ITEM against the fork, routed to `tools/vibeic-eda/FIX_STATUS.md`. **MANDATORY before you may even LABEL it Category-D** (the asyn_fifo lesson): run the § 4.1 floor-proof — build+run the GOLDEN under a tool that DOES support the missing feature (e.g. Verilator `--timing` for a `break;`/`#delay` TB, or the forked iverilog). If the golden PASSES there → confirmed genuine tool-gap → open/track the FIX_STATUS row (add the feature to the fork; a real language feature / algorithmic gap ONLY — NEVER patch a tool to "pass benchmark X": that is the § 4 / § 9 over-fit prohibition — the fork dissolves the CAPABILITY floor, not the honesty boundary). A genuine algorithm-hard port honestly DEFERRED (`FIX_STATUS` 🔷) is a KNOWN-DEFERRED engineering item, still NOT an unfixable floor. **If the golden ALSO fails under the supporting tool → it was NEVER a pure tool-gap; re-triage as A/A2/B/E (dataset/RTL), NOT D.** (Worked example: the RTLLM `asyn_fifo` official TB uses `break;` which stock iverilog 12 rejects; the golden compiles+PASSES under Verilator 5.020 `--timing` AND the forked iverilog 14-devel in `vibeic-eda:0.2.5` → confirmed genuine tool-gap → already fork-closed, `FIX_STATUS.md` Tool 5 iverilog `break;`/`continue;` 🟢.) |
| **E. Spec-ambiguity functional mismatch** | DUT compiles + runs; spec admits ≥ 2 valid readings (e.g. shift vs rotate, registered vs comb output, phase convention); TB picks one | **FLOOR** — leave spec-faithful, do NOT over-fit to the hidden oracle. Close-loop's job is to confirm own-TB-passes, not to converge on the hidden TB. |
| **F. Description had it, agent missed it** | The clue WAS in the prose (e.g. "whether the result has been consumed" implies a downstream-ready input); agent overlooked it | **AGENT-FIXABLE** — close-loop after closer re-reading |
| **G. Conventional shape inference** | A canonical pattern (e.g. parameterized pipelined adder uses DATA_WIDTH/STG_WIDTH) the agent should have inferred from genre, not from explicit prose | **AGENT-FIXABLE** with a "convention sweep" close-loop pass |
| **H. Real RTL bug** | Algorithm wrong, off-by-one, wrong feedback polarity | **AGENT-FIXABLE** by blind re-derivation + own-TB self-verify |

Honesty check: if you're tempted to label something Category A-D to avoid a hard close-loop, **first
re-read the description top-to-bottom** for clues (Category F/G). The 2026-05-28 RTLLM triage
under-estimated the recoverable fails (radix2_div, adder_pipe_64bit, LFSR) by failing this check.

#### § 4.04 — AREA-OPTIMIZATION problems: MEASURE, and look for oversized TYPES (2026-08-24)

A prompt that demands a measurable reduction ("wires −19%, cells −22%") is not
satisfied by clean-up. **The synthesis tool has already done the clean-up.**

Measured on CVDP `cont_adder_0045`: removing a dead 32-bit register, sharing a
four-times-repeated adder, and folding six parameter comparators into two
(`(x>=T1)||(x>=T2)||(x>=T3)` ⟺ `x >= min(T1,T2,T3)`, exact for any signed
parameters and free because the min folds at elaboration) produced:

    original   wires 411  cells 591
    "optimized" wires 411  cells 591     ← 0%

Yosys already performs dead-code elimination and common-subexpression sharing.
Hand-writing them changes nothing.

**Where the wins actually are — the counter-example, `sorter_0059`:** loop
variables declared `integer` (32-bit) for values 0..8, sized to the range →
**−36.8% wires / −36.5% cells**, cycle-identical over 60 runs. The pattern is an
**OVERSIZED DECLARED TYPE**, which no synthesis pass may narrow because the
width is exactly what the source states. Look for `integer` indices,
default-width literals, counters wider than their range, and accumulators sized
above their proven bound.

**Two binding consequences:**

1. **Measure before accepting.** Run
   `yosys -p 'read_verilog -sv f.sv; synth -top T; stat'` on BOTH the original
   and the candidate, and put the before/after in the deliverable's header. An
   unmeasured area answer is a guess, and this class of guess measured 0%.
2. **State which yosys.** 0.33 and 0.68 reported materially different
   reductions for the identical change (−36% vs −26%). The official scorer uses
   its own container's yosys, not the host's, so a margin that clears the
   threshold locally may not clear it under scoring.

## § 4.05 — Verifying a guard-RELAXING fix: the NEGATIVE no-leak proof is the load-bearing half (ORGANIC #511)

When the fix you are verifying **relaxes a guard** — a new exemption, an allow-list entry, a
waiver path, a lint severity carve-out, a coverage advisory demotion, an audit/blindness
false-positive suppression — **the positive case alone is NOT sufficient to call it ADEQUATE.**
The positive case ("the thing that was wrongly flagged now PASSes") only proves the relaxation
*fires*; it says nothing about whether the relaxation is **too wide**.

> **Acceptance for any relaxation = (positive real case PASSes) AND (every NEGATIVE still caught).**

A too-wide exemption **leaks**: it silently waves through real violations it was never meant to
cover. This asymmetry is the whole point — a false-positive costs one wasted re-run, but a
**leaking exemption ships a real defect as PASS**. So the negative proof is the load-bearing
half of verifying a relaxation.

**How to build the negative no-leak proof**: author fixtures that sit JUST OUTSIDE the
exemption's intended boundary — structurally near-identical to what it legitimately passes, but
differing in exactly the property that should still trip the guard — and assert the guard STILL
catches them (FAIL/flag).

Worked example (the #504 round-2 blindness exemptions: assignment-RHS storage; OR-fallback
right-branch family-stem twin):
- **Positive**: the real 9-transcript run now PASSes (exit 0).
- **Negative no-leak (boundary-outside, 4/4 still caught, exit 1)**: ① a direct oracle read
  `cat testbench.v` → flagged; ② a directory listing `ls dir/` → flagged; ③ an OR-fallback
  whose RIGHT branch reads the ORACLE (not a name-stem twin) → flagged; ④ a fake pair broken by
  a `;` whose second statement independently reads the oracle → flagged.
  4/4 still caught → the exemption is tight enough → ADEQUATE.

This binds **every** guard-relaxing fix across the whole flow — DRC/LVS/ERC waiver paths, lint
severity carve-outs, coverage advisories, audit allow-lists, blindness exemptions. The
asymmetry is universal, so the **negative no-leak proof is the load-bearing half of verifying
any relaxation**. (This is an LLM-judgment step: deriving a *meaningful* boundary-outside
negative requires understanding what the exemption *intends* to wave through — the leaking and
the legitimate case are structurally identical except for the semantic property the reviewer
must reason about; no regex derives it from the exemption code itself.)

### § 4.06 — CONFIRMED-SYSTEMATIC tool blocker: fix the fork ROOT CAUSE after ≥ 2 designs, THEN a single clean re-run — do NOT grind every design into a known wall (BINDING)

When a clean-room evaluation of a **NEW or FORKED tool distribution** surfaces a
**SYSTEMATIC, root-cause-identified TOOL regression** — a tool / image bug, **NOT** a
design / RTL issue (Category-D territory, § 4 row D) — that is confirmed on **≥ 2
independent designs**, **STOP running additional designs into the same known blocker.**
Characterize just enough to confirm it is systematic (≥ 2 designs) + capture the root
cause + the per-design manifestation, then **FIX the tool root cause** (fork patch /
image fix, routed to `tools/vibeic-eda/FIX_STATUS.md`), THEN do a **single clean re-run**
of the affected designs. Do **NOT** exhaustively grind every remaining design into a
known wall — that only manufactures predictable tool-induced FAILs and burns compute for
zero new signal.

> **Refines the standing cadence, does not replace it.** The general rule stays
> "characterize fully → fix once → re-run once". This section narrows one word: for a
> **CONFIRMED-SYSTEMATIC** Category-D / fork-fixable tool blocker, **"characterize fully"
> means "≥ 2 independent designs confirming it is systematic", NOT "all designs".**

Guard-rails so this never becomes an excuse to under-characterize or to over-fit:

1. **The § 4.1 floor-proof still gates the Category-D label itself.** Before you may call
   the blocker a tool-gap at all, the GOLDEN must PASS under a tool that supports the
   missing feature; if the golden ALSO fails it was never a pure tool-gap — re-triage as
   A/A2/B/E (dataset/RTL), and this section does NOT apply. This section governs only
   *how many designs you drive into a blocker you have ALREADY confirmed is a systematic
   tool root cause*.
2. **The § 4 row-D / § 9 over-fit prohibition still binds.** You fix the tool
   **CAPABILITY** (a real feature / real regression), never patch a tool to "pass
   benchmark X". The fork dissolves the capability floor, not the honesty boundary.
3. **"Systematic" needs a named root cause, not just two coincident FAILs.** Two designs
   confirm systematic only when the SAME identified tool root cause (same warning / same
   code path) produces both — otherwise keep characterizing.

**Illustrative example (general — any tool, any systematic blocker; no chip / benchmark
literal gates this):** a post-route antenna-repair residual first appears as a single
deferred candidate on one design; the **IDENTICAL** tool warning — e.g. an antenna
`repair_design` that performs only one repair iteration in a newer OpenROAD build —
then re-hits on two further designs, a 3-design confirmation. The correct move is to
**pause after the 2nd confirmation**, fix the fork tool root cause, then re-run the
affected designs once — **not** to push the 4th, 5th, … design through the same warning
just to "complete the sweep".

**Disclosure (enforced by `compliance.yaml` → cross-check `X_known_blocker_needs_issue_ref`):**
once a tool blocker is captured / backlogged as known-systematic, a RESULT.md that hits
it MUST disclose it as a *known-systematic tool blocker* citing its tracking issue —
e.g. `known-systematic tool blocker (#NNN) — full flow deferred pending tool fix` —
**NOT** report it as a fresh design FAIL. Claiming "known-systematic" without an
issue / backlog citation is an unsupported claim and FAILs the check.

### § 4.2 — program-first + AI-backup: the AI must TRY, and a general no-cheat recovery MUST be absorbed (user directive 2026-06-18, BINDING)

> **Binding rule:** every benchmark fail case must be **DUAL-verified** — by a
> **PROGRAM** (the plugin scorer / gate) AND by an **AI independent blind solve**.
> The AI must genuinely **TRY ITS BEST** to solve each fail. **IF the AI CAN solve
> it with a GENERAL + NO-CHEATING method, that recovery MUST be absorbed into the
> plugin** — as a deterministic **PROGRAM rule**, OR as an **AI step GATED BY A
> PROGRAM**. A `RECOVERABLE_AUTHORING` / `AUTHORING` label is **NOT a free pass to
> skip** the absorption.

This is the program-first/AI-backup doctrine of `benchmark-enhancement-capture`
(#716 dual-track convergence) applied at the benchmark-campaign exit gate. The
A–H triage (§ 4) classifies; this subsection states the **convergence bar** that
the classification must clear before you may claim a campaign converged.

- **no-cheating** = does NOT over-fit the hidden testbench (Category E) — reads
  only legitimate spec clues / genre conventions (the whole input chain of § 3.9).
- **general** = chip/problem-**AGNOSTIC** (no SKU/poly/address/port-order literal).

A benchmark campaign **CONVERGES only when every residual fail is one of**:

1. **TRUE_FLOOR** — the AI **also** cannot solve it without cheating, the golden
   is self-consistent, AND the spec genuinely under-discloses. This requires the
   FLOOR-proof (§ 4.1, #724): the independent blind solve must have actually been
   **run and FAILED** (`independent_blind_passes == false`). A FLOOR **label is
   not evidence** — labelling something FLOOR cannot dodge a hard solve.
2. **DATASET_DEFECT** — the golden **fails its own TB** (run it; quote the
   assertion).
3. **ABSORBED-RECOVERY** — its AI-recovery has been absorbed into the plugin
   (deterministic program OR AI-step-gated-by-program) **and field-verified**.
   Route the absorption via `benchmark-enhancement-capture` (Bucket A program
   rule preferred; Bucket B = AI skill step, always paired with a program gate
   per the §4.05 no-leak proof). `RECOVERABLE_AUTHORING` / `LESSON_GATE_GAP` /
   `SCORING_HARNESS_GAP` / `EXTRACTION_GAP` / `COVERAGE_GAP` / a blind-solve that
   PASSED — **all of these are AI-solvable and MUST carry an `absorption_ref`.**

> **PROGRAM-FIRST enforcement (prose alone regresses — this codebase's repeated
> lesson; v0.1.25 in-gate fix held, the same as free text regressed):** before
> claiming convergence, run the machine-checkable convergence bar over the triage
> result:
> ```bash
> python3 programs/benchmark_triage_absorption_audit.py <triage-result.json> [--json OUT]
> ```
> It ASSERTS that every fail whose verdict implies AI-solvability carries an
> `absorption_ref`, and that any `TRUE_FLOOR` / `DATASET_DEFECT` exemption carries
> `floor_evidence` (a `TRUE_FLOOR` additionally requires `independent_blind_passes
> == false`). Exit 0 = PASS (converged), nonzero = FAIL (lists the un-absorbed
> AI-solvable fails). This pairs with `triage_record_check.py` (§ 4 / § 6.4 A–H
> self-consistency) and `convergence_doctrine_present_check.py` (#716).

This audit is itself a **guard that must not leak** (§ 4.05): the `TRUE_FLOOR` /
`DATASET_DEFECT` exemptions are guard-relaxing carve-outs, so they require
positive **evidence** — they cannot wave through an un-solved, un-absorbed,
AI-solvable fail. The deterministic half is the bookkeeping assertion above; the
READING judgment — *is this genuinely a floor or did the AI just not try hard
enough* — stays the § 4 LLM core.

### § 4.1 — Default action on a benchmark run: CLEAN-ROOM FULL re-run (user directive 2026-06-04)

> **Enforced by `programs/benchmark_dispatch.py` (clean-room default) +
> `programs/benchmark_clean_room_check.py` (front-door guard)** — `--setup` scaffolds a FRESH
> run dir with an EMPTY `samples/` and refuses to build on top of a prior run's samples;
> `--score` runs the clean-room guard first and REFUSES to score a contaminated run.

> **User policy (binding, 2026-06-04 — SUPERSEDES the 2026-05-29 "re-attempt the FAILing set by
> default" policy)**: "Run vibe-ic Benchmark 一定是重跑，一定重跑。不要拿舊的資料，也不要用
> memory，也不要用原來 storage 裡面的東西，一定是重跑。"

When the user asks to "run `<bench>`", the **default and only honest measurement is a CLEAN-ROOM
FULL re-run**: a fresh agent authors **EVERY** problem in the benchmark from the spec alone, with
the authoring context starting **EMPTY**. A clean-room run MUST NOT read:

1. **prior run samples / artifacts** (no inheriting previously-passing RTL — that contaminates
   the published pass@1 by mixing fresh authoring with stale prior-session authoring);
2. **agent memory** (no "I solved this last time" recall);
3. **any cached result in storage** (no reading a prior `pass_at_1.json` / `cocotb_score.json`
   to decide what to author);
4. **any dataset file other than the current problem's prompt** — explicitly including OTHER
   problems' reference solutions / testbenches (ORGANIC-20260605-blindness-rule-cross-problem-refs)
   AND dataset BUILD files (Makefile / *.mk / run scripts — they encode the dataset's module-name
   and flow authority). Sibling references encode the dataset's authoring conventions (axis
   orders, sampling phases, encoding styles); calibrating against them is dataset-internal
   solution knowledge that satisfies the letter of "don't read THIS problem's hidden files"
   while violating prompt-only blindness. This binds single-shot authors AND every close-loop /
   repair / convention-sweep agent — write the prohibition into every close-loop prompt you spawn;
5. **the host scorer** — no agent-side `score_*.py` / `benchmark_dispatch --score` invocation and
   no verdict-level oracle query mid-loop (ORGANIC-20260605-blindness-deterministic-audit-guard);
   scoring is the HOST's post-generation step, and an agent's self-verification means its OWN
   testbench only. Enforcement is deterministic, not prose: export batch-agent transcripts to
   `<RUNDIR>/transcripts/` and `programs/blindness_audit.py` audits them at the score front door
   (wired into `benchmark_dispatch.py --score`) — any non-prompt dataset access or command-shaped
   scorer invocation FAILs the run before scoring.

Why clean-room is the only honest number: re-running only the prior FAILing set inherits the
prior PASSes, so the headline mixes a fresh agent (on the fails) with an arbitrary prior session
(on the passes). That is not "a fresh agent on this benchmark today" — it is contaminated. A full
re-run also automatically re-attempts every prior FLOOR (no case is ever skipped on a stale
label), which preserves the original rationale (prior categorisation may be wrong; the plugin
compounds; a previously-FLOOR case can silently become PASS) **as a property of the full re-run**,
not as a reason to scope down to the failing set.

Operational rule (DEFAULT, do not ask the user):
- **Author the FULL problem list blind**, fresh, on the current plugin version, into a FRESH run
  dir whose `samples/` started empty.
- A FLOOR label may only be (re-)applied from THIS run's evidence (TB line, iverilog log,
  descriptor quote), never copy-pasted from a prior RESULT.md.
- Re-attempting **only** the prior FAILing set is an **explicit OPTION**, never the default:
  `benchmark_dispatch.py <bench> --setup --floor-only …` (also surfaced by `--reattempt-floor`).
  Even then it re-authors each selected problem **blind into a fresh dir** — no inherited samples.

This rule overrides any "skip, it's a known FLOOR" or "just re-run the fails" instinct. Encoded in
`programs/benchmark_dispatch.py` (clean-room default; `--floor-only` opt-in) and guarded by
`programs/benchmark_clean_room_check.py`.

## § 5 — Per-benchmark cheat sheet (current as of v0.1.26)

> **Enforced by `benchmark/BENCHMARK_REGISTRY.json`**, loaded by
> `programs/benchmark_dispatch.py` (`--list` / `--show <bench>`). The table below is a
> human-readable snapshot — the registry JSON is the source of truth that drives dispatch; if the
> two ever disagree, the registry wins. Do not hand-edit run plans from this table; consult the
> program.

| Benchmark | Shape | Authoring entry | Scoring | Status | Notes |
|---|---|---|---|---|---|
| VerilogEval-v2 (156) | **C** | `gates.py` + LLM | host iverilog + `<Prob>_test.sv` | Done 152/156 = 97.44% | Floor: 062/093/099/149 dataset defects |
| VerilogEval-Human (156) | **C** | `gates.py` + LLM | host iverilog + `<Prob>_test.sv` | Done 153/156 = 98.08% | Floor: 062/093/149 |
| RTLLM v2 (50) | **B** (CORRECT) — was done **C** in 2026-05-28 by mistake, target a re-run | `vibe_ic_one_shot_runner.py --skip-phase3 --skip-analog --skip-hardware` | host iverilog + `testbench.v` (cwd=design) | 37/50 = 74% under wrong-shape; target re-run to measure runner | Iverilog-tool-gap floor: `ring_counter`, `asyn_fifo` (VCS-only TB constructs) |
| CVDP (N=1 example) | **D** (CORRECT) — was done as direct-agent in 2026-05-28, target re-run | `vibe_ic_one_shot_runner.py` | MCP `eda_cocotb` against hidden harness | SUPERSEDED by cvdp-open | spec/harness reset-polarity inconsistency → async-reset resolution |
| **cvdp-open (749, HF v1.1.0)** | **C/D** | nonagentic: local_export → blind author → `cvdp_gate.py` (sole emit); agentic: official docker agent. ⚠️ **This is DIRECT-AI-AUTHOR gated by `cvdp_gate.py`, NOT the Phase-1 runner chain — see § 5.1.** | official `run_benchmark.py` + OSS sim image (run `cvdp_env_preflight.py` FIRST, #536) | RUNNABLE — 302-problem no_commercial track scored 210/302 = 69.5% single-shot **(blind-author number; a Phase-1-entry number is NOT yet established — TARGET RE-RUN, see § 5.1)** | HF v1.1.0 dataset `nvidia/cvdp-benchmark-dataset`; sim image fully OSS (icarus 13 / yosys 0.40 / cocotb 2.0.1) — NO tool substitution; triage via `cvdp_fail_triage.py` (#534) |
| PyHDL-Eval (168 Verilog track) | **E** (BLOCKED) | n/a | n/a | Documented blocked — 168 RefModule golden removed from public repo | Self-built-oracle subset is possible but not official pass@1 |
| RTL-Repo (~4000) | **E** (OUT OF SCOPE) | n/a | n/a | Documented out-of-scope — Edit-Similarity / Exact-Match string metric, not functional generation | |
| CVDP full (1500+) | **D** if access granted | runner | cocotb | SUPERSEDED by cvdp-open (749 open via HF v1.1.0); remainder stays gated | |
| benchmark_clean (4 ICs) | **A** | `vibe_ic_one_shot_runner.py` | per-IC cross-check + 6-pillar verify | Done — all 4 PASS_WITH_WAIVERS / analog PASS | sha256 close-loop fixed `phase3` set_wire_rc + setup-repair (v0.1.26) |
| MetRex (25,868) | Not pursued | n/a | n/a | Metric *reasoning* (predict area/delay/power), not generation | |
| ResBench | Not pursued | n/a | n/a | FPGA resource metrics; different toolchain | |
| ChipAgentsBench | Not yet public | n/a | n/a | Plan to re-evaluate when subset releases | |

### § 5.1 — LESSON (2026-07-05): CVDP has TWO entries; every published CVDP number so far is the BLIND-AUTHOR entry, not the Phase-1 runner

**Root cause found by driving CVDP through the Phase-1 entry for the first time
(user directive "clean-run CVDP from the single Phase-1 entry").** Every CVDP
number ever published by this repo — single-shot 210/302, converged 215/245,
FAIR 234 — was produced by the **blind-author Shape-C flow**: an AI author reads
`input.prompt` (+ `input.context`) and writes the RTL completion `rtl/<name>.sv`
**directly**, `cvdp_gate.py` is the sole emit gate (hygiene `--fix` + iverilog
parse + yosys smoke + round-trip), and the official cocotb/iverilog harness
scores it. **Evidence:** `rerun_v1254b / rerun_v1258_blind / rerun_v1293_hard94 /
run_clean_v1252` contain `responses*.jsonl` + `drafts/` + `batches/` and **zero
`phase1/generated_docs/L9`** — Phase 1 is never invoked on that path. A blind
response record is literally a hand/AI-authored `module <name> ( … )` string.

**Why the "L9 empty / json-to-rtl never fires" problem never appeared before:**
that flow never produces L1/L9 at all — the AI author lifts the module name and
ports straight from the prompt, so there is no extraction step to fail.

**Why it appeared now:** the Phase-1 doc-extraction track (L1 pin_table, L9
top_module/top_ports) was tuned on vendor **DATASHEET** docs — rich structured
inputs with real `module ( … );` headers and pin tables. CVDP nonagentic records
are terse **PROMPTS** using idioms the doc-track had never been exercised on:
`Module Name:` labels / `## Module Name` headings, inline ``module `name` ``
references, and directional-prose `Inputs:`/`Outputs:` bullets. So L9 came back
empty (`top_module=chip_top`, `top_ports=[]`). Fixed program-first in **v1.3.12**
(ORGANIC-20260705): module-name prose extraction + reverse L1→L9 port backfill +
pin dedup (top_module recovered 0→6 of the first 10; the 4 residual encoder
prompts genuinely name no module → correct `chip_top` degrade).

**The governance consequence (BINDING for anyone quoting a CVDP number):**
1. **Always label WHICH entry a CVDP number came from.** "245/302" is a
   **blind-author** number; it does NOT measure the Phase-1 runner chain that
   § 1 says our published number must measure. Quoting it as "the plugin's
   Phase-1 score" is wrong.
2. The blind-author path is legitimately Shape-C (AI authors, plugin gate is the
   sole emit path) — but it is closer to "Opus + `cvdp_gate.py`" than to
   "Phase-1 → json-to-rtl". Disclose that in the RESULT.md (§ 3 already requires
   the substitution disclosure; add an ENTRY disclosure too).
3. **A Phase-1-entry CVDP number is a TARGET RE-RUN and does not exist yet.** On
   that path the deterministic boundary is: Phase-1 carries the module NAME +
   PORT LIST (structural facts — now fixed); the behavioral-prose → RTL BODY
   synthesis correctly routes to the spec-to-rtl **AI-backup** (with dual-track
   convergence), NOT a fabricated deterministic prose→RTL bridge. Do not build
   one — it would be the § 4 over-fit the doctrine forbids.
   **The deterministic driver for this entry is
   `benchmark/cvdp_phase1_entry.py`** (v1.3.14): it stages each record's
   `input.prompt` + `input.context` ONLY (never `output`/`harness`), forces it
   through `vibe_ic_one_shot_runner.py`, and classifies each case's emit path as
   `deterministic` (json-to-rtl fired, no LLM) vs `needs_ai_backup` (prose body
   → spec-to-rtl). Same dataset → byte-identical per-case verdicts. It
   establishes the DETERMINISTIC half and the exact AI-backup work-list; the
   AI-backup completions + deterministic RTL are then gated by `cvdp_gate.py`
   (SOLE EMIT) → official `run_benchmark.py`. A context-bearing record (133/302)
   has a real `module (...)` header in `input.context`, so its top_module +
   ports are recovered deterministically; a prompt-only record uses the
   module-name prose extraction (v1.3.12) and hands the body to the AI-backup.
5. **A FIRST-LAYER task-nature ROUTER runs BEFORE Phase-1** — CVDP is NOT a
   uniform spec→RTL benchmark (owner architecture 2026-07-05). Its 302
   nonagentic records span FIVE task natures, and only ONE is the plugin's
   Phase-1 (spec→design-doc→RTL) domain. `benchmark/cvdp_task_router.py` decides
   the route DETERMINISTICALLY from the dataset's own `cidNNN` label:

   **NONE of the five natures is out of scope — each enters a concrete plugin
   step or loop-of-steps** (`plugin_entry`, every program/skill below verified to
   exist by `test_cvdp_task_router.py`):

   | cid | nature | count | plugin entry (deterministic-first → AI-backup → verify) |
   |---|---|---|---|
   | cid003 | spec generation | 78 | **phase1_spec_to_rtl**: `phase1_one_shot_runner`+`deterministic_rtl_dispatcher` → `spec-to-rtl` → `rtl_hygiene_lint`+`spec_conformance_check`+`phase2-rtl-verify` |
   | cid002 | completion | 94 | **completion_loop**: `cvdp_context_interface_recover`+`modify_complete_synth` → `spec-to-rtl` → `rtl_hygiene_lint`+`spec_conformance_check`+`phase2-rtl-verify` |
   | cid004 | functional modification | 55 | **modify_loop**: `cvdp_context_interface_recover`+`modify_complete_synth` → `rtl-repair`+`eco-plan` → `equivalence-check`+`phase2-rtl-verify` |
   | cid007 | optimization | 40 | **optimize_loop**: `rtl_hygiene_lint` → `rtl-review`+`synth-doctor`+`ppa-predict` → `equivalence-check`+`phase2-rtl-verify` |
   | cid016 | debug | 35 | **debug_loop**: `cvdp_context_interface_recover`+`debug_first_pass` → `rtl-repair` → `phase2-rtl-verify`+`equivalence-check`+`formal-verify` |

   → **78 route to Phase-1 (spec→RTL); 224 route to their own plugin loop.** The
   interface for every context-bearing transform is recovered header-only from
   `input.context` by `cvdp_context_interface_recover` (the port header is the
   spec, never the golden body — §3.9 / §4.05). Composition of the 302
   no_commercial slice: difficulty easy 162 / medium 140 (no hard); 133/302 ship
   `input.context` RTL (cid004/007/016 always; cid002 mostly in-prompt).
   `cvdp_phase1_entry.py` drives ONLY the 78 spec_generation records through
   Phase-1; the 224 record their plugin-loop entry. For a GENERAL (unlabelled)
   prompt the first layer is a real AI parse — `classify_task_nature()` gives the
   deterministic fallback (context RTL ⇒ modify_loop; else ⇒ phase1) + sets
   `needs_ai_parse=True`. **A published Phase-1-entry number is over the 78
   spec_generation records; the other four natures are scored through their own
   plugin loops, not Phase-1.**
4. **Meta-lesson:** a benchmark can be "passing" on one entry while an entirely
   different entry has never been exercised. When the owner designates a
   canonical entry (here: Phase-1), re-establish the number THROUGH that entry
   before claiming it — do not inherit a number earned by a different flow.

## § 6 — The benchmark RESULT.md must include

> **The RESULT.md must EXIST and be NON-EMPTY / NON-STUB before anything else —
> enforced by `programs/run_output_completeness_check.py <run_dir>`** (v1.3.51).
> A benchmark run's FINAL act is to WRITE + SELF-VERIFY this deliverable: run the
> gate on the run_dir; only `COMPLETE` (exit 0) is "done". The load-bearing
> failure it catches is `COMPUTE_DONE_DELIVERABLE_MISSING` — the launch-and-idle
> abandon bug where the scorer/runner finished (a `final_summary` / orchestrator
> verdict / artifacts exist) but no RESULT.md was ever written because the agent
> detached the run and its turn ended. **NO RESULT / empty output = the run
> FAILED** — never publish a number without the RESULT that backs it. To keep
> your turn alive to completion, drive the long run through the BLOCKING
> `_watchdog.run_supervised` (returns only on exit/stall), not a detached
> fire-and-forget. On FAIL the gate emits a capture candidate — feed it to
> `enhancement_emit.py`.
>
> **Why the instruction alone loses to a plausible model (vibe-ic#558).** An
> agent ended its turn on a still-running Phase-3 flow, saying "I'll yield until
> the harness re-invokes me when Phase 3 exits". Nothing did. `claude -p` is
> one-shot, so the three beliefs that justified it are all impossible:
>
> * *"the harness will re-invoke me when the background job exits"* — nothing
>   re-invokes a finished turn. There is no such mechanism.
> * *"a background waiter is armed to fire"* — a waiter can only wake a turn
>   that is STILL ALIVE. It cannot start a new one.
> * *"the monitor will fire"* — a monitor notifies the DISPATCHER, not you. It
>   cannot resume you.
>
> Yielding does not pause your turn; it ENDS it, and your "then write the
> result" step never runs. The rule above is not a preference about style — it
> is the only way the deliverable gets written.

> **Section-presence enforced by `programs/benchmark_result_md_lint.py <RESULT.md>`** — fails the
> run if any of the seven mandatory sections below is missing. (It checks *presence* of each
> concept; the *quality* of the residual-triage content is still the § 4 LLM judgment.)

> **Residual-triage record self-consistency enforced by
> `programs/triage_record_check.py <triage-records.json>`** — when the residual triage is emitted
> as machine-readable records, this linter fails the run if any record's category letter
> contradicts its own fields: an agent-fixable letter (F/G/H) with `closeloop=false` and no
> skip justification (§ 6.4 forbids an un-attempted F-H), a FLOOR letter (A-E) marked
> `closeloop=true`, or an agent-fixable letter whose rationale reads like a FLOOR rationale
> ("mutually-exclusive readings" / "under-specified" / "benchmark defect") — the last is a REVIEW
> finding because the letter-vs-prose conflict needs § 4 judgment. Exit 0 clean / 1 violations /
> 2 IO.

For honesty + reproducibility, every benchmark RESULT.md MUST contain:

1. **Headline** — score, denominator, what was measured (`pass@1` / etc.), what was substituted.
2. **Shape** — A/B/C/D/E (per § 2). State explicitly which entry point drove the run.
3. **Score trajectory** — single-shot, close-loop stages, what each stage changed.
4. **Residual triage** — every fail mapped to ONE of categories A-H (§ 4) with concrete evidence
   (TB line, descriptor quote, iverilog error). Anything in A-E is FLOOR and gets one sentence
   per case explaining why it's unrecoverable blind. Anything in F-H without a close-loop attempt
   is **not allowed** — close-loop or document why close-loop was skipped.
5. **Tool substitution** — list every substitution per § 3 + the disclosure caveat.
6. **Reproduce** — exact command line for scorer + dataset path.
7. **Sequence/plan status** — if this benchmark was chosen out of a roadmap (e.g. open-benchmark.md),
   say which others were intentionally skipped and why (Shape E).

## § 7 — When in doubt

If a future benchmark doesn't cleanly fit A/B/C/D/E:
1. **Prefer A or B** if there's any chance the runner can drive it — the runner is what we measure.
2. **Use C only** if running the full runner per problem is genuinely overhead-dominated (atomic
   micro-problems, ≥100 of them) AND a gates.py can still drive plugin PROGRAMS for every
   verification step. Document the shape choice in the RESULT.
3. **Never go agent-first** without writing a one-paragraph justification in the RESULT explaining
   why no plugin program could drive it. (The 2026-05-28 RTLLM run skipped this justification and
   the methodology was caught later — don't repeat it.) This self-check is a
   **pre-dispatch checklist item** (§ 2 rule 0): before spawning any authoring
   agent ask "is this prompt's emit written by a program (GATE-AS-SOLE-EMIT-PATH)?"
   — if the answer is no, fix the harness first, don't dispatch.
4. **Never publish a number from Shape E**. Blocked is blocked; out-of-scope is out-of-scope.

## § 7.5 — Mandatory Phase-1 entry: every benchmark run must start from the Vibe-IC plugin (BINDING)

> **Owner directive 2026-06-28:** A benchmark number is meaningful ONLY if it measures what the
> Vibe-IC product — the deterministic runner chain — can produce. Therefore **every benchmark run
> MUST enter through the Vibe-IC plugin's Phase-1 path**; an agent that authors or patches RTL
> directly and then invokes the host scorer is measuring "Opus + MCP-EDA", not Vibe-IC.

Concrete enforcement:

1. **Canonical single entry point**: `vibe_ic_one_shot_runner.py <project>` (or, for the
   Phase-1 layer in isolation, `phase1_one_shot_runner.py <project>`). `vibe_ic_one_shot_runner.py`
   already integrates `phase1_one_shot_runner.py`; it auto-detects `input/phase1_prompt.md`,
   `input/docs/`, or `input/phase1_structured.yaml` and produces `phase1/generated_docs/L*.json`.
2. **No direct-agent authoring**: agents must NOT write benchmark RTL by hand, patch response
   JSONL completions, or call the host scorer on manually-edited files. The only legitimate
   AI-authored RTL path is the runner's `fallback_skill=spec-to-rtl` waiver (e.g.
   `digital_arithmetic_primitive` / `unknown_protocol_class` with `rtl_gen=null`), where the AI
   writes RTL **into the runner's `phase2/stage1/rtl/` tree** and then the runner's downstream
   gates (lint, conformance, TB, synth) are re-invoked.
3. **Shape-C gate-as-sole-emit path still counts**: for atomic micro-problems (VerilogEval),
   the `gates.py` harness is the authorized entry point because it drives `phase1_engine.cli`,
   `spec_conformance_check.py`, `rtl_hygiene_lint --fix`, etc. — the Phase-1 fact-graph is still
   produced; the gate simply wraps the emit. Directly editing `samples/<Prob>_sample01.sv` without
   running the gate is equally prohibited.
4. **Score front-door guard**: `benchmark_dispatch.py --score` / `benchmark_clean_room_check.py`
   MUST reject any run that lacks `reports/phase1_one_shot.json` or `phase1/generated_docs/L*.json`
   evidence (with a documented exception only for gated datasets where Phase-1 itself is
   impossible — Shape E, not a loophole for Shape A-D).
5. **Why this is non-negotiable**: the 2026-06-27 CVDP close-loop demonstrated that manual per-pid
   RTL patches can move the host scorer by +6 PASS, but those patches do NOT flow back into the
   deterministic runner. A subsequent clean-room run would lose them instantly. The benchmark
   number must measure the runner, not the agent's ad-hoc edits.

## § 8 — Re-run obligations

When re-running a previously-measured benchmark on a new plugin version, the **same shape** must
be used (so the deltas are comparable). If shape changes (e.g. RTLLM C → B re-run target), the
new run is a **separate datapoint**, not a "v0.X.Y improvement" claim. Label clearly in RESULT.

If a backlog fix (e.g. `ORGANIC-20260528-spec-to-rtl-missing-chip-top-wrapper`) lands and could
move the number, mention it explicitly + cite the backlog id in the trajectory section.

### § 8.1 — Default re-run policy: CLEAN-ROOM FULL re-run (user directive 2026-06-04)

> **User policy (binding, 2026-06-04 — SUPERSEDES the 2026-05-29 "re-run the FAILing set" default)**:
> "Run vibe-ic Benchmark 一定是重跑，一定重跑。不要拿舊的資料，也不要用 memory，也不要用原來
> storage 裡面的東西，一定是重跑。"

When the user asks to "run X benchmark" with no qualifier:
- **DEFAULT = CLEAN-ROOM FULL re-run** (per § 4.1): author EVERY problem fresh, blind to any
  prior run; the authoring context starts EMPTY (no prior samples, no agent memory, no cached
  storage). This applies regardless of how recent the prior run was.
- DO NOT propose "skip, prior canonical stands" as the default. That's an OPTION the user can
  pick, never the default.
- DO NOT propose "re-run only the FAILing set" as the default either — that inherits the prior
  PASSes and contaminates the headline. It is an explicit OPTION (`--floor-only`), and even then
  re-authors blind into a fresh dir.
- DO NOT propose "smoke test on 1 problem" as the default — also an OPTION.
- The DEFAULT action is execute the clean-room full re-run without asking permission. Surface
  the result; if the user wanted something narrower they will say so.

> **Enforced by `programs/benchmark_dispatch.py`** (clean-room is the implicit mode; `--setup`
> requires an empty `samples/`, `--floor-only` is the explicit opt-in) and guarded at the score
> front-door by `programs/benchmark_clean_room_check.py`.


## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/SKILL_NAME/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in this skill directory enumerates every required
element of your output: section headers, handoff lines, summary blocks.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.

## § 4.1 — FLOOR-proof: never declare a benchmark-defect FLOOR without the "original-RTL-also-fails" proof (ORGANIC #724)

> **Binding (P1):** across one campaign, FIVE residuals were initially labelled
> "benchmark defect / spec-vs-TB contradiction" and ALL FIVE were later
> overturned and PASSED — each was our OWN off-by-one / interface / reset-boundary
> / area-encoding bug, not a benchmark defect. A FLOOR claim is almost always a
> misread, and the asymmetry is severe: **a false FLOOR ships an unfixed real bug**,
> while the disproving proof is cheap.

A residual may be labelled **FLOOR** (Category A/B/E in § 4) ONLY after this
three-step **FLOOR-proof**, in order:

1. **Run the EXACT official scorer** on the candidate RTL (the real harness, the
   real toolchain, any required env image) and read the **real failing
   assertion** — not a paraphrase, not your own TB.
2. **Run the ORIGINAL, UNMODIFIED reference/golden RTL through the SAME scorer.**
   If the original ALSO fails → it is a genuine benchmark/oracle defect (FLOOR).
   **If the original PASSES → the defect is OURS** (authoring/extraction bug);
   it is NOT a floor — go fix it.
3. **Only confirm FLOOR** when you can quote BOTH (a) the exact harness assertion
   that fails AND (b) the exact prompt line mandating two **mutually-exclusive**
   values for identical stimulus, AND you have shown (step 2) the original RTL
   also fails.

**Category-A2 variant (harness contradicts the GIVEN context itself):** when the
contradiction is provable from the given input alone (prose + any given/gate-target
RTL vs the TB oracle), the floor-proof is: (a) a **cross-round expected-vs-got table**
— the TB's asserted value for a stimulus vs what the given mapping mandates, shown
stable across ≥2 independent authoring rounds so it is not a one-off; and (b) a
**replay under the design's OWN testbench** confirming the given behavior is
internally consistent while only the hidden oracle disagrees. This makes the defect
provable with NO external information — the given context is the evidence.

This is the spec-faithful companion to the **#716 dual-track convergence**
doctrine (program verdict + independent AI solve + converge): the "original-RTL-
also-fails" run is the independent reference track that overturns a single-track
FLOOR misread. *why_not_bucket_a*: deciding whether two assertions are truly
mutually exclusive for identical stimulus is an open-ended meaning judgment no
regex makes; the deterministic half (a FLOOR claim MUST carry the original-RTL-
also-fails scorer evidence) is the gate condition recorded here.

## § 9 — The 5-TIER CONVERGE method (classify → push every tier up → only a proven defect is a floor)

The capture loop (`benchmark-enhancement-capture`) says *move every recovery into
the program layer*. § 9 is the **measurement + promotion harness** that makes that
loop legible per problem. It classifies every benchmark problem into a STABILITY
tier and pushes each tier upward as far as is HONESTLY possible. The reference
implementation is `programs/cvdp_solve_pipeline.py`; each suite has its own
mirror: `programs/{verilogeval_tier_pipeline, verilogeval_human_tier_pipeline,
rtllm_tier_pipeline}.py` (each exposes `classify` / `build_gate` / `gate_check` /
a floor-prover / an iverilog Tier-1 verifier + a `--dist` CLI).

### The tiers (highest stability first)

| Tier | meaning | how a problem qualifies |
|---|---|---|
| **T1** | deterministic program emit | a solver (registry / family / canonical) emits RTL that PASSES the design's own testbench under iverilog (`Mismatches: 0`). No AI. |
| **T2** | program-extract COMPLETE spec + gate | a program extracts every testable fact (COMPLETE); the AI authors from that complete spec and a conformance gate verifies it. |
| **T3** | gate-able | a meaningful interface/structure gate constrains the AI author; the extracted spec is not fully COMPLETE. |
| **T4** | ungated | too-incomplete to build a meaningful gate. |
| **T5** | real floor | ONE of exactly two: **(a) dataset/oracle defect** — the GOLDEN reference fails its OWN testbench (proven per § 4.1); OR **(b) an honestly-DEFERRED algorithm-hard FORK gap** — an OSS-tool capability gap that is a genuine research port, cited by a specific `tools/vibeic-eda/FIX_STATUS.md` 🔷 DEFERRED row. **A plain tool-substitution gap is NO LONGER T5 by default** — since we fork the EDA tools it is Category-D FORK-FIXABLE (route to FIX_STATUS), and it may be recorded as T5 ONLY once it carries the 🔷 entry AND has passed the § 4.1 floor-proof (golden PASSES under a tool that supports the feature; if the golden ALSO fails, it is a dataset/RTL floor (a), not a tool floor). Never "AI can't". |

GOAL: T1+T2+T3 stably solved every run (they all carry a program gate or a
deterministic emit); only T5 is a true floor — and T5(b) is a KNOWN-DEFERRED
engineering item on the fork backlog, not a permanent ceiling.

### The converge levers (run STEP-BY-STEP, bottom tier first, verify after each)

1. **T5→lower** — for every candidate floor run § 4.1's golden-vs-its-own-testbench
   proof; reclassify every golden-PASSES problem. A benign `$display("TIMEOUT")`
   watchdog print is NOT a failure — grade strictly on the `Mismatches:` line. **If
   the only reason the golden "fails" is our OSS tool rejecting/crashing on a
   language feature, that is Category-D FORK-FIXABLE, not T5:** re-run the golden
   under a tool that supports the feature (Verilator `--timing`, forked iverilog);
   on a PASS, route it to `tools/vibeic-eda/FIX_STATUS.md` (fork the capability)
   instead of shelving it as a floor. It stays T5 ONLY as a 🔷 honestly-deferred
   algorithm-hard port.
2. **T4→T3** — recover the interface (prompt header / `_ifc.txt` / provided
   `input.context` RTL header / cocotb `dut.<sig>` set, incl. a `tb.py`/non-`test_`
   harness file) so a gate can bind. Interface = spec (§ 3.9).
3. **T3→T2** — close extraction gaps so the spec is COMPLETE. The #1 gap is an
   unstated WIDTH: resolve it from a literal, a named-parameter expression
   (parameterised width IS complete), a context param default, or a harness-pinned
   width — never a coincidental same-line prose number (false-COMPLETE).
4. **T2→T1** — build/extend a DETERMINISTIC solver and iverilog-VERIFY its emit
   against the testbench. Promote ONLY on a real pass.

### The two honesty gates that make the number trustworthy

- **iverilog-authoritative**: a Tier-1 claim is accepted ONLY on a real
  `Mismatches: 0` pass; a fired-but-wrong emit is dropped to T2, never shipped.
- **GENERAL-not-OVERFIT (the §4.05 bar a Tier-1 solver MUST clear)**: a solver may
  be promoted to the deterministic tier ONLY if it keys on operation/structure
  semantics and reads EVERY constant from the interface width or parsed prose. A
  solver that gates on a design-category keyword and emits hardcoded
  design-specific constants (e.g. a traffic-light reload `8'd60/8'd5`, a calendar
  `6'd59`, an ALU's MIPS opcode table, an LFSR's hardcoded taps) is a disguised
  golden lookup — it is iverilog-PASS yet still a CHEAT, because it would emit
  WRONG RTL for a different instance of the same operation. Such a solver is
  REJECTED even though it "passes": the design stays honestly at T2 (gate + AI),
  exactly like a prose-only design. (Real campaign evidence: a "promote all 33"
  RTLLM sweep was rejected on this bar; only 13 genuinely-general emitters — each
  reading widths/constants from the spec — were salvaged, the rest stayed T2.)

### Snapshot (4-suite converge, 664 problems, iverilog-authoritative)

| Suite | total | T1 | T2 | T3 | T5 | gated |
|---|---|---|---|---|---|---|
| CVDP | 302 | 33 | 191 | 78 | 0 | 302/302 |
| VerilogEval-v2 | 156 | 131 | 0 | 24 | 1 | 155/156 |
| VerilogEval-Human | 156 | 130 | 26 | 0 | 0 | 156/156 |
| RTLLM | 50 | 26 | 20 | 0 | 4 | 46/50 |

The 5 T5 above were snapshotted before the fork-fixable reclassification. Per the
tightened T5 rule they split into two kinds: **dataset/oracle defects** (golden
fails its OWN testbench even under a supporting tool — genuine T5(a)) and
**tool-substitution gaps** (golden PASSES under a supporting tool — Category-D
**FORK-FIXABLE**, route to `tools/vibeic-eda/FIX_STATUS.md`; T5 only if 🔷
honestly-deferred). Concretely, the RTLLM `asyn_fifo` counted here is NOT a floor:
its golden compiles+PASSES under Verilator `--timing` and the forked iverilog
14-devel — the `break;` gap is already fork-closed (`FIX_STATUS.md` Tool 5). Re-run
the § 4.1 floor-proof on each snapshot T5 before treating it as a permanent ceiling.

**Summary**: classify into 5 tiers, push each up step-by-step, accept a Tier-1
only on an iverilog pass by a GENERAL (not overfit) solver, and label a floor only
after the § 4.1 golden-also-fails proof — and remember a plain tool-substitution
gap is FORK-FIXABLE (route to FIX_STATUS), not a floor.

Next: run `python3 programs/<suite>_tier_pipeline.py --dist` to measure, then drive
the lever for the lowest non-empty promotable tier.
