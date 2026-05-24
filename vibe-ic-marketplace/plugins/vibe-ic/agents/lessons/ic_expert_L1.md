# IC Expert Schema & Lessons — L1

## Schema (REQUIRED top-level keys, benchmark-derived)

Target filename: `L1_DATASHEET.json`

The output JSON **must** have exactly these top-level keys, in this order:

| Key | Type |
|-----|------|
| `document_id` | string |
| `ic_name` | string |
| `generated_by` | string |
| `source_documents` | list of strings (len 5) |
| `overview` | dict (keys: purpose, key_features, package, process_node_fpga, process_node_asic) |
| `electrical_characteristics` | dict (keys: supply_vbus, supply_1v8, osc_freq, id_bus_vil, id_bus_vih, id_bus_drive_strength_ma) |
| `pinout` | dict (keys: VBUS, ID_BUS, CC_I, CC_O, OUT1, GND) |
| `protocol_summary` | string |

**Forbidden**: do NOT add extra top-level keys (e.g., `compliance`, `references`, `channels`, `power_domains`, `notes`, `top_module`). The extractor expects this exact schema.
