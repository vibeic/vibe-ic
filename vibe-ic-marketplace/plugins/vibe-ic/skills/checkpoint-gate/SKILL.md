---
name: checkpoint-gate
description: "Verify that all required artifacts exist and pass quality checks before advancing to the next phase. Triggers at Phase 1→2 and Phase 2→3 transitions. Use when: 'ready to proceed', 'check if we can move on', 'checkpoint', 'sign off', or at the end of each phase. This is a MANDATORY gate — no phase transition without passing."
---


<!-- WAVE_76_CHIP_AGNOSTIC_BANNER -->

> **Case-study notation.** This skill cites the <chip-class> / <half-duplex-tester> /
> MDV-A1101 <benchmark> reference project as concrete evidence for the
> rules below. The rules themselves are chip-AGNOSTIC and apply to
> any IC of the matching `ic_class` (see
> `vibe-ic-marketplace/plugins/vibe-ic-d/programs/ic_class_profile.py`).
> When you adopt this skill on a different IC, swap `<chip-class>` →
> `<your IC name>` and `<half-duplex-tester>` → `<your host-tester name>`; the
> structural gates and rule bodies do not depend on those SKUs.
> See `docs/design/CASE_STUDIES/AS3616_*.md` for the full <benchmark>
> regression history.

# Checkpoint Gate — Phase Transition Verification

Verify all required deliverables exist and meet quality standards before allowing the design to proceed to the next phase.

## Deterministic gate (run this FIRST — single command per checkpoint)

The required-file checklist + the fixed numeric thresholds (DS>=70, AN>=56,
spec 0-ERROR, SVA>=8, DRC<=5, cell_count>0) + the SOF-non-zero check are now
codified in one deterministic program so every agent applies the **same**
files and the **same** numbers every time:

```bash
python3 programs/checkpoint_gate_check.py <project_dir> --checkpoint {1|2|3} --json
```

- Exit `0` = PASS (every required file present + every applicable threshold met).
- Exit `1` = FAIL (a required file is MISSING or a threshold is violated).
- Exit `2` = usage / project-dir I/O error.

It degrades gracefully: an absent artifact is reported `MISSING` (never a
crash, never silently passed); the external scorers
(`ds_quality_check.py` / `an_validator.py` / `spec_validator.py` /
`synth_doctor.py`, which ship in the repo-root `tools/` dir) are reported
`MISSING-SCORER` if unavailable on this host so you know to re-run the score
on a machine that has them — `MISSING-SCORER` alone does NOT flip a PASS to
FAIL. A clean DRC report (no `violation` token) correctly counts 0, so there
is no false alert.

**Run the program FIRST.** The per-checkpoint prose below is the human
explanation of what the program enforces PLUS the genuinely-qualitative
checks the program cannot evaluate (pin-name consistency between DS/AN,
register-address agreement, schematic↔RTL signal match, STA waiver
documentation) — those still need AI judgment. Do not hand-eyeball the
numeric thresholds; let the program own them.

## Checkpoint 1: Phase 1 → Phase 2 (Spec → Design)

### MANDATORY first gate: all 10 L-layer docs

Before anything else, run:
```
python3 vibe-ic-d/programs/phase1_doc_presence_check.py generated_docs/
```
MUST exit 0. Required layers: L1 datasheet, L2 FRS, L3 cmd protocol, L4 regmap,
L5 ADI spec, L6 control logic, L7 test/debug, L8 timing, L8 rtl-constants,
L9 integration. **Skipping any L-layer is a known regression class**:
when intermediate layers (L2/L4/L5/L6/L7/L8R) are skipped, fresh
agents produce a simplified L9 that drops mandatory submodule pins,
and the project's `<host_tester>` then FAILs at integration.

> **Case study reference.** Concrete example documenting this
> regression class (<chip-class> v041-v043 → <half-duplex-tester> FAIL on
> dclk/drst/pad_ctrl/rx_chk/rx_cmd/dis_cnt/spare/otp_ctrl/gen_wake):
> see `docs/design/CASE_STUDIES/AS3616_v041_L_layer_skip_regression.md`.

### Required Files
- [ ] `phase1_spec/01_prompt.md` — original user input
- [ ] `phase1_spec/02_dialog.md` — AI conversation log (≥2 rounds)
- [ ] `phase1_spec/03_spec_confirmed.md` — confirmed specification
- [ ] `phase1_spec/04_datasheet.md` — 10-section datasheet (score ≥7)
- [ ] `phase1_spec/05_appnote.md` — 8-section application note (score ≥7)
- [ ] `generated_docs/` — all 10 L1-L9 JSONs (enforced by phase1_doc_presence_check.py)

