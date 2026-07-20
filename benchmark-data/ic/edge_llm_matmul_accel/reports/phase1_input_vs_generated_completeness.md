# Phase 1 — input prompt → Phase 1 output completeness

**Verdict**: SKIP_LOW_TOKENS
**Prompt**: `input/docs/00_user_request.md`
**Reference doc**: False
**Captured pct**: 100.0%
  - distinct tokens: 0
  - garble / artefact: 0
  - captured: 0
  - missing: 0

**Thresholds**: FAIL < 50%, WARN < 80%, PASS otherwise.

## Haystack layers searched

- `L10_TEST_CASES.json`: 0 token hit(s)
- `L10_TEST_CASES.md`: 0 token hit(s)
- `L11_OTP_CONTENT.json`: 0 token hit(s)
- `L11_OTP_CONTENT.md`: 0 token hit(s)
- `L12_BEHAVIORAL_SEQUENCES.json`: 0 token hit(s)
- `L12_BEHAVIORAL_SEQUENCES.md`: 0 token hit(s)
- `L13_LAB_CALIBRATION.json`: 0 token hit(s)
- `L13_LAB_CALIBRATION.md`: 0 token hit(s)
- `L14_PROTOCOL_VERSIONING.json`: 0 token hit(s)
- `L14_PROTOCOL_VERSIONING.md`: 0 token hit(s)
- `L15_ENCODING_TABLES.json`: 0 token hit(s)
- `L15_ENCODING_TABLES.md`: 0 token hit(s)
- `L16_COMPLIANCE_PROPERTIES.json`: 0 token hit(s)
- `L16_COMPLIANCE_PROPERTIES.md`: 0 token hit(s)
- `L17_CHANNEL_SIGNAL_CATALOG.json`: 0 token hit(s)
- `L17_CHANNEL_SIGNAL_CATALOG.md`: 0 token hit(s)
- `L18_INTERCONNECT_TOPOLOGY.json`: 0 token hit(s)
- `L18_INTERCONNECT_TOPOLOGY.md`: 0 token hit(s)
- `L19_CONSTRAINTS_PDK.json`: 0 token hit(s)
- `L19_CONSTRAINTS_PDK.md`: 0 token hit(s)
- `L1_DATASHEET.json`: 0 token hit(s)
- `L1_DATASHEET.md`: 0 token hit(s)
- `L20_DFT_SCAN_TOPOLOGY.json`: 0 token hit(s)
- `L20_DFT_SCAN_TOPOLOGY.md`: 0 token hit(s)
- `L21_POWER_INTENT.json`: 0 token hit(s)
- `L21_POWER_INTENT.md`: 0 token hit(s)
- `L22_VERIFICATION_PLAN.json`: 0 token hit(s)
- `L22_VERIFICATION_PLAN.md`: 0 token hit(s)
- `L23_SECURITY_REQUIREMENTS.json`: 0 token hit(s)
- `L23_SECURITY_REQUIREMENTS.md`: 0 token hit(s)
- `L24_SIGNOFF.json`: 0 token hit(s)
- `L24_SIGNOFF.md`: 0 token hit(s)
- `L25_RELIABILITY_MISSION_PROFILE.json`: 0 token hit(s)
- `L25_RELIABILITY_MISSION_PROFILE.md`: 0 token hit(s)
- `L26_MECHANICAL_TRANSDUCTION.json`: 0 token hit(s)
- `L26_MECHANICAL_TRANSDUCTION.md`: 0 token hit(s)
- `L27_MEMORY_MODULE_SPD.json`: 0 token hit(s)
- `L27_MEMORY_MODULE_SPD.md`: 0 token hit(s)
- `L2_FRS.json`: 0 token hit(s)
- `L2_FRS.md`: 0 token hit(s)
- `L3_CMD_PROTOCOL.json`: 0 token hit(s)
- `L3_CMD_PROTOCOL.md`: 0 token hit(s)
- `L4_REGMAP.json`: 0 token hit(s)
- `L4_REGMAP.md`: 0 token hit(s)
- `L5_ADI_SPEC.json`: 0 token hit(s)
- `L5_ADI_SPEC.md`: 0 token hit(s)
- `L6_CONTROL_LOGIC.json`: 0 token hit(s)
- `L6_CONTROL_LOGIC.md`: 0 token hit(s)
- `L7_TEST_DEBUG.json`: 0 token hit(s)
- `L7_TEST_DEBUG.md`: 0 token hit(s)
- `L8_RTL_CONSTANTS.json`: 0 token hit(s)
- `L8_RTL_CONSTANTS.md`: 0 token hit(s)
- `L8_TIMING_WAVEFORM.json`: 0 token hit(s)
- `L8_TIMING_WAVEFORM.md`: 0 token hit(s)
- `L9_INTEGRATION_SPEC.json`: 0 token hit(s)
- `L9_INTEGRATION_SPEC.md`: 0 token hit(s)

## Missing tokens (sample, longest first)

(none — every harvested token was captured)

Cell = chip-AGNOSTIC design token (numeric+unit, hex constant, all-caps identifier, indexed signal). Harvest matches `phase1_doc_input_completeness_check`. Phase 1 threshold is intentionally lower than Phase 1 (doc-extraction) (interpretation vs extraction) — see file header.
