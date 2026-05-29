---
name: architecture-explore
description: Explore micro-architecture trade-offs (pipeline depth, parallelism, memory hierarchy, bus width) against PPA targets before committing to RTL. Use when the user says "architecture exploration", "design space exploration", "DSE", "pipeline depth", "parallelism", "micro-architecture", "trade-off study".
---

# Architecture Explore

The decisions with the biggest PPA impact happen before a line of RTL is written. This skill runs a lightweight design-space exploration against a handful of candidate micro-architectures and reports the Pareto frontier.

## When to use

- At the start of a new block design
- When the first PPA predictions miss target
- Before committing to an IP from a vendor
- For re-targeting a block to a new process or frequency

## Inputs

1. Functional spec (from `/spec-review`)
2. PPA targets: area, frequency, power, throughput, latency
3. Process node / library
4. Workload characterization (for data-path blocks)
5. Candidate knobs: pipeline depth, parallel lanes, memory banking, cache size, bus width

## Workflow

1. **Define the parameter space** — typically 3–5 knobs with 2–4 levels each
2. **Build analytic model** per candidate:
   - Throughput = f(parallelism, frequency)
   - Area ~ Σ(units × unit_area) + memory × bit_area
   - Power ~ activity × C × Vdd² × f
   - Latency = depth × cycle_time
3. **Prune** obviously-dominated points
4. **Spot-check** top candidates with `/ppa-predict`
5. **Plot** (or tabulate) Pareto frontier
6. **Recommend** 1–2 architectures with rationale

## Output format

- `arch/dse.md`:
  - Knob table
  - Candidate table with estimated PPA
  - Pareto frontier (ASCII chart or small SVG)
  - Recommendation with rationale
  - Handoff to `/spec-to-rtl` for the chosen point

## Technical basis

Classic DSE references: Patterson & Hennessy quantitative approach. Industry reference designs (RISC-V implementations, NVDLA) document similar knob trade-offs. ML-driven DSE is an active research area (Archgym, HW2VEC).

## Handoff

- Chosen architecture → `/spec-to-rtl`
- PPA cross-check → `/ppa-predict`
- Risk list → `/regression-manage`

## Compliance gate (vibe-ic-d - mandatory when deterministic edition is installed)

If you have the `vibe-ic-d` plugin installed alongside `vibe-ic`,
after producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic-d/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic-d/skills/architecture-explore/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding vibe-ic-d skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.
