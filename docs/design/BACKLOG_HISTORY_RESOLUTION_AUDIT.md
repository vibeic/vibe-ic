# BACKLOG History Resolution Audit (v2 → v10)

Cross-references every concrete gate / tool / fix proposed in `PLUGIN_ENHANCEMENT_BACKLOG_v{2..10}.md` against:
- shipped programs in `opensource_repo/vibe-ic-marketplace/plugins/vibe-ic-d/programs/` (currently 195 files)
- shipped MCP tools in `mcp-eda-server/src/index.js` (36 server.tool entries + 10 device tools = 44 total)
- shipped skills + hooks in `vibe-ic-marketplace/plugins/vibe-ic-core/skills/` + `vibe-ic-d/hooks/`
- shipped versions in `marketplace.json` + per-plugin `plugin.json` (currently 0.111.0)

Last updated: 2026-04-29 (post-v0.108 bench-a benchmark + v0.109/0.110/0.111 closure).

---

## v3 Backlog (5 hardware bugs)

| Item | Where it landed | Status |
|---|---|---|
| Bug 1 — Pre-awake silence: BOR-only, missing soft-reset | `pre_awake_silence_check.py` + `host_soft_reset_unwake_path_check.py` (W2) | ✅ RESOLVED |
| Bug 2 — 0x73 GET_STATE CRC mismatch | `crc_seed_consistency_check.py` (12 vectors), `crc_residual_check.py`, `crc_engine_isolation_check.py`, `cmd_protocol_crc_verify.py`, `crc_completeness_check.py`, `crc_bitorder_check.py` | ✅ RESOLVED — 6 CRC gates now |
| Bug 3 — Malformed bit-count (9-bit byte) accepted | `bit_count_modulo_check.py` | ✅ RESOLVED |
| Bug 4 — 0xE0 OTP program response shape wrong | `cmd_response_conformance_check.py` + `response_payload_template_check.py` + (v0.106) `rtl_response_byte_oracle_check.py` | ✅ RESOLVED |
| Bug 5 — 0xE2 OTP read doesn't bound ADR/LEN | `cmd_arg_range_validation_check.py` | ✅ RESOLVED |

**v3 score: 5/5 RESOLVED**

---

## v4 Backlog (signoff/acceptance policy)

| Item | Status |
|---|---|
| O1 — Escalate `pre_awake_silence_check` SINGLE_CLEAR_PATH to ERROR | ✅ Severity wired in `acceptance_gate_full.py` |
| O2 — Escalate `crc_engine_isolation_check` SHARED_CRC_DATA_MUX to ERROR | ✅ `crc_engine_isolation_check.py` exists |
| O3 — `warn_acceptance_policy_check` flow gate | ✅ `warn_acceptance_policy_check.py` |
| O4 — Agent-prompt mandate `WARN_ACCEPTANCE_LOG.md` | ⚠️ Documentation rule, not a gate |
| P1 — Evidence quality rating in behavioral schema | ✅ `gate_evidence_completeness_check.py` |
| P2 — Cross-link evidence files | ⚠️ Indirectly via `provenance_logger.py` |
| Q1 — `behavioral_test_sheet_runner` MCP tool | ✅ Provided by `eda_simulate` + `bit_level_full_stack_tb_check.py` |

**v4 score: 5/7 RESOLVED, 2/7 partial**

---

## v5 Backlog (turnaround / scope-protocol)

