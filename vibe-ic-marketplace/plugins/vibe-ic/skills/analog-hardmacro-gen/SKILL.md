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

> Deliverable PRESENCE + non-degeneracy is enforced deterministically:
> `programs/analog_hardmacro_check.py` (all 4 files exist; LEF has
> MACRO/PIN, LIB has cell, V has module) and
> `programs/analog_liberty_nonzero_delay_check.py` (the "no zero-delay
> Liberty" rule — area-only / all-zero `.lib` => FAIL). Cross-file
> pin-name equality is enforced by
> `programs/analog_hardmacro_pinname_consistency_check.py`.

### 1. GDS (`hardmacro/<block>/<block>.gds`)
- Source: Magic layout → `eda_gds` or `eda_run_tcl` with Magic `gds write`
- The `gds write` / `lef write` Magic TCL is a fixed command template —
  emitted deterministically alongside the port-extraction TCL in
  `programs/magic_port_extract_emit.py`.
- Must include all metal layers, vias, device layers

### 2. LEF abstract (`hardmacro/<block>/<block>.lef`)
- Generated via Magic `lef write` (see `magic_port_extract_emit.py`)
- Contains: MACRO definition, PIN locations (with DIRECTION + USE), OBS layer, SIZE
- Pin names must match the RTL port names exactly — enforced by
  `programs/analog_hardmacro_pinname_consistency_check.py` (3-way
  set-equality: spec.json `interface.pins` ↔ LEF PINs ↔ Verilog ports;
  portless LEF + ported Verilog => FAIL).

### 3. Liberty timing model (`hardmacro/<block>/<block>.lib`)
- Derived from SPICE corner results (worst-case SS corner).
- Non-degeneracy enforced by
  `programs/analog_liberty_nonzero_delay_check.py`: the `.lib` must carry
  at least one timing/leakage attribute and every timing value must be
  non-zero (an area-only or all-zero `.lib` is the documented vacuous-STA
  defect and FAILs). The check also reports the corner-sweep provenance
  (`real_ngspice` vs stub) read from `corner_results.json`.
- **Judgment residual (NOT a program):** which arcs to model and what
  delay value to assign — `corner_results.json` carries the analog spec
  value (e.g. `vout_v`, `ota_ugbw_hz`) per PVT corner, NOT pre-computed
  `cell_rise`/`cell_fall`/`setup`/`hold`/`leakage` timing arcs. Mapping
  a measured analog metric onto Liberty timing arcs for a given control
  interface is an analog-modeling decision; only the SS-worst-corner
  selection and the non-zero formatting are deterministic.

### 4. Behavioral Verilog (`hardmacro/<block>/<block>.v`)
- For gate-level simulation (digital TB can instantiate this)
- The **port list** must match the spec interface — enforced by
  `programs/analog_hardmacro_pinname_consistency_check.py`.
- **Judgment residual (NOT a program):** HOW MUCH analog behavior to
  model in the integration Verilog — which ports matter for digital sim,
  what minimal behavior keeps gate-level sim meaningful:
  ```verilog
  module ldo_1v8 (input vin, input en, input [2:0] trim, output vout);
    assign vout = en ? 1'b1 : 1'bz;  // simplified: high when enabled
  endmodule
  ```
- Real analog behavior is in SPICE; this is just for digital integration sim

## Workflow

1. **GDS**: If `layout.mag` exists, run Magic `gds write` (template via
   `magic_port_extract_emit.py`); else run `eda_analog_layout` first
2. **LEF**: Run Magic `lef write` with correct pin definitions
3. **Liberty**: Pick the SS (worst) corner from `corner_results.json` and
   author the `.lib` with non-zero arcs (modeling judgment per § 3 above);
   non-degeneracy gate = `analog_liberty_nonzero_delay_check.py`
4. **Behavioral Verilog**: Emit a module whose port list matches
   `spec.json` `interface.pins`; behavior-modeling is judgment (§ 4 above)
5. **Validate** (deterministic, do not hand-check): run
   `analog_hardmacro_check.py` + `analog_hardmacro_pinname_consistency_check.py`
   + `analog_liberty_nonzero_delay_check.py` on the project dir

## Output format

```
hardmacro/<block>/
  ├── <block>.gds      — physical layout
  ├── <block>.lef      — abstract for PnR placement
  ├── <block>.lib      — timing model for STA
  └── <block>.v        — behavioral model for simulation
```

## Do not

- Do not generate Liberty with zero delays — use actual SPICE-measured
  values (enforced by `programs/analog_liberty_nonzero_delay_check.py`)
- Do not mismatch pin names between LEF and Verilog — causes LVS failure
  at integration (enforced by
  `programs/analog_hardmacro_pinname_consistency_check.py`)
- Do not include internal device-level detail in LEF — only pins and
  obstruction (modeling judgment, left to the agent)

## Handoff

- `hardmacro/<block>/` → Digital Step 15 (Floorplan; was Step 14 pre-Wave-91) via OpenROAD macro placement
- LEF → `eda_pnr` `additional_lefs` parameter
- Liberty → `eda_sta` additional liberty path
- Behavioral Verilog → `eda_simulate` for mixed-signal gate-level sim

## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/analog-hardmacro-gen/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.

**Your task is not complete until the audit returns PASS.**
