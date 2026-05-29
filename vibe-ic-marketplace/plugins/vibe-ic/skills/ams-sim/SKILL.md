---
name: ams-sim
description: Plan and run analog / mixed-signal simulations — DC op, AC, transient, Monte Carlo, corner sweeps, PSRR/CMRR, noise — using ngspice, Xyce, Spectre, or HSPICE, and triage the results. Use when the user says "SPICE", "ngspice", "Monte Carlo", "corner simulation", "analog sim", "AC analysis", "transient", "PSRR", "CMRR", "noise analysis".
---

# AMS Sim

Analog blocks must be verified across process corners, temperature, voltage, and mismatch. This skill plans the testbench matrix, generates the simulator decks, and triages results.

## When to use

- After `/analog-sizing` produces a schematic
- After `/analog-layout` + extraction (post-layout)
- When mismatching is the suspected failure mode (Monte Carlo)
- Mixed-signal co-simulation with a digital controller (ngspice + Verilog-A, or Spectre APS)

## Inputs

1. Schematic / netlist (`.sp`, `.cir`, `.scs`)
2. Device models from PDK (`.lib` / `.scs`)
3. Specs to verify (gain, BW, PSRR, CMRR, noise, slew, settling, offset)
4. Corner definition (FF/SS/TT/FS/SF × temp × supply)
5. Monte Carlo N (typical 500–5000 runs)

## Analysis matrix

| Analysis | Purpose |
|---|---|
| `.op` | DC operating point, bias validation |
| `.dc` | Sweeps (supply, input, parameter) |
| `.ac` | Gain, bandwidth, phase margin |
| `.tran` | Settling, slew, large-signal |
| `.noise` | Input-referred noise, SNR |
| `.pss` / `.pac` / `.pnoise` | Periodic steady-state (for RF / SC circuits) |
| `.mc` | Monte Carlo mismatch + process |

## Workflow

1. Pick the analysis subset needed for the spec
2. Build deck with corner + MC sweeps
3. Run (ngspice / Xyce / Spectre / HSPICE)
4. Extract measurements via `.meas` statements
5. Tabulate corners × MC yield vs spec
6. Flag failing corners; propose sizing or layout changes
7. Hand off to re-sizing loop

## Output format

- `sim/<block>.sp` (or equivalent) — simulator deck
- `sim/<block>_results.md`:
  - Spec table with pass/fail per corner
  - MC yield percentage per spec
  - Sensitivity list (which device / parameter dominates)
  - Suggested fixes

## Tool prerequisites

Open source: ngspice (https://ngspice.sourceforge.io/), Xyce. Commercial: Cadence Spectre, Synopsys HSPICE, Silvaco SmartSpice.

## Technical basis

Pelgrom mismatch model, corner methodology from PDK, Monte Carlo with correlated process parameters. Mixed-signal co-sim per Verilog-AMS / Verilog-A standards.

## Handoff

- Failing corners → `/analog-sizing` (re-size)
- Layout-driven failures → `/analog-layout`
- Model issues → escalate to PDK team

## Compliance gate (vibe-ic-d - mandatory when deterministic edition is installed)

If you have the `vibe-ic-d` plugin installed alongside `vibe-ic`,
after producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic-d/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic-d/skills/ams-sim/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding vibe-ic-d skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.
