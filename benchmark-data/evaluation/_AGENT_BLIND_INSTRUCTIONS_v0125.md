# Blind RTL author — Vibe-IC v0.1.25 + MCP-EDA (shared agent instructions)

You process ONE batch of VerilogEval problems, fully blind, emitting a scoreable RTL sample per problem.
Your caller gives you these PARAMS:
- `BENCH`      one of: v2 | human | machine   (only used in the stage path)
- `DATASET`    absolute dir holding `<Prob>_prompt.txt` (and the hidden refs you must NOT read)
- `RUNDIR`     absolute run dir (has `gates.py`, `work/`, `samples/`, `batches/`)
- `BATCHFILE`  absolute path to a list of `<Prob>` names (one per line) — YOUR batch
- `STAGE`      = BENCH (used in `/foss/designs/_bench_stage/v0125/<STAGE>/...`)

## ABSOLUTE BLINDNESS RULE (violating invalidates the run)
For each problem you may read ONLY `<DATASET>/<Prob>_prompt.txt`.
NEVER open / read / cat / grep / list `<Prob>_ref.sv` or `<Prob>_test.sv`. They are the hidden
reference + testbench, scored later by a separate deterministic scorer you do NOT run. Reading them
in any way = cheating.

## Per-problem procedure (every `<Prob>` in BATCHFILE)
1. Read ONLY `<DATASET>/<Prob>_prompt.txt`. Extract: module name (always `TopModule`), exact port
   list (names / dirs / widths), and required behavior. (Machine prompts are verbose LLM prose and
   may be self-contradictory — make your best honest interpretation; do NOT hunt for the hidden ref.)
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
       <name>: { dir: input,  width: <N> }    # width = bit count; scalar = 1
       <name>: { dir: output, width: <N> }
   ```
   Use the prompt's EXACT port names/dirs/widths. `[3:0]` => width 4.
3. Write `<RUNDIR>/work/<Prob>/sample.sv` — synthesizable SystemVerilog, module `TopModule` with the
   prompt's exact port declaration, implementing the behavior. Blind, from the prompt only.
4. Stage for MCP (mkdir -p first):
   `cp <RUNDIR>/work/<Prob>/sample.sv /home/reyerchu/AI_IC_design/_bench_stage/v0125/<STAGE>/<Prob>/TopModule.sv`
   If a later MCP call reports "files not visible in container", re-run the cp with the Bash sandbox
   disabled (`dangerouslyDisableSandbox: true`) and retry.
5. MCP `eda_lint`: `verilog_files=["/foss/designs/_bench_stage/v0125/<STAGE>/<Prob>/TopModule.sv"]`,
   `top_module="TopModule"`. Must be success / 0 errors. Fix + re-stage + re-lint on errors.
6. MCP `eda_synth`: same container path, `top_module="TopModule"`, `pdk="gf180"`,
   `output_netlist="/foss/designs/_bench_stage/v0125/<STAGE>/<Prob>/net.v"`. Must synth cleanly.
   Apply these semantics-preserving fixes if lint/synth flags them:
   - LATCH but combinational intended -> add `default`/`else` so every branch assigns (or `always_comb`).
     If a transparent latch IS intended, code `always_latch`.
   - PROCASSINIT (decl-init on a reg also procedurally assigned) -> for reset-less power-up state use a
     SEPARATE `initial q = 0;` block, not `output reg q = 0`.
   - CASEOVERLAP -> rewrite overlapping `casez` priority encoder as an equivalent priority if/else-if.
   - CASEINCOMPLETE -> add explicit `default`.
   Re-stage + re-synth after any fix.
7. Run the deterministic gate (emits the scoreable sample on hard-PASS). **Use an ABSOLUTE `--workdir`**
   (a relative path breaks phase1_run_all, which runs with cwd=repo root):
   ```
   cd <RUNDIR>
   python3 gates.py --prob <Prob> --workdir <RUNDIR>/work --dataset <DATASET>
   ```
   Hard gates = phase1_run_all + iverilog_compile. On hard-PASS it writes
   `<RUNDIR>/samples/<Prob>_sample01.sv`. Fix conformance ERRORs (wrong port name/width/dir vs prompt)
   or compile errors and re-run. The gate ENFORCES `rtl_hygiene_lint --fix` (step 5a) before emit, so
   reset-less registered outputs are auto-given `initial=0` power-up determinism — you do NOT need to
   add `initial` yourself, and you must NOT remove it. Remaining WARN-level items (spec_conformance
   WARN, residual rtl_hygiene WARN) are OK — do NOT over-fit to silence WARNs. (Do NOT treat the
   power-up WARN as "OK to leave at X" — the gate now repairs it; leaving it to the agent re-opened
   the v0.1.24 self-inflicted dip on Prob034/053/104.)
8. Confirm `<RUNDIR>/samples/<Prob>_sample01.sv` exists.

Do NOT run any scorer. Do NOT touch `_ref.sv` / `_test.sv`. The host orchestrator scores later.
Emitting a best-effort sample is the goal for EVERY problem (gates need only compile+phase1, not
functional correctness) — even a contradictory prompt should still get a sample emitted.

## Final report (compact table)
Per `<Prob>`: sample emitted (yes/no) | eda_lint (pass/fixed) | eda_synth cells+latches | gates hard-PASS
(yes/no) | any structural fix applied | any problem you could not emit (with reason).
