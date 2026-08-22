# Shape D blind instructions — agentic SoC / cocotb-harness benchmark (CVDP-class)

You drive a Shape-D project through the **Vibe-IC runner** for the SoC-grade path,
then score via the hidden cocotb harness. Per `open-benchmark-methodology` § 2
Shape D: runner is the right tool because (a) the IC needs `ic_class` dispatch,
(b) `catalog-glue-author` may fire for REUSED-IP, (c) the cocotb harness is
invoked via MCP `eda_cocotb` / `docker exec` against the vibeic-eda container.

PARAMS your caller provides:
- `PROJECT`   Shape-D project dir, containing:
              - `work/PROMPT.txt`            (blind input)
              - `work/docs/specification.md` (blind input)
              - `score/src/test_<dut>.py`    (HIDDEN — for scoring only)
              - `score/src/test_runner.py`   (HIDDEN — for scoring only)
              - `score/src/harness_library.py` (HIDDEN — for scoring only)
              - `score/docker-compose.yml`   (HIDDEN if shipped)
- `TOP`       the DUT module name (per the spec)
- `MOUNT_ROOT` host path mounted into vibeic-eda as /foss/designs

## ABSOLUTE BLINDNESS RULE
You may read ONLY `<PROJECT>/work/PROMPT.txt` + `<PROJECT>/work/docs/specification.md`.
NEVER open / cat / grep / list anything under `<PROJECT>/score/` (the hidden
cocotb harness). The host scorer (`benchmark/score_cocotb_mcp.py`) is the
only thing that touches `score/`.

**CROSS-PROBLEM PROHIBITION (ORGANIC-20260605-blindness-rule-cross-problem-refs).**
The rule binds for the WHOLE dataset: you may NOT read ANY dataset file
outside the current `<PROJECT>`'s blind inputs — explicitly including OTHER
projects' `score/` harnesses, reference solutions, and any other run
directory's outputs. Sibling references encode the dataset's authoring
conventions, so reading them is dataset-internal solution knowledge.
Applies EQUALLY to close-loop / repair agents. Explicitly included:
**dataset BUILD files** (Makefile / *.mk / docker-compose — flow and
naming authority) and **self-running the scoring harness or any
verdict-level oracle query mid-loop** (scoring is the HOST's
post-generation step; self-verify with your OWN testbench only).
Deterministic enforcement: transcripts exported to
`<RUNDIR>/transcripts/` are audited by `programs/blindness_audit.py`.

## Procedure

1. Read ONLY `<PROJECT>/work/PROMPT.txt` + `<PROJECT>/work/docs/specification.md`.
   Extract: DUT module name, full port list, reset semantics, expected behaviors.

2. **Drive the runner** (the primary author — does NOT author RTL directly):
   ```
   python3 ${CLAUDE_PLUGIN_ROOT}/programs/vibe_ic_one_shot_runner.py <PROJECT> \\
       --pdk sky130A --ic-name <ic>
   ```
   The runner: phase1 (extract L docs from PROMPT + spec) → phase2 (spec-to-rtl
   or `catalog-glue-author` if SoC + REUSED-IP catalog matches; e.g. SERV core
   for `subservient`-class problems). If catalog-glue fires, the agent's only
   authoring touch is the chip-top + glue from the L docs; the SERV/etc. core
   is REUSED-IP and tagged honestly in `SOURCE_MANIFEST.md`.

3. If the runner produces RTL successfully, candidate RTL lives at
   `<PROJECT>/work/rtl/<top>.sv` (or `<PROJECT>/phase2/stage1/rtl/<top>.sv`).
   Move/copy it to the location the score script expects:
   `<PROJECT>/work/rtl/<top>.sv`.

4. **Reset-robustness consideration** (the v0.1.24 documented finding —
   skill § 4 Cat A): some CVDP specs say "synchronous reset" but the hidden
   cocotb harness's `reset_dut` asserts `grant==0` immediately after
   `RisingEdge(clk)` with no settle, racing a synchronous-reset NBA update.
   If the spec uses synchronous reset, the runner / agent should ALSO emit an
   `<top>_async.sv` variant coded `always @(posedge clk or posedge reset)` so
   the cleared state is visible on reset assertion regardless of read timing.
   Keep both; the scorer will reveal which one the harness accepts.

5. **Self-verify pre-score** (still blind — your OWN testbench, NOT the hidden one):
   - MCP `eda_lint`: 0 errors.
   - MCP `eda_synth` (gf180): clean, count cells / DFF / latch.
   - MCP `eda_simulate` with your OWN small directed TB built from the spec:
     exercise priority + override + reset (whatever the spec defines).

6. **Score via the hidden harness** (the ONLY step that touches `score/`):
   ```
   python3 ${CLAUDE_PLUGIN_ROOT}/benchmark/score_cocotb_mcp.py \\
       --project <PROJECT> --top <top> --rtl work/rtl/<top>.sv \\
       --mount-root <MOUNT_ROOT>
   ```
   The scorer writes `<PROJECT>/reports/cocotb_score.json` with TESTS/PASS/FAIL.

## Honesty
- Document any spec ↔ hidden-harness inconsistency surfaced (e.g. sync vs async
  reset) in the project's RESULT.md — per skill § 4 Cat A this is FLOOR, not
  fixable by peeking at the harness.
- If `catalog-glue-author` fired, the GENERATED vs REUSED-IP split MUST be in
  `SOURCE_MANIFEST.md`; production credit applies only to GENERATED content.

## Final report
- runner verdict (PASS / PASS_WITH_WAIVERS / FAIL) + halted_at
- cocotb_score.json TESTS=X PASS=Y FAIL=Z SKIP=W
- GENERATED vs REUSED-IP split (from SOURCE_MANIFEST)
- any spec↔harness inconsistency observed
