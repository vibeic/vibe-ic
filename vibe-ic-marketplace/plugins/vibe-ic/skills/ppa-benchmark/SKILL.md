---
name: ppa-benchmark
description: Set up a PPA comparison between two or more arms — tool versions, flow configurations, RTL variants, PDKs — by declaring each arm, the conditions that make them comparable, and the residual unfairness that survives. Scoring is done by an independent program, never by this skill. Use when the user says "compare these flows", "A/B the PnR settings", "did the new tool version help", "benchmark PPA", or "is this comparison fair".
---

# Compare PPA measurements

Define the arms and their intended differences before running them. Use the
same design requirements, workload, PDK, constraints, analysis stage, corners,
activity basis and tool settings except for the declared change under test.
State the design revision and exact configuration paths so the comparison is
reviewable. Do not add an identity or hash admission gate.

Run the owning native tools for each arm and read their actual area, timing,
power, congestion or runtime results. Keep missing measurements visible as
NOT_MEASURED. An early estimate is not a measured result, and unmatched stages,
corners or activity assumptions cannot establish an improvement.

For stochastic flows, state seeds and runs per arm. Record host load and tool
runtime when reporting execution cost. Preserve the full intended arm/case
population, including crashes and unavailable results. Explain remaining
unfairness and uncertainty rather than normalizing it away without evidence.

Write a comparison table with arm, metric, value, unit, scope, native report
path and original limit. Explain the measured tradeoffs and any recommendation
in terms of the user's priorities. A native failure remains failed; neither a
ranking score nor an independent wrapper changes that result.

Use `ppa-measure` to read the actual numbers, `ppa-diagnose` to investigate
their causes, and `ppa-optimize` to propose the next bounded change.
