---
name: analog-extraction-resim
description: Post-layout parasitic extraction + re-simulation for analog blocks — compares pre-layout vs post-layout specs. Use when the user says "post-layout resim", "extract and resimulate", "parasitic check", or at Step A7 of the analog track.
---

# Analog Extraction Resim

After analog layout in Magic, extracts parasitic RC and re-simulates across PVT corners to check for layout-induced performance degradation. Compares pre-layout vs post-layout results and flags regressions.

## When to use

- Step A7 of the analog track
- After `analog-layout` has produced a Magic `.mag` file
- When the user asks "did the layout hurt my bandwidth?"

## Inputs

1. `analog/<block>/layout.mag` — Magic layout file
2. `analog/<block>/corner_results.json` — pre-layout SPICE results (baseline)
3. `analog/<block>/spec.json` — specs for pass/fail comparison
4. PDK (gf180 or sky130)

## Workflow

1. **Extract parasitics**:
   - `eda_extraction` with `gds_file` or via Magic TCL:
     ```tcl
     load <block>
     extract all
     ext2spice lvs
     ext2spice
     ```
   - Output: `analog/<block>/<block>_extracted.spice`

2. **Re-simulate with extracted netlist**:
   - Replace ideal subcircuit with extracted netlist in testbench
   - Run `eda_spice_corner` with same corners as pre-layout
   - Output: `analog/<block>/post_layout_corner_results.json`

3. **Compare pre vs post**:
   - For each spec metric in each corner:
     - Calculate degradation: `(post - pre) / pre × 100%`
     - Flag >20% degradation as ERROR
     - Flag >10% degradation as WARNING
   - Typical degradation sources:
     - Bandwidth reduction (parasitic C on high-impedance nodes)
     - Gain reduction (parasitic R in signal path)
     - Increased noise (parasitic coupling)

## Output format

### `analog/<block>/pre_vs_post.json`
```json
{
  "block_name": "ldo_1v8",
  "pre_layout_file": "corner_results.json",
  "post_layout_file": "post_layout_corner_results.json",
  "comparison": {
    "gain_db": {"pre": 62.3, "post": 58.1, "degradation_pct": -6.7, "status": "WARNING"},
    "ugb_mhz": {"pre": 11.2, "post": 8.9, "degradation_pct": -20.5, "status": "ERROR"},
    "vout_dc": {"pre": 1.8002, "post": 1.7998, "degradation_pct": -0.02, "status": "OK"}
  },
  "worst_degradation": {"metric": "ugb_mhz", "pct": -20.5},
  "overall_status": "NEEDS_RELAYOUT"
}
```

## Degradation thresholds

| Degradation | Status | Action |
|------------|--------|--------|
| <10% | OK | Proceed to hardmacro generation |
| 10-20% | WARNING | Note for review, may proceed |
| >20% | ERROR | Re-layout required (improve routing, add shielding) |

## Do not

- Do not skip extraction and go straight to hardmacro — parasitic RC is the #1 cause of analog silicon failure
- Do not compare only TT corner — worst-case degradation often appears at SS+hot
- Do not ignore capacitive loading on compensation nodes (Cc) — parasitics add to Cc

## Handoff

- If overall_status == "OK" or "WARNING" → `analog-hardmacro-gen` (Step A8)
- If overall_status == "NEEDS_RELAYOUT" → back to `analog-layout` (Step A5)
- `post_layout_corner_results.json` → `analog_pre_vs_post_layout_check` gate

## Compliance gate (vibe-ic-d - mandatory when deterministic edition is installed)

If you have the `vibe-ic-d` plugin installed alongside `vibe-ic-core`,
after producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic-d/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic-d/skills/analog-extraction-resim/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.

**Your task is not complete until the audit returns PASS.**