### Quality Checks

**Codified in `checkpoint_gate_check.py --checkpoint 1` (let the program own these):**
- [ ] All 5 `phase1_spec/0*.md` files present + `generated_docs/` 10/10 L-layer docs
- [ ] `ds_quality_check.py` score >= 70/100
- [ ] `an_validator.py` score >= 56/80
- [ ] `spec_validator.py` reports 0 ERROR-level mismatches

**Still requires AI judgment (the program cannot fully evaluate these):**
- [ ] Datasheet has no TBD values
- [ ] Pin names consistent between DS and AN
- [ ] Register addresses match between DS and AN firmware example
- [ ] All timing parameters have min/typ/max
- [ ] If RTL is already drafted: `spec_conformance_check.py` reports 0 ERROR
      (ports + reset mode/polarity + latency match the spec contract)

### Automated Quality Gate Commands

Run these commands from the project root (all must pass):

```bash
# 1. Datasheet quality score (must be >= 70/100)
python3 tools/vibe_ic_tools/ds_quality_check.py phase1_spec/04_datasheet.md --json
# Check: .total_score >= 70

# 2. Application note quality score (must be >= 56/80)
python3 tools/vibe_ic_tools/an_validator.py phase1_spec/05_appnote.md --json
# Check: .total_score >= 56

# 3. Cross-consistency check (must have 0 errors)
python3 tools/vibe_ic_tools/spec_validator.py \
    --ds phase1_spec/04_datasheet.md \
    --an phase1_spec/05_appnote.md \
    --spec phase1_spec/03_spec_confirmed.md \
    --json
# Check: .consistent == true (i.e., .summary.errors == 0)

# 3b. Spec↔RTL contract conformance (only if RTL already exists; must have 0 ERROR)
python3 programs/spec_conformance_check.py \
    --spec phase1_spec/04_datasheet.md \
    --rtl-dir phase2/stage1/rtl --top <module> --json /tmp/conf.json
# Check: 0 ERROR findings (port-missing/extra/dir/width, reset-*-spec-mismatch)

# 4. Log results (unified JSONL)
python3 tools/vibe_ic_tools/vibe_ic_log.py log \
    --ic <IC_NAME> --phase 1 --stage checkpoint1 \
    --tool checkpoint-gate --status PASS \
    --metrics '{"ds_score":<DS>,"an_score":<AN>,"mismatches":0}' \
    --output pipeline.jsonl
```

### Output
Write `phase1_spec/checkpoint1_signoff.md`:
```markdown
# Checkpoint 1 Sign-off — <IC_NAME>
Date: <date>
Score: DS=<X>/10, AN=<Y>/10
Files: 5/5 present
Quality: <PASS/FAIL>
Decision: PROCEED TO PHASE 2 / REVISE
```

## Checkpoint 2: Phase 2 → Phase 3 (Design → Verify)

### Required Files
- [ ] `phase2_design/rtl/<module>.sv` — synthesizable RTL
- [ ] `phase2_design/rtl/<module>_formal.sv` — SVA assertions (≥8)
- [ ] `phase2_design/synth/synth.log` — synthesis log (0 errors)
- [ ] `phase2_design/synth/synth_<module>.v` — PDK-mapped netlist
- [ ] `phase2_design/pnr/<module>.def` — P&R layout
- [ ] `phase2_design/gds/<module>.gds` — GDSII file
- [ ] `phase2_design/signoff/drc_report.rpt` — DRC (target: 0 violations)
- [ ] `phase2_design/schematic/<module>_schematic.md` — circuit diagram

### Quality Checks

**Codified in `checkpoint_gate_check.py --checkpoint 2` (let the program own these):**
- [ ] All 8 required RTL/synth/pnr/gds/signoff/schematic files present
- [ ] `programs/synth_doctor.py` verdict != MANUAL_REVIEW (CLEAN/DIAGNOSED ok)
- [ ] Cell count > 0 (from synth.log, not just file existence)
- [ ] SVA assertion count >= 8 (in `*_formal.sv`)
- [ ] DRC: if `drc_report.rpt` exists, violations <= 5 (else reported SKIP)

