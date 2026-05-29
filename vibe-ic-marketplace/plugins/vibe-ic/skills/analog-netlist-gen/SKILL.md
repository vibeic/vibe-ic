---
name: analog-netlist-gen
description: Generate a complete SPICE netlist (.sp) from a sized analog topology, with correct PDK device models, body connections, and testbench. Use when the user says "generate SPICE", "write netlist", "create spice deck", or at Step A3 of the analog track.
---

# Analog Netlist Gen

Translates the sizing table (from `analog-sizing`) and topology (from `analog-topology-select`) into a valid, simulatable SPICE netlist with proper PDK model includes, body connections, and measurement statements.

## When to use

- Step A3 of the analog track
- After `analog-sizing` has produced a device table with W/L/Id values
- When the user wants to convert hand analysis into a SPICE deck

## Inputs

1. `analog/<block>/topology.md` — from `analog-topology-select`
2. `analog/<block>/sizing.md` — from `analog-sizing` (device table with W, L, gm/Id, Id)
3. `analog/<block>/spec.json` — from `analog-spec-extract` (specs for .meas statements)
4. PDK: gf180 or sky130

## GF180 device instantiation (CRITICAL)

From `analog-sizing/PRACTICAL_NOTES.md` — verified working:

```spice
* Model include — ORDER MATTERS
.include /foss/pdks/gf180mcuD/libs.tech/ngspice/design.ngspice
.lib /foss/pdks/gf180mcuD/libs.tech/ngspice/sm141064.ngspice typical

* NMOS: drain gate source body
XM1 drain gate source 0 nfet_03v3 W=20u L=2u

* PMOS: drain gate source body — BODY MUST BE VDD
XMP1 drain gate source VDD pfet_03v3 W=20u L=4u
```

**Body connection rules**:
- NMOS body → VSS (ground, node `0`)
- PMOS body → VDD (supply)
- Getting this wrong is the #1 SPICE simulation failure

## SKY130 device instantiation

```spice
.lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice tt

* NMOS: drain gate source body
XM1 drain gate source 0 sky130_fd_pr__nfet_01v8 W=1u L=0.15u

* PMOS: drain gate source body
XMP1 drain gate source VDD sky130_fd_pr__pfet_01v8 W=2u L=0.15u
```

## Workflow

1. Read topology schematic → identify all devices and their connections
2. Read sizing table → get W, L for each device
3. Generate subcircuit definition:
   ```spice
   .subckt <block_name> <port_list>
   * Device instantiations
   .ends
   ```
4. Generate testbench:
   - Power supply: `Vdd VDD 0 DC 3.3` (GF180) or `DC 1.8` (SKY130)
   - Stimulus: DC sweep, AC source, transient pulse (depends on block type)
   - Load: resistive/capacitive per spec
5. Generate `.meas` statements from spec.json:
   ```spice
   .meas DC vout_dc FIND V(vout) AT=3.3
   .meas AC gain_db FIND VDB(vout) AT=1k
   .meas TRAN tpd TRIG V(in) VAL=1.65 RISE=1 TARG V(out) VAL=1.65 FALL=1
   ```
6. Add `.control` block for ngspice batch mode

## Output format

Two files per block:

### `analog/<block>/<block>.sp` — subcircuit
```spice
* <block_name> — auto-generated from sizing table
* PDK: GF180MCU  Process: typical
.include /foss/pdks/gf180mcuD/libs.tech/ngspice/design.ngspice
.lib /foss/pdks/gf180mcuD/libs.tech/ngspice/sm141064.ngspice typical

.subckt <block_name> <ports>
<device instantiations>
.ends
```

### `analog/<block>/tb_<block>.sp` — testbench
```spice
* Testbench for <block_name>
.include <block>.sp

X1 <connections> <block_name>
Vdd VDD 0 DC 3.3
<stimulus>
<analysis commands>
<.meas statements>
.end
```

## Do not

- Do not hardcode absolute PDK paths — use the standard include patterns above
- Do not forget body connections (4th terminal)
- Do not mix model include order (design.ngspice MUST come before .lib)
- Do not use `.param` for device sizes unless doing a sweep — use literal values for clarity

## Handoff

- `analog/<block>/<block>.sp` + `tb_<block>.sp` → `/ams-sim` or `eda_spice_corner` (Step A4)
- If simulation fails → back to `/analog-sizing` for re-sizing

## Compliance gate (vibe-ic-d - mandatory when deterministic edition is installed)

If you have the `vibe-ic-d` plugin installed alongside `vibe-ic`,
after producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic-d/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic-d/skills/analog-netlist-gen/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.

**Your task is not complete until the audit returns PASS.**
