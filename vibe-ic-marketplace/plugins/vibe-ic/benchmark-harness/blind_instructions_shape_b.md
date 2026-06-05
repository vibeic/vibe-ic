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
scorer (`benchmark-harness/score_iverilog_tb.py`), at scoring time, not generation.

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
   The runner internally: Path-A phase1 (NL → L1-L13) → phase2 spec-to-rtl (with
   chip_top wrapper, power-up `--fix`, lint, synth) → emits RTL at
   `<project>/phase2/stage1/rtl/`.

4. **Copy the runner's RTL to the scoreable location**:
   The runner emits its top module under whatever name was authored. Find the
   module that matches the description's stated name and copy it to
   `<RUNDIR>/samples/<leaf>.v`.

5. **Handling phase2 outcomes** — there are TWO classes to distinguish carefully:

   **5a. Runner step_rtl_gen WAIVES with `fallback_skill='spec-to-rtl'`** (very
   common; happens for every IC class whose `rtl_gen=null`):
   - This is **the runner's INTENDED PATH**, not a failure. The runner has
     already done phase1 → emitted `<project>/phase1/generated_docs/L*.json`
     → detected ic_class → set the expected output path. It is now handing off
     to you (the AI playing the spec-to-rtl ROLE) to author RTL.
   - **Author RTL at `<project>/phase2/stage1/rtl/<top>.<v|sv>`** using the L
     docs (L1-L9 esp.) PLUS the original `design_description.txt`. The blind
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
     `eda_lint`, `eda_synth`, `spec_conformance_check`, `eco_loop` (up to 3
     retries on `reference_tb` FAIL), `full_stack_tb_gen`, `final_audit`.
     These gates are what make Shape B more valuable than direct-agent
     authoring (Shape C with MCP only).

   **5b. Runner step FAILS** (not WAIVES) — e.g. yosys synth ERROR, port
   conformance FAIL, missing chip_top wrapper:
   - Read the failing step's log from `<project>/reports/orchestrator/phase2_one_shot.json`.
   - Apply a GENERAL, chip-agnostic fix (e.g. chip_top wrapper if missing,
     port name typo). Do NOT peek at the hidden testbench.
   - Re-run the runner. ONE retry max.

6. The benchmark NUMBER measures what the runner pipeline (incl. you in the
   spec-to-rtl role per 5a) produces. The 2026-05-28 wrong-shape RTLLM 37/50
   was direct-agent authoring with MCP only — phase1 / chip_top / hygiene fix /
   eco_loop / conformance ALL skipped. Shape B done correctly invokes the AI
   for authoring AS PART OF the runner pipeline, with all those gates firing.

## Final report (compact table)
Per `<leaf>`: module name | runner verdict | sample emitted (y/n) | any close-loop
fix applied (what + why GENERAL) | any design not emittable (with reason).
