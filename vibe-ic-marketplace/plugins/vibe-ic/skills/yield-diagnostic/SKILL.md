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

1. **Random vs systematic** — look at the spatial distribution and pick the
   `spatial_class` (edge / cluster / uniform / random). The signature→root-cause
   *lookup* (edge ring → process, clusters → defects, uniform → design
   marginality) is deterministic and **enforced by
   `programs/wafer_map_pattern_classify.py`** — pass it `--spatial-class <c>`
   (or a project dir / JSON carrying `spatial_class`) and it emits the
   root-cause bucket. Give it a `wafer_map.csv` and it also reports objective
   edge/interior fail fractions to help you choose the class. (Picking the
   class from a raw map is the judgment step — the spec gives no cut-points, so
   the program never fabricates one.)
2. **Bin attribution** — which test(s) are failing, and what do they exercise?
3. **Localize** — correlate the failing test to a design region, IP, or power domain
4. **Hypothesize** — one of: design marginality (setup/hold), process corner (slow Vt), layout sensitivity (density, antenna), test program issue
5. **Propose experiments** — Shmoo, temperature sweep, different test pattern, die photography
6. **Propose fixes** — the cost order (test program tweak < metal ECO <
   base-layer ECO < respin) is a fixed ordinal table, so the ranking is
   deterministic and **enforced by `programs/yield_fix_cost_rank.py`**. Feed it
   a JSON list of candidate fixes; it classifies each into a remediation class
   and emits the cost-sorted table. A fix it can't classify is reported, never
   silently bucketed.

## Output format

```
# Yield Diagnostic — <lot/block>

Observed yield: X% (target Y%)

## Pattern classification
<!-- Spatial -> root-cause mapping is emitted by
     programs/wafer_map_pattern_classify.py — do not hand-map the signature. -->
- Spatial: <edge / cluster / uniform / random>
- Bin distribution: <dominant bins>
- Conclusion: <likely systematic | random | mixed>

## Hypothesized root cause
<top 1–2 hypotheses with evidence>

## Diagnostic experiments
1. <experiment> → <expected signature if hypothesis is right>
2. ...

## Proposed fixes (by cost)
<!-- This table's cost ordering is emitted by programs/yield_fix_cost_rank.py
     (the markdown field of its JSON report) — do not hand-rank. -->
| # | Fix | Cost | Expected yield uplift | Risk |
|---|-----|------|----------------------|------|
| 1 | Relax test margin on BIN_X | Low | +2% | Test escape |
| 2 | Metal ECO on clock tree     | Med | +5% | Re-run P&R |
| ...

## Next data to collect
- <data type that would discriminate hypotheses>
```

## Technical basis

Grounded in ML-based yield learning and diagnostic agents trained on wafer maps and ATE logs. Core idea: yield diagnosis is pattern recognition on multi-modal data (spatial + parametric + time), which is where LLMs + vision models now match senior silicon-validation engineers on first-pass triage.

## Do not

- Do not conflate random defects with systematic failures — the fix cost differs by 100×
- Do not recommend a respin without exhausting test program and ECO options
- Do not overclaim root-cause confidence; always report the alternative hypothesis too

## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/yield-diagnostic/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.
