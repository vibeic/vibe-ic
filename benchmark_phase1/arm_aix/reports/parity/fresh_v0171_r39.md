# Phase 1 extractor parity diff

_Emitted by `l_doc_parity_diff.py` (v0.1.51). Doctrine: program output should match fresh-agent output; any divergence is either a program gap or a hallucination._

## Overall

- ABSENT_IN_PROGRAM : 99
- HALLUCINATED      : 0
- VALUE_MISMATCH    : 11
- SHAPE_MISMATCH    : 18

## Per L-doc

| L doc | program-bytes | agent-bytes | absent | halluc | mismatch | shape | parity-% |
|---|---|---|---|---|---|---|---|
| L1_DATASHEET | 102407 | 7019 | 9 | 0 | 1 | 1 | 57.7 |
| L2_FRS | 116476 | 11652 | 3 | 0 | 1 | 1 | 54.5 |
| L3_CMD_PROTOCOL | 21889 | 8103 | 13 | 0 | 0 | 1 | 74.5 |
| L4_REGMAP | 821 | 1385 | 2 | 0 | 0 | 1 | 50.0 |
| L5_ADI_SPEC | 809 | 1738 | 2 | 0 | 0 | 1 | 70.0 |
| L6_CONTROL_LOGIC | 12747 | 4435 | 10 | 0 | 0 | 1 | 45.0 |
| L7_TEST_DEBUG | 822 | 3535 | 4 | 0 | 0 | 1 | 37.5 |
| L8_RTL_CONSTANTS | 23644 | 6486 | 17 | 0 | 0 | 1 | 80.6 |
| L8_TIMING_WAVEFORM | 676 | 4893 | 6 | 0 | 0 | 1 | 72.0 |
| L9_INTEGRATION_SPEC | 31469 | 7168 | 12 | 0 | 0 | 1 | 40.9 |
| L10_TEST_CASES | 2234 | 6383 | 2 | 0 | 0 | 1 | 40.0 |
| L11_OTP_CONTENT | 820 | 270 | 0 | 0 | 0 | 0 | 100.0 |
| L12_BEHAVIORAL_SEQUENCES | 2402 | 5924 | 8 | 0 | 0 | 1 | 43.8 |
| L13_LAB_CALIBRATION | 803 | 256 | 0 | 0 | 0 | 0 | 100.0 |
| L14_PROTOCOL_VERSIONING | 2117 | 8579 | 2 | 0 | 0 | 1 | 70.0 |
| L15_ENCODING_TABLES | 285126 | 17262 | 1 | 0 | 0 | 1 | 86.7 |
| L16_COMPLIANCE_PROPERTIES | 42948 | 20403 | 0 | 0 | 0 | 0 | 100.0 |
| L17_CHANNEL_SIGNAL_CATALOG | 10262 | 17313 | 1 | 0 | 7 | 1 | 69.0 |
| L18_INTERCONNECT_TOPOLOGY | 6354 | 14788 | 7 | 0 | 2 | 1 | 84.6 |
| L19_CONSTRAINTS_PDK | 564 | 0 | 0 | 0 | 0 | 1 | 0.0 |
| L20_DFT_SCAN_TOPOLOGY | 438 | 0 | 0 | 0 | 0 | 0 | 100.0 |
| L21_POWER_INTENT | 437 | 0 | 0 | 0 | 0 | 0 | 100.0 |
| L22_VERIFICATION_PLAN | 510 | 0 | 0 | 0 | 0 | 1 | 0.0 |
| L23_SECURITY_REQUIREMENTS | 442 | 0 | 0 | 0 | 0 | 0 | 100.0 |

## Missing from program (99 total, showing top 20)

- **L1_DATASHEET** `release_history` — agent captured this fact / sibling-extras; program did not
  - agent has: `[{'date': '16 June 2003', 'issue': 'A', 'change': 'First release'}, {'date': '19 March 2004', 'issue': 'B', 'change': 'F`
- **L1_DATASHEET** `protocol_variants_described` — agent captured this fact / sibling-extras; program did not
  - agent has: `['AXI3 (AMBA 3)', 'AXI4 (AMBA 4)', 'AXI4-Lite (AMBA 4)', 'AXI5 (AMBA 5)', 'AXI5-Lite (AMBA 5)', 'ACE (AMBA 4)', 'ACE-Lit`
- **L1_DATASHEET** `key_features` — agent captured this fact / sibling-extras; program did not
  - agent has: `['Separate address/control and data phases', 'Unaligned data transfers via byte strobes', 'Burst-based transactions with`
- **L1_DATASHEET** `five_channels` — agent captured this fact / sibling-extras; program did not
  - agent has: `[{'name': 'AR (Read Address)', 'direction': 'Master -> Slave'}, {'name': 'R  (Read Data)', 'direction': 'Slave -> Master`
- **L1_DATASHEET** `supported_interconnect_topologies` — agent captured this fact / sibling-extras; program did not
  - agent has: `['Shared address and data buses', 'Shared address buses and multiple data buses', 'Multilayer, with multiple address and`
