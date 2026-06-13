# IC Expert Schema & Lessons — L6

## Schema (REQUIRED top-level keys, benchmark-derived)

Target filename: `L6_CONTROL_LOGIC.json`

The output JSON **must** have exactly these top-level keys, in this order:

| Key | Type |
|-----|------|
| `document_id` | string |
| `ic_name` | string |
| `generated_by` | string |
| `source_documents` | list of strings (len 4) |
| `submodule_control_logic` | dict (keys: mac, rx_phy, rx_cmd, rx_chk, tx_phy, crc8, otp_ctrl, dclk...) |

**Forbidden**: do NOT add extra top-level keys (e.g., `compliance`, `references`, `channels`, `power_domains`, `notes`, `top_module`). The extractor expects this exact schema.
