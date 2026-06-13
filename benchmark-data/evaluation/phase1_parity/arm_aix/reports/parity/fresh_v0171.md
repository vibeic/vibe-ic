# Phase 1 extractor parity diff

_Emitted by `l_doc_parity_diff.py` (v0.1.51). Doctrine: program output should match fresh-agent output; any divergence is either a program gap or a hallucination._

## Overall

- ABSENT_IN_PROGRAM : 126
- HALLUCINATED      : 0
- VALUE_MISMATCH    : 29
- SHAPE_MISMATCH    : 0

## Per L-doc

| L doc | program-bytes | agent-bytes | absent | halluc | mismatch | shape | parity-% |
|---|---|---|---|---|---|---|---|
| L1_DATASHEET | 102407 | 7019 | 9 | 0 | 2 | 0 | 57.7 |
| L2_FRS | 116476 | 11652 | 7 | 0 | 1 | 0 | 27.3 |
| L3_CMD_PROTOCOL | 21889 | 8103 | 13 | 0 | 1 | 0 | 74.5 |
| L4_REGMAP | 821 | 1385 | 2 | 0 | 0 | 0 | 66.7 |
| L5_ADI_SPEC | 809 | 1738 | 2 | 0 | 0 | 0 | 80.0 |
| L6_CONTROL_LOGIC | 12747 | 4435 | 10 | 0 | 0 | 0 | 50.0 |
| L7_TEST_DEBUG | 822 | 3535 | 4 | 0 | 0 | 0 | 50.0 |
| L8_RTL_CONSTANTS | 23644 | 6486 | 36 | 0 | 0 | 0 | 61.3 |
| L8_TIMING_WAVEFORM | 676 | 4893 | 6 | 0 | 0 | 0 | 76.0 |
| L9_INTEGRATION_SPEC | 31469 | 7168 | 12 | 0 | 0 | 0 | 45.5 |
| L10_TEST_CASES | 2234 | 6383 | 2 | 0 | 0 | 0 | 60.0 |
| L11_OTP_CONTENT | 820 | 270 | 0 | 0 | 0 | 0 | 100.0 |
| L12_BEHAVIORAL_SEQUENCES | 2402 | 5924 | 8 | 0 | 0 | 0 | 50.0 |
| L13_LAB_CALIBRATION | 803 | 256 | 0 | 0 | 0 | 0 | 100.0 |
| L14_PROTOCOL_VERSIONING | 2117 | 8579 | 2 | 0 | 2 | 0 | 60.0 |
| L15_ENCODING_TABLES | 285126 | 17262 | 1 | 0 | 1 | 0 | 86.7 |
| L16_COMPLIANCE_PROPERTIES | 42948 | 20403 | 0 | 0 | 1 | 0 | 85.7 |
| L17_CHANNEL_SIGNAL_CATALOG | 10262 | 17313 | 1 | 0 | 9 | 0 | 65.5 |
| L18_INTERCONNECT_TOPOLOGY | 6354 | 14788 | 11 | 0 | 12 | 0 | 64.6 |
| L19_CONSTRAINTS_PDK | 564 | 0 | 0 | 0 | 0 | 0 | 100.0 |
| L20_DFT_SCAN_TOPOLOGY | 438 | 0 | 0 | 0 | 0 | 0 | 100.0 |
| L21_POWER_INTENT | 437 | 0 | 0 | 0 | 0 | 0 | 100.0 |
| L22_VERIFICATION_PLAN | 510 | 0 | 0 | 0 | 0 | 0 | 100.0 |
| L23_SECURITY_REQUIREMENTS | 442 | 0 | 0 | 0 | 0 | 0 | 100.0 |

## Missing from program (126 total, showing top 20)

- **L1_DATASHEET** `electrical_specs_rationale` — agent captured this top-level fact; program did not (R22 collapse: 1 finding per missing top-level key)
  - agent has: `Protocol spec defines only logical signal semantics (synchronous, sampled on rising edge of ACLK, ARESETn active-LOW). N`
- **L1_DATASHEET** `five_channels` — agent captured this top-level fact; program did not (R22 collapse: 1 finding per missing top-level key)
  - agent has: `[{'name': 'AR (Read Address)', 'direction': 'Master -> Slave'}, {'name': 'R  (Read Data)', 'direction': 'Slave -> Master`
- **L1_DATASHEET** `key_features` — agent captured this top-level fact; program did not (R22 collapse: 1 finding per missing top-level key)
  - agent has: `['Separate address/control and data phases', 'Unaligned data transfers via byte strobes', 'Burst-based transactions with`
- **L1_DATASHEET** `max_burst_length` — agent captured this top-level fact; program did not (R22 collapse: 1 finding per missing top-level key)
  - agent has: `{'AXI3': 16, 'AXI4_INCR': 256, 'AXI4_FIXED_WRAP': 16}`
