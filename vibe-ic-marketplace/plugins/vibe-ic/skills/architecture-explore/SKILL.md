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

1. Define the candidate knobs and the workload they affect. Pipeline depth,
   parallel lanes, banking and bus width are common choices.
2. Build a labelled analytic estimate or run native synthesis/implementation
   for each candidate under the same PDK, clock and constraints. Estimates may
   use throughput = parallelism × frequency, area = sum of unit areas plus
   memory area, dynamic power = activity × C × Vdd² × frequency, and latency =
   pipeline depth × cycle time. State every coefficient and assumption.
3. Compare actual candidate values and identify non-dominated points. Preserve
   missing values rather than assigning them zero or a default score.
4. Plot or tabulate the tradeoffs and validate the strongest estimates with
   native measurements where available.
5. Recommend an architecture from the original target priorities, remaining
   uncertainty, implementation risk and measured tradeoffs.

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
