# Phase 1 extractor parity diff

_Emitted by `l_doc_parity_diff.py` (v0.1.51). Doctrine: program output should match fresh-agent output; any divergence is either a program gap or a hallucination._

## Overall

- ABSENT_IN_PROGRAM : 336
- HALLUCINATED      : 0
- VALUE_MISMATCH    : 56
- SHAPE_MISMATCH    : 24

## Per L-doc

| L doc | program-bytes | agent-bytes | absent | halluc | mismatch | shape | parity-% |
|---|---|---|---|---|---|---|---|
| L1_DATASHEET | 101302 | 7019 | 26 | 0 | 0 | 1 | 0.0 |
| L2_FRS | 116318 | 11652 | 11 | 0 | 0 | 1 | 0.0 |
| L3_CMD_PROTOCOL | 11705 | 8103 | 55 | 0 | 0 | 1 | 0.0 |
| L4_REGMAP | 243 | 1385 | 5 | 0 | 0 | 1 | 0.0 |
| L5_ADI_SPEC | 229 | 1738 | 9 | 0 | 0 | 1 | 0.0 |
| L6_CONTROL_LOGIC | 12408 | 4435 | 20 | 0 | 0 | 1 | 0.0 |
| L7_TEST_DEBUG | 240 | 3535 | 7 | 0 | 0 | 1 | 0.0 |
| L8_RTL_CONSTANTS | 1095 | 6486 | 93 | 0 | 0 | 1 | 0.0 |
| L8_TIMING_WAVEFORM | 284 | 4893 | 25 | 0 | 0 | 1 | 0.0 |
| L9_INTEGRATION_SPEC | 31076 | 7168 | 22 | 0 | 0 | 1 | 0.0 |
| L10_TEST_CASES | 1732 | 6383 | 5 | 0 | 0 | 1 | 0.0 |
| L11_OTP_CONTENT | 204 | 270 | 1 | 0 | 1 | 1 | 25.0 |
| L12_BEHAVIORAL_SEQUENCES | 1884 | 5924 | 16 | 0 | 0 | 1 | 0.0 |
| L13_LAB_CALIBRATION | 214 | 256 | 1 | 0 | 1 | 1 | 25.0 |
| L14_PROTOCOL_VERSIONING | 4127 | 8579 | 3 | 0 | 3 | 1 | 30.0 |
| L15_ENCODING_TABLES | 314830 | 17262 | 9 | 0 | 2 | 1 | 20.0 |
| L16_COMPLIANCE_PROPERTIES | 71097 | 20403 | 1 | 0 | 2 | 1 | 42.9 |
| L17_CHANNEL_SIGNAL_CATALOG | 18262 | 17313 | 10 | 0 | 10 | 1 | 27.6 |
| L18_INTERCONNECT_TOPOLOGY | 21698 | 14788 | 17 | 0 | 37 | 1 | 15.4 |
| L19_CONSTRAINTS_PDK | 552 | 0 | 0 | 0 | 0 | 1 | 0.0 |
| L20_DFT_SCAN_TOPOLOGY | 248 | 0 | 0 | 0 | 0 | 1 | 0.0 |
| L21_POWER_INTENT | 247 | 0 | 0 | 0 | 0 | 1 | 0.0 |
| L22_VERIFICATION_PLAN | 498 | 0 | 0 | 0 | 0 | 1 | 0.0 |
| L23_SECURITY_REQUIREMENTS | 252 | 0 | 0 | 0 | 0 | 1 | 0.0 |

## Missing from program (336 total, showing top 20)

- **L1_DATASHEET** `doc_id` — agent captured this fact; program did not
  - agent has: `L1`
- **L1_DATASHEET** `extraction_source` — agent captured this fact; program did not
  - agent has: `claude-opus-4.7-fresh-2026-05-29`
- **L1_DATASHEET** `fields.ic_name` — agent captured this fact; program did not
  - agent has: `AMBA AXI / ACE Protocol Specification`
- **L1_DATASHEET** `fields.document_id` — agent captured this fact; program did not
  - agent has: `ARM IHI 0022H (ID040120)`
- **L1_DATASHEET** `fields.issuer` — agent captured this fact; program did not
  - agent has: `Arm Limited`
