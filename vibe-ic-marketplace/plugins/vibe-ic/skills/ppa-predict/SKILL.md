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

**The skill that measures is `ppa-measure`.** It parses tool artefacts, hashes
what it parsed, and emits `MEASURED` records. This skill has read no artefact —
that is the whole point of it, and it is also the whole limit of it.

Three things make this hard to misread rather than merely stated once: the
frontmatter above says it, every output row carries the `ESTIMATED` status
literal, and `compliance.yaml` refuses an output of this skill that claims a
measured status or a post-route stage. The third one is the one that still
works after nobody remembers the first two.

This skill also produces no gate verdict. Whether an estimate is good enough to
proceed is a caller's decision or a program's; it is not a line in this report.


> **Doctrine (v0.1.50):** 把修法寫進工具，而非寫進 prompt。
> Mandatory program preflight first; AI is the backstop, not the lead.

Provide fast, pre-synthesis estimates of Power, Performance (Fmax /
critical-path delay), and Area for an RTL module. Acts as a Circuit
Foundation Model surrogate for the synthesis tool — seconds instead of
hours.

## Mandatory Deterministic Preflight

Before any narrative estimate:

```bash
# 1. Extract any PPA hints already declared in the project README / spec:
python3 plugins/vibe-ic/programs/readme_ppa_extractor.py \
    --rtl-dir <rtl> --readme <README.md> --json /tmp/ppa_hints.json

# 2. Turn the RTL cell count + the PDK + those hints into the numbers
#    themselves. This is the program that owns the arithmetic:
python3 plugins/vibe-ic/programs/ppa_predict_aggregate.py \
    --cell-count <yosys stat cells> --pdk <gf180mcuD|sky130A|...> \
    [--fmax-hint-mhz <from step 1>] \
    [--declared-area-um2 <from step 1>] [--declared-power-uw <from step 1>] \
    --out-md /tmp/ppa_estimate.md --out-json /tmp/ppa_estimate.json
```

Use the JSON output as the floor of any estimate you state. **Do not
overclaim a tighter number than the program returned** — the program
read the actual spec/README declared values; LLM-generated estimates
without that anchor have a known confabulation rate.

**Step 2 is not optional and it is not a formatter.** Every area, power and
Fmax number this skill reports comes from `ppa_predict_aggregate`, and the
report you write quotes it rather than re-deriving it. The doctrine line at the
top of this file — *把修法寫進工具，而非寫進 prompt* — is exactly this: the
cell-count → area/power tables, the per-PDK constants, the `ESTIMATED` /
`RTL_PROXY` labels, the `eligible_for_physical_ppa: false` flag and the
per-figure "what this number assumed" block are all IN the program. A narrative
estimate written beside it is a second table nobody can diff against the first.

Its exit codes are the same three this lane uses everywhere:

| rc | meaning | what you do |
|---|---|---|
| 0 | an estimate was produced | quote it; add trade-off narration only |
| 2 | `[CANNOT CHECK]` — e.g. `--cell-count 0`, which is a count that was never taken, not a design of zero cells | say the count is missing and stop; do NOT supply a number of your own |
| 3 | bad invocation | fix the arguments |

An rc=2 is the one to be careful with: this skill's whole failure mode is
producing a fluent number when it has no anchor, and rc=2 is the program saying
there is no anchor.

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

## ⛔ ECO spare-cell preservation (mandatory)

> ⛔ **ECO spare-cell preservation:** cells/gates/pads carrying the `dont_touch` /
> `keep` attribute (or otherwise tagged spare/ECO) are RESERVED for a future
> metal-only ECO. When predicting PPA or suggesting area/power optimizations,
> NEVER RECOMMEND deleting, resizing, re-purposing, or "recovering" spare cells
> or reserved pads to shrink area — they are a deliberate ~1-5% investment, not
> waste to reclaim, and any such recommendation would later trip
> `spare_cell_preservation_check.py`. Report spare-pool area separately (as
> intentional ECO reserve) rather than flagging it as a removable area
> overhead. See the `design-for-eco` skill.

## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/ppa-predict/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.
