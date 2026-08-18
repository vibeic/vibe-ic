---
name: analog-spec-extract
description: Extract analog block specifications from L1/L5 design documents into machine-readable spec.json per block. Use when starting the analog design track, or when the user says "extract analog specs", "what analog blocks do we need", "analog block list".
---

# Analog Spec Extract

Reads L1_DATASHEET.json (pin types, electrical specs) and L5_ADI_SPEC.json (analog-digital interface) to enumerate every analog block that needs transistor-level design, and produces a machine-readable `spec.json` for each.

## ⛔ HARD RULE — never silently emit empty block list (Wave 47, v0.120.1)

User directive (Wave 47): **"EVERY ITEM IN DESIGN DOCUMENTS SHOULD BE IMPLEMENTED!!!! EVERY!!!"**

The deterministic parts of this hard rule are now programs — run them, don't re-implement them in prose:

- **8-class analog keyword scan + L5-mapping** — enforced by `programs/analog_content_detected_must_emit_l5_check.py` (the chip-AGNOSTIC grep over `input_doc/*.txt` + `input/docs/*.txt` for oscillator / ldo / bandgap / por / pull / esd / charge_pump / trim, with per-hit negation awareness, lives there). For each detected class emit at least one minimal `analog_blocks[]` entry:
  ```json
  {"name": "<descriptive>", "type": "<class>", "spec": "<one-line>",
   "evidence": "<file>:<line>", "implementation_status": "needs_design_work"}
  ```
  then run the gate against `<project_dir>`.
- **Forbidden `analog/A0_skip_decision.json` top-level skip** — enforced by `programs/analog_a0_skip_forbidden_check.py`. Replace any skip with `analog/A0_implementation_status.json` (per-block A1-A8 status) OR set `L5.analog_blocks_detected=false` when the keyword scan PASSes empty.

A1 (this skill) PASS criterion is keyword-grep cleanliness, not human judgment that "the chip looks digital".

**Residual LLM judgment (not a program):** the keyword scan is a *recall floor*, not a complete detector — recognising a NON-keyword analog block (a custom sensor-readout front-end described only functionally, with no token in the 8-class list) is exactly where your judgment is needed. Catch what the grep misses and add it to `analog_blocks[]` anyway.

**Spurious-block flip-side (cross-ref → `analog-topology-select`, #466B):** the recall floor
also OVER-fires. A candidate emitted **only** because a product-name keyword in L1 matched a
class — with no spec ever bound (`spec == null`) — is *presumed spurious* and must be
confirmed against the L5 type enumeration (the "N analog blocks" count sentence and/or the
Block A/B table headers) **before** A2 spends any sizing compute. Drop it if L5 doesn't
enumerate that class; keep + spec-bind it if L5 does. A block's multiplicity (`×N`) must
come from the block's OWN enumeration row, never a sibling block's evidence paragraph. The
full sanity procedure + `why_not_bucket_a` rationale lives in `analog-topology-select`'s
"spurious-block sanity check" capture; do not re-implement it here as a deny-list — whether
a name-only block is real requires reading L5, not a static rule.


## When to use

- At the start of the analog design track (Step A1)
- After Phase 1 or Phase 1 has produced L1 + L5 layer documents
- When the user asks "what analog blocks does this chip need?"

## Inputs

1. `generated_docs/L1_DATASHEET.json` — pin definitions, electrical characteristics
2. `generated_docs/L5_ADI_SPEC.json` — analog-digital interface signals, protection, trim

## Analog block taxonomy

The **name → type** lookup is deterministic — enforced by `programs/analog_block_type_classify.py`
(`python3 analog_block_type_classify.py <name>` classifies a single block; `--block-list <path>`
FAILs when any block's declared `type` contradicts the lookup of its `name`, e.g. `name="ldo_1v8"`
declared `Oscillator`). The "Key specs" column below is reference vocabulary for the LLM step that
binds numbers (next section), not a deterministic rule.

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
   a. Classify by taxonomy — `programs/analog_block_type_classify.py`
   b. **Bind specs from L1/L5 (LLM judgment, NOT a program):** the per-memory doctrine
      *"semantic extraction needs LLM confirm"* applies — a program can grep candidate numbers,
      but deciding *which* number is the typ Vout vs the max Iload vs the PSRR@1kHz from a prose
      datasheet sentence or a free-form electrical-characteristics table is your job. Fill the
      `specs` block accordingly.
   c. Identify interface signals (inputs, outputs, enable, trim bits)
   d. Write `analog/<block>/spec.json` — its presence + substance is enforced by
      `programs/analog_a1_spec_extract_check.py` (`--block <name>`)
4. Write `analog/analog_block_list.json` (master list) — its fixed schema + `block_count`
   consistency + per-block `spec_file` resolution is enforced by
   `programs/analog_block_list_emit_check.py` (`--project <root>`)

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

## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/analog-spec-extract/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.

**Your task is not complete until the audit returns PASS.**
