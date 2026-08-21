---
name: analog-hw-tuning-loop
description: Closed-loop hardware-in-the-loop analog tuning — iterates SPICE sizing → hardware build → measure → compare → adjust until hardware matches SPICE matches spec. Use when the user says "tune analog on hardware", "hardware convergence", "HIL tuning loop".
---

# Analog HW Tuning Loop

The master orchestrator for hardware-verified analog convergence. First converges in SPICE simulation, then validates on real hardware, iterating until all three sources agree: hardware measurement, SPICE prediction, and design spec.

## When to use

- Step A9 of the analog track (hardware verification)
- When the user says "tune the LDO on hardware", "verify analog on bench"
- After `analog-sizing-loop` has converged in simulation

## Inputs

1. `analog/<block>/spec.json` — target specs
2. `analog/<block>/sizing_final.json` — SPICE-converged sizing
3. `analog/<block>/corner_results.json` — SPICE simulation results
4. Hardware setup: FPGA board, scope, breadboard/PCB

## Two-phase convergence

### Phase 1: SPICE convergence (delegates to `analog-sizing-loop`)

Run the simulation-only loop until all PVT corners pass. This phase is fully automatic with no hardware needed.

### Phase 2: Hardware verification (max 3 iterations)

```
For each iteration:
  1. analog-hw-testbench-gen → generate FPGA stimulus RTL
  2. eda_fpga_compile → eda_fpga_program → program DE10-Lite
  3. Prompt user: "Confirm the breadboard circuit has been built"
     - Display component BOM derived from sizing_final.json
     - Show wiring diagram from hw_test/README.md
  4. analog-hw-measure → scope capture + ADC readings
  5. Three-way comparison + verdict — enforced by `programs/analog_hil_three_way_verdict.py`
  6. Iterate per the verdict; single-knob + iteration-cap discipline enforced by program (see below)
```

## Three-way comparison logic (enforced by program)

The four-row decision table (SPICE-vs-Spec, HW-vs-Spec, HW-vs-SPICE-discrepancy)
→ {CONVERGED | CONVERGED_WARNING | MODEL_INACCURACY | BACK_TO_PHASE1} is a pure
lookup — **enforced by `programs/analog_hil_three_way_verdict.py`** (PASS on a
CONVERGED variant, FAIL on MODEL_INACCURACY / BACK_TO_PHASE1, SKIP on no data).

| SPICE vs Spec | HW vs Spec | HW vs SPICE | Verdict |
|:---:|:---:|:---:|---|
| PASS | PASS | <20% | CONVERGED — ideal |
| PASS | PASS | >=20% | CONVERGED_WARNING (model-accuracy) |
| PASS | FAIL | — | MODEL_INACCURACY — add margin, re-sim + re-measure |
| FAIL | — | — | BACK_TO_PHASE1 — should not reach Phase 2 |

## Convergence criteria

- **MUST**: Hardware measurement within spec limits
- **TARGET**: Hardware vs SPICE discrepancy < 20% per metric — enforced by `programs/analog_hw_spice_correlation_check.py`
- **IDEAL**: All three (hardware, SPICE, spec) agree within 10%

## Output format

### `analog/<block>/hw_tuning_report.json`
Schema (block_name, converged, total_iterations.{spice,hardware}, per-metric
final_comparison.{spec,spice,hw,discrepancy_pct}, convergence_status) is
**structurally validated by `programs/analog_hil_report_schema_check.py`**.

**`convergence_status` accepts EITHER vocabulary**, because this document
defines two and never said which one to write:

| written as | meaning | `converged` must be |
|---|---|---|
| `IDEAL` | all three agree within 10 % (see Convergence criteria) | `true` |
| `CONVERGED` | hardware in spec, HW-vs-SPICE < 20 % | `true` |
| `WARNING` / `CONVERGED_WARNING` | in spec, HW-vs-SPICE ≥ 20 % | either |
| `MODEL_INACCURACY` | hardware out of spec — add margin, re-sim + re-measure | not `true` |
| `BACK_TO_PHASE1` | SPICE itself out of spec — should not have reached Phase 2 | not `true` |

The right-hand four are exactly what the decision table above produces and what
`programs/analog_hil_three_way_verdict.py` computes from the same
`final_comparison` block. The validator used to accept only the first three, so
a report carrying the honest `MODEL_INACCURACY` outcome came back as a SCHEMA
violation — a real bench finding reported as a format complaint. Writing a
non-converged verdict together with `"converged": true` is still a FAIL: that
is a self-contradiction, not a vocabulary choice.
```json
{
  "block_name": "ldo_1v8",
  "converged": true,
  "total_iterations": {"spice": 3, "hardware": 1},
  "final_comparison": {
    "vout_dc": {"spec": 1.80, "spice": 1.8002, "hw": 1.803, "discrepancy_pct": 0.16}
  },
  "convergence_status": "IDEAL",
  "notes": []
}
```

## Do not

- Do not skip Phase 1 (SPICE) — always converge in simulation before going to hardware
- Do not exceed 3 hardware iterations — enforced by `programs/analog_hil_iteration_cap_check.py` (escalate a model-accuracy issue instead of iterating)
- Do not assume breadboard is pre-built — always display wiring guide and wait for user confirmation (interactive human-in-the-loop gate — kept as judgment)
- Do not adjust more than 1 component per hardware iteration — enforced by `programs/analog_hil_single_knob_check.py` (records sizing-per-iteration in `analog/<block>/hw_sizing_history.json`)

## Enforcement status (read this before trusting a green A9)

The three programs above are wired into flow step **A9** as
`advisory_program_exit_zero` — they RUN and their verdicts are printed and
carried into the step's JSON report, but they cannot fail the step yet.

The reason is a producer gap, and it is measured: **nothing in this repository
writes `hw_tuning_report.json` or `hw_sizing_history.json`** — zero files
repo-wide, no program emits them, and this document is the only place that
describes their shape. So all three report **exit 2 = NOT CHECKED** on every
published run, which the flow renders as `n/a (input not present)` rather than
`ok`. A blocking gate over an artefact with no producer would certify nothing.

**When you author these two files** (that is your job in Phase 2 above — they
are agent-authored by design), the gates start judging real content. Once a
runner step emits them, promote all three to `program_exit_zero` in
`flow/phase1_phase2_phase3.yaml`: they already return exit 1 for every defect,
including a malformed report.

## Handoff

- Converged block with `hw_tuning_report.json` → `analog-hardmacro-gen`
- If model accuracy issue detected → document in `analog/<block>/model_calibration_notes.md`
- Final hardware measurements → `analog_hw_spice_correlation_check` gate

## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/analog-hw-tuning-loop/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.

**Your task is not complete until the audit returns PASS.**
