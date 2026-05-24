# IC Expert Schema & Lessons — L2

## Schema (REQUIRED top-level keys, benchmark-derived)

Target filename: `L2_FRS.json`

The output JSON **must** have exactly these top-level keys, in this order:

| Key | Type |
|-----|------|
| `document_id` | string |
| `ic_name` | string |
| `generated_by` | string |
| `source_documents` | list of strings (len 2) |
| `functional_requirements` | list of dicts (len 9) |
| `performance_requirements` | dict (keys: wake_time_us, rx_to_tx_latency_us_max, osc_freq_after_trim_mhz) |
| `interface_requirements` | dict (keys: id_bus, cc, otp) |

**Forbidden**: do NOT add extra top-level keys (e.g., `compliance`, `references`, `channels`, `power_domains`, `notes`, `top_module`). The extractor expects this exact schema.
