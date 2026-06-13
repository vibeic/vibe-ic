# Blind RTL author — RTLLM v2.0 + Vibe-IC v0.1.26 + MCP-EDA (shared agent instructions)

You process ONE batch of RTLLM designs, fully blind, emitting a scoreable RTL sample per design.
PARAMS your caller gives you:
- `DATASET`   = /home/reyerchu/AI_IC_design/_extbench/RTLLM   (the RTLLM repo root)
- `RUNDIR`    = /home/reyerchu/vibe-ic/benchmark_external/rtllm/run_blind_v0126
- `BATCHFILE` = absolute path to a list of design dirs (one per line, relative to DATASET) — YOUR batch

## ABSOLUTE BLINDNESS RULE (violating invalidates the run)
For each `<design>` you may read ONLY `<DATASET>/<design>/design_description.txt`.
NEVER open / cat / grep / list `<DATASET>/<design>/testbench.v` or `verified_*.v` (the hidden
reference + testbench, scored later by a deterministic host scorer you do NOT run). Reading them
in any way = cheating. You may NOT read `LLM_generated_verilog.v` either.

## Per-design procedure (every `<design>` in BATCHFILE)
1. Read ONLY `<DATASET>/<design>/design_description.txt`. Extract: the EXACT module name (the
   description states "Module name: <name>"), the exact port list (names / dirs / widths), and the
   required behavior + algorithm. The module name is NOT "TopModule" here — use the design's stated
   name (e.g. `multi_8bit`, `adder_16bit`) verbatim, because the hidden testbench instantiates the
   DUT by that exact name.
2. `leaf` = the last path component of `<design>` (e.g. `Arithmetic/Multiplier/multi_8bit` → `multi_8bit`).
   It equals the module name for these designs.
3. Write `<RUNDIR>/work/<leaf>/sample.v` — synthesizable Verilog-2001/SV, module named exactly as
   the description states, with the description's exact port declaration, implementing the behavior.
   Blind, from the description only.
4. Stage for MCP (mkdir -p first):
   `cp <RUNDIR>/work/<leaf>/sample.v /home/reyerchu/AI_IC_design/_bench_stage/v0126/rtllm/<leaf>/<module>.v`
   (container path: `/foss/designs/_bench_stage/v0126/rtllm/<leaf>/<module>.v`)
   If a later MCP call reports "files not visible in container", re-run the cp with the Bash sandbox
   disabled (`dangerouslyDisableSandbox: true`) and retry.
5. MCP `eda_lint`: `verilog_files=["/foss/designs/_bench_stage/v0126/rtllm/<leaf>/<module>.v"]`,
   `top_module="<module>"`. Must be 0 errors. Fix + re-stage + re-lint on errors.
6. MCP `eda_synth`: same container path, `top_module="<module>"`, `pdk="gf180"`,
   `output_netlist="/foss/designs/_bench_stage/v0126/rtllm/<leaf>/net.v"`. Must synth cleanly.
   Apply semantics-preserving fixes if flagged: LATCH→add default/else or always_comb; reset-less
   registered power-up→use a separate `initial`; CASEINCOMPLETE→add default; CASEOVERLAP→rewrite as
   priority if/else-if. Re-stage + re-synth after any fix.
7. Syntax-gate the sample (no testbench, no ref): `iverilog -g2012 -o <RUNDIR>/work/<leaf>/syn.bin
   <RUNDIR>/work/<leaf>/sample.v`. Must compile. (The module may have unused outputs at this stage;
   that's fine — it just must be syntactically complete and self-consistent.)
8. On lint-clean + synth-clean + iverilog-compile, copy the scoreable artifact:
   `cp <RUNDIR>/work/<leaf>/sample.v <RUNDIR>/samples/<leaf>.v`
   Confirm `<RUNDIR>/samples/<leaf>.v` exists.

Do NOT run any scorer. Do NOT touch `testbench.v` / `verified_*.v` / `LLM_generated_verilog.v`.
The host orchestrator scores later via iverilog + the hidden testbench. Emit a best-effort sample
for EVERY design — even an ambiguous description should still get a sample.

## Final report (compact table)
Per `<leaf>`: module name | sample emitted (y/n) | eda_lint (pass/fixed) | eda_synth cells+latches |
iverilog compile (y/n) | any structural fix | any design you could not emit (with reason).
