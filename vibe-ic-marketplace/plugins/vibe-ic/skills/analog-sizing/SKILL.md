---
name: analog-sizing
description: Size transistors in an analog circuit topology to meet performance specs (gain, bandwidth, noise, power). Use when the user says "size this amplifier", "analog sizing", "op-amp design", "bias point", "find W/L", or shares a schematic and a spec table.
---

# Analog Sizing

Given an analog topology (schematic or netlist) and a performance spec (gain, UGB, phase margin, noise, power, area), propose transistor W/L sizes and bias currents that meet the spec. Acts as the LLM copilot layer over classical analog sizing tools and SPICE.

## When to use

Trigger when the user:
- Has a schematic (op-amp, LDO, bandgap, comparator, PLL CP) and needs sizes
- Wants to explore a design space before running SPICE sweeps
- Asks for gm/Id-based sizing intuition
- Needs a starting point for an optimizer

## Inputs to gather

1. Topology (schematic, netlist, or textual description)
2. Process and models (e.g., TSMC 180nm, 65nm, FinFET node)
3. Spec table: gain (dB), UGB (Hz), PM (°), noise, power budget, supply, load
4. Starting point or "greenfield"
5. Constraint: minimize power, minimize area, or balanced

## Sizing workflow

1. **Identify the signal path and loading** — what sets gain, what sets BW, what dominates noise
2. **Pick operating regions** — strong inversion for speed, weak/moderate for efficiency
3. **Use gm/Id methodology** — pick a gm/Id target per device, derive Id from gm, then W/L
4. **Size mirrors and biases** — match ratios, ensure headroom
5. **Compensation** — for op-amps, pick Cc and nulling resistor for target PM
6. **Sanity-check** — walk through the spec line by line against the proposed sizes
7. **Recommend SPICE verification** — always

## Output format

```
# Analog Sizing — <topology>

Process: <node>
Supply: <V>

## Operating point plan
| Device | Role       | gm/Id | Id (µA) | W (µm) | L (µm) | Region |
|--------|------------|-------|---------|--------|--------|--------|
| M1     | input pair | 15    | 20      | 40     | 0.5    | moderate |
| ...    |

## Predicted performance (gm/Id estimates)
| Spec | Target | Estimate | Margin |
|------|--------|----------|--------|
| Gain | 60 dB | ~62 dB | + |
| UGB  | 10 MHz | ~11 MHz | + |
| PM   | 60°    | ~62°    | + |
| Power | 200 µW | ~180 µW | + |

## Compensation
Cc = ..., Rz = ...

## Verification
Run SPICE: <suggested testbench(es) — AC, transient, noise, corners>
```

## Technical basis

Grounded in ADO-LLM, Maieutic Semiconductor's analog copilot direction, and gm/Id methodology (Silveira, Flandre, Jespers). Core idea: analog sizing is a constrained optimization where good initial conditions matter more than the optimizer — and LLMs trained on analog literature are very good at initial conditions.

## Do not

- Do not claim final sign-off from hand analysis; always recommend SPICE
- Do not ignore corners — flag typical/SS/FF/hot/cold as an explicit next step
- Do not propose sizes that violate matching, mirror ratios, or common-mode constraints

## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/analog-sizing/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.
