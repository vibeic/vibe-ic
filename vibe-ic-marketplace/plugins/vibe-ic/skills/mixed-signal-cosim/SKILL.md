---
name: mixed-signal-cosim
description: Run mixed-signal co-simulation — digital gate-level Verilog + analog behavioral models together. Use when the user says "mixed-signal sim", "co-simulation", "digital-analog integration test", or at Step A9 of the analog track.
---

# Mixed-Signal Co-Sim

Verifies that analog blocks work correctly when connected to the digital logic by running a combined simulation: digital gate-level netlist + analog behavioral Verilog models (derived from SPICE corner results).

## When to use

- Step A9 of the analog track (final integration verification)
- After `analog-hardmacro-gen` has produced behavioral Verilog models
- When the user says "does the digital logic talk correctly to the LDO?"

## Inputs

1. Digital gate-level netlist (`synth/netlist.v` or `pnr/routed.v`)
2. `hardmacro/<block>/<block>.v` — behavioral Verilog per analog block
3. Digital testbench (`sim/tb_*.v`)
4. `analog/<block>/spec.json` — expected analog behavior

## Approaches (in order of preference)

### Approach 1: Behavioral Verilog (default, works with iverilog)

Generate enhanced behavioral models that go beyond `assign vout = en ? 1'b1 : 1'bz`:

```verilog
module ldo_1v8 (input vin, input en, input [2:0] trim, output reg vout_ok);
  // Model startup delay from SPICE measurements
  parameter STARTUP_DELAY_NS = 50;  // from corner_results.json
  
  initial vout_ok = 0;
  always @(posedge en) begin
    #STARTUP_DELAY_NS vout_ok = 1;
  end
  always @(negedge en) vout_ok = 0;
endmodule
```

Run via `eda_simulate` with the digital netlist + behavioral models.

### Approach 2: ngspice mixed-mode (advanced)

Use ngspice's digital simulation capability for true analog-digital co-sim:
- Digital blocks modeled as `d_source` / `d_state` models
- Analog blocks as full transistor-level SPICE
- Connected via `adc_bridge` / `dac_bridge` XSPICE models

Run via `eda_spice` with a combined deck.

## Workflow

1. Identify all analog-digital boundaries in the design
2. For each analog block:
   a. Load `corner_results.json` → extract key timing parameters
   b. Generate enhanced behavioral Verilog with realistic delays
3. Assemble co-simulation netlist:
   - Digital top module (gate-level or RTL)
   - Analog behavioral models replacing analog subcircuit instances
   - Shared testbench with stimulus
4. Run simulation via `eda_simulate`
5. Check:
   - Enable/disable sequences propagate correctly
   - Analog outputs reach expected levels within timeout
   - Digital controller responds to analog status signals
   - No glitches at analog-digital boundaries

## Output format

### `cosim/<block>_cosim_results.json`
```json
{
  "block_name": "ldo_1v8",
  "approach": "behavioral_verilog",
  "tests": [
    {"name": "startup_sequence", "status": "PASS", "details": "vout_ok asserted after 52ns"},
    {"name": "trim_sweep", "status": "PASS", "details": "all 8 trim codes accepted"}
  ],
  "all_pass": true
}
```

### `cosim/behavioral_models/` — generated Verilog models

## Do not

- Do not use Approach 2 (ngspice mixed-mode) unless Approach 1 fails — it's much slower and harder to debug
- Do not model analog blocks as ideal (zero delay, infinite bandwidth) — use SPICE-derived parameters
- Do not modify the digital netlist to accommodate analog models — the models must adapt

## Handoff

- `cosim_results.json` → `mixed_signal_cosim_check` gate program
- Behavioral models → can be reused for FPGA simulation if needed
- If co-sim reveals integration bugs → fix in RTL or analog interface

## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/mixed-signal-cosim/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.

**Your task is not complete until the audit returns PASS.**
