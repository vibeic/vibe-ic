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
> Liberty" rule — area-only / all-zero `.lib` => FAIL; a propagation arc
> slower than the design's declared SDC/L8 clock period => FAIL). Cross-file
> pin-name equality is enforced by
> `programs/analog_hardmacro_pinname_consistency_check.py`.

### 1. GDS (`hardmacro/<block>/<block>.gds`)
- **NOT YOUR JOB — a program does this.** `programs/analog_hardmacro_gds_emit.py`
  streams `phase3/analog/<block>/layout.mag` out to
  `phase3/analog/hardmacro/<block>/<block>.gds` with Magic, against the
  technology the layout's own `tech` line names. `analog_one_shot_runner`
  invokes it at `A8_hardmacro_gen`, before the A8 checks. It is deliberately
  NOT wired into A8's flow gate: `flow_compliance_check` is the acceptance
  auditor, and an auditor that writes a declared `required_output` into the
  project it audits certifies its own output. Do not hand-author a `.gds`.
- Its TCL is `magic_port_extract_emit.build_gds_write_tcl` — the same fixed
  `load / select top cell / gds write` template the extraction path uses.
  Between v0.1.114 and 2026-07 that emitter had **no caller at all**, which is
  why A8 declared a layout no run produced.
- Honest contract: rc=2 when no container/Magic/magicrc for that technology is
  reachable, rc=1 when Magic runs and the result carries no geometry (the
  hollow file is deleted, never left where a presence check would count it),
  and a deterministic-stub `layout.mag` is skipped so the PASS_WITH_STUB tier
  is untouched.
- If the block has no `layout.mag` yet, run `eda_analog_layout` (A5) first —
  the producer names that as its skip reason rather than inventing geometry.

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
  defect and FAILs). If a `cell_rise`/`cell_fall`/intrinsic propagation
  delay exceeds the design-owned clock period in SDC/L8, the same check
  FAILs: an analog settling time is not a synchronous cell arc. Keep a
  leakage+capacitance-only Liberty when the macro has no real synchronous
  propagation arc, and record settling in `interface.json`
  `timing_contract`. The check also reports the corner-sweep provenance
  (`real_ngspice` vs stub) read from `corner_results.json`.
- **Judgment residual (NOT a program):** which genuine sub-period arcs to
  model and what delay value to assign — `corner_results.json` carries the
  analog spec value (e.g. `vout_v`, `ota_ugbw_hz`) per PVT corner, NOT pre-computed
  `cell_rise`/`cell_fall`/`setup`/`hold`/`leakage` timing arcs. Mapping
  a measured analog metric onto Liberty timing arcs for a given control
  interface is an analog-modeling decision. The deterministic boundary is:
  SS-worst-corner selection, non-zero formatting, and no propagation arc
  may exceed the design clock period; a slower settling contract belongs
  in `interface.json` `timing_contract` instead.

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

1. **GDS**: nothing to author — `analog_hardmacro_gds_emit` produces it from
   `layout.mag`; if there is no `layout.mag`, run `eda_analog_layout` (A5) first
2. **LEF**: Run Magic `lef write` with correct pin definitions
3. **Liberty**: Pick the SS (worst) corner from `corner_results.json` and
   author the `.lib` with non-zero leakage and only genuine sub-period
   propagation arcs (modeling judgment per § 3 above); put analog settling
   in `interface.json` `timing_contract`;
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
- Do not encode an analog settling time longer than the declared clock period
  as `cell_rise` / `cell_fall`: an analog macro carries no synchronous cell
  arc for that contract. Move it to `interface.json` `timing_contract`
  (enforced by `programs/analog_liberty_nonzero_delay_check.py`)
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
