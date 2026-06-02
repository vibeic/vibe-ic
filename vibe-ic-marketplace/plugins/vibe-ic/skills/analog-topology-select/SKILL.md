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
2. PDK device characteristics — do NOT retype Vth/supply constants here.
   They are a single deterministic source-of-truth in
   `programs/pdk_registry.json` under the per-PDK `analog_device_params`
   block (`vth_n_v`, `vth_p_v`, `nominal_supply_v`). Look them up by PDK
   name; the A2 gate (`programs/analog_a2_topology_select_check.py`) and
   `analog-sizing-loop` consume the same registry field.
   (canonical reference: GF180 nfet≈0.65V/pfet≈0.70V/3.3V; SKY130 nfet≈0.45V/pfet≈0.47V/1.8V.)
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
   - Supply voltage headroom. Vth and the nominal supply are deterministic
     PDK constants — read `vth_n_v` / `vth_p_v` / `nominal_supply_v` from
     `programs/pdk_registry.json` (`analog_device_params`), do NOT guess.
     The *headroom feasibility* itself stays judgment: you must read each
     candidate's schematic to count how many devices are stacked between
     the rails and pick realistic Vdsat/Vov margins (the spec gives no
     `n_stacked` or `Vdsat` field, so there is no deterministic value to
     program — see "Do not / headroom" below). Then check
     `available = Vdd - Σ(Vth + Vdsat over the stack) ≥ 0` per candidate.
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
- Vth(N), Vth(P), Vdd — quote the exact values you looked up from
  pdk_registry.json analog_device_params for this PDK → requires ...
- No inductors → ring oscillator instead of LC
```

## Do not

- Do not skip the trade-off analysis — topology selection without justification is the #1 cause of wasted iterations
- Do not assume textbook Vth (0.3-0.5V) — read the real per-PDK Vth from
  `programs/pdk_registry.json` (`analog_device_params`); GF180's ≈0.65V
  invalidates many textbook topologies
- Do not recommend topologies that require devices not in the PDK
- **headroom:** Do not invent a fixed `n_stacked` or Vdsat margin to make
  the headroom check a program. The Vth/supply constants are programmatic
  (registry), but how many devices stack between the rails and the per-device
  Vdsat depend on the candidate schematic and bias point — that is genuine
  analog judgment, not a deterministic table lookup.

## Handoff

- `analog/<block>/topology.md` → `/analog-sizing` (Step A2, continued)
- Rejected topologies documented for future reference

## Compliance gate (vibe-ic-d - mandatory when deterministic edition is installed)

If you have the `vibe-ic-d` plugin installed alongside `vibe-ic`,
after producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic-d/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic-d/skills/analog-topology-select/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.

**Your task is not complete until the audit returns PASS.**


## Captured by benchmark-enhancement-capture — 2026-05-28 (RTLLM Shape B + benchmark_clean + CVDP cross-step capture)

### Skill: ΔΣ modulator topology — 2nd-order SC CIFB with 1-bit quantizer + feedback DAC

**Pattern**: When the analog block class is `delta_sigma_adc` or `delta_sigma_modulator`, the canonical SC topology that Analog A2's primitive panel must recognize is: TWO switched-capacitor integrators (NMOS-input two-stage Miller OTA + Cs/Ci + two-phase non-overlapping switches) + 1-bit clocked comparator (preamp + cross-coupled regenerative latch) + 1-bit feedback DAC (±Vref select switches). This is the CIFB (cascade-of-integrators with distributed feedback) topology, the textbook 2nd-order ΔΣ.

**When to apply**: Analog A2 topology selection for blocks whose L5 spec names `delta_sigma`, `delta-sigma`, `incremental ΔΣ`, or `SC modulator`. Also applicable for sub-blocks of a higher-order ΔΣ ADC chain.

**What to do**: Author topology.md listing: opamp (two-stage Miller, NMOS input pair, PMOS load + class-AB output), comparator (StrongARM-style or preamp+latch), SC integrator (Cs/Ci ratio sized for stability + gain), 1-bit DAC (CMOS analog mux on Vref±). For higher orders, extend to cascaded integrators with distributed/feedforward coefficients.

**Worked example** (from u_hawaii_adc): u_hawaii_adc A2: prior A2 panel rejected `delta_sigma` block-type (no transistor/primitive keyword match). The skill-authored topology.md named opamp/comparator/SC integrator/DAC as transistor-level primitives → A2 PASS. Real ngspice on the resulting netlist showed UGBW 1.81-14.93 MHz across 9 corners (> 1 MHz fclk → integrator settles).

**Why this is GENERAL**: Standard textbook ΔΣ topology (any Schreier / Norsworthy reference). Applies across audio ADCs, sensor readout, incremental high-resolution conversion. Doesn't depend on the specific spec target.

_Captured by benchmark-enhancement-capture 2026-05-28._
