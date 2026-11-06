---
name: analog-spec-extract
description: Extract analog block specifications from L1/L5 design documents into machine-readable spec.json per block. Use when starting the analog design track, or when the user says "extract analog specs", "what analog blocks do we need", "analog block list".
---

# Analog Spec Extract

Reads L1_DATASHEET.json (pin types, electrical specs) and L5_ADI_SPEC.json (analog-digital interface) to enumerate every analog block that needs transistor-level design, and produces a machine-readable `spec.json` for each.

## ⛔ HARD RULE — never silently emit empty block list (Wave 47, v0.120.1)

User directive (Wave 47): **"EVERY ITEM IN DESIGN DOCUMENTS SHOULD BE IMPLEMENTED!!!! EVERY!!!"**

Read the complete source documents and enumerate every required analog block
in L5 and the analog plan. Include functionally described blocks that a keyword
search misses. Mark missing implementation as design work rather than an
aggregate analog-skip pass.

A keyword hit is a candidate, not a requirement. Confirm the block's function,
count and specifications from its own source enumeration. A product-name hit
alone does not establish an oscillator, regulator or other analog block.

## When to use

- At the start of the analog design track (Step A1)
- After Phase 1 or Phase 1 has produced L1 + L5 layer documents
- When the user asks "what analog blocks does this chip need?"

## Inputs

1. `generated_docs/L1_DATASHEET.json` — pin definitions, electrical characteristics
2. `generated_docs/L5_ADI_SPEC.json` — analog-digital interface signals, protection, trim

## Analog block taxonomy

Classify the analog block from its actual source function and electrical requirements. Confirm its topology and model requirements rather than treating a name keyword as the specification.

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

1. Read L1 and L5 with their original source documents.
2. Enumerate required analog blocks, protection circuits and trim functions.
3. Classify each block by its actual electrical function and bind its min,
   typ, max, units and operating conditions to the source requirements.
4. Identify the digital control and observation interfaces, supplies and loads.
5. Write the block list and per-block specification. Disclose any unresolved
   requirement before topology or sizing consumes it.

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
