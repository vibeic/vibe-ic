---
name: analog-hardmacro-gen
description: Package a verified analog block into a hardmacro (LEF abstract + Liberty timing + GDS + behavioral Verilog) for digital PnR integration. Use when the user says "package analog block", "generate hardmacro", "create LEF/Liberty", or at Step A7 of the analog track.
---

# Analog Hardmacro Gen

Takes a verified analog block (SPICE corner sweep passed, optionally hardware-verified) and produces the four deliverables that digital PnR (OpenROAD) needs to integrate it alongside standard cells.

## When to use

- Step A7 of the analog track
- After `analog-extraction-resim` confirms post-layout specs are acceptable
- When the user says "package this analog block for digital integration"

## Inputs

1. `analog/<block>/corner_results.json` — worst-case timing from SPICE
2. `analog/<block>/layout.mag` — Magic layout (or generate via `eda_analog_layout`)
3. `analog/<block>/spec.json` — port definitions
4. PDK (gf180 or sky130)

## Four deliverables

### 1. GDS (`hardmacro/<block>/<block>.gds`)
- Source: Magic layout → `eda_gds` or `eda_run_tcl` with Magic `gds write`
- Must include all metal layers, vias, device layers

### 2. LEF abstract (`hardmacro/<block>/<block>.lef`)
- Generated via Magic `lef write` command (via `eda_run_tcl engine=magic`)
- Contains: MACRO definition, PIN locations (with DIRECTION + USE), OBS layer, SIZE
- Pin names must match the RTL port names exactly

### 3. Liberty timing model (`hardmacro/<block>/<block>.lib`)
- Derived from SPICE corner results (worst-case SS corner):
  - Input→output propagation delay → `cell_rise` / `cell_fall`
  - Setup/hold times for digital control inputs
  - Leakage power from DC operating point
- Simplified single-corner model (SS worst case) is sufficient for v0.108
- Format: standard Liberty `.lib` with one cell definition

### 4. Behavioral Verilog (`hardmacro/<block>/<block>.v`)
- For gate-level simulation (digital TB can instantiate this)
- Simplified model with correct port list and basic behavior:
  ```verilog
  module ldo_1v8 (input vin, input en, input [2:0] trim, output vout);
    assign vout = en ? 1'b1 : 1'bz;  // simplified: high when enabled
  endmodule
  ```
- Real analog behavior is in SPICE; this is just for digital integration sim

## Workflow

1. **GDS**: If `layout.mag` exists, run Magic `gds write`; else run `eda_analog_layout` first
2. **LEF**: Run Magic `lef write` with correct pin definitions
3. **Liberty**: Parse `corner_results.json` for SS corner → extract worst-case delays → generate `.lib`
4. **Behavioral Verilog**: Parse `spec.json` for ports → generate simplified behavioral module
5. Validate: LEF pin names match Verilog port names match spec.json interface

## Output format

```
hardmacro/<block>/
  ├── <block>.gds      — physical layout
  ├── <block>.lef      — abstract for PnR placement
  ├── <block>.lib      — timing model for STA
  └── <block>.v        — behavioral model for simulation
```

## Do not

- Do not generate Liberty with zero delays — use actual SPICE-measured values
- Do not mismatch pin names between LEF and Verilog (causes LVS failure at integration)
- Do not include internal device-level detail in LEF — only pins and obstruction

## Handoff

- `hardmacro/<block>/` → Digital Step 15 (Floorplan; was Step 14 pre-Wave-91) via OpenROAD macro placement
- LEF → `eda_pnr` `additional_lefs` parameter
- Liberty → `eda_sta` additional liberty path
- Behavioral Verilog → `eda_simulate` for mixed-signal gate-level sim

## Compliance gate (vibe-ic-d - mandatory when deterministic edition is installed)

If you have the `vibe-ic-d` plugin installed alongside `vibe-ic`,
after producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic-d/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic-d/skills/analog-hardmacro-gen/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.

**Your task is not complete until the audit returns PASS.**
