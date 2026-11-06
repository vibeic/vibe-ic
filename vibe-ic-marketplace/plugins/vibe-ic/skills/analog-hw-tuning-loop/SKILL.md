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

Compare hardware, SPICE and the original specification under matching conditions. State which comparisons were measured and which remain open.

## Three-way comparison

| SPICE vs Spec | HW vs Spec | HW vs SPICE | Verdict |
|:---:|:---:|:---:|---|
| PASS | PASS | <20% | CONVERGED — ideal |
| PASS | PASS | >=20% | CONVERGED_WARNING (model-accuracy) |
| PASS | FAIL | — | MODEL_INACCURACY — add margin, re-sim + re-measure |
| FAIL | — | — | BACK_TO_PHASE1 — should not reach Phase 2 |

## Convergence criteria

- **MUST**: Hardware measurement within spec limits
- Calculate hardware-versus-SPICE differences from the actual measurements and compare them with the original declared correlation limits. Keep missing hardware data unmeasured.
- **IDEAL**: All three (hardware, SPICE, spec) agree within 10%

## Output format

Report the hardware and SPICE measurements, conditions, iteration history and unresolved differences directly. A report schema does not establish convergence.

**`convergence_status` accepts EITHER vocabulary**, because this document
defines two and never said which one to write:

| written as | meaning | `converged` must be |
|---|---|---|
| `IDEAL` | all three agree within 10 % (see Convergence criteria) | `true` |
| `CONVERGED` | hardware in spec, HW-vs-SPICE < 20 % | `true` |
| `WARNING` / `CONVERGED_WARNING` | in spec, HW-vs-SPICE ≥ 20 % | either |
| `MODEL_INACCURACY` | hardware out of spec — add margin, re-sim + re-measure | not `true` |
| `BACK_TO_PHASE1` | SPICE itself out of spec — should not have reached Phase 2 | not `true` |

## Do not

- Do not skip Phase 1 (SPICE) — always converge in simulation before going to hardware
- Keep the stated maximum of 3 hardware iterations. If those iterations do not converge, report the remaining model discrepancy and investigate it before another hardware trial.
- Do not assume breadboard is pre-built — always display wiring guide and wait for user confirmation (interactive human-in-the-loop gate — kept as judgment)
- Change at most one component per hardware iteration so the measured effect can be attributed to that change. Record the changed component and native before/after measurements.

## Review the native hardware result

Record the actual scope/ADC data, SPICE conditions and source specification.
Keep hardware that was unavailable or not executed explicitly NOT_MEASURED.
Do not introduce a report-schema or iteration-history gate to qualify a native
measurement.

## Handoff

- Converged block with `hw_tuning_report.json` → `analog-hardmacro-gen`
- If model accuracy issue detected → document in `analog/<block>/model_calibration_notes.md`
- Final hardware measurements → native measurement and correlation review
