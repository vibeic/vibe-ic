# Shape B blind instructions — standalone-design benchmark (RTLLM-class)

You drive a batch of designs through the **deterministic Vibe-IC runner**
(`vibe_ic_one_shot_runner.py --skip-phase3 --skip-analog --skip-hardware`) — NOT
direct agent authoring. Per the `open-benchmark-methodology` skill § 2 Shape B:
the runner is the primary author; the agent only triages failures.

PARAMS your caller provides:
- `DATASET`   absolute path to the benchmark dataset on disk (per-design dirs each
              with `design_description.txt` + `testbench.v` + golden `verified_*.v`)
- `RUNDIR`    absolute path to the run dir (with `samples/`, `problems.list`, `batches/`)
- `BATCHFILE` list of design dirs (relative to DATASET) — your batch

## CAPTURED-LESSON DIGEST — MUST READ + APPLY (ORGANIC #718/#733)

If `<RUNDIR>/lessons.md` exists (rendered by `benchmark_dispatch.py --setup` from chip-AGNOSTIC `### Skill:` sections), it is run-dir material (blindness preserved). Staging is not enough — you MUST CONSUME it.

**MANDATORY PRE-AUTHORING CONSUMPTION (ORGANIC #733 - staged != consumed).**
Staging the digest is not enough; you MUST CONSUME it per design. BEFORE you
author EACH design, you MUST: (1) OPEN the staged `<RUNDIR>/lessons.md`; (2)
KEYWORD-MATCH the design genre against the digest genre-convention sections -
`barrel shifter`, `frequency divider / odd / dual-edge`, `async FIFO`,
`serial<->parallel`, `edge/pulse detect`, `FSM Moore`, `gshare`, `serial twos
complement`, `K-map -> mux`, `IEEE-754 float multiply`, `saturating counter /
no upper limit / cannot overflow`; (3) APPLY the matched
section to your RTL. section 4-E NO-LEAK: apply a convention ONLY "unless the
spec states otherwise" - never override an explicit spec; a spec-ambiguous case
stays spec-faithful (no oracle answer). The #716 recovered-floor gain is only
realized when the author reads+applies the matched convention, not merely has
it staged.


## ORCHESTRATION RULES (for the caller spawning the agents — ORGANIC-20260605)

Shape B uses the SAME batch fan-out architecture as Shape C, so the same
caller-side rules are REQUIRED (full doctrine + rationale in
`blind_instructions_shape_c.md` § ORCHESTRATION RULES):

1. **Batch granularity** — one agent per pre-split `batches/batchNN.list`,
   never one agent per design.
2. **Disk truth** — reconcile progress by counting on-disk
   `<RUNDIR>/samples/` files, never by tallying agent returns; resume =
   diff `problems.list` vs `samples/`.
3. **Transcript export is the DEFAULT** — copy every authoring and
   close-loop agent's transcript to `<RUNDIR>/transcripts/` (named per
   agent) before scoring; the blindness audit reads them
   (ORGANIC-20260605-transcripts-export-default).
4. **Rate-limit resilience ladder
   (ORGANIC-20260605-ratelimit-resilient-dispatch-ladder).** Provider-side
   burst rate-limiting kills a full-width fan-out within seconds — kill
   signature: sub-minute workflow death, ZERO/near-zero token usage, most
   agents nulled at once; same-width retries die identically while a
   single sustained agent survives. On a burst kill: (a) drop to a
   **1-agent CANARY** that must complete a FULL batch before any scaling;
   (b) resume at **narrow width (2–4 concurrent)** with completion-driven
   dispatch (launch the next agent when one finishes), never barrier
   fan-out; (c) disk-truth reconcile (rule 2) remains the resume
   mechanism.

## ABSOLUTE BLINDNESS RULE
For each `<design>` you may read ONLY `<DATASET>/<design>/design_description.txt`.
NEVER open / cat / grep / list `testbench.v` / `verified_*.v` / any
`LLM_generated_verilog.v`. The hidden TB / golden ref are touched ONLY by the host
scorer (`benchmark/score_iverilog_tb.py`), at scoring time, not generation.

**CROSS-PROBLEM PROHIBITION (ORGANIC-20260605-blindness-rule-cross-problem-refs).**
The rule binds for the WHOLE dataset: you may NOT read ANY dataset file other
than the current design's `design_description.txt` — explicitly including
OTHER designs' testbenches / verified references, and any other run
directory's `work/` or `samples/`. Sibling reference solutions encode the
dataset's authoring conventions, so reading them is dataset-internal solution
knowledge even though they are not the current design's own hidden files.
Applies EQUALLY to close-loop / repair agents. Explicitly included:
**dataset BUILD files** (Makefile / *.mk / run scripts — they encode
module-name and flow authority) and **self-running the host scorer or any
verdict-level oracle query mid-loop** (`score_*.py`, `benchmark_dispatch
--score` — scoring is the HOST's post-generation step; self-verify with
your OWN testbench only). Deterministic enforcement: transcripts exported
to `<RUNDIR>/transcripts/` are audited by `programs/blindness_audit.py`
at the score front door.

