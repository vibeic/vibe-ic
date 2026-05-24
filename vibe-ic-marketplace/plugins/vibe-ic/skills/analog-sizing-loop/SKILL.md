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

```
Iteration 0:
  analog-sizing → initial W/L + bias
  analog-netlist-gen → SPICE deck
  eda_spice_corner (TT only) → quick sanity check
    If TT fails → re-size immediately (don't waste time on corners)

Iteration 1-N (max 5):
  eda_spice_corner (all corners: TT/SS/FF × -40/25/125°C)
  Parse yield table vs spec.json limits
  If all PASS → done
  If FAIL:
    1. Identify worst-case corner (e.g., SS @ -40°C)
    2. Identify dominant failure (e.g., gain too low)
    3. Identify sensitive device (e.g., M1 gm too small)
    4. Adjust: increase W (for more gm) or decrease L (for more speed)
    5. Re-generate netlist with new sizes
    6. Re-simulate
```

## Convergence strategy

| Failure mode | Adjustment | Typical fix |
|-------------|------------|-------------|
| Gain too low | Increase gm/Id (↑W or ↑L) | +50% W on input pair |
| Bandwidth too low | Decrease parasitic C (↓W) or ↑bias current | Trade gain for BW |
| Phase margin too low | Increase Cc or add nulling Rz | +50% Cc |
| Noise too high | Increase W×L product on input devices | +2× area on input pair |
| Power too high | Reduce bias current | ↓Ibias by 30% |
| Output swing too small | Reduce Vdsat (↑W at same Id) | Cascode → folded-cascode |

## Output format

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

1. **All specs pass across all corners** → SUCCESS
2. **5 iterations without convergence** → STOP, report best-so-far + remaining failures
3. **Fundamental topology limitation** (e.g., single-stage gain capped at 40dB but spec requires 60dB) → STOP, recommend topology change

## Do not

- Do not run all corners on iteration 0 — TT-only is sufficient for initial sanity
- Do not make more than 2 simultaneous changes per iteration — hard to debug
- Do not exceed 5 iterations — if not converging, the topology is likely wrong
- Do not adjust a device that has no sensitivity to the failing spec

## Handoff

- `corner_results.json` → `analog_corner_sweep_check` gate (verification)
- `sizing_final.json` → `/analog-layout` (Step A5)
- If 5 iterations fail → back to `/analog-topology-select` (re-evaluate topology)

## Compliance gate (vibe-ic-d - mandatory when deterministic edition is installed)

If you have the `vibe-ic-d` plugin installed alongside `vibe-ic-core`,
after producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic-d/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic-d/skills/analog-sizing-loop/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.

**Your task is not complete until the audit returns PASS.**