- **L1_DATASHEET** `package_info_rationale` — agent captured this top-level fact; program did not (R22 collapse: 1 finding per missing top-level key)
  - agent has: `AXI is a bus protocol specification, not a packaged IC. No package/pinout/electrical-DC data exists in this document.`
- **L1_DATASHEET** `protocol_variants_described` — agent captured this top-level fact; program did not (R22 collapse: 1 finding per missing top-level key)
  - agent has: `['AXI3 (AMBA 3)', 'AXI4 (AMBA 4)', 'AXI4-Lite (AMBA 4)', 'AXI5 (AMBA 5)', 'AXI5-Lite (AMBA 5)', 'ACE (AMBA 4)', 'ACE-Lit`
- **L1_DATASHEET** `release_history` — agent captured this top-level fact; program did not (R22 collapse: 1 finding per missing top-level key)
  - agent has: `[{'date': '16 June 2003', 'issue': 'A', 'change': 'First release'}, {'date': '19 March 2004', 'issue': 'B', 'change': 'F`
- **L1_DATASHEET** `supported_interconnect_topologies` — agent captured this top-level fact; program did not (R22 collapse: 1 finding per missing top-level key)
  - agent has: `['Shared address and data buses', 'Shared address buses and multiple data buses', 'Multilayer, with multiple address and`
- **L1_DATASHEET** `vendor` — agent captured this top-level fact; program did not (R22 collapse: 1 finding per missing top-level key)
  - agent has: `Arm Limited, Company 02557590 registered in England, 110 Fulbourn Road, Cambridge, England CB1 9NJ`
- **L2_FRS** `error_response_conditions` — agent captured this top-level fact; program did not (R22 collapse: 1 finding per missing top-level key)
  - agent has: `['FIFO or buffer overrun/underrun', 'Unsupported transfer size attempted', 'Write access attempted to read-only location`
- **L2_FRS** `functional_requirements` — agent captured this top-level fact; program did not (R22 collapse: 1 finding per missing top-level key)
  - agent has: `[{'id': 'FR-HANDSHAKE-01', 'text': 'All five transaction channels use the same VALID/READY handshake. Source generates V`
- **L2_FRS** `protocol_overview.burst_based` — agent captured this fact; program did not
  - agent has: `True`
- **L2_FRS** `protocol_overview.out_of_order_completion` — agent captured this fact; program did not
  - agent has: `True`
- **L2_FRS** `protocol_overview.multiple_outstanding` — agent captured this fact; program did not
  - agent has: `True`
- **L2_FRS** `protocol_overview.atomicity_modes` — agent captured this fact; program did not
  - agent has: `['Normal', 'Exclusive', 'Locked (AXI3 only)']`
- **L2_FRS** `protocol_overview.endianness` — agent captured this fact; program did not
  - agent has: `byte-invariant (supports both little-endian and big-endian byte ordering in the same address space)`
- **L3_CMD_PROTOCOL** `burst_length_field` — agent captured this top-level fact; program did not (R22 collapse: 1 finding per missing top-level key)
  - agent has: `{'AxLEN_AXI3': {'bits': '[3:0]', 'burst_length_formula': 'AxLEN + 1', 'range': '1 to 16 transfers, all burst types'}, 'A`
- **L3_CMD_PROTOCOL** `cache_attribute_encoding_AXI3` — agent captured this top-level fact; program did not (R22 collapse: 1 finding per missing top-level key)
  - agent has: `{'AxCACHE[0]': 'Bufferable  (B)', 'AxCACHE[1]': 'Cacheable   (C) (renamed Modifiable in AXI4)', 'AxCACHE[2]': 'Read-Allo`
- **L3_CMD_PROTOCOL** `exclusive_access_restrictions` — agent captured this top-level fact; program did not (R22 collapse: 1 finding per missing top-level key)
  - agent has: `['Address must be aligned to (burst_size * burst_length).', 'Number of bytes must be a power of 2: 1,2,4,8,16,32,64,128.`
- **L3_CMD_PROTOCOL** `exclusive_access_sequence` — agent captured this top-level fact; program did not (R22 collapse: 1 finding per missing top-level key)
  - agent has: `['Master issues an exclusive read with some ARID at address X.', 'Slave that supports exclusive monitors X for that ARID`

## Value mismatches (29 total, showing top 20)

- **L1_DATASHEET** `ic_name`
  - program: `UNKNOWN_IC`
  - agent:   `AMBA AXI / ACE Protocol Specification`
- **L1_DATASHEET** `intended_audience`
  - program: `This specification is written for hardware and software engineers who want to be`
  - agent:   `Hardware and software engineers familiar with AMBA who want to design AXI-compat`