- **L1_DATASHEET** `fields.copyright` — agent captured this fact; program did not
  - agent has: `Copyright (c) 2003-2020 Arm Limited or its affiliates`
- **L1_DATASHEET** `fields.confidentiality` — agent captured this fact; program did not
  - agent has: `Non-Confidential`
- **L1_DATASHEET** `fields.release_history` — agent captured this fact; program did not
  - agent has: `[{'date': '16 June 2003', 'issue': 'A', 'change': 'First release'}, {'date': '19 March 2004', 'issue': 'B', 'change': 'F`
- **L1_DATASHEET** `fields.protocol_variants_described` — agent captured this fact; program did not
  - agent has: `['AXI3 (AMBA 3)', 'AXI4 (AMBA 4)', 'AXI4-Lite (AMBA 4)', 'AXI5 (AMBA 5)', 'AXI5-Lite (AMBA 5)', 'ACE (AMBA 4)', 'ACE-Lit`
- **L1_DATASHEET** `fields.purpose` — agent captured this fact; program did not
  - agent has: `Defines the AMBA AXI/ACE on-chip bus protocols for high-performance, high-frequency master-slave communication, suitable`
- **L1_DATASHEET** `fields.key_features` — agent captured this fact; program did not
  - agent has: `['Separate address/control and data phases', 'Unaligned data transfers via byte strobes', 'Burst-based transactions with`
- **L1_DATASHEET** `fields.five_channels` — agent captured this fact; program did not
  - agent has: `[{'name': 'AR (Read Address)', 'direction': 'Master -> Slave'}, {'name': 'R  (Read Data)', 'direction': 'Slave -> Master`
- **L1_DATASHEET** `fields.supported_data_bus_widths_bits` — agent captured this fact; program did not
  - agent has: `[8, 16, 32, 64, 128, 256, 512, 1024]`
- **L1_DATASHEET** `fields.supported_interconnect_topologies` — agent captured this fact; program did not
  - agent has: `['Shared address and data buses', 'Shared address buses and multiple data buses', 'Multilayer, with multiple address and`
- **L1_DATASHEET** `fields.endianness` — agent captured this fact; program did not
  - agent has: `byte-invariant; both little-endian and big-endian components can coexist in a single memory space`
- **L1_DATASHEET** `fields.max_burst_length.AXI3` — agent captured this fact; program did not
  - agent has: `16`
- **L1_DATASHEET** `fields.max_burst_length.AXI4_INCR` — agent captured this fact; program did not
  - agent has: `256`
- **L1_DATASHEET** `fields.max_burst_length.AXI4_FIXED_WRAP` — agent captured this fact; program did not
  - agent has: `16`
- **L1_DATASHEET** `fields.burst_boundary_rule` — agent captured this fact; program did not
  - agent has: `A burst must not cross a 4KB address boundary`
- **L1_DATASHEET** `fields.intended_audience` — agent captured this fact; program did not
  - agent has: `Hardware and software engineers familiar with AMBA who want to design AXI-compatible systems and modules`

## Value mismatches (56 total, showing top 20)

- **L11_OTP_CONTENT** `rationale`
  - program: `No OTP fuses`
  - agent:   `AXI is a bus/interconnect protocol; it has no one-time-programmable fuses, no fa`
- **L13_LAB_CALIBRATION** `rationale`
  - program: `No lab calibration`
  - agent:   `AXI is a digital bus protocol with no analog content, no measurement-based calib`
- **L14_PROTOCOL_VERSIONING** `fields.versions`
  - program: `[{'release_date': '16 June 2003', 'issue': 'A', 'change': 'First release'}, {'re`
  - agent:   `[{'release_date': '16 June 2003', 'issue': 'A', 'change': 'First release'}, {'re`
- **L14_PROTOCOL_VERSIONING** `fields.deprecated_features`
  - program: `[{'feature': 'but', 'quote': 'The interleaving of write data with different IDs `
  - agent:   `[{'feature': 'WID (Write data ID tag)', 'deprecated_in_version': 'AXI4', 'ration`
- **L14_PROTOCOL_VERSIONING** `evidence`
  - program: `[{'line': 27, 'quote': '16 June 2003          A         Non-Confidential        `
  - agent:   `[{'spec_page': 'ii (front matter)', 'spec_section': 'Change history', 'quote': '`
