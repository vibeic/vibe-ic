# Phase-1 Fact-Graph Provenance Audit

- IC: **U_Hawaii_EE628_DeltaSigma_ADC**
- Class: `analog-front-end`
- Total facts: 11

| uuid | path | source | origin | auto_decided | reasoning |
|------|------|--------|--------|--------------|-----------|
| `f-c61dac23` | `L1.channel_count` | inferred | nl_ingest | True | extracted from user's natural-language description |
| `f-921be0d6` | `L1.converter_type` | inferred | nl_ingest | True | extracted from user's natural-language description |
| `f-86ceaa96` | `L1.physical.die_size_um` | inferred | nl_ingest | True | extracted from user's natural-language description |
| `f-182ccc46` | `L1.physical.seal_ring_included` | inferred | nl_ingest | True | extracted from user's natural-language description |
| `f-cdd7e19e` | `L1.process.pdk` | inferred | nl_ingest | True | extracted from user's natural-language description |
| `f-aef26c2a` | `L1.project.affiliation` | inferred | nl_ingest | True | extracted from user's natural-language description |
| `f-82c30237` | `L1.project.source_url` | inferred | nl_ingest | True | extracted from user's natural-language description |
| `f-b81a8911` | `L1.project.tapeout_date` | inferred | nl_ingest | True | extracted from user's natural-language description |
| `f-4003f032` | `L9.instances.modulator_count` | inferred | nl_ingest | True | extracted from user's natural-language description |
| `f-9ab2b8de` | `L9.instances.modulator_with_ldo_count` | inferred | nl_ingest | True | extracted from user's natural-language description |
| `f-5c5a483a` | `L9.power_domains` | inferred | nl_ingest | True | extracted from user's natural-language description |

## WARN_INSUFFICIENT_REQUIRED_FIELDS

_required_facts_satisfied_pct = 0.19 (3 / 16 satisfied)_

Phase 2b's `phase1_doc_presence_check` and downstream hard-gates expect 100% required-fact coverage. The following required facts had no textual support in the input prompt / docs:

### L1
  - `L1.differential_capable`
  - `L1.input_voltage_range_v`

### L2
  - `L2.digital_interface`
  - `L2.power_modes`

### L3
  - `L3.protocol_present`

### L4
  - `L4.pointer_register_present`
  - `L4.register_map`

### L5
  - `L5.alert_pin_present`
  - `L5.reference_source`

### L6
  - `L6.submodule_control_logic`

### L8
  - `L8.conversion_timing`

### L8R
  - `L8R.clock_frequency_hz`

### L9
  - `L9.pad_list`

