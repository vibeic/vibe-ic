# Shape C blind instructions — atomic-micro-problem benchmark (VerilogEval-class)

You process a BATCH of atomic micro-problems blind, emitting a scoreable RTL sample
per problem. Per `open-benchmark-methodology` skill § 2 Shape C: lightweight
gates-based harness — running the full Vibe-IC runner per problem is
overhead-dominated for ≥100 atomic problems, but **every verification GATE is
still a plugin program** (`phase1_engine`, `spec_conformance_check`,
`rtl_hygiene_lint --fix`, `iverilog`).

## ORCHESTRATION RULES (for the caller spawning the agents — ORGANIC-20260605)

These are REQUIRED, learned from a 312-problem clean-room run where per-problem
fan-out lost ~93% of its agents' results while batch fan-out completed 312/312:

1. **Batch granularity is REQUIRED for ≥100-problem datasets.** Spawn ONE
   authoring agent per pre-split `<RUNDIR>/batches/batchNN.list` file — NEVER
   one agent per problem. Hundreds of short-lived per-problem subagents lose
   their final structured return far too often; batch agents do sustained
   multi-problem work and return reliably.
2. **The filesystem is the authoritative truth for emitted samples.** The
   deterministic gate writes `<RUNDIR>/samples/<Prob>_sample01.sv` regardless of
   whether the agent's structured return survives. Orchestrators MUST reconcile
   progress by COUNTING on-disk samples — never by tallying agent returns.
3. **Resume = diff `problems.list` vs on-disk `samples/`.** The un-authored set
   is exactly the problems with no `<Prob>_sample01.sv` on disk; re-dispatch
   only those (in batches), never re-author what is already on disk.
4. **Transcript export is the DEFAULT, not an optional extra
   (ORGANIC-20260605-transcripts-export-default).** `--setup` pre-creates
   `<RUNDIR>/transcripts/`; the caller MUST copy/export EVERY authoring and
   close-loop agent's transcript (or tool-call path log) there, named per
   agent (e.g. `batch03.log`, `closeloop_r2_probX.log`), BEFORE scoring.
   `--score` audits them deterministically and refuses on violations; a run
   scored without them takes the honest NOTICE branch and its RESULT.md MUST
   disclose "blindness audit unavailable".
5. **Rate-limit resilience ladder
   (ORGANIC-20260605-ratelimit-resilient-dispatch-ladder).** Provider-side
   burst rate-limiting kills a full-width fan-out within seconds — the kill
   signature is sub-minute workflow death with ZERO/near-zero token usage and
   most agents nulled at once. Naive retries at the same width die
   identically, while a single sustained agent survives. On a burst kill:
   (a) drop to a **1-agent CANARY** that must complete a FULL batch before
   any scaling; (b) resume at **narrow width (2–4 concurrent)** with
   completion-driven dispatch (launch the next agent when one finishes),
   never barrier fan-out; (c) disk-truth reconcile (rule 3) remains the
   resume mechanism. Recognize the signature instead of burning full-width
   retries.

PARAMS your caller provides:
- `BENCH`     benchmark name (e.g. `verilogeval-v2`, `verilogeval-human`) — used by gates_atomic.py
- `DATASET`   absolute path to dataset (flat dir with `<Prob>_prompt.txt`, hidden `<Prob>_test.sv` / `<Prob>_ref.sv`)
- `RUNDIR`    absolute path to run dir (with `work/`, `samples/`, `batches/`)
- `BATCHFILE` list of `<Prob>` ids — your batch

## ABSOLUTE BLINDNESS RULE
For each `<Prob>` you may read ONLY `<DATASET>/<Prob>_prompt.txt`.
NEVER open / cat / grep / list `<Prob>_test.sv` or `<Prob>_ref.sv` (the hidden testbench +
golden reference, touched ONLY by the host scorer at scoring time).

**CROSS-PROBLEM PROHIBITION (ORGANIC-20260605-blindness-rule-cross-problem-refs).**
The rule binds for the WHOLE dataset, not just the current problem: you may
NOT read ANY dataset file other than the current problem's `_prompt.txt` —
explicitly including OTHER problems' `_test.sv` / `_ref.sv` / reference
solutions, and any other run directory's `work/` or `samples/`. Sibling
reference solutions encode the dataset's authoring conventions (axis orders,
sampling phases, encoding styles), so reading them is dataset-internal
solution knowledge: it violates prompt-only blindness even though the file is
not the current problem's own hidden file. This prohibition applies EQUALLY
to every close-loop / repair / convention-sweep agent, not only single-shot
authors. It explicitly includes **dataset BUILD files** (Makefile / *.mk /
CMakeLists.txt / run scripts) — they encode the dataset's module-name and
flow authority and are dataset-internal solution knowledge — and the
harness's **`canonical_samples/` tree** (vetted defect-audit samples =
solution knowledge; host scorer only, access is audit-flagged).

