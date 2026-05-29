# Phase 1 extractor parity diff

_Emitted by `l_doc_parity_diff.py` (v0.1.51). Doctrine: program output should match fresh-agent output; any divergence is either a program gap or a hallucination._

## Overall

- ABSENT_IN_PROGRAM : 64
- HALLUCINATED      : 0
- VALUE_MISMATCH    : 20
- SHAPE_MISMATCH    : 0

## Per L-doc

| L doc | program-bytes | agent-bytes | absent | halluc | mismatch | shape | parity-% |
|---|---|---|---|---|---|---|---|
| L1_DATASHEET | 102407 | 7019 | 1 | 0 | 2 | 0 | 88.5 |
| L2_FRS | 116476 | 11652 | 2 | 0 | 1 | 0 | 72.7 |
| L3_CMD_PROTOCOL | 21889 | 8103 | 2 | 0 | 0 | 0 | 96.4 |
| L4_REGMAP | 821 | 1385 | 2 | 0 | 0 | 0 | 66.7 |
| L5_ADI_SPEC | 809 | 1738 | 2 | 0 | 0 | 0 | 80.0 |
| L6_CONTROL_LOGIC | 12747 | 4435 | 10 | 0 | 0 | 0 | 50.0 |
| L7_TEST_DEBUG | 822 | 3535 | 4 | 0 | 0 | 0 | 50.0 |
| L8_RTL_CONSTANTS | 23644 | 6486 | 7 | 0 | 0 | 0 | 92.5 |
| L8_TIMING_WAVEFORM | 676 | 4893 | 6 | 0 | 0 | 0 | 76.0 |
| L9_INTEGRATION_SPEC | 31469 | 7168 | 12 | 0 | 0 | 0 | 45.5 |
| L10_TEST_CASES | 2234 | 6383 | 2 | 0 | 0 | 0 | 60.0 |
| L11_OTP_CONTENT | 820 | 270 | 0 | 0 | 0 | 0 | 100.0 |
| L12_BEHAVIORAL_SEQUENCES | 2402 | 5924 | 8 | 0 | 0 | 0 | 50.0 |
| L13_LAB_CALIBRATION | 803 | 256 | 0 | 0 | 0 | 0 | 100.0 |
| L14_PROTOCOL_VERSIONING | 2117 | 8579 | 1 | 0 | 0 | 0 | 90.0 |
| L15_ENCODING_TABLES | 285126 | 17262 | 1 | 0 | 0 | 0 | 93.3 |
| L16_COMPLIANCE_PROPERTIES | 42948 | 20403 | 0 | 0 | 0 | 0 | 100.0 |
| L17_CHANNEL_SIGNAL_CATALOG | 10262 | 17313 | 1 | 0 | 7 | 0 | 72.4 |
| L18_INTERCONNECT_TOPOLOGY | 6354 | 14788 | 3 | 0 | 10 | 0 | 80.0 |
| L19_CONSTRAINTS_PDK | 564 | 0 | 0 | 0 | 0 | 0 | 100.0 |
| L20_DFT_SCAN_TOPOLOGY | 438 | 0 | 0 | 0 | 0 | 0 | 100.0 |
| L21_POWER_INTENT | 437 | 0 | 0 | 0 | 0 | 0 | 100.0 |
| L22_VERIFICATION_PLAN | 510 | 0 | 0 | 0 | 0 | 0 | 100.0 |
| L23_SECURITY_REQUIREMENTS | 442 | 0 | 0 | 0 | 0 | 0 | 100.0 |

## Missing from program (64 total, showing top 20)

- **L1_DATASHEET** `<sibling-extras>` — agent captured this fact / sibling-extras; program did not
  - agent has: `{'extra_agent_subkeys': ['electrical_specs_rationale', 'five_channels', 'key_features', 'max_burst_length', 'package_inf`
- **L2_FRS** `<sibling-extras>` — agent captured this fact / sibling-extras; program did not
  - agent has: `{'extra_agent_subkeys': ['error_response_conditions', 'functional_requirements'], 'count': 2}`
- **L2_FRS** `protocol_overview.<sibling-extras>` — agent captured this fact / sibling-extras; program did not
  - agent has: `{'extra_agent_subkeys': ['atomicity_modes', 'burst_based', 'endianness', 'multiple_outstanding', 'out_of_order_completio`
- **L3_CMD_PROTOCOL** `<sibling-extras>` — agent captured this fact / sibling-extras; program did not
  - agent has: `{'extra_agent_subkeys': ['burst_length_field', 'cache_attribute_encoding_AXI3', 'exclusive_access_restrictions', 'exclus`
- **L3_CMD_PROTOCOL** `burst_size_encodings.<sibling-extras>` — agent captured this fact / sibling-extras; program did not
  - agent has: `{'extra_agent_subkeys': ['unit'], 'count': 1}`
- **L4_REGMAP** `register_map_present` — agent captured this fact / sibling-extras; program did not
  - agent has: `False`
- **L4_REGMAP** `notes` — agent captured this fact / sibling-extras; program did not
  - agent has: `If a future system-integration L4 is required, the canonical 'address-side fields' to capture would be: AxADDR width (im`
- **L5_ADI_SPEC** `analog_digital_interface_present` — agent captured this fact / sibling-extras; program did not
  - agent has: `False`
