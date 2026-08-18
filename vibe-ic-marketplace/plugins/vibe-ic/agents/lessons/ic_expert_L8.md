# IC Expert Schema & Lessons — L8

## Schema (REQUIRED top-level keys, benchmark-derived)

Target filename: `L8_TIMING_WAVEFORM.json`

The output JSON **must** have exactly these top-level keys, in this order:

| Key | Type |
|-----|------|
| `document_id` | string |
| `ic_name` | string |
| `generated_by` | string |
| `source_documents` | list of strings (len 3) |
| `aid_bit_timing` | dict (keys: bit_period_us, bit0_low_us, bit1_low_us, sampling_point_us_from_falling_edge, inter_byte_gap_us) |
| `wake_timing` | dict (keys: wake_low_min_us, wake_low_max_us, wake_to_first_bit_us) |
| `break_timing` | dict (keys: break_low_min_us) |
| `response_timing` | dict (keys: rx_to_tx_delay_us_min, rx_to_tx_delay_us_max) |
| `reset_timing` | dict (keys: por_to_clk_valid_us, por_to_first_wake_ready_us) |

**Forbidden**: do NOT add extra top-level keys (e.g., `compliance`, `references`, `channels`, `power_domains`, `notes`, `top_module`). The extractor expects this exact schema.