| Item | Provision | Status |
|---|---|---|
| R1 — `bus_turnaround_consumes_spec_constant_check` | `bus_turnaround_consumes_spec_constant_check.py` (v0.106 added magnitude check) | ✅ RESOLVED with magnitude upgrade |
| R2 — `protocol_turnaround_audit` semantic | Subsumed by R1 + `dead_timing_constant_warn.py` | ✅ RESOLVED |
| R3 — `protocol_timeline_assert` cocotb auto-gen | `assertion_property_check.py` + `protocol_gap_check.py` | ⚠️ PARTIAL — generic cocotb scaffolding still missing |
| R4 — `dead_timing_constant_warn` | `dead_timing_constant_warn.py` | ✅ RESOLVED |
| R5 — L9 mandate `dispatcher.response_delay_state_required` | `l9_response_delay_schema_check.py`, `l9_completeness_check.py` | ✅ RESOLVED |
| S1 — `eda_scope_protocol_decode` MCP tool | mcp-eda-server tool exists | ✅ RESOLVED |
| S2 — `eda_pass_reference_scope_diff` | mcp-eda-server tool exists | ✅ RESOLVED |
| S3 — `eda_rtl_signaltap_autogen` | mcp-eda-server tool exists | ✅ RESOLVED |
| T1 — Tester-verdict frame decode | `tester_verdict_frame_decode.py` | ✅ RESOLVED |

**v5 score: 8/9 RESOLVED, 1/9 partial**

---

## v6 Backlog (BACKLOG-v6 P0 set; was the v0.104 mandatory checklist)

All 9 originally-promised P0 gates ARE shipped in v0.104+ and **all PASS structurally** on the v0.108 fresh-agent RTL. But hardware byte[6]=PASS still required gates the v0.104 P0 set didn't cover.

| Item | v0.104+ provision | Status | Caught v0.108 issues? |
|---|---|---|---|
| R6 — `dispatcher_tx_arm_order_check` | `dispatcher_tx_arm_order_check.py` | ✅ RESOLVED | ❌ (not its scope) |
| R7 — `frame_assembler_capture_window_check` | Subsumed by `byte_assembler` lint + `pulse_decoder_edge_check.py` + `interface_encoding_audit.py` | ⚠️ PARTIAL | ❌ |
| R8 — `dispatch_fetch_loop_population_check` | `dispatch_fetch_loop_population_check.py` | ✅ RESOLVED | ❌ — verified loop EXISTS but didn't catch latency |
| R9 — `dispatch_register_default_reset_check` | `dispatch_register_default_reset_check.py` | ✅ RESOLVED | ❌ |
| **P1 — `pad_drive_high_active_check`** | only `oe_pattern_check.py` + `tristate_bus_check.py` exist | ❌ STILL MISSING — v7 P1.1 `tristate_active_drive_check` is similar but distinct | ❌ |
| P2 — `self_rx_mask_check` | `self_rx_mask_check.py` | ✅ RESOLVED | ❌ (not its scope) |
| W1 — `wake_pulse_suppress_when_woken_check` | `timer_freeze_after_state_check.py` (synonym) | ✅ RESOLVED | ❌ |
| W2 — `host_soft_reset_unwake_path_check` | `host_soft_reset_unwake_path_check.py` | ✅ RESOLVED | ❌ |
| D1 — `auto_diagnostic_led_synth` skill | ❌ MISSING | ❌ MISSING | n/a |
| **D2 — `oracle_bytewise_dump` MCP tool** | ❌ STILL MISSING; closest existence: `eda_pass_reference_scope_diff` | ❌ STILL MISSING | This would have collapsed v0.108 round 1 debug from hours to minutes |
| D3 — `rig_topology_disclosure` | `rig_topology_disclosure_check.py` | ✅ RESOLVED | ❌ |
| **C1 — `cmd_response_byte_oracle_check`** | `cmd_response_conformance_check.py` exists; v0.106 added `rtl_response_byte_oracle_check.py` | ⚠️ PARTIAL — exists but **never invoked in v0.108 round 1** because no L10 oracle vectors generated | WOULD HAVE CAUGHT IT if invoked |
| C2 — `otp_image_field_layout_doc_check` | `otp_image_check.py` + `rsp_example_otp_consistency_check.py` + (v0.106) `otp_image_layer_consistency_check.py` | ✅ RESOLVED with v0.106 P1.3 |
| **T1 — OpenROAD pdngen zero-net specialnets** | mcp-eda-server `eda_pnr` PDN handling improved; v0.106 added auto-stripe | ⚠️ PARTIAL — v0.108 round 1 IR-drop still failed PDN connectivity (waiver 22) |
| **T2 — KLayout custom-PDK DRC layermap fix** | mcp-eda-server `eda_drc_klayout` | ❌ STILL BROKEN — v0.108 round 3 hit `L_lname is not defined` again (waiver 28); 6+ versions deferred |
| **T3 — IR-drop default PDN stripe** | mcp-eda-server `eda_ir_drop` | ⚠️ PARTIAL — v0.106 added Metal4 auto-stripe but KeyFoundry techlef gap (RESISTANCE PER CUT) blocks anyway (waiver 22) |

