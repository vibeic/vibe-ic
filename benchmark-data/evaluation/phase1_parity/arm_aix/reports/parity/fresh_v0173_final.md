# Phase 1 extractor parity diff

_Emitted by `l_doc_parity_diff.py` (v0.1.51). Doctrine: program output should match fresh-agent output; any divergence is either a program gap or a hallucination._

## Overall

- ABSENT_IN_PROGRAM : 65
- HALLUCINATED      : 0
- VALUE_MISMATCH    : 36
- SHAPE_MISMATCH    : 18

## Per L-doc

| L doc | program-bytes | agent-bytes | absent | halluc | mismatch | shape | parity-% |
|---|---|---|---|---|---|---|---|
| L1_DATASHEET | 103138 | 7019 | 4 | 0 | 3 | 1 | 69.2 |
| L2_FRS | 116476 | 11652 | 3 | 0 | 1 | 1 | 54.5 |
| L3_CMD_PROTOCOL | 23233 | 8103 | 10 | 0 | 4 | 1 | 72.7 |
| L4_REGMAP | 821 | 1385 | 2 | 0 | 0 | 1 | 50.0 |
| L5_ADI_SPEC | 809 | 1738 | 2 | 0 | 0 | 1 | 70.0 |
| L6_CONTROL_LOGIC | 14915 | 4435 | 1 | 0 | 8 | 1 | 50.0 |
| L7_TEST_DEBUG | 822 | 3535 | 4 | 0 | 0 | 1 | 37.5 |
| L8_RTL_CONSTANTS | 24164 | 6486 | 17 | 0 | 0 | 1 | 80.6 |
| L8_TIMING_WAVEFORM | 676 | 4893 | 6 | 0 | 0 | 1 | 72.0 |
| L9_INTEGRATION_SPEC | 34418 | 7168 | 2 | 0 | 5 | 1 | 63.6 |
| L10_TEST_CASES | 2234 | 6383 | 2 | 0 | 0 | 1 | 40.0 |
| L11_OTP_CONTENT | 820 | 270 | 0 | 0 | 0 | 0 | 100.0 |
| L12_BEHAVIORAL_SEQUENCES | 4971 | 5924 | 1 | 0 | 6 | 1 | 50.0 |
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

## Missing from program (65 total, showing top 20)

- **L1_DATASHEET** `release_history` — agent captured this fact / sibling-extras; program did not
  - agent has: `[{'date': '16 June 2003', 'issue': 'A', 'change': 'First release'}, {'date': '19 March 2004', 'issue': 'B', 'change': 'F`
- **L1_DATASHEET** `protocol_variants_described` — agent captured this fact / sibling-extras; program did not
  - agent has: `['AXI3 (AMBA 3)', 'AXI4 (AMBA 4)', 'AXI4-Lite (AMBA 4)', 'AXI5 (AMBA 5)', 'AXI5-Lite (AMBA 5)', 'ACE (AMBA 4)', 'ACE-Lit`
- **L1_DATASHEET** `key_features` — agent captured this fact / sibling-extras; program did not
  - agent has: `['Separate address/control and data phases', 'Unaligned data transfers via byte strobes', 'Burst-based transactions with`
- **L1_DATASHEET** `supported_interconnect_topologies` — agent captured this fact / sibling-extras; program did not
  - agent has: `['Shared address and data buses', 'Shared address buses and multiple data buses', 'Multilayer, with multiple address and`
- **L2_FRS** `functional_requirements` — agent captured this fact / sibling-extras; program did not
  - agent has: `[{'id': 'FR-HANDSHAKE-01', 'text': 'All five transaction channels use the same VALID/READY handshake. Source generates V`
- **L2_FRS** `error_response_conditions` — agent captured this fact / sibling-extras; program did not
  - agent has: `['FIFO or buffer overrun/underrun', 'Unsupported transfer size attempted', 'Write access attempted to read-only location`
- **L2_FRS** `protocol_overview.<sibling-extras>` — agent captured this fact / sibling-extras; program did not
  - agent has: `{'extra_agent_subkeys': ['atomicity_modes', 'burst_based', 'endianness', 'multiple_outstanding', 'out_of_order_completio`
