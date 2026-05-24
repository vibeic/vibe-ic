---
name: analog-topology-select
description: Select circuit topology for each analog block based on specs and PDK constraints. Use when the user says "what topology for the LDO", "analog topology", "circuit architecture", or at Step A2 of the analog track.
---

# Analog Topology Select

Given a block's `spec.json` (from `analog-spec-extract`) and PDK device characteristics, recommends a circuit topology. This is the highest-leverage decision in analog design — wrong topology wastes 10+ sizing iterations; right topology converges in 1-2.

## When to use

- Step A2 of the analog track
- After `analog-spec-extract` has produced spec.json per block
- When the user asks "what circuit should I use for this LDO?"

## Inputs

1. `analog/<block>/spec.json` — from `analog-spec-extract`
2. PDK device characteristics:
   - GF180: Vth≈0.65V (nfet_03v3), Vth≈0.70V (pfet_03v3), 3.3V supply
   - SKY130: Vth≈0.45V (nfet_01v8), Vth≈0.47V (pfet_01v8), 1.8V supply
3. Constraints: power budget, area budget, accuracy requirements

## Proven topologies (GF180, verified via SPICE)

These templates are from `analog-sizing/PRACTICAL_NOTES.md` — all verified working on GF180 with ngspice:

### LDO
**Recommended**: NMOS-input diff pair + PMOS active mirror + PMOS series pass transistor
- Why NMOS input (not PMOS): at Vth=0.65V, PMOS input pair common-mode range is too narrow for 1.8V output feedback
- Feedback: resistor divider (R1, R2) from Vout to inverting input
- Compensation: Miller Cc from output to diff-pair drain
- **Anti-pattern**: PMOS-input diff pair — fails at GF180 Vth levels

### Oscillator
**Recommended**: Current-starved 5-stage ring oscillator
- Frequency set by bias current (Ibias) → tunable via current mirror ratio
- No inductors needed (GF180 has no spiral inductor models)
- **Anti-pattern**: LC oscillator — no inductor in GF180

### POR (Power-On Reset)
**Recommended**: PMOS diode offset + resistor divider + 2-inverter chain + weak PMOS feedback + RC delay
- PMOS diode provides fixed |Vtp| offset (~0.7V) → trip point independent of VDD
- Hysteresis via weak PMOS feedback from output to inverter chain
- RC delay for clean release timing
- **Anti-pattern**: Schmitt trigger — inverter threshold tracks VDD proportionally, making trip point unreliable

### Bandgap Reference
**Recommended**: Brokaw bandgap (CTAT + PTAT summing)
- Two BJTs (or parasitic PNP in GF180) with different current densities
- CTAT from Vbe, PTAT from ΔVbe × R ratio
- Output: ~1.2V reference (process-independent)

### Comparator
**Recommended**: Folded-cascode + latch output stage
- Folded-cascode for high gain + wide input range
- Latch for fast decision with digital-compatible output

## Workflow

1. Load `spec.json` and identify block type
2. Map to 2-3 candidate topologies from the library above
3. Evaluate each against:
   - Supply voltage headroom (Vdd - 2×Vth for stacked devices)
   - Power budget vs. required performance
   - Area constraints
   - PDK device availability (e.g., no inductors in GF180)
4. Select best topology with justification
5. Output `topology.md` with:
   - Schematic description (ASCII art or text)
   - Key device roles
   - Trade-off analysis
   - Why alternatives were rejected
6. Flag if no known topology fits → escalation

## Output format

`analog/<block>/topology.md` — one file per block:

```
# Topology — <block_name>

## Selected: <topology_name>

## Schematic
<ASCII schematic or description>

## Device roles
| Device | Role | Key constraint |
|--------|------|----------------|
| M1,M2 | Input diff pair | Vgs > Vth + Vdsat_tail |
| ... | | |

## Trade-off analysis
| Candidate | Pros | Cons | Verdict |
|-----------|------|------|---------|
| NMOS-input OTA | Wide CM range at 3.3V | Higher noise | Selected |
| PMOS-input OTA | Lower noise | CM range too narrow | Rejected |

## PDK constraints applied
- Vth(N) = 0.65V, Vth(P) = 0.70V → requires ...
- No inductors → ring oscillator instead of LC
```

## Do not

- Do not skip the trade-off analysis — topology selection without justification is the #1 cause of wasted iterations
- Do not assume textbook Vth (0.3-0.5V) — GF180 is 0.65V, which invalidates many textbook topologies
- Do not recommend topologies that require devices not in the PDK

## Handoff

- `analog/<block>/topology.md` → `/analog-sizing` (Step A2, continued)
- Rejected topologies documented for future reference

## Compliance gate (vibe-ic-d - mandatory when deterministic edition is installed)

If you have the `vibe-ic-d` plugin installed alongside `vibe-ic-core`,
after producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic-d/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic-d/skills/analog-topology-select/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.

**Your task is not complete until the audit returns PASS.**
