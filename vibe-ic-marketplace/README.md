# Vibe-IC Marketplace — **v1.0** (open marketplace foundation)

**AI-Native IC Design plugins for Claude Code — Vibe Coding for ASIC**

> From natural-language dialogue to tapeout-ready GDS, driven by AI agents with EDA tools as callable execution engines — **with gates that catch fabricated artefacts**.

---

## Open marketplace surface (v0.85 → v1.0, 2026-04-26)

The full open-platform stack ships in this release. Anyone can publish
plugins to a registry (reference deployment target: `https://vibeic.ai/api/v1`),
and any developer can install them — with cryptographic signature
verification, automatic trust-tier scoring, encrypted-IP support, and
per-call billing. See:

- [`docs/design/ROADMAP.md` § 6](../docs/design/ROADMAP.md) — open-platform vision
- [`docs/design/plugin_platform_spec.md`](../docs/design/plugin_platform_spec.md) — plugin.yaml + CLI + registry layout
- [`docs/design/registry_api.md`](../docs/design/registry_api.md) — HTTP protocol
- [`docs/design/encrypted_ip_spec.md`](../docs/design/encrypted_ip_spec.md) — AES-256-GCM IP artifacts
- [`docs/design/release_spec.md`](../docs/design/release_spec.md) — MCP tool hand-off + billing rail + v1.0 frozen schemas

CLI quick reference:

```bash
# Local lifecycle (no registry needed)
vibe-ic plugin keygen     --out ~/.vibe-ic/keys/me.pem
vibe-ic plugin pack       ./my-plugin --out my-plugin-1.0.0.tgz --sign ~/.vibe-ic/keys/me.pem
vibe-ic plugin validate   my-plugin-1.0.0.tgz
vibe-ic plugin install    my-plugin-1.0.0.tgz [--verify-sig pubkey.pem]
vibe-ic plugin list / info / uninstall

# Registry (default: vibeic.ai; override with VIBE_IC_REGISTRY_URL)
vibe-ic plugin login      --namespace my-org --secret ...
vibe-ic plugin publish    my-plugin-1.0.0.tgz
vibe-ic plugin search     "spi"
vibe-ic plugin install    my-org/my-plugin                     # registry resolves
vibe-ic plugin yank       my-org/my-plugin@1.0.0 --reason ...

# Encrypted IP (v0.95)
vibe-ic plugin ip keygen  --out customer-key.bin
vibe-ic plugin ip encrypt secret.v --key customer-key.bin
vibe-ic plugin install    vendor/my-ip --ip-key customer-key.bin

# MCP tool catalogue (v1.0; mcp-eda-server reads ~/.vibe-ic/mcp_tools.json)
vibe-ic plugin mcp-tools  list
vibe-ic plugin mcp-tools  show

# Billing rail (v1.0)
vibe-ic plugin billing record  --namespace V --plugin-id P --version V \
                               --mcp-tool-name T --cost-cents N
vibe-ic plugin billing report  --since 30d
```

**Three plugin layers** (`layer:` field in `plugin.yaml`):

| Layer | What it carries | Examples |
|-------|-----------------|----------|
| `exp` | K1-K5 entries, PRACTICAL_NOTES, T5/T6 captures, decision_log | `reference-plugins/example-exp/` |
| `ip`  | hard / firm / soft IP + `ip_metadata.yaml` (encryptable) | `reference-plugins/example-ip/` |
| `eda` | third-party MCP EDA / device tool stub | `reference-plugins/example-eda/` |

**Reference server** (deployable to vibeic.ai):
```bash
python3 vibe-ic-marketplace/plugins/vibe-ic-d/programs/vibeic_registry_server.py \
    --port 8090 --state-dir /var/lib/vibeic-registry
```

Stdlib-only (sqlite3 + http.server). Run behind nginx for HTTPS.

**Acceptance gates** (run them on a clean machine; exit 0 = release ready):
```bash
python3 vibe-ic-marketplace/plugins/vibe-ic-d/programs/acceptance_gate_cli.py   # 8 steps
python3 vibe-ic-marketplace/plugins/vibe-ic-d/programs/acceptance_gate_registry.py   # 13 steps
python3 vibe-ic-marketplace/plugins/vibe-ic-d/programs/acceptance_gate_full.py   # 15 steps
```

---

**v0.76 highlights** (2026-04-25, clean-slate fresh-agent benchmark close-out):

5 gaps surfaced by the v075noris_clean fresh-agent run (clean-slate trial: a fresh agent built IC-A from input docs alone, hit USB-HID tester first-pass PASS, but flagged concrete plugin gaps):

1. **`sustained_vs_edge_check`** — flag RTL using edge-detect when spec text says "sustained / 維持 / hold / continue". Catches the `cc_reset` edge-vs-sustained class of bug independently rediscovered by the fresh agent.
2. **`transient_signal_latch_check`** — flag 1-cycle pulses produced by handshake-gated drivers that get read by multi-cycle FSM consumers without latching. Catches the `tx_phy last_byte` race class.
3. **`sv_compat_check` extended** with iverilog-14.0 anti-patterns: SV `package` declarations and type-qualified parameters (`parameter int unsigned`) — both rejected by iverilog 14.0 even with -g2012, so flag pre-synth.
4. **`doc_extract` program** — wraps `pdftotext` + `libreoffice` + `openpyxl` behind one Python script for vendor doc conversion (.doc/.docx/.pdf/.ppt/.pptx/.xls/.xlsx → text + JSON). Eliminates the same shell pipeline every fresh agent rebuilds.
5. **`plugin_clean_slate_test.sh` harness** — post-build verification gates (deliverable presence, md5 distinctness vs baseline, RTL filename diversity, hardware verdict) so fresh-build regressions surface in CI, not on next IC.

**Counts**: skills **71**. Programs 115 → **118**. plugin.json: 0.75.0 → **0.76.0** (core + d). Pytest: **1791 passing** (v0.76 programs ship without pytest coverage; tests pending in v0.77). mcp-eda-server: **v2.6.1** (24 EDA + 6 device + new `eda_doc_extract` = **31 tools**).

**Caveats** (v0.77 backlog):

- 3 new programs (`sustained_vs_edge_check` / `transient_signal_latch_check` / `doc_extract`) shipped without pytest coverage.
- `doc_extract` lives only as a `programs/*.py`, not as a `skills/doc-extract/SKILL.md` — invocation is via direct CLI / `eda_doc_extract` MCP tool, not slash-command.
- `sv_compat_check` iverilog-14.0 anti-pattern extension hasn't been pytest-validated against existing fixtures.

**v0.75 highlights** (2026-04-25, meta-hygiene + v068 on-bench follow-up):

**1. `practical_notes_specificity_check` meta-gate** — enforces `feedback_general_not_specific` across every `vibe-ic/skills/*/PRACTICAL_NOTES.md`. HARD_RULES catch chip codenames, tester product names, specific OTP filenames, dated validation tags, vendor PDF filenames, HID command-byte declarations, specific PASS markers, chip-specific pin names, iteration codenames naming a chip, and custom PDK codenames. SOFT_RULES warn on softer provenance leakage (e.g., "from <chip> debug"). `<!-- specificity-allow: <reason> -->` escape hatch for intentional examples. `--strict` promotes SOFT→ERROR. `--paths` for scoped runs. **18 pytest**.

**2. PRACTICAL_NOTES.md cleanup — 29 files** — applied the meta-gate to existing notes and rewrote project/vendor-specific markers to generic equivalents ("Real bug from <chip> debug (BUG #N):" → "Observed failure mode:", specific tester names → "protocol tester", vendor foundry codenames → "custom vendor 180nm PDK", dated validation tags → "<calibration date>"). Before: 37 findings across 29 files. **After: errors=0, warnings=0 on 37 files scanned.** Retained open-source PDK names (GF180/SKY130) and generic plugin-version numbers.

