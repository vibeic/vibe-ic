# IC Expert Schema & Lessons — L5 (Analog-Digital Interface)

> **L5 "ADI" = ANALOG-DIGITAL INTERFACE** — the analog↔digital boundary spec
> (ADC/DAC interfaces, mixed-signal pads, PHY analog front-end, reference
> voltages, sense/trim/test pads). It is a **functional layer**, **NOT** the
> vendor *Analog Devices Inc.* (the acronym collides). For a pure-digital design
> this layer is correctly **empty**.

## Schema (REQUIRED top-level keys, benchmark-derived)

Target filename: `L5_ADI_SPEC.json`  (human title: *Analog-Digital Interface*)

The output JSON **must** have exactly these top-level keys, in this order:

| Key | Type |
|-----|------|
| `document_id` | string |
| `ic_name` | string |
| `generated_by` | string |
| `source_documents` | list of strings (len 3) |
| `analog_digital_interfaces` | list of dicts (len 18) |
| `timing_notes` | string |

**Forbidden**: do NOT add extra top-level keys (e.g., `compliance`, `references`, `channels`, `power_domains`, `notes`, `top_module`). The extractor expects this exact schema.