- **L3_CMD_PROTOCOL** `response_encodings` — agent captured this fact / sibling-extras; program did not
  - agent has: `{'RRESP[1:0] / BRESP[1:0]': {'0b00': 'OKAY    - normal access success (or exclusive failed)', '0b01': 'EXOKAY  - exclusi`
- **L3_CMD_PROTOCOL** `lock_encodings` — agent captured this fact / sibling-extras; program did not
  - agent has: `{'AXI3_AxLOCK[1:0]': {'0b00': 'Normal access', '0b01': 'Exclusive access', '0b10': 'Locked access', '0b11': 'Reserved'},`
- **L3_CMD_PROTOCOL** `cache_attribute_encoding_AXI3` — agent captured this fact / sibling-extras; program did not
  - agent has: `{'AxCACHE[0]': 'Bufferable  (B)', 'AxCACHE[1]': 'Cacheable   (C) (renamed Modifiable in AXI4)', 'AxCACHE[2]': 'Read-Allo`
- **L3_CMD_PROTOCOL** `protection_attribute_encoding` — agent captured this fact / sibling-extras; program did not
  - agent has: `{'AxPROT[0]': {'0': 'Unprivileged access', '1': 'Privileged access'}, 'AxPROT[1]': {'0': 'Secure access', '1': 'Non-secu`
- **L3_CMD_PROTOCOL** `valid_ready_handshake_rules` — agent captured this fact / sibling-extras; program did not
  - agent has: `['Transfer occurs only when both VALID and READY are HIGH at a rising ACLK edge.', 'Once VALID is asserted, it must rema`
- **L3_CMD_PROTOCOL** `burst_size_encodings.unit` — agent captured this fact / sibling-extras; program did not
  - agent has: `Bytes in transfer (per beat)`
- **L3_CMD_PROTOCOL** `burst_length_field.<sibling-extras>` — agent captured this fact / sibling-extras; program did not
  - agent has: `{'extra_agent_subkeys': ['AxLEN_AXI4', 'wrap_only_allowed'], 'count': 2}`
- **L3_CMD_PROTOCOL** `burst_length_field.AxLEN_AXI3.range` — agent captured this fact / sibling-extras; program did not
  - agent has: `1 to 16 transfers, all burst types`
- **L3_CMD_PROTOCOL** `qos.added_in` — agent captured this fact / sibling-extras; program did not
  - agent has: `AXI4`
- **L3_CMD_PROTOCOL** `region.added_in` — agent captured this fact / sibling-extras; program did not
  - agent has: `AXI4`
- **L4_REGMAP** `register_map_present` — agent captured this fact / sibling-extras; program did not
  - agent has: `False`
- **L4_REGMAP** `notes` — agent captured this fact / sibling-extras; program did not
  - agent has: `If a future system-integration L4 is required, the canonical 'address-side fields' to capture would be: AxADDR width (im`
- **L5_ADI_SPEC** `analog_digital_interface_present` — agent captured this fact / sibling-extras; program did not
  - agent has: `False`

## Value mismatches (36 total, showing top 20)

- **L1_DATASHEET** `package_info_rationale`
  - program: `Bus protocol specification, not a packaged IC. No package / pinout / electrical `
  - agent:   `AXI is a bus protocol specification, not a packaged IC. No package/pinout/electr`
- **L1_DATASHEET** `electrical_specs_rationale`
  - program: `Protocol spec defines only logical signal semantics (synchronous, sampled on ris`
  - agent:   `Protocol spec defines only logical signal semantics (synchronous, sampled on ris`
- **L1_DATASHEET** `intended_audience`
  - program: `This specification is written for hardware and software engineers who want to be`
  - agent:   `Hardware and software engineers familiar with AMBA who want to design AXI-compat`
- **L2_FRS** `protocol_overview.wire_count`
  - program: `2`
  - agent:   `5 independent channels, each with VALID/READY pair`
