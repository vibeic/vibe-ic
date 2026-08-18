# IC Expert Schema & Lessons — L8R

## Schema (REQUIRED top-level keys, benchmark-derived)

Target filename: `L8_RTL_CONSTANTS.json`

The output JSON **must** have exactly these top-level keys, in this order:

| Key | Type |
|-----|------|
| `document_id` | string |
| `ic_name` | string |
| `generated_by` | string |
| `clock_frequency_hz` | integer |
| `bit_period_cycles` | integer |
| `bit0_threshold_cycles` | integer |
| `bit1_threshold_cycles` | integer |
| `wake_low_min_cycles` | integer |
| `break_low_min_cycles` | integer |
| `inter_byte_gap_min_cycles` | integer |
| `rx_to_tx_delay_min_cycles` | integer |
| `rx_to_tx_delay_max_cycles` | integer |
| `por_debounce_cycles` | integer |
| `crc8_polynomial` | string |
| `crc8_init` | string |
| `otp_read_access_cycles` | integer |
| `otp_program_pulse_cycles` | integer |
| `signature_bytes` | list of strings (len 9) |

**Forbidden**: do NOT add extra top-level keys (e.g., `compliance`, `references`, `channels`, `power_domains`, `notes`, `top_module`). The extractor expects this exact schema.
