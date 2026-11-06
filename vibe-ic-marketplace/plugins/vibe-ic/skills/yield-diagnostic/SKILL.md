---
name: yield-diagnostic
description: Analyze silicon test or wafer data to diagnose yield issues, identify systematic failures, and propose layout or process fixes. Use when the user says "yield is low", "diagnose failing dies", "wafer map shows", "bin analysis", or shares ATE/wafer-sort data.
---

# Yield Diagnostic

Given silicon test data (wafer maps, bin yields, ATE failure logs, Shmoo plots), identify systematic vs random failures, localize the root cause, and propose a fix — layout, test program, or process.

## When to use

Trigger when the user:
- Has a yield number that came in below target
- Sees a spatial pattern on a wafer map
- Has a specific bin dominating failures
- Needs to triage silicon bring-up problems

## Inputs to gather

1. Wafer map(s) or bin summary
2. Test program / bin definitions
3. Affected design (block, full chip)
4. Process node and fab
5. Historical baseline for comparison

## Diagnostic workflow

1. Plot the actual wafer/bin data and distinguish edge, ring, cluster, stripe and random patterns using the measured spatial distribution. State the evidence and uncertainty for each classification.
2. **Bin attribution** — which test(s) are failing, and what do they exercise?
3. **Localize** — correlate the failing test to a design region, IP, or power domain
4. **Hypothesize** — one of: design marginality (setup/hold), process corner (slow Vt), layout sensitivity (density, antenna), test program issue
5. **Propose experiments** — Shmoo, temperature sweep, different test pattern, die photography
6. Rank proposed yield fixes by the measured failure mechanism, expected benefit, validation experiment, cost and implementation risk. Keep an untested root cause or benefit estimate labelled as a hypothesis.

## Output format

Plot the actual wafer/bin data and distinguish edge, ring, cluster, stripe and random patterns using the measured spatial distribution. State the evidence and uncertainty for each classification.

Rank proposed yield fixes by the measured failure mechanism, expected benefit, validation experiment, cost and implementation risk. Keep an untested root cause or benefit estimate labelled as a hypothesis.

## Technical basis

Grounded in ML-based yield learning and diagnostic agents trained on wafer maps and ATE logs. Core idea: yield diagnosis is pattern recognition on multi-modal data (spatial + parametric + time), which is where LLMs + vision models now match senior silicon-validation engineers on first-pass triage.

## Do not

- Do not conflate random defects with systematic failures — the fix cost differs by 100×
- Do not recommend a respin without exhausting test program and ECO options
- Do not overclaim root-cause confidence; always report the alternative hypothesis too