## Per-design procedure (every `<design>` in BATCHFILE)

1. Read ONLY `<DATASET>/<design>/design_description.txt`. Extract:
   - the **EXACT module name** stated by the description (the testbench instantiates
     the DUT by that name; NOT `TopModule`),
   - the exact port list (names / dirs / widths),
   - the algorithm / behavior + any timing details.
   `leaf = basename(<design>)` (e.g. `Arithmetic/Multiplier/multi_8bit` → `multi_8bit`).

2. **Build a per-design Path-A project** for the runner:
   ```
   <project> = <RUNDIR>/work/<leaf>/
   <project>/input/phase1_prompt.md   ← copy of design_description.txt
   ```

3. **Drive the runner** (the primary author):
   ```
   python3 ${CLAUDE_PLUGIN_ROOT}/programs/vibe_ic_one_shot_runner.py <project> \
       --skip-phase3 --skip-analog --skip-hardware --pdk sky130A
   ```
   The runner internally: Path-A phase1 (NL → L1-L27) → phase2 spec-to-rtl (with
   chip_top wrapper, power-up `--fix`, lint, synth) → emits RTL at
   `<project>/phase2/stage1/rtl/`.

4. **Export the runner's RTL to the scoreable location — DETERMINISTIC, the
   SOLE EMIT PATH** (ORGANIC #678; analogous to `gates_atomic.py` for Shape C):
   ```
   python3 ${CLAUDE_PLUGIN_ROOT}/programs/shape_b_sample_export.py \
       --project <project> --leaf <leaf> --samples <RUNDIR>/samples \
       [--module <spec 'Module name:' value>]
   ```
   DO NOT hand-copy a single module. The program copies the runner's **COMPLETE
   TB-facing-top RTL FILE verbatim**, preserving every variant-alias / synonym
   wrapper bundled with its inner children in one file, then runs a post-export
   guard (standalone `iverilog -g2012` compile + variant-alias completeness).

   **WHY (the gate↔scorer discrepancy this closes).** The runner may fire
   `reset_clock_variant_alias` (#518): it renames the TB-facing top to
   `<top>__rcvar_inner` in place and appends a wrapper `<top>` exposing the
   canonical reset/clock spelling, wired 1:1 — BOTH modules in ONE file, and only
   that complete file PASSES the hidden TB (which binds the canonical port). The
   same class applies to leaf-typo synonym wrappers (#517). A hand-extracted
   single module ships only the un-wrapped inner core (prompt-spelling ports),
   DROPPING the wrapper: standalone compile (no TB) passes the inner → gate
   green, but the host scorer binds the hidden TB against the canonical port →
   COMPILE-ERROR, and the runner's deterministic fix never reaches the scorer.
   The export program is the sole emit path so that can never happen; its guard
   REJECTS any export missing a wrapper (or a wrapper's inner). Exit 0 = sample
   exported + guard passed; a non-zero exit means re-run the runner, never
   hand-edit the sample.

5. **Handling phase2 outcomes** — there are TWO classes to distinguish carefully:

   **5a. Runner step_rtl_gen WAIVES with `fallback_skill='spec-to-rtl'`** (very
   common; happens for every IC class whose `rtl_gen=null`):
   - This is **the runner's INTENDED PATH**, not a failure. The runner has
     already done phase1 → emitted `<project>/phase1/generated_docs/L*.json`
     → detected ic_class → set the expected output path. It is now handing off
     to you (the AI playing the spec-to-rtl ROLE) to author RTL.
   - **Author RTL at `<project>/phase2/stage1/rtl/<top>.<v|sv>`** using the L
     docs (L1-L27 esp.) PLUS the original `design_description.txt`. The blind
     rule still applies — never read the hidden testbench. Module name must
     match what L9 / the description states (NOT "TopModule" for RTLLM).
   - This is NOT "bypassing the runner" — bypass means authoring with MCP
     OUTSIDE the runner's pipeline. Authoring INSIDE the runner's pipeline,
     at the path it set, after the WAIVE message, IS the runner's design.
   - **Then re-invoke the runner** so its downstream gates run on your RTL:
     `python3 ${CLAUDE_PLUGIN_ROOT}/programs/vibe_ic_one_shot_runner.py <project> \
         --skip-phase3 --skip-analog --skip-hardware --pdk sky130A`
     The runner detects RTL is present, skips step_rtl_gen, and continues
     with: `chip_top_gate_wrapper_gen` (auto-emits the chip_top wrapper if
     L9.top_module != your authored top), `rtl_hygiene_lint --fix` (enforces
     power-up determinism on reset-less registered outputs — v0.1.24 lesson),
     `eda_lint`, `eda_synth`, `spec_conformance_check`, `rtl_repair_retry` (up to 3
     retries on `reference_tb` FAIL; **not** a physical/metal ECO),
     `full_stack_tb_gen`, `final_audit`.
     These gates are what make Shape B more valuable than direct-agent
     authoring (Shape C with MCP only).

   **5b. Runner step FAILS** (not WAIVES) — e.g. yosys synth ERROR, port
   conformance FAIL, missing chip_top wrapper:
   - Read the failing step's log from `<project>/reports/orchestrator/phase2_one_shot.json`.
   - Apply a GENERAL, chip-agnostic fix (e.g. chip_top wrapper if missing,
     port name typo). Do NOT peek at the hidden testbench.
   - Re-run the runner. ONE retry max.

   **5c. Mandatory blind AI review after either 5a or a PROGRAM emit:**
   - `benchmark_dispatch.py --solve` writes one hash-bound task per gated
     candidate to `<RUNDIR>/needs_ai_review.jsonl`. A PROGRAM PASS is a
     candidate, not acceptance.
   - The reviewing AI may read only the task's `prompt_path` and `rtl_paths`;
     it must not read the hidden testbench, reference solution, scorer result,
     or any oracle. It independently classifies the task route and checks RTL
     semantics against the prompt.
   - Write the review to the task's `review_path` using schema
     `vibeic.benchmark.ai_review.v2`, the task's exact `id`,
     `prompt_sha256`, and `rtl_sha256`, a real
     `reviewer={"kind":"AI","model":"<model>"}`,
     `blind={"oracle_accessed":false}`,
     `routing={"verdict":"AGREE","ai_nature":"<program nature>"}`, and
     `semantic_review={"verdict":"PASS","findings":[],"rationale":"..."}`.
   - **AI is the final semantic authority, but a rejection needs executable
     proof.** To
     overrule a deterministic route, use `routing.verdict=OVERRIDE_PROGRAM`
     and add `override.program_limitation` plus either prompt-bound
     `prompt_evidence=[{"excerpt":"...","supports":"..."}]` or a detailed
     `override.explanation`. A concrete `proposed_program_enhancement`
     (`component`, `proposal`, `regression_fixture`) is encouraged and retained.
   - If the current RTL is wrong, return
     `semantic_review.verdict=FAIL` with at least one actionable finding and a
     rationale. Write a self-contained SystemVerilog test to the task's exact
     `challenge_path`, with top `vibeic_ai_challenge_tb`, no include/readmem/
     file/system/DPI access, and print `VIBEIC_AI_CHALLENGE=PASS` only on PASS.
     On a checked mismatch it must print `VIBEIC_AI_CHALLENGE=FAIL` before a
     non-zero `$fatal`; compile errors and timeouts are invalid proof.
     Add `verification_test` using the task's required schema/path, the test
     SHA-256, exact prompt evidence, expected behavior, and rationale. The
     frozen Program candidate must compile and FAIL this test; otherwise the AI
     rejection is unproven and repair is blocked.
   - `--resume` records a proven finding in `needs_ai_repair.jsonl`. The AI may
     then repair the working RTL and must write the requested repair record,
     naming its model/rationale and binding parent RTL, repaired RTL, and the
     challenge hashes. PROGRAM gates re-run; the repair must pass the
     **same immutable challenge** and a fresh AI review before it can replace
     the Program candidate. The frozen candidate, proof, and repair hashes also
     persist in `program_enhancement_candidates.jsonl` for capture enhancement.
   - Run `benchmark_dispatch.py <bench> --resume --dataset <DATASET> --run
     <RUNDIR>`. Scoring is blocked until
     `program_first_ai_review_acceptance.json` says
     `COMPLETE` for every problem.

6. The benchmark NUMBER measures what the runner pipeline (incl. you in the
   spec-to-rtl role per 5a) produces. The 2026-05-28 wrong-shape RTLLM 37/50
   was direct-agent authoring with MCP only — phase1 / chip_top / hygiene fix /
   rtl_repair_retry / conformance ALL skipped. Shape B done correctly invokes the AI
   for authoring AS PART OF the runner pipeline, with all those gates firing,
   then requires a blind AI semantic review of the Program result.

## Final report (compact table)
Per `<leaf>`: module name | runner verdict | sample emitted (y/n) | any close-loop
fix applied (what + why GENERAL) | any design not emittable (with reason).
