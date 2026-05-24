---
name: analog-spec-extract
description: Extract analog block specifications from L1/L5 design documents into machine-readable spec.json per block. Use when starting the analog design track, or when the user says "extract analog specs", "what analog blocks do we need", "analog block list".
---

# Analog Spec Extract

Reads L1_DATASHEET.json (pin types, electrical specs) and L5_ADI_SPEC.json (analog-digital interface) to enumerate every analog block that needs transistor-level design, and produces a machine-readable `spec.json` for each.

## ⛔ HARD RULE — never silently emit empty block list (Wave 47, v0.120.1)

User directive (Wave 47): **"EVERY ITEM IN DESIGN DOCUMENTS SHOULD BE IMPLEMENTED!!!! EVERY!!!"**

Before declaring "no analog blocks" / SKIP / SKIPPED-CONDITION:

1. Run keyword grep over `input_doc/*.txt` and `input/docs/*.txt` for the 8 chip-AGNOSTIC analog keyword classes:
   - **oscillator**: `oscillator`, `RC.osc`, `crystal`, `fOSC`, `tOSC`, `FREQ_TRIM`, `FREQ_INIT`, `FREQ_ALL`
   - **ldo**: `LDO`, `low.dropout`, `regulator`, `VDDA`, `VDD_LDO`, `VREG`
   - **bandgap**: `bandgap`, `VBG`, `VREF`, `voltage reference`
   - **por**: `POR`, `power.on.reset`, `BOR`, `brownout`
   - **pull**: `pull.up`, `pull.down`, `RPD`, `RPU`, `RMPD`, `pulldown.resistor`, `pullup.resistor`
   - **esd**: `ESD`, `ESD.protection`, `clamp.diode`
   - **charge_pump**: `charge.pump`, `level.shifter`, `comparator`, `OTA`, `op.amp`
   - **trim**: `TRIM_*`, `trim register`, `trim code`

2. For each class with ≥1 hit, emit at least one minimal `analog_blocks[]` entry in L5 with:
   ```json
   {"name": "<descriptive>", "type": "<class>", "spec": "<one-line>",
    "evidence": "<file>:<line>", "implementation_status": "needs_design_work"}
   ```

3. Run the plugin gate to verify:
   ```bash
   python3 vibe-ic-marketplace/plugins/vibe-ic-d/programs/analog_content_detected_must_emit_l5_check.py <project_dir>
   ```

4. Forbidden: `analog/A0_skip_decision.json` as a top-level skip. Replace with `analog/A0_implementation_status.json` listing each block's per-step (A1-A8) status, OR rely on `L5.analog_blocks_detected=false` when the keyword scan PASSes empty.

A1 (this skill) PASS criterion is keyword-grep cleanliness, not human judgment that "the chip looks digital".


## When to use

- At the start of the analog design track (Step A1)
- After Phase 1 or Phase 2a has produced L1 + L5 layer documents
- When the user asks "what analog blocks does this chip need?"

## Inputs

1. `generated_docs/L1_DATASHEET.json` — pin definitions, electrical characteristics
2. `generated_docs/L5_ADI_SPEC.json` — analog-digital interface signals, protection, trim

## Analog block taxonomy

| Type | Typical names | Key specs |
|------|--------------|-----------|
| LDO | ldo, regulator, vreg | Vout, Vin range, Iload, PSRR, dropout, Iq |
| Bandgap | bgr, bandgap, vref | Vref, TC (ppm/°C), PSRR, noise |
| Oscillator | osc, rc_osc, ring_osc | Frequency, accuracy, power, jitter |
| POR | por, power_on_reset | Trip voltage, hysteresis, delay |
| Comparator | comp, comparator | Offset, propagation delay, Vin range |
| ADC | adc, sar_adc | Resolution, sample rate, INL/DNL, ENOB |
| DAC | dac | Resolution, settling time, INL/DNL |
| PLL | pll, dpll | Lock range, jitter, loop BW |
| Charge pump | cp, charge_pump | Output current, compliance range |
| OTA/OpAmp | ota, opamp | Gain, UGB, PM, noise, CMRR |
| Bias | bias, ibias, current_ref | Accuracy, TC, compliance |
| Level shifter | ls, level_shift | Delay, Vin/Vout range |

## Workflow

1. Parse L1 for pins with `type: "power"`, `type: "analog"`, or electrical specs suggesting analog blocks
2. Parse L5 for `analog_blocks[]`, `protection[]`, `trim_outputs[]`
3. For each detected block:
   a. Classify by taxonomy (above)
   b. Extract specs from L1/L5 (voltage, current, frequency, accuracy)
   c. Identify interface signals (inputs, outputs, enable, trim bits)
   d. Write `analog/<block>/spec.json`
4. Write `analog/analog_block_list.json` (master list)

## Output format

### `analog/analog_block_list.json`
```json
{
  "blocks": [
    {"name": "ldo_1v8", "type": "LDO", "spec_file": "analog/ldo_1v8/spec.json"},
    {"name": "por", "type": "POR", "spec_file": "analog/por/spec.json"}
  ],
  "block_count": 2
}
```

### `analog/<block>/spec.json`
```json
{
  "block_name": "ldo_1v8",
  "block_type": "LDO",
  "supply": {"nom_v": 3.3, "min_v": 2.7, "max_v": 5.5},
  "specs": {
    "vout": {"min": 1.75, "typ": 1.80, "max": 1.85, "unit": "V"},
    "iload_max": {"typ": 50, "unit": "mA"},
    "iq": {"max": 60, "unit": "uA"},
    "psrr_1khz": {"min": 40, "unit": "dB"}
  },
  "interface": {
    "inputs": ["vin", "en"],
    "outputs": ["vout"],
    "digital_ctrl": ["trim[2:0]"]
  },
  "constraints": {
    "area_budget_um2": null,
    "power_budget_uw": null
  }
}
```

## Handoff

- `analog/<block>/spec.json` → `/analog-topology-select` (Step A2)
- `analog/analog_block_list.json` → triggers the analog track in the flow

## Compliance gate (vibe-ic-d - mandatory when deterministic edition is installed)

If you have the `vibe-ic-d` plugin installed alongside `vibe-ic-core`,
after producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic-d/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic-d/skills/analog-spec-extract/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.

**Your task is not complete until the audit returns PASS.**
