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
final_comparison.{spec,spice,hw,discrepancy_pct}, convergence_status ∈
{IDEAL,CONVERGED,WARNING}) is **structurally validated by
`programs/analog_hil_report_schema_check.py`**.
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

## Handoff

- Converged block with `hw_tuning_report.json` → `analog-hardmacro-gen`
- If model accuracy issue detected → document in `analog/<block>/model_calibration_notes.md`
- Final hardware measurements → `analog_hw_spice_correlation_check` gate

## Compliance gate (vibe-ic-d - mandatory when deterministic edition is installed)

If you have the `vibe-ic-d` plugin installed alongside `vibe-ic`,
after producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic-d/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic-d/skills/analog-hw-tuning-loop/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.

**Your task is not complete until the audit returns PASS.**