- **L1_DATASHEET** `max_burst_length` — agent captured this fact / sibling-extras; program did not
  - agent has: `{'AXI3': 16, 'AXI4_INCR': 256, 'AXI4_FIXED_WRAP': 16}`
- **L1_DATASHEET** `vendor` — agent captured this fact / sibling-extras; program did not
  - agent has: `Arm Limited, Company 02557590 registered in England, 110 Fulbourn Road, Cambridge, England CB1 9NJ`
- **L1_DATASHEET** `package_info_rationale` — agent captured this fact / sibling-extras; program did not
  - agent has: `AXI is a bus protocol specification, not a packaged IC. No package/pinout/electrical-DC data exists in this document.`
- **L1_DATASHEET** `electrical_specs_rationale` — agent captured this fact / sibling-extras; program did not
  - agent has: `Protocol spec defines only logical signal semantics (synchronous, sampled on rising edge of ACLK, ARESETn active-LOW). N`
- **L2_FRS** `functional_requirements` — agent captured this fact / sibling-extras; program did not
  - agent has: `[{'id': 'FR-HANDSHAKE-01', 'text': 'All five transaction channels use the same VALID/READY handshake. Source generates V`
- **L2_FRS** `error_response_conditions` — agent captured this fact / sibling-extras; program did not
  - agent has: `['FIFO or buffer overrun/underrun', 'Unsupported transfer size attempted', 'Write access attempted to read-only location`
- **L2_FRS** `protocol_overview.<sibling-extras>` — agent captured this fact / sibling-extras; program did not
  - agent has: `{'extra_agent_subkeys': ['atomicity_modes', 'burst_based', 'endianness', 'multiple_outstanding', 'out_of_order_completio`
- **L3_CMD_PROTOCOL** `burst_length_field` — agent captured this fact / sibling-extras; program did not
  - agent has: `{'AxLEN_AXI3': {'bits': '[3:0]', 'burst_length_formula': 'AxLEN + 1', 'range': '1 to 16 transfers, all burst types'}, 'A`
- **L3_CMD_PROTOCOL** `response_encodings` — agent captured this fact / sibling-extras; program did not
  - agent has: `{'RRESP[1:0] / BRESP[1:0]': {'0b00': 'OKAY    - normal access success (or exclusive failed)', '0b01': 'EXOKAY  - exclusi`
- **L3_CMD_PROTOCOL** `lock_encodings` — agent captured this fact / sibling-extras; program did not
  - agent has: `{'AXI3_AxLOCK[1:0]': {'0b00': 'Normal access', '0b01': 'Exclusive access', '0b10': 'Locked access', '0b11': 'Reserved'},`
- **L3_CMD_PROTOCOL** `cache_attribute_encoding_AXI3` — agent captured this fact / sibling-extras; program did not
  - agent has: `{'AxCACHE[0]': 'Bufferable  (B)', 'AxCACHE[1]': 'Cacheable   (C) (renamed Modifiable in AXI4)', 'AxCACHE[2]': 'Read-Allo`
- **L3_CMD_PROTOCOL** `protection_attribute_encoding` — agent captured this fact / sibling-extras; program did not
  - agent has: `{'AxPROT[0]': {'0': 'Unprivileged access', '1': 'Privileged access'}, 'AxPROT[1]': {'0': 'Secure access', '1': 'Non-secu`
- **L3_CMD_PROTOCOL** `qos` — agent captured this fact / sibling-extras; program did not
  - agent has: `{'AxQOS': '4-bit Quality of Service identifier. Default 0b0000 = not participating. Higher value = higher priority (reco`
- **L3_CMD_PROTOCOL** `region` — agent captured this fact / sibling-extras; program did not
  - agent has: `{'AxREGION': '4-bit region identifier; up to 16 logical regions; must remain constant within any 4KB space.', 'added_in'`
- **L3_CMD_PROTOCOL** `valid_ready_handshake_rules` — agent captured this fact / sibling-extras; program did not
  - agent has: `['Transfer occurs only when both VALID and READY are HIGH at a rising ACLK edge.', 'Once VALID is asserted, it must rema`

## Value mismatches (11 total, showing top 20)

- **L1_DATASHEET** `intended_audience`
  - program: `This specification is written for hardware and software engineers who want to be`
  - agent:   `Hardware and software engineers familiar with AMBA who want to design AXI-compat`
- **L2_FRS** `protocol_overview.wire_count`
  - program: `2`
  - agent:   `5 independent channels, each with VALID/READY pair`
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
- **L18_INTERCONNECT_TOPOLOGY** `multi_copy_atomicity.english`
  - program: `Once a write is observed by one observer, all observers must see it (no write co`
  - agent:   `A system is multi-copy atomic iff (a) writes to the same location are observed i`
- **L18_INTERCONNECT_TOPOLOGY** `id_routing.description`
  - program: `Interconnect may append bits to AxID to identify the originating master; slave-s`
  - agent:   `Slave-side ID_WIDTH > master-side ID_WIDTH. The interconnect appends additional `
