# IC Expert Schema & Lessons — L9

## Schema (REQUIRED top-level keys, benchmark-derived)

Target filename: `L9_INTEGRATION_SPEC.json`

The output JSON **must** have exactly these top-level keys, in this order:

| Key | Type |
|-----|------|
| `document_id` | string |
| `document_version` | string |
| `ic_name` | string |
| `description` | string |
| `generated_from` | list of strings (len 12) |
| `dtop_top_level` | dict (keys: module_name, description, ports) |
| `submodules` | dict (keys: PAD_CTRL, DCLK, DRST, RX_PHY, TX_PHY, MAC, CRC8, RX_CHK...) |
| `internal_wire_map` | dict (keys: description, wires, total_internal_wires, total_wire_bits) |
| `register_set_clear_logic` | dict (keys: description, reg_PH, reg_PT, reg_RD_DIS, reg_cc_pd_on, reg_TEST, reg_AWAKE) |
| `analog_output_assignments` | dict (keys: description, assignments) |
| `instantiation_order` | dict (keys: description, order) |

**Forbidden**: do NOT add extra top-level keys (e.g., `compliance`, `references`, `channels`, `power_domains`, `notes`, `top_module`). The extractor expects this exact schema.
