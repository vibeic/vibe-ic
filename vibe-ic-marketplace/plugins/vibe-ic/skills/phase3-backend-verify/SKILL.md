---
name: phase3-backend-verify
description: After phase3_one_shot_runner produces synth netlist + DEF + GDS + STA + DRC reports, AI spot-checks design quality. Triggers on /vibe-ic-phase3 / /vibe-ic-phase23 PASS or phrases like "review backend", "check tapeout readiness", "verify GDS".
tier: verification
paired_program: phase3_one_shot_runner.py
---

# Phase 3 Backend Verification

**Purpose**: phase3 runner is a thin orchestrator over yosys / OpenROAD / KLayout / Netgen. PASS just means the tools didn't error. Whether the resulting silicon is FAB-ready is a separate question.

## Verification checklist

1. **Synth quality**:
   - Read `phase3/synth/synth.log` — count cells, area, gate types
   - Detect inferred latches (FATAL — fix RTL)
   - Detect implicit width truncation warnings
   - Compare cell count to L8 typical_gate_count if defined

2. **Floorplan / utilization**:
   - Read `phase3/pnr/area.rpt` — confirm utilization between 50%-75%. <40% wastes silicon, >85% causes routing congestion
   - Confirm core_area covers all macro instances + std cells
   - Confirm IO ring + power straps not overlapping core

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
   - file size sane (~3-5 MB for ~1700 cell design)
   - top cell name matches `--top-name` argument
   - includes merged macro PA-GDS (file size jumps when macro merged)

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

Append findings to `<project>/reports/phase3_verify.md`. PASS summary or escalation list.


## Compliance gate (mandatory — not optional)

After producing your output, save it to a file and run:

```bash
python3 ../../_shared/skill_compliance_check.py \
    --requirements ./compliance.yaml <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with the specific missing elements listed.
`compliance.yaml` (in this skill's directory) enumerates every required
element of your output — section headers, metadata fields, handoff lines,
tool invocations.

**Your task is not complete until the audit returns PASS.** If it fails,
re-read the listed missing elements, patch your output, and re-run the
audit.

