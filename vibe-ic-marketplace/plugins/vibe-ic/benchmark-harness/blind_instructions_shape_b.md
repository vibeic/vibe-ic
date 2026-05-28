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

## ABSOLUTE BLINDNESS RULE
For each `<design>` you may read ONLY `<DATASET>/<design>/design_description.txt`.
NEVER open / cat / grep / list `testbench.v` / `verified_*.v` / any
`LLM_generated_verilog.v`. The hidden TB / golden ref are touched ONLY by the host
scorer (`benchmark-harness/score_iverilog_tb.py`), at scoring time, not generation.

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

5. **Only if the runner FAILS at a phase2 step**, do a CLOSE-LOOP fix (agent's
   only authoring touch):
   - Read the failing step's log from `<project>/reports/orchestrator/phase2_one_shot.json`.
   - Apply a GENERAL, chip-agnostic fix (e.g. chip_top wrapper if missing, port
     name typo in phase1 extraction). Do NOT peek at the hidden testbench.
   - Re-run the runner from the failing step.
   - If close-loop succeeds, emit the sample as in step 4.

6. **NEVER author RTL directly to avoid runner failure**. The benchmark NUMBER
   measures what the runner produces. Direct-agent authoring would measure
   "LLM + MCP", not "Vibe-IC runner" (the 2026-05-28 RTLLM 37/50 worked example).

## Final report (compact table)
Per `<leaf>`: module name | runner verdict | sample emitted (y/n) | any close-loop
fix applied (what + why GENERAL) | any design not emittable (with reason).
