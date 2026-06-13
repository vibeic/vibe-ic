# Phase 1 extractor parity diff

_Emitted by `l_doc_parity_diff.py` (v0.1.51). Doctrine: program output should match fresh-agent output; any divergence is either a program gap or a hallucination._

## Overall

- ABSENT_IN_PROGRAM : 303
- HALLUCINATED      : 15
- VALUE_MISMATCH    : 0
- SHAPE_MISMATCH    : 14

## Per L-doc

| L doc | program-bytes | agent-bytes | absent | halluc | mismatch | shape | parity-% |
|---|---|---|---|---|---|---|---|
| L1_DATASHEET | 101312 | 7019 | 26 | 1 | 0 | 1 | 0.0 |
| L2_FRS | 116106 | 11652 | 11 | 1 | 0 | 1 | 0.0 |
| L3_CMD_PROTOCOL | 11675 | 8103 | 55 | 1 | 0 | 1 | 0.0 |
| L4_REGMAP | 372 | 1385 | 6 | 1 | 0 | 1 | 0.0 |
| L5_ADI_SPEC | 2441 | 1738 | 10 | 1 | 0 | 1 | 0.0 |
| L6_CONTROL_LOGIC | 12367 | 4435 | 20 | 1 | 0 | 1 | 0.0 |
| L7_TEST_DEBUG | 647 | 3535 | 8 | 1 | 0 | 1 | 0.0 |
| L8_RTL_CONSTANTS | 1105 | 6486 | 93 | 1 | 0 | 1 | 0.0 |
| L8_TIMING_WAVEFORM | 294 | 4893 | 25 | 1 | 0 | 1 | 0.0 |
| L9_INTEGRATION_SPEC | 31086 | 7168 | 22 | 1 | 0 | 1 | 0.0 |
| L10_TEST_CASES | 1656 | 6383 | 5 | 2 | 0 | 1 | 0.0 |
| L11_OTP_CONTENT | 21887 | 270 | 3 | 1 | 0 | 1 | 0.0 |
| L12_BEHAVIORAL_SEQUENCES | 1894 | 5924 | 16 | 1 | 0 | 1 | 0.0 |
| L13_LAB_CALIBRATION | 508 | 256 | 3 | 1 | 0 | 1 | 0.0 |

## Hallucinations (PRIORITY)

- **L1_DATASHEET** `<heuristic>` — ic_name lifted from license boilerplate ('SUCH ARM TECHNOLOGY')
  - program emitted: `"ic_name": "SUCH ARM TECHNOLOGY"`
- **L2_FRS** `<heuristic>` — ic_name lifted from license boilerplate ('SUCH ARM TECHNOLOGY')
  - program emitted: `"ic_name": "SUCH ARM TECHNOLOGY"`
- **L3_CMD_PROTOCOL** `<heuristic>` — ic_name lifted from license boilerplate ('SUCH ARM TECHNOLOGY')
  - program emitted: `"ic_name": "SUCH ARM TECHNOLOGY"`
- **L4_REGMAP** `<heuristic>` — ic_name lifted from license boilerplate ('SUCH ARM TECHNOLOGY')
  - program emitted: `"ic_name": "SUCH ARM TECHNOLOGY"`
- **L5_ADI_SPEC** `<heuristic>` — ic_name lifted from license boilerplate ('SUCH ARM TECHNOLOGY')
  - program emitted: `"ic_name": "SUCH ARM TECHNOLOGY"`
- **L6_CONTROL_LOGIC** `<heuristic>` — ic_name lifted from license boilerplate ('SUCH ARM TECHNOLOGY')
  - program emitted: `"ic_name": "SUCH ARM TECHNOLOGY"`
- **L7_TEST_DEBUG** `<heuristic>` — ic_name lifted from license boilerplate ('SUCH ARM TECHNOLOGY')
  - program emitted: `"ic_name": "SUCH ARM TECHNOLOGY"`
- **L8_RTL_CONSTANTS** `<heuristic>` — ic_name lifted from license boilerplate ('SUCH ARM TECHNOLOGY')
  - program emitted: `"ic_name": "SUCH ARM TECHNOLOGY"`
- **L8_TIMING_WAVEFORM** `<heuristic>` — ic_name lifted from license boilerplate ('SUCH ARM TECHNOLOGY')
  - program emitted: `"ic_name": "SUCH ARM TECHNOLOGY"`
- **L9_INTEGRATION_SPEC** `<heuristic>` — ic_name lifted from license boilerplate ('SUCH ARM TECHNOLOGY')
  - program emitted: `"ic_name": "SUCH ARM TECHNOLOGY"`
- **L10_TEST_CASES** `<heuristic>` — ic_name lifted from license boilerplate ('SUCH ARM TECHNOLOGY')
  - program emitted: `"ic_name": "SUCH ARM TECHNOLOGY"`
- **L10_TEST_CASES** `<heuristic>` — opcode emitted from a doc that has no opcode field
  - program emitted: `"opcode_hex": "0x16"`
- **L11_OTP_CONTENT** `<heuristic>` — ic_name lifted from license boilerplate ('SUCH ARM TECHNOLOGY')
  - program emitted: `"ic_name": "SUCH ARM TECHNOLOGY"`
- **L12_BEHAVIORAL_SEQUENCES** `<heuristic>` — ic_name lifted from license boilerplate ('SUCH ARM TECHNOLOGY')
  - program emitted: `"ic_name": "SUCH ARM TECHNOLOGY"`
- **L13_LAB_CALIBRATION** `<heuristic>` — ic_name lifted from license boilerplate ('SUCH ARM TECHNOLOGY')
  - program emitted: `"ic_name": "SUCH ARM TECHNOLOGY"`

## Missing from program (303 total, showing top 20)

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