**NO SELF-SCORING (ORGANIC-20260605-blindness-deterministic-audit-guard).**
You may NEVER invoke the host scorer (`score_*.py`, `benchmark_dispatch
--score`) or make ANY verdict-level oracle query mid-loop — not in
single-shot, not in close-loop. Scoring is the HOST's post-generation step.
Self-verification means YOUR OWN testbench only. Enforcement is
deterministic, not just this text: the orchestrator exports agent
transcripts to `<RUNDIR>/transcripts/`, and `programs/blindness_audit.py`
runs at the score front door — any non-prompt dataset access or
command-shaped scorer invocation in a transcript FAILs the whole run.

**CAPTURED-LESSON DIGEST (ORGANIC-20260605-shapec-lesson-digest-injection).**
If `<RUNDIR>/lessons.md` exists (rendered by `benchmark_dispatch.py --setup`
from the capture loop's general-pattern sections), you MUST read it BEFORE
authoring your batch. It contains only chip-AGNOSTIC general patterns (the
capture policy bars design identifiers and oracle data), so reading it
preserves blindness while preventing already-captured recoveries from
recurring. It is run-dir material, NOT a dataset file — the cross-problem
prohibition above does not apply to it.

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


## Per-problem procedure (every `<Prob>` in BATCHFILE)

1. Read ONLY `<DATASET>/<Prob>_prompt.txt`. Extract: module name (typically
   `TopModule` for VerilogEval-class; the registry's `module_name_strategy` says
   `always_TopModule`), exact port list (names / dirs / widths; `[3:0]` → width 4,
   scalar → 1), and required behavior.

2. Write `<RUNDIR>/work/<Prob>/spec.yaml` from the prompt ONLY:
   ```yaml
   ic_name: TopModule
   class_path: combinational-logic     # or sequential-logic / fsm
   L1:
     ic_name: TopModule
     description: "one-line behavior summary"
   L9:
     module_name: TopModule
     ports:
       <name>: { dir: input,  width: <N> }
       <name>: { dir: output, width: <N> }
   ```

3. Write `<RUNDIR>/work/<Prob>/sample.sv` — synthesizable SystemVerilog, module
   `TopModule` (or the registry-stated name), with the prompt's exact port
   declaration, implementing the behavior. Blind, from the prompt only.

4. (Optional) MCP `eda_lint` + `eda_synth` (gf180) for early-fail detection.
   These are programs too; they catch latches / case-incomplete / power-up-X
   before the host gate.

5. Run the deterministic gate (emits the scoreable sample on hard-PASS):
   ```
   python3 ${CLAUDE_PLUGIN_ROOT}/benchmark/gates_atomic.py \\
       --prob <Prob> \\
       --workdir <RUNDIR>/work \\
       --dataset <DATASET> \\
       --bench <BENCH>
   ```
   Hard gates = `phase1_run_all` + `iverilog_compile` + NO emit-blocking
   structural finding. On hard-PASS the gate writes
   `<RUNDIR>/samples/<Prob>_sample01.sv`. The gate ENFORCES
   `rtl_hygiene_lint --fix` (step 5a) before emit, so reset-less registered
   outputs are auto-given `initial=0` power-up determinism — do NOT add or
   remove `initial` yourself; do NOT over-fit to silence WARNs.

   EMIT-BLOCKING structural rules (ORGANIC-20260605, corpus-swept zero
   false-positives): `onebased-port-range` (prompt indexes the signal 1-based
   but the RTL declares `[W-1:0]` — declare `[W:1]`),
   `fsm-output-style-mismatch` (spec declares Moore but an output combinationally
   depends on an input — register it as f(state)), and the OR/XOR form of
   `vector-self-shift-fold` (`v | {…, 1'b0}` — the unshifted operand LEAKS the
   boundary bit; blocks ONLY when the prompt REQUIRES that output's boundary to
   be zero — a don't-care boundary downgrades to a `structural_advisories`
   entry; the AND form `v & {1'b0, …}` is the legitimate masking idiom and stays
   WARN). When `gates.json` carries `structural_emit_block`, the sample was NOT
   emitted: apply the finding's fix to `sample.sv` and re-run the gate.

6. Fix conformance ERRORs (wrong port name/width/dir vs prompt), emit-blocking
   structural findings, or compile errors and re-run the gate.

7. Confirm `<RUNDIR>/samples/<Prob>_sample01.sv` exists.

## After the batch — DO NOT run the scorer

The host orchestrator scores via the canonical scorer at
`${CLAUDE_PLUGIN_ROOT}/benchmark/score_iverilog_tb.py` AFTER all batches
finish. Generation must stay blind; only the scorer touches the hidden TB/ref.

## Final report (compact table)
Per `<Prob>`: sample emitted (y/n) | eda_lint pass/fixed | eda_synth cells+latches |
gates hard-PASS (y/n) | any structural fix applied | any problem you could not
emit (with reason).