**Still requires AI judgment (the program cannot fully evaluate these):**
- [ ] P&R: placement + routing complete
- [ ] All signals in schematic match RTL ports

### Automated Quality Gate Commands

Run these commands from the project root (all must pass):

```bash
# 1. Synth doctor — log must not classify to an un-fixable error pattern
python3 programs/synth_doctor.py phase2_design/synth/synth.log --json
# Check: .verdict is "CLEAN" or "DIAGNOSED" (MANUAL_REVIEW => human triage needed)
# Check: cell count > 0 separately (grep synth.log; synth_doctor only classifies errors)

# 2. SVA assertion count (must be >= 8)
grep -c 'assert\s*property\|assert\s*(' phase2_design/rtl/*_formal.sv
# Check: count >= 8
# Alternative one-liner:
ASSERT_COUNT=$(grep -c -E 'assert\s+property|assert\s*\(' phase2_design/rtl/*_formal.sv 2>/dev/null || echo 0)
if [ "$ASSERT_COUNT" -lt 8 ]; then echo "FAIL: Only $ASSERT_COUNT assertions (need >=8)"; fi

# 3. DRC violations check (if DRC report exists)
if [ -f phase2_design/signoff/drc_report.rpt ]; then
    DRC_COUNT=$(grep -c -i 'violation' phase2_design/signoff/drc_report.rpt 2>/dev/null || echo 0)
    if [ "$DRC_COUNT" -gt 5 ]; then echo "FAIL: $DRC_COUNT DRC violations (max 5)"; fi
fi

# 4. P&R doctor (optional, for additional diagnostics)
python3 programs/pnr_doctor.py phase2_design/pnr/pnr.log --json
# Check: .verdict is "CLEAN" or "DIAGNOSED" (MANUAL_REVIEW => human triage needed)

# 5. Log results
python3 tools/vibe_ic_tools/vibe_ic_log.py log \
    --ic <IC_NAME> --phase 2 --stage checkpoint2 \
    --tool checkpoint-gate --status PASS \
    --metrics '{"cells":<N>,"assertions":<N>,"drc_violations":<N>}' \
    --output pipeline.jsonl
```

### Output
Write `phase2_design/checkpoint2_signoff.md`

## Checkpoint 3: Phase 3 → Production

### Required Files (Quartus FPGA Flow on <host>)
- [ ] `phase3_verify/fpga/<module>_fpga.qpf` — Quartus project file
- [ ] `phase3_verify/fpga/<module>_fpga.qsf` — Quartus settings (device=5CSEBA6U23I7, pin assignments)
- [ ] `phase3_verify/fpga/<module>_fpga.sdc` — SDC timing constraints
- [ ] `phase3_verify/fpga/<module>_fpga_top.sv` — FPGA top wrapper (connect DUT to DE10-Nano pins)
- [ ] `phase3_verify/fpga/compile.log` — Quartus compilation log (map+fit+asm+sta)
- [ ] `phase3_verify/fpga/<module>_fpga.sof` — SRAM Object File for programming
- [ ] `phase3_verify/fpga/fit.summary` — Fitter resource summary (ALMs, registers, pins)
- [ ] `phase3_verify/fpga/sta.summary` — Timing analysis summary

### Quality Checks

**Codified in `checkpoint_gate_check.py --checkpoint 3` (let the program own these):**
- [ ] All 7 required Quartus FPGA files present (qpf/qsf/sdc/top/compile.log/fit.summary/sta.summary)
- [ ] SOF file generated (non-zero size)

**Still requires AI judgment (the program cannot fully evaluate these):**
- [ ] Quartus map: 0 errors
- [ ] Quartus fit: successful placement & routing
- [ ] STA: no setup/hold violations (or documented waivers)

### FPGA Flow Commands (on <host>, Quartus 23.1 Lite)
```bash
export PATH="~/eda/quartus/quartus/bin:$PATH"
cd phase3_verify/fpga/
quartus_map <module>_fpga    # Analysis & Synthesis
quartus_fit <module>_fpga    # Fitter (Place & Route)
quartus_asm <module>_fpga    # Assembler (Generate SOF)
quartus_sta <module>_fpga    # Timing Analysis
```

### Output
Write `phase3_verify/checkpoint3_signoff.md` with SOF size, resource usage, timing result

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
audit. This guarantees that different agents executing this same SKILL.md
produce reports containing the same required elements, even when the prose
inside each element differs. Missing elements are the single largest
source of skill-execution non-determinism.
