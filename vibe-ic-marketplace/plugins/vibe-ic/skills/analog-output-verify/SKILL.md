---
name: analog-output-verify
description: After analog_one_shot_runner emits A1..A9 outputs, AI spot-checks corner-sim coverage, hardmacro completeness, HIL data fidelity. Triggers on /vibe-ic-analog PASS or phrases like "review analog", "verify A8 hardmacro", "check analog corners".
tier: verification
paired_program: analog_one_shot_runner.py
---

# Analog Output Verification

**Purpose**: analog runner is a thin chain marking each A1..A9 as PASS / WAIVED. WAIVED means human / domain skill needed. Even PASS steps need verification — analog correctness is rarely binary.

> **v1.6.14 Wave 90 — step renumber.** Pre-release decimal/sub-step
> ids were integerised; the analog track is now A1-A9 (A1-A5 unchanged,
> per-block PV is A6, Resim/Hardmacro/Cosim are A7/A8/A9).

## Verification checklist

For each analog block in `<project>/analog/<block>/`:

### A1 spec_extract
- A1_spec.json should match L5_ADI_SPEC.json's block entry
- Confirm specs are silicon-realistic (no V > 5V on 1.8V devices, etc.)

### A2 topology_select
- A2_topology.json names a real topology (cascode / two-stage / Miller / etc.)
- Topology choice consistent with A1 spec (e.g. high-gain → two-stage, low-power → folded cascode)

### A3 netlist_gen
- `<block>.sp` is valid SPICE netlist
- All transistor names cite a real model from `input/pdk/spice/*.lib`
- No floating nodes / dangling pins

### A4 corner_sweep
- All PVT corners run (TT/SS/FF + temp + voltage) — A4_corners.json covers ≥27 corners
- All corners' verdict columns parse and are numeric
- Margin to spec on every corner ≥10%

**Run the deterministic gate first** — the ≥27-corner count and the
≥10% per-corner margin floor are fixed thresholds, so let the program
assert them (it accepts both `A4_corners.json` and the runner's
`corner_results.json`, self-skips when no corner artefact / stub data
exists, and never over-flags informational corners with no numeric
margin):

```bash
python3 ../../programs/analog_corner_margin_check.py <project> \
    --json <project>/reports/gates/analog_corner_margin.json
```

Exit 0 = PASS (or self-skip), 1 = FAIL (count < 27 or a corner < 10%).
Note this is *stricter* than `analog_corner_sweep_check.py` (which only
enforces the lighter 9-corner 3×3 matrix). After the gate is green,
apply AI judgment to the items below.

### A5 layout
- A5_layout.json references a Magic .mag file that exists
- DRC clean (or has waivers list)
- LVS-ready

### A6 per_block_pv
- `analog/<block>/{drc_clean.flag, lvs_match.flag}` both present
- DRC + LVS log evidence retained for audit

### A7 post_layout_resim
- A7_postsim.json has same metrics as A4 corners + extracted parasitic
- Performance degradation 5-20% is normal; >30% indicates layout bug

### A8 hardmacro_gen
- LEF + lib + GDS + Verilog all generated
- LEF matches GDS outline
- Liberty timing data complete
- Verilog blackbox or behavioral

### A9 hw_verify
- Real breadboard measurement vs SPICE — error <5% PASS, 5-15% WARN, >15% FAIL
- Required for tapeout sign-off

## Spot-check actions

- Eyeball A4_corners.json for corner outliers
- Cross-check A8 LEF outline width × height vs A5 layout extents
- Compare A9 measurements to A7 simulation; flag systematic offsets

## When to escalate

- A4 corner FAIL → invoke `analog-sizing-loop` to retune
- A7 vs A4 delta > 30% → invoke `analog-extraction-resim` debug
- A9 vs A7 delta > 15% → invoke `analog-hw-tuning-loop`

## Output

Append findings to `<project>/reports/analog_verify.md`.


## Compliance gate (mandatory — not optional)

After producing your output, save it to a file and run:

```bash
python3 ../../_shared/skill_compliance_check.py \
    --requirements ./compliance.yaml <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with the specific missing elements listed.
`compliance.yaml` (in this skill's directory) enumerates every required
element of your output — section headers, metadata fields, handoff lines,
tool invocations.

**Your task is not complete until the audit returns PASS.** If it fails,
re-read the listed missing elements, patch your output, and re-run the
audit.