- **L15_ENCODING_TABLES** `fields.tables`
  - program: `[{'table_id': 'Table A2-1', 'name': 'Global signals', 'line': 1329, 'rows': ['Si`
  - agent:   `[{'table_id': 'Table A3-2', 'name': 'Burst size encoding', 'field_bits': 'AxSIZE`
- **L15_ENCODING_TABLES** `evidence`
  - program: `[{'line': 1329, 'quote': 'Table A2-1 Global signals', 'table': 'Table A2-1'}, {'`
  - agent:   `[{'spec_page': 'A3-49', 'spec_section': 'A3.4 Burst size', 'quote': 'Table A3-2 `
- **L16_COMPLIANCE_PROPERTIES** `fields.properties`
  - program: `[{'anchor_token': 'shall', 'english_form': 'Agreement shall prevail.', 'line': 1`
  - agent:   `[{'id': 'p_4kb_boundary', 'scope': 'AR_channel, AW_channel', 'english_form': 'A `
- **L16_COMPLIANCE_PROPERTIES** `evidence`
  - program: `[{'line': 102, 'quote': 'Agreement shall prevail.'}, {'line': 134, 'quote': 'con`
  - agent:   `[{'spec_page': 'A3-40', 'spec_section': 'A3.1.2 Reset', 'quote': 'During reset a`
- **L17_CHANNEL_SIGNAL_CATALOG** `fields.channels`
  - program: `[{'name': 'AW', 'direction_majority': 'Master', 'signal_count': 13, 'signals': [`
  - agent:   `[{'name': 'AW', 'full_name': 'Write Address Channel', 'direction': 'Master to Sl`
- **L17_CHANNEL_SIGNAL_CATALOG** `fields.global_signals`
  - program: `[{'name': 'ACLK', 'direction': 'Global', 'semantics': 'source     Global clock s`
  - agent:   `[{'name': 'ACLK', 'width': '1', 'direction': 'Clock source -> all', 'semantics':`
- **L17_CHANNEL_SIGNAL_CATALOG** `fields.channel_counts.signals_per_channel.R`
  - program: `6`
  - agent:   `7`
- **L17_CHANNEL_SIGNAL_CATALOG** `fields.channel_counts.total_signals_excluding_global`
  - program: `44`
  - agent:   `45`
- **L17_CHANNEL_SIGNAL_CATALOG** `fields.channel_counts.total_signals_including_ACLK_ARESETn`
  - program: `46`
  - agent:   `47`
- **L17_CHANNEL_SIGNAL_CATALOG** `fields.dependency_graph.common_rule`
  - program: `VALID once asserted MUST remain asserted until READY also asserted on the same c`
  - agent:   `VALID must not depend (combinationally) on READY. A source may not wait for READ`
- **L17_CHANNEL_SIGNAL_CATALOG** `fields.dependency_graph.AXI3_write`
  - program: `AWVALID and WVALID independent; BVALID does NOT wait for AW handshake`
  - agent:   `AWVALID and WVALID asserted independently of AWREADY/WREADY. Slave must wait for`
- **L17_CHANNEL_SIGNAL_CATALOG** `fields.dependency_graph.AXI4_write`
  - program: `BVALID waits for both AW (AWVALID && AWREADY) and W (WVALID && WREADY && WLAST) `
  - agent:   `AWVALID and WVALID asserted independently of AWREADY/WREADY. Slave must wait for`
- **L17_CHANNEL_SIGNAL_CATALOG** `fields.dependency_graph.AXI_read`
  - program: `ARVALID precedes RVALID; RVALID stays asserted until ARREADY accepted and final `
  - agent:   `ARVALID asserted independently of ARREADY. Slave must wait for both ARVALID and `
- **L17_CHANNEL_SIGNAL_CATALOG** `evidence`
  - program: `[{'line': 1361, 'quote': 'AWID                        Master      Identification`
  - agent:   `[{'spec_page': 'A2-32', 'spec_section': 'A2.1 Global signals (Table A2-1)', 'quo`
- **L18_INTERCONNECT_TOPOLOGY** `fields.interconnect_rules`
  - program: `[{'rule': 'from the same master completes. An arbiter within the interconnect mu`
  - agent:   `['Interconnect must realign the address and write data when determining the dest`
