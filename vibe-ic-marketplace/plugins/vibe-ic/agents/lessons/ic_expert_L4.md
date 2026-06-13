# IC Expert Schema & Lessons — L4

## Schema (REQUIRED top-level keys, benchmark-derived)

Target filename: `L4_REGMAP.json`

The output JSON **must** have exactly these top-level keys, in this order:

| Key | Type |
|-----|------|
| `document_id` | string |
| `ic_name` | string |
| `generated_by` | string |
| `source_documents` | list of strings (len 3) |
| `otp_map_128x8` | list of dicts (len 7) |
| `control_registers_logical` | list of dicts (len 2) |

**Forbidden**: do NOT add extra top-level keys (e.g., `compliance`, `references`, `channels`, `power_domains`, `notes`, `top_module`). The extractor expects this exact schema.
