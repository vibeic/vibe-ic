---
name: ppa-predict
description: Predict power, performance, and area of an RTL module before running synthesis. Use when the user says "estimate PPA", "how big will this be", "what's the area of this module", "will this meet timing", or wants an early PPA sanity check before committing to a long synthesis run.
---

# PPA Predict

> **Doctrine (v0.1.50):** 把修法寫進工具，而非寫進 prompt。
> Mandatory program preflight first; AI is the backstop, not the lead.

Provide fast, pre-synthesis estimates of Power, Performance (Fmax /
critical-path delay), and Area for an RTL module. Acts as a Circuit
Foundation Model surrogate for the synthesis tool — seconds instead of
hours.

## Mandatory Deterministic Preflight

Before any narrative estimate:

```bash
# Extract any PPA hints already declared in the project README / spec:
python3 plugins/vibe-ic/programs/readme_ppa_extractor.py \
    --rtl-dir <rtl> --readme <README.md> --json /tmp/ppa_hints.json
```

Use the JSON output as the floor of any estimate you state. **Do not
overclaim a tighter number than the program returned** — the program
read the actual spec/README declared values; LLM-generated estimates
without that anchor have a known confabulation rate.

## When to use

Trigger when the user:
- Wants an area/timing ballpark before running DC/Genus/Yosys
- Is comparing two RTL variants and needs a quick "which is better"
- Asks "will this fit in X gates" or "can I close timing at Y MHz"
- Needs PPA feedback inside a generate-evaluate loop

## Inputs to gather

1. Target technology node (e.g., TSMC 28nm, 16nm, 7nm; or generic `NangateOpenCell`)
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

Technology: <node>
Target frequency: <MHz>

| Metric | Estimate | Range | Confidence |
|--------|----------|-------|------------|
| Area (µm²) | ... | ... – ... | High/Med/Low |
| Gate count (NAND2 eq) | ... | ... – ... | ... |
| Fmax (MHz) | ... | ... – ... | ... |
| Dynamic power (mW @ target f) | ... | ... – ... | ... |
| Leakage (µW) | ... | ... – ... | ... |

## Critical path (estimated)
<signal A> → <logic> → <signal B>  (~<n> logic levels)

## Bottleneck
<what is limiting Fmax or dominating area>

## Optimization suggestions
- <suggestion 1, e.g., pipeline the multiplier>
- <suggestion 2, e.g., share the adder>
```

## Technical basis

Grounded in Circuit Foundation Models for pre-synthesis prediction — encoder-based CFMs like MasterRTL, CircuitEncoder, and graph-neural-network surrogates trained on synthesized netlists. Typical prediction error: 10–15% vs real synthesis for area, 15–20% for timing.

## Do not

- Do not claim single-number precision — always give a range
- Do not replace real synthesis for sign-off; this is a pre-check only
- Do not extrapolate far outside the training distribution (e.g., very exotic architectures)

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
