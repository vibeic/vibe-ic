---
name: phase3-backend-verify
description: Review backend native tool measurements and reports from the sole table engine against their original limits, including synthesis, DEF, GDS, STA and DRC.
tier: verification
paired_program: flow_engine.py
---

# Phase 3 Backend Verification

Read `<project>/reports/flow_engine.json` from the normal public runner. The
Router selects the task window and `flow/steps.json` defines its ordered rows;
there is one engine run path. Identify steps by their current table position
and `name`, never by a retired public step ID.

For every selected backend row, read `tool_ran`, `native_steps`,
`native_metrics`, `metrics`, and the native paths in `reports`. Open each
underlying tool report and compare the actual measurement, operator and limit
with the original spec, PDK or owner requirement. Check that the tool consumed
the intended design and corner. An exit code or summary PASS does not prove
that the resulting silicon satisfies its engineering requirements.

AI review each result for physical plausibility, missing coverage and defects
that the reported number cannot describe. Keep the existing per-row review
and measured review duration with that result. A missing native value, missing
original limit or unexecuted selected tool remains `NOT_MEASURED`; disclose it
without fabricating a number or changing a limit. Do not claim tapeout readiness
without DRC=0, WNS≥0 and all applicable native measurements meeting their
original limits. Deferred work remains open work.

Use the actual report paths saved by the engine. The paths below illustrate
the corresponding report type; they do not override the run's native paths.

## Verification checklist

1. **Synth quality**:
   - Read the actual Yosys log and native elaboration/synthesis result. Resolve inferred latches, width truncation, unresolved modules and other tool diagnostics in the design or tool before rerunning synthesis.
   - AI residual only: read cells/area/gate-types and compare cell count to L8
     typical_gate_count if defined (judgment, no fixed threshold in spec).

2. **Floorplan / utilization**:
   - Read utilization from the native physical database. Retain the advisory 50–75% planning band; fixed-die designs may legitimately differ. A value at or below zero or above 100% requires investigation, not a fabricated placement result.
   - AI residual only: confirm core_area covers all macro instances + std cells, and that the
     IO ring + power straps are not overlapping the core (structural judgment).

3. **STA — multi-corner**:
   - Read `phase3/reports/sta.rpt` — ALL slacks must be ≥0
   - Critical paths shouldn't hit `set_max_delay` boundary; identify margin
   - Hold violations are NOT acceptable even if setup is clean
   - For complete sign-off: SS / TT / FF corner all checked, not just TT

4. **DRC**:
   - Read `phase3/reports/drc.rpt`
   - violations=0 PASS, ≥1 FAIL or WAIVED depending on rule
   - If WAIVED with Calibre deck pointer: confirm offline Calibre run is scheduled
   - Density / antenna violations are common late-stage issues

5. **LVS**:
   - Read `phase3/reports/lvs.rpt` (or note if WAIVED)
   - Net mismatches indicate floorplan / connectivity bug
   - Device count mismatches indicate wrong macro picked

6. **GDS sanity**:
   - Open the final GDS with the native layout tool. Check that the intended geometry was loaded and compare its measured extent and content with the required design scope.
   - Read the GDS hierarchy with the native layout tool and confirm that the selected top cell is the intended root, with all required child cells resolved.
   - AI residual only: sanity-check that the file size is consistent with a merged macro
     PA-GDS (size jumps when a hard macro is merged) — judgment, no fixed threshold.

7. **Power / EM / IR estimates**:
   - if available, read `phase3/reports/power.rpt`
   - Compare to L8 power budget if defined

## Spot-check actions

- Open the GDS in KLayout (offscreen) and visually confirm metal stack reasonable.
- Diff this design's `area.rpt` and `sta.rpt` vs prior known-good run; flag regressions.
- Check critical timing paths: do they make sense (clock-to-clock through expected logic) or are they bizarre artifacts?

## When to escalate

- DRC violations >0 → invoke `drc-fix`
- Setup slack <0 → invoke `sta-review` then `eco-plan`
- Hold violations → invoke `hold-fix`
- LVS mismatch → invoke `lvs-triage`
- Utilization wildly off → re-run with adjusted `--die-um` / `--util`

## Output

Append findings to `<project>/reports/phase3_verify.md`. For each selected row, record its current position/name, native report and value, original limit, AI finding, and any FAIL or `NOT_MEASURED` obligation. Keep a measured PASS distinct from deferred or unmeasured work.
