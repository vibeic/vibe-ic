# Shape C blind instructions — atomic-micro-problem benchmark (VerilogEval-class)

You process a BATCH of atomic micro-problems blind, emitting a scoreable RTL sample
per problem. Per `open-benchmark-methodology` skill § 2 Shape C: lightweight
gates-based harness — running the full Vibe-IC runner per problem is
overhead-dominated for ≥100 atomic problems, but **every verification GATE is
still a plugin program** (`phase1_engine`, `spec_conformance_check`,
`rtl_hygiene_lint --fix`, `iverilog`).

PARAMS your caller provides:
- `BENCH`     benchmark name (e.g. `verilogeval-v2`, `verilogeval-human`) — used by gates_atomic.py
- `DATASET`   absolute path to dataset (flat dir with `<Prob>_prompt.txt`, hidden `<Prob>_test.sv` / `<Prob>_ref.sv`)
- `RUNDIR`    absolute path to run dir (with `work/`, `samples/`, `batches/`)
- `BATCHFILE` list of `<Prob>` ids — your batch

## ABSOLUTE BLINDNESS RULE
For each `<Prob>` you may read ONLY `<DATASET>/<Prob>_prompt.txt`.
NEVER open / cat / grep / list `<Prob>_test.sv` or `<Prob>_ref.sv` (the hidden testbench +
golden reference, touched ONLY by the host scorer at scoring time).

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
   python3 ${CLAUDE_PLUGIN_ROOT}/benchmark-harness/gates_atomic.py \\
       --prob <Prob> \\
       --workdir <RUNDIR>/work \\
       --dataset <DATASET> \\
       --bench <BENCH>
   ```
   Hard gates = `phase1_run_all` + `iverilog_compile`. On hard-PASS the gate
   writes `<RUNDIR>/samples/<Prob>_sample01.sv`. The gate ENFORCES
   `rtl_hygiene_lint --fix` (step 5a) before emit, so reset-less registered
   outputs are auto-given `initial=0` power-up determinism — do NOT add or
   remove `initial` yourself; do NOT over-fit to silence WARNs.

6. Fix conformance ERRORs (wrong port name/width/dir vs prompt) or compile
   errors and re-run the gate.

7. Confirm `<RUNDIR>/samples/<Prob>_sample01.sv` exists.

## After the batch — DO NOT run the scorer

The host orchestrator scores via the canonical scorer at
`${CLAUDE_PLUGIN_ROOT}/benchmark-harness/score_iverilog_tb.py` AFTER all batches
finish. Generation must stay blind; only the scorer touches the hidden TB/ref.

## Final report (compact table)
Per `<Prob>`: sample emitted (y/n) | eda_lint pass/fixed | eda_synth cells+latches |
gates hard-PASS (y/n) | any structural fix applied | any problem you could not
emit (with reason).