### Pre-existing gates noted in v6 backlog (still confirmed)
- `self_rx_mask_check.py` ✅
- `timer_freeze_after_state_check.py` ✅

### Still-relevant gaps in v0.108 plugin
- `memory_read_pipeline_check.py` exists but is documentation-only (didn't catch v0.104 latency bug — addressed in v7 P0.1 `fetch_round_trip_sentinel_check`)
- `nba_addr_read_race_check.py` exists but checks producer-side only

**v6 score: 9/16 RESOLVED, 4/16 partial, 3/16 STILL MISSING (P1, D1, D2)**

---

## v7 Backlog (BACKLOG-v7, shipped in v0.106)

| Item | Status |
|---|---|
| P0.1 — `fetch_round_trip_sentinel_check.py` | ✅ shipped v0.106 |
| P0.2 — `rtl_response_byte_oracle_check.py` | ✅ shipped v0.106 |
| P0.3 — `scope_response_byte_decode_check.py` | ✅ shipped v0.106 |
| P1.1 — `tristate_active_drive_check.py` (FPGA-target-only, with protocol-mode guard) | ✅ shipped v0.106 |
| P1.2 — `bus_turnaround_consumes_spec_constant_check` magnitude upgrade | ✅ shipped v0.106 |
| P1.3 — `otp_image_layer_consistency_check.py` | ✅ shipped v0.106 |
| P2.1 — `dispatcher_response_size_table_audit.py` | ❌ NOT SHIPPED |
| P2.2 — `dispatcher_awake_gate_check.py` | ❌ NOT SHIPPED |
| P2.3 — Latency-aware upgrade of `dispatch_fetch_loop_population_check` | ⚠️ PARTIAL — sentinel sim addresses behaviorally but static check unchanged |

**v7 score: 6/9 RESOLVED, 1/9 partial, 2/9 missing (P2.1, P2.2)**

---

## v8 Backlog (SOFT discovery layer for SOLE-ACCEPTANCE rule, shipped in v0.109)

| Item | Status |
|---|---|
| `CLAUDE.md` rule #11 | ✅ shipped v0.109 |
| `spec-to-rtl/SKILL.md` ⛔ SOLE banner | ✅ shipped v0.109 |
| `tapeout-checklist/SKILL.md` ⛔ SOLE banner | ✅ shipped v0.109 |
| `phase23_completion_self_audit_check.py` (NEW gate) | ✅ shipped v0.109, v2.0.0 in v0.111 |
| `eda_phase23_completion_audit` MCP tool | ✅ shipped v0.109 (35 → 36 server.tool) |
| `flow_compliance_check.py` docstring leads with rule | ✅ shipped v0.109 |
| Tool count + plugin metadata bump | ✅ shipped v0.109 |

**v8 score: 7/7 RESOLVED**

---

## v9 Backlog (HARD enforcement Stop hook, shipped in v0.110)

| Item | Status |
|---|---|
| `phase23_claim_validator.sh` Stop hook | ✅ shipped v0.110 |
| `vibe-ic-d/.claude-plugin/plugin.json` hooks.Stop wired with 130 s timeout | ✅ shipped v0.110 |
| Multilingual claim regex (English + Chinese phrases) | ✅ shipped |
| `[NOT-CLAIMING-COMPLETE]` override escape | ✅ shipped |
| python3-only JSON parsing (no jq) | ✅ shipped |
| Three-case test verified (BLOCK / ALLOW / ALLOW-with-override) | ✅ verified |
| Fail-open on infra failures (missing transcript / project / gate) | ✅ shipped |

**v9 score: 7/7 RESOLVED**

### v9 follow-up addressed in v0.111
| Item | Status |
|---|---|
| 3-state verdict (PASS / PASS_WITH_WAIVERS / FAIL) | ✅ shipped v0.111 |
| Stop hook injects PASS_WITH_WAIVERS caveat (forbids "all 34 PASS" phrasing) | ✅ shipped v0.111 |
| `WAIVED → WAIVED-DEFERRED` per-step label | ✅ shipped v0.111 |
| `fsm_error_invariant.py` directory expansion (live patch during v0.108 run 3) | ✅ shipped v0.111 |
| `waivers_schema_check.py` accepts `"A<n>"` analog ids (live patch during v0.108 run 4) | ✅ shipped v0.111 |

---

## v10 Backlog (proposed for v0.112+, NOT yet shipped)

| Item | Status | Why it matters |
|---|---|---|
| P0.1 — KLayout `L_lname` minimum-viable DRC deck auto-derive | ❌ NOT SHIPPED | Closes waiver 28 root cause; reused across every custom-PDK ASIC |
| P0.2 — Cascading-waiver auto-propagation | ❌ NOT SHIPPED | 6 of 9 v0.108 waivers are cascades; clarity matters |
| P0.3 — Stop hook validates next-turn phrasing | ❌ NOT SHIPPED | Closes only remaining hole in v0.110 enforcement |
| P1.1 — Auto-trigger A1-A8 from L9 `analog_modules` | ❌ NOT SHIPPED | Round 4 needed manual `analog_block_list.json` |
| P1.2 — `foundry_signoff_plan_check.py` schema gate | ❌ NOT SHIPPED | 9 waivers reference "foundry deck closes" but no closure plan |
| P1.3 — Waiver staleness 90/180-day check | ❌ NOT SHIPPED | Old waivers rot silently |
| P1.4 — MCP server reliability + auto-reconnect | ❌ NOT SHIPPED | v0.108 run 3 had MCP device tools disconnect mid-run |
| P1.5 — SKIPPED-CONDITION 2-kind disambiguation | ❌ NOT SHIPPED | "rightful skip" vs "trigger missing" should differ |
| P2.1 — Auto-generate `FINAL_REPORT.md` from gate JSON | ❌ NOT SHIPPED | Reduces agent-prose-discipline dependence |
| P2.2 — Cross-version benchmark CI | ❌ NOT SHIPPED | Frozen v0108_golden + regression check |
| P2.3 — Per-step provenance hash audit | ❌ NOT SHIPPED | Some PASS verdicts have thin evidence |

**v10 score: 0/11 — all NOT SHIPPED (just authored)**

---

## Summary table

| Version | Resolved | Partial | Missing | Total |
|---|---|---|---|---|
| v3 | 5 | 0 | 0 | 5 |
| v4 | 5 | 2 | 0 | 7 |
| v5 | 8 | 1 | 0 | 9 |
| v6 | 9 | 4 | 3 | 16 |
| v7 | 6 | 1 | 2 | 9 |
| v8 | 7 | 0 | 0 | 7 |
| v9 | 7 | 0 | 0 | 7 |
| v10 | 0 | 0 | 11 | 11 (just proposed) |
| **Total (v3-v9, excluding v10 proposals)** | **47** | **8** | **5** | **60** |

47/60 (78 %) of historical proposals shipped, 8/60 (13 %) partial, 5/60 (8 %) still missing.

---

## The 5 historical items still missing (carried forward to v10 for visibility)

1. **v6 P1 `pad_drive_high_active_check`** — v7 P1.1 `tristate_active_drive_check` covers FPGA target with protocol-mode guard, but v6 P1 was specifically about ASIC-side pad drive strength. Distinct axis. Not yet covered.

2. **v6 D1 `auto_diagnostic_led_synth` skill** — would auto-add LED diagnostics to FPGA wrapper for board-level visibility into FSM stuck-states. Useful but never shipped.

3. **v6 D2 `oracle_bytewise_dump` MCP tool** — would burn a known-PASS oracle SOF + dump every byte usb-hid-tester sees as ground truth. Closest existence is `eda_pass_reference_scope_diff` (different mechanism). v0.108 round 1 debug would have been minutes instead of hours with this tool.

4. **v7 P2.1 `dispatcher_response_size_table_audit.py`** — cross-check `cmd_dispatch.sv` `resp_len` assignments against L9 declared `response_size`. Catches off-by-one in response size that the byte_oracle gate may also catch but more directly.

5. **v7 P2.2 `dispatcher_awake_gate_check.py`** — verify dispatcher gates non-wake commands behind `awake_q`. Per-protocol-mode requirement.

Plus 4 v6 partial items still need full closure:
- T1 OpenROAD pdngen specialnets — partial via v0.106
- **T2 KLayout DRC layermap fix** — STILL BROKEN, deferred for 6+ versions, root cause of waiver 28. Highest priority. Lifted to v10 P0.1.
- T3 IR-drop default PDN stripe — partial; KeyFoundry techlef gap independently blocks
- C1 cmd_response_byte_oracle — gate exists but L10 vector generation not auto

---

## Trend analysis

**v3-v5 cycle (5 → 9 items)**: hardware-bug-driven, all single-purpose deterministic gates. Resolution rate 18/21 = 86 %.

**v6 cycle (16 items)**: largest backlog. Mixed deterministic gates + MCP tools + skill enhancements + tool fixes. Resolution rate 9/16 = 56 % (+4 partial). The 3 missing + 4 partial reveal that **plugin development is bottlenecked on tool / framework / mcp work**, not on writing more deterministic gates. Gates shipped reliably; tools didn't.

**v7 cycle (9 items)**: process-correction backlog (after v0.108 fresh-agent revealed coverage gaps). Resolution rate 6/9 = 67 %. The 2 missing P2 items are both follow-on dispatcher checks — minor.

**v8-v9 cycle (14 items, both shipped in v0.109/0.110/0.111)**: enforcement infrastructure backlog. Resolution rate 14/14 = 100 %. Why so high: structural enforcement is single-purpose code that either compiles and runs or doesn't. No fuzzy borders.

**v10 cycle**: just authored. Resolution rate 0/11. Many items are framework-level (MCP reliability, KLayout fix, FINAL_REPORT generator) — historically the harder category to close.

---

## Recommended priority for v0.112+ release planning

Sort by `(severity × cross-project frequency × age) - implementation_difficulty`:

1. **v10 P0.1 / v6 T2** — KLayout L_lname fix. **Highest priority**: every custom-PDK project hits this; deferred 6+ versions; closes waiver 28 single-handedly.
2. **v10 P0.3** — Stop hook next-turn phrasing validation. Low effort, closes the only enforcement hole left.
3. **v6 D2** — `oracle_bytewise_dump` MCP tool. Hardware-debug productivity multiplier.
4. **v10 P1.4** — MCP server reconnect. Reliability foundation.
5. **v10 P0.2** — Cascading-waiver auto-propagation. Quality-of-life but reveals true root-cause count.
6. **v10 P1.1** — Auto-trigger A1-A8. Round 4 lesson — should have been automatic.

The remaining items are nice-to-have or already partially covered; can wait for v0.114+.
