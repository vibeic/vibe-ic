---
name: phase3-backend-verify
description: After phase3_one_shot_runner produces synth netlist + DEF + GDS + STA + DRC reports, AI spot-checks design quality. Triggers on /vibe-ic-phase3 / /vibe-ic-phase23 PASS or phrases like "review backend", "check tapeout readiness", "verify GDS".
tier: verification
paired_program: phase3_one_shot_runner.py
---

# Phase 3 Backend Verification

> **Doctrine (v0.1.50):** 把修法寫進工具，而非寫進 prompt.
> Programs first; AI is the backstop on residual narrative.

## Mandatory Deterministic Preflight

```bash
python3 plugins/vibe-ic/programs/phase3_verify_aggregate.py \
    <project_dir> \
    --out-md /tmp/phase3_verify.md \
    --out-json /tmp/phase3_verify.json --strict
```

The aggregator runs `phase23_completion_audit`, `drc_zero_violations_check`,
`lvs_pass_check`, and `sta_report_check`; parses DRC count + WNS/TNS;
and checks 6 required-file presence. **Refuse to claim tape-out-ready
without DRC=0 AND WNS≥0 AND all backing checks PASS.**

**Purpose**: phase3 runner is a thin orchestrator over yosys / OpenROAD / KLayout / Netgen. PASS just means the tools didn't error. Whether the resulting silicon is FAB-ready is a separate question.

## Verification checklist

1. **Synth quality**:
   - Inferred-latch (FATAL) + implicit-width-truncation detection is **enforced by
     `programs/synth_doctor.py`** (LATCH_INFERENCE + WIDTH_MISMATCH classifiers).
     Run `python3 programs/synth_doctor.py phase3/synth/synth.log --json` and treat any
     `LATCH_INFERENCE` finding as FATAL (fix RTL). Do NOT re-derive these by eye.
   - AI residual only: read cells/area/gate-types and compare cell count to L8
     typical_gate_count if defined (judgment, no fixed threshold in spec).

2. **Floorplan / utilization**:
   - Utilization band is **enforced by `programs/utilization_band_check.py`** (advisory
     50-75% band; hard FAIL only on the universal impossible range — utilization ≤0 or
     >100%). Run `python3 programs/utilization_band_check.py <project_dir> --json /tmp/util.json`.
     The 40/50/75/85 numbers are a free-die rule-of-thumb, **advisory WARN only** — fixed-die /
     harness-bounded designs legitimately sit well below 50% (corpus 13-85%), so do NOT treat
     low utilization as a failure.
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
   - File existence / non-empty / valid GDSII header / minimum size is **enforced by
     `programs/gds_size_check.py`** (`--gds-file phase3/final.gds [--min-size-kb N]`).
   - Top-cell-name equality (top cell matches the `--top-name` argument) is **enforced by
     `programs/gds_topcell_name_check.py`** (`--gds-file phase3/final.gds --top-name <top>` —
     parses STRNAME/SNAME records, FAILs if the named cell is absent, WARNs if it is a
     referenced sub-cell rather than the hierarchy root). Do NOT eyeball the cell name.
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

