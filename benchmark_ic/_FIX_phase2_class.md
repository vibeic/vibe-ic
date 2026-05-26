# FIX — Phase-2 class-aware verification gating (v1.6.523)

## Problem
Phase-2 verification was hardwired to a half-duplex AID-protocol peripheral
(3-port `clk`/`reset_n`/`id_bus` reference TB + DE10 board-pin + `<half-duplex-tester>`
connect_test + protocol/analog gates). Generic digital IP — CPUs, SoCs,
crypto/arithmetic primitives, bit-serial cores — could NEVER pass even with
clean synth + passing sim, because the AID TB cannot bind a memory-bus/data
top and the protocol/analog gates have no applicable spec layer. This was the
biggest systematic gap across the 21-IC benchmark.

## Approach (chip-AGNOSTIC, honesty-preserving)
Make inapplicable gates **SKIP with an explicit reason**; never auto-pass.
A genuine functional failure (sim mismatch, real compile/synth error, real
structural defect, multi-bit NBA race) still **FAILs**. Every new escape path
is **fail-closed**: unknown/unregistered classes keep the full legacy AID FAIL
logic engaged.

## Fixes (files owned)
1. **ic_class_registry.json** — added `verification_track`
   (`aid_protocol` | `generic_full_stack`) + `command_protocol_applicable` /
   `analog_applicable` / `half_duplex_bus` flags to every class. Set
   `generic_full_stack` for `digital_arithmetic_primitive`, `pure_analog`,
   `bare_fpga`; added a new **`processor_cpu`** class (synonyms cpu/processor/
   soc/riscv_core/...) with all three protocol/analog/half-duplex flags false.
   Existing protocol classes stay `aid_protocol`. Added profile-emitted names
   as synonyms (`aid_class_half_duplex_single_wire`, `unknown`) so the accessor
   resolves the runner's class strings.
2. **ic_class_profile.py** — new `class_verification_flags(ic_class)` and
   `is_aid_protocol_track(ic_class)` accessors reading the registry; fail-closed
   default = `aid_protocol`, all flags applicable.
3. **phase2_one_shot_runner.py** — `step_reference_tb` now takes `ic_class`;
   for non-AID-track classes it SKIPs the hardcoded AID TB and runs the generic
   full-stack TB (`step_full_stack_tb_gen` output under `sim_full_stack/`) as
   the functional gate. PASS if it compiles+runs (`FULL_STACK_TB_DONE`); **FAIL
   if the DUT genuinely fails to compile/elaborate** (honesty); SKIP/WAIVE with
   "interface family not covered by AID reference TB; gate-level synth + Phase 3
   is the verification path" if no generic TB can be built. Same predicate
   applied to `step_qsf_gen` and `step_usb_hid_tester_verify`: memory-bus core
   with no `*de10*` board-harness top → SKIP (not FAIL).
4. **analog_content_detected_must_emit_l5_check.py** — per-keyword negation
   awareness (`_keyword_is_negated`): a keyword only inside a negation
   ("does not need an LDO", "no bandgap", "without analog oscillator", "❌ LDO",
   "~~bandgap~~") no longer counts; positive mentions and mixed lines
   ("no LDO but a real bandgap") work per-hit.
5. **nba_shift_register_same_cycle_read_check.py** — bit-serial-family
   suppression (`_bit_serial_evidence`): W==1 datapath / `bit_serial` ic_class
   marker (L docs/facts/catalog) / evidence waiver
   `bit_serial_core_lookahead_intentional` downgrades FAIL→WARN. **Multi-bit
   same-cycle NBA race on a non-bit-serial design still FAILs.**

`flow_compliance_check.py` — added `_class_skipped_gates()` +
`_CLASS_SKIPPABLE_{PROTOCOL,ANALOG}_GATES`; wired into
`_run_structural_rtl_gates`. When the class marks command_protocol/analog
not-applicable, the four protocol gates (opcode-arg, typed-electrical,
behavioral-step, protocol-sim) and four analog gates (block-coverage,
hardmacro, mixed-signal, analog-content-must-emit) SKIP with "N/A for class X".
Core gates (lint/synth/CDC/sim correctness, CRC, FSM, bitwidth) never skip.

## Verification
- `ast.parse` passes on all 5 edited `.py`; `ic_class_registry.json` valid JSON.
- New tests: `programs/tests/test_phase2_class_aware_gating.py` — **30 tests, all pass**.
  Covers: generic class SKIPs AID TB + protocol/analog gates with reasons but
  still runs functional gates; real DUT compile failure still FAILs; negated
  analog keyword → no analog content (positive still counts); W==1/bit-serial →
  WARN; multi-bit race → still FAIL; fail-closed for unknown class.
- Full suite: baseline **1304 passed / 4 skipped / 1 xfailed / 4 xpassed / 0 failed**;
  after: **1334 passed / 4 skipped / 1 xfailed / 4 xpassed / 0 failed** (+30 new,
  no new failures).
- Confirmed (not edited): `l9_submodule_conformance_check.py` carries the
  submodule-instantiation regex accepting `mod #(.P(P)) inst (...)`
  (`_INSTANTIATION_TEMPLATE`, optional `#(...)` before instance name with one
  nested-paren level); `ip_catalog_pull.py` emits provenance `outputs` dict
  (path → `sha256:<hex>`) plus the `outputs_sha256` alias.
