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

1. **Define the parameter space** — typically 3–5 knobs with 2–4 levels each.
   *This is an AI-judgment step:* pick the knobs and levels that matter for
   THIS block and workload (you know the design; the program does not).
2. **Build analytic model + prune** — do NOT hand-compute the PPA math or
   eyeball dominance. Encode each candidate as a knob row with the per-unit
   coefficients and run the deterministic program. It applies the four
   formulas (Throughput = parallelism × frequency, Area = Σ(units × unit_area)
   + memory × bit_area, Power = activity × C × Vdd² × f, Latency = depth ×
   cycle_time) and returns the Pareto frontier (area-minimise, power-minimise,
   latency-minimise, throughput-maximise) via a dominance filter:

   ```bash
   python3 plugins/vibe-ic/programs/arch_dse_pareto.py knobs.json --json arch/dse.json
   ```

   `knobs.json` is a list of candidates, each giving its knob values plus the
   coefficients the formulas need (`unit_area`, `activity`, `cap`, `vdd`, …).
   The program is chip-AGNOSTIC and hard-codes no process numbers — you supply
   the coefficients. It degrades gracefully (reports `status: MISSING` /
   per-candidate `notes`) on partial input rather than crashing or
   over-flagging. The `pareto_frontier` list in the output is the set of
   non-dominated points to carry forward.
3. **Spot-check** the frontier candidates with `/ppa-predict`
4. **Plot** (or tabulate) the Pareto frontier from `arch/dse.json`
5. **Recommend** 1–2 architectures with rationale. *This is an AI-judgment
   step:* the program tells you WHICH points are Pareto-optimal; you decide
   WHICH of those best fits the PPA target priorities, risk, and roadmap.

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

## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/architecture-explore/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.
