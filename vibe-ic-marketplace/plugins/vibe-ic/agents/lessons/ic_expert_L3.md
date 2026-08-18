# IC Expert Schema & Lessons — L3

## Schema (REQUIRED top-level keys, benchmark-derived)

Target filename: `L3_CMD_PROTOCOL.json`

The output JSON **must** have exactly these top-level keys, in this order:

| Key | Type |
|-----|------|
| `document_id` | string |
| `ic_name` | string |
| `generated_by` | string |
| `source_documents` | list of strings (len 3) |
| `protocol_name` | string |
| `frame_format` | dict (keys: wake, break, start_bit, bit_encoding, byte_order, crc) |
| `command_set` | list of dicts (len 5) |
| `md905_signature_response` | string |

**Forbidden**: do NOT add extra top-level keys (e.g., `compliance`, `references`, `channels`, `power_domains`, `notes`, `top_module`). The extractor expects this exact schema.
