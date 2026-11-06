---
name: ppa-predict
description: EARLY, PRE-SYNTHESIS ESTIMATE of power, performance and area — a ranged guess produced before any tool has run, never a measurement and never admissible as final PPA. Use when the user says "estimate PPA", "how big will this be", "what's the area of this module", "will this meet timing", or wants a sanity check before committing to a long synthesis run. For numbers parsed out of real tool artefacts, use `ppa-measure` instead — the two must never share a table.
---

# PPA Predict

## Read this before the first number: this is an estimate

Every number this skill produces carries status `ESTIMATED`, and
`docs/PPA_INTERFACES.md` §2 is unambiguous about what that status may do:

| status | may enter a numeric comparison |
|---|---|
| `MEASURED` | yes |
| `ESTIMATED` | **never in final PPA** |

So a number from this skill may be used to choose between two RTL variants, to
size a floorplan before it exists, or to decide whether a synthesis run is worth
starting. It may not be used to answer whether a design met its target, it may
not be carried into a PPA report, and it may not be compared against a number
that came from an artefact. A prediction and a measurement look identical once
they are two cells of the same table, which is why they are never allowed to
become two cells of the same table.

**The skill that measures is `ppa-measure`.** It reads the actual native tool artifacts and reports their measured values
with scope and source paths. This skill has read no artefact —
that is the whole point of it, and it is also the whole limit of it.

This skill also produces no gate verdict. Whether an estimate is good enough to
proceed is a caller's decision or a program's; it is not a line in this report.

> **Doctrine (v0.1.50):** 把修法寫進工具，而非寫進 prompt。
> Use native tool measurements when available and label estimates explicitly.

Provide fast, pre-synthesis estimates of Power, Performance (Fmax /
critical-path delay), and Area for an RTL module. Acts as a Circuit
Foundation Model surrogate for the synthesis tool — seconds instead of
hours.

## Prepare an explicit estimate

Read the actual design input, RTL structure and selected PDK characterization.
Use a native synthesis cell count if one is already available, and state that
scope separately from a purely pre-synthesis estimate. Name the area, delay,
activity, capacitance and voltage assumptions behind the model.

Report ranges and units. Keep every predicted value labelled ESTIMATED, state
what the model omits, and use native tool measurements before claiming a PPA
requirement is met. No retired estimator program supplies a JSON result or
exit code for this workflow.

## When to use

Trigger when the user:
- Wants an area/timing ballpark before running DC/Genus/Yosys
- Is comparing two RTL variants and needs a quick "which is better"
- Asks "will this fit in X gates" or "can I close timing at Y MHz"
- Needs PPA feedback inside a generate-evaluate loop

## Inputs to gather

1. Target technology (e.g. an open PDK such as `gf180mcuD`, `sky130A` or
   `ihp-sg13g2`; or a generic standard-cell assumption)
2. Target clock frequency (MHz)
3. Target cell library (if known) or standard-cell assumption
4. Optimization goal: area, speed, power, or balanced

## Prediction workflow

1. **Structural analysis** — count flops, adders, multipliers, memory bits, mux layers
2. **Critical-path estimate** — identify the deepest combinational chain and estimate logic-level delay
3. **Gate-count estimate** — map each construct to approximate NAND2 equivalents
4. **Power estimate** — dynamic (activity × capacitance × V² × f) + leakage (gate count × node leakage)
5. **Confidence band** — report each number as a range, not a point estimate

## Output format

```
# PPA Prediction — <module>

Status: ESTIMATED (never enters final PPA)
Not a measurement: run /ppa-measure for numbers parsed from tool artefacts

Technology: <node>
Target frequency: <MHz>

Every row below is an ESTIMATED record. None of them has a source artefact,
because at this point in the flow no artefact exists.

| Metric | Status | Estimate | Range | Confidence |
|--------|--------|----------|-------|------------|
| Area (µm²) | ESTIMATED | ... | ... – ... | High/Med/Low |
| Gate count (NAND2 eq) | ESTIMATED | ... | ... – ... | ... |
| Fmax (MHz) | ESTIMATED | ... | ... – ... | ... |
| Dynamic power (mW @ target f) | ESTIMATED | ... | ... – ... | ... |
| Leakage (µW) | ESTIMATED | ... | ... – ... | ... |

## Summary
<one paragraph: what was estimated, from what, and how far it can be trusted>

## Critical path (estimated)
<signal A> → <logic> → <signal B>  (~<n> logic levels)

## Bottleneck
<what is limiting Fmax or dominating area>

## Optimization suggestions
- <suggestion 1, e.g., pipeline the multiplier>
- <suggestion 2, e.g., share the adder>

Next: run /ppa-measure
```

## Technical basis

Grounded in Circuit Foundation Models for pre-synthesis prediction — encoder-based CFMs like MasterRTL, CircuitEncoder, and graph-neural-network surrogates trained on synthesized netlists. Typical prediction error: 10–15% vs real synthesis for area, 15–20% for timing.

## Do not

- Do not claim single-number precision — always give a range
- Do not replace real synthesis for sign-off; this is a pre-check only
- Do not extrapolate far outside the training distribution (e.g., very exotic architectures)
- Do not label any number here `MEASURED`, and do not attach a source artefact
  hash to one. Nothing was parsed; a provenance field on an estimate is a claim
  that a reader can only discover is false by trying to re-derive it.
- Do not attribute an estimate to a post-route or extracted stage. This skill
  runs before those stages exist, so a stage label from them is not an optimistic
  approximation — it is a different number's label on this number.
- Do not put an estimate and a measurement in the same table, the same chart, or
  the same sentence with a comparison in it. If both are needed, they are two
  documents: this one, and a `ppa-measure` report.
- Do not answer whether the design met its target from these numbers. That
  question is answered from `MEASURED` records by a deterministic program.

## Preserve the ECO reserve

Keep unused spare cells, ECO gates and reserved pads through synthesis and
physical repair. Compare the native netlist or database before and after the
change. No unused reserve instance may disappear, and its keep attributes must
remain intact. A consumed spare must be named in the intended ECO. Restore any
unintentionally removed spare before rerunning the native tools. See
`design-for-eco` for the design intent.