- **L5_ADI_SPEC** `signaling_summary` — agent captured this fact / sibling-extras; program did not
  - agent has: `{'clock': 'Single ACLK per AXI interface; all input signals sampled on rising edge of ACLK; all output changes occur aft`
- **L6_CONTROL_LOGIC** `fsm_hints` — agent captured this fact / sibling-extras; program did not
  - agent has: `{'per_channel_states': ['IDLE      (VALID=0)', 'VALID     (VALID=1, READY=0; data held stable)', 'HANDSHAKE (VALID=1, RE`
- **L6_CONTROL_LOGIC** `write_transaction_fsm_master` — agent captured this fact / sibling-extras; program did not
  - agent has: `['Drive AWADDR + AW* fields; assert AWVALID.', 'Drive WDATA[0]+WSTRB+WLAST=0 (or WLAST=1 if single beat); assert WVALID.`
- **L6_CONTROL_LOGIC** `read_transaction_fsm_master` — agent captured this fact / sibling-extras; program did not
  - agent has: `['Drive ARADDR + AR* fields; assert ARVALID.', 'Wait for ARREADY handshake.', 'Slave drives RDATA / RRESP / RLAST and as`
- **L6_CONTROL_LOGIC** `channel_dependency_rules_AXI3_write` — agent captured this fact / sibling-extras; program did not
  - agent has: `{'BVALID_dependency': ['WVALID', 'WREADY', 'WLAST']}`
- **L6_CONTROL_LOGIC** `channel_dependency_rules_AXI4_AXI5_write` — agent captured this fact / sibling-extras; program did not
  - agent has: `{'BVALID_dependency': ['AWVALID', 'AWREADY', 'WVALID', 'WREADY', 'WLAST'], 'note': 'AXI4/AXI5 add an additional slave de`
- **L6_CONTROL_LOGIC** `channel_dependency_rules_read` — agent captured this fact / sibling-extras; program did not
  - agent has: `{'RVALID_dependency': ['ARVALID', 'ARREADY']}`
- **L6_CONTROL_LOGIC** `anti_deadlock_rule` — agent captured this fact / sibling-extras; program did not
  - agent has: `Inside the slave, VALID for an outgoing channel must not be combinationally dependent on the READY of an incoming channe`
- **L6_CONTROL_LOGIC** `exit_from_reset` — agent captured this fact / sibling-extras; program did not
  - agent has: `Earliest point after reset that a master may drive ARVALID/AWVALID/WVALID HIGH is the rising ACLK edge after ARESETn=HIG`
- **L6_CONTROL_LOGIC** `default_ready_state_recommendation` — agent captured this fact / sibling-extras; program did not
  - agent has: `{'AWREADY': 'Default HIGH recommended (slave must accept any valid address in one cycle).', 'ARREADY': 'Default HIGH rec`
- **L6_CONTROL_LOGIC** `interleaving` — agent captured this fact / sibling-extras; program did not
  - agent has: `{'AXI3': 'Write data with different IDs (via WID) was permitted to be interleaved.', 'AXI4_AXI5': 'Write data interleavi`
- **L7_TEST_DEBUG** `test_debug_architecture_present` — agent captured this fact / sibling-extras; program did not
  - agent has: `False`

## Value mismatches (20 total, showing top 20)

- **L1_DATASHEET** `ic_name`
  - program: `UNKNOWN_IC`
  - agent:   `AMBA AXI / ACE Protocol Specification`
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
- **L18_INTERCONNECT_TOPOLOGY** `default_signal_values.BID`
  - program: `Required (no default)`
  - agent:   `Optional (no default driven from slave when omitted at master)`
- **L18_INTERCONNECT_TOPOLOGY** `default_signal_values.BRESP`
  - program: `Required (no default)`
  - agent:   `0b00 (OKAY) — only as memory-slave default when not driven`
- **L18_INTERCONNECT_TOPOLOGY** `default_signal_values.AWBURST`
  - program: `Required (no default)`
  - agent:   `0b01 (INCR)`
- **L18_INTERCONNECT_TOPOLOGY** `default_signal_values.RID`
  - program: `Required (no default)`
  - agent:   `Optional`
- **L18_INTERCONNECT_TOPOLOGY** `default_signal_values.RRESP`
  - program: `Required (no default)`
  - agent:   `Optional (defaults to OKAY)`
- **L18_INTERCONNECT_TOPOLOGY** `default_signal_values.RLAST`
  - program: `Required (no default)`
  - agent:   `Optional`
- **L18_INTERCONNECT_TOPOLOGY** `default_signal_values.ARREGION`
  - program: `Required (no default)`
  - agent:   `0x0`
- **L18_INTERCONNECT_TOPOLOGY** `default_signal_values.ARBURST`
  - program: `Required (no default)`
  - agent:   `0b01 (INCR)`
- **L18_INTERCONNECT_TOPOLOGY** `multi_copy_atomicity.english`
  - program: `Once a write is observed by one observer, all observers must see it (no write co`
  - agent:   `A system is multi-copy atomic iff (a) writes to the same location are observed i`
- **L18_INTERCONNECT_TOPOLOGY** `id_routing.description`
  - program: `Interconnect may append bits to AxID to identify the originating master; slave-s`
  - agent:   `Slave-side ID_WIDTH > master-side ID_WIDTH. The interconnect appends additional `