- **L2_FRS** `protocol_overview.wire_count`
  - program: `2`
  - agent:   `5 independent channels, each with VALID/READY pair`
- **L3_CMD_PROTOCOL** `channels`
  - program: `[{'name': 'AW', 'direction_majority': 'Master', 'signal_count': 13, 'signals': [`
  - agent:   `[{'name': 'AR (Read Address)', 'direction': 'Master -> Slave', 'signals': ['ARID`
- **L14_PROTOCOL_VERSIONING** `versions`
  - program: `[{'release_date': '16 June 2003', 'issue': 'A', 'change': 'First release'}, {'re`
  - agent:   `[{'release_date': '16 June 2003', 'issue': 'A', 'change': 'First release'}, {'re`
- **L14_PROTOCOL_VERSIONING** `deprecated_features`
  - program: `[{'feature': 'but', 'quote': 'The interleaving of write data with different IDs `
  - agent:   `[{'feature': 'WID (Write data ID tag)', 'deprecated_in_version': 'AXI4', 'ration`
- **L15_ENCODING_TABLES** `tables`
  - program: `[{'table_id': 'Table A2-1', 'name': 'Global signals', 'line': 1329, 'rows': ['Si`
  - agent:   `[{'table_id': 'Table A3-2', 'name': 'Burst size encoding', 'field_bits': 'AxSIZE`
- **L16_COMPLIANCE_PROPERTIES** `properties`
  - program: `[{'anchor_token': 'shall', 'english_form': 'Agreement shall prevail.', 'line': 1`
  - agent:   `[{'id': 'p_4kb_boundary', 'scope': 'AR_channel, AW_channel', 'english_form': 'A `
- **L17_CHANNEL_SIGNAL_CATALOG** `channels`
  - program: `[{'name': 'AW', 'direction_majority': 'Master', 'signal_count': 13, 'signals': [`
  - agent:   `[{'name': 'AW', 'full_name': 'Write Address Channel', 'direction': 'Master to Sl`
- **L17_CHANNEL_SIGNAL_CATALOG** `global_signals`
  - program: `[{'name': 'ACLK', 'direction': 'Global', 'semantics': 'source     Global clock s`
  - agent:   `[{'name': 'ACLK', 'width': '1', 'direction': 'Clock source -> all', 'semantics':`
- **L17_CHANNEL_SIGNAL_CATALOG** `channel_counts.signals_per_channel.R`
  - program: `6`
  - agent:   `7`
- **L17_CHANNEL_SIGNAL_CATALOG** `channel_counts.total_signals_excluding_global`
  - program: `44`
  - agent:   `45`
- **L17_CHANNEL_SIGNAL_CATALOG** `channel_counts.total_signals_including_ACLK_ARESETn`
  - program: `46`
  - agent:   `47`
- **L17_CHANNEL_SIGNAL_CATALOG** `dependency_graph.common_rule`
  - program: `VALID once asserted MUST remain asserted until READY also asserted on the same c`
  - agent:   `VALID must not depend (combinationally) on READY. A source may not wait for READ`
- **L17_CHANNEL_SIGNAL_CATALOG** `dependency_graph.AXI3_write`
  - program: `AWVALID and WVALID independent; BVALID does NOT wait for AW handshake`
  - agent:   `AWVALID and WVALID asserted independently of AWREADY/WREADY. Slave must wait for`
- **L17_CHANNEL_SIGNAL_CATALOG** `dependency_graph.AXI4_write`
  - program: `BVALID waits for both AW (AWVALID && AWREADY) and W (WVALID && WREADY && WLAST) `
  - agent:   `AWVALID and WVALID asserted independently of AWREADY/WREADY. Slave must wait for`
- **L17_CHANNEL_SIGNAL_CATALOG** `dependency_graph.AXI_read`
  - program: `ARVALID precedes RVALID; RVALID stays asserted until ARREADY accepted and final `
  - agent:   `ARVALID asserted independently of ARREADY. Slave must wait for both ARVALID and `
- **L18_INTERCONNECT_TOPOLOGY** `interconnect_rules`
  - program: `[{'rule': 'from the same master completes. An arbiter within the interconnect mu`
  - agent:   `['Interconnect must realign the address and write data when determining the dest`
- **L18_INTERCONNECT_TOPOLOGY** `default_signal_values.BID`
  - program: `Required (no default)`
  - agent:   `Optional (no default driven from slave when omitted at master)`
- **L18_INTERCONNECT_TOPOLOGY** `default_signal_values.BRESP`
  - program: `Required (no default)`
  - agent:   `0b00 (OKAY) — only as memory-slave default when not driven`