- **L3_CMD_PROTOCOL** `qos.AxQOS`
  - program: `4-bit Quality of Service identifier. Default 0b0000 = not participating in QoS.`
  - agent:   `4-bit Quality of Service identifier. Default 0b0000 = not participating. Higher `
- **L3_CMD_PROTOCOL** `region.AxREGION`
  - program: `4-bit region identifier; up to 16 logical regions; must reflect a single physica`
  - agent:   `4-bit region identifier; up to 16 logical regions; must remain constant within a`
- **L3_CMD_PROTOCOL** `single_response_for_write`
  - program: `For a write transaction, a single BRESP is signaled for the entire burst on B ch`
  - agent:   `For a write transaction, a single BRESP is signaled for the entire burst, not fo`
- **L3_CMD_PROTOCOL** `per_beat_response_for_read`
  - program: `For a read transaction, the slave can signal different RRESP values for each bea`
  - agent:   `For a read transaction, the slave can signal different RRESP values for differen`
- **L6_CONTROL_LOGIC** `fsm_hints.rule`
  - program: `Transfer occurs only when both VALID and READY are HIGH at a rising clock edge.`
  - agent:   `Source MUST NOT wait for READY before asserting VALID. Destination MAY wait for `
- **L6_CONTROL_LOGIC** `channel_dependency_rules_AXI4_AXI5_write.note`
  - program: `AXI4+ adds AW handshake as a BVALID prerequisite.`
  - agent:   `AXI4/AXI5 add an additional slave dependency on AW handshake before BVALID, so s`
- **L6_CONTROL_LOGIC** `exit_from_reset`
  - program: `earliest point after reset that a master is permitted to begin driving ARVALID, `
  - agent:   `Earliest point after reset that a master may drive ARVALID/AWVALID/WVALID HIGH i`
- **L6_CONTROL_LOGIC** `default_ready_state_recommendation.AWREADY`
  - program: `Default HIGH recommended (slave accepts any valid request in one cycle)`
  - agent:   `Default HIGH recommended (slave must accept any valid address in one cycle).`
- **L6_CONTROL_LOGIC** `default_ready_state_recommendation.WREADY`
  - program: `Default HIGH recommended (slave accepts any valid request in one cycle)`
  - agent:   `May default HIGH only if slave can always accept write data in one cycle.`
- **L6_CONTROL_LOGIC** `default_ready_state_recommendation.BREADY`
  - program: `Default HIGH recommended (slave accepts any valid request in one cycle)`
  - agent:   `May default HIGH only if master can always accept a write response in one cycle.`
- **L6_CONTROL_LOGIC** `default_ready_state_recommendation.ARREADY`
  - program: `Default HIGH recommended (slave accepts any valid request in one cycle)`
  - agent:   `Default HIGH recommended (same reasoning).`
- **L6_CONTROL_LOGIC** `default_ready_state_recommendation.RREADY`
  - program: `Default HIGH recommended (slave accepts any valid request in one cycle)`
  - agent:   `May default HIGH only if master can accept read data immediately at start of rea`
- **L9_INTEGRATION_SPEC** `axi4_lite_subset`
  - program: `, the following sections should be read: • Part A AMBA AXI Protocol Specificatio`
  - agent:   `AXI4-Lite is a subset of AXI4 for simpler control-register-style interfaces (def`
- **L9_INTEGRATION_SPEC** `default_slave_behavior`
  - program: `component, to indicate that there is no slave at the transaction address. See DE`
  - agent:   `When the interconnect cannot decode a slave access, it must return DECERR. Spec `
- **L9_INTEGRATION_SPEC** `interface_categories`
  - program: `, the following sections should be read: • Part A AMBA AXI Protocol Specificatio`
  - agent:   `['Read/Write interface (AR, R, AW, W, B)', 'Read-only interface (AR, R only; no `
- **L9_INTEGRATION_SPEC** `register_slice_insertion_rule`
  - program: `Each AXI channel transfers information in only one direction, and the architectu`
  - agent:   `A register slice can be inserted at almost any point in any channel, at the cost`
