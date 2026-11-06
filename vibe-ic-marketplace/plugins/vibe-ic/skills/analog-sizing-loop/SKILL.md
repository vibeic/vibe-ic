---
name: analog-sizing-loop
description: Closed-loop analog optimization — iterates sizing → netlist → SPICE corner sweep → spec check → re-size until all PVT corners pass. Use when the user says "optimize the analog block", "close the loop", "auto-size", or at Step A4 of the analog track.
---

# Analog Sizing Loop

Automates the iterative analog design loop that previously required 5-14 manual iterations (per PRACTICAL_NOTES.md). Orchestrates `analog-sizing` → `analog-netlist-gen` → `eda_spice_corner` in a closed loop with spec-driven convergence.

## When to use

- Step A4 of the analog track (after topology + initial sizing)
- When a single SPICE run shows failing corners and the user wants automated optimization
- After `/analog-sizing` provides an initial design point

## Inputs

1. `analog/<block>/spec.json` — performance targets with min/max limits
2. `analog/<block>/topology.md` — selected topology
3. `analog/<block>/sizing.md` — initial sizing from `analog-sizing`
4. PDK (gf180 or sky130)

## Loop workflow

1. Run SPICE for the required PVT corners using the current sizing and models.
2. Read each failing native measurement against its original specification.
3. Identify the sensitive device and likely cause using operating-point,
   gain, bandwidth, phase-margin, noise, swing or power data.
4. Propose a bounded sizing change. Change at most two parameters per iteration
   so the effect can be attributed to that change.
5. Emit the revised netlist and rerun the same native measurements. Keep the
   prior sizing and results so a regression can be reverted.
6. Stop when all required corners meet their original limits. After five
   unsuccessful iterations, report the best result and reconsider topology.

Typical sizing moves are hypotheses to verify, not a substitute for SPICE.

| Failure mode | Candidate change |
|--------------|------------------|
| Low gain | Increase input-pair W by 50% |
| Low bandwidth | Reduce W to 0.7× and increase bias to 1.3× |
| Low phase margin | Increase compensation capacitance by 50% |
| High noise | Increase input-pair area to 2× |
| High power | Reduce bias current to 0.7× |
| Low output swing | Increase W to 1.4× at the same drain current |

Choose a move only when the measured circuit behavior supports it. An unknown
failure mode requires circuit analysis, not an invented policy verdict.

## Output format

Choose the next bounded design change from the failing native measurements and engineering sensitivity. Keep the stated iteration budget, record the changed parameters, and rerun the owning native tools with unchanged limits.

### `analog/<block>/sizing_final.json`
```json
{
  "block_name": "ldo_1v8",
  "iterations": 3,
  "converged": true,
  "final_sizing": {
    "M1": {"W": "40u", "L": "2u", "role": "input_pair"},
    "MP_pass": {"W": "100u", "L": "0.5u", "role": "pass_transistor"}
  },
  "worst_corner": "ss_-40C_3.0V",
  "yield_pct": 100
}
```

### `analog/<block>/corner_results.json`
Written by `eda_spice_corner` — PVT matrix with per-spec pass/fail.

### `analog/<block>/sizing_history.json`
```json
{
  "iterations": [
    {"iter": 0, "changes": "initial", "tt_pass": false, "reason": "gain=45dB < 55dB spec"},
    {"iter": 1, "changes": "M1 W: 20u→40u", "tt_pass": true, "all_corners_pass": false, "worst": "ss_-40C"},
    {"iter": 2, "changes": "Ibias: 20uA→30uA", "tt_pass": true, "all_corners_pass": true}
  ]
}
```

## Stopping conditions

- All required native measurements meet their original specification.
- Five sizing iterations have not converged. Report the best measured result
  and the remaining failures before considering a topology change.
- The topology cannot provide the required gain, swing, bandwidth or noise.
  Explain the circuit limitation and return to topology selection.

## Do not

- Move a specification or PDK limit to make sizing pass.
- Change more than two parameters in one iteration.
- Spend further simulation on a parameter with no sensitivity to the failing
  specification without explaining the expected mechanism.
- Treat an absent native result as convergence.

## Handoff

- `corner_results.json` → native corner-result review
- `sizing_final.json` → `/analog-layout` (Step A5)
- If 5 iterations fail → back to `/analog-topology-select` (re-evaluate topology)

## Iterate using native results

Run the owning tool on each proposed change and read its native result against
the original limit. Keep the previous design and measured result so you can
revert a regression. Stop when the declared requirements are met, the approved
run budget is exhausted, or another trial cannot resolve the remaining cause.
Report the best measured result and every unresolved requirement. Do not add an
admission record or change a limit to obtain a pass.
