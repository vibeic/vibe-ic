# IC Expert Schema & Lessons — L7

## Schema (REQUIRED top-level keys, benchmark-derived)

Target filename: `L7_TEST_DEBUG.json`

The output JSON **must** have exactly these top-level keys, in this order:

| Key | Type |
|-----|------|
| `document_id` | string |
| `ic_name` | string |
| `generated_by` | string |
| `source_documents` | list of strings (len 3) |
| `test_modes` | list of dicts (len 3) |
| `md905_test_sequence` | list of strings (len 5) |
| `debug_hooks` | list of strings (len 1) |

**Forbidden**: do NOT add extra top-level keys (e.g., `compliance`, `references`, `channels`, `power_domains`, `notes`, `top_module`). The extractor expects this exact schema.
