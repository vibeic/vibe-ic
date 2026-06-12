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

**Body connection rules** (NMOS body → VSS/`0`, PMOS body → VDD — the #1 SPICE
simulation failure): enforced deterministically by `programs/analog_netlist_pdk_check.py`
(`PMOS_BODY_TO_VSS` / `NMOS_BODY_TO_VDD`). Model-include presence is also enforced
there (`NO_MODEL_INCLUDE`).

## SKY130 device instantiation

```spice
.lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice tt

* NMOS: drain gate source body
XM1 drain gate source 0 sky130_fd_pr__nfet_01v8 W=1u L=0.15u

* PMOS: drain gate source body
XMP1 drain gate source VDD sky130_fd_pr__pfet_01v8 W=2u L=0.15u
```

## Workflow

1. Read topology schematic → identify all devices and their connections.
   **KEEP-JUDGMENT:** resolving a free-form/ASCII topology description into the
   device-to-net connectivity graph is comprehension, not parsing — only an LLM can
   do this reliably. (Once the graph exists, `analog_netlist_connectivity_check.py`
   verifies it has no floating nodes / unused ports.)
2. Read sizing table → get W, L for each device
3. Generate subcircuit definition:
   ```spice
   .subckt <block_name> <port_list>
   * Device instantiations
   .ends
   ```
4. Generate testbench:
   - Power supply: `Vdd VDD 0 DC 3.3` (GF180) or `DC 1.8` (SKY130). The supply value
     must match the PDK + device flavor — enforced by
     `programs/analog_tb_supply_pdk_check.py` (`SUPPLY_PDK_MISMATCH` /
     `SUPPLY_DEVICE_MISMATCH` / `DEVICE_FLAVOR_PDK_MISMATCH`).
   - Stimulus: DC sweep, AC source, transient pulse — **choosing the stimulus class
     and load network requires understanding the block's function (KEEP-JUDGMENT).**
   - Load: resistive/capacitive per spec
5. Generate `.meas` statements from spec.json — **deterministic; do not hand-author.**
   Run `programs/analog_meas_from_spec_gen.py <block>/spec.json --out meas.inc`. It
   classifies each spec key into DC / AC / TRAN and emits the templated `.meas` lines
   (FAILs honestly if spec.json is missing or has no measurable keys).
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

## Deterministic gates (run these — do not eyeball)

These rules are enforced by programs, not by prose. Run them after emitting `.sp`/`tb_*.sp`:

| Rule | Program | FAIL codes |
|------|---------|------------|
| Body connections + model-include presence | `programs/analog_netlist_pdk_check.py` | `PMOS_BODY_TO_VSS`, `NMOS_BODY_TO_VDD`, `NO_MODEL_INCLUDE` |
| Include order (design.ngspice before .lib, GF180) | `programs/analog_netlist_include_order_check.py` | `LIB_BEFORE_DESIGN_INCLUDE` |
| No hardcoded absolute paths (except `/foss/pdks/...`) | `programs/analog_netlist_path_lint.py` | `NON_WHITELISTED_ABSOLUTE_PATH` |
| No floating nodes / unused ports | `programs/analog_netlist_connectivity_check.py` | `FLOATING_NODE`, `UNUSED_PORT` |
| Supply value matches PDK + device flavor | `programs/analog_tb_supply_pdk_check.py` | `SUPPLY_PDK_MISMATCH`, `SUPPLY_DEVICE_MISMATCH`, `DEVICE_FLAVOR_PDK_MISMATCH` |
| `.meas` lines from spec.json | `programs/analog_meas_from_spec_gen.py` | (generator) |

## Do not

- Do not use `.param` for device sizes unless doing a sweep — use literal values for clarity
  (style preference; not gated).

## Handoff

- `analog/<block>/<block>.sp` + `tb_<block>.sp` → `/ams-sim` or `eda_spice_corner` (Step A4)
- If simulation fails → back to `/analog-sizing` for re-sizing

## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/analog-netlist-gen/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.

**Your task is not complete until the audit returns PASS.**
