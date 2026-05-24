---
name: analog-layout
description: Plan analog layout with matching, common-centroid, interdigitation, dummy devices, guard rings, and shielding. Use when the user says "analog layout", "matching layout", "common centroid", "dummies", "guard ring", "interdigitated", "current mirror layout", "differential pair layout".
---

# Analog Layout

`analog-sizing` picks W/L; this skill translates the sized schematic into a layout plan that actually survives process variation. Matching and noise immunity live or die on layout, not schematic.

## When to use

- Current mirrors, differential pairs, bandgap references, DAC ladders
- Any circuit where σ(Vth) or σ(β) matching drives the spec
- Circuits near digital noise sources (guard rings / shielding needed)
- Before handing off to a layout engineer or Magic / Virtuoso

## Inputs

1. Sized schematic with device list (W, L, M, NF)
2. Matching pairs / groups (which devices must match)
3. Sensitivity list (which mismatches kill which spec)
4. PDK rules (well spacing, latch-up, antenna)
5. Floorplan block size budget

## Workflow

1. **Identify matching groups** — pairs, quads, ratios
2. **Choose matching style**:
   - Common-centroid 2×2, 4×4 for differential pairs
   - Interdigitation ABAB or ABBA for current mirrors
   - Centroid-preserving patterns for large ratios
3. **Dummy devices**: at least 2 dummies on each side of a matching row
4. **Guard rings**: n-well ring around PMOS, p-substrate ring around NMOS near digital
5. **Routing rules**:
   - Symmetric routing for differential signals
   - Shielded routing for sensitive nodes (clock, bandgap output)
   - Avoid crossing a matched row with unrelated metal
6. **Density / antenna**: ensure fill rules and antenna rules met without breaking symmetry
7. **Post-layout extraction**: plan for RC back-annotation → re-simulate → may need sizing iteration

## Output format

- `layout/<block>_layout_plan.md`:
  - Device placement diagram (ASCII or SVG)
  - Matching pattern per group
  - Routing rules
  - Dummy / guard-ring list
  - Known risks

## Technical basis

Classic references: Razavi "Design of Analog CMOS Integrated Circuits" ch. on layout, Hastings "The Art of Analog Layout", Pelgrom matching model. Process-specific matching coefficients come from the PDK.

## Handoff

- Sized devices → input to this skill came from `/analog-sizing`
- LVS verification → `/lvs-triage`
- DRC verification → `/drc-fix`
- Post-layout resim → `/ams-sim`

## Compliance gate (vibe-ic-d - mandatory when deterministic edition is installed)

If you have the `vibe-ic-d` plugin installed alongside `vibe-ic-core`,
after producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic-d/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic-d/skills/analog-layout/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding vibe-ic-d skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.