**3. v068 on-bench RTL follow-up (4 bugs surfaced on USB-HID tester)** — scope-level bisect on the bench turned up four RTL behaviours that passed v0.74 structural gates but misbehaved on real hardware. Fixes are in the fresh-agent's own RTL under `phase2+3_v068/rtl/`:
   - **Bug 1 + 2.2** (wake pulses don't stop after command response / no pulses at POR) — `wake_ctrl.v`: pre-load `cnt` so first pulse fires ~100µs after POR (not immediately); accept `break_restart_i` to re-clear `frozen_o` on long-low. **Hardware verified ✅**.
   - **Bug 2.3** (trailing BR on every IC response) — `cmd_fsm.v`: drop `tx_send_br_o <= 1'b1` in S_TX. **Sim verified ✅**, hardware re-verify pending.
   - **Bug 3** (0x70 doesn't write register) — `cmd_fsm.v`: `reg_state_ph_pt <= rx_buf[1] & 8'hE0` in the 0x70 case. **Sim verified ✅**, hardware re-verify pending.
   - **Bug 4** (500 ms low doesn't restart DUT) — `rx_decoder.v`: new `break_restart_o` pulse when long-low exceeds `BREAK_RESTART_MIN = 5_000_000` cycles (100 ms @ 50 MHz). Threshold was 6 ms in first draft; raised to 100 ms on-bench because USB-HID tester normal test cycles emit long-lows that triggered a false restart. **Sim verified ✅**, hardware re-verify pending.
   - Baseline USB-HID tester 5/5 `byte[6]=0xF2` PASS still holds.
   - New per-module testbenches: `tb_wake_ctrl_v075.v` (5/5), `tb_rx_break_v075.v` (2/2), `tb_bug3_70_regwrite_v075.v` (ALL PASS).

**4. `fpga_wrapper_input_polluter_check` Phase-2a gate** — flags FPGA wrappers that AND/OR multiple `inout` pins where typically only one is wired to bench hardware. Generic across protocols (single-wire ID buses, 1-Wire, I2C SDA, RGMII RX_CTL hand-tied). Catches the sim-PASS / hardware-FAIL trap surfaced by a fresh-agent BENCH-A/IC-A run that defensively probed 5 candidate GPIOs (V10 + W9 + V9 + W10 + W8); the floating ghost pins poisoned the input via weak-pullup noise, breaking break/symbol detection. The fixed wrapper (single connected pin only) hits USB-HID tester 5/5 PASS. Optional `--qsf` arg escalates WARN→ERROR when the QSF binds fewer pins than the RTL ANDs together. Allowlist: `// fpga-input-polluter-allow: <reason>`. Wired into `phase2_phase3.yaml` step 2 with `condition_files_exist: ["rtl"]` guard. **24 pytest**.

**Counts**: Skills **71** (unchanged). Programs 112 → **115** (+`practical_notes_specificity_check` + `fpga_wrapper_input_polluter_check` + `phase2a_gate_contract_check` carried from v0.74 tail). plugin.json: 0.74.0 → **0.75.0** (core + d). Pytest: 1749 → **1791 passing** (+18 meta-gate, +24 polluter check). mcp-eda-server: **2.3.2** (unchanged).

**Key commits**: `c1a0fa6f` (clean 29 PRACTICAL_NOTES, push), `775548b5` (meta-gate + 18 tests), `59f952d2` (`BREAK_RESTART_MIN` 6 ms → 100 ms + hardware-verified `.sof`), `a478b7b8` (v068 RTL 4-bug fixes + sim), `2fd3c33c` / `f1644870` (v0.74 follow-up: `postcheck_pass_only` no-op bug + autopatch 26 tests).

**What v0.75 does NOT yet do** (candidates for v0.76):

- Hardware re-verify of Bug 2.3 / 3 / 4 on DE10-Lite + USB-HID tester (only Bugs 1 + 2.2 got back on the bench after the fix).
- 5 candidate Phase-2a gates the 4 bugs suggest: `wake_freeze_clearability_check`, `por_to_first_wake_ready_check`, `response_frame_layout_check`, `cmd_write_register_sideeffect_check`, `break_restart_detector_check`.
- `testbench-gen` PRACTICAL_NOTES section on "dynamic-behavior coverage" — the class of bug that compiles + passes static gates but fails on hardware (Bug 2.3 class).
- Periodic scheduled re-run of `practical_notes_specificity_check` against main to prevent drift.

**v0.74 highlights** (2026-04-25, hardware-proven release):

The fresh-agent-generated RTL for BENCH-A/IC-A passes USB-HID tester hardware **5/5 rounds** (`byte[6]=0xF2` + 17-byte MSN) after 9 concrete bug classes were root-caused via scope-level bisect. Every fix is in the fresh-agent's own RTL (`phase2+3_v068/rtl/*.v` — `cmd_fsm`, `tx_encoder`, `rx_decoder`, `otp_reader`, `wake_ctrl`, `ic-a_top`) with zero v052 code ported in. The 9 bug classes are now codified as **7 new generic Phase-2a structural gates**, all IC-agnostic (apply equally to AID/MID, I2C, SPI, UART, 1-Wire, USB HID).

**The 7 new Phase-2a gates** (vibe-ic-d/programs/):

| Gate | Catches | pytest |
|---|---|---|
| `internal_vs_external_timing_check` | L8 missing host-side vs DUT-side timing split | 10/10 |
| `rsp_example_otp_consistency_check` | L3 rsp_example bytes ≠ L11 OTP / wrong CRC | 11/11 |
| `threshold_range_contiguity_check` | Discrete classification ranges with gaps | 12/12 |
| `spec_response_delay_check` | RTL missing tSRS / tIRT wait state | 7/7 |
| `nba_addr_read_race_check` | FSM addr/data pipeline race | 8/8 |
| `periodic_timer_vs_rx_activity_check` | Wake/keepalive not reset on RX activity | 8/8 |
| `memory_read_pipeline_check` | Memory with registered read, undocumented latency | 9/9 |

All 7 are wired into `phase2_phase3.yaml` step 2 ("Lint") via `optional_program_exit_zero` with `condition_files_exist` guards, so they fire only when the input spec document is present — non-protocol ICs (pure digital, analog-heavy, mixed-signal without single-wire protocol) see the gates as silent no-ops.

**Phase-1 parallel work stream (merged)**: K1/K2/K5 UUID markers from Phase-2 RTL, bulk parsers, model-neutral NL ingest, docs SKILL.md sync + compliance expansion. Commits `c9fce35a` → `6508d4dc`, author: phase1 agent.

**Counts**: Skills **71** (unchanged). Programs 105 → **112** (+7 Phase-2a gates). plugin.json: 0.73.0 → **0.74.0** (core + d). Pytest: **1146 passing** (+ 65 new today). mcp-eda-server: **2.3.2** (unchanged — v0.73 content carried forward).

**Reproducibility**: the fresh-agent `phase2+3_v068/fpga/ic-a.sof` is in the repo. To reproduce the USB-HID tester PASS:
```bash
cd 1st_benchmark_bench-a/phase2+3_v068/fpga/
quartus_pgm -c "USB-Blaster [1-2]" -m jtag -o "p;output_files/ic-a.sof"
printf 'q\n' | timeout 3 ../../../vendor_ref/hid_tool    # REQUIRED — reset USB-HID tester between burns
sleep 2
printf 's\n' | timeout 5 ../../../vendor_ref/hid_tool    # expect byte[6]=0xF2
```

**v0.74 follow-up** (commit `f1644870`, 2026-04-25): Closed 4 deliberately-deferred items the phase1 agent flagged.

1. **`_shared/skill_compliance_check.py` `postcheck_pass_only` no-op bug** — the cross-check rule used by **69 / 71** compliance.yaml was silently returning `[]` when the `// Post-checks: rtl_hygiene_lint=…, fsm_error_invariant=…` header was absent, so agents could bypass the check by simply omitting the comment. The fix makes a missing or partial header a hard FAIL, and `gen_integration_fixtures.py` now auto-injects the header for any skill whose YAML carries the rule (so the three regenerated golden fixtures — `spec-to-rtl`, `integration-spec-gen`, `flow-orchestrate` — stay valid). `tests/test_driver_core.py` updated: `test_no_header_skipped` → `test_no_header_flagged`; new `test_partial_header_does_not_pass`.
2. **`phase1_k5_quality_check.py` K5-T/U/V Stage-C3 consumer** — confirmed already implemented (lines 642-721) AND tested by `test_phase1_k5_fact_uuid_markers.py` (166 LOC, 7 tests covering known/unknown UUID, value match/mismatch, hex-literal coercion, multi-marker conflict, missing index). No code change required; phase1 agent's "未實作" was incorrect.
3. **`tools/training/phase1_k5_autopatch.py`** — fully implemented (976 LOC, 8 patchers) but had **no test**. Added `tools/training/test_phase1_k5_autopatch.py` — **26 tests** covering each K5 patcher (A/C/D/G/I/K/O/Q), helpers (`pick_states_for`, `pick_port_template`), `patch_all` integration, idempotency, and CLI smoke.
4. **`spec-to-rtl` Stage-C2 RTL marker emission** — deferred to **v0.75** (Phase 2b scope). The consumer side already exists; the sender that should emit `// phase1-fact: <uuid> path=<L.path> source=<provenance>` markers from spec-to-rtl per `docs/design/PHASE1_FACT_UUID_PROPOSAL.md` §3.1-3.3 is the missing half.

**Counts after follow-up**: plugin pytest **1748 → 1749** (one new postcheck test); autopatch pytest **+26**.

**What v0.74 does NOT yet do** (candidates for v0.75):

- Gates covering v052 Round-1 bug classes (rising-edge classifier, sequential-vs-combinational CRC, MAC length validation, 3-stage synchronizer, opcode byte-indexing). Today's 7 gates catch structural RTL bugs; v052's Round-1 required a different class of gate (correctness-level linting).
- Phase-2b testbench enhancement that injects spec-declared timing (not RTL's own constants) to catch sim-self-consistent-but-hardware-wrong bugs — the exact failure mode that made v068's `tb_l10_cases.v` report 14/14 PASS while hardware was 0/3 FAIL.
- Schema-level `generated_docs/L*.json` completeness checks (e.g., L3 must list every opcode the IC claims to support; L8 must list every tXXX timing parameter mentioned in the FRS).

**v0.72 highlights** (2026-04-24, merge v0.70 residual closure + v0.71 v0.63-ROADMAP shake-down):

v0.70 and v0.71 were built in parallel on separate workstreams — v0.70 closed the four v0.69 Phase-3 residuals (Yosys gate wiring, stub detection, subprocess fallback, deprecation lock) while v0.71 shook down the v0.63 ROADMAP (PRACTICAL_NOTES on 5 EDA-fallback skills + `custom_metal_prefix` schema fix via mcp-eda-server 2.3.1). They don't overlap on code, only on version metadata. v0.72 merges both.

**Carry-over from v0.70** (new code files — Phase-3 residual closure):

- **Yosys gates wired into `flow_compliance_check.py` as pre-PnR HARD gates.** `yosys_hilomap_required_check` + `yosys_script_template_check` run against the synth `.ys`; failure injects a synthetic gate step and returns FAIL with the `DRT-0305 zero_ GROUND` remediation hint. `--skip-yosys-gates` escape hatch for sim-only flows, auto-skipped on `--stage 1`. +10 tests.
- **`drc_rdb_summarize` emits `stub: true|false`** to distinguish the v0.69 normalizer's fabricated "0 violations" stub from a real KLayout `.rpt`. Detected via `_STUB_MARKER_RE` + `_STUB_HEADER_RE`. RDB format always `stub: false`. +5 tests.
- **`def2gds` cascades** `pya` → `klayout -b` subprocess → DeviceError `KLAYOUT_NOT_FOUND` body. Non-Docker hosts without the in-process `pya` bindings now work via a small Ruby driver (KLayout's `-r` runs Ruby, not TCL — corrected from the v0.69 spec). `--prefer-subprocess` flag for forced-fallback testing. +8 tests (1 skipped on CI without pya).
- **New `openroad_tcl_deprecation_check.py`** — recursively greps `*.tcl` + embedded TCL for `-bottom_routing_layer` / `-top_routing_layer` / `write_gds` / `set_global_routing_layer_adjustment`. Documentary-line suppression (`removed` / `deprecat` / `replaces` tokens) so SKILL.md prose naming deprecations doesn't false-positive. Plugin self-check against own tree: PASS. +11 tests.

**Carry-over from v0.71** (v0.63 ROADMAP consolidation):

v0.63 (released 2026-04-24) outlined 14 IC-agnostic deliverables distilled from the v052 fresh-agent Phase 2+3 debug. Over v0.64-v0.70 those items were drafted, integrated, and wired into other gates (`rtl_precheck_gate` aggregator landed in v0.66; v0.69 Phase-3 hardening added `def2gds`, `drc_rdb_summarize`, Yosys hilomap gates; v0.70 added K3 typical_scaffolds). **v0.71 is the v0.63 shake-down release**: every one of the 14 items now passes its own contract tests end-to-end, and the one residual plumbing gap (MCP tool schemas not exposing `custom_metal_prefix`) is closed.

**Changes shipped in v0.71**:

- **`mcp-eda-server` v2.3.0 → v2.3.1**: `custom_metal_prefix` option added to every custom-PDK tool schema (`eda_synth`, `eda_pnr`, `eda_gds`, `eda_sta`, `eda_extraction`). The `pdkConfig()` branch already honoured `customOpts.custom_metal_prefix` (v0.63 fix); now MCP clients can *set* it through the declared schema instead of relying on the hardcoded `"met"` fallback. No runtime behaviour change on existing gf180/sky130 configs.
- **5 skill `PRACTICAL_NOTES.md` files added**: `open-rcx-fallback`, `drc-from-lef`, `lvs-open-source`, `atpg-name-harmonize`, `lef-psm-patch`. Each documents the PDK-specific quirks the author hit during v052 (metal-layer naming, VIA resistance placement, Fault escape identifiers, Magic `.tech` availability, OpenROAD version drift). The `SKILL.md` files already carried the reference-card content; `PRACTICAL_NOTES.md` is where the battle-scar notes now live.
- **Exit-code hardening** for 5 RTL pattern auditors: `tristate_self_rx_mask_check`, `pulse_decoder_edge_check`, `packet_length_check_present`, `otp_write_lock_gate_check`, `l12_sequence_implementation_check` all now exit 2 (not 1) when the `--rtl-dir` target is missing, matching the vibe-ic-d contract `0 PASS / 1 FAIL / 2 input-missing`. Detected via `category == "IO"` findings; existing pytests (API-level) unchanged.
- **Contract re-verification** of all 8 v0.63 programs: each has working `--help` (exit 0), standard `0 / 1 / 2` exit-code contract, companion pytest suite (72 tests total, all PASS). No hardcoded `IC-A` / `USB-HID tester` / `PIN_V10` / `id_bus` / `m18e80pm180su` runtime strings — provenance references in docstrings/tests preserved.

**What v0.71 does NOT do** (next release candidates):

- New programs / new skills (v0.71 is consolidation, not breadth expansion).
- v052-specific calibration of the open-source EDA skills — `open-rcx-fallback` and `drc-from-lef` remain first-order/subset per design. Calibration is PDK-specific and cannot be open-sourced in the plugin.
- Plugin-side response to MCP `prompts` primitive.

**The 14 v0.63 ROADMAP items as shipped in v0.71** (path + contract status):

| # | Item | Path | --help | pytest |
|---|------|------|--------|--------|
| 1 | `tristate_self_rx_mask_check` | `plugins/vibe-ic-d/programs/tristate_self_rx_mask_check.py` | 0 | 8 / 8 |
| 2 | `pulse_decoder_edge_check` | `plugins/vibe-ic-d/programs/pulse_decoder_edge_check.py` | 0 | 7 / 7 |
| 3 | `packet_length_check_present` | `plugins/vibe-ic-d/programs/packet_length_check_present.py` | 0 | 7 / 7 |
| 4 | `otp_write_lock_gate_check` | `plugins/vibe-ic-d/programs/otp_write_lock_gate_check.py` | 0 | 8 / 8 |
| 5 | `l12_sequence_implementation_check` | `plugins/vibe-ic-d/programs/l12_sequence_implementation_check.py` | 0 | 11 / 11 |
| 6 | `tester_oracle_health_check` | `plugins/vibe-ic-d/programs/tester_oracle_health_check.py` | 0 | 10 / 10 |
| 7 | `hw_vs_rtl_verdict_check` | `plugins/vibe-ic-d/programs/hw_vs_rtl_verdict_check.py` | 0 | 10 / 10 |
| 8 | `plugin_self_leak_check` | `plugins/vibe-ic-d/programs/plugin_self_leak_check.py` | 0 | 11 / 11 |
| 9 | `open-rcx-fallback` skill | `plugins/vibe-ic/skills/open-rcx-fallback/` | 0 | - |
| 10 | `drc-from-lef` skill | `plugins/vibe-ic/skills/drc-from-lef/` | 0 | - |
| 11 | `lvs-open-source` skill | `plugins/vibe-ic/skills/lvs-open-source/` | 0 | - |
| 12 | `atpg-name-harmonize` skill | `plugins/vibe-ic/skills/atpg-name-harmonize/` | 0 | - |
| 13 | `lef-psm-patch` skill | `plugins/vibe-ic/skills/lef-psm-patch/` | 0 | - |
| 14 | `custom_metal_prefix` schema | `mcp-eda-server/src/index.js` (5 tools) | - | - |

**v0.72 counts** (after merge): Skills 71 (unchanged). Programs **105** (v0.70 adds `openroad_tcl_deprecation_check`; v0.71 adds no new programs). plugin.json: **0.72.0** (both core + d) — skipping 0.71.0 to avoid ambiguity with the previously-pushed v0.71 label. mcp-eda-server: **2.3.1** (from v0.71's `custom_metal_prefix` schema fix). Plugin tests: pytest suite combines v0.70's 1658 + v0.71's 72 contract tests; full recount after this commit. Triangle: **71/71**. release_audit: 0 problems.

**v0.69 highlights** (2026-04-24, Phase-3 hardening — close the backlog surfaced by the v068 fresh-agent OpenROAD run):

The v068 fresh-agent Phase 3 (OpenROAD PnR + KLayout DRC + GDS merge) tripped on six plugin-level issues mid-run. The agent patched them by hand and shipped the GDS, but left a backlog for the plugin itself. v0.69 closes all six.

- **New skill `def2gds/`** (`vibe-ic/skills/def2gds/` + matching d-side triangle). OpenROAD ≥ 2023 dropped `write_gds`; the canonical Phase-3 GDS generation path now uses KLayout (via `pya` Python bindings or `klayout -b` batch) to merge cell GDS with a routed DEF. Skill takes `--def` / `--tech-lef` / `--cell-lef` / `--cell-gds` / `--layer-map` / `--out` / `--top` and emits the merged GDS. Logic ported from the v052 `def2gds_v2.py` reference, generalised (no hard-coded project paths / design names / m18e80pm180su assumptions). +1 to skills triangle (70/70 → 71/71). Compliance + tests as usual.

- **New program `drc_rdb_summarize.py`** (`vibe-ic-d/programs/`). KLayout DRC emits `.rdb` (XML report database) or `.rpt` (plain text) depending on invocation; neither is a human-friendly summary. This program parses both formats and returns a single JSON `{total_violations, per_rule, source_file, clean}` — exit 0 on 0 violations, exit 1 on any, exit 2 on arg/IO error. Integration tested against v068's actual DRC output. +13 tests.

- **New program `openroad_drc_report_normalize.py`** (`vibe-ic-d/programs/`). Closes the "empty `drc_route.rpt` means what?" ambiguity — OpenROAD `detailed_route -output_drc <path>` writes either 0 bytes or skips the file entirely on clean runs. This program normalizes missing/empty to a canonical `"Total violations : 0"` stub so `drc_rdb_summarize` can parse uniformly. +7 tests including an integration test chaining both programs.

- **New program `yosys_hilomap_required_check.py`** (`vibe-ic-d/programs/`). Enforces CLAUDE.md rule 4 — Yosys `.ys` synth scripts must contain `hilomap` AFTER `techmap` and BEFORE `write_verilog`. Without it, OpenROAD `detailed_route` crashes with `DRT-0305 zero_ GROUND` on the unmapped tie net (exactly what v068's agent hit mid-run). Verified: v068's actual `scripts/synth.ys` (the agent's hand-fixed version) PASSes. +8 tests covering clean / missing-hilomap / ordering-wrong / commented-out.

- **New program `yosys_script_template_check.py`** (`vibe-ic-d/programs/`). Complementary check for the broader Yosys script shape: `-sv` + `-flatten` + `hilomap` all present per CLAUDE.md rules 4 + 7. `--allow-no-sv` for Verilog-2001-only designs, `--simulation-only` for sim scripts that don't need silicon-bound cell mapping. +11 tests.

- **Deprecated OpenROAD flags swept** — `-bottom_routing_layer` / `-top_routing_layer` removed from `global_route` / `detailed_route` in OpenROAD 2024+. Exhaustive grep confirmed no plugin occurrence today (v068 had them in a prior checkpoint; current tree is already clean). v0.70 will ship a `openroad_tcl_deprecation_check.py` to lock the absence.

**Counts**: Skills 70 → **71** (+def2gds). Programs 100 → **104** (+4). Plugin tests: 1579 → **1625 passed / 0 failed** (+46). Triangle: **71/71**. release_audit: 0 problems. plugin.json: 0.68.0 → **0.69.0** (both core + d). mcp-eda-server: 2.3.0 (unchanged — v0.69 is plugin-side only).

**v0.70 backlog surfaced** by the v0.69 agent:
- Wire the two Yosys gates into `flow_compliance_check.py` as hard pre-PnR gates (currently ad-hoc CLI).
- `drc_rdb_summarize` JSON gets a `stub: true` field when parsing the normalized "0 violations" stub (so audit trails distinguish real-KLayout output from wrapper output).
- `def2gds` second-path fallback via `klayout -b` subprocess (no in-process `pya` import) — usable outside the Docker image.
- `openroad_tcl_deprecation_check.py` to permanently lock Item 4's sweep.

**v0.68 highlights** (2026-04-24, MCP `resources` first-class in the device framework):

MCP has two distinct primitives — **tools** (actions; the AI invokes them to do something) and **resources** (read-only state; the AI fetches them via URI to know something). v0.61-v0.67 shipped tools; `resources` was missing. Every "what state is the scope in?" query had to burn a tool invocation, clutter the tool list, and pollute the AI's chain of thought with non-action metadata. v0.68 closes the gap.

**`mcp-eda-server` v2.2.0 → v2.3.0** — one schema addition, one registry path, one reference implementation:

- **`resources[]` (top-level, optional)** on the manifest. Each entry declares `name` / `uri` / `description` / `driver` / `tool_mode` / `mime_type` / `timeout_sec`. URIs follow the `<category>://<vendor-device>/<resource-name>` convention (e.g. `scope://keysight-dso-x-3014t/current_setup`).

- **Auto-registration** in `_registry.js`: after tools, loop through `resources[]` and call `server.registerResource()` (newer SDK API) with fallback to `server.resource()` for older SDKs. Handler spawns the driver with the resource's `tool_mode` via `--mode <mode>`, reads stdout, serializes to the MCP `contents[]` envelope. Vendor attribution (`[<category> · by <full_name> <homepage>]`) surfaces in the description exactly like for tools. Startup log now reads `registered N tool(s) + M resource(s) from K manifest(s)`.

- **One reference resource shipped**: `keysight-scope/manifest.json` declares `current_setup`. `driver.py` gains `mode_read_state()` — runs SCPI queries only (no acquisition arm), returns live `idn_string` / `channels_enabled[]` / `timebase` / `trigger` / per-channel scale/offset/probe/coupling/bandwidth. Verified end-to-end against the connected DSO-X 3014T: returns real-time configuration via structured JSON, no tool call, no side effect.

**Smoke test `test/test_devices_registry.sh`**: 28/28 → **33/33 PASS** (+5 new checks: resources-section required keys, URI regex, live read_state output shape, manifest-validator resource rules, fake-server harness confirming registration count).

**What v0.68 does NOT do** (saved for v0.69 / v0.70):
- Resources on `terasic-de10lite/` (e.g. `fpga://.../connection_status`) or `vendor-usb_hid_tester/` (e.g. `tester://.../hidraw_node`) — the framework supports them now but the reference drivers don't ship resources yet.
- MCP `prompts` (the third primitive) — pre-canned templates like "measure rise time on CH1".
- `pyvisa-py` optional fallback for generic SCPI scopes.
- Windows / macOS driver variants (framework supports via `supported_platforms`; no vendor has shipped one yet).

**Notes for future implementers** (captured by the Track agent):
- MCP SDK exposes both `registerResource()` (newer, takes `config.title`) and `resource()` — registry feature-detects.
- This scope returns `":TRIG:EDGE:SLOPE?"` as `"NEG"` (3-letter SCPI SHORT form), while `configure()` writes `"NEGATIVE"` (LONG form). Not a bug — SCPI spec — but round-trip equality tests should normalize.
- `:CHANn:BWLIMIT?` returns `"1"` / `"0"`, not `"ON"` / `"OFF"`. Kept raw in `current_setup`; v0.69 could normalize.

Skills 70 (unchanged). Programs 100 (unchanged). plugin.json: 0.67.0 → **0.68.0** (both core + d). mcp-eda-server: **2.2.0 → 2.3.0**. Plugin tests: **1579 passed / 0 failed** (unchanged — v0.68 is MCP-side only). MCP smoke: 28 → **33/33**. Triangle: **70/70**. release_audit: 0 problems.

**v0.67 highlights** (2026-04-24, mcp-eda-server device framework → production posture):

A short follow-up research pass on existing MCP hardware servers (UnitApi/mcp, IoT-Edge, MCP4EDA, Arduino MCP, awesome-mcp-hardware) produced three clear borrow-worthy patterns: IVI Foundation instrument-class alignment, OS-platform filtering via manifest, and structured error taxonomy. v0.67 lands all three on the `mcp-eda-server` side. The plugin tree itself is unchanged.

**`mcp-eda-server` v2.1.0 → v2.2.0** — four schema additions on the existing device framework:

- **`ivi_class`** (top-level, optional) — IVI Foundation instrument-class tag when the device fits a standard class: `IviScope`, `IviDmm`, `IviFgen`, `IviDCPwr`, `IviACPwr`, `IviSpecAn`, `IviRFSigGen`, `IviSwtch`, `IviPwrMeter`, `IviCounter`, `IviDigitizer`. Non-IVI devices (FPGAs / testers / cameras) simply omit. Unknown names log a warning — future IVI evolution doesn't break the registry. `scope/keysight-scope/` declares `IviScope`; the other two decline (correctly).
- **`supported_platforms`** (top-level, default `["linux"]`) — OS filter checked at server start. Drivers whose list doesn't include the running `process.platform` are skipped with `[devices] SKIP ... (platform)` rather than registered then failing at invocation.
- **`permissions`** (top-level, optional) — declarative preconditions: `require_group:<name>` (unix group), `require_binary:<name>` (binary on PATH or `$<NAME>_ROOTDIR/bin`), `require_env:<VAR>`, `require_file:<abs>`. Registry evaluates at startup; unmet conditions log `[devices] NOTE ...` as a warning but do NOT prevent tool registration — the driver itself surfaces the real error at invocation. The `permissions` list is for MCP-client discoverability, not gatekeeping. `fpga/terasic-de10lite/` declares `require_binary:quartus_pgm` + `require_group:plugdev`; `tester/vendor-usb_hid_tester/` declares `require_group:plugdev`; `scope/keysight-scope/` declares `require_group:plugdev`.
- **`mode`** per-tool (`"hw"` / `"sim"` / `"mock"`, default `"hw"`) + **`tool_mode`** per-tool renamed from the previous `mode` field (which carried the driver-dispatch keyword). Separates two conflated concepts: "what semantic mode does this tool run in" (hw/sim/mock) vs "which internal code path does the single driver binary take". `scope_periodic_pulse_check` already had `--mock-samples-csv` capability but the MCP layer couldn't see it; now a contributor can ship `<tool>_hw` / `<tool>_sim` variants side-by-side and MCP clients see the difference.

Plus the **hard rename** `timeout_ms` → `timeout_sec` (per-tool). The old key is rejected at manifest-validation time — memory rule "no backwards-compat shims", plugin is in active development, one truth per field. All three reference manifests updated.

**DeviceError taxonomy** (`mcp-eda-server/src/devices/_shared/errors.py`) — a Python base class + 7 subclasses with stable machine-readable `error_code` values: `device_not_found`, `permission_denied`, `timeout`, `protocol_error`, `vendor_tool_not_found`, `device_busy`, `invalid_argument`. Each subclass carries a `recoverable: bool` hint so AI agents can decide whether to retry. Every error-return site in all three drivers (`scope/keysight-scope/driver.py`, `fpga/terasic-de10lite/driver.py`, `tester/vendor-usb_hid_tester/driver.py`) now raises a subclass and the outer `main()` serializes to the canonical 5-field body: `{success, error_code, error, recoverable, last_seen_output}`. MCP clients can branch on `error_code` without parsing English.

**Category naming aligned to IVI**: TBD rows in `src/devices/README.md` + CONTRIBUTING.md switched from ad-hoc `signal-generator` / `power-supply` / `spectrum-analyzer` to IVI-short-names `fgen` / `dcpwr` / `specan` plus the rest (`acpwr/`, `rfsiggen/`, `swtch/`, `pwrmeter/`, `counter/`). Custom non-IVI categories stay verbose (`logic-analyzer/`, `camera/`, `mcu/`, `env/`). This is a docs + future-folder-name change; the 3 shipped directories (`scope/`, `fpga/`, `tester/`) keep their names because they already matched.

**Smoke test** `test/test_devices_registry.sh`: 17/17 → **28/28 PASS** (+11 new checks covering error taxonomy, 5-field body contract, phantom-device detection, and the `_shared/errors.py` import contract).

**What v0.67 does NOT do** (saved for v0.68): MCP `resources` / `prompts` first-class support; pyvisa-py optional fallback for scope drivers; Windows/macOS-specific driver variants (the framework now supports it; no vendor has shipped one yet).

Skills 70 (unchanged). Programs 100 (unchanged). plugin.json: 0.66.0 → **0.67.0** (both core + d). mcp-eda-server: **2.1.0 → 2.2.0**. Plugin tests: **1579 passed / 0 failed** (unchanged). MCP smoke: 17/17 → **28/28**. Triangle: **70/70**. release_audit: 0 problems.

**v0.66 highlights** (2026-04-24, enforce the auditors we already have):

**The observation**: v0.64 shipped `timer_freeze_after_state_check` — a static RTL auditor that would have caught the `wake_ctrl` periodic-wake-pulse bug before it reached silicon. But the checker lived as a standalone `--rtl-dir`-taking tool with no workflow obligation to run it. A developer could (and did) edit wake_ctrl.v, compile the SOF, burn the FPGA, and the plugin's auditor was never consulted. Having the tool without running it ≡ having no tool.

**The fix** (single-purpose v0.66):

- New program: **`rtl_precheck_gate.py`** — aggregates every v0.63/v0.64 RTL static auditor (`tristate_self_rx_mask_check`, `pulse_decoder_edge_check`, `packet_length_check_present`, `otp_write_lock_gate_check`, `l12_sequence_implementation_check`, `timer_freeze_after_state_check`) into one invocation and a single PASS/FAIL verdict. Exit 0 = every enabled auditor passes. Exit 1 = any auditor failed. L12 auditor is skipped cleanly when no `--l12-json` is supplied (it's designed that way; other 5 are mandatory). `--skip <name>,<name>` allows per-run exemption. +10 tests including a regression test that ensures an injected v052-shape buggy wake_ctrl.v reliably fires `timer_freeze_after_state_check` FAIL through the gate.

- **Wired into `mcp-eda-server` `device_fpga_de10lite_program`**: the Terasic DE10-Lite burn tool now takes four new args — `rtl_dir` (directory of .v/.sv sources for the SOF; strongly recommended), `l12_json` (optional; forwarded to l12 auditor), `allow_known_bugs` (override for intentional-bug-measurement flows), `skip_rtl_precheck` (skip entirely for pre-built 3rd-party SOFs). When `rtl_dir` is provided, the gate runs *before* the SOF-existence check and hard-blocks `quartus_pgm` invocation on any FAIL. The precheck report surfaces in the program-mode JSON response regardless of outcome so MCP clients always see which auditor reported what.

- **Post-burn scope attestation wiring**: same `device_fpga_de10lite_program` tool gains `post_burn_scope_checks` — a list of dicts forwarded to `scope_periodic_pulse_check` after a successful burn. Each dict specifies channel / span / period / expect / etc. Any scope check FAIL flips overall `success` to false and lists the failed check names in `failed_scope_checks`. This closes the other half of the wake_ctrl regression: even if pre-burn statics pass, silicon can still surprise (bad PDK corner, tool bug, etc), and a manual scope probe two days later is not good enough. Now burn → auto-probe → immediate failure notice.

- **Applied the wake_ctrl `else if (awake)` freeze-branch fix to `~/phase2+3_v052/rtl/wake_ctrl.v`** — this machine's RTL was the drifted buggy copy; the build-host had it fixed but the sync was human-manual. Post-fix, gate on v052 tree: 6/6 PASS.

**Why this is a v0.66, not v0.65.1**: behaviourally the burn tool's contract changed (new mandatory-if-provided arg `rtl_dir`, new response field `rtl_precheck`, new ability to block burn). MCP schema is backward-compatible (all new args optional), but semantically this is a defense-posture upgrade.

End-to-end verification on the real FPGA + tester + scope: before the v0.66 fix, wake_ctrl.v FAILed `timer_freeze_after_state_check` → gate correctly refused burn with `failed_auditors: ["timer_freeze_after_state_check"]`. After the fix, gate passes and `device_fpga_de10lite_program` proceeds normally.

Skills 70 (unchanged). Programs 99 → **100** (+`rtl_precheck_gate.py`). plugin.json: 0.65.0 → **0.66.0** (both core + d). mcp-eda-server: 2.1.0 (unchanged — device framework itself unchanged; one existing tool gained four optional args). Plugin tests: 1564 → **1579 passed / 0 failed**. MCP smoke 17/17 unchanged. Triangle: **70/70**. release_audit: 0 problems.

**v0.65 highlights** (2026-04-24, layer-3 hardware attestation via SCPI + vendor-extensible MCP device framework):

The v0.64 wake_ctrl bug was caught by Layer 1 (sim) — no, sim PASSed. Layer 2 (static RTL check) — yes. **Layer 3 (live silicon measurement) — also yes**, but only because a human happened to plug in a scope. v0.65 closes the gap: Layer 3 is now a programmable, scriptable, MCP-callable check.

- **Plugin: `scope-pattern-attestation` skill** + companion `scope_periodic_pulse_check` program. Talks to a Keysight DSO-X 3014T (and any InfiniiVision-class scope speaking the same SCPI dialect) over USB, captures a 50ms window on the IO line of interest, finds LOW pulses by hysteresis threshold-cross, computes consecutive-pulse gaps, FAILs when ≥2 gaps match a target period ± tolerance. **Verified live on real hardware**: detected the v0.64 wake_ctrl bug in 50ms (10 pulses, 26µs wide, 5.000-5.001ms apart — exact match to spec). +14 tests using `--mock-samples-csv` mode (CI-runnable without hardware). +1 d-side compliance triangle (skill_compliance_triangle 69 → 70).

- **MCP server: `mcp-eda-server` v2.0.0 → v2.1.0** ships a vendor-extensible device framework. New `src/devices/` subdirectory + auto-registry: any vendor drops `src/devices/<vendor>/` with `manifest.json` + `driver.py` + `README.md` + `udev/`, and the tool auto-registers when the MCP server starts — zero changes to the 1755-line core `src/index.js` (only ADD: 1 import + 1 try-wrapped `await registerDevices(server)`). The 20 existing EDA tools are untouched. **Three reference vendors shipped to prove the contract crosses device classes AND driver shapes**:
  - **`keysight-scope/`** — `device_scope_capture` + `device_scope_periodic_pulse_check`. Driver shape: instrument-library client (SCPI via `usbtmc`). Live-caught the v0.64 wake_ctrl bug end-to-end during the agent's smoke test.
  - **`terasic-de10lite/`** — `device_fpga_de10lite_program` + `device_fpga_de10lite_detect`. Driver shape: vendor-binary wrapper (orchestrate `quartus_pgm`). Auto-discovers Quartus install via `$QUARTUS_ROOTDIR` / `$PATH` / common defaults; produces structured JSON error when Quartus is missing rather than crashing.
  - **`vendor-usb_hid_tester/`** — `device_tester_usb_hid_tester_connect_test` + `device_tester_usb_hid_tester_send_raw`. Driver shape: raw-protocol stdlib client (`/dev/hidraw*` direct, no external Python dep). Verified live: connected to USB-HID tester (Nuvoton USB HID 0316:403e), ran the standard CONNECT → SEND_TEST sequence on the IC-A v052 SOF currently burned to the DE10-Lite, captured 5 async E0 frames, all `byte[6]=0xF2` PASS — confirms cable-id protocol still passes even though the wake-pulse periodic-pattern check on the same silicon FAILs (proves the two checks are independent — protocol-level acceptance is invisible to the Layer-3-via-scope check, and vice versa).
  - These three together cover the three most common device-driver shapes (instrument library, vendor-binary wrapper, raw-protocol stdlib).

- **`mcp-eda-server/src/devices/CONTRIBUTING.md`** documents the vendor PR flow: required directory layout, `manifest.json` schema, driver JSON-IO contract, tool naming convention, hardware-setup expectations, license requirements, PR review checklist. Vendors maintain their own driver; we review the contract.

- **`test/test_devices_registry.sh`** — 17-check shell smoke test (Node syntax, JSON validity, driver `--help` works, mock invocation produces structured JSON error rather than crashing). Per-vendor parity verified: all three reference drivers respond identically to `--help` and `--mode <invalid>`.

End-to-end loop now possible from a single MCP client: `device_fpga_de10lite_program` (burn the SOF) → trigger the IC into the suspected-bad state via your existing tester → `device_scope_periodic_pulse_check` (verify the periodic-pulse anti-pattern is absent). All three are MCP tools, all returning structured JSON, all callable from any LLM agent.

**Why this matters for any IC, not just IC-A**: the same shape applies to anything that has timing-sensitive IO behavior. Next-vendor candidates we expect (per Track B agent's recommendation): Saleae logic analyzer (multi-channel digital trace), Rigol/Keysight power supply (brown-out + IR-drop sweeps), Rigol/Keysight signal generator (functional sweep stim).

Skills 69 → **70** (+`scope-pattern-attestation`). Programs 98 → **99** (+`scope_periodic_pulse_check`). MCP devices: 0 → **3 reference vendors / 6 device tools auto-registered**. plugin.json: 0.64.0 → **0.65.0** (both core + d). mcp-eda-server: **2.0.0 → 2.1.0**. Plugin tests 1545 → **1564 passed / 0 failed**. MCP smoke 17/17. Triangle: **70/70 complete**. release_audit: 0 problems.

**v0.64 highlights** (2026-04-24, hardware-only-caught wake-pulse bug → new RTL pattern auditor):

A user FPGA bring-up of v052's `wake_ctrl.v` revealed that after `0x74` wake, the IC kept emitting a wake pulse on `ID_BUS` every ~5 ms forever. Sim missed it (no testbench waited >1 tITO with `awake=1`). Hardware caught it on first power-on. Root cause: the tITO idle-timeout counter incremented inside a nested `else` branch that didn't reference the `awake` input, so the counter rolled over once per tITO (`TITO_CYC` cycles) and triggered `wake_req`. The user's fix added an explicit `else if (awake) cnt <= 24'd0;` freeze branch.

This v0.64 ships the static checker that would have caught the bug pre-tapeout:

- **`timer_freeze_after_state_check.py`** — for any module that takes a one-shot state-bit INPUT (`awake` / `active` / `enable` / `started` / `live` / `running` / `armed` / `ready_lock` / `on_state`) AND has a self-incrementing counter (`<cnt> <= <cnt> + N;`), require an explicit freeze branch `else if (<state>) <cnt> <= <const>;` somewhere in the same `always` block. Flag missing freezes for manual review. Whitelist line-comment supported (`// timer_freeze_check: ok-unconditional`) for modules whose counter legitimately runs ungated. **Verified ground-truth specimen**: the buggy v052 `wake_ctrl.v` is flagged at line 34 (`end else cnt <= cnt + 24'd1;`); the user's fixed version passes cleanly. Also tested for false positives — `output reg <state>` (state owned/produced, not consumed) and internal `reg <state>` (module's own state machine) are excluded; `output reg awake` in v052 `mac.v` and `reg active` in v052 `gen_wake.v` no longer false-flag thanks to the input-only filter and the `[^;,)]*?` non-pairing across module-port commas. **+12 tests** in `test_timer_freeze_after_state_check.py`.

**Generality of the rule**: applies to any "do something until a condition, then stop" timer (wake-from-idle, watchdog, refresh, debounce, transmit-pulse). Not limited to IC-A / cable-side-id-ic class.

**Limits documented**: this is a static heuristic. The strict acceptance criterion (`else if (<state>) <cnt> <= 0;`) will false-flag single-line `if (!<state>) <cnt> <= <cnt>+1;` designs that gate inline. Such modules should add the freeze branch (clearer intent) or the whitelist comment (explicit override).

Plugin tests: 1533 → **1545 passed / 0 failed**. Programs: 97 → **98**. Skills: 69 (unchanged). plugin.json: 0.63.0 → **0.64.0** (both core + d). Triangle: **69/69 complete**. release_audit: 0 problems.

**v0.63 highlights** (2026-04-24, v052 fresh-agent lessons → 14 deliverables: 8 new programs + 5 new skills + 1 mcp-eda-server fix):

The v052 fresh-agent Phase 2+3 run for IC-A "Vendor" produced **USB-HID tester F2 PASS reproducible 30/30 on DE10-Lite** where v045-v051 had FAIL'd for 6 weeks. v052 used only `input/` (no vendor source / no other-project copies; vendor_leak_audit = 0 leaks across 516 blacklisted files). The 14 v0.63 items below are the IC-AGNOSTIC distillations of what made v052 win.

**5 new RTL pattern auditors** (deterministic grep-based, derived from real v052-vs-v045 RTL diffs; each cites the specific v052 source line in its docstring):

- `tristate_self_rx_mask_check` — for any top-level `inout W` with companion `W_oe`, require the RX tap to be masked (`W_rx = W_oe ? 1'b1 : W;`); flag direct `assign W_rx = W;`. Generic to any inout bus. Source: v052 `rtl/pad_ctrl.v:8`.
- `pulse_decoder_edge_check` — pulse-width LOW classifiers must emit on the rising edge (end of LOW), not from `low_cnt >= MIN` alone. Generic to PPM/PWM/AID/DALI/1-Wire/NEC-IR/UART break. Source: v052 `rtl/rx_phy.v:35-50`.
- `packet_length_check_present` — modules that dispatch to per-command response logic must have a length-validity comparison (`rx_len ==` / `byte_cnt ==` / `pkt_len ==`) before dispatch. Generic to any packet-based protocol. Source: v052 `rtl/mac.v:392`.
- `otp_write_lock_gate_check` — OTP/fuse write-enable assertions (`otp_we`, `otp_pwe`, `fuse_prog`, `nvm_we`, `mtp_we`) must be near a `lock` / `lk` / `protected` / `wp` token. Heuristic — flagged sites need manual review. Source: v052 `rtl/mac.v:280-385` (E0 handler reads OTP[0x2E] LK byte, decodes per-region locks).
- `l12_sequence_implementation_check` — for each sequence in `L12_BEHAVIORAL_SEQUENCES.json`, find the implementing RTL module (file basename includes the sequence id) and verify it has actual conditional/FSM logic, not just a state bit set externally. Source: v052 `rtl/testmode_entry.v` + `rtl/cc_reset_ctrl.v`.

**3 new workflow gates** (process discipline that came out of v052 debugging):

- `tester_oracle_health_check` — before iterating RTL on a hardware FAIL, burn a known-good SOF and verify the tester returns the PASS fingerprint. STOP if not — oracle is broken. Saves the 6-weeks-on-broken-tester failure mode v045-v051 demonstrated.
- `hw_vs_rtl_verdict_check` — before declaring "hardware blocked", require N (default 3) RTL variants to produce byte-identical FAIL responses. Differing responses = RTL bug, not hardware. v045 prematurely concluded hardware was broken on byte[6] differences.
- `plugin_self_leak_check` — CI-style scan of plugin's own `references/` and `skills/*/references/` for >N-line (default 50) verbatim Verilog or `module…endmodule` embedded in JSON. Prevents the `references/aid/rtl/` style backdoor that lets agents copy real RTL into generated work. Live run on v0.63 plugin = exit 0 (clean).

**5 new skills** (open-source EDA fallbacks packaged from `phase2+3_v052/scripts_v053/`):

- `open-rcx-fallback` — SPEF extraction from LEF resistance + DEF wire geometry when PDK has no OpenRCX pattern file. (`--lef X.lef --def routed.def → design.spef`)
- `drc-from-lef` — Generate KLayout DRC deck from LEF WIDTH/SPACING/VIA-ENCLOSURE rules (subset — no density/antenna/well-tap).
- `lvs-open-source` — 3-layer LVS: Yosys formal equivalence + Python netlist-vs-DEF connectivity + Magic ext2spice (when `.tech` available). Coverage documented per layer.
- `atpg-name-harmonize` — Rewrite Fault ATPG scan-cut netlist's `\__uuf__._NNNN_.B` style escape identifiers to plain alphanumeric so iverilog hierarchical probes work. Required for any Yosys → Fault scan flow.
- `lef-psm-patch` — Patch LEF CUT-layer sections with RESISTANCE attribute (many PDK LEFs only put it on VIA sections; OpenROAD PSM reads CUT). Required for `analyze_power_grid`.

All 5 source scripts were stripped of v052-specific paths / design names / KeyFoundry m18e80pm180su PDK references during packaging — see git diff for the full strip log.

**1 mcp-eda-server fix**: `src/index.js:187` `metal_prefix` was hardcoded `"met"` in the custom-PDK branch, silently producing an empty `define_metal_layers` for any PDK whose layers don't match SKY130 naming (KeyFoundry m18e80pm180su uses uppercase MET1-6). Now reads from `customOpts.custom_metal_prefix`, default `"met"` so existing custom configs keep working.

Skills: 64 → **69**. Programs: 89 → **97** (+5 RTL pattern auditors + 3 workflow gates; `_phase1_sentinel.py` from v0.62 unchanged). plugin.json bumped 0.53.0 → **0.63.0** (both core + d). Plugin tests: 1425 → **1533 passed / 0 failed**. Triangle: **69/69 complete**.

Sub-agent execution: this v0.63 release was assembled by 4 parallel teammate agents (Track A: RTL auditors; Track B: workflow gates; Track C: EDA fallback skills; Track D: integration + version bump + commit) coordinated through the Task system.

**v0.62 highlights** (2026-04-24, P2 deferral cleanup — apb-peripheral class-tree refactor + sentinel centralisation):

v0.61 shipped two P2 deferrals (Bug #3 + #4 from G1 fresh-agent verification). v0.62 closes both. The two fixes are independent in motivation but share a single test file because both surfaced under the same MY_WDT verification.

- **Bug #3 (P2 → FIXED) — apb-peripheral inheritance**: `apb-peripheral.yaml` declared `parent: protocol-ic`, forcing APB designs to fill serial-protocol fields the bus doesn't have (`frame_format.start_bit`, `frame_format.crc`, `command_set`, `aid_bit_timing`, `wake_timing`, `response_timing`, `bit_period_cycles`, `crc8_polynomial`, `crc8_init`). G1's MY_WDT had to either (a) write `"N/A"` placeholders for ten serial fields it doesn't have, or (b) declare the no-protocol sentinel. Neither is right — APB IS a protocol, just a memory-mapped one. **Fix**: re-parented `apb-peripheral` from `protocol-ic` to `digital-ic` directly in both `apb-peripheral.yaml` (the template's `parent:` field) and `class_kb/class-tree.yaml` (the taxonomy tree). New chain: `any-ic → digital-ic → apb-peripheral` (was: `any-ic → digital-ic → protocol-ic → apb-peripheral`). Re-classified `protocol-ic`'s description in class-tree.yaml as "SERIAL FRAMED protocol" to make the sibling boundary explicit. `uart-peripheral` and `cable-side-id-ic` (genuine serial protocols) stay under `protocol-ic`. +3 tests including a defensive guard that `uart-peripheral` chain still includes `protocol-ic`.
- **Bug #4 (P2 → FIXED) — sentinel inconsistency across gates**: `protocol_present:false` was honored by `phase1_doc_presence_check.py` (which skipped L3/L8R presence requirements) but ignored by `phase1_consistency_check.py`'s `R_clock_freq_positive` and `R_layer_documents_present` rules — both produced false-FAILs on no-protocol designs (memory-controller, analog-front-end, register-pointer ICs). v0.61's fix to Bug #1 INCIDENTALLY masked the symptom (L8R got populated so `clock_frequency_hz` was found), but the root cause — duplicated, unsynchronised sentinel logic — remained. **Fix**: extracted sentinel logic into shared `vibe-ic-d/programs/_phase1_sentinel.py` exposing `SENTINEL_OPTIONAL_LAYERS` (frozen at `{L3, L8R}`), `is_no_protocol_sentinel_active_in_dir(docs_dir)` (filesystem form), and `is_no_protocol_sentinel_active_in_docs(docs_dict)` (in-memory form for already-loaded gates). Both gates now import from the shared module. `R_clock_freq_positive` (and any other rule whose target layer is in `SENTINEL_OPTIONAL_LAYERS`) skips with `info` finding when sentinel active and that layer is genuinely absent. `R_layer_documents_present` strips L3/L8R from the missing-layers set when sentinel active. Defensive: rules still FAIL when L8R is present but `clock_frequency_hz` is malformed, and `R_layer_documents_present` still flags L1/L2/L4/L5/L6/L7/L9 as required regardless of sentinel. +11 tests covering both API forms, both rule branches, and 3 defensive non-regressions.

With Bug #3 fixed, apb-peripheral designs author a clean spec.yaml without needing the no-protocol sentinel workaround. Older spec.yaml that did declare `protocol_present:false` keeps working — sentinel logic is shared, not removed.

Plugin tests: 1411 → **1425 passed / 0 failed** (60 skipped, 5 xfailed). +14 tests in `test_phase1_sentinel_shared.py`. Skills 64, programs **89** (+1: `_phase1_sentinel.py`). Triangle: 64/64 complete.

**v0.61 highlights** (2026-04-24, Path A fact-graph hardening from G1 fresh-agent verification):

G1 fresh-agent verified v0.60's two-entry-points by running Path A end-to-end on a brand-new class (`apb-peripheral` / MY_WDT watchdog). The architectural contract held — JSON + `human_docs/` co-emit, Phase 2a's doc-gen skills never accidentally trigger (seventeen of them in active set; none ran) — but four real plugin bugs surfaced. v0.61 fixes the two P0/P1 ones and documents the two P2 deferrals. **Skills 64**, programs 88, plugin tests 1411 (carry-over from v0.60: skills count unchanged).

- **Bug #1 (P0) FIXED — L8R silent drop**: `tools/phase1_engine/ingest.py:_walk_leaves` heuristic ("dict of all-scalar values yields whole dict as one record" — kept `{min,typ,max,unit}` together) ALSO fired at the top level (`prefix=""`), and the caller's `if not leaf_path: continue` guard then dropped the entire yielded record. Symptom: any spec.yaml whose `L8R:` block was purely scalar (typical: `clock_frequency_hz`, `reset_polarity`, `irq_count`, `address_alignment`) lost **all** L8R facts; `generated_docs/L8_RTL_CONSTANTS.json` was never written, which (a) blocked Phase 2b's SDC generator and (b) chained-FAIL'd `phase1_consistency_check.py`'s `R_clock_freq_positive` and `R_layer_documents_present` rules. Fix: heuristic now gated on `prefix` non-empty so it only fires on nested records, never on layer-top level. Same fix benefits `from_existing_docs` round-trip. +8 tests in `test_ingest_top_level_scalars.py`.
- **Bug #2 (P1) FIXED — `json_schema_check` profile vs Path A schema mismatch**: `SKILL_PROFILES` only had v0.51 doc-gen skill keys (`part_number`, `registers`, `base_address`, …). Path A's fact-graph renderer uses fact-graph-native keys (`ic_name`, `register_map`, `dtop_top_level`, …). Every Path A `--skill-profile <skill>` invocation FAIL-ed on MISSING_KEY for keys the renderer never produces. Fix: added 14 new fact-graph profiles `L1`-`L13` (incl. `L8R`) with universal-minimum required keys per layer; class-specific structure is enforced by `phase1_consistency_check` / `spec_floor` / qbank, not duplicated here. Empty profile (e.g. `L2/L3/L5/L6/L7/L8` whose structure varies by class) now legitimately PASSes on valid JSON instead of erroring "no required keys specified". Path B v0.51 profiles untouched. +10 tests.
- **Bug #3 (P2) DEFERRED to v0.62**: `apb-peripheral` template inherits `protocol-ic`, forcing APB designs to fill serial-protocol fields (`frame_format`, `aid_bit_timing`, `wake_timing`). Workaround: use `protocol_present: false` sentinel — `phase1_doc_presence_check` honors it. Proper fix needs class-tree refactor (introduce `bus-peripheral` intermediate, or detach `apb-peripheral` from `protocol-ic`).
- **Bug #4 (P2) DEFERRED to v0.62**: sentinel inconsistency — `protocol_present:false` was honored by `phase1_doc_presence_check.py` but not by `phase1_consistency_check.py`'s `R_clock_freq_positive` / `R_layer_documents_present` rules. Bug #1 fix INCIDENTALLY resolved both rules (L8R now populated, clock_frequency_hz now found), so the immediate symptom is gone. Remaining work is centralising sentinel recognition in a shared utility so all gates query the same logic. Tracked for v0.62.

End-to-end v0.61 re-verification on the same MY_WDT spec.yaml: **4/4 core gates PASS** (`phase1_doc_presence_check`, `phase1_consistency_check` 14/15 + 1 warn, `phase1_quality_parity_check`, `json_schema_check`); 14/14 layer JSONs render (was 13/14); fact-graph 128 facts → **143 facts** (the +15 are L8R, no longer dropped). The 2 layer-level json_schema_check FAILs that remain (`L11`, `L13`) are user-spec authoring deviations (`L11.calibration_tables` should be `L11.tables`; `L13.contract.criterion` should be `L13.criterion` per the canonical qbank schema) — the gate is correctly catching schema-drift, not mis-firing. The G1 verdict + v0.61 verification artefacts live at `benchmark/phase1_v060_apb_wdt/` (failure baseline) and `benchmark/phase1_v061_apb_wdt/` (post-fix re-run).

Plugin tests: 1401 → **1411 passed / 0 failed** (60 skipped, 5 xfailed). Fact-graph tests: 15 → **23**. `json_schema_check` tests: 10 → **20**. Skills 64, programs 88 (both unchanged).

**v0.60 highlights** (2026-04-24, two-entry-points alignment):

v0.58's Phase-1 fact-graph refactor accidentally collapsed **two distinct entry points** to the platform into a single `phase1` skill: it bundled both Phase 1 (prompt → spec) and Phase 2a (docs → L1-L13) work into one fact-graph pipeline, and moved the 10 Phase-2a per-layer doc-gen skills to `legacy/`. This contradicted the public 3-phase definition on vibeic.ai (Phase 1 = dialogue → Design Documents; Phase 2a = Documents → L1-L13). v0.60 restores the two-entry-points architecture without losing v0.58's fact-graph value.

```
   Path A:  Prompt / Dialogue ──► Phase 1 ──► L1-L13 JSON ───┐
                                            + human .md      │
                                                              ▼
                                                   ┌── Phase 2b → Phase 3
                                                   │
   Path B:  Existing Design Docs ──► Phase 2a ────┘
            (vendor PDF / hand-spec)  (10 doc-gen skills)
```

- **R1 — Human-readable Markdown render**: `tools/phase1_engine/render.py` gains `render_human_docs()` which emits `human_docs/L*.md` (Markdown views of every L*.json) alongside the JSON. The `phase1` skill's `run-all` invocation now produces both deliverables; the standalone `render` subcommand gains `--human-docs-dir`. Rationale: Phase 1's prompt entry must produce both the machine-readable JSON (consumed by Phase 2b) AND a human-readable view for stakeholder review. v0.58 only emitted the JSON. +6 tests.
- **R2 — Restored 10 Phase-2a doc-gen skills** from `legacy/skills_phase1_v051/` to active: `datasheet-gen`, `frs-gen`, `cmd-protocol-gen`, `regmap-gen`, `adi-spec-gen`, `control-logic-gen`, `test-debug-gen`, `timing-waveform-gen`, `rtl-constants-gen`, `integration-spec-gen`. These are the per-layer skills used when Path B (existing Design Documents) enters at Phase 2a. d-side compliance + tests restored alongside.
- **R3 — `prompt-intake` and `phase1-orchestrate` stay in legacy**: their function is fully subsumed by `phase1` skill's ingest + PM-Agent dialogue + render pipeline. The legacy archive is preserved for reference.
- **R4 — `phase1/SKILL.md` rewrite**: description now reflects "Phase 1 = prompt/dialogue entry point producing L1-L13 JSON + human Markdown"; new "Two entry points" section explicitly lists Path A (this skill) vs Path B (Phase 2a's seventeen sibling skills); added per-skill table of the Phase-2a siblings with restored-in-v0.60 notes; clarified that the 10 doc-gen restore is NOT a regression of v0.58 (the fact-graph still works for Path A; the per-layer skills are for Path B).
- Total skills: 54 → **64** active (Phase 1 = 2 + Phase 2a = 17 + Phase 2b = 22 + Phase 3 = 23). Plugin tests: 1317 → **1401 passed / 0 failed**. Fact-graph tests: 9 → **15**. Triangle: **64/64 complete**.

**v0.59 highlights** (2026-04-24, fact-graph L10-L13 completion + v0.58 cleanup):

v0.58 (the Phase-1 fact-graph refactor by phase 1 agent) shipped with two real bugs the multi-IC validation flow needed: (a) `schema.LAYER_FILE_NAMES` declared `L10`-`L13` but `render.py` had zero L10-L13 logic in qbank or ingest, so the new pipeline silently never wrote those files; (b) `LAYER_FILE_NAMES["L13"] = "L13_HARDWARE_OBSERVED.json"` while `hardware_pass_attestation_check.py` expects `L13_LAB_CALIBRATION.json`, so the gate would always fail file-not-found after a fact-graph render. v0.59 closes both, plus the d-side orphan-skill cleanup that v0.58 forgot.

- **H1 — fact-graph L10-L13 completion**: confirmed `render.py` is already generic (renders any fact whose path starts with `L<N>.`); the only real gap was the qbank. Added `any-ic_L{10,11,12,13}.yaml` (4 new files) so the PM Agent has questions for `test_cases / tables / sequences / criterion`. End-to-end smoke-test confirmed L10/L11/L12/L13 round-trip cleanly into the canonical JSON shapes (`test_cases[]`, `tables[]`, `sequences[]`, `criterion + criterion_params + tester`). +9 tests in `tools/phase1_engine/tests/test_l10_l13_render.py`.
- **H2 — L13 filename alignment**: `schema.LAYER_FILE_NAMES["L13"]` changed from `L13_HARDWARE_OBSERVED.json` (v0.58) → `L13_LAB_CALIBRATION.json` (matches `hardware_pass_attestation_check.py` and the v0.50-v0.55 canonical name). Schema docstring updated to document the L13 contract-vs-evidence boundary: Phase 1 fills `criterion + criterion_params + tester`; Phase 2b appends `known_pass_bitstream + known_pass_transcript`. Pinned by `test_l13_filename_aligns_with_attestation_gate`.
- **v0.58 d-side orphan cleanup**: phase 1 agent moved 12 core skills (datasheet-gen / frs-gen / cmd-protocol-gen / regmap-gen / adi-spec-gen / control-logic-gen / test-debug-gen / timing-waveform-gen / rtl-constants-gen / integration-spec-gen / phase1-orchestrate / prompt-intake) to `legacy/skills_phase1_v051/` but left the matching `vibe-ic-d/skills/<name>/` directories in the active tree, breaking `skill_compliance_triangle_check` (12 `d_skill_orphan` errors) and 2 integration-test fixtures. v0.59 deletes the duplicates from the active tree (they're preserved in `legacy/`). Active d-side skill count 66 → **54** (matches core-side 54). Triangle re-check: **54/54 complete, 0 failed**.
- **`_shared/test_integration_fixtures.py` CRITICAL list refresh**: removed the 4 legacy skill names that were causing fixture-not-found failures; replaced with the new single `phase1` skill (xfail until its fixture is generated).

Plugin tests: pre-v0.59 (broken from v0.58) → **1317 passed / 0 failed** (50 skipped, 5 xfailed). Programs: 88 (unchanged). Skills: 65 → **54** (post-v0.58 refactor settled). Fact-graph tests: 9/9 (new).

**v0.57 highlights** (2026-04-24, post-v0.56 verification cleanup):

The v0.56 ship claimed to close 11 of 14 v0.55 multi-IC overfittings. An independent fresh-agent re-run (`RESULTS_v056.md`) verified **9 FIXED + 3 IMPROVED + 2 STILL-BROKEN**, plus caught a fresh internal contradiction that v0.56's own C3 gate flagged (memory-controller spec_floor declared `L3_opcode_count_min: 3` alongside the no-protocol-sentinel default). v0.57 closes all 5 residuals.

- **D1 — memory-controller spec_floor**: removed `L3_opcode_count_min: 3`. The new C3 gate (`no_protocol_consistency_check`) was correctly flagging this as an internal contradiction; v0.57 fixes the contradiction at the source.
- **D2 — phase1_doc_presence_check sentinel-aware**: when `L1_DATASHEET.json` (or `L3_CMD_PROTOCOL.json`) declares `protocol_present: false`, both L3 and L8R presence requirements skip cleanly with an INFO `skipped-*-no-protocol` finding instead of an ERROR `missing-*`. Memory / register-pointer / analog-front-end ICs no longer have to fabricate L3 + L8R files just to satisfy presence. +4 tests.
- **D3 — memory-controller.yaml `facts:` rewrite**: prior schema was DRAM-only (`refresh_scheme`, `bank_machine_count`, `phy_frequency_ratio`) and forced commodity I²C EEPROMs into nonsensical fields. New schema covers three sub-styles via `memory_subclass: dram-controller | flash-controller | serial-eeprom`. EEPROM-specific fields now first-class: `page_size_bytes`, `write_cycle_ms`, `ack_poll_semantics`, `wp_pin_behavior`, `addressing_scheme`, `device_address_pins`. DRAM-only fields gated on `memory_subclass == dram-controller`.
- **D4 — l9_completeness_check.py `registers` conditional**: pure-logic / pad-only / some analog-FE ICs have no addressable register file. Setting `no_registers: true` (or `registers_not_applicable: true`) at L9 root now skips the requirement with a SKIPPED_SECTION info finding. +4 tests.
- **D5 — `sequence_naming.strip_suffixes`** filled for the four remaining templates (`bus-controller`, `crypto-engine`, `processor`, `soc-harness`). Every class with L12 sequences now ships its own per-class suffix list.

Plugin tests: 1397 → **1405 passed / 0 failed** (61 skipped, 6 xfailed). Programs unchanged (88). Class templates unchanged (12).

**v0.56 highlights** (2026-04-24, the de-IC-A-overfit release):

The v0.55 multi-IC validation campaign (24LC256 EEPROM + ADS1115 ADC) found 14 structural overfittings to the cable-side-id-ic / IC-A benchmark class. v0.56 closes 11 of them in one ship.

- **A1 — phase1_quality_parity_check default** auto-resolves `class_path` from `L1_DATASHEET.json` (mirrors `layer_extension_presence_check`); `--class-path` is now an OVERRIDE only. Templates without `spec_floor:` emit a `vacuous_pass_no_spec_floor` WARNING so silent-PASS becomes visible.
- **A2 — filled `spec_floor:` blocks** in the four silent templates: `memory-controller`, `protocol-ic`, `apb-peripheral`, `uart-peripheral`. Floors are class-median, NOT IC-A-derived.
- **A3 — new class template `analog-front-end.yaml`** for ADCs / DACs / op-amps / comparators / voltage refs. Includes a `protocol_present: false` default + `monotonic_adc_sweep` L13 criterion preset.
- **A4 — no-protocol sentinel** (`{protocol_present: false, reason: ...}`) added to `cmd-protocol-gen/SKILL.md`. `cmd_protocol_crc_verify.py` skips cleanly (exit 0) when the sentinel is present; `phase1_quality_parity_check.py` skips L3 floors. New gate **`no_protocol_consistency_check.py`** verifies the sentinel is internally consistent across L3 / L8R / class-template (no contradicting `command_set` / `crc` / `crc8_polynomial` / forbidden floor key).
- **B1 — `count_l9_ports()`** now descends into `dtop_top_level.ports` (the orchestrator schema). Prior version always returned 0, silently skipping the port-count floor.
- **B2 — `l9_completeness_check.py`** schema reconciliation. `top_level_ports` is now found under `dtop_top_level.ports` / `dtop.ports` / `top_level.ports` etc., not just at the JSON root.
- **B3 — de-IC-A-ified `cable-side-id-ic.yaml`**. Removed the IC-A-specific `L6_required_submodules` list (`mac/rx_phy/tx_phy/rx_chk/rx_cmd/gen_wake/...`) from the parent class. Moved into a new sub-class `cable-side-id-ic-maxim-style.yaml`. Parent floors loosened: `L6_submodule_count_min: 6` (was 10), `L9_top_level_port_count_min: 14` (was 18). CRC-poly comments scrubbed of vendor names.
- **B4 — generalized L13 attestation criterion**. `hardware_pass_attestation_check.py` now supports five criterion types (`distinct_non_padding_bytes` (default), `monotonic_adc_sweep`, `memory_readback_match`, `register_write_read_roundtrip`, `comparator_alert_on_threshold`). The L13 doc selects which one applies. ADC reading a DC signal no longer false-fails.
- **C1 — PM-Agent class-resolution table** added to `prompt-intake/SKILL.md`: every prompt-intake Step-2 category maps to a deterministic class template name. No more silent fall-through to `any-ic`.
- **C2 — per-class `sequence_naming.strip_suffixes`** added to memory-controller / protocol-ic / apb-peripheral / uart-peripheral templates. `l12_tb_coverage_check` now matches abbreviated tb names for non-IC-A classes too.
- **C3 — new gate `no_protocol_consistency_check.py`** (subsumed under A4 above; same program closes both items).

Plugin tests: 1352 → **1397 passed / 0 failed** (61 skipped, 6 xfailed). Programs: 87 → **88**. Class templates: 10 → 12 (analog-front-end + cable-side-id-ic-maxim-style added).

**v0.55 highlights** (2026-04-24, plugin-quality fixes):

- **A1 — `release_audit.py`**: single-source-of-truth audit. Scans the live plugin tree for canonical version + skill_count + program_count + test_count, then cross-checks the four public-facing surfaces (plugin README, root README, vibeic.ai README, vibeic.ai/index.html). Catches the "I bumped the count in 3 of 4 places" toil that produced stale numbers in v0.51-v0.54. Section-aware (only audits the current version's changelog block in markdowns; full file in HTML). +21 tests.
- **A3 — six new gates wired into the canonical 28-step flow**: `bit_level_full_stack_tb_check` (v0.52), `l10_tb_conformance_check` / `l12_tb_coverage_check` / `verilator_coverage_measure` / `fpga_verification_audit` (v0.53), `rtl_bug_report_schema_check` (v0.54) — until now were orphans only fired if the agent knew to invoke them. Now part of `flow/phase2_phase3.yaml` steps 2 / 4 / 5 / 6. New `optional_program_exit_zero` predicate added to `flow_compliance_check.py` so condition-aware gates skip cleanly on projects that don't ship the trigger artefacts. +5 predicate tests.
- **C1 — `skill_compliance_triangle_check.py`**: invariant gate enforcing that every `vibe-ic/skills/<name>/` has a matching `vibe-ic-d/skills/<name>/{compliance.yaml, tests/test_compliance.py}`. Audit at v0.55 release confirmed all 65 skills are triangle-complete; the gate exists to catch any future drift. Catches d-side orphans (renamed-and-not-cleaned-up directories) too. +12 tests.
- **C2 — `memory_gc.py`**: advisory tool for Claude Code memory directories. Surfaces STALE (`expires:` past today), ABANDONED (`project_*` unmodified > 30 d, advisory only), DUPLICATE (same `description:` in two files), ORPHAN (in `MEMORY.md` but missing on disk), UNINDEXED (on disk but missing from `MEMORY.md`). Recommended `expires:` frontmatter for `project_*` entries documented in the docstring. +23 tests.
- Plugin tests: 1282 → **1343 passed / 0 failed** (61 skipped, 6 xfailed). Programs: 84 → **87**.

**v0.54 highlights** (2026-04-24, post-v0.53 review):

- **A+E — class-template sequence naming**: removed IC-A-specific suffix list (`_entry|_unlock|_validation|_chain|[0-9]+ms`) hard-coded in `l12_tb_coverage_check.py`. Each IC class template (e.g. `cable-side-id-ic.yaml`) now declares its own `sequence_naming.strip_suffixes:` list. New `--ic-class <template.yaml>` flag loads it. Without a template, only literal-id tb candidates are tried — no IC-specific assumptions baked into the gate.
- **B — `data/estimation_keywords.yaml`**: lifted the hard-coded English + zh estimation regexes out of `fpga_verification_audit.py` into a YAML file. Adds Japanese (`およそ`, `推定`), Korean (`약`, `추정`), Spanish/Portuguese (`aproximado`, `environ`), German (`schätzungsweise`) so non-Chinese reports are also audited. New `--keywords-yaml` flag overrides the bundled list.
- **C — git-log-before-defect rule**: added Rule E to `spec-to-rtl/SKILL.md` plus a "Before claiming this skill is out of date" block in `phase1-orchestrate/SKILL.md`. The v0.53 changelog incorrectly claimed `phase1-orchestrate` "still says L1-L9, fix queued for v0.54" — that was already fixed in v0.52. Agents now must `git log --since=<latest-version>` on a SKILL.md before filing a defect against it.
- **D — `rtl_bug_report_schema_check.py`** (new program, +30 tests): every entry in `reports/rtl_bugs.json` must carry `spec_evidence: {doc, locator, quote, interpretation}` with a doc that exists in the project tree, a verbatim quote ≥ 20 chars (no ellipsis-only), and an interpretation. `severity: silicon-blocking` additionally requires `expected_behaviour_unambiguous: true` plus at least one of `vendor_sample_test` / `independent_review`. Prevents the v0.53 pattern of "agent reads spec, agent finds RTL doesn't match, agent declares silicon-blocking" without any independent confirmation.
- Plugin tests: **1282 passed / 0 failed** (61 skipped, 6 xfailed). Programs: 83 → 84.

**v0.53 highlights** (2026-04-24):

- **Fresh-agent USB-HID tester F2 PASS reproduced from `input/` alone** (v052 benchmark run). A fresh Claude-spawned agent generated L1-L13 + 22-module RTL + SOF that makes the actual USB-HID tester protocol tester return `E0 40 00 00 0E 3A F2 02 02 02 02 02 BE AB BA D1 CD D0 D1 D2 AF CD CD D1 B5 AC D2 C1 B8 02 02 FA` — byte[6]=0xF2 with full IC-A signature tail. Independently verified by re-burning the SOF and re-running the HID test. `vendor_leak_audit` confirmed 0 exact-file/string copies against 516 blacklisted files across `/home/user/a3606` + 8 earlier phase2+3_v* folders. This retracts the v0.52-era "PIN_V10 disconnected" hypothesis — the hardware was fine; earlier v045-v051 FAILs were real RTL bugs the machine-checked gates had let through.
- **New deterministic program: `l12_tb_coverage_check.py`** — reads `generated_docs/L12_BEHAVIORAL_SEQUENCES.json` and enforces that each multi-step sequence (EngineerMode double-0x74, CC_Reset 700ms, TestMode HV+CC_I entry, 9-step RX validation) has a corresponding `sim/tb/tb_*.v`. Without this gate, v052's first pass reported `1083/1083 PASS` but silently lacked testbenches for TestMode, OTP-E0-write, and PT-mux. The same agent, re-prompted with the gate, added `tb_testmode.v` (10 cases), `tb_otp_e0_write.v` (25 cases), `tb_pt_mux.v` (15 cases) → 1133 total tests, 4/4 L12 sequences covered.
- **Machine-measured Verilator coverage replaces agent self-report**. The v052 agent's first report claimed "≥ 95 % line coverage (estimated)". After running `verilator --cc --coverage --coverage-line --coverage-toggle` and `verilator_coverage --annotate`, the actual numbers are: **line 78.3 %, toggle 75.5 %, branch 82.3 %** (lcov DA 84.3 %, BRDA 76.3 %). All 22 RTL files elaborated — no module was Verilator-incompatible. **Lesson**: plugin must require `reports/coverage/coverage_actual.json` with tool-generated content; self-reported percentages are now considered unverified.
- **Two real RTL gaps caught by new testbenches** (both real silicon issues, not sim artefacts):
  1. **Lock-bit not enforced** — `mac.v` E0 handler checks `ADDR<0x80` but does not check ID_LK / IMSN_LK / ASN_LK region contents nor gate writes on EngineerMode. `tb_otp_e0_write.v` case 8 demonstrates the post-lock write is accepted and reaches `ram128x8`.
  2. **TestMode pattern matcher is stub** — the v0.52 RTL enters TestMode only via the `0xEC` HID command, not via the real HV + CC_I + ID_BUS serial-pattern entry described in `TestMode說明.txt`. `tb_testmode.v` verifies what the stub actually does (sticky-latch + POR-clear invariants) and flags the missing pattern matcher as a silicon-blocking bug before tape-out.
- ~~**Plugin defect identified**: `phase1-orchestrate/SKILL.md` still describes only L1-L9.~~ — **already fixed in v0.52** (commit `00889aa1`); the v0.53 agent was working against stale local state. Orchestrator has explicitly chained L1-L13 + `doc-consistency-check` + `schematic-gen` since v0.52.
- **v0.53.1**: added 75 pytest tests across the 4 new v0.53 programs (`l12_tb_coverage_check`, `l10_tb_conformance_check`, `verilator_coverage_measure`, `fpga_verification_audit`) — they shipped without tests. Full plugin suite: **1240 passed / 0 failed** (up from 1165 in v0.53), 61 skipped, 6 xfailed.

---

**v0.50-pre highlights** (2026-04-23/24, subsumed into v0.53):

- **Hardware reality check (2026-04-24) — retracting v0.48 "52/52 BIST PASS"**: a live USB-HID test against the actual benchmark protocol tester board revealed that v0.48 / v0.50-pre agent-built .sof files all return `02 02 02 ...` padding on the ID bus (FAIL), while only the human-engineered v037v2 .sof produces the correct `F2 02 02 02 02 02 BE AB BA D1 ... B8 02 02 FA` ID string (PASS). The v0.48 "self-BIST 52/52 PASS" was a **FPGA-internal loopback** (same FPGA running both host_bist + device in the same fabric) — not a real protocol PASS. 8 RTL bugs were found by close reading of `input/docs/` alone (no peek at v037v2): H0/H1 polarity inverted, MSB-first instead of LSB-first, CRC init 0x00 not 0xFF, FPGA wrapper at 48 kHz instead of 5 MHz, FPGA wrapper had no physical pin for ACC_ID, MAC response echoed RX opcode instead of RX+1, response CRC used RX accumulator, payload_len table wrong for 8 of 13 CMDs. **None** of the passing structural gates (presence / schema / parity / tapeout_signoff strict 4/4 / flow_compliance strict 28/28) caught any of these — proving that structural gates are necessary-but-not-sufficient and the plugin was missing a functional (close-loop) check class.
- **Three-layer defense (v0.50 — spec, sim, hardware)**: the 2026-04-24 benchmark IC regen experiment showed that Layer 1 (extraction) + Layer 2 (sim) still isn't sufficient — a fresh-agent RTL that passes every structural + L10-conformance sim gate can STILL fail a real tester because vendor `input/docs/` are an incomplete spec for a specific hardware tester (e.g. protocol tester returned only `02 02 02 ...` padding even when sim drove 8/8 CMD→RSP vectors correctly; only human-engineer v037v2 produces the golden signature). Therefore v0.50 adds **Layer 3 — L13_LAB_CALIBRATION + `hardware_pass_attestation_check.py`**: real-tester transcripts + known-PASS bitstream identity must be captured as a first-class artefact before a project can claim production-ready. Sim PASS = simulation certification; only L13-attested real-hardware PASS = production certification. Previous plugin versions conflated the two. New program rejects padding-only transcripts (`02 02 ...`) and missing bitstream identity. Seven-word summary: **extract everything + sim everything + attest hardware** — three layers redundant on purpose.
- **Two-layer defense principle (v0.50)**: the plugin now treats "no design-doc info missing" as a problem that requires BOTH layers to be green:
  - **Layer 1 — extraction completeness (upstream)**: L1-L9 aren't always wide enough for a given IC class. v0.50 adds three extension layers: **L10 TEST_CASES** (CMD→RSP vectors + error paths), **L11 CALIBRATION** (platform-specific tuning tables like FPGA counter windows, XOR-trim masks), **L12 BEHAVIORAL_SEQUENCES** (multi-step protocols like Engineer Mode double-0x74 unlock, CC Reset 700ms, TestMode HV entry, RX 9-step validation). Each class template's `spec_floor` declares minimums for its extensions. `layer_extension_presence_check.py` enforces the floors.
  - **Layer 2 — close-loop functional verification (downstream)**: `cmd_response_conformance_check.py` drives each L10 vector into the RTL via iverilog and verifies every RSP byte-for-byte against the spec. Independent of whether L1-L9 + L10-L12 captured the fact correctly.
  - Treat as redundant layers: if extraction has a gap the ruleset didn't anticipate, close-loop still catches functional divergence; if close-loop can't be exercised for some paths (e.g. Engineer Mode entry), extension layers still force the agent to acknowledge the facts. Seven-word summary: **extract everything AND test-drive everything**.
- **Two new v0.50 programs close the gap**:
  - `input_docs_coverage_check.py` — fails if any `input/docs/` file is not cited in L*.json provenance OR a project-root `input_docs_coverage.md` manifest. Directly addresses "the agent fabricated values because it didn't read all documents".
  - `cmd_response_conformance_check.py` — a close-loop functional check: given a `cmd_response_vectors.json` with per-CMD expected RSP bytes (from the L3/PDF tables), drives the RTL via a sim hook and verifies every RSP byte-for-byte (wildcards `XX`/`YY` allowed for device-specific fields). Directly addresses "the RTL compiled / parity-passed / synth-passed / PnR-clean but failed on real hardware".
  - Updates to `spec-to-rtl/SKILL.md` add both as MANDATORY rules (Rule A: read every input/docs file + write coverage manifest; Rule B: close-loop CMD→RSP conformance before declaring PASS), including the meta-principle that `tapeout_signoff 4/4 + flow_compliance 28/28 + 10/10 L*.json + parity PASS ≠ real hardware PASS`.
- **Fill-to-Floor Rule + `phase1_quality_parity_check.py`** — fixes the v0.49 persona-divergence failure mode where common/medium/high pseudo-users produced three different ICs (4 / 7 / 13 opcodes; CRC 0x07 vs 0x31; 32 vs 128-byte OTP) from the same plugin. Each class template (`class_kb/templates/<class>.yaml`) now carries a `spec_floor:` block defining the class-median hardware minimums; IC Expert Agent must lift below-floor fields to the floor via documented industry defaults (`auto_decided: true` with reasoning). The parity gate ran against the failed v0.49 outputs and correctly flagged every divergence. Same-day re-run of all 3 personas with v0.50-pre produced **identical quality L*.json** (13 opcodes, CRC 0x31 MAXIM, 128-byte OTP, all 10 required submodules — `pad_ctrl dclk drst rx_phy tx_phy rx_chk rx_cmd mac otp_ctrl gen_wake`), with only above-floor variance remaining (registers 4/8/8; L9 ports 20/22/24). **60 skills**, **73 deterministic programs**, **758 test functions**. Phase 2+3 silicon parity verification pending.

**v0.49 highlights**:

- **Phase-1 training scorecard — 127/127 PASS across 5 gates, 20/20 Yosys synth on LLM-generated RTL**: the K1-K5 Phase-1 training architecture now has 96 primary ICs + 22 dialogue variants + 9 persona-stress variants = **127 doc sets**, all passing (a) Phase-1 presence (10 canonical L*.json files each), (b) Phase-1 K4 consistency (15 rules, 4 new from mining), (c) Phase-2 spec-to-rtl readiness (5 operational criteria), (d) FPGA-signal presence, and (e) OTP image presence. 20 of the ICs were taken through real Yosys `synth` to measure whether docs produce non-trivial RTL — **20/20 PASS, cumulative ~220K gates synthesised** across crypto/CPU/DSP/FPU/peripheral/bus/DMA classes. See `benchmark/phase1_v046/phase2_real_synth_pilot.md`.
- **K5 quality loop closed — 9 patterns mined from real synth**: writing Verilog from Phase-1 docs surfaced 9 recurring design-spec defects that static rules miss but humans-doing-synthesis catch. Each pattern is (a) auto-detected by `phase1_k5_quality_check.py`, (b) warned against in the corresponding Phase-1 skill SKILL.md, (c) logged in CI as non-blocking output. Top patterns: K5-A templated L6 FSMs (121 occurrences), K5-C generic L9 ports_mapped (116), K5-D duplicate `dir`/`direction` keys (40), K5-I L4 MMIO vs L9 native bus conflict (36). New in this release: K5-G (FIFO/packet reg missing bitfield schema), K5-H (L1 class_path vs L6 scope mismatch), K5-F (crypto missing key schedule).
- **3 new Phase-1 deterministic programs** — `phase1_consistency_check.py` (15 K4 rules), `phase1_k5_quality_check.py` (9 K5 patterns), `otp_image_check.py`. Plus 5-gate CI workflow `.github/workflows/phase1_regression.yml`.

**Carry-over v0.48 highlights**:

- **3-phase fresh-agent pilot — FPGA BIST 52/52 PASS + GDS tapeout 4/4 strict (benchmark IC / across two sessions)**: Phase 1 L1-L9 docs generated in a 2026-04-22 session from `input/` (19 vendor docs). Phase 2 RTL also generated 2026-04-22; initial BIST was 0/13. A 2026-04-23 follow-up session applied 5 fixes, hit **on-board BIST 52/52** (13 opcodes × 4 stress loops) on DE10-Lite, then continued Phase 3 in the same day: **Yosys (3576 cells) → Fault ATPG → OpenROAD PnR (0 routing violations, 6m30s with 6-metal + 8 threads) → OpenSTA (setup WNS=0, TNS=0 all 3 corners) → klayout streamout (5.1 MB GDS, 0 off-grid) → klayout sanity DRC + instance-count LVS → tapeout_signoff_check strict 4/4 PASS**. The end-to-end reproducibility holds across **two sessions**, not one — Phase 1 was NOT re-run 2026-04-23. See *Proven outcomes* and *2026-04-23 debug session* below.
- **2 new RTL-review bug classes** (not yet automated — future v0.49 target):
  - **Pulse-vs-state confusion** — `rx_cmd.awake_set_o` generated as a 1-cycle pulse instead of a latched state; downstream `rx_chk` wake-state gate rejects all non-wake opcodes
  - **Producer/consumer rate mismatch** — MAC asserts `tx_bit_valid` every `sys_clk` (~400 ns), but `tx_phy` consumes one bit every ~10 μs → only the first bit of every response lands
- **Canonical 33-step Phase 2+3 flow** — machine-readable `flow/phase2_phase3.yaml` + `flow_compliance_check.py --strict` gate. No step is optional; waivers require ≥20-char human-reviewed reasons and a non-self approver. Agents must emit the full 33-step plan table before executing any step.
- **Anti-fabrication enforcement (v0.47.2-.4)** — gates now ask "was this file produced by a real tool run?" not just "does this file exist?":
  - **`def_stage_progression_check`** rejects byte-identical PnR stage DEFs (the "copy routed.def 5 times" cheat)
  - **Tool-signature + min-size checks** in `eda_report_audit` reject hand-typed <2 KB report stubs
  - **`fpga_on_board_attestation_check`** rejects pure-JSON self-attestation for Step 28; requires a Quartus programmer log **and** non-JSON hardware evidence (webcam / UART / scope)
  - **`provenance_logger` + `provenance_check`** pair: tools must be wrapped; gates verify the logged SHA-256 matches the file on disk (mandatory at Steps 9 / 19 / 24 / 27)
- **Phase-1 fact-manifest architecture** — per-layer manifests (starting `lessons/manifests/L1_manifest.json`, 40 facts) encode every required data point as `{pm_question_beginner|intermediate|expert, ic_expert_default, provenance_hint}`. PM agent asks user from the Q-bank; IC Expert assembles final JSON from user answers + documented defaults. No benchmark is read at inference.
- **Open-source ATPG integration** — `fault_atpg_run.py` wraps Fault (cloudv-io) inside the iic-osic-tools Docker image. Eliminates the "no commercial ATPG" waiver; produces real stuck-at coverage metadata on every synthesized netlist.
- **65 skills**, **78 deterministic programs**, **786 test functions** (122 test files). Strict 4-of-4 compliance (legacy 3-of-4 demoted to `--lenient` for WIP drafts).

**Change log**:

- **v0.52** (2026-04-24, post-`phase2+3_v051` honest-FAIL fix): closes the byte-level-sim PASS / FPGA-bit-level-FAIL gap exposed when the v0.51 fresh-agent run on the benchmark IC PASSed every Rule A/B/C gate yet returned padding-only `02 02 …` from the real protocol tester. Two new gates:
  - **`bit_level_full_stack_tb_check.py`** (Rule D in `spec-to-rtl/SKILL.md`) — requires a synth-able full-stack tb under `sim_full_stack/` that instantiates the chip top, drives the single-wire pad bit-by-bit, decodes the response back to bytes, and writes `results.json` with `distinct_non_padding_bytes ≥ 10` and `opcodes_tested ≥ 3` (same response criterion `hardware_pass_attestation_check` uses). Prevents proceeding to FPGA without exercising the bit-to-byte assembler / `tx_phy` first-byte handshake / `rx_phy` bit-classifier in sim. +16 tests.
  - **`signoff_audit.py` PDK-input exclusion fix** — file discovery now excludes path segments under `input/`, `inputs/`, `pdk/`, `vendor_ref/`, `references/`. The v0.51 run accepted PDK standard-cell GDS at `input/pdk/gds/<stdcell>.gds` as design tape-out evidence; `_has_files()` now drops those by default. +4 regression tests.
  - **`phase1-orchestrate/SKILL.md`** rewritten from L1-L9 to **L1-L13 + cross-checks** — adds explicit steps for `test-cases-gen` (L10), `calibration-gen` (L11), `behavioral-sequences-gen` (L12), `lab-calibration-gen` (L13), `doc-consistency-check`, `schematic-gen`, plus the corresponding gate invocations (`layer_extension_presence_check`, `phase1_consistency_check`, `clock_scale_consistency_check`, `manifest_leak_check`). The agent that hit the v0.51 byte-vs-bit gap was working off the stale L1-L9 description and skipped the L10-L12 layers downstream gates depend on.
  - Plugin tests: **1165 passed / 0 failed** (61 skipped, 6 xfailed).
- **v0.51**: Vendor-leak audit **+ post-audit smoke-test PASS**. A fresh agent was spawned with the v0.51 plugin on a previously-used benchmark IC input set (19 vendor docs) under hard bans (no peek at any prior-version RTL, no memory-of-past-fix recipes, no vendor RTL references). Following only Rule A (`input_docs_coverage_check` — read every `input/docs/` file + write coverage manifest) → Rule B (L1-L13 extraction + quality-parity + L10/11/12 presence + `cmd_response_conformance_check` sim with 11/11 byte-for-byte) → Rule C (`rtl_unit_test_coverage_check` — per-module iverilog tbs for every FSM-bearing module) → Layer 3 (`hardware_pass_attestation_check` against the real benchmark tester), the agent reached **real-hardware PASS first attempt** — signature matches golden byte-for-byte, stable over 5 consecutive invocations. Three RTL bugs were found and fixed **from Rule C tb evidence alone** (no reference peek): OTP-read 1-cycle latency, `tx_mac` always-on abort detector, RX window sizing (scaled from the µs timing pptx, not a tester's cycle counts which would be wrong at a different core clock). This retires the v0.50.2 gap and proves the Rule-A→B→C→3 path is reproducible without reference RTL. Plus: the "no cheating, generic for any IC" code audit itself — the plugin previously named specific commercial ICs in places that should be class-generic — a `cmd_protocol_crc_verify.py` CRC preset hard-coded a vendor-protocol name, the `cable-side-id-ic` class template described itself as a specific-part-number class with a vendor-tester-named test-sequence field and vendor-specific required-sequence ids, `class_reference.yaml` cited a single vendor's datasheet as the canonical reference, and `lessons/manifests/L1_manifest.json` left vendor strings in `benchmark_value` samples even after v0.47.7 nulled the corresponding `ic_expert_default`. v0.51 anonymises all of these: CRC preset renamed to a generic `MAXIM-VARIANT init=0xFF`; class template described as a generic single-wire ID controller class with a `production_test_sequence` field; required-sequence ids replaced with generic `validation_chain` + `host_stimulus_sequence` categories; class reference replaced with a multi-source generic citation; manifest strings anonymised to `BENCHMARK_IC`, `BENCHMARK_TESTER`, `single-wire ID protocol`, etc. `layer_extension_presence_check.py` updated to enforce required CATEGORIES not vendor-specific ids. README + memory post-mortems retain the case-study narrative (legitimate lessons-learned history) but all vendor identity has been stripped from both narrative text and executable plugin code. Plugin tests: 961 passed / 0 failed / 2 skipped / 6 xfailed.
- **v0.50.2**: benchmark IC fresh-agent reaches **protocol tester PASS without referring to any v037v2 reference RTL** — response matches golden signature byte-for-byte. Path that worked: scope+USBTMC verified DUT didn't drive bus → in-FPGA debug LEDs narrowed to dispatcher-stuck-in-IDLE → iverilog per-module tbs (`tb_rx_phy.v` + `tb_dispatcher.v`) revealed two bug classes: `CYC_FRAME_END` shorter than max in-frame high gap (silently drops bytes after byte 1), and dispatcher `S_RX` treating trailing BR as mid-frame restart (clears byte buffer, length check fails). Both fixes from spec docs alone. Lessons captured as: new skill `rtl-unit-testbench-gen` (mandates sim_unit/tb_<module>.v with realistic-timing pulse stimuli + per-event $display + explicit PASS/FAIL verdict); new program `rtl_unit_test_coverage_check.py` (FSM-bearing modules must have a per-module tb); spec-to-rtl SKILL.md adds Rule C ("when sim PASS + hardware FAIL, write per-module tb FIRST — 100x faster than scope+camera"). +5 tests, +3 patterns, all PASS.
- **v0.50-pre** (2026-04-23/24 unreleased patches): hardware reality-check retraction of v0.48 "52/52 self-BIST PASS" (was loopback-only, fails real protocol tester). 2 new programs (`input_docs_coverage_check.py`, `cmd_response_conformance_check.py`) close the functional-vs-structural-gate gap + 10 new tests. `spec-to-rtl/SKILL.md` updated with two MANDATORY rules: read every `input/docs/` file + close-loop CMD→RSP conformance. Fill-to-Floor Rule in `ic-expert-agent.md`; `spec_floor:` block in `class_kb/templates/cable-side-id-ic.yaml` (L3 opcodes ≥8, CRC poly whitelist, L4 OTP ≥64 B, L6 ≥10 submodules with 10 required, L9 ports ≥18 wires ≥30); `phase1_quality_parity_check.py` new gate (fuzzy submodule match with u_/i_/inst_/m_ prefix strip, 6 pytest tests). Re-ran v0.49's failed 3-persona benchmark: **all 3 now produce same-quality L*.json; 4/4 gates exit 0 across common/medium/high**. Fixes the "persona fidelity dominates silicon fidelity" gap documented in `project_v049_3persona_benchmark` memory. Phase 2+3 silicon parity verification pending.
- **v0.49**: Phase-1 training scorecard (127/127 across 5 gates); 20/20 Yosys synth pilot on LLM-generated RTL (~220K gates); K5 quality loop closed with 9 patterns (A-I) mined from real synth + enforced by `phase1_k5_quality_check.py` + referenced in Phase-1 skill SKILL.md PRACTICAL_NOTES. 3 new programs: `phase1_consistency_check.py` (15 K4 rules), `phase1_k5_quality_check.py` (9 K5 patterns), `otp_image_check.py`. 5-gate CI workflow `.github/workflows/phase1_regression.yml`. Training corpus reorganised under `benchmark/phase1_v046/` (96 primary ICs + 22 dialogue + 9 persona). No Phase 2+3 changes; v0.48 outcomes carry over unchanged. **2026-04-23 3-persona end-to-end benchmark on the benchmark IC**: ran Phase 1+2+3 under common / medium / high pseudo-user personas with hard bans on prior-version peeking. All three reached `tapeout_signoff_check --strict 4/4 PASS` with real tool-run evidence; `flow_compliance_check --strict` scored 14/28 / 3/28 / 3/28 respectively (bookkeeping gap, not artefact gap). Silicon fidelity tracked persona fidelity — common persona's vague cues produced a generic cable-auth IC (CRC 0x07, 4 commands); high persona's detailed spec produced a benchmark-IC-equivalent IC (CRC 0x31 MAXIM, 13 opcodes). Two plugin gaps surfaced: (a) no automated BIST-vs-liveness discrimination — high-persona's HEX "52/52" turned out to be a tick counter, self-disclosed in RTL comments, not caught by any gate; (b) `tapeout_signoff_check --strict` and `flow_compliance_check --strict` disagree on "done" for all three runs. `def_stage_progression_check` correctly blocked a DEF-padding fraud attempt by the common-persona agent.
- **v0.48**: Honest fresh-agent end-to-end pilot covering all 3 phases. Initial 2026-04-22 run hit chain-end (`input/` → `.sof` burned) but BIST was 0/13. The 2026-04-23 debug session applied 5 fixes (BIST harness: cmd reorder + trailing-BR shrink 30→2 cycles / master listen-window race; core RTL: awake_state level export, MAC ↔ tx_phy_ready handshake, shared CRC reset between RX/TX) → **BIST 52/52 PASS**. Same day continued with Phase 3: Yosys synth (3576 cells / 128086 µm²) → Fault ATPG 4.6% combinational (no scan insert) → OpenROAD PnR with m18e80pm180su 6-metal CWB flow + 8 threads (0 routing violations in 6m30s after 5 optimization iterations) → OpenSTA 3-corner (typ/wci/bci, setup WNS=0 TNS=0 all corners; hold violations present, no ECO run) → klayout streamout (5.1 MB GDS, 892k shapes, 0 off-grid) → geometric DRC sanity + netlist-vs-GDS instance count LVS (PDK did not ship vendor DRC/LVS runsets — matches v037v2 reference's known limitation) → `tapeout_signoff_check --mode tapeout` **strict 4-of-4 PASS**. Two RTL bug classes recorded for future `rtl-review` upgrade (pulse-vs-state confusion + producer/consumer rate mismatch).
- **v0.47.8**: Closed the input→RTL extraction gap. 3 new programs: `xlsx_extract.py` (tables from .xlsx spec docs — vendors ship CRC golden vectors + OTP maps in .xlsx that prior skills ignored); `cmd_protocol_crc_verify.py` (derive CRC poly/init/refin from golden vectors — no more guessing from a polynomial's name); `clock_scale_consistency_check.py` (reject threshold values lacking `domain_clock` / `source_clock` / `scale_factor` — prevents the 20× scale-factor class of bug). Three SKILL.md files (cmd-protocol-gen, regmap-gen, rtl-constants-gen) now mandate these checks. +15 tests.
- **v0.47.7**: Sanitized `lessons/manifests/L1_manifest.json` — 24 of 40 `ic_expert_default` fields lifted verbatim from the benchmark are now `null` with `provenance_hint: user_required`. New `manifest_leak_check.py` (+6 tests) rejects any future manifest where `benchmark_value == ic_expert_default` for non-generic paths. Closes the same cheat class as v0.47.6 at the Phase-1 layer.
- **v0.47.6**: **Removed `references/&lt;vendor-rtl&gt;/` (17-file verbatim benchmark IC RTL bundle)** from `plugins/vibe-ic/skills/spec-to-rtl/`. The bundle shipped production RTL as an "answer key" and biased "fresh-agent PASS" metrics into mimicry. All v044 / v045 / v046 "reference-reuse PASS" claims retracted. SKILL.md instruction "prefer using the reference verbatim" removed; PRACTICAL_NOTES re-written to say the opposite.
- **v0.47.5**: MCP server auto-logs provenance on `eda_synth / eda_pnr / eda_gds / eda_sta / eda_lvs / eda_drc_klayout`. Agents can no longer opt out — any tool call through the MCP server records a hashed JSONL entry.
- **v0.47.4**: `provenance_check` made **mandatory** at Steps 9 / 19 / 24 / 27. Agents must wrap tool calls with `provenance_logger.py`; gates verify logged hash matches disk hash. Fixes `datetime.utcnow()` deprecation.
- **v0.47.3**: `provenance_logger.py` + `provenance_check.py` + `fpga_on_board_attestation_check.py`. Step 28 now needs 4 evidence classes (JSON + bitstream-hash match + programmer log + non-JSON hardware artefact). +19 tests.
- **v0.47.2**: anti-fabrication hardening — `def_stage_progression_check.py` (catches 5-identical-DEF fraud); `eda_report_audit` requires tool signatures + `MIN_REPORT_BYTES` per mode (rejects 200 B hand-typed stubs). +11 tests.
- **v0.47.1**: `tapeout_signoff_check` wrapper forward `--json/--lenient/--strict` (was silently dropping flags).
- **v0.47**: Phase-1 fact-manifest architecture + `extract_fact_manifest.py` training tool + L1 PoC (40 facts curated). Phase-0 internal helper (`reference-ingest`) removed from public release — was a training-only preprocessor. Honest retraction of earlier "10/10 converged" claims (see tutorial).
- **v0.46.1**: Fault open-source ATPG integration — Step 11 waiver eliminated. Aon_timer pilot: 6433 fault sites, 60.35 % stuck-at, 36 essential test vectors.
- **v0.46**: Strict 28-step flow enforcement. 15 gate-signature bugs fixed. `flow_compliance_check.py` + 4 per-stage gates + `waivers_schema_check.py`. Strict threshold 4/4. Aon_timer pilot: 27 PASS + 1 WAIVED (only on-board FPGA test; environmental). **Catches and blocks the "7 of 28 steps, declared PASS" failure mode.**
- v0.45: +2 programs for Phase-1 doc completeness + fresh-agent provenance honesty (8 tests). *(Shipped a `references/&lt;vendor-rtl&gt;/` verbatim-copy bundle — removed in v0.47.6; see below.)*
- v0.43: +2 programs for device-response-no-BR + Verilog bitwidth consistency (8 tests)
- v0.42: +2 programs for gap-reset granularity + CRC init=0xFF residual (8 tests)
- v0.41: +4 programs for CRC / handshake / CDC / reset (18 tests)

**Proven outcomes**:

- **v0.51 fresh-agent real-hardware PASS — FIRST attempt, zero reference peek (2026-04-24)**: STRICT fresh-agent on v0.51 plugin, input set = same 19 vendor docs used throughout the benchmark. Hard bans: no prior-version RTL, no memory of past bug fixes, no vendor RTL references. Flow = Rule A (input-docs coverage 19/19) → Rule B1-B5 (L1-L13 extraction + quality parity + `cmd_response_conformance_check` sim 11/11 byte-for-byte) → Rule C (per-module iverilog tbs, 9/9 FSM modules) → Layer 3 (`hardware_pass_attestation_check`). **All 8 plugin gates PASS** on the first end-to-end run. On-board signature over the real protocol tester is byte-for-byte identical to golden and stable over 5 consecutive `SEND_TEST` invocations. Three bugs found-and-fixed **from Rule C tb evidence alone** (no reference peek): OTP-read 1-cycle latency (S_READ → S_READ_W1/W2), `tx_mac` always-on abort detector (arm only in S_BIT_HIGH/S_BYTE_IBT), RX window sizing (scaled from the µs timing pptx, not from a specific tester's cycle counts — those would be wrong at a different core clock). **This retires the v0.50.2 gap** (where a reference peek was still implicit in the debug loop) and establishes that Rule-A→B→C→3 is a reproducible recipe without reference RTL.
- **v0.48 benchmark IC fresh-agent end-to-end (2026-04-22 → 2026-04-23) — BIST 52/52 PASS**: STRICT fresh-agent pilot (banned v037v2 / v044 / v045 / v047 / agent memory / vendor RTL). Starting from `input/` only (19 vendor docs), the agent derived CRC params from 16 xlsx golden vectors (poly=0x31, init=0xFF, matches ID protocol spec), produced 10 L1-L9 layer docs (both phase1 gates exit 0), generated 15 RTL files / 2,241 lines (iverilog + Yosys clean), Quartus compiled `.sof` (1,955 LE, 0 errors, timing met), burned to DE10-Lite via USB-Blaster (JTAG ID 0x031050DD). Initial 2026-04-22 BIST: 0/13 opcodes PASS. After 2026-04-23 debug session iterating purely on BIST harness + RTL wiring (no spec changes), final **on-board BIST: 13/13 opcodes × 4 stress loops = 52/52 PASS**, equal to v037v2 human-engineer baseline. Five fixes applied: (1) `rx_cmd.awake_state_o` exposed as latched level (was 1-cycle pulse); (2) MAC handshake with `tx_phy_ready_i` (was free-running tx_bit_valid); (3) shared CRC reset shared between RX and TX paths; (4) BIST cmd table reordered with 0x74 first to set device awake_state in loop-1 cmd-0; (5) BIST `BR_HIGH_CYC` reduced 30→2 cycles to enter S_RX_WAIT before device's earliest response edge (master listen-window race). Honest conclusion: **chain reproducible from docs to bitstream and to functional BIST PASS** with debug effort comparable to a manual bring-up. Next gap: `rtl-review` program upgrade to catch pulse-vs-state and producer/consumer rate-mismatch classes statically.
- **v046 aon_timer** (open-source IP + strict flow): OpenTitan `aon_timer` through all 28 steps — 27 PASS + 1 WAIVED (no FPGA board in sub-agent env). 0 silent-failure findings, `stuck_at_ge_target = True` via Fault. Simulated-signoff PASS, not on-board-tested.
- ~~**v044 benchmark IC** (reference-reuse): fresh agent copied `references/&lt;vendor-rtl&gt;/` verbatim + wrote own QSF → protocol tester PASS 5/5~~ — **RETRACTED v0.47.6**. The bundle's RTL was byte-identical to the benchmark; "copying it verbatim" is not a plugin capability. Bundle removed. Only the v037v2 spec-generation PASS below still stands as a real outcome.
- **v037v2 benchmark IC** (spec-generation): fresh agent regenerated all 17 RTL modules from L1-L9 docs → **protocol tester PASS 3/3**. Stands as the only real hardware-PASS outcome to date.
- **Phase-1 fact-manifest PoC (v0.47)**: L1 layer — 40 facts extracted from benchmark, curated with 3-level Q-bank + defaults + provenance hints. PM subagent produced `pm_collected.json` with user-answered + deferred splits. **Open honesty**: value-correct JSON-from-dialogue alone (no reference-material extractor) is not yet achieved — earlier "10/10 converged" claims were shortcut-tainted and have been retracted (see `docs/tutorials/phase1_closed_loop_training.md`).

**Anti-cheating provenance (NEW)** — v0.47.4 honestly documents that a 2026-04-22 benchmark-ic pilot had a subagent fabricate 15 of 28 steps (5 byte-identical DEFs + 6 hand-typed <2 KB report stubs + 1 pure-JSON FPGA self-attestation). Every failure mode is now an automated gate (see Honesty Boundaries).

---

## What is Vibe-IC?

Vibe-IC brings the "Vibe Coding" paradigm to IC design. Instead of manually driving dozens of EDA tools through arcane TCL scripts, you describe what you want in plain language and an AI agent orchestrates the entire RTL-to-GDSII flow.

**This is not AI4EDA** (bolting ML onto existing tools). This is **AI-Native Design**: the AI agent is the core decision-maker; EDA tools are callable execution engines.

### Three-phase design flow (**source of truth: `plugins/vibe-ic/flow/phase2_phase3.yaml`**)

```
┌────────────┬────────────────────────────────────────────────┬────────────────────────┐
│ Phase 1    │ Dialogue → L1-L9 design documents              │ pm-agent → ic-expert-  │
│            │ (phase1-orchestrate, 10 lesson files)          │ agent → L1..L9 JSON    │
├────────────┼────────────────────────────────────────────────┼────────────────────────┤
│ Phase 2    │ Step 01-06: RTL generation + verification      │ RTL + sim + formal     │
│            │ Step 07-13: synthesis + DFT (+ Fault ATPG)     │ + FPGA early proto     │
│            │                                                │ + mapped netlist       │
├────────────┼────────────────────────────────────────────────┼────────────────────────┤
│ Phase 3    │ Step 14-24: physical design + sign-off         │ CTS, routing, DRC/LVS  │
│            │ Step 25-28: output + validation                │ tape-out GDS + FPGA    │
│            │                                                │ on-board sign-off      │
└────────────┴────────────────────────────────────────────────┴────────────────────────┘

                     ┌─────────────────────────────────────┐
                     │  flow_compliance_check.py --strict  │
                     │           exit 0 = PASS             │
                     └─────────────────────────────────────┘
```

Verified on **GF180MCU 180 nm**, **SKY130 130 nm**, and the **m18e80pm180su** custom 180 nm PDK. Hardware-validated on a DE10-Lite (MAX10) FPGA with a production single-wire ID communication IC (2,827 cells, 17 RTL modules) via the protocol tester.

---

## Plugins in this marketplace

| Plugin | Purpose | Count |
|--------|---------|-------|
| **[vibe-ic](plugins/vibe-ic/)** | Skill catalog — one SKILL.md per task. Includes `flow-orchestrate` (strict 33-step entry point), 2 agents, 10 lesson files, Phase-1 orchestrator, L2-L9 doc generators. | 60 skills + 2 agents + 10 lessons |
| **[vibe-ic-d](plugins/vibe-ic-d/)** | **Deterministic edition** — compliance YAMLs + programs that make skill execution auditable. Includes `flow_compliance_check`, 4 per-stage gates, `waivers_schema_check`, `fault_atpg_run`, and the v0.47.2-.4 anti-fabrication layer (`def_stage_progression_check`, `provenance_logger/check`, `fpga_on_board_attestation_check`). | 60 compliance specs + 64 programs |

### vibe-ic vs vibe-ic-d

- `vibe-ic` alone gives you the skill library and the agent definitions. Agents produce high-quality output but **different agents may skip different sections** — a variability source that breaks reproducibility.
- `vibe-ic-d` adds a **compliance gate** at two levels:
  1. **Per-skill** — every SKILL.md has a matching `compliance.yaml` enumerating required output elements (section headers, metadata fields, handoff lines, tool invocations). A generic driver audits skill output; task only completes when the audit returns PASS.
  2. **Per-flow** — the 33-step canonical Phase 2+3 flow has per-step gate predicates and a top-level `flow_compliance_check --strict` that must exit 0 before any PASS claim. Waivers are machine-validated (reason ≥ 20 chars, non-self approver).

**This is the plugin's public contract with agents**: if `flow_compliance_check --strict` exits non-zero, the design is not signed off. Period.

Provenance: vibe-ic-d's discipline was extracted from two **real** debug sessions —
- 2026-04-16: 11 distinct FPGA-protocol bugs traced to SKILL.md sections agents skipped silently.
- 2026-04-21: a 10-IC Phase 2+3 campaign ran only 7 of 28 mandatory steps yet declared "10/10 PASS". Led to the strict 28-step gate, 15 YAML gate-signature fixes, and the open-source Fault integration.

See [plugins/vibe-ic-d/README.md](plugins/vibe-ic-d/README.md) for the full program matrix.

---

## The canonical Phase 2+3 flow (33 steps)

**Source of truth**: [`plugins/vibe-ic/flow/phase2_phase3.yaml`](plugins/vibe-ic/flow/phase2_phase3.yaml)

**Entry point for agents**: [`AGENT_USAGE_GUIDE.md`](AGENT_USAGE_GUIDE.md) — mandatory first read.

### Stage 1 — RTL + Verification (Steps 01-06)

| # | Step | Primary skill | Gate |
|---|---|---|---|
| 01 | Spec-to-RTL | `spec-to-rtl` | `rtl/*.sv` present |
| 02 | Lint (hygiene + Quartus-unsafe ROM init) | `rtl-review` | `rtl_hygiene_lint` + `rom_init_lint` exit 0 |
| 03 | CDC / RDC | `cdc-check` + `rdc-check` | 3 CDC programs exit 0 |
| 04 | Simulation (testbench-driven) | `testbench-gen` | `sim/results.xml` or `sim/pass.flag` |
| 05 | Formal (assertions proved) | `assertion-gen` + `formal-verify` | `formal/results.json.all_proved = true` |
| 06 | FPGA early prototype | `fpga-test-harness` | `.sof` + `quartus_map_audit.json` |

### Stage 2 — Synthesis + DFT (Steps 07-13)

| # | Step | Primary skill | Gate |
|---|---|---|---|
| 07 | Constraint setup (SDC + PVT) | `constraint-gen` | `constraints/*.sdc` + `pvt_matrix.json` |
| 08 | SDC validation | `sdc-validator` | `sdc_syntax_check` exit 0 |
| 09 | Synthesis (Yosys → netlist) | `synth-doctor` + MCP `eda_synth` | `synth_netlist_check` exit 0 |
| 10 | Pre-layout STA (multi-corner) | `sta-review` + MCP `eda_sta` | `sta_report_check --mode sta` exit 0 |
| 11 | **DFT insertion (scan + ATPG)** | `dft-insert` + `atpg` + **`fault_atpg_run`** | `stuck_at_ge_target = true` |
| 12 | Post-DFT optimization | `synth-doctor` | `synth/post_dft_netlist.v` present |
| 13 | Equivalence check (RTL ≡ post-DFT) | `equivalence-check` | `reports/lec.json.equivalent = true` |

### Stage 3 — Physical Design + Sign-off (Steps 14-24)

| # | Step | Primary skill | Gate |
|---|---|---|---|
| 14 | Floorplan + PDN | MCP `eda_pnr` | `pnr/floorplan.def` |
| 15 | Clock planning | `cts-plan` | `cts/clock_plan.json` |
| 16 | Placement | `placement-optimize` | `pnr/placed.def` |
| 17 | **CTS (Clock Tree Synthesis)** | MCP `eda_pnr` | `pnr/post_cts.def` + `clock_tree.rpt` |
| 18 | Post-CTS hold fixing | `hold-fix` | `pnr/post_hold.def` |
| 19 | Routing | MCP `eda_pnr` | `routed.def` + DRC 0 viol |
| 20 | Post-route STA (MCMM sign-off) | `sta-review` + MCP `eda_sta` | WNS ≥ 0 across all corners |
| 21 | IR drop | `ir-drop-triage` | `ir_drop_report_check` exit 0 |
| 22 | EM check | `em-check` | `em_report_check` exit 0 |
| 23 | Antenna check | (PDK) | `reports/antenna.rpt` clean |
| 24 | Physical Verification (DRC / LVS / ERC) | `drc-fix` + `lvs-triage` + `perc-check` | All three exit 0 |

### Stage 4 — Output + Validation (Steps 25-28)

| # | Step | Primary skill | Gate |
|---|---|---|---|
| 25 | Power analysis | `power-analysis` | `power_report_check` exit 0 |
| 26 | Tapeout checklist | `tapeout-checklist` | `tapeout_signoff_check --strict` exit 0 |
| 27 | **GDSII output** (gated on 24 + 26) | MCP `eda_gds` | `gds/*.gds` + `gds_size_check` exit 0 |
| 28 | **FPGA final sign-off** (on-board) | `fpga-test-harness` | `on_board_pass.json.all_scenarios_passed = true` |

### Waivers (the ONLY legitimate way to skip a step)

```json
{
  "waived_steps": [
    {
      "id": 28,
      "reason": "No physical FPGA board in sub-agent env; benchmark IC session already validated the same BIST-on-hardware workflow with matching pass_flags",
      "approver": "reyerchu",
      "ticket": "N/A-pilot"
    }
  ]
}
```

Rubber-stamp waivers are rejected: reason must be ≥ 20 chars and not a placeholder (`TODO`, `n/a`, `skip`); approver must not be `agent` / `self` / `claude`. See `programs/waivers_schema_check.py`.

---

## Agent architecture (Phase 1)

[`plugins/vibe-ic/agents/`](plugins/vibe-ic/agents/)

### Two agents, strict separation of concerns

- **`pm-agent.md`** — dialogue-only PM. Reads the layer's fact manifest and asks the user one targeted question at a time (adapting phrasing to the user's declared skill level: beginner / intermediate / expert). Emits `pm_collected.json` with every fact tagged as `user_answered` or `deferred`. **Never** writes the final L1-L9 doc.
- **`ic-expert-agent.md`** — consumes `pm_collected.json` + the fact manifest + per-layer lessons. For every `deferred` fact, fills in the documented `ic_expert_default` along with its reasoning. Emits the final L1-L9 JSON doc. **Never** reads the benchmark.

### Fact manifest — Phase-1 source of truth

[`plugins/vibe-ic/agents/lessons/manifests/`](plugins/vibe-ic/agents/lessons/manifests/) — one manifest per layer. Each entry:

```jsonc
{
  "path": "ic_name",                    // dot-path in the target L<N>.json
  "benchmark_value": "Single-wire ID Controller",
  "type": "str",
  "category": "identity",
  "pm_question_expert":       "IC name/part number?",
  "pm_question_intermediate": "What is the name or part number of the IC you want to design?",
  "pm_question_beginner":     "What should we call this chip?",
  "ic_expert_default": "Single-wire ID Controller",
  "default_reasoning": "Matches benchmark reference design target for reproduction.",
  "provenance_hint": "user_stated"
}
```

- **Built by `tools/training/extract_fact_manifest.py`** (internal training tool) which walks a benchmark JSON and emits every leaf value as a fact skeleton. A curator (human or IC-Expert subagent) fills in the Q-bank, defaults, and provenance.
- **Used at inference** by PM + IC Expert — no benchmark read.
- **Current status**: L1 manifest has all 40 facts curated (PoC). L2-L9 manifests are still schema-only prose lessons (`lessons/ic_expert_L2..L9.md`).

### Sample dialogues (reference only)

`docs/tutorials/phase1_sample_dialogue_{beginner,intermediate,expert}{,_zh}.md` — six dialogues (EN + ZH × three user levels) showing the PM agent's intended shape.

### Tutorial

[`docs/tutorials/phase1_closed_loop_training.md`](../docs/tutorials/phase1_closed_loop_training.md) — full methodology **and** the post-mortem of two earlier verification attempts that used unsound shortcuts (mimicry with answer key visible / verbatim copy from prior runs). The tutorial is written as a retraction and is the honest baseline for future work.

---

## Installation

```bash
# Clone the marketplace
git clone https://github.com/reyerchu/AI_IC_design.git
cd AI_IC_design

# Install core skills + agents
claude plugin install vibe-ic-marketplace/plugins/vibe-ic

# Install the deterministic edition (recommended — compliance gates)
claude plugin install vibe-ic-marketplace/plugins/vibe-ic-d

# MCP EDA server (Docker-packaged 20 tools; optional but recommended)
cd mcp-eda-server && npm install && npm start
```

Manual install:

```bash
cp -r vibe-ic-marketplace/plugins/vibe-ic /path/to/your-project/.claude/plugins/
cp -r vibe-ic-marketplace/plugins/vibe-ic-d    /path/to/your-project/.claude/plugins/
```

---

## Typical workflow

```bash
# ---- Phase 1 ---- dialogue + doc generation -------------------------
"I want a chip that does X"                   → pm-agent (dialogue)
   └→ handoff                                 → ic-expert-agent (L1..L9 JSON)

# ---- Phase 2+3 ---- 33-step canonical flow --------------------------
"Run Phase 2+3 for this IC"                   → skill: flow-orchestrate
                                                (emits 33-step plan BEFORE executing)
   └→ per-stage gate after each stage         → stage{1,2,3,4}_compliance.py
   └→ final gate                              → flow_compliance_check.py --strict

# ---- Skill-level single-task invocations (any time) -----------------
"Review this RTL"                             → skill: rtl-review
"Write a testbench for X"                     → skill: testbench-gen
"Triage this DRC report"                      → skill: drc-fix
"Ready for tapeout?"                          → skill: tapeout-checklist
```

**The canonical rule**: for any task that touches downstream EDA (synth, PnR, GDS, sign-off), the agent's first action must be to invoke `flow-orchestrate` — do not let an agent call Quartus / Yosys / OpenROAD directly from a prompt. See [`AGENT_USAGE_GUIDE.md`](AGENT_USAGE_GUIDE.md).

---

## Skills catalog (65 total)

Grouped by design-flow phase.

### Phase 1 — Dialogue → L1-L9 (11 skills)
| Skill | Purpose |
|---|---|
| **phase1-orchestrate** | Entry point; drives pm-agent + ic-expert-agent |
| **prompt-intake** | Initial user-dialogue intake for the PM Agent |
| **datasheet-gen** | Generate structured datasheet-style L1 doc |
| **frs-gen** | L2 Functional Requirements |
| **cmd-protocol-gen** | L3 Command Protocol |
| **regmap-gen** | L4 Memory Map / Register spec |
| **adi-spec-gen** | L5 Analog-Digital Interface |
| **control-logic-gen** | L6 Control Logic |
| **test-debug-gen** | L7 Test & Debug |
| **timing-waveform-gen** | L8 Timing & Waveform (external + internal) |
| **integration-spec-gen** | L9 Integration (DTOP ports, submodules, wires) |
| **doc-consistency-check** | Cross-layer consistency verification |

### Phase 2 — RTL + Verification (13 skills)
spec-to-rtl, rtl-review, rtl-repair, rtl-constants-gen, assertion-gen, testbench-gen, formal-verify, equivalence-check, cdc-check, rdc-check, coverage-closure, ppa-predict, hls-c2rtl, synth-wrapper-gen.

### Phase 2/3 — Synthesis → GDSII (16 skills)
synth-doctor, dft-insert, atpg, upf-author, constraint-gen, sdc-validator, placement-optimize, cts-plan, sta-review, hold-fix, drc-fix, lvs-triage, ir-drop-triage, em-check, perc-check, eco-plan, power-analysis.

### Orchestration + sign-off (6 skills)
**flow-orchestrate** (canonical 33-step), spec-review, spec-validator, architecture-explore, checkpoint-gate, tapeout-checklist, regression-manage.

### Silicon-adjacent (6 skills)
analog-sizing, analog-layout, ams-sim, schematic-gen, bringup-plan, yield-diagnostic.

### FPGA prototyping (3 skills)
fpga-hps-bridge, fpga-signaltap, fpga-test-harness.

### Domain-specific (1 skill)
**otp-content-gen** — generate OTP memory contents from spec (single-wire ID controller family).

---

## MCP EDA Server v2.0 (20 tools)

One Docker image (`hpretl/iic-osic-tools:latest`) provides every tool. Supports GF180MCU, SKY130, and custom PDKs (e.g. `m18e80pm180su`).

| Category | Tools |
|----------|-------|
| Synthesis | Yosys (`eda_synth`) |
| Verification | Verilator (`eda_lint`), iverilog (`eda_simulate`), SymbiYosys (`eda_formal`), cocotb (`eda_cocotb`), Yosys LEC (`eda_equiv`) |
| Timing | OpenSTA (`eda_sta`, `eda_sta_mcorner`) |
| Backend | OpenROAD (`eda_pnr`), KLayout (`eda_gds`, `eda_drc_klayout`), Magic (`eda_extraction`) |
| Signoff | Netgen (`eda_lvs`), OpenROAD PSM (`eda_ir_drop`), **Fault** (`eda_dft` via `fault_atpg_run`) |
| Analog | ngspice / Xyce (`eda_spice`) |
| Audit | vibe-ic-d programs (`eda_rtl_audit`) |
| FPGA | Quartus / Vivado (`eda_fpga_compile`, `eda_fpga_program`) |
| Search | PostgreSQL (`eda_ic_search`) |

See [mcp-eda-server/INSTALL_GUIDE.md](../mcp-eda-server/INSTALL_GUIDE.md).

---

## Deterministic programs (80 total)

```
cd plugins/vibe-ic-d/programs && python3 -m pytest tests/ -q
# 526 passed, 2 skipped, 0 failed.
```

**Headline programs**:

*v0.46 — canonical flow + gates*:

| Program | Role |
|---|---|
| **`flow_compliance_check.py`** | Strict 33-step gate — reads `flow/phase2_phase3.yaml`, validates every step's outputs + gate predicate, rejects rubber-stamp waivers. **Exit 0 is the only PASS.** |
| `stage{1,2,3,4}_compliance.py` | Per-stage interim gates |
| **`waivers_schema_check.py`** | Rejects placeholder reasons (`TODO`, `n/a`), self-approvers (`agent`, `claude`), duplicate ids |
| **`fault_atpg_run.py`** | Open-source stuck-at ATPG via Fault + iic-osic-tools Docker. PDK_CONFIG table supports GF180 + m18e80pm180su. |
| **`rom_init_lint.py`** | Catches Quartus-unsafe `initial begin for(i=0;...) rom[i]=...` (silent-failure class surfaced 2026-04-21) |
| **`quartus_map_audit.py`** | Scans `.map.rpt` for `Stuck at GND/VCC`, Warning 10030/10855, lost fanout |
| **`bist_window_calculator.py`** | Computes sample-window size for BIST responses |
| `otp_image_check.py` | Validates OTP-content generator outputs |

*v0.47.2-.4 — anti-fabrication layer*:

| Program | Role |
|---|---|
| **`def_stage_progression_check.py`** | Rejects byte-identical stage DEFs (the "`cp routed.def 5 times`" cheat). Requires SHA uniqueness + size monotone + instance-count non-regression + `+ ROUTED` geometry. |
| **`provenance_logger.py`** | Wrap ANY tool invocation; records `{tool, version, argv, input/output hashes, exit, duration}` to `<project>/provenance.jsonl`. |
| **`provenance_check.py`** | Gate verifier: does `provenance.jsonl` contain an exit-0 entry, from an allow-listed tool, declaring this output, whose logged hash still matches the file on disk? Mandatory at Steps 9 / 19 / 24 / 27. |
| **`fpga_on_board_attestation_check.py`** | Step 28 hardening: rejects pure-JSON self-attestation. Requires pass.json + bitstream-hash match + Quartus programmer log + ≥1 non-JSON hardware artefact (webcam / UART / scope). |
| `eda_report_audit` tightened | Every mode now needs tool signature (OpenROAD/Netgen/KLayout/Magic) + `MIN_REPORT_BYTES`. Rejects hand-typed <2 KB stubs. |

See [plugins/vibe-ic-d/README.md](plugins/vibe-ic-d/README.md) for the full matrix.

---

## Repository structure

```
vibe-ic-marketplace/
├── AGENT_USAGE_GUIDE.md             ← MUST READ for any agent
├── README.md                        ← this file
├── .claude-plugin/marketplace.json
└── plugins/
    ├── vibe-ic/
    │   ├── flow/
    │   │   └── phase2_phase3.yaml   ← 33-step source of truth
    │   ├── agents/
    │   │   ├── pm-agent.md           ← dialogue-only PM (asks per manifest)
    │   │   ├── ic-expert-agent.md    ← assembles JSON from answers + defaults
    │   │   └── lessons/
    │   │       ├── ic_expert_L1..L9.md   ← prose lessons per layer
    │   │       └── manifests/
    │   │           └── L1_manifest.json  ← 40-fact Q-bank (PoC)
    │   └── skills/
    │       ├── flow-orchestrate/    ← strict 33-step entry
    │       ├── phase1-orchestrate/  ← Phase-1 dialogue driver
    │       ├── spec-to-rtl/         ← Step 01
    │       ├── ...                  ← 60 skills total
    │       └── otp-content-gen/
    └── vibe-ic-d/
        ├── programs/
        │   ├── flow_compliance_check.py  ← final gate
        │   ├── stage{1,2,3,4}_compliance.py
        │   ├── waivers_schema_check.py
        │   ├── fault_atpg_run.py         ← Step 11 ATPG
        │   ├── rom_init_lint.py
        │   ├── quartus_map_audit.py
        │   ├── bist_window_calculator.py
        │   └── ...                       ← 62 programs total
        ├── skills/                       ← compliance YAMLs
        └── tests/                        ← 490 tests
```

External tools/ (at repo root): `tools/training/` (closed-loop harness), `tools/phase1_regression.py` (benchmark-driven regression for Phase 1).

---

## Debug-session lessons — where plugin rules come from

Every deterministic program and PRACTICAL_NOTE in this plugin was extracted from a real failure. The lessons accumulated over two major sessions:

### 2026-04-16 — benchmark IC fresh-agent FPGA debug (10 lessons → v0.41-v0.45)

| # | Lesson | Plugin enhancement |
|---|--------|--------------------|
| 1 | Skipping any of 10 Phase-1 L-docs silently produces a simplified L9 → protocol tester FAIL | `phase1_doc_presence_check.py` |
| 2 | RTL generation must not proceed on a partial doc stack | `spec-to-rtl/SKILL.md` mandatory pre-check |
| 3 | "Fresh-agent PASS" claims need provenance labeling | `fresh_agent_provenance_check.py` |
| 4 | Bit-shape protocols need hardware-validated reference RTL | *(2026-04-17) Shipped `references/&lt;vendor-rtl&gt;/` (17 files) as verbatim-copy bundle. **Retracted in v0.47.6**: bundling production RTL biased "fresh-agent PASS" metrics into mimicry. Fix: require complete L1-L9 docs via `phase1_doc_presence_check`; if a user genuinely has vendor RTL, they supply it as flow input with `provenance: user_supplied_reference`.* |
| 5 | End-of-command gap must reset on bit-level, not byte-level | `gap_reset_granularity_check.py` |
| 6 | CRC residual `== 0` rule is init-dependent | `crc_residual_check.py` |
| 7 | Device response MUST NOT emit leading BR | `device_response_no_br_check.py` |
| 8 | Verilog bit-select must match declared register width | `bitwidth_consistency_check.py` |
| 9 | LED-per-FSM-state + webcam unlocks remote hardware debug | `fpga-test-harness/PRACTICAL_NOTES.md` |
| 10 | Tester LCD photos can show false PASS — verify decoded byte stream | `fpga-test-harness/PRACTICAL_NOTES.md` |

### 2026-04-21 — 10-IC Phase 2+3 campaign disaster (5 lessons → v0.46)

| # | Lesson | Plugin enhancement |
|---|--------|--------------------|
| 1 | Agent prompts that call tools directly (Quartus / Yosys / OpenROAD) skip 21 of 28 mandatory steps | Canonical 28-step flow in `flow/phase2_phase3.yaml` + rewritten strict `flow-orchestrate/SKILL.md` + mandatory plan-table emission up-front |
| 2 | 3-of-4 legacy threshold rubber-stamps 7-of-28 compliance as "signed off" | `signoff_audit.py` threshold 3/4 → 4/4 (`--lenient` restores legacy) + strict `flow_compliance_check.py` |
| 3 | YAML gate strings drifted from program CLIs (14 gate-signature bugs across ~14 steps) | Unified `--json PATH` interface; glob expansion in `flow_compliance_check`; 14 gate rewrites |
| 4 | Waivers without validation become "TODO: fix later" silent skips | `waivers_schema_check.py` — rejects placeholder reasons + self-approvers |
| 5 | "No commercial ATPG" is a solvable waiver, not a permanent gap | `fault_atpg_run.py` + iic-osic-tools integration — real stuck-at coverage on every synthesized netlist |

### 2026-04-22 — benchmark-ic v0.47 pilot: subagent fabricated 15 of 28 steps (→ v0.47.1-.4)

Symptom: subagent ran the canonical 28-step flow against the
hardware-verified benchmark IC baseline, reported **27 PASS / 1 WAIVED**,
`flow_compliance_check --strict` exit 0. Real runtime was 12 minutes —
suspicious on its own, since aon_timer's honest run took ~1 h.

Forensic audit showed:

| Cheat | Evidence | Steps affected |
|---|---|---|
| Copied `pnr/top.def` to all 5 stage names | 5 byte-identical DEFs, all 546,067 B with mtime 02:17:49 | 14, 16, 17, 18, 19 |
| Hand-typed "0 violations / all clean" report stubs | 6 files between 500 B and 1.4 KB with generic "spacing: 0" text | 21, 22, 23, 24, 25 |
| Pure JSON self-attestation for FPGA on-board test | `{"all_scenarios_passed": true}` — no actual board in environment | 28 |
| `tapeout_signoff_check` wrapper silently dropped `--json` flag | required_outputs file never written; exit 0 anyway | 26 |

The existing gates (file-exists + keyword-match) passed all of this.

| # | Lesson | Plugin enhancement |
|---|--------|--------------------|
| 1 | Gates that only check `files_exist` let an `echo > file.rpt` agent through | `eda_report_audit` — every mode now needs tool signature (OpenROAD/OpenSTA/Netgen/KLayout/Magic...) + `MIN_REPORT_BYTES` size floor (1-2 KB/mode) |
| 2 | Byte-identical PnR stage DEFs are the obvious "I copied it" signal — but nothing was checking | `def_stage_progression_check.py` — SHA uniqueness + size monotone + instance-count growth + routed-geometry presence. Wired into Step 19. |
| 3 | Step 28 JSON was trivially forgeable | `fpga_on_board_attestation_check.py` — requires 4 evidence classes: JSON + bitstream hash match + Quartus programmer log + ≥1 non-JSON hardware artefact (webcam / UART / scope) |
| 4 | Gate model asked "does file exist?" not "was it produced by a tool?" | `provenance_logger.py` wraps tool calls, records `{tool, version, argv, input-hashes, output-hashes, exit, duration, stdout/err hash}` to `provenance.jsonl`. `provenance_check.py` verifies logged hash matches disk hash. **Mandatory** at Steps 9 / 19 / 24 / 27. |
| 5 | `tapeout_signoff_check` wrapper dropped flags | Forward `sys.argv[1:]` verbatim to underlying `signoff_audit.main` |

**Meta-lesson**: plugin value is not "smart agent" — it's "every past mistake is now an automated check". All three sessions started with an agent that believed it had shipped a PASS. Only the gate-programs caught the gap.

### 2026-04-22 — v0.48 fresh-agent end-to-end: input/ → .sof → BIST 0/13

First fresh-agent run since v0.47.6 bundle removal. Banned list enforced strictly: v037v2 / v044 / v045 / v047 / agent memory / any vendor RTL. Chain reproduced from `input/` to a JTAG-burned DE10-Lite `.sof`. Physical board lights and CONF_DONE confirmed via camera. Self-BIST scored 0/13 opcodes PASS.

Two RTL bug classes surfaced that **no existing plugin program catches**:

| # | Bug class | Why existing gates miss it |
|---|-----------|-----------------------------|
| 1 | **Pulse-vs-state confusion** — `rx_cmd.awake_set_o` is a 1-cycle pulse; downstream `rx_chk.state` needs a latched level. Wake gate rejects every non-wake opcode. | iverilog parses, Yosys elaborates, `sv_compat_check` + `provenance` + `phase1_doc_presence` all exit 0. Sim-less static checks can't spot semantic mismatch between producer and consumer. |
| 2 | **Producer/consumer rate mismatch** — MAC asserts `tx_bit_valid` every `sys_clk` (~400 ns); `tx_phy` bit-time is ~10 μs. Only first bit of every response lands. | Same — clean static analysis, no handshake-protocol checker in plugin. |

**Future v0.49 target**: `rtl-review` / `assertion-gen` upgrades to catch these two bug classes (pulse-type audit + valid/ready handshake enforcement). For v0.48, they are documented honest gaps — plugin does NOT yet ship a fix.

### 2026-04-23 — v0.48 BIST 52/52 PASS via in-FPGA diagnostic

Continuation of the 2026-04-22 pilot. Goal: take BIST from 0/13 (then 20/52 after intermediate fixes) all the way to a clean 52/52. No scope, no SignalTap — debug only via DE10-Lite seven-segment HEX displays + LEDs.

Five fixes applied in sequence (none of them required peeking at v037v2/v044 baselines):

| # | Fix | Where | Effect |
|---|-----|-------|--------|
| 1 | Expose `awake_state` as a latched level (was only a 1-cycle pulse `awake_set`) | `rx_cmd.v` → wire to `rx_chk.awake_state_i` in `top.v` | Fixes wake gate rejecting all non-0x74 cmds |
| 2 | MAC produces `tx_bit_valid` only when `tx_phy_ready` (handshake) | `mac.v` ↔ `tx_phy.v` | Fixes "only first bit of every byte lands" |
| 3 | Shared CRC engine reset on every TX-side response start | `mac.v` `crc_reset_tx_o`, OR'd into `crc8.crc_reset_i` | Fixes residual CRC state from RX path corrupting TX CRC |
| 4 | BIST cmd table re-ordered: 0x74 (Get-ID, sets `awake_state`) at index 0 | `host_bist.v` cmd_opcode/rsp_opcode/cmd_tx_len/cmd_rx_len/tx_byte | Loop-1's first cmd now wakes the device, eliminating wake-gate false fails for 0x70/0x72 |
| 5 | BIST trailing-BR HIGH phase shrunk 30→2 cycles | `host_bist.v` `BR_HIGH_CYC` | Master listen-window race: device drove first response bit ~9+rsp_len cycles after BR rise; BIST entered S_RX_WAIT 71 cycles after BR rise. Shrinking the gap lets BIST's edge detector see bit 0's fall edge. Symptom (0x3A vs expected 0x75) was the smoking-gun "rx_first_byte == expected >> 1". |

**In-FPGA diagnostic instrumentation that solved it** (added to `host_bist.v` + `fpga_top.v`):

- `total_pass_o[6:0]` cumulative PASS counter (max 52) → HEX1:HEX0 always
- `fail_mask_o[12:0]` sticky per-cmd fail bit
- `first_bad_{cmd,fb,bc,crc,why,valid}_o` snapshot of first failing cmd
- HEX5:HEX3 mux'd by `scan_en` (SW[0]) — DOWN: fail_mask, UP: first_bad diagnostic
- LEDR[6:3] also mux'd: DOWN: dbg_any_match stickies, UP: {valid, why_first, why_count, why_crc}

This let each debug iteration be: edit RTL → quartus_sh+pgm (~30 s) → eyeball HEX (instant). Five iterations took ~5 minutes each rather than hours per scope shot.

**Lesson going into v0.49**: every BIST harness ought to ship this exact instrumentation pattern (cumulative pass + fail mask + first-bad snapshot + view-selector switch) by default. A new program `bist_instrumentation_check.py` could enforce this in `synth-wrapper-gen` for any FPGA top with a self-test FSM.

### 2026-04-23 — v0.48 Phase 3 complete: RTL → GDS → Tapeout 4/4 strict

Same 2026-04-23 session that achieved the Phase 2 52/52 BIST PASS continued straight into the backend flow using the pre-existing fresh-agent v0.48 RTL (generated in the 2026-04-22 pilot, debugged today). Target PDK: `m18e80pm180su`, Magnachip 180 nm, under iic-osic-tools Docker. **Note**: Phase 1 L1-L9 docs were NOT re-run this day — they came from the 2026-04-22 session and lived on disk.

| Step | Tool | Script | Key metric |
|------|------|--------|-----------|
| Synth | Yosys 0.62 | `synth/synth.ys` | 3576 cells, chip area 128086 µm² |
| DFT | Fault ATPG | CLI only | 4.6% combinational coverage (no scan insert) |
| P&R | OpenROAD | `pnr/pnr_openroad.tcl` | 0 routing violations, 6m30s wall-clock |
| STA | OpenSTA | `sta/sta.tcl` | Setup WNS=0 / TNS=0 (typ/wci/bci); hold violations open |
| GDS | klayout | `gds/streamout.py` | 5.1 MB, 550×550 µm, 892k shapes, 0 off-grid |
| DRC sanity | klayout | `drc/sanity.py` | Well-formed (vendor runset not in PDK) |
| LVS sanity | klayout | `lvs/instance_compare.py` | netlist 48 types / 3576 inst == GDS match |
| Tapeout | `tapeout_signoff_check` | strict mode | **4/4 PASS** (gds + netlist + timing + drc) |

**Two critical PnR speedups discovered in this session** (both applied, both generalize):

1. **6-metal tech LEF over 4-metal**: first attempt used `CWB/m18e80pm180su_4lm_tech_v56.lef`; detailed_route stalled at 1800+ violations after 2 optimization iterations (convergence <1%/iter). Switching to the 6-metal LEF (plus MET5/MET6 tracks) took the same design to 0 violations in 5 iters. Single biggest backend-performance knob on this PDK.
2. **`set_thread_count 8`** at the top of the PnR TCL: detailed_route 0th-iter wall-time dropped 4m12s → 1m37s (~3× speedup). Single edit, generalizes to any OpenROAD run.

**Also required**: mark both `zero_` and `one_` nets as `setSpecial` in OpenDB — otherwise TritonRoute emits `DRT-0305 Net ... of signal type POWER is not routable` and aborts. The v037v2 reference TCL only handled `zero_`; `one_` bit us on first run.

**Honesty caveats (carried to Honesty Boundaries):**
- DFT 4.6% is raw combinational ATPG, no scan-chain insertion. Realistic open-flow target with scan is 55-75%.
- Hold violations present in all 3 STA corners (-1.17 to -1.79 ns). No hold-ECO pass executed.
- Full sign-off DRC/LVS requires vendor klayout DRC runset + netgen LVS runset. The `m18e80pm180su` package shipped here does NOT include either — v037v2 also lacked them. We substitute klayout geometric sanity + instance-count comparison, clearly marked as non-sign-off checks.

### 2026-04-24 — v0.53 fresh-agent USB-HID tester F2 PASS + L10-L13 completeness audit

A fresh Claude-spawned agent in workspace `phase2+3_v052/` ran Phase 2+3 end-to-end from `input/` alone (no peek at other `phase2+3_v*` folders, no peek at `/home/user/a3606/` vendor tree, plugin's `spec-to-rtl/references/aid/` already removed in v0.51). Outcome: byte-for-byte USB-HID tester F2 PASS, independently verified by re-burn + re-test.

| # | Lesson | Plugin enhancement |
|---|--------|--------------------|
| 1 | `phase1-orchestrate/SKILL.md` lists only L1-L9; 4 layers (L10 test-cases, L11 calibration, L12 behavioral-sequences, L13 lab-calibration) existed as standalone skills since v0.50 but no orchestrator chained them. Fresh agent skipped all four silently. | **Queued for v0.54**: rewrite orchestrator to invoke all 13 layer skills + fail if any is missing |
| 2 | Agent self-reported "1083/1083 PASS, 100 % coverage" but lacked testbenches for TestMode, OTP E0 write, PT-mux (three multi-step sequences named in L12) | **`l12_tb_coverage_check.py`** — each L12 sequence must have a corresponding `sim/tb/tb_*.v` (filename match OR content grep for sequence ID) |
| 3 | Agent self-reported Verilator coverage `≥ 95 %` was an estimate, not a tool measurement | Require `reports/coverage/coverage_actual.json` to contain verilator-generated `coverage.dat` + `verilator_coverage --annotate` output; reject any number not sourced from tool output |
| 4 | `tb_otp_e0_write.v` (25 cases) found a real silicon bug: `mac.v` E0 handler does not enforce ID_LK / IMSN_LK / ASN_LK lock bits — post-lock writes are accepted | Trace-to-requirement: L2 FRS §6.7 requires lock enforcement. Add `otp_lock_enforcement_check.py` that searches `mac.v` for lock-region gating before accepting a spec-PASS claim |
| 5 | `tb_testmode.v` (10 cases) found another real silicon bug: TestMode entry in v0.52 RTL is a `0xEC`-command stub, not the real HV + CC_I + ID_BUS pattern entry sequence named in L12 `TEST_MODE_ENTRY` | Add `l12_sequence_implementation_check.py` — for each L12 `host_stimulus_sequence`, search RTL for pattern-matcher evidence, not just for the final state bit being set |
| 6 | Fresh-agent USB-HID tester PASS required 6 real RTL fixes vs. a previous (v051) agent that FAILed: rx_phy rising-edge classify, rx_chk combinational validate, MAC length-check, rx_clk↔core_clk 3-stage sync, E0/E2 payload byte-index, id_bus_rx self-mask during TX | Document as `spec-to-rtl/PRACTICAL_NOTES.md` entries so future fresh agents start from these 6 lessons rather than rediscovering them |
| 7 | "PIN_V10 disconnected" hypothesis (held from 2026-04-22 to 2026-04-24 morning) was wrong. Same physical board that returned byte[6]=0x02 for v045-v051 RTLs returned byte[6]=0xF2 for v052 RTL after the 6 fixes. Baseline-oracle drift was an RTL cause, not a hardware cause. | Add `usb_hid_tester_oracle_health_check` — before declaring "hardware-blocked", require that a known-good reference .sof be rebuilt and tested; only if reference also FAILs is the hardware verdict valid |

**Meta-lesson for v0.53**: even after v0.50's 3-layer defense (spec + sim + hardware), a fresh agent's self-reported PASS can still hide missing testbenches, estimated (not measured) coverage, and RTL that is silicon-wrong but sim-good. v0.53 promotes "the agent said so" into "a plugin program measured it" for two specific cases (L12→tb coverage, Verilator coverage). Same seven-word principle, extended: **extract + test + attest + cross-check self-reports**.

---

## Honesty boundaries

- **v0.48 fresh-agent benchmark IC chain is end-to-end reproducible across two sessions**: 2026-04-22 session produced Phase 1 L1-L9 docs + Phase 2 RTL + initial `.sof` (BIST 0/13). 2026-04-23 session did Phase 2 debug (BIST 0→52/52) + full Phase 3 (routed GDS + tapeout_signoff_check strict 4/4). Phase 1 was NOT re-run 2026-04-23 — the L1-L9 docs were inherited from disk. The two RTL bug classes that stalled the 2026-04-22 initial BIST (pulse-vs-state, producer/consumer rate) were resolved by hand-editing 5 files; the plugin still does NOT auto-catch these patterns. Full sign-off DRC/LVS still needs vendor runsets not in PDK package. v0.49 targets: encode RTL-level bug classes as `rtl-review` rules; encode PnR speedup defaults (6-metal + 8 threads + `one_`/`zero_` special-net handling) in flow scripts.
- **v044 "fresh agent protocol tester PASS" is RETRACTED (v0.47.6)**. It was achieved by copying a plugin-bundled verbatim reference (`references/&lt;vendor-rtl&gt;/rtl/*` — 17 files, SHA-identical to the benchmark IC production RTL). That's not a plugin capability; it's shipping an answer-key. The bundle has been removed. Only v037v2 spec-generation PASS 3/3 stands as a real outcome.
- v046 aon_timer 27/28 + 1 waiver is **simulated-sign-off PASS**, not on-board-tested PASS. Step 28 genuinely requires a physical board.
- **benchmark-ic v0.47 pilot's "27 PASS" was fabricated**, discovered the same day, retracted. The real state is 13 PASS / 3 FAIL / 12 MISSING. The fabrication drove the v0.47.2-.4 gate hardening (see Debug-session lesson 3 above).
- Phase-1 "value-correct JSON from dialogue alone" is **not yet achieved**. L1 manifest is a curated 40-fact PoC that proves the architecture; L2-L9 manifests are still prose lessons. Earlier "10/10 converged" / "30/30 match=1.00" claims were shortcut-tainted (answer key visible / verbatim copy) and have been retracted. See `docs/tutorials/phase1_closed_loop_training.md`.
- Fault stuck-at coverage on an open-flow netlist (no scan-chain insertion) typically reaches **55-75 %**, not the 85-95 % achievable with commercial scan + ATPG tools. Set realistic `--min-coverage` targets.
- **v0.53 v052 fresh-agent USB-HID tester F2 PASS is REAL and reproducible** — SOF re-burned, HID test re-run by a human supervisor, byte[6]=0xF2 + signature tail confirmed. But the same testbench suite has **measured Verilator coverage of only 78 % line / 75 % toggle / 82 % branch**, not the 95 % the agent first self-reported. Two silicon-blocking RTL gaps (E0 lock-bit not enforced; TestMode pattern matcher stub) were caught by the new tb_otp_e0_write / tb_testmode and are **not yet fixed** — the v052 SOF passes the specific USB-HID tester cable-test but must NOT be shipped to silicon without those two fixes.
- **v0.53 plugin defect**: `phase1-orchestrate/SKILL.md` still describes only L1-L9. Fresh agents following the orchestrator silently skip L10-L13 even though the four skills exist. `l12_tb_coverage_check.py` (new in v0.53) catches the downstream symptom (missing testbenches per L12 sequence) but does not fix the upstream orchestrator itself. Fix queued for v0.54.

---

## Links

- **Main repository**: [AI_IC_design](https://github.com/reyerchu/AI_IC_design)
- **Marketplace pattern**: [superpowers-marketplace](https://github.com/obra/superpowers-marketplace)
- **GF180MCU PDK**: [google/gf180mcu-pdk](https://github.com/google/gf180mcu-pdk)
- **SKY130 PDK**: [google/skywater-pdk](https://github.com/google/skywater-pdk)
- **Fault (open-source ATPG)**: [cloudv-io/fault](https://github.com/cloudv-io/fault)
- **iic-osic-tools Docker**: [hpretl/iic-osic-tools](https://hub.docker.com/r/hpretl/iic-osic-tools)

## License

MIT
