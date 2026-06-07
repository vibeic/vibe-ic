#!/usr/bin/env python3
"""
flow_compliance_check.py — Strict Vibe-IC phase 2+3 gate (40 main-track
steps + A1-A9 analog + M1-M4 mixed-signal + P0 structural-RTL umbrella
in v1.6.15).

⛔ THIS IS THE SOLE PHASE 2+3 ACCEPTANCE CRITERION.

Any agent claiming "Phase 2+3 complete", "design flow done", "tape-out
ready", "ready for fab", or any equivalent — MUST run this with
`--strict` and produce `Overall: PASS` with every required step PASS
before the claim is valid. Individual gates passing (tapeout_signoff_check,
usb_hid_tester_connect_test, BACKLOG-v6/v7 P0 set, lvs_yosys_equiv, etc.) are
NECESSARY BUT NOT SUFFICIENT. v0.108 fresh-agent benchmark proved that
a project can pass every individual structural gate while only
completing 2/34 canonical steps because steps 15-33 (PnR canonical
artefacts, SPEF, post-route STA, IR/EM/antenna/SI, post-layout sim,
SPICE correlation, ECO, power, metal fill, tapeout checklist) and
step 36 (FPGA final sign-off, was step 35 pre-Wave-91) were never
verified. (Wave 91 / v1.6.15: stage3-5 cascade +1; pre-PnR Yosys gate
is now Step 14; structural-RTL umbrella is `P0`.)

Companion wrapper: phase23_completion_self_audit_check.py — emits a
single PASS/FAIL plus a clean N/<total> metric for embedding in
FINAL_REPORT.md.

Reads `vibe-ic/flow/phase1_phase2_phase3.yaml` (or the --flow-def override),
walks the project directory, and verifies every step has:
  (a) all required_outputs present (file globs), AND
  (b) its gate predicate passes.

Unlike the legacy `signoff_audit.py` which passes at 3-of-4 evidence, this
program requires **every** step to pass unless a matching entry exists in
`<project>/waivers.json`. A waived step is reported as SKIPPED-WAIVED but
does NOT block the compliance result.

Without the --lenient flag, the exit code is:
  0 = all non-waived steps PASS
  1 = one or more steps FAIL or MISSING
  2 = flow definition or I/O error

With --lenient, MISSING steps (required_outputs not found) degrade to WARN
but gate predicate failures still FAIL. Intended for in-progress drafts only.

Usage:
    python3 flow_compliance_check.py <project_dir>
    python3 flow_compliance_check.py <project_dir> --json report.json
    python3 flow_compliance_check.py <project_dir> --flow phase1_phase2_phase3 --strict

Waivers (<project>/waivers.json):
    {
      "waived_steps": [
        {"id": 39, "reason": "No FPGA board this session", "approver": "user"}
      ]
    }
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional
import _path_layout as _pl

try:
    import yaml
except ImportError:
    print("flow_compliance_check: PyYAML required (pip install pyyaml)", file=sys.stderr)
    sys.exit(2)


def _find_flow_def() -> Path:
    """Locate flow/phase1_phase2_phase3.yaml across install layouts.

    v1.0.0+ unified plugin layout:
       file = <plugin_root>/programs/<this>
       flow = <plugin_root>/flow/phase1_phase2_phase3.yaml

    Pre-v1.0 split layout (deprecated): vibe-ic / vibe-ic-d split.
    """
    here = Path(__file__).resolve()
    # v1.0.0+ unified: programs/.parent = plugin root, flow/ is sibling.
    for ancestor in (here.parent.parent,
                     here.parent.parent.parent,
                     here.parent.parent.parent.parent):
        if ancestor.is_dir():
            direct = ancestor / "flow" / "phase1_phase2_phase3.yaml"
            if direct.is_file():
                return direct
    # Pre-v1.0 split layout fallback (legacy)
    for ancestor in (here.parent, here.parent.parent, here.parent.parent.parent,
                     here.parent.parent.parent.parent):
        if not ancestor.is_dir():
            continue
        for sib in ("vibe-ic", "vibe-ic"):
            sibling = ancestor / sib
            if not sibling.is_dir():
                continue
            direct = sibling / "flow" / "phase1_phase2_phase3.yaml"
            if direct.is_file():
                return direct
            # Versioned cache layout
            best: Optional[Path] = None
            for sub in sorted(sibling.iterdir()):
                f = sub / "flow" / "phase1_phase2_phase3.yaml"
                if f.is_file():
                    best = f
            if best:
                return best
    return here.parent.parent / "flow" / "phase1_phase2_phase3.yaml"


DEFAULT_FLOW_DEF = _find_flow_def()

PROGRAMS_DIR = Path(__file__).parent

# v1.6.99 (issue #31 Bug 2) — informational-only gates. Gates listed
# here are still EXECUTED and their per-step result is REPORTED in the
# normal listing (so the agent sees the status), but they are
# EXCLUDED from FAIL-counting toward the Phase 2 verdict. Rationale:
# bit_level_full_stack_tb_check is a TB skeleton check that needs
# real scenarios to pass; until those land it is a coverage gap, not
# a deployment blocker. Real gate fails (self_rx_mask_check, etc.)
# still drive FAIL — informational suppression is keyed on gate name,
# never on step id, so it remains chip-AGNOSTIC.
INFORMATIONAL_GATES: frozenset[str] = frozenset({
    "bit_level_full_stack_tb_check",
    # v0.1.89 — periodic_timer_vs_rx_activity_check emits WARN-severity
    # findings only (`[WARN] periodic_timer_no_rx_reset`); it's a heuristic
    # ("is this counter a protocol rx-timer that should reset on activity?")
    # that false-positives on legitimate free-running counters — e.g. a reused
    # CPU core's program-counter / cycle-timer (SERV `o_cnt`). A WARN heuristic
    # is a coverage signal, not a deployment blocker, so (like
    # bit_level_full_stack_tb_check) it is reported per-step but EXCLUDED from
    # the strict-structural FAIL count. Keyed on gate name; chip-AGNOSTIC.
    "periodic_timer_vs_rx_activity_check",
})


def _step_failure_is_informational_only(result: "StepResult") -> bool:
    """Return True iff every FAIL reason in `result` cites a gate in
    INFORMATIONAL_GATES (and at least one such reason exists). Used by
    the verdict pass to exclude informational-only step failures from
    `failing`. Reasons emitted by `_evaluate_gate` for failing
    program_exit_zero sub-gates start with `program failed: <cmd>`;
    we substring-scan for any informational gate name."""
    if result.status != "FAIL" or not result.reasons:
        return False
    saw_informational = False
    for reason in result.reasons:
        # Skip output: lines and other diagnostic context lines —
        # only "program failed: ..." carries the gate-name signal.
        if not reason.startswith("program failed:"):
            continue
        matched = False
        for gate_name in INFORMATIONAL_GATES:
            if gate_name in reason:
                matched = True
                saw_informational = True
                break
        if not matched:
            # A real gate failure is in the mix → not informational-only.
            return False
    return saw_informational


# v0.104: structural-RTL gates that MUST run before eda_lint.
# These existed since v0.63-v0.103 but were never wired into the
# mandatory flow — the v0.103 fresh-agent run proved two of them
# (self_rx_mask_check, timer_freeze_after_state_check) would have
# caught high-impact bugs if invoked.  Conditional: each gate only
# fires when RTL files are present; exit-2 (input-missing) = skip.
_STRUCTURAL_RTL_GATES: tuple[str, ...] = (
    "self_rx_mask_check",
    "tristate_self_rx_mask_check",
    "timer_freeze_after_state_check",
    "pulse_decoder_edge_check",
    "packet_length_check_present",
    "otp_write_lock_gate_check",
    "l12_sequence_implementation_check",
    "nba_addr_read_race_check",
    "sustained_vs_edge_check",
    "transient_signal_latch_check",
    "periodic_timer_vs_rx_activity_check",
    "memory_read_pipeline_check",
    "crc_engine_isolation_check",
    "bit_count_modulo_check",
    "cmd_arg_range_validation_check",
    "response_payload_template_check",
    "pre_awake_silence_check",
    "dispatch_register_default_reset_check",
    "host_soft_reset_unwake_path_check",
    "dispatch_fetch_loop_population_check",
    "dispatcher_tx_arm_order_check",
    "rig_topology_disclosure_check",
    "fpga_wrapper_input_polluter_check",
    "oe_pattern_check",
    "crc_bitorder_check",
    "interface_encoding_audit",
    "phy_counter_audit",
    "mask_application_check",
    "protocol_delimiter_consistency_check",
    "crc_seed_consistency_check",
    "crc_completeness_check",
    "crc_residual_check",
    "handshake_check",
    "gap_reset_granularity_check",
    "protocol_gap_check",
    "trailing_delimiter_completeness_check",
    "device_response_no_br_check",
    "warn_acceptance_policy_check",
    "tristate_bus_check",
    "fsm_error_invariant",
    "bitwidth_consistency_check",
    "periodic_signal_required_check",
    "fpga_async_input_synchronizer_check",
    "bus_turnaround_consumes_spec_constant_check",
    "dead_timing_constant_warn",
    "l9_response_delay_schema_check",
    # v0.106 BACKLOG-v7: byte-stream + latency + active-drive + OTP axes
    "fetch_round_trip_sentinel_check",
    "rtl_response_byte_oracle_check",
    "scope_response_byte_decode_check",
    "tristate_active_drive_check",
    "otp_image_layer_consistency_check",
    # v0.107: post-layout SPICE verification gate
    "spice_correlation_check",
    # v0.108: analog design pipeline gates
    "analog_block_coverage_check",
    "analog_corner_sweep_check",
    "analog_netlist_pdk_check",
    "analog_hw_spice_correlation_check",
    "analog_hardmacro_check",
    "mixed_signal_cosim_check",
    "analog_pre_vs_post_layout_check",
    "analog_flow_compliance_check",
    "analog_digital_interface_check",
    # v1.6.35: per-block A1-A9 deterministic artefact-presence +
    # substance gates. Closes the v10632/v10634 escape where the
    # runner declared every A1-A9 step WAIVED for every block (no
    # gate shipped). Each gate is chip-AGNOSTIC, VACUOUS_PASSes when
    # `analog/analog_block_list.json` is missing or empty (digital-
    # only project), and FAILs only when the artefact is present
    # but a stub. Discovers blocks via the block-list file, runs on
    # the project root, and accepts `--block <name>` for per-block
    # invocation by analog_one_shot_runner.
    "analog_a1_spec_extract_check",
    "analog_a2_topology_select_check",
    "analog_a3_netlist_gen_check",
    "analog_a4_corner_sweep_check",
    "analog_a5_layout_check",
    "analog_a6_block_pv_check",
    "analog_a7_post_layout_resim_check",
    "analog_a8_hardmacro_gen_check",
    "analog_a9_hw_verify_check",
    # v0.108: half-duplex protocol RTL invariant gates
    "break_framing_vs_l3_check",
    "break_handler_safety_check",
    "tx_abort_during_transmission_check",
    # v0.117 / BACKLOG-v11 P0.1: protocol-FSM topology gate. Closes the
    # entire modular-protocol-FSM 1-cycle handshake race class observed in
    # v0.116 <benchmark> benchmark. Warning-class — silent for L9 fsm_topology
    # override and for non-protocol designs.
    "protocol_fsm_topology_check",
    # v0.117 / BACKLOG-v11 P0.2-P0.6: structural lint gates against the
    # specific bug patterns observed in v0.116 <benchmark> (clock divider
    # period mismatch, cross-module 1-cycle pulse race, frame-end
    # detection by duplicate start pulse, CRC literal mismatch, fixed-
    # priority arbiter starvation). Each gate is chip-agnostic and
    # silent on clean reference RTL (v099 oracle baseline verified).
    "clock_divider_period_check",
    "cross_module_1cycle_handshake_check",
    "frame_end_detection_check",
    "crc_oracle_vector_check",
    "arbiter_starvation_check",
    # v0.118 / BACKLOG-v11 P1.1: tristate inout port without weak
    # pull-up assignment (Quartus QSF / Vivado XDC) AND no L11
    # external_pullup declaration. Catches the v0.116 <benchmark> floating-
    # bus glitch class. Silent for ASIC targets, silent for non-tristate
    # inouts, silent if QSF/XDC declares a pull-up.
    "tristate_pullup_assertion_check",
    # v0.118 / BACKLOG-v11 P2.1: workflow gate at Step 5→6 boundary.
    # Protocol-IP designs must run a full-stack cocotb / Verilator TB
    # with PASS verdict + sim mtime > all RTL mtime + non-trivial
    # transcript before FPGA-step verification counts. Silent for
    # non-protocol designs and for projects pre-Step-6.
    "protocol_ip_simulation_required_check",
    # v0.118 / BACKLOG-v11 P1.2: $readmemh / $readmemb on FPGA family
    # silently breaks if not supported (Intel MAX10 needs ERAM mode;
    # Xilinx needs xpm_memory_*). Caught the v0.116 <benchmark> OTP-init
    # silent failure (BRAM became LUT-array-of-X). Silent for ASIC,
    # silent for known-OK families, silent for megafunction-with-init.
    "bram_init_portable_compat_check",
    # v0.118 / BACKLOG-v11 P1.3: WARNING-class — BRAM wrapper
    # registers data_out + consumer FSM non-blocking-captures it →
    # off-by-one stale read. Conservative cross-module data-flow
    # heuristic; silent for combinational outputs, blocking captures,
    # L6-declared wait states, and BRAM_OUTPUT_REGISTER_ACKNOWLEDGED
    # marker.
    "bram_pdob_combinational_check",
    # v0.118 / BACKLOG-v10 P0.1 enforcement: KLayout DRC ran in
    # structural-only fallback mode (no real geometric rules) →
    # require explicit waiver K01_klayout_structural_only_drc.
    # Closes the silent "structural pass = real DRC" gap from v0.112.
    "klayout_deck_mode_check",
    # v0.118 / BACKLOG-v10 P1.3: waivers older than 90 days WARN,
    # older than 180 days ERROR. Forces stale waivers to be closed
    # or re-justified.
    "waiver_staleness_check",
    # v0.118 / BACKLOG-v10 P2.3: per-step provenance hash audit.
    # Program shipped in v0.114 but was never wired into the audit
    # runner. Verifies PASS-verdict gate reports' output_files exist
    # on disk and their recorded sha256 matches the current file.
    # Catches the "stub-flag PASS" anti-pattern. WARN on missing
    # output_files (legacy projects); ERROR on definitively-stale
    # provenance (hash mismatch + file older than gate run). Silent
    # if no gate_reports/ directory.
    "provenance_hash_audit",
    # v0.119 LL-2/3/4/5/6: half-duplex protocol response-window family.
    # Closes the v0118-vendor <benchmark> FRAME_END_GAP=80us bug class. All
    # five gates derive constraints from the project's own L1-L13 specs
    # (no oracle dependency). Silent for non-half-duplex projects.
    #   LL-2 catches missing frame_end_gap field in L8.
    #   LL-3 catches frame_end_gap in L8 outside [ibt_max+margin,
    #        2*ibt_max] range.
    #   LL-4 catches RTL where total response latency exceeds
    #        ibt_max + 3*tSRS_min budget.
    #   LL-5 (WARNING) requires top module to expose dbg_*_latency
    #        observable for HW debugging without recompile.
    #   LL-6 (WARNING) requires TB to drive both extremes of every
    #        L2 timing range.
    "frame_end_gap_in_l8_check",
    "l8_frame_end_gap_derivation_check",
    "half_duplex_response_window_check",
    "response_latency_observability_check",
    "tb_timing_extremes_check",
    # v0.119.3 LL-10/11: closes the v0119_fresh_v2 <benchmark> bug classes —
    # fresh agent named FPGA top ports differently from QSF (silent
    # unconstrained pin → chip clock not connected → <half-duplex-tester> silent),
    # and declared TWK_PULSE/TITO_TICKS constants but never wrote the
    # wake-pulse FSM. Both gates derive constraints from L1-L13 + QSF
    # alone, no oracle.
    "fpga_port_qsf_consistency_check",
    "wake_pulse_implementation_check",
    # v0.119.4 LL-14: closes the v0119_fresh_v3 <benchmark> bug class found via
    # BFM-driven closed-loop sim. Fresh agent built a frame-end idle counter
    # that resets on rx_byte_vld/rx_br/tx_active and increments under
    # id_bus_rx==1, but FORGOT to reset it when id_bus_rx==0. After IBT
    # (~21us) plus next-byte first-bit HIGH (~8us), cumulative HIGH crossed
    # FRAME_END_GAP (27us) mid-frame, chip declared EOF early, responded
    # while master still TXing. Bus contention + silent functional fail
    # invisible to lint, formal, and 7/7 prior structural gates. Caught only
    # by usb_hid_tester_bfm_gen sim — now hard-gated structurally.
    "half_duplex_frame_end_idle_reset_check",
    # v0.119.6 LL-15: closes the v3 byte[6]=0x02 silent HW failure where
    # BFM-validated chip RTL fails <half-duplex-tester> acceptance because the agent
    # confused IBT (chip TX inter-byte HIGH gap) with the host BR LOW
    # threshold and picked IBT≈8us. Real silicon needs IBT ≥ ~half of
    # tSRS_min so the master can re-arm its bit receiver between bytes.
    # Caught by oracle bisect (v0118 IBT=22.7us PASS vs v3 IBT=8.5us FAIL).
    "tx_timing_use_max_of_range_check",
    # v0.119.7 LL-16: closes the v3 vs v0118-oracle root cause discovered
    # by direct RTL bisect. Fresh agent split the bus driver into two
    # parallel sources (tx_phy.tx_oe | wake_fsm.wake_drv), which:
    #   1. desyncs tx_active (only reflects tx_phy state, not wake) →
    #      rx_phy self-RX mask leaks during wake pulse;
    #   2. routes wake through different LE delay vs other TX ops, the
    #      master sees sub-microsecond edge-shape mismatch invisible to
    #      scope_capture at 100ns sample resolution;
    #   3. silent failure: BFM 12/12 PASS, <half-duplex-tester> connect_test
    #      byte[6]=0x02 FAIL, scope identical to known-PASS oracle.
    # The fix is structural: every bus drive op (BR/BIT/IBT/WAKE/END_BR)
    # must route through a single tx_phy. This is how the v0118 oracle
    # SOF that PASSes does it.
    "single_bus_driver_check",
    # v0.119.8 LL-17: closes the v3 vs v0118-oracle real root cause found
    # by controlled wrapper-flip experiment. v0118 RTL + v0118 wrapper
    # PASSes <half-duplex-tester> byte[6]=0xF2; same v0118 RTL + v3-style wrapper FAILs
    # with byte[6]=0x02 — only the wrapper assign expression differs.
    # Quartus / Vivado / Lattice synth tools infer OPEN_DRAIN_OUTPUT pad
    # from `(oe && !tx) ? 1'b0 : 1'bz` (split data/oe form) but a regular
    # tristate from `oe ? 1'b0 : 1'bz` (single signal). Both produce
    # identical wave on a scope at 100 ns/sample but the host's analog
    # front-end detects pad-startup / edge / bus-hold differences.
    "half_duplex_wrapper_open_drain_check",
    # v0.119.9 LL-18: closes Category-A spec-extraction gap. cmd-protocol-gen
    # historically left fields_tx in symbolic form (VID, PID, ID[0..5],
    # SN[0..5]) and downstream skills didn't resolve them to concrete OTP
    # byte addresses. Fresh agent then guesses → reads wrong addresses →
    # BFM passes canned data → host connect_test FAILs on real silicon.
    # v0118 STATUS lists 4 fixes (#5/#6/#7/#14) that were exactly this
    # extraction gap. The gate forces L3 fields_tx to be byte-exact:
    # literal bytes, OTP-addr resolved, register-backed, or CRC marker.
    "cmd_protocol_byte_exact_check",
    # v0.119.10 LL-19/LL-20: companion checks on the OTP and timing
    # extraction sides. LL-18 enforces L3 fields_tx are byte-exact;
    # LL-19 makes sure the symbolic names L3 still uses (VID, SN, etc.)
    # have a concrete byte-address resolution in L11_OTP_CONTENT.
    # LL-20 makes sure L2 timing fields are in [min,max] form so
    # LL-2/3/4/15 can read them. Together LL-18/19/20 close
    # Category-A spec-extraction gap to ~90%.
    "otp_field_map_check",
    "frs_timing_range_check",
    # v0.119.11 LL-21/22/23: close A residual + B workflow + C pad fan-out.
    "regmap_bit_layout_check",       # A residual: bit positions must be explicit
    "oracle_dump_required_check",    # B workflow: oracle_referenced_fix needs artifact
    "fpga_pad_fanout_check",         # C structural: bus-pin pad fan-out ≤ 1
    # v0.119.12 LL-24: hw-debug-loop convergence audit. The skill drives
    # a 7-step bounded debug loop (scope → bisect → fix → re-burn →
    # re-test). This gate enforces Step 7: when the project enters the
    # loop (evidence/ directory present), it must converge to a recorded
    # PASS verdict and every oracle-referenced fix must cite a captured
    # artifact. Closes the methodology gap "we couldn't ship 1st-time
    # PASS, but here is the deterministic loop we ran to get there".
    "hw_acceptance_test_passed_check",
    # v0.119.13 LL-25: THE root cause for v3 <benchmark>. fresh-agent fpga_top
    # declared only 3 pins (GPIO_id_bus / KEY_rstn / LED) but L2 names
    # 8 hardware pins (WAKE, CC_I, CC_O, CC_EN, RD_ENB, OUT1, OUT2,
    # ID_IO). <half-duplex-tester> rig physically routes CC_I + WAKE; without those
    # FPGA pins the rig cannot wake the chip and connect_test returns
    # byte[6]=0x02 deterministically. Compare v068 oracle SOF whose QSF
    # binds all 8. No amount of internal-RTL fix recovers a missing pin.
    "fpga_top_pin_completeness_check",
    # v0.119.21 LL-26: advisory gate for sub-microsecond Category-C residual
    # surfaced by the v0.119.20 vendor benchmark. Catches the case where a
    # chip's TX bit-clock period is too coarse to place edges within an
    # L2 timing tolerance window — e.g. 5 MHz clock (T_tx_ns=200) snaps
    # edges at 100 ns, eating 20% of a ±0.5us host budget. The gate
    # silent-skips when L2 has no tolerance windows OR the chip TX clock
    # period isn't declared (no false alerts), WARNs (still exits 0)
    # when between safety_factor and warn_factor, FAILs only when ratio
    # exceeds warn_factor (default 10×).
    "tx_bit_width_min_resolution_check",
    # v0.119.27 LL-28 was REMOVED in v0.119.29: the prescribed QSF form
    # `set_instance_assignment -name OPEN_DRAIN ON -to <pad>` causes
    # Quartus error 125048 (the assignment name does not exist on
    # MAX10 / Cyclone). The hypothesis that a missing QSF assignment
    # was the <half-duplex-tester> byte[6]=0x02 root cause was wrong: Quartus
    # auto-infers OPEN_DRAIN_OUTPUT from the RTL ternary pattern, no
    # extra QSF entry needed. The gate file is kept as a deprecated
    # silent-PASS stub for backward-compat with any caller that
    # invokes it directly. NOT registered here.
    # v0.119.23 LL-27: catches the FPGA toggle-divider clock antipattern
    # surfaced by the v0.119.22 vendor benchmark. Fresh agent emitted
    # `clk_5m <= ~clk_5m` (toggle divider) and used clk_5m as the chip's
    # core clock; Quartus warned but Phase 2 didn't catch. Effective core
    # clock turned out 2.5 MHz instead of 5 MHz → all chip TX bits 2× spec
    # → <half-duplex-tester> byte[6]=0x02 deterministic FAIL. The gate detects the
    # toggle-register / counter-bit derivation pattern, silent-skips for
    # ASIC projects (no .qsf/.xdc/.qpf), and PASSes when a matching
    # create_generated_clock SDC entry exists.
    "fpga_clock_divider_antipattern_check",
    # v0.119.29 ROOT_CAUSE_ANALYSIS — 5 gates closing the 7 deltas
    # surfaced by <benchmark> phase2_fresh_v011924_v2 (FAIL byte[6]=0x02)
    # vs ic-a_fpga_quartus_ok (PASS byte[6]=0xF2). All chip-agnostic.
    #   Area 1: tx bit-cell µs vs declared TX clock — wrong clock domain
    #           for TX_PHY makes per-bit LOW/HIGH ratio off even when the
    #           total bit period happens to match.
    "tx_bit_timing_units_check",
    #   Area 2: L9.clock_binding declares ≥2 clocks but top RTL ties
    #           every binding-listed submodule to a single wire — divider
    #           cascade collapsed.
    "clock_cascade_synthesis_check",
    #   Area 3: L3 example response bytes match an OTP slice but
    #           response_source is literal/unspecified — extractor read
    #           the example as the answer instead of as `stream OTP[..]`.
    "cmd_response_otp_provenance_check",
    #   Area 4: opcodes that take ≥2 inbound argument bytes lack an
    #           argument_validation_predicate field — chip responds to
    #           every host VID/PID without checking.
    "cmd_argument_validation_present_check",
    #   Area 5: L5 pad external_pullup field disagrees with QSF
    #           WEAK_PULL_UP_RESISTOR assignment — internal vs external
    #           pull-up source mismatch distorts edges on real silicon.
    "fpga_pad_pullup_consistency_check",
    # v0.119.32 LL-29..33 — closes the v0.119.30 <benchmark> vendor extractor
    # gaps documented in MIN_DIFF_ANALYSIS.md. All 7 deltas are
    # Category-A (input/docs/ already had the data, the extractor
    # missed it). Each gate is chip-agnostic, silent-skips when its
    # trigger condition isn't met, honors a named waiver.
    #   LL-29: vendor FPGA reference timing table in input/docs/
    #          must propagate verbatim into L8 rx_classifier_ticks.
    "vendor_fpga_reference_table_extraction_check",
    #   LL-30: when L9 declares master_clock_hz == L2 chip target freq,
    #          RTL must NOT introduce a toggle divider for the chip
    #          clock. Direct master-clock binding is mandatory.
    "chip_clock_toggle_divider_when_master_already_target_check",
    #   LL-31: hierarchical extension of LL-27. Toggle-derived signal
    #          passed across module boundaries to a port that the
    #          submodule uses as `posedge` is also a violation, even
    #          though LL-27 (single-file scan) misses it.
    "toggle_divider_hierarchical_clock_check",
    #   LL-32: when input/docs/ measure timings (regex hit on
    #          `tXxx_us=NN` / `MIN..MAX..us` / vendor-table), L2 must
    #          NOT be abstract-only. At least one timing key.
    "l2_timing_completeness_check",
    #   LL-33: when input/docs/ contain `RSP_xx[NN]` per-opcode
    #          response-latency table, L11/L8 must propagate
    #          response_latency_ticks dict (or per-entry equivalent).
    "per_opcode_response_latency_table_check",
    # v0.119.33 LL-34..36 — closes the v0.119.32 <benchmark> vendor last
    # extractor gaps documented in PLUGIN_ENHANCEMENT_BACKLOG_v13.md.
    # All three are Cat A (vendor docs ARE complete; the plugin's
    # eyes were too narrow). Each gate silent-skips when its trigger
    # is absent and honors a named ≥40-char waiver.
    #   LL-34: when extracted text doc declares CRC parameters
    #          (polynomial+init/order signals — e.g. FRS §7), L3
    #          MUST emit `crc_parameters` (or `crc`) with
    #          polynomial_hex/init_hex/bit_order + an evidence path.
    "crc_parameters_extracted_check",
    #   LL-35: when input/docs/ contains a pin-planner / board /
    #          topology image, bringup-plan MUST run its vision step
    #          and emit rig_topology.json with the canonical schema.
    "rig_topology_image_extracted_check",
    #   LL-36: WARN-only — flag PDF entries in the doc-extract
    #          manifest whose coverage_score (text_chars/file_size)
    #          is below 2%, hinting that pdfplumber/PyMuPDF should
    #          be installed for figure-heavy docs.
    "binary_doc_low_extraction_warn",
    # v0.119.34 LL-37..38 — closes BACKLOG-v13 Wave 2 audit items #4
    # and #D (final extraction-fidelity gates). Both are Cat A and
    # silent-skip when their trigger condition is absent.
    #   LL-37: when rtl/*crc*.v has `crc_out <= 8'hXX` and L8 has a
    #          `crc8_constants` array (or `crc_parameters` block),
    #          the literal init / reflected polynomial values must
    #          agree. Catches v0.119.32 RTL-init=0xFF vs L8-SEED=0
    #          drift before tape-out.
    "crc_constants_rtl_doc_consistency_check",
    #   LL-38: scans input/docs/ + generated_docs/ for verbatim
    #          extraction coverage. FAILs if <95% of high-signal
    #          patterns from input docs appear in any L*.json.
    #          Defends against the 41% extraction-loss documented
    #          in EXTRACTION_COVERAGE_AUDIT_v0119.32.md.
    "extraction_coverage_check",
    # v0.119.37 / BACKLOG-v13 Wave 5: requires Phase 1 (doc-extraction) to emit
    #   `<project>/reports/extraction_coverage_report.{md,json}` and
    #   the recorded `overall.pct` to be >= 95%. Companion to LL-38;
    #   guarantees the human-reviewable report ships every run, not
    #   only when the agent remembers to invoke
    #   phase1_coverage_report_gen.py. Honors waiver
    #   `phase1_coverage_below_threshold_intentional` (>=40 chars).
    #   Silent-skip when no Phase 1 (doc-extraction) artefacts exist yet.
    "phase1_coverage_report_present_check",
    # v0.119.39 / BACKLOG-v13 Wave 7 LL-40: structural validation of the
    #   top-level `extraction_evidence` field that Wave 2 / Wave 5 / Wave 7
    #   SKILL.md updates require every L*.json to carry. LL-38 only does
    #   substring matching across the union; LL-40 verifies the field's
    #   shape (dict-of-list-of-{string|{literal,label}}). Required L docs:
    #   L1, L2, L3, L4, L6, L8, L9, L11. Honors waiver
    #   `extraction_evidence_schema_alternative` (>=40 chars). Silent-skip
    #   when generated_docs/ absent.
    "extraction_evidence_schema_check",
    # v0.119.44 / Wave 12 — three silicon-level RTL bug gates surfaced by
    # the v0.119.43 fresh-agent benchmark (17th attempt, <half-duplex-tester> byte[6]=
    # 0x02 FAIL despite Overall: PASS on 115 prior structural gates). The
    # agent's own RESULT.md diagnosis named exactly these three plugin-
    # capability gaps; Wave 12 ships chip-AGNOSTIC implementations:
    #   Gate 1: NBA shift-register-with-same-cycle-read race detector.
    #           Catches `out <= sr[1]; sr <= sr >> 1;` style bugs where
    #           the read sees stale pre-shift bits — the v0.119.43
    #           id_bus_phy.v tx_sr root cause. WARN on explicit concat-
    #           shift look-ahead patterns. Honors waiver
    #           `nba_shift_register_intentional` (>=40 chars).
    "nba_shift_register_same_cycle_read_check",
    #   Gate 2: bit-level full-stack TB oracle (companion to legacy
    #           bit_level_full_stack_tb_check). Forces results.json to
    #           carry per_vector expected-vs-actual byte arrays + L-doc
    #           evidence + TB/RTL-top file existence. Closes the
    #           "fabricate distinct-byte count" gameability hole. Honors
    #           waiver `bit_level_oracle_skipped` (>=40 chars).
    "bit_level_full_stack_tb_oracle_check",
    #   Gate 3: CRC compute-done before TX-state transition. When a CRC
    #           module exposes a done/valid/ready strobe and the FSM
    #           transitions to a TX-ish state, the transition must gate
    #           on that strobe. Silent-skip when no CRC module / no done
    #           port / no recognised TX state name. Honors waiver
    #           `crc_done_unnecessary_for_tx_timing` (>=40 chars).
    "crc_compute_done_before_tx_start_check",
    # v0.119.45 / Wave 13 — three new gates surfaced by the v0.119.44
    # 18th fresh-agent benchmark. The agent reached structural Overall:
    # PASS but <half-duplex-tester> byte[6]=0x02 FAIL on real silicon. CONNECT reply
    # arrived with 11 non-padding bytes; SEND_TEST → 4x async frames
    # all-padding from byte[6] onward. Three plugin-capability gaps:
    #   Gate 1: every L3-listed opcode must have a decode branch in the
    #           FSM (else SEND_TEST routes to default arm and returns
    #           padding). Honors `opcode_decode_intentionally_grouped`.
    "opcode_dispatch_completeness_check",
    #   Gate 2: every L9 / L11 named state must appear as a localparam /
    #           parameter / typedef-enum value in the FSM RTL. Closes
    #           the "behavioural sequence collapses onto default state"
    #           class. Honors `fsm_state_intentionally_collapsed`.
    "fsm_state_coverage_check",
    #   Gate 3: bit_level_full_stack_tb_oracle_check ENHANCEMENT — also
    #           cross-check per-vector CRC bytes against L3-declared
    #           CRC parameters. Catches the "agent picked arbitrary CRC
    #           variant, sim PASSes silicon FAILs" gameability hole.
    #           Honors `tb_crc_variant_intentional_mismatch`. (Already
    #           registered above; this comment documents the new
    #           enhancement.)
    # v0.119.47 / Wave 14 — closes the v0.119.46 fresh-agent benchmark
    # (20th attempt, <half-duplex-tester> byte[6]=0x02 FAIL despite Overall:
    # PASS_WITH_WAIVERS and 16/16 sim vectors PASS). Root cause:
    # rx_phy.sv collapsed the entire L8.rx_classifier_ticks vendor
    # reference table (H0/H1/BR/IBT/WKP min/max thresholds, contiguous
    # 1-tick gap between H1_MAX=195 and H0_MIN=196) onto a single
    # T_BIT_DECODE_THRESHOLD=200 magic constant. Real-silicon bits in
    # the gap region got mis-classified → host saw garbage → <half-duplex-tester>
    # padded byte[6]=0x02 instead of 0xF2. The L8 numbers were correct;
    # the RTL ignored them. Wave 14 ships a chip-AGNOSTIC structural
    # gate that fails the RTL when L8 has N classifier thresholds and
    # the RX-decode RTL covers fewer than N-1 distinct values, OR when
    # any L8 threshold value is missing from RTL ±1 tick. WARN-class
    # for RTL extras not in L8. Honors waiver
    # `rx_classifier_thresholds_simplified_intentional` (≥40 chars).
    "rx_classifier_thresholds_match_l8_check",
    # v0.119.48 / Wave 15 — closes the v0.119.47 fresh-agent benchmark
    # (21st attempt, <half-duplex-tester> byte[6]=0x02 FAIL despite Wave-14 PASS).
    # Root-cause analysis (docs/design/ROOT_CAUSE_DIFF_v068_vs_v0119.47.md)
    # ranks the 4 plugin gaps below by silicon-impact. All chip-AGNOSTIC.
    #   Gate 1 (CRITICAL): TX bit cell total-consumption check. Catches
    #           the silent sim-PASS / hardware-FAIL pattern where the
    #           TX side advances bit_idx after only the LOW phase plus
    #           a short fixed gap (e.g. 200 ns) instead of filling the
    #           bit cell to BIT_CY. Honors waiver
    #           `tx_bit_cell_intentionally_truncated` (>=40 chars).
    "tx_phy_bit_cell_total_consumed_check",
    #   Gate 2: RX IBT frame-end semantics — same threshold value used
    #           for BOTH byte-boundary AND frame-end signals collapses
    #           the two-tier inter-byte-time model. Honors waiver
    #           `rx_ibt_single_threshold_intentional` (>=40 chars).
    "rx_ibt_frame_end_semantics_check",
    #   Gate 3: RX byte-assembler IBT-flush recovery. Without an
    #           IBT-driven partial-byte flush, any single-bit RX glitch
    #           leaves bit_idx stuck mid-byte forever and the frame is
    #           lost. Honors waiver `rx_partial_byte_recovery_skipped`
    #           (>=40 chars).
    "rx_byte_assembler_ibt_flush_recovery_check",
    #   Gate 4: wake-pulse generator must suppress its pulse when the
    #           bus is active (host or DUT TX in progress); otherwise
    #           wake LOW collides with host BR/TX and corrupts framing.
    #           Honors waiver `wake_pulse_collision_acceptable` (>=40
    #           chars).
    "wake_gen_bus_active_reset_check",
    # v0.119.49 / Wave 16 — closes the v0.119.48 fresh-agent benchmark
    # (22nd attempt, <half-duplex-tester> byte[6]=0x02 FAIL). Root cause: MAX 10 doesn't
    # accept `(* ram_init_file *)` attribute, fresh-agent OTP ROM compiled
    # stuck-at-zero, all ID bytes = 0 (Hypothesis #5). Four chip-AGNOSTIC
    # gates close this and three companion gaps:
    #   Gate 1 (CRITICAL): catch silent BRAM/ROM init NOT loaded into the
    #           FPGA bitstream after Quartus compile. Parses fit.summary
    #           for `Total memory bits: 0 /` and map.rpt for verbatim
    #           Quartus warnings (`MIF is not supported for the selected
    #           family`, `RAM logic ... is uninferred`, etc.). Cross-checks
    #           QSF SEARCH_PATH coverage. Honors waiver
    #           `bram_init_runtime_loaded_intentional` (>=40 chars).
    "bram_init_file_actually_loaded_check",
    #   Gate 2: top-level wrapper for half-duplex single-wire bus must
    #           mask the RX path during DUT TX. Auto-discovers bus, OE,
    #           and sync-FF signals — chip-AGNOSTIC. Honors waiver
    #           `self_rx_no_mask_intentional` (>=40 chars).
    "self_rx_mask_required_check",
    #   Gate 3: when CRC engine is fed serially, the FSM consuming
    #           crc_q must wait at least one cycle after the LAST feed
    #           pulse before sampling — else crc_q is the byte-N-1
    #           residue. Detects same-cycle feed-pulse + crc_q-read in
    #           one state arm. Honors waiver
    #           `crc_settle_unnecessary_combinational_crc` (>=40 chars).
    "crc_q_settle_cycle_after_last_feed_check",
    #   Gate 4: when RTL uses $readmemh / $readmemb, Quartus QSF must
    #           have a SEARCH_PATH covering the dir containing the hex
    #           file, OR list it explicitly via MISC_FILE/MIF_FILE.
    #           Honors waiver
    #           `fpga_search_path_runtime_supplied_intentional` (>=40
    #           chars).
    "fpga_search_path_includes_required_dirs_check",
    # v0.119.50 / Wave 18 — closes the v0.119.49 vendor-PASS-oracle
    # benchmark (real PASS oracle: vendor_ref/.../dtop_fpga.sof,
    # hardware-verified <half-duplex-tester> byte[6]=0xF2 5/5). Two chip-AGNOSTIC
    # gates added; the Wave 15 `tx_phy_bit_cell_total_consumed_check`
    # is amended to compare RTL bit-low parameters against L8 vendor
    # measurements. Both new gates target the wake-pulse generator,
    # which the real-oracle root-cause diff identified as the top
    # delta between vendor RTL and fresh-agent v0.119.49.
    #   Gate 1: wake-pulse LOW duration must match the vendor
    #           measurement document (typically a PPTX scope-shot in
    #           input/docs/), within ±10%. WKP_MIN is the host
    #           classifier's acceptance threshold, NOT the chip's
    #           implementation target. Honors waiver
    #           `wake_pulse_intentional_offset` (>=40 chars).
    "wake_pulse_width_matches_measurement_check",
    #   Gate 2: wake-pulse generator must stop emitting after the
    #           first valid RX command (vendor reference gates wake
    #           counter via `have_received_id_cmd_latch`). Continuing
    #           to emit after handshake collides with host async
    #           frames on the open-drain bus. Honors waiver
    #           `wake_pulse_continuous_emit_intentional` (>=40 chars).
    "wake_pulse_emit_gated_by_first_rx_command_check",
    # v0.119.52 / Wave 20 — closes the v0.119.51 fresh-agent benchmark
    # (25th attempt, <half-duplex-tester> byte[6]=0x02 FAIL despite Wave 16 PASS).
    # Root cause: agent replaced `(* ram_init_file *)` with a
    # case-statement LUT-style ROM. Quartus STILL emitted the
    # `MIF not supported for the selected family` warning + `Total
    # memory bits: 0` because the BRAM-shape detector still fired.
    # Wave 16 gate skipped (no $readmemh / no ram_init_file). Wave 20
    # adds a finer-grained MAX-10-specific gate: any module whose name
    # suggests OTP/ROM/MEM/LUT and that declares a register array MUST
    # use either `altsyncram` Megafunction with init_file, or
    # `$readmemh` (paired with `AUTO_*_RECOGNITION OFF` QSF pragmas
    # — see vendor ram128x8.v reference). Honors waiver
    # `otp_pattern_intentional_logic_lut` (>=40 chars). Wave 20 also
    # tightens `bram_init_file_actually_loaded_check` so it FAILs on
    # the verbatim Quartus warning irrespective of explicit init
    # syntax when the project hosts a ROM-named module.
    "otp_module_uses_supported_pattern_check",
    # v0.119.55 / Wave 23 — Phase 1 (doc-extraction) 100% extraction coverage is a
    # HARD non-waivable requirement. This gate forbids any waiver
    # whose name matches a Phase 1 (doc-extraction)-related pattern (e.g.
    # `extraction_coverage_*`, `phase1_coverage_*`,
    # `extraction_evidence_*`, `phase1_*_acceptable`,
    # `phase1_*_intentional`, `extraction_*_alternative`). The 28th
    # fresh-agent attempt at 13.7% coverage silenced LL-38 + LL-39 +
    # LL-40 with three such waivers; Wave 23 closes the loophole.
    # Non-Phase-2a waivers (RTL-bug intentional, vendor table choice,
    # tester quirk, etc.) remain valid.
    "phase1_no_waivers_used_check",
    # v0.119.55 / Wave 23 — closes the v0.119.54 fresh-agent benchmark
    # (28th attempt) where Phase 1 (doc-extraction) produced ONLY 4 of 13 L docs
    # (L2/L8/L9/L11) and the agent silenced LL-38/LL-39/LL-40 with
    # three Phase 1 (doc-extraction)-named waivers. extraction coverage measured
    # 13.7% (149/1091) yet flow_compliance_check returned
    # `Overall: PASS_WITH_WAIVERS`. Wave 23 forbids those waivers
    # (`phase1_no_waivers_used_check` above) AND requires every L1-L13
    # generator to actually emit its L*.json with non-empty content.
    # A missing L doc means the auto-discovery patterns have nowhere
    # to land; coverage cannot reach 100% via patterns alone if 9 of
    # 13 generator skills were skipped. Chip-AGNOSTIC: matches by
    # `L<n>_` prefix only — any vendor-specific suffix is accepted.
    # NO WAIVER (Wave 23 hard rule).
    "phase1_all_l_docs_present_check",
    # v0.119.54 / Wave 22 — closes the v0.119.53 fresh-agent benchmark
    # (27th attempt, <half-duplex-tester> byte[6]=0x02 FAIL despite Wave-21 altsyncram
    # OTP loaded + 1024 memory bits). Root cause: top-level RX path used
    # a simple 2-FF synchronizer (id_ff1, id_ff2) feeding the bit decoder
    # directly. Vendor real-PASS-oracle uses 3-stage sync + 2-of-2
    # deglitch (`assign rx_low = syn3 & syn2;`). Without deglitch,
    # 1-cycle cable / EMI / open-drain edge glitches are mis-classified
    # by the bit decoder as BIT0/BIT1/BR/IBT, frame state corrupts, DUT
    # silent → host byte[6]=0x02 padding. Sim PASSes, hardware FAILes —
    # canonical silent sim-PASS / hardware-FAIL pattern. Chip-AGNOSTIC.
    # Honors waiver `rx_deglitch_intentionally_omitted` (>=40 chars).
    "rx_deglitch_filter_required_check",
    # v0.119.56 / Wave 24 — closes the v0.119.55 fresh-agent benchmark
    # (29th attempt, <half-duplex-tester> byte[6]=0x02 FAIL despite Phase 1 (doc-extraction) 100% +
    # 134 structural gates PASS). Vendor diff confirmed: the ONLY
    # systematic difference vs the PASS oracle was the missing SDC
    # clock constraint. Without SDC, Quartus optimises for area only,
    # critical paths run > clock period → setup slack negative → bit
    # decoder timing errors → CRC residue ≠ 0 → silent byte[6]=0x02.
    # Two gates close the gap end-to-end:
    #   - fpga_sdc_clock_constraint_check enforces a `create_clock`
    #     entry exists in <project>/fpga/*.sdc with period matching
    #     L8/RTL clock constants within 5%. Honors waiver
    #     `fpga_sdc_explicitly_unconstrained` (>=40 chars).
    #   - fpga_sta_negative_slack_check parses Quartus *.sta.summary
    #     in fpga/output_files/ and FAILs on any Setup/Hold slack <0
    #     ns at any corner (Slow 0C / Slow 85C / Fast 0C). Honors
    #     waiver `fpga_negative_slack_acceptable` (>=40 chars).
    # Both chip-AGNOSTIC. fpga_async_input_synchronizer_check (already
    # registered above) was extended in Wave 24 with the same waiver
    # surface (`fpga_async_input_synchronizer_intentional`) so that
    # the 3-gate FPGA timing+sync trio offers a uniform escape hatch.
    "fpga_sdc_clock_constraint_check",
    "fpga_sta_negative_slack_check",
    # v0.119.57 / Wave 25 — closes the v0.119.56 fresh-agent benchmark
    # (30th attempt, <half-duplex-tester> byte[6]=0x02 deterministic FAIL despite
    # Phase 1 (doc-extraction) 100% + 137 structural gates PASS + SDC/STA all corners
    # ≥ 0 ns slack). Vendor diff Pattern 5: fresh main_fsm.sv:374-400
    # emits `S_TX_BR` state (1200 ticks = 24 µs LOW) before
    # transmitting response bits; vendor `MAC.v:1017-1071` jumps
    # directly from RX-done → TX-CMD with no device-side BR. Host
    # <half-duplex-tester> reads the spurious 24 µs LOW as another BR/IBT
    # abnormality, resets frame state, discards DUT reply →
    # byte[6]=0x02. Chip-AGNOSTIC protocol convention: in
    # half-duplex single-wire request-response protocols (AID
    # class), the device/slave reply does NOT prepend its own BR;
    # the BR was the host's framing at the beginning. Honors waiver
    # `slave_tx_break_intentional` (≥40 chars).
    "slave_tx_no_device_break_check",
    # v0.119.58 / Wave 26 — closes the v0.119.57 fresh-agent benchmark
    # (31st attempt, <half-duplex-tester> byte[6]=0x02 deterministic FAIL across 5/5
    # connect_test runs despite Wave-25 PASS). Diagnosed in
    # `docs/design/MIN_DELTA_DIAG_v0119.57.md`: four chip-AGNOSTIC
    # silent-RTL-bug families surfaced concurrently.
    #   Gate 1 (PRIMARY): L8 rx_classifier_ticks must have CONTIGUOUS
    #       thresholds — h1_max+1 ≥ h0_min, h0_max+1 ≥ br_min,
    #       br_max+1 ≥ wkp_min.  Closes the multi-version vendor table
    #       gap (`20230103-3.txt` NEW: H0_MIN=196 + H1_MAX=192 →
    #       3-tick gap [193..195]).  Honors waiver
    #       `rx_classifier_threshold_gap_intentional` (≥40 chars).
    "rx_classifier_no_threshold_gap_check",
    #   Gate 2: byte_valid / byte_complete / crc_feed_vld emit must
    #       gate on an IBT-window counter (≥IBT_MIN), not just on
    #       `bit_idx == 8`.  Vendor RX_PHY.v:686 uses
    #       rx_data_byte_valid_2p5m gated by ≥234 ticks settle.
    #       Honors waiver `rx_byte_valid_no_ibt_gate_intentional`
    #       (≥40 chars).
    "rx_byte_valid_requires_ibt_gate_check",
    #   Gate 3: altsyncram (and similar BRAM-inferred ROM) read
    #       latency vs FSM consume cycle count.  outdata_reg_a
    #       "UNREGISTERED" → 2-cycle wait required; "CLOCK0"/default
    #       → 3-cycle wait.  Off-by-one consume returns previous
    #       address content.  Honors waiver
    #       `bram_latency_intentional_offset` (≥40 chars).
    "bram_read_latency_consume_alignment_check",
    #   Gate 4: between last RX bit and CRC-validate state, FSM must
    #       have a dedicated settle state (≥1 cycle) waiting for
    #       crc_out to fully propagate.  Direct RX-byte-receive →
    #       VALIDATE transitions sample stale residue.  Honors waiver
    #       `crc_settle_in_validate_state_intentional` (≥40 chars).
    "crc_residue_settle_state_required_check",
    # v0.119.57 / Wave 25 — defensive hardening companion gate.
    # Locks the (poly_form, input_direction, output_reversal)
    # triple-pairing for CRC engines so a future fresh-agent that
    # half-rewrites a CRC module cannot silently regress to a
    # wire-incompatible CRC. PASS combinations: (0x31, MSB-first,
    # DIRECT), (0x8C, LSB-first, DIRECT), (0x31, MSB-first,
    # explicit bit-reverse load — vendor 0x31 + reversal). FAILs
    # poly=0x8C with MSB-first input or poly=0x31 with LSB-first
    # input. SKIPs gracefully when poly cannot be classified.
    # Honors waiver `crc_polyform_intentional_pairing` (≥40 chars).
    "crc_polyform_outputreversal_pairing_check",
    # v0.119.59 / Wave 27 — closes the v0.119.58 fresh-agent benchmark
    # (32nd attempt, <half-duplex-tester> byte[6]=0x02 deterministic FAIL across 5/5
    # connect_test runs).  Diagnostic
    # `docs/design/SCOPE_DIAG_v068_vs_v0119.58.md`: vendor PASS DUT
    # actively drives id_bus during SEND_TEST async response (E0 frame
    # trailer = real CRC `01 A9`); v0.119.58 trailer = `02 02` (host
    # padding).  CONNECT reply identical between both → basic tristate
    # works.  The dispatch → 0x74 → TX path is silent.  Two
    # chip-AGNOSTIC structural gates close the gap.
    #   Gate 1 (PRIMARY): for every SEND_TEST-class opcode in L3
    #     (synonyms get_id / get_info / get_state / query / identify /
    #      send_test / get_serial / get_eeprom / read_id),
    #     verify the FSM contains a dispatch arm whose state-chain
    #     reaches an OE-family signal asserted to 1'b1 with a per-bit
    #     counter (≥8 bit cells loop).  Honors waiver
    #     `send_test_silent_intentional` (≥40 chars).
    "send_test_active_drive_check",
    #   Gate 2: catch the canonical "fresh-agent fully wires CONNECT
    #     handler but stubs SEND_TEST" pattern.  Compare downstream
    #     dispatch-chain line counts; FAIL when SEND_TEST < 50% of
    #     CONNECT.  Honors waiver
    #     `send_test_dispatch_intentionally_minimal` (≥40 chars).
    "connect_vs_send_test_parity_check",
    # v0.119.60 / Wave 28 — runtime functional verification gate.  After
    # 33 fresh-agent attempts the static structural-RTL gates were at
    # their limit: every project hit Overall: PASS on 145 gates yet
    # still produced byte[6]=0x02 deterministic FAIL on real silicon.
    # The plugin now ships
    # `tools/protocol_tb/aid_class_reference_tb.v` — a chip-AGNOSTIC
    # half-duplex AID-class reference TB that drives host-side BR +
    # cmd-byte + tSRS gap and captures DUT-side bytes.  This gate
    # plugs the agent's RTL into the TB, compiles with iverilog,
    # runs with vvp, and parses stdout for the
    # `PROTOCOL_REFERENCE_TB_PASS` sentinel.  Static gate PASS is
    # necessary but no longer sufficient — runtime PASS is the
    # functional contract.  WARNs (does NOT block) when iverilog is
    # missing on the build host so legacy CI nodes still work.
    # SKIPs gracefully for non-protocol designs (no inout id_bus, no
    # L3 commands).  Honors waiver
    # `protocol_reference_tb_skipped_intentional` (≥40 chars).
    "protocol_reference_tb_pass_check",
    # v0.119.61 / Wave 29 — Wave 28 reference TB caught two silent
    # bugs in the v0.119.59 RTL that 33 prior hardware FAIL attempts
    # could not pin: (a) illegal SV `function void` with output args,
    # (b) RX FSM next-edge classify with no frame-end commit losing
    # the last bit of every frame.  Two new chip-AGNOSTIC gates close
    # those classes:
    #   Gate 1 - function_void_with_output_check: scans rtl/ for SV
    #     functions declaring output / inout args (LRM violation;
    #     iverilog crashes; Quartus tolerates -> silent FAIL on real
    #     silicon).  Honors waiver `function_void_output_intentional`
    #     (>=40 chars).
    "function_void_with_output_check",
    #   Gate 2 (PRIMARY) - rx_last_bit_frame_end_commit_check:
    #     enforces that an RX FSM either classifies bits on the
    #     rising edge of the LOW pulse (Pattern A) or, when
    #     classifying on the next falling edge (Pattern B), commits
    #     the in-progress bit on the frame-end / timeout path before
    #     transitioning to validate.  Without commit, the last bit of
    #     any frame whose final bit is followed by bus release is
    #     lost -> CRC FAIL -> dispatch never fires -> DUT silent.
    #     Honors waiver `rx_last_bit_loss_intentional` (>=40 chars).
    "rx_last_bit_frame_end_commit_check",
    # v0.119.63 / Wave 31 — anti-gaming: separate "in typed structured
    # field" from "in raw blob".  SEMANTIC_AUDIT_v0119.57 (1094/1094 =
    # 100% literal-grep score) revealed that ~87% of design data lived
    # in `all_input_literals_aggregated` and 9 of 13 L docs carried
    # ZERO typed structured fields.  Four chip-AGNOSTIC gates close
    # the loophole, all NON-WAIVABLE (forbidden prefixes
    # `l_doc_structured_*` / `l_doc_aggregated_*` / `l_doc_unique_*` /
    # `extraction_coverage_denominator_*` enforced by
    # `phase1_no_waivers_used_check`).
    #   Gate 1: each L doc must carry a minimum number of typed
    #           structured fields (per L-layer semantic role).
    "l_doc_structured_field_count_check",
    #   Gate 2: blob-shape fields (`all_input_literals_aggregated`,
    #           `*_dump`, `*_blob`, `*_aggregated`, `raw_text`,
    #           `LX_DUMP*`) bounded — single-field 10 KB / per-doc
    #           50 KB / global 200 KB.
    "l_doc_aggregated_blob_size_check",
    #   Gate 3: distinct vendor token count must dominate the
    #           recorded extraction-coverage denominator (≥80% PASS,
    #           ≥50% WARN, <50% FAIL); catches the v0.119.50/56
    #           denominator-shrink gameplay (38/118 vs legit 1091/1094).
    "extraction_coverage_denominator_audit",
    #   Gate 3b: per-input-doc completeness — each input document's
    #           harvested tokens must appear ≥50% in
    #           generated_docs/L*.json. Closes the silent-skip vector
    #           where phase1's extractors miss an entire vendor doc
    #           because of fname-filter or format-extractor gaps.
    #           Forbidden waiver prefix `phase1_input_vs_generated_*`.
    "phase1_doc_input_completeness_check",
    #   Gate 4: pairwise jaccard similarity between L docs ≤70% so a
    #           shared aggregated blob across all 13 L*.json FAILs.
    "l_doc_unique_content_check",
    # v0.119.65 / Wave 33 — RESULT.md provenance gate.  When agent
    # ships RESULT.md claiming Phase 2+3 PASS / a successful SOF
    # burn, the document MUST cite (a) the SHA-256 of
    # phase23_completion_audit.json they self-audited against,
    # (b) the mcp-eda program-tool response (or
    # `burn_provenance.json`) carrying a PASS-class success marker,
    # (c) the audit verdict value (PASS or PASS_WITH_WAIVERS).
    # The Wave 33 burn guard refuses to burn when the audit JSON
    # verdict is FAIL, so a successful burn implies a specific
    # response; missing citations indicate either an unguarded
    # burn (closed in Wave 33) or RESULT.md fabrication.  SKIP
    # when RESULT.md is absent or honestly reports FAIL.  Honors
    # waiver `result_md_audit_provenance_intentional` (≥40 chars).
    "result_md_audit_provenance_check",
    # v0.119.69 / Wave 37 — Phase 1 (doc-extraction) extraction-completeness gates.
    # Close the column-D documentation extraction gaps observed in
    # docs/design/COL_D_DOCS_AUDIT.md: vendor docs (RX_EVENT,
    # opcode-detail override, ADDR/LEN limit footnotes) were not
    # systematically ingested into L3/L6 typed fields. Each gate is
    # chip-AGNOSTIC: triggers purely on vendor-doc filename patterns
    # and language-agnostic regex; SKIP when the trigger doc absent.
    #   A1: RX-event decision-table -> L6 reject_rules array
    #   A2: opcode-override doc -> L3 response_payload_template
    #   A3: ADDR/LEN constraint footnote -> L3 argument_constraints
    #   A4: cross-doc ADDR-limit conflict -> WARN if no resolution doc
    "l6_reject_rules_from_rx_event_check",
    "l3_opcode_response_template_check",
    "l3_opcode_argument_constraints_check",
    "doc_consistency_no_unresolved_conflicts_check",
    # v0.119.70 / Wave 38 — typed sub-field DEPTH gates. Audit
    # `docs/design/PHASE2A_FULL_AUDIT_v0119.67.md` line 67-77 found
    # ~70 missed items remain after Wave 37 — almost all are typed
    # sub-field shallowness (vendor data lives in free-form
    # `description` strings instead of typed schemas). Each Wave 38
    # gate is chip-AGNOSTIC, triggers only when the L doc / vendor
    # docs supply enough signal, and SKIPs cleanly otherwise.
    #   B1: L1 electrical_specs[] needs name/min_typ_max/unit/
    #       conditions/evidence per entry. Catches the audit's
    #       electrical-limits gap (line 22, 75).
    "l1_electrical_specs_typed_depth_check",
    #   B2: L1 pin_table[] needs name/mode/aliases per entry.
    #       Closes datasheet-vs-RTL-vs-board name disambiguation
    #       (audit line 35: FPGA pinmap missing typed shape).
    "l1_pin_table_aliases_typed_check",
    #   B3: L4 multi-bit register fields with enum-style names
    #       (DLY/MODE/SEL/CFG/...) must declare enumerated_values[].
    #       Closes 4-state debounce / filter mode gap (audit line
    #       28, 67, 77).
    "l4_regmap_enumerated_values_typed_check",
    #   B4: when multi-clock topology detected, L8/L9 must declare
    #       a typed clock_domains[] with master + derived. Closes
    #       master/divided/external clock gap (audit line 24, 32).
    "l8_clock_domains_typed_check",
    #   B5: L11 otp_lock_bits[] must carry typed `affects[]` +
    #       `trigger_value`. Closes "0x40 default 00, write 80
    #       then 0x60-0x7F not writable" dependency edge gap (audit
    #       line 57, item #10).
    "l11_otp_lock_dependencies_typed_check",
    #   B6: L12 sequences must carry typed steps[] with action +
    #       expected_signal/latency_us/next_state, plus a trigger.
    #       Closes wake-handshake / engineer-mode-entry gap
    #       (audit line 29, 30).
    "l12_behavioral_sequences_steps_typed_check",
    # v0.119.71 (Wave 39) — backlog-v0119.70 post-PASS items + 3
    # test-pattern coverage gates.
    #   A1: byte-assembler explicit 9-bit detector + main_fsm reject
    #       path. Closes col-D R8/R9 silent-by-side-effect FAIL.
    "byte_assembler_explicit_9bit_reject_check",
    #   B1: main_fsm cmd_buf[N] usage must align with L3
    #       payload_semantics + RTL comment. Closes the v0.119.70
    #       E2 dispatch arm where comment says LEN/ADDR but logic
    #       contradicts.
    "cmd_buf_index_semantic_consistency_check",
    #   C2: each L3.opcodes entry must carry typed
    #       pre_wake_allowed: bool. NO WAIVER (governance hard).
    "l3_opcode_pre_wake_allowed_typed_check",
    #   D1: L10.test_cases must cover every L3 constraint
    #       (positive AND negative).
    "l10_test_cases_cover_l3_constraints_check",
    #   D2: L11/L12 silent sequences must cover every L6.reject_rule.
    "l11_sequence_covers_l6_reject_rules_check",
    #   D3: every L3 constraint must have a matching SystemVerilog
    #       assertion (assert/assume/cover property) in rtl/.
    "assertion_covers_l3_constraints_check",
    # v0.120.1 / Wave 47 — prevent silent SKIP of analog content +
    # generic "every spec section must be cited" gate. Closes the
    # v0.120 fresh-agent failure where <chip-class> datasheet documented
    # oscillator + RPD + RMPD + ESD + TRIM_VBG/LDO/OSC OTP registers
    # but agent emitted L5_ADI_SPEC.json analog_blocks=[] and
    # A0_skip_decision.json: SKIPPED-CONDITION. The first gate is
    # chip-AGNOSTIC across 8 analog keyword classes (oscillator /
    # LDO / bandgap / POR / pull / ESD / charge-pump / trim) and
    # FAILs when keyword detected in docs but L5 lacks a matching
    # entry. The second gate is a generic per-section coverage
    # audit (every section heading in docs must be cited by some
    # L*.json field).
    "analog_content_detected_must_emit_l5_check",
    "phase1_doc_content_implementation_completeness_check",
    # v0.120.2: closes the gap where L5 has analog blocks but
    # input/pdk/ ships only the digital wrapper. Verifies SPICE model
    # deck + DRC deck + LVS deck axes are present; honors waiver
    # pdk_analog_deck_pending_foundry_nda. Chip-AGNOSTIC.
    "pdk_analog_completeness_check",
    # v0.121: closes the silent-FAIL where Quartus / iverilog load an
    # all-zero placeholder OTP image, build succeeds, chip burns, but
    # every byte from OTP is 0x00 → hardware deterministically FAILs
    # host-tester verdict. Honors waiver
    # otp_image_intentionally_zeroed (>=60 chars). Chip-AGNOSTIC.
    "otp_image_nonzero_check",
    # v0.123: closes the silent-loss bug where EDA tools write outputs
    # to /tmp (or other volatile locations) and the agent forgets to
    # copy them back into the project tree before claiming completion.
    # Wave 53 left a real GDS at /tmp/.../chip_top.gds; Wave 55 audit
    # assumed it didn't exist and left 33 spurious waivers open.
    # Honors waiver project_artifacts_external_storage_intentional.
    # Chip-AGNOSTIC.
    "project_outputs_in_tree_check",
    # v0.124 / Wave 58 — closes Wave 56 column-D RTL bug families on
    # v0.121-vendor.  Each gate is chip-AGNOSTIC, silent-skips when its
    # trigger condition is absent, and honors a named ≥40-char waiver.
    #   Gate 1: wake-pulse generator else-branch period-counter reset
    #     starves the periodic pulse on continuous host polling
    #     (Issue 2 root cause). Honors waiver
    #     `wake_pulse_counter_else_reset_intentional` (≥40 chars).
    "wake_gen_silence_gate",
    #   Gate 2: every L3 opcode must have an explicit case arm in the
    #     dispatch FSM, OR the default arm must be silent-reject.
    #     Catches the spam-responder default that mass-PASSes 0xE0/
    #     0xE2/0x76/0x78 frames (Issues 4 + 0xE0/0xE2 silent fail).
    #     Honors waiver `dispatch_handler_intentionally_default_routed`
    #     (≥40 chars).
    "dispatch_handler_completeness",
    #   Gate 3: when L3.crc_parameters declared AND a CRC engine is
    #     instantiated in rtl/, its output (crc_q / crc_ok / etc.)
    #     MUST be in the validate / dispatch / frame_ok decision
    #     fan-in.  Closes the "CRC computed but never consumed"
    #     silent-PASS hole.  Honors waiver
    #     `crc_validation_explicit_bypass` (≥40 chars).
    "crc_validation_present",
    #   Gate 4: when a scope CSV captures a host→chip round-trip on
    #     a half-duplex bus, the chip-reply window MUST NOT contain
    #     any LOW pulse ≥ BR_MIN ticks (BR is the host's framing).
    #     Catches Issue 3 (14.92 µs preamble) directly without RTL
    #     access.  Honors waiver
    #     `chip_reply_br_preamble_intentional` (≥40 chars).
    "scope_reply_preamble_check",
    #   Gate 5: rig firmware capability blockers must carry an explicit
    #     `rig_firmware_*` waiver instead of silently SKIP.  Catches
    #     the RIG_BLOCKED column-D rows that today look like RTL bugs
    #     in the audit dashboard.  Honors waiver `rig_firmware_blocker`
    #     (or any `rig_firmware_*` key, ≥40 chars).
    "rig_firmware_capability_check",
    # Wave 79 — cross-layer integrity gate. When both L9 + RTL are
    #   present, verifies top_level_ports[] vs RTL top module match on
    #   pin set + direction. Catches the silent-floating-pin / silent-
    #   default-pin classes where QSF/SDC generators emit assignments
    #   for non-existent RTL ports (or skip RTL ports that have no L9
    #   entry). Silent for L9-only or RTL-only states (different gate's
    #   job). Honors waiver `l9_rtl_pin_consistency_intentional`
    #   (≥40 chars).
    "l9_rtl_pin_consistency_check",
    # v1.6.19 wire-in — submodule-half companion to the Wave 79 gate
    #   above. Catches the artefact-level consequences of CLAUDE.md
    #   rule #1 (multi-agent port-naming drift) and rule #3 (no stub
    #   modules): every L9.submodules[].name must have a matching
    #   `module <name>` declaration in rtl/*.sv|.v AND must be
    #   instantiated by some other module (dead-code detection). When
    #   schema_version=1, also cross-checks per-submodule .ports against
    #   the actual RTL port list. VACUOUS_PASS when L9 is absent or
    #   carries no submodules. Real-world signal: v0117-vendor flags 9
    #   genuine submodule gaps (L9 declares 12 submodules, rtl/ emits 4).
    "l9_submodule_conformance_check",
    # v1.6.29 wire-in — substance / canonical-real-file gates from
    #   v1.6.28 / v1.6.29. Both VACUOUS_PASS-friendly so they don't
    #   misfire on digital-only projects or pre-GDS-stream-out runs.
    #   - analog_artefact_substance_check (v1.6.28): catches 64-byte
    #     HEADER+ENDLIB GDS stubs and the
    #     `ai_authored_methodology_stub` self-marker the v10627-vendor
    #     run shipped for all 8 analog blocks (32 substance-less
    #     deliverables that passed presence-only audit).
    #   - chip_gds_canonical_real_file_check (v1.6.29): catches
    #     symlinks at phase3/stage4/gds/, phase3/mixed_signal/,
    #     phase3/stage4/foundry_handoff/ — same anti-pattern v1.6.22
    #     deleted by hand from v10619.
    "analog_artefact_substance_check",
    "chip_gds_canonical_real_file_check",
    # v1.6.51 wire-in — generalised symlink ban under all canonical
    #   deliverable trees (phase3/stage4, phase3/mixed_signal,
    #   phase2/stage1/fpga, phase2/stage2/synth, analog/hardmacro).
    #   The chip-GDS gate above is one slice; this is the file-extension-
    #   AGNOSTIC generalisation covering Verilog netlists, LEF/Liberty,
    #   SDC/SPEF, SOF, .rpt sign-off files. Foundry-shipped reference
    #   symlinks can be exempted via `<project>/.canonical_symlink_allowlist`.
    #   Closes backlog ORGANIC-20260508-canonical-symlink-forbid.yaml.
    "canonical_path_symlink_forbid_check",
    # v1.6.51 wire-in — substance check for whitelisted phase1 metadata
    #   JSON files. v1.6.26 taxonomy verifies location only; this gate
    #   verifies content. Catches `extraction_patterns.json={}`,
    #   `extraction_patterns.auto.json={"patterns":[]}`,
    #   `completeness_check_config.json={"version":1,"checks":[]}` —
    #   all of which pass taxonomy but yield vacuous downstream
    #   coverage. Closes backlog
    #   ORGANIC-20260508-metadata-content-substance.yaml.
    "metadata_content_substance_check",
    # v1.6.55 wire-in — Tier-2 phase1 structured-field substance.
    #   Tier-1 (token-presence-anywhere) misses the case where every
    #   mandatory L-doc field is at template default while a catch-all
    #   `auto_discovered_identifiers` list scoops up surface tokens.
    #   This Tier-2 gate audits the structured fields downstream
    #   consumers actually query (ic_name, protocol_overview, opcodes,
    #   fsm_states, pin_table, electrical_specs) against per-field
    #   template-default rules. FAILs only on > 30% of audited fields
    #   at default; WARN on smaller proportions; escape-valve via
    #   `no_<field>_in_input: true` siblings (generalises L5 no_analog
    #   / L11 no_calibration). Closes detection-half of GitHub issue #4.
    "phase1_structured_field_substance_check",
    # v1.6.31 wire-in — provenance.jsonl audit-chain completeness.
    #   Each tool invocation must declare every output as
    #   sha256:<64-hex>, and every declared file must exist + match.
    #   Closes the v1.6.30 doctrine rule #2 ("Provenance entries
    #   carry SHA256 of every output. Empty is honest; fabricated
    #   is dishonest.") that until now lived in agent prompt-text
    #   only. Synthetic-timestamp pattern (all entries on `:00`
    #   seconds) is a WARNING by default; promote to FAIL with
    #   --strict-timing.
    "provenance_output_hash_completeness_check",
    # v1.6.33 wire-in — doctrine rule #5: AGENT_REPORT.md must carry
    #   SHA256 attestation of every canonical artefact (SOF / GDS /
    #   synth netlist / LEF / Liberty). The presence gate (v1.6.24)
    #   only checks the 5 section names; this gate audits the report
    #   content. Real-world signal: v10619-vendor (0 sha256) and
    #   v10627-vendor (1 sha256, missing GDS attestation) both FAIL.
    "agent_report_sha256_attestation_check",
    # v1.6.38 — `emitter_failure_mode_check` /
    # `literal_verdict_keyword_check` / `source_chip_agnostic_check` /
    # `changelog_metric_reproducibility_check` are intentionally NOT
    # wired here: they audit the *plugin source* (a project would not
    # normally ship a fork of plugin code), so they run as standalone
    # CI / pre-commit gates against the plugin tree, not against
    # individual project trees. See `tools/ci/run_plugin_self_audit.sh`
    # for invocation. Wiring them here would emit VACUOUS_PASS on every
    # project (no programs/ subdir under <project>) and add no value.
    # v1.4.0 wire-in (revised v1.6.4): only gates that silent-skip
    # cleanly on incomplete projects. Removed 3 that FAIL on legitimate
    # phase-incomplete projects (dispatcher_awake_gate_check,
    # behavioral_evidence_per_spec_item_check, gate_evidence_completeness_check).
    "derived_clock_sdc_required_check",
    "cross_constant_invariant_check",
    "dispatcher_response_size_table_audit",
    "pad_drive_high_active_check",
    "waiver_legitimacy_check",
    # v1.6.0 wire-in (revised v1.6.4 after quality review):
    # Only gates verified to silent-skip cleanly on incomplete projects
    # are wired below. Gates that need pipeline-late prerequisites
    # (synth/sim/UPF/coverage/HW verdict) are available as standalone
    # *_check.py but NOT in the canonical structural-RTL-gates tuple.
    "backlog_sanitize_check",
    "fpga_program_chain_attest_check",
    "fpga_qsf_lint",
    "fresh_agent_provenance_check",
    "ic_class_consistency_check",
    "json_schema_check",
    "l9_completeness_check",
    "layer_extension_presence_check",   # patched v1.6.4: silent-skip on generic classes
    "manifest_leak_check",
    "module_port_audit",
    "no_protocol_consistency_check",
    "openroad_tcl_deprecation_check",
    "output_artifact_check",
    "payload_bit_position_check",
    # phase1_consistency_check / phase1_doc_presence_check retracted v1.6.4
    # — only applicable to Path A (NL prompt → L docs); FAILs cleanly
    # on Path B projects that ran phase1 from input/docs.
    "phase1_k5_quality_check",
    "phase1_quality_parity_check",
    "phase1_gate_contract_check",
    "practical_notes_specificity_check",
    "rtl_precheck_gate",
    "scope_periodic_pulse_check",
    "skill_compliance_triangle_check",
    "testbench_exists_check",
    "tester_oracle_health_check",
    # v1.6.4 RETRACTED (introduced regression on incomplete projects;
    # gates lack chip-AGNOSTIC silent-skip on missing prerequisites):
    # "coverage_metric_check"            — needs sim coverage report
    # "flow_stage_check"                  — signoff_audit late-phase
    # "frontend_backend_handoff_check"   — needs synth netlist in synth/
    # "functional_state_transition_coverage_check" — needs sim transcript
    # "hw_vs_rtl_verdict_check"           — needs hardware verdict file
    # "synth_wrapper_check"               — synth-stage prereq
    # "upf_syntax_check"                  — only applicable to UPF designs
    # "verilator_coverage_measure"        — needs verilator coverage
)

# Canonical synthesis-script search order. v0.70 Item 1 runs the two
# v0.69-shipped Yosys auditors (yosys_hilomap_required_check,
# yosys_script_template_check) against whichever path exists first.
_YS_SEARCH_ORDER: tuple[str, ...] = (
    "scripts/synth.ys",
    "synth/synth.ys",
    "synth.ys",
    "scripts/yosys.ys",
    "yosys.ys",
    "rtl/synth.ys",
    # Wildcard fallback: any .ys at project root or under scripts/ / synth/.
    "*.ys",
    "scripts/*.ys",
    "synth/*.ys",
)


def _find_synth_ys(project: Path) -> Optional[Path]:
    """Locate the Yosys synthesis script emitted by step 9 (Synthesis).

    We search `_YS_SEARCH_ORDER` top-to-bottom; the first match wins. If
    the wildcard tail matches multiple files we pick the one whose name
    contains 'synth' (case-insensitive) — otherwise the first
    lexicographic hit. Returns None when nothing is found (caller then
    reports MISSING, not FAIL, because some flows ship no .ys at all —
    e.g. pre-Yosys schematic-only drafts).
    """
    for pat in _YS_SEARCH_ORDER:
        if "*" in pat or "?" in pat:
            matches = sorted(project.glob(pat))
            if matches:
                # Prefer a file whose name suggests synthesis.
                for m in matches:
                    if "synth" in m.name.lower():
                        return m
                return matches[0]
        else:
            p = project / pat
            if p.is_file():
                return p
    return None


@dataclass
class StepResult:
    id: Any  # int for main-track steps (1-40), str for analog ("A1"-"A9") / mixed-signal ("M1"-"M4") / preflight ("P0")
    name: str
    stage: str
    status: str  # PASS, FAIL, MISSING, WAIVED, SKIPPED-CONDITION
    reasons: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)
    gate_output: str = ""


# reports/ subdirs to also probe when a yaml-pattern starts with `reports/`.
# Gate writers historically write to flat reports/<name>; the post-generate
# sweep in final_report_generate.py moves them into category subdirs. This
# fallback lets audit gates still find them after the sweep without forcing
# every yaml entry to know which subdir each artefact ends up in.
_REPORTS_SUBDIR_FALLBACK = (
    # v1.6.25 — phase-aligned subfolders (new canonical taxonomy)
    "phase1", "phase2", "phase3", "analog", "audit", "orchestrator",
    # nested-under-audit subdirs that programs sometimes target directly
    "signoff", "hardware",
)


def _glob_first(project: Path, pattern: str) -> List[str]:
    """Return list of paths (relative to project) matching the glob pattern.

    For patterns starting with ``reports/`` and finding no direct match,
    also probe ``reports/<subdir>/<rest>`` to accommodate the post-
    generate sweep that moves flat reports/ artefacts into category
    subdirs (sourced by `_REPORTS_SUBDIR_FALLBACK`).
    """
    matches = sorted(project.glob(pattern))
    if not matches and pattern.startswith("reports/"):
        rest = pattern[len("reports/"):]
        for sd in _REPORTS_SUBDIR_FALLBACK:
            matches = sorted(project.glob(f"reports/{sd}/{rest}"))
            if matches:
                break
    # v0.2.55 — canonical-analog-dir tolerance. The flow-def pins analog
    # A-step artefacts at phase-distributed prefixes (phase1/analog/,
    # phase2/analog/, phase3/analog/), but the analog runner writes ALL
    # of them under the single canonical analog dir (`_pl.analog_dir`,
    # currently phase3/analog/). When a `phase{1,2,3}/analog/<rest>`
    # pattern misses, re-probe the canonical analog dir with the same
    # tail. chip-AGNOSTIC: pure path remap, no chip names.
    if not matches:
        # Longest prefix first so "phase3/analog/" wins over "analog/".
        for _pref in ("phase1/analog/", "phase2/analog/", "phase3/analog/",
                      "analog/"):
            if pattern.startswith(_pref):
                tail = pattern[len(_pref):]
                try:
                    canon = _pl.analog_dir(project)
                    canon_matches = sorted(canon.glob(tail))
                    if canon_matches:
                        matches = canon_matches
                        break
                except Exception:
                    pass
    return [str(m.relative_to(project)) for m in matches]


def _check_files_exist(project: Path, patterns: List[str], any_of: bool) -> tuple[bool, List[str], List[str]]:
    """Return (passed, found_paths, missing_patterns)."""
    found: List[str] = []
    missing: List[str] = []
    for pat in patterns:
        # Support "A OR B" syntax in YAML-level patterns by splitting
        sub_patterns = [p.strip() for p in pat.split(" OR ")]
        hits_for_this = []
        for sp in sub_patterns:
            hits_for_this.extend(_glob_first(project, sp))
        if hits_for_this:
            found.extend(hits_for_this)
        else:
            missing.append(pat)
    if any_of:
        passed = len(found) > 0
    else:
        passed = len(missing) == 0
    return passed, found, missing


def _expand_globs(args: List[str], cwd: Path) -> List[str]:
    """Expand shell-style globs in program arguments (bash nullglob semantics).
    If a glob pattern has NO match, drop it — this mirrors what a shell with
    `shopt -s nullglob` does and matches the intent of flow gates that list
    multiple optional source globs like `phase2/stage1/rtl/*.sv
    phase2/stage1/rtl/*.v`. Non-glob args pass through unchanged."""
    out: List[str] = []
    for a in args:
        if any(c in a for c in ["*", "?", "["]) and not a.startswith("-"):
            matches = sorted(str(p.relative_to(cwd)) for p in cwd.glob(a))
            if matches:
                out.extend(matches)
            # else: nullglob — drop the pattern entirely
        else:
            out.append(a)
    return out


def _resolve_program_cmd(cmd_str: str, cwd: Path | None = None) -> List[str]:
    """Turn 'program_name arg1 arg2' into ['python3', '/path/to/program.py', 'arg1', 'arg2'].
    Program names without .py are resolved against PROGRAMS_DIR. Globs in args
    are expanded relative to cwd (the project dir) so yaml gates can use
    shell-style patterns like 'rtl/*.sv'."""
    parts = shlex.split(cmd_str)
    if not parts:
        return []
    prog_name = parts[0]
    if not prog_name.endswith(".py"):
        prog_path = PROGRAMS_DIR / f"{prog_name}.py"
    else:
        prog_path = PROGRAMS_DIR / prog_name
    if not prog_path.exists():
        return []
    args = parts[1:]
    if cwd is not None:
        args = _expand_globs(args, cwd)
    return [sys.executable, str(prog_path)] + args


def _check_program_exit_zero(project: Path, cmd_str: str) -> tuple[bool, str]:
    """Run program in project dir (with globs expanded relative to project),
    return (passed, output_snippet).

    Exit-code semantics align with the structural-RTL-gates runner
    (`_run_structural_rtl_gates`):
      * rc == 0  → PASS
      * rc == 2  → VACUOUS_PASS — the "input-missing skip" convention
                   used by gate programs that print
                   ``verdict: SKIP`` and exit 2 when the artefact they
                   audit doesn't exist yet (e.g.
                   foundry_handoff_package_check on pre-tapeout
                   projects, mixed_signal_merge_check on digital-only
                   projects). The snippet is prefixed with the Wave 93
                   ``__VACUOUS_HINT__:`` sentinel so check_step
                   promotes the step to the VACUOUS_PASS verdict tier
                   instead of plain PASS.
      * rc == 1  → FAIL
      * other    → FAIL
    """
    argv = _resolve_program_cmd(cmd_str, cwd=project)
    if not argv:
        return False, f"program not found: {cmd_str.split()[0]}"
    try:
        r = subprocess.run(
            argv,
            cwd=project,
            capture_output=True,
            text=True,
            timeout=300,
        )
        snippet = (r.stdout[-300:] + "\n" + r.stderr[-300:]).strip()
        if r.returncode == 0:
            return True, snippet
        if r.returncode == 2:
            # Treat as vacuous pass — surface the program command so
            # reviewers know which gate vacuously passed.
            return True, f"{_VACUOUS_HINT_PREFIX}{cmd_str}"
        return False, snippet
    except subprocess.TimeoutExpired:
        return False, f"program timed out: {cmd_str}"
    except Exception as exc:
        return False, f"program invocation error: {exc}"


# Wave 93 / v1.6.17 — VACUOUS_PASS verdict tier support.
# A gate program may signal "I ran but the input it audits doesn't apply
# to this project" by:
#   * exiting 0, AND
#   * printing a line beginning with "VACUOUS_PASS:" on stdout, AND/OR
#   * writing a JSON report whose top-level "verdict" field is
#     "VACUOUS_PASS".
# This pattern was introduced in Wave 92 / v1.6.16 for the Step 14 Yosys
# gate when no .ys script exists, but the verdict tier itself was never
# formalised in flow_compliance_check.py — so projects whose only Step
# 14 evidence was VACUOUS_PASS were displayed as ordinary PASS without a
# distinguishing label. Wave 93 makes the tier first-class: counted as a
# PASS for verdict aggregation, but rendered as "VACUOUS-PASS" in the
# per-step listing so reviewers can see which steps actually executed
# vs. were vacuously satisfied.
_VACUOUS_HINT_PREFIX = "__VACUOUS_HINT__: "


def _stdout_signals_vacuous(snippet: str) -> bool:
    """Return True iff the program's combined stdout/stderr snippet
    contains a `VACUOUS_PASS:` token at line-start. Allows leading
    whitespace from indented logging."""
    if not snippet:
        return False
    for line in snippet.splitlines():
        if line.lstrip().startswith("VACUOUS_PASS"):
            return True
    return False


def _run_yosys_gates(project: Path) -> tuple[bool, List[str]]:
    """Run the v0.69-shipped Yosys script auditors against the project's
    synthesis .ys file. v0.70 Item 1: both checks must pass BEFORE any
    PnR step is allowed to evaluate, so a synth script that skipped
    hilomap can't silently produce a netlist that detailed_route then
    crashes on.

    Returns ``(passed, reasons)`` with one or more human-readable
    remediation strings on failure. If the project ships no .ys script
    at all, the gate is skipped (passed=True) — a pre-PnR flow without a
    Yosys script typically means the project is using a different
    synthesiser and the canonical check does not apply.
    """
    ys_path = _find_synth_ys(project)
    if ys_path is None:
        # No .ys file at all — not a FAIL because flows without Yosys are
        # legitimate (e.g. Cadence Genus or GlobalFoundries flows). The
        # wider flow_compliance_check still catches a missing netlist
        # via step 9's required_outputs.
        return True, []

    reasons: List[str] = []
    ys_rel = ys_path.relative_to(project) if ys_path.is_absolute() \
        else ys_path

    # --- yosys_hilomap_required_check: ordering constraint -----------------
    hilomap_prog = PROGRAMS_DIR / "yosys_hilomap_required_check.py"
    if hilomap_prog.exists():
        try:
            r1 = subprocess.run(
                [sys.executable, str(hilomap_prog),
                 "--ys-file", str(ys_path)],
                capture_output=True, text=True, timeout=60,
            )
        except subprocess.TimeoutExpired:
            return False, [
                f"FAIL: yosys_hilomap_required_check timed out on "
                f"{ys_rel} — cannot verify techmap→hilomap→write_verilog "
                f"ordering, so PnR is unsafe. Re-run the check manually."
            ]
        if r1.returncode != 0:
            reasons.append(
                f"FAIL: yosys_hilomap_required_check failed — PnR will "
                f"crash at detailed_route with DRT-0305 zero_ GROUND on "
                f"the unmapped tie net. Add "
                f"`hilomap -hicell TIEHI Y -locell TIELO Y` to your "
                f"{ys_rel} between `techmap` and `write_verilog` "
                f"(see CLAUDE.md rule 4)."
            )
            # Include the auditor's own stderr excerpt so the operator can
            # see the exact line number that tripped the check.
            snippet = (r1.stdout.strip() + "\n" + r1.stderr.strip()).strip()
            if snippet:
                reasons.append(f"    auditor output: "
                               f"{snippet.splitlines()[0][:200]}")
    else:
        reasons.append(
            "FAIL: yosys_hilomap_required_check.py not found in "
            "programs/ — plugin install may be incomplete."
        )

    # --- yosys_script_template_check: token presence ----------------------
    tmpl_prog = PROGRAMS_DIR / "yosys_script_template_check.py"
    if tmpl_prog.exists():
        try:
            r2 = subprocess.run(
                [sys.executable, str(tmpl_prog),
                 "--ys-file", str(ys_path)],
                capture_output=True, text=True, timeout=60,
            )
        except subprocess.TimeoutExpired:
            reasons.append(
                f"FAIL: yosys_script_template_check timed out on "
                f"{ys_rel} — cannot verify -sv/-flatten/hilomap are "
                f"present; treat as fail for strict gating."
            )
        else:
            if r2.returncode != 0:
                reasons.append(
                    f"FAIL: yosys_script_template_check failed — one of "
                    f"-sv / -flatten / hilomap is missing from {ys_rel}. "
                    f"Without `-flatten` the ATPG flow breaks on "
                    f"backslash-escaped hierarchical names; without `-sv` "
                    f"SystemVerilog RTL is rejected; without `hilomap` "
                    f"OpenROAD trips DRT-0305. CLAUDE.md rule 4 requires "
                    f"all three for real-PDK synthesis."
                )
                snippet = (r2.stdout.strip() + "\n"
                           + r2.stderr.strip()).strip()
                if snippet:
                    reasons.append(f"    auditor output: "
                                   f"{snippet.splitlines()[0][:200]}")
    else:
        reasons.append(
            "FAIL: yosys_script_template_check.py not found in "
            "programs/ — plugin install may be incomplete."
        )

    return (len(reasons) == 0), reasons


# v1.6.97 (issue #29 Bugs 1+2) — thin-input waiver scaffold.
#
# Some benchmark / customer projects are intentionally thin on input
# documentation (e.g. IC-A with a single short datasheet excerpt and
# 2-3 application notes — total <5 input docs). The two extractor-
# coverage gates (``phase1_doc_input_completeness_check`` and
# ``l_doc_structured_field_count_check``) cannot pass on such projects
# because the extractor genuinely has nothing more to harvest. Without
# a waiver path these projects can never reach PASS_WITH_WAIVERS, which
# blocks downstream USB-HID tester / Phase 3 GDS work.
#
# The ``--allow-thin-input`` flag converts FAILs from EXACTLY these two
# gates to a WAIVED entry (review_required: true, ticket id) when the
# project's input-doc count falls below ``THIN_INPUT_DOC_COUNT_THRESHOLD``.
# Other gates' FAILs are NOT waived; nor are these two gates waived on
# projects with adequate input docs (≥ threshold) — those FAILs are real
# bugs in the extractor / project content, not thin-input artefacts.
#
# Threshold = 5: empirically, projects with ≥5 input docs have enough
# breadth that a coverage FAIL is symptomatic of a real extractor gap
# (or missing source content), not of input thinness.
#
# v1.6.98 (issue #30 Bug 2) — the doc-count predicate is RETIRED in
# favour of a COVERAGE-shape predicate. Real-world benchmarks (e.g.
# IC-A with 31 input docs) hit the same coverage-gap pattern as a
# 3-doc project: extractors can't catch every register-table row in
# every doc-shape, regardless of total doc count. The new predicate
# fires when ANY input doc is below 100% capture, gated by a
# MAX_THICK floor (200 docs) to reject projects that dump huge
# bundles to game the gate. THIN_INPUT_DOC_COUNT_THRESHOLD is kept
# as a legacy constant for any external code that still imports it,
# but the runtime no longer consults it.
THIN_INPUT_DOC_COUNT_THRESHOLD = 5  # legacy; superseded by coverage-shape predicate (v1.6.98)
MAX_THICK_DOC_THRESHOLD = 200       # anti-gaming floor on doc count
_THIN_INPUT_WAIVER_GATES = (
    "phase1_doc_input_completeness_check",
    "l_doc_structured_field_count_check",
    # v0.1.57 capture: atomic Shape-D problems (CVDP-style: brief prompt + 1-page
    # spec) have spec-faithful L docs that legitimately don't carry the depth
    # these two gates expect of SoC-grade inputs. Without waivers, atomic
    # single-module IPs can never reach PASS_WITH_WAIVERS even when their
    # RTL/synth/lint pass cleanly. Eligibility is still gated by the
    # _is_thin_input_eligible predicate so rich projects don't get a free pass.
    "l9_submodule_conformance_check",
    "metadata_content_substance_check",
)
_THIN_INPUT_WAIVER_TICKET = "thin-input-v1.6.97"

# v0.1.57: absolute-size threshold for the "100% capture of a tiny input"
# case. The existing predicate (any doc <100%) doesn't fire when the
# extractor caught everything from a brief input — but those L docs are
# still too thin to support SoC-grade structural gates. When sum(raw_total
# across non-reference docs) <= this many tokens, the project counts as
# thin even when capture is 100%.
TINY_INPUT_TOTAL_RAW_TOKENS = 100


# v1.6.210 (#91) — PASS_WITH_OPEN_SOURCE_CONSTRAINTS verdict tier.
# Canonical map of step ids whose required EDA tools are not present
# in the open-source iic-osic-tools container and have no equivalent
# substitute. Each entry pairs a step id to the commercial tool family
# the step would normally consume.
#
# This is a CONSERVATIVE list: steps included here are confirmed to
# have no usable open-source path in the iic-osic-tools container as
# of v1.6.210. Steps that DO have an open-source equivalent (e.g.,
# 21 SPEF via OpenRCX, 23 IR via OpenSTA+PDNGEN, 25 antenna via
# OpenROAD antenna_checker, 32 metal fill via OpenROAD fill) are
# DELIBERATELY EXCLUDED — leaving those gates FAIL / MISSING is the
# correct verdict, because the open-source path was available and
# wasn't taken.
#
# chip-AGNOSTIC: this is a tool-availability mapping, not a chip-
# class mapping. Every project using iic-osic-tools as its container
# inherits the same set.
#
# When the user enables the OS-constraints promotion path (default),
# a FAIL verdict is upgraded to PASS_WITH_OPEN_SOURCE_CONSTRAINTS
# IFF (a) every failing / missing item is in this map, (b) the chip
# is engineering-complete (Step 36 PASS + fpga_burn PASS), and
# (c) no P0 umbrella defects, no structural-RTL defects.
#
# The tier carries `review_required: true` and an explicit deferral
# list. It is NOT a green pass — it is a machine-attested deferral
# that the tapeout vendor must close before production.
_OPEN_SOURCE_CONTAINER_BLOCKED_STEPS: Dict[Any, str] = {
    5:  "Formal verification harness (SymbiYosys IS in container, "
        "but L3-driven SVA / cover-property authoring is project-specific "
        "and not auto-generatable; human design-spec needed)",
    11: "DFT insertion (Tessent Scan / DFTMAX)",
    12: "Post-DFT optimisation (Design Compiler + DFT)",
    13: "RTL≡post-DFT equivalence (Formality / Conformal)",
    # v1.6.211 (#92) — added per field-agent verification that
    # iic-osic-tools open-source paths do not produce gate-required
    # signoff artefacts. OpenRCX / OpenSTA-IR / antenna_checker /
    # OpenROAD-fill / klayout-LVS work for development but not for
    # tapeout-grade signoff precision.
    21: "Parasitic Extraction → SPEF (Calibre xRC / StarRC; OpenRCX "
        "lacks signoff-grade precision)",
    23: "IR Drop static+dynamic (RedHawk / Voltus; OpenSTA+PDNGEN "
        "only handles static average IR)",
    24: "EM check (RedHawk-EM / Totem)",
    25: "Antenna check (Calibre PERC antenna rules; OpenROAD "
        "antenna_checker only catches a subset)",
    26: "Signal Integrity (Sigrity / Cadence SI)",
    28: "Post-Layout SPICE PV (HSPICE / Spectre)",
    29: "Physical Verification ERC + Density signoff (Calibre PERC + "
        "DRC density; klayout/magic DRC/LVS cover topology but not "
        "ERC/density signoff variants)",
    32: "Metal Fill (Calibre YieldEnhancer / ICC2 metalfill; "
        "OpenROAD fill produces non-signoff geometry)",
    "M1": "Mixed-signal top-level merge (Cadence AMS)",
    "M2": "Mixed-signal AMS co-sim (Xcelium AMS)",
    "M3": "Mixed-signal final PV (Calibre AMS)",
    "M4": "Mixed-signal tapeout PV (Calibre AMS + LVS)",
    # v1.6.225 (#96 follow-up) — Step A4 (analog corner sweep) is a
    # top-level canonical step (stage_analog), NOT a P0 umbrella sub-
    # gate. v1.6.223 added the per-block gate `analog_a4_corner_sweep_
    # _check` to `_P0_THIN_INPUT_DEFERRABLE_SUBGATES`, but the Step A4
    # itself fails outside P0, so the P0 deferral path never reached
    # it. Field-agent #96 verification confirmed the canonical-flow
    # verdict still resolved to `Overall: FAIL` because A4 stays at
    # status=FAIL with proxy testbench misses (Brokaw bandgap, multi-
    # phase charge-pump, pull-device topology) outside any deferral
    # pathway. Routing A4 through the OS-constraints top-
    # level map matches how Steps 5/11/12/13/21/23/25/29/32 and the
    # mixed-signal M1-M4 entries handle the same shape of gap.
    # chip-AGNOSTIC: rationale is tool-availability, not chip-class.
    "A4": ("Analog corner sweep spec convergence (Cadence Virtuoso "
           "AMS + Spectre + real PDK characterization; iic-osic-tools "
           "proxy testbenches in analog_real_corner_sweep.py prove "
           "the tooling path only — Brokaw bandgap, multi-phase "
           "charge-pump, pull-device topology refinement all require "
           "commercial AMS sign-off)"),
    # v0.2.103 (#496) — PDK-substitution deferral for the analog A-steps
    # whose deck instantiation depends on a foundry PDK that has no public
    # ngspice models. When L19 declares a non-default target process and
    # the runner's OWN sizing/netlist decks HONESTLY disclose that they
    # substitute the open-source default PDK (sky130A / gf180mcuD), the
    # #438b PDK-mismatch gate (correctly) intercepts even those decks — so
    # A3 (and the downstream A5-A9 steps that consume A3's decks) become
    # PERMANENTLY unpassable on the open-source path: fabrication forbidden,
    # no waiver, no disclosure route. These entries give the SAME shape of
    # deferral that A4 / Steps 5/11-13/21-32 already carry: routed through
    # the OS-constraints promotion (review_required, named commercial-tool
    # requirement) AND, more precisely, through the pdk-substitution
    # ENV_UNAVAILABLE waiver synthesised in `_load_waivers` so the step is
    # WAIVED-DEFERRED (named reason + ticket), never counted executed-PASS.
    # Applicable ONLY under the disclosed-substitution predicate; an
    # UNDISCLOSED deck mismatch still hard-FAILs. chip-AGNOSTIC: keyed on
    # PDK-availability, never any chip-class literal.
    "A3": ("Analog netlist generation against the L19 target process "
           "(Cadence Virtuoso schematic + foundry PDK device models; the "
           "open-source default PDKs sky130A / gf180mcuD ship public "
           "ngspice models only — a non-default target's decks must "
           "substitute the open-source default, which the #438b "
           "PDK-mismatch gate correctly intercepts)"),
    "A5": ("Analog layout against the L19 target process (Magic / Cadence "
           "Virtuoso Layout XL + foundry PDK; non-default target has no "
           "public layout tech, so layout runs against the substituted "
           "open-source PDK)"),
    "A7": ("Post-layout resimulation against the L19 target process "
           "(parasitic models for the non-default target need the foundry "
           "PDK; only the substituted open-source PDK has public models)"),
    "A8": ("Hardmacro generation (LEF/Liberty/GDS/Verilog) against the "
           "L19 target process (characterised against the foundry PDK; the "
           "substituted open-source PDK is what the open path can deliver)"),
    "A9": ("Mixed-signal co-sim / HW verification against the L19 target "
           "process (AMS environment + foundry PDK; the open path runs the "
           "substituted open-source PDK)"),
}

# v1.6.211 (#92) — structural-RTL sub-gates inside the P0 umbrella
# that are deferrable under the open-source-container promotion path.
# When P0 status is FAIL but EVERY failing sub-gate (as parsed out of
# the P0 reasons[] list) is in this set, the P0 FAIL is "soft" — it
# does NOT block the PASS_WITH_OPEN_SOURCE_CONSTRAINTS promotion, and
# P0 is added to the deferral list with a per-sub-gate breakdown.
# Each entry maps the sub-gate name (matching _STRUCTURAL_RTL_GATES
# basenames, sans `_check` suffix variations) to the rationale for
# why an open-source container can't close it.
# chip-AGNOSTIC: sub-gates are checker programs whose blockers come
# from missing input docs / commercial AMS interface contracts, not
# from any chip-class identifier.
_P0_THIN_INPUT_DEFERRABLE_SUBGATES: Dict[str, str] = {
    "analog_a2_topology_select_check": (
        "Per-block analog topology.md needs commercial AMS schematic "
        "front-end (Spectre AMS / Virtuoso schematic capture)"),
    # v1.6.226 (#96 follow-up 2) — analog_corner_sweep_check is the
    # older project-wide PVT-coverage gate (distinct from the newer
    # per-block analog_a4_corner_sweep_check). It demands ≥9 corners
    # per block (3 process × 3 temps), but the open-source path's
    # `analog_real_corner_sweep.py` runner only emits 1 corner
    # (tt @ 27C) per block, because the iic-osic-tools open-source
    # PDKs (sky130A, gf180mcuD) ship typical-only ngspice device
    # models — there is no ss/ff/sf/fs corner file in the public
    # PDK distribution. Full 3-process × 3-temp × Vdd corner +
    # Monte-Carlo matching needs commercial PDK characterization
    # corner files plus the ams-sim AI skill upgrade (as the runner
    # explicitly documents in its header). Routing this gate
    # through the same P0 sub-gate deferral path matches how the
    # newer analog_a4_corner_sweep_check (v1.6.223) is handled.
    # chip-AGNOSTIC: rationale is PDK-availability, not chip-class.
    "analog_corner_sweep_check": (
        "PVT corner sweep (3 process × 3 temps × Vdd) requires "
        "commercial PDK characterization corner files; open-source "
        "PDKs (sky130A, gf180mcuD) ship typical-only ngspice device "
        "models, so analog_real_corner_sweep.py can emit only the "
        "tt@27C corner. Full ss/ff/sf/fs × temp × Vdd sweep + MC "
        "matching needs commercial corner kits + ams-sim AI skill "
        "upgrade"),
    # v1.6.223 (#96) — Real-silicon spec convergence on bandgap /
    # charge_pump / pull / etc. proxy testbenches requires Cadence
    # Virtuoso AMS + Spectre + real PDK device-grade characterization.
    # The iic-osic-tools open-source proxy testbenches in
    # analog_real_corner_sweep.py prove the tooling path (ngspice
    # runs, .measure parses, corner_results.json emits) but cannot
    # close topology spec compliance (e.g. Brokaw bandgap PTAT/CTAT
    # trim, multi-phase charge-pump clocking, real pull-device
    # sizing). Foundry tapeout review must close this with commercial
    # AMS. chip-AGNOSTIC — applies to any project running the open-
    # source A4 path.
    "analog_a4_corner_sweep_check": (
        "Real-silicon analog spec convergence (Cadence Virtuoso AMS "
        "+ Spectre + real PDK characterization; iic-osic-tools proxy "
        "testbenches prove the tooling path only, not topology spec "
        "compliance)"),
    # v1.6.229 (#97) — four structural-RTL sub-gates whose root
    # cause is the same open-source-PDK + open-source-AMS gap that
    # already defers analog_corner_sweep_check /
    # analog_a4_corner_sweep_check / analog_digital_interface_check.
    # They all FAIL on the OS path because A5-A8 (Magic layout,
    # xschem schematics, hardmacro LEF/Liberty/GDS, mixed-signal
    # AMS merge, full A1-A9 closure) require commercial AMS tools
    # or device-grade PDK characterisation that the iic-osic-tools
    # container cannot provide. Routing them through the same P0
    # sub-gate deferral path keeps the verdict-promotion logic
    # consistent. chip-AGNOSTIC: every entry's rationale references
    # tool / PDK availability, never any chip-class identifier.
    "analog_block_coverage_check": (
        "Per-block A5-A8 hardmacro / layout coverage requires "
        "commercial AMS (Cadence Virtuoso) or Magic + xschem with "
        "full PDK device libraries; open-source PDK distributions "
        "ship the digital cell stacks only, not the analog primitive "
        "device libraries needed for analog block coverage"),
    "analog_hardmacro_check": (
        "Hardmacro LEF / Liberty / GDS / Verilog deliverables need "
        "real analog layout closure (Cadence Virtuoso Layout XL + "
        "Calibre LVS/DRC). Open-source Magic / netgen path produces "
        "geometry but not signoff-grade hardmacro views"),
    "mixed_signal_cosim_check": (
        "M1-M4 mixed-signal top-level merge requires real hardmacro "
        "GDS files + AMS co-sim environment (Cadence Xcelium AMS / "
        "Spectre); open-source iic-osic-tools has no AMS co-sim "
        "harness"),
    "analog_flow_compliance_check": (
        "Full A1-A9 analog closure (topology select → corner sweep "
        "→ layout → post-layout resim → hardmacro emit → AMS co-sim) "
        "requires a commercial AMS environment with characterised "
        "PDK corner files; the open-source path can prove tooling "
        "wiring but not flow closure"),
    "analog_digital_interface_check": (
        "Mixed-signal interface contract (AMS supply/level-shifter "
        "BFM) requires commercial AMS environment"),
    "l_doc_structured_field_count_check": (
        "Typed-field threshold not met — thin input docs require "
        "additional human-authored design content"),
    "phase1_doc_input_completeness_check": (
        "Input doc capture below 100% — extractor coverage shape "
        "gap; requires human-authored doc to close"),
    "protocol_ip_simulation_required_check": (
        "Protocol IP simulation harness requires commercial protocol "
        "BFM (USB / PCIe / SystemVerilog VIP)"),
}

# Steps the chip must have passed for the OS-constraints promotion
# to fire. These are the "chip is shipped on FPGA" signals.
_OS_CONSTRAINTS_PREREQ_STEPS: tuple[Any, ...] = (
    6,   # FPGA early prototype + verification report audit
    36,  # FPGA final sign-off (recompile + on-board test)
)


def _parse_p0_failing_subgates(p0_result: Any) -> List[str]:
    """v1.6.211 (#92) — extract failing structural-RTL sub-gate names
    from a P0 StepResult's reasons list.

    The P0 umbrella emits reason lines of the form
        "FAIL: <gate_name> — <first message line>"
    or, when ≥2 gates fail, a header `Failed gates (N):` followed by
    indented `- <gate_name> — <msg>` lines (see the structural_result
    composition site).  Both shapes are handled.

    Returns the de-duplicated list of failing gate names (stripped of
    the FAIL prefix and dashes).  Empty list if the result is None or
    not a P0 step.
    """
    if p0_result is None:
        return []
    out: List[str] = []
    seen: set = set()
    for line in (p0_result.reasons or []):
        s = str(line).strip()
        if not s:
            continue
        # Form 1: "FAIL: gate_name — msg"
        if s.startswith("FAIL: "):
            s = s[len("FAIL: "):]
        # Form 2: "- gate_name — msg" (indented under "Failed gates (N):")
        elif s.startswith("- "):
            s = s[2:]
        elif s.startswith("Failed gates"):
            continue
        elif s.startswith("SKIP:") or s.startswith("WAIVED"):
            continue
        # Pull the gate name up to the first " — " or whitespace
        for sep in (" — ", " - ", ":"):
            if sep in s:
                s = s.split(sep, 1)[0].strip()
                break
        else:
            s = s.split()[0] if s.split() else s
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _count_input_docs(project: Path) -> int:
    """Count the input documents available to phase1 extractors.

    Prefers ``phase1/input_doc/*.txt`` (the canonical post-
    extraction location); falls back to ``input/docs/*.txt`` for
    pre-extracted projects. De-duplicates by basename so the same
    doc present in both directories counts once.
    """
    seen: set = set()
    for d in (_pl.input_doc_dir(project), project / "input" / "docs"):
        if not d.is_dir():
            continue
        for p in d.glob("*.txt"):
            seen.add(p.name)
    return len(seen)


def _is_thin_input_eligible(project: Path) -> bool:
    """v1.6.98 (issue #30 Bug 2) — coverage-shape thin-input predicate.

    Eligible iff:
      - the phase1 completeness report exists, AND
      - any per-doc entry has captured_pct < 1.0 with raw_total > 0
        and is not a reference_doc (i.e. real coverage gap), AND
      - total doc count <= MAX_THICK_DOC_THRESHOLD (anti-gaming).

    Replaces the earlier ``len(input_docs) <= 5`` doc-count predicate.
    A 31-doc project with 3 below 100% capture (the IC-A benchmark
    pattern) is now eligible; a 1000-doc dump with one stub is NOT.

    Falls back to the legacy doc-count predicate (count <
    THIN_INPUT_DOC_COUNT_THRESHOLD) if the completeness report is
    missing, so projects that have never run phase1 yet still get
    the v1.6.97 thin-input behaviour. Returns False if the report is
    present but malformed (don't crash on schema drift).
    """
    report_path = _pl.report_path(
        project, "phase1_input_vs_generated_completeness.json")
    if not report_path.is_file():
        # No report → fall back to legacy doc-count behaviour.
        return _count_input_docs(project) < THIN_INPUT_DOC_COUNT_THRESHOLD
    try:
        data = json.loads(report_path.read_text())
    except Exception:
        return False
    per_doc = data.get("per_doc")
    if not isinstance(per_doc, list):
        # Defensive: also handle dict-shaped per_doc if the schema
        # ever drifts (current schema is list-of-dicts).
        if isinstance(per_doc, dict):
            per_doc = list(per_doc.values())
        else:
            return False
    if not per_doc:
        return False
    if len(per_doc) > MAX_THICK_DOC_THRESHOLD:
        return False
    # v0.1.57: "tiny absolute-size input" predicate, orthogonal to coverage%.
    # If sum(raw_total) across non-reference docs is <= TINY_INPUT_TOTAL_RAW_TOKENS,
    # the input is too small to support SoC-grade structural gates even when
    # the extractor captured 100% of it. CVDP atomic problems hit this case
    # (the v0.1.56 fixed_priority_arbiter had sum(raw_total)=0; the
    # priority_encoder had sum(raw_total)=3).
    total_raw = 0
    for entry in per_doc:
        if not isinstance(entry, dict):
            continue
        if entry.get("reference_doc") is True:
            continue
        total_raw += int(entry.get("raw_total") or 0)
    if total_raw <= TINY_INPUT_TOTAL_RAW_TOKENS:
        return True
    # Original predicate: any non-reference doc below 100% capture.
    for entry in per_doc:
        if not isinstance(entry, dict):
            continue
        if entry.get("reference_doc") is True:
            continue
        if (entry.get("raw_total") or 0) <= 0:
            # SKIP_LOW_TOKENS / empty docs don't count as coverage gaps.
            continue
        captured = entry.get("captured_pct", entry.get("capture_pct", 1.0))
        try:
            if float(captured) < 1.0:
                return True
        except (TypeError, ValueError):
            continue
    return False


# v1.6.523 — class-aware gate skip-set. The hardwired Phase-2 protocol
# + analog gates assume an AID-class half-duplex command-driven IC with
# analog content. Generic digital IP (CPUs, crypto, arithmetic
# primitives, bit-serial cores) legitimately have NO SW-visible command
# protocol and NO analog content — running these gates against them is a
# guaranteed false-FAIL. When the detected class marks command_protocol
# / analog as not-applicable, these gates SKIP (with an explicit
# "N/A for class X" reason) instead of FAIL. Core functional/structural
# gates (lint, synth, CDC, sim correctness) are NEVER in this set.
#
# Each entry: gate_name -> applicability-flag key in class_verification_flags.
#   "command_protocol_applicable" — protocol opcode-argument / typed-
#       electrical-spec / protocol-behavioral-step / protocol-sim gates
#   "analog_applicable"           — analog block-coverage / hardmacro /
#       mixed-signal / analog-content-must-emit gates
_CLASS_SKIPPABLE_PROTOCOL_GATES: frozenset[str] = frozenset({
    "l3_opcode_argument_constraints_check",     # opcode addr_max/len_max
    "l1_electrical_specs_typed_depth_check",     # typed electrical spec
    "l12_behavioral_sequences_steps_typed_check",  # protocol behavioral step
    "protocol_ip_simulation_required_check",     # protocol sim required
})
# ORGANIC-20260605-fullstack-byte-oracle-inapplicable-to-datapath-primitive
# (#419): full-stack byte-protocol ARTEFACT gates. For a registry-matched
# class with command_protocol_applicable=false (datapath / combinational
# primitives — "No SW-visible protocol / register map", per the registry
# entry) these are structurally unsatisfiable: there are no opcodes to
# build golden response bytes from, no register fields to type or lay
# out, no submodule decomposition to conform to, and no protocol
# metadata to be substantive about. A functionally perfect primitive
# (lint clean, synth clean, zero latches, functional TB PASS) would
# carry a guaranteed false-FAIL.
#
# DOUBLE-KEYED, fail-closed: the skip fires ONLY when (a) the class
# flag says command_protocol_applicable=false AND (b) the L docs
# POSITIVELY record a no-opcode/no-regmap input
# (_ldocs_record_no_opcodes) — a primitive-classed project whose input
# docs DO define opcodes or registers keeps every gate. The
# primitive-appropriate set (generic_full_stack reference TB against
# the L9 contract, lint, synth, latch checks) still runs and still
# gates.
_CLASS_SKIPPABLE_FULLSTACK_ARTEFACT_GATES: frozenset[str] = frozenset({
    "rtl_response_byte_oracle_check",         # byte-protocol golden vectors
    "l4_regmap_enumerated_values_typed_check",  # register-map field depth
    "regmap_bit_layout_check",                # register-map bit layout
    "l9_submodule_conformance_check",         # submodule structure
    "metadata_content_substance_check",       # protocol metadata substance
})


def _ldocs_record_no_opcodes(project: Path) -> bool:
    """Deterministic L-doc evidence that the INPUT itself carries no
    command protocol: every opcode/command list across generated_docs
    L3*.json is empty AND the L4 regmap records no registers (or an
    explicit register_map_present=false). Missing generated_docs ->
    False (fail-closed: no positive evidence, keep every gate).

    #419 REOPEN fix: the canonical runner layout is
    phase1/generated_docs/ (_pl.generated_docs_dir) — the original
    helper read project/generated_docs and therefore NEVER found a real
    runner's docs (fail-closed dormancy on every production project);
    root generated_docs/ stays only as a legacy-layout fallback."""
    gd = _pl.generated_docs_dir(project)
    if not gd.is_dir():
        gd = project / "generated_docs"   # legacy fallback layout
    if not gd.is_dir():
        return False

    def _count_named_lists(obj: Any, key_tokens: tuple) -> int:
        n = 0
        if isinstance(obj, dict):
            for k, v in obj.items():
                kl = str(k).lower()
                if isinstance(v, list) and any(t in kl for t in key_tokens):
                    n += len(v)
                n += _count_named_lists(v, key_tokens)
        elif isinstance(obj, list):
            for it in obj:
                n += _count_named_lists(it, key_tokens)
        return n

    saw_any_doc = False
    opcode_total = 0
    reg_total = 0
    regmap_explicitly_absent = False
    for f in sorted(gd.glob("L3*.json")) + sorted(gd.glob("L4*.json")):
        try:
            data = json.loads(f.read_text())
        except Exception:
            return False        # unreadable evidence -> fail closed
        saw_any_doc = True
        name = f.name.upper()
        if name.startswith("L3"):
            opcode_total += _count_named_lists(data, ("opcode", "command"))
        else:
            reg_total += _count_named_lists(data, ("register",))
            if isinstance(data, dict) and \
                    data.get("register_map_present") is False:
                regmap_explicitly_absent = True
    if not saw_any_doc:
        return False
    return opcode_total == 0 and (reg_total == 0 or regmap_explicitly_absent)


_CLASS_SKIPPABLE_ANALOG_GATES: frozenset[str] = frozenset({
    "analog_block_coverage_check",
    "analog_hardmacro_check",
    "mixed_signal_cosim_check",
    "analog_content_detected_must_emit_l5_check",
    # v1.6.553 — post-layout SPICE correlation is an ANALOG / mixed-signal
    # signoff deliverable, NOT a digital one. For a pure-digital IC class
    # (analog_applicable=False) the critical-path is signed off by STA +
    # SPEF + Liberty — there is never a transistor-level SPICE deck to
    # correlate against. Without this skip, every digital-only IC that
    # completes Phase 3 (and therefore emits phase3/stage3/extracted/*.spef
    # + phase3/stage3/sta/*.rpt) trips spice_correlation_check's
    # NO_SPICE_VERIFICATION FAIL, which under --skip-analog surfaced as a
    # spurious phase2 FAIL on digital command-driven protocol ICs (espi /
    # usb_pd / sgmii). HONEST + GENERAL: this fires ONLY when the detected
    # IC class is registry-matched AND analog_applicable=False (fail-closed
    # for unknown classes); a genuinely-analog IC (analog_applicable=True)
    # still runs the gate and still FAILs on a missing/uncorrelated SPICE
    # deck. The analog-HW sibling self-skips on absent hw_measurements.json
    # but is class-gated here too for symmetry.
    "spice_correlation_check",
    "analog_hw_spice_correlation_check",
})


def _class_skipped_gates(project: Path) -> Dict[str, str]:
    """v1.6.523 — return {gate_name: skip_reason} for gates that are
    N/A for the detected IC class (chip-AGNOSTIC).

    Fail-closed: if the class is unknown / unregistered, or the profile
    helper is unavailable, returns {} so EVERY gate runs (no weakening
    of existing FAIL logic). Only opens a skip when there is positive
    evidence that command_protocol / analog is not-applicable for the
    class.
    """
    try:
        import sys as _sys
        if str(PROGRAMS_DIR) not in _sys.path:
            _sys.path.insert(0, str(PROGRAMS_DIR))
        from ic_class_profile import (detect_ic_class,
                                      class_verification_flags)
    except Exception:
        return {}
    try:
        profile = detect_ic_class(project) or {}
    except Exception:
        return {}
    ic_class = str(profile.get("ic_class") or "unknown")
    flags = class_verification_flags(ic_class)
    # Fail-closed: only act on registry-matched classes with explicit
    # not-applicable flags. An unmatched class keeps every gate.
    if not flags.get("registry_matched"):
        return {}
    skipped: Dict[str, str] = {}
    if flags.get("command_protocol_applicable") is False:
        for g in _CLASS_SKIPPABLE_PROTOCOL_GATES:
            skipped[g] = (
                f"N/A for class {ic_class!r}: command_protocol_applicable"
                f"=false (verification_track="
                f"{flags.get('verification_track')!r}). This IC has no "
                f"SW-visible command protocol / opcode argument map / "
                f"protocol behavioral steps, so the protocol gate does "
                f"not apply. Core functional gates (lint/synth/CDC/sim) "
                f"still run.")
    if flags.get("analog_applicable") is False:
        for g in _CLASS_SKIPPABLE_ANALOG_GATES:
            skipped[g] = (
                f"N/A for class {ic_class!r}: analog_applicable=false "
                f"(verification_track={flags.get('verification_track')!r}). "
                f"This IC has no analog content, so the analog "
                f"block-coverage / hardmacro / mixed-signal gate does "
                f"not apply. Core functional gates (lint/synth/CDC/sim) "
                f"still run.")
    # #419 (ORGANIC-20260605-fullstack-byte-oracle-inapplicable-to-
    # datapath-primitive): the full-stack byte-protocol ARTEFACT gates
    # skip ONLY on the DOUBLE key — class says no command protocol AND
    # the L docs positively record a no-opcode/no-regmap input.
    if (flags.get("command_protocol_applicable") is False
            and _ldocs_record_no_opcodes(project)):
        for g in _CLASS_SKIPPABLE_FULLSTACK_ARTEFACT_GATES:
            skipped.setdefault(g, (
                f"N/A for class {ic_class!r}: command_protocol_applicable"
                f"=false AND the L docs record a no-opcode / no-regmap "
                f"input — there are no opcodes to build golden bytes "
                f"from, no register fields, no submodule decomposition, "
                f"no protocol metadata. The primitive-appropriate set "
                f"(generic_full_stack reference TB vs the L9 contract, "
                f"lint, synth, latch checks) still runs and still gates "
                f"(ORGANIC-20260605 #419)."))
    return skipped


# v0.2.55 — pure-analog flow profile. A pure-analog IC (e.g. a stand-
# alone ADC / LDO / bandgap) has NO digital RTL track at all: its
# physical implementation is produced by the analog A1..A9 track, not by
# the digital RTL→synth→PnR→GDS canonical steps. Without a class profile
# the SOLE-ACCEPTANCE gate marks every digital step (stages 1-4) MISSING
# and the whole flow FAILs, even though a pure-analog chip is COMPLETE
# once its analog track signs off. These stages are the digital RTL→GDS
# backend that a pure-analog IC replaces with the analog track. Mixed-
# signal (M1-M4) is also N/A for a single-domain analog IC (no A+D GDS
# merge). chip-AGNOSTIC: keyed off the registry contract, never a name.
_PURE_ANALOG_NA_STAGES: frozenset = frozenset({
    "stage1", "stage2", "stage3", "stage4", "stage_mixed_signal",
})

# Memoization cache keyed by resolved project path (string).
_PURE_ANALOG_CACHE: Dict[str, Tuple[bool, str]] = {}


def _project_is_pure_analog(project: Path) -> Tuple[bool, str]:
    """True when the project's detected IC class is pure-analog with NO
    digital RTL track — so the digital backend stages (1-4) + mixed-
    signal (M1-M4) are N/A and replaced by the analog A1..A9 track.

    Decision is fail-CLOSED and chip-AGNOSTIC:
      - the registry class entry must say analog_applicable=True AND
        rtl_gen=null AND fallback_skill=null (the analog-only signature),
      - AND the project must carry no synthesisable RTL
        (phase2/stage1/rtl/ empty),
      - AND an analog block list must be present (canonical analog dir
        or L5_ADI_SPEC.analog_blocks) so we never misclassify a digital
        project that simply hasn't generated RTL yet.

    Returns (is_pure_analog, reason). Any missing precondition → False.
    """
    key = str(project.resolve())
    if key in _PURE_ANALOG_CACHE:
        return _PURE_ANALOG_CACHE[key]
    result: Tuple[bool, str] = (False, "")
    try:
        # (1) No synthesisable RTL anywhere canonical.
        rtl_present = False
        for cand in ("phase2/stage1/rtl", "rtl", "src", "hdl"):
            d = project / cand
            if d.is_dir() and (any(d.glob("*.sv")) or any(d.glob("*.v"))):
                rtl_present = True
                break
        if rtl_present:
            result = (False, "synthesisable RTL present")
            _PURE_ANALOG_CACHE[key] = result
            return result
        # (2) Registry contract: analog-only class.
        import sys as _sys
        if str(PROGRAMS_DIR) not in _sys.path:
            _sys.path.insert(0, str(PROGRAMS_DIR))
        from ic_class_profile import detect_ic_class as _detect
        profile = _detect(project) or {}
        ic_class = str(profile.get("ic_class") or "unknown")
        config = None
        try:
            reg = json.loads(
                (PROGRAMS_DIR / "ic_class_registry.json").read_text())
            for c in (reg.get("classes") or []):
                if (c.get("name") == ic_class
                        or ic_class in (c.get("synonyms") or [])):
                    config = c
                    break
        except Exception:
            config = None
        analog_only_class = False
        if config is not None:
            analog_only_class = (
                bool(config.get("analog_applicable"))
                and config.get("rtl_gen") is None
                and config.get("fallback_skill") is None)
        elif profile.get("is_pure_analog") and not profile.get("is_pure_digital"):
            analog_only_class = True
        if not analog_only_class:
            result = (False, f"class {ic_class!r} is not analog-only")
            _PURE_ANALOG_CACHE[key] = result
            return result
        # (3) Analog block list must exist (guards against a digital
        # project that merely lacks RTL).
        if not _has_canonical_analog_blocks(project):
            result = (False, "no analog block list — not confirmably analog")
            _PURE_ANALOG_CACHE[key] = result
            return result
        result = (
            True,
            f"pure-analog class {ic_class!r} (analog_applicable=True, "
            f"rtl_gen=null, fallback_skill=null), no digital RTL — digital "
            f"backend (stages 1-4) + mixed-signal replaced by the analog "
            f"A1..A9 track")
    except Exception as e:
        result = (False, f"pure-analog detection unavailable: {e}")
    _PURE_ANALOG_CACHE[key] = result
    return result


def _run_structural_rtl_gates(project: Path,
                              strict_timing: bool = False,
                              allow_thin_input: bool = False
                              ) -> tuple[bool, List[str], List[str], List[Dict[str, Any]]]:
    """v0.104: run all structural-RTL gates on the project's RTL directory.

    Each gate is invoked with the RTL directory as its positional arg.
    Exit 0 = PASS, exit 1 = FAIL, exit 2 = input-missing (skip).
    Returns (all_passed, fail_reasons, skip_reasons, waiver_entries).

    v1.6.97 (issue #29) — when ``allow_thin_input=True`` AND the
    project has fewer than ``THIN_INPUT_DOC_COUNT_THRESHOLD`` input
    docs, FAILs from ``_THIN_INPUT_WAIVER_GATES`` are converted to
    waiver entries (recorded in ``waiver_entries``) instead of fails.
    Other gates' FAILs propagate normally.
    """
    rtl_dir = None
    for candidate in ("phase2/stage1/rtl", "rtl", "src", "hdl"):
        d = project / candidate
        if d.is_dir() and any(d.glob("*.v")) or any(d.glob("*.sv")):
            rtl_dir = d
            break
    if rtl_dir is None:
        if any(project.glob("*.v")) or any(project.glob("*.sv")):
            rtl_dir = project
        else:
            # ORGANIC-20260606 #447: 0/N checkers executed is NOT a PASS.
            # First element None = "not executed" — the caller renders the
            # P0 umbrella as SKIPPED-CONDITION (excluded from executed-PASS
            # counts), never as a PASS that pads a strict verdict.
            return None, [], ["no RTL directory found — structural gates "
                              "skipped (analog track / pre-RTL)"], []

    # Compute thin-input eligibility once. Only matters when the flag
    # is set. v1.6.98: shifted from doc-count to COVERAGE-shape — see
    # _is_thin_input_eligible docstring (issue #30 Bug 2).
    thin_input_eligible = (
        allow_thin_input
        and _is_thin_input_eligible(project)
    )

    fails: List[str] = []
    skips: List[str] = []
    waivers: List[Dict[str, Any]] = []
    # v1.6.523 — class-aware skip-set. Compute once; gates that are N/A
    # for the detected IC class SKIP with an explicit reason instead of
    # FAILing. Fail-closed: empty dict (unknown class) runs every gate.
    class_skips = _class_skipped_gates(project)
    for gate_name in _STRUCTURAL_RTL_GATES:
        prog = PROGRAMS_DIR / f"{gate_name}.py"
        if not prog.exists():
            continue
        if gate_name in class_skips:
            skips.append(f"{gate_name} (SKIP: {class_skips[gate_name]})")
            continue
        try:
            # v0.118 fix: pass `project` (not `rtl_dir`) so gates can
            # access project-level artefacts (generated_docs/L*.json,
            # waivers.json, output_files/, *.qsf). Each gate uses
            # project.rglob for RTL discovery, so giving them the
            # project root finds RTL AND project files. The rtl_dir
            # check above only gates the entire runner ("if no RTL at
            # all, skip the lot").
            argv = [sys.executable, str(prog), str(project)]
            # v1.6.32: forward --strict-timing to the provenance gate
            # only. Other gates don't accept it.
            if strict_timing and gate_name == \
               "provenance_output_hash_completeness_check":
                argv.append("--strict-timing")
            r = subprocess.run(
                argv,
                cwd=project,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            fails.append(f"FAIL: {gate_name} timed out")
            continue
        if r.returncode == 2:
            skips.append(gate_name)
        elif r.returncode == 1:
            first_line = (r.stdout.strip() or r.stderr.strip()).split("\n")[0][:200]
            # v1.6.97 — thin-input waiver eligibility.
            # v1.6.98 — eligibility shifted to coverage-shape; see
            # _is_thin_input_eligible.
            if (thin_input_eligible
                    and gate_name in _THIN_INPUT_WAIVER_GATES):
                waivers.append({
                    "gate": gate_name,
                    "review_required": True,
                    "ticket": _THIN_INPUT_WAIVER_TICKET,
                    "evidence": (
                        "phase1 coverage-shape gap: at least one "
                        "input doc is below 100% capture (per "
                        "phase1_input_vs_generated_completeness."
                        f"json) — {gate_name} cannot pass on such "
                        "projects; converted from FAIL to WAIVED "
                        "via --allow-thin-input"),
                    "reason": (
                        "coverage-shape thin-input (any-doc-<100%-"
                        f"capture, doc count <= {MAX_THICK_DOC_THRESHOLD})"),
                    "first_line": first_line,
                })
            else:
                fails.append(f"FAIL: {gate_name} — {first_line}")

    return (len(fails) == 0), fails, skips, waivers


def _check_json_field_true(project: Path, spec: Dict[str, Any]) -> tuple[bool, str]:
    rel = spec["file"]
    path = project / rel
    field_key = spec["field"]
    expect = spec.get("expect", True)
    if not path.exists() and rel.startswith("reports/"):
        # Subdir fallback (mirrors _glob_first behaviour)
        rest = rel[len("reports/"):]
        for sd in _REPORTS_SUBDIR_FALLBACK:
            cand = project / "reports" / sd / rest
            if cand.exists():
                path = cand
                break
    if not path.exists():
        return False, f"json file missing: {path.name}"
    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        return False, f"json parse error: {exc}"
    # Support dotted keys
    v: Any = data
    for part in field_key.split("."):
        if not isinstance(v, dict) or part not in v:
            return False, f"field not found: {field_key}"
        v = v[part]
    return (v == expect), f"{field_key} = {v!r}"


def _evaluate_gate(project: Path, gate: Dict[str, Any]) -> tuple[bool, List[str]]:
    """Evaluate a gate spec, return (passed, reasons)."""
    reasons: List[str] = []

    # `files_exist` - top-level (any_of / all_of via flag)
    if "files_exist" in gate:
        any_of = gate.get("any_of", False)
        all_of = gate.get("all_of", True) and not any_of
        passed, found, missing = _check_files_exist(
            project, gate["files_exist"], any_of=any_of
        )
        if not passed:
            reasons.append(f"missing files (any_of={any_of}): {missing}")
        return passed, reasons

    # `program_exit_zero` - single command.
    # Accept BOTH the bare-string form ("prog . --args") AND the mapping
    # form ({"command": "prog . --args"}). Some canonical flow steps (e.g.
    # Step 16 Clock planning) author the gate as a YAML mapping with a
    # `command:` key for readability; without this normalization shlex.split
    # would receive a dict and crash the ENTIRE compliance run for every
    # project that reaches such a step (chip-agnostic). This mirrors how
    # `optional_program_exit_zero` already extracts spec["command"].
    if "program_exit_zero" in gate:
        _pez = gate["program_exit_zero"]
        if isinstance(_pez, dict):
            _cmd = _pez.get("command")
            if not _cmd:
                reasons.append("program_exit_zero: mapping form missing `command` key")
                return False, reasons
        else:
            _cmd = _pez
        passed, out = _check_program_exit_zero(project, _cmd)
        if not passed:
            reasons.append(f"program failed: {_cmd}")
            reasons.append(f"output: {out[:200]}")
        elif out.startswith(_VACUOUS_HINT_PREFIX):
            # Wave 93 — bubble the rc=2 vacuous signal up so check_step
            # promotes the step's status to VACUOUS_PASS instead of PASS.
            reasons.append(out)
        return passed, reasons

    # `json_field_true`
    if "json_field_true" in gate:
        passed, out = _check_json_field_true(project, gate["json_field_true"])
        if not passed:
            reasons.append(f"json gate failed: {out}")
        return passed, reasons

    # `optional_program_exit_zero` (added v0.55) — runs a program ONLY
    # when one or more `condition_files_exist` paths exist. Used for
    # gates that apply to a subset of projects (e.g. L10/L12 conformance
    # only when L10/L12 docs exist; FPGA verification audit only when
    # the human report exists). Skipping returns True so the gate
    # doesn't block projects that legitimately don't ship the input.
    if "optional_program_exit_zero" in gate:
        spec = gate["optional_program_exit_zero"]
        if not isinstance(spec, dict):
            reasons.append("optional_program_exit_zero: spec must be a dict")
            return False, reasons
        cmd = spec.get("command")
        cond_files = spec.get("condition_files_exist", [])
        if not cmd:
            reasons.append("optional_program_exit_zero: missing `command`")
            return False, reasons
        if not isinstance(cond_files, list) or not cond_files:
            reasons.append(
                "optional_program_exit_zero: `condition_files_exist` "
                "must be a non-empty list of glob patterns"
            )
            return False, reasons
        # Skip the program if NONE of the condition paths exist.
        present = []
        for pat in cond_files:
            present.extend(project.glob(pat))
        if not present:
            return True, reasons  # no inputs -> N/A -> pass
        passed, out = _check_program_exit_zero(project, cmd)
        if not passed:
            reasons.append(f"optional program failed: {cmd}")
            reasons.append(f"output: {out[:200]}")
        elif _stdout_signals_vacuous(out):
            # Wave 93 — preserve the VACUOUS signal for upstream verdict
            # aggregation. The hint is filtered out before display so the
            # per-step listing only shows real reasons.
            reasons.append(f"{_VACUOUS_HINT_PREFIX}{cmd}")
        return passed, reasons

    # `all_of` - list of sub-gates, all must pass
    if "all_of" in gate and isinstance(gate["all_of"], list):
        # Wave 93 — preserve VACUOUS_HINT reasons from passing sub-gates so
        # the step-level handler can promote a step whose every executed
        # sub-gate was vacuously satisfied.
        for sub in gate["all_of"]:
            if not isinstance(sub, dict):
                continue
            p, r = _evaluate_gate(project, sub)
            if not p:
                reasons.extend(r)
                return False, reasons
            for hint in r:
                if hint.startswith(_VACUOUS_HINT_PREFIX):
                    reasons.append(hint)
        return True, reasons

    # `any_of` - list of sub-gates, any one passes
    if "any_of" in gate and isinstance(gate["any_of"], list):
        for sub in gate["any_of"]:
            if not isinstance(sub, dict):
                continue
            p, _ = _evaluate_gate(project, sub)
            if p:
                return True, reasons
        reasons.append(f"no sub-gate passed in any_of")
        return False, reasons

    reasons.append("gate spec unrecognized")
    return False, reasons


# v1.6.269 (#126) — ENV_UNAVAILABLE step-name → canonical step-id
# mapping. Lets the `waivers` (non-`waived_steps`) entry shape carry
# a free-form `step: "<name>"` string (e.g. `fpga_compile`,
# `fpga_onboard_test`, `drc`, `lvs`) and bind it to the canonical
# step-id used by the flow YAML. Chip-AGNOSTIC: keys are step roles,
# never chip names.
# v2.3 renumber: the map is aligned to the v2.3 flow YAML (PERC
# inserted at 28, DFM at 35, downstream shifted; HTOL at 44). The pre-v2.3 map
# carried off-by-one legacy ids (drc→29 while PV was 30, ir_drop→23
# while IR was 24, …) — fixed wholesale here, single source = the YAML.
_ENV_UNAVAILABLE_STEP_NAME_TO_ID: Dict[str, Any] = {
    "fpga_compile":         6,
    "fpga_early_prototype": 6,
    "fpga_onboard_test":    39,
    "fpga_final_signoff":   39,
    "fpga_signoff":         39,
    "drc":                  31,
    "lvs":                  31,
    "erc":                  31,
    "physical_verification": 31,
    "ir_drop":              24,
    "em":                   25,
    "antenna":              26,
    "si":                   27,
    "signal_integrity":     27,
    "extraction":           22,
    "parasitic_extraction": 22,
    "perc":                 28,
    "esd":                  28,
    "latch_up":             28,
    "reliability_signoff":  28,
    "post_layout_sim":      29,
    "post_layout_spice":    30,
    "metal_fill":           34,
    "dfm":                  35,
    "htol":                 44,
    # v0.2.103 (#496) — analog A-step role-names so a pdk-substitution
    # ENV_UNAVAILABLE waiver (auto-synthesised in `_load_waivers` under
    # the disclosed-substitution predicate, or hand-authored) binds to the
    # canonical A-step ids. The A-step ids are STRING ids ("A3"…) in the
    # flow YAML; the map values mirror that exactly. chip-AGNOSTIC: role
    # names only, never chip-class literals.
    "analog_netlist":          "A3",
    "analog_netlist_gen":      "A3",
    "analog_layout":           "A5",
    "analog_post_layout_resim": "A7",
    "analog_hardmacro":        "A8",
    "analog_cosim":            "A9",
    "mixed_signal_cosim":      "A9",
}


# ── v0.2.103 (#496): analog PDK-substitution waiver path ───────────────────
# When a project's L19 declares a target process with NO public ngspice
# models (e.g. an IHP/TSMC node), the runner's own sizing/netlist decks
# must substitute the open-source default PDK (sky130A / gf180mcuD). The
# (correct) #438b PDK-mismatch gate then honestly intercepts even those
# OWN decks → A3 hard-FAILs with no waiver, no disclosure route, leaving a
# non-default-PDK-target analog chip on the open-source path PERMANENTLY
# unpassable (fabrication forbidden, no waiver exists).
#
# This is the EXACT shape the digital ENV_UNAVAILABLE waivers already
# handle for Quartus/Calibre. We mirror them: under the disclosed-
# substitution predicate, synthesise an ENV_UNAVAILABLE-tier waiver for the
# affected A-steps so `check_step()` downgrades the natural FAIL/MISSING to
# WAIVED-DEFERRED (named reason + ticket + review_required, NOT counted as
# executed-PASS). An UNDISCLOSED mismatch synthesises nothing → hard-FAIL.
#
# Predicate (BOTH must hold):
#   (a) the deck HONESTLY discloses the substitute PDK — a structured
#       `pdk_substitution` marker line in the SPICE deck head that names the
#       substituted open-source PDK family; AND
#   (b) L19 declares the real target AND it differs from the deck's family.
# chip-AGNOSTIC: structural marker + L19 field containment, no chip literals.

# Analog steps that depend on A3's substituted-PDK decks. A4 already has a
# top-level OS-constraints deferral; A3/A5/A7/A8/A9 are added by #496.
_PDK_SUBSTITUTION_AFFECTED_A_STEPS = ("A3", "A5", "A7", "A8", "A9")

_PDK_SUBSTITUTION_TICKET = "pdk-substitution-v0.2.103"

# Structured deck disclosure marker. The deck author writes a comment line
# in the SPICE deck head naming the substitution, e.g.:
#   * pdk_substitution: target=sg13g2 substitute=sky130A reason=no public ngspice models
# Matching is token-based (the literal `pdk_substitution`), case-insensitive.
_PDK_SUBSTITUTION_MARKER_RE = re.compile(
    r"pdk[_\s\-]?substitution", re.IGNORECASE)

# v0.3.2 (#496 round-2) — PROSE disclosure recognition. Real runner decks
# emitted before the structured emitter existed carry a free-text header like:
#   * PDK NOTE (disclosed): tapeout target is IHP SG13G2 (L9/L19) ...
#   * SG13G2 has NO public ngspice corner lib, so the open-source sim deck
#   * uses sky130A typical device models — modeled, NOT silicon sign-off.
# The gate must honour these previously-generated honest artifacts WITHOUT
# regeneration. Recognition predicate for the prose form (ALL must hold):
#   (1) a `PDK NOTE` line is present in the deck head;
#   (2) disclosure / substitute wording is present ("disclosed" or
#       "substitut*"); AND
#   (3) BOTH PDK names are named in the head — the detected substitute family
#       token AND the declared target token — exactly the honesty bar the
#       structured marker enforces. chip-AGNOSTIC: token containment only.
_PDK_NOTE_RE = re.compile(r"pdk\s*note", re.IGNORECASE)
_PDK_NOTE_DISCLOSE_RE = re.compile(r"disclos|substitut", re.IGNORECASE)


def _pdk_substitution_disclosed(project: Path) -> Optional[Dict[str, str]]:
    """Return a disclosure dict {substitute, target, deck} when the project
    HONESTLY discloses that its analog decks substitute the open-source
    default PDK for a non-default L19 target — else None.

    Both halves of the #496 predicate are enforced here. Disclosure is honest
    in EITHER form:
      • STRUCTURED — a `pdk_substitution` marker line whose text names the
        substituted family (the form the emitter now writes); OR
      • PROSE — a `PDK NOTE` header with disclose/substitute wording that
        names BOTH the substitute family and the declared target (the form
        real runner decks already carry — recognised so honest pre-existing
        artifacts pass without regeneration).
    And in both forms:
      (a) at least one analog deck (.sp under the canonical analog dir) carries
          the disclosure in its head AND its detected PDK family is named; AND
      (b) L19.fields.pdk_target is concrete AND the deck's detected family
          token does NOT appear in it (a real mismatch).
    An undisclosed deck (no marker, no prose disclosure) → None → no waiver →
    the #438b gate hard-FAILs. chip-AGNOSTIC: structural marker scan + prose
    family-token containment, no chip-class literals.
    """
    try:
        import analog_netlist_pdk_check as _npc
    except ImportError:
        return None

    declared = _npc._declared_pdk_target(project)
    if not declared:
        return None  # (b) requires L19 to declare a concrete real target

    analog_dir = _pl.analog_dir(project)
    if not analog_dir.is_dir():
        return None
    for sp in sorted(analog_dir.rglob("*.sp")):
        try:
            text = sp.read_text(errors="replace")
        except OSError:
            continue
        head = "\n".join(text.splitlines()[:24])
        pdk = _npc._detect_pdk(text)
        if not pdk:
            continue
        # (b) the deck family must genuinely differ from the declared target.
        if pdk.lower() in declared.lower():
            continue

        # ── STRUCTURED form: a `pdk_substitution` marker naming the family ──
        m = _PDK_SUBSTITUTION_MARKER_RE.search(head)
        if m:
            marker_line = _line_containing(head, m.start())
            # The disclosure must NAME the substituted family it actually uses
            # (so a stray "pdk_substitution: none" cannot game it).
            if pdk.lower() in marker_line.lower():
                return {"substitute": pdk, "target": declared,
                        "deck": str(sp.relative_to(project))}
            # marker present but family not named → fall through to prose check
            # (do not accept on the structured branch alone).

        # ── PROSE form: a `PDK NOTE` header naming BOTH PDKs ──────────────
        # (1) PDK NOTE present; (2) disclose/substitute wording; (3) both the
        # substitute family token AND the declared target token in the head.
        head_lc = head.lower()
        if (_PDK_NOTE_RE.search(head)
                and _PDK_NOTE_DISCLOSE_RE.search(head)
                and pdk.lower() in head_lc
                and declared.lower() in head_lc):
            return {"substitute": pdk, "target": declared,
                    "deck": str(sp.relative_to(project))}
    return None


def _line_containing(text: str, pos: int) -> str:
    ls = text.rfind("\n", 0, pos) + 1
    le = text.find("\n", pos)
    if le < 0:
        le = len(text)
    return text[ls:le]


def _synthesise_pdk_substitution_waivers(
        project: Path, out: Dict[Any, Dict[str, Any]]) -> None:
    """v0.2.103 (#496) — when the disclosed-substitution predicate holds,
    add an ENV_UNAVAILABLE-tier waiver for each affected analog A-step that
    is not already explicitly waived. Mutates `out` in place; mirrors the
    shape of the digital ENV_UNAVAILABLE waivers (reason + ticket +
    review_required + evidence + `_env_unavailable` flag) so `check_step`'s
    existing fallback path converts the natural FAIL/MISSING to
    WAIVED-DEFERRED. No-op when nothing is disclosed (→ undisclosed
    mismatch hard-FAILs as before)."""
    disclosure = _pdk_substitution_disclosed(project)
    if not disclosure:
        return
    for sid in _PDK_SUBSTITUTION_AFFECTED_A_STEPS:
        if sid in out:
            continue  # explicit waiver takes precedence
        rationale = (
            f"PDK_SUBSTITUTION: L19 declares target process "
            f"'{disclosure['target']}' which has no public ngspice models; "
            f"the analog deck ({disclosure['deck']}) HONESTLY discloses it "
            f"substitutes the open-source default PDK '{disclosure['substitute']}'. "
            f"The #438b PDK-mismatch gate correctly intercepts this own-deck "
            f"substitution, so step {sid} is DEFERRED for foundry "
            f"re-characterisation against the real target PDK (not "
            f"executed-PASS)."
        )
        out[sid] = {
            "id": sid,
            "reason": (
                f"ENV_UNAVAILABLE (pdk-substitution): {rationale} "
                f"[ticket={_PDK_SUBSTITUTION_TICKET}, review_required=True]"
            ),
            "approver": "field-agent-attest (pdk-substitution tier)",
            "ticket": _PDK_SUBSTITUTION_TICKET,
            "verdict_tier": "ENV_UNAVAILABLE",
            "review_required": True,
            "evidence": [disclosure["deck"]],
            "_env_unavailable": True,
            "_pdk_substitution": True,
        }


def _load_waivers(project: Path, max_step: int = 40) -> Dict[int, Dict[str, str]]:
    """Load waivers AFTER validating schema. Returns {} if file missing.
    Raises SystemExit(1) if waivers.json exists but is malformed/rubber-stamped."""
    wpath = project / "waivers.json"
    if not wpath.exists():
        # v0.2.103 (#496) — even with no waivers.json, the disclosed
        # PDK-substitution predicate auto-synthesises the A-step deferral
        # waivers so a non-default-target analog chip on the open path is
        # not permanently unpassable. An UNDISCLOSED mismatch → {} → FAIL.
        out: Dict[Any, Dict[str, Any]] = {}
        _synthesise_pdk_substitution_waivers(project, out)
        return out
    # Reuse waivers_schema_check for validation
    try:
        from waivers_schema_check import validate as _validate
        findings, _ = _validate(project, max_step=max_step)
        errors = [f for f in findings if f.severity == "error"]
        if errors:
            print(
                f"flow_compliance_check: {len(errors)} schema error(s) in "
                f"{wpath}:", file=sys.stderr,
            )
            for f in errors:
                print(f"  step {f.step_id} / entry {f.entry_index}: "
                      f"{f.rule} — {f.message}", file=sys.stderr)
            print("flow_compliance_check: waivers invalid → cannot continue. "
                  "Fix waivers.json or remove it.", file=sys.stderr)
            raise SystemExit(1)
    except ImportError:
        # fallback: load without validation (will warn in output)
        print("flow_compliance_check: waivers_schema_check.py unavailable — "
              "loading waivers without schema validation", file=sys.stderr)
    try:
        data = json.loads(wpath.read_text())
        def _parse_id(v):
            try:
                return int(v)
            except (ValueError, TypeError):
                return str(v)
        # v0.112 (BACKLOG-v10 P0.2): cascade auto-propagation. A waiver
        # entry with `cascades_to: [<step_id>, ...]` is the ROOT; each
        # listed step inherits a synthetic waiver pointing back to the
        # root. This collapses N+1 manually-duplicated entries to 1.
        out: Dict[Any, Dict[str, Any]] = {}
        for w in data.get("waived_steps", []):
            root_id = _parse_id(w["id"])
            # ORGANIC-20260606 #437(e): waiver authors use `rationale` and
            # `reason` interchangeably, but every consumer read ONLY
            # `reason` — a valid rationale-keyed waiver then displayed as
            # "(no reason)" and was counted invalid. Normalize once here.
            if not w.get("reason") and w.get("rationale"):
                w = {**w, "reason": w["rationale"]}
            out[root_id] = w
            for child in w.get("cascades_to", []) or []:
                child_id = _parse_id(child)
                if child_id in out:
                    continue  # explicit child entry takes precedence
                out[child_id] = {
                    **w,
                    "id": child_id,
                    "cascade_source": root_id,
                    "reason": (f"cascaded from waiver {root_id}: "
                               f"{w.get('reason', '(no reason)')}"),
                }
        # v1.6.269 (#126) — ENV_UNAVAILABLE waiver shape. Some projects
        # (notably the v106267 / phase23_one_shot_runner-emitted shape)
        # use a top-level `waivers` array whose entries carry
        # `step: "<role-name>"` + `verdict_tier: "ENV_UNAVAILABLE"`
        # + `ticket` + `review_required: true` + `evidence: [...]`.
        # These are the canonical ENV_UNAVAILABLE waivers documented in
        # GH issue #126 (Quartus / Calibre / commercial tool not on
        # host). Bind them to the canonical step-id via the
        # _ENV_UNAVAILABLE_STEP_NAME_TO_ID map so subsequent
        # check_step() sees them as a WAIVED step.
        # Chip-AGNOSTIC: only role-name strings, never chip-specific.
        # We accept an entry IFF every required attestation field is
        # present: ticket, review_required=true, evidence[] non-empty,
        # rationale string. Missing any → entry is skipped (a future
        # waivers_schema_check.py pass will surface the omission), and
        # the step will FAIL normally. This is the "missing the waiver
        # entry still FAILs" half of the contract.
        for w in data.get("waivers", []) or []:
            if not isinstance(w, dict):
                continue
            tier = (w.get("verdict_tier") or "").strip().upper()
            if tier != "ENV_UNAVAILABLE":
                continue
            step_name = (w.get("step") or "").strip().lower()
            sid = _ENV_UNAVAILABLE_STEP_NAME_TO_ID.get(step_name)
            if sid is None:
                continue
            # Required attestation fields
            ticket = w.get("ticket")
            reviewer_required = w.get("review_required") is True
            evidence = w.get("evidence") or []
            rationale = (w.get("rationale") or "").strip()
            if not (isinstance(ticket, str) and ticket
                    and reviewer_required
                    and isinstance(evidence, list) and evidence
                    and len(rationale) >= 40):
                continue
            if sid in out:
                continue  # explicit waived_steps entry takes precedence
            out[sid] = {
                "id": sid,
                "reason": (
                    f"ENV_UNAVAILABLE: {rationale[:200]} "
                    f"[ticket={ticket}, review_required={reviewer_required}]"
                ),
                "approver": w.get("approver",
                                  "field-agent-attest (ENV_UNAVAILABLE tier)"),
                "ticket": ticket,
                "verdict_tier": tier,
                "review_required": reviewer_required,
                "evidence": evidence,
                "_env_unavailable": True,
            }
        # v0.2.103 (#496) — auto-synthesise the analog PDK-substitution
        # deferral waivers (no-op when nothing is disclosed). Runs after
        # explicit waivers so hand-authored A-step entries take precedence.
        _synthesise_pdk_substitution_waivers(project, out)
        return out
    except Exception as exc:
        print(f"flow_compliance_check: cannot parse {wpath}: {exc}",
              file=sys.stderr)
        raise SystemExit(1)


def _check_condition(project: Path, condition: Dict[str, Any]) -> bool:
    """Evaluate a step condition (e.g. files_exist). Returns True if step should run."""
    if not condition:
        return True
    # v0.113 (BACKLOG-v10 P1.1): auto-trigger A1-A8 from L9 analog_modules.
    # If condition lists `analog/analog_block_list.json` and that file is
    # absent, look at L9_INTEGRATION_SPEC.json for an `analog_modules`
    # array. If present, the condition is satisfied without requiring
    # the agent to author the redundant trigger file.
    files = condition.get("files_exist", [])
    if files:
        for pat in files:
            if _glob_first(project, pat):
                continue
            # Auto-derive analog block list from L9 if requested
            if "analog_block_list" in pat:
                if _l9_has_analog_modules(project):
                    continue
                # v0.2.55 — canonical-path tolerance. The analog runner
                # writes the block list to the canonical analog dir
                # (`_pl.analog_dir` = phase3/analog/), but the flow-def
                # condition historically pins `phase1/analog/`. Accept the
                # canonical location too, and fall back to L5_ADI_SPEC's
                # `analog_blocks` array (Phase-1 doc-extraction emits it).
                # chip-AGNOSTIC: existence of an analog block list anywhere
                # canonical, never a chip name.
                if _has_canonical_analog_blocks(project):
                    continue
            return False
    return True


def _has_canonical_analog_blocks(project: Path) -> bool:
    """v0.2.55 — True if the project has an analog block list at the
    canonical analog dir (`_pl.analog_dir`, i.e. phase3/analog/) OR the
    Phase-1 L5_ADI_SPEC.json declares a non-empty `analog_blocks` array.

    Closes the path drift between the analog runner (writes
    phase3/analog/analog_block_list.json) and the flow-def condition
    (pins phase1/analog/analog_block_list.json). chip-AGNOSTIC."""
    try:
        bl = _pl.analog_dir(project) / "analog_block_list.json"
        if bl.is_file():
            d = json.loads(bl.read_text())
            blocks = d.get("blocks") or d.get("analog_blocks")
            if isinstance(blocks, list) and len(blocks) > 0:
                return True
    except Exception:
        pass
    for cand in (_pl.generated_docs_dir(project) / "L5_ADI_SPEC.json",
                 project / "phase1/generated_docs/L5_ADI_SPEC.json"):
        try:
            if not cand.is_file():
                continue
            d = json.loads(cand.read_text())
            if d.get("no_analog") is True:
                continue
            blocks = d.get("analog_blocks") or d.get("blocks")
            if isinstance(blocks, list) and len(blocks) > 0:
                return True
        except Exception:
            continue
    return False


def _l9_has_analog_modules(project: Path) -> bool:
    """v0.113 P1.1 helper: True if L9_INTEGRATION_SPEC.json declares any
    analog modules. Lets A1-A8 unblock without manually authoring
    analog/analog_block_list.json."""
    candidates = [ project / "phase1/generated_docs", _pl.generated_docs_dir(project) / "L9_INTEGRATION_SPEC.json", project / "phase1/generated_docs", _pl.generated_docs_dir(project) / "L9.json",
    ]
    for p in candidates:
        if not p.exists():
            continue
        try:
            d = json.loads(p.read_text())
        except Exception:
            continue
        am = d.get("analog_modules") or d.get("analog_blocks")
        if isinstance(am, list) and len(am) > 0:
            return True
    return False


# v0.2.63 — ORGANIC-20260606-runner-missing-canonical-steps (#430).
# Canonical flow steps the open-tool runner chain DOES NOT implement yet,
# each with its NAMED capability flag. Scope: digital backend steps whose
# tooling (scan insertion + ATPG, post-DFT re-opt, LEC, post-layout SPICE
# correlation) is not wired into phase2/phase3 runners — a clean full-chain
# digital run can therefore never produce their evidence regardless of
# design quality. Step 18 (spare-cell/ECO-prep) is NOT listed: the runner
# emits its evidence chain (v0.2.60), so it gates normally. chip-AGNOSTIC:
# keyed on canonical step id, never on a chip/class literal.
#
# v0.2.67 (#437d) — step 28 added: the runner emits the SDF (write_sdf)
# but never RUNS an SDF-annotated gate-level re-sim; it used to fabricate
# `sim_postlayout/pass.flag` from "RTL TB PASS + post-route TNS=0", which
# is an RTL-sim approximation, not gate-level timing sim. The runner now
# emits an honest `sdf_sim_skipped.json` self-report instead, so a clean
# run leaves step 28's required outputs absent → SKIPPED-CONDITION here.
# A REAL SDF-annotated sim (results.log referencing $sdf_annotate) still
# gates normally via post_layout_sim_check.
# v0.2.73 (#440) — step 5 added: no formal proof engine is wired into
# the phase2 runner; the old shape emitted a placeholder .sby (targeting
# nonexistent files) + a results.json whose all_proved derived from the
# SIM verdict. The runner now emits only formal_not_run.json (with the
# assertion-gen fallback direction), so a run without a real SymbiYosys
# proof leaves step 5's required outputs absent → SKIPPED-CONDITION
# here. A real proof (authored .sby + sby log + results.json) still
# gates normally.
# v2.3 renumber: PERC inserted at 28 → SDF-sim is 29, SPICE-corr 30.
_PLATFORM_CAPABILITY_GAPS: Dict[int, str] = {
    5:  "cap:formal_property_proof",
    11: "cap:dft_scan_insertion_atpg",
    12: "cap:post_dft_optimization",
    13: "cap:logic_equivalence_check",
    29: "cap:sdf_annotated_gatelevel_sim",
    30: "cap:post_layout_spice_correlation",
}


# v0.2.64 — ORGANIC-20260606 #433/#434 evidence-integrity scan.
# A PASS that nothing substantiates is not a PASS:
#   * #434: evidence content tagged `deterministic_stub` / `low_confidence`
#     is DEFERRED work — the step downgrades to WAIVED (review_required),
#     which excludes it from strict PASS (headline becomes
#     PASS_WITH_WAIVERS at best). The strict verdict is otherwise gameable
#     by emitting tagged stubs.
#   * #433(b): a verdict-shaped artifact whose `evidence` POINTER names a
#     file that does not exist or is empty (the broken
#     `sim/reference_tb/ref_tb.log` chain seen in all four campaign
#     projects) downgrades to FAIL EVIDENCE_MISSING. Prose evidence notes
#     (no path separator) are not dereferenced.
#   * a verdict artifact may honestly SELF-REPORT "SKIPPED-CONDITION"
#     (e.g. the formal step when no proof tool ran) — the step then
#     reports SKIPPED-CONDITION instead of a fabricated PASS.
# chip-AGNOSTIC: tag / structure scan only, no chip-class literals.
_STUB_TAG_RE = re.compile(
    r'deterministic_stub|"low_confidence"\s*:\s*true|low_confidence=true',
    re.IGNORECASE)


def _evidence_integrity_scan(project: Path,
                             result: "StepResult") -> "StepResult":
    if result.status != "PASS" or not result.evidence:
        return result
    stub_hits: List[str] = []
    broken: List[str] = []
    self_skipped: List[str] = []
    for rel in list(result.evidence):
        rel_s = str(rel)
        p = Path(rel_s) if rel_s.startswith("/") else project / rel_s
        try:
            if p.stat().st_size == 0:
                broken.append(f"{rel} (0 bytes)")
                continue
            txt = p.read_text(errors="replace")[:8000]
        except OSError:
            continue  # non-text / vanished: out of scope for this scan
        if _STUB_TAG_RE.search(txt):
            stub_hits.append(str(rel))
            continue
        if '"verdict"' in txt:
            try:
                d = json.loads(txt)
            except ValueError:
                d = None
            if isinstance(d, dict):
                if str(d.get("verdict", "")).upper().replace("_", "-") \
                        == "SKIPPED-CONDITION":
                    self_skipped.append(
                        f"{rel}: {str(d.get('reason', ''))[:160]}")
                    continue
                ev_ptr = d.get("evidence")
                if isinstance(ev_ptr, str) and "/" in ev_ptr:
                    tgt = project / ev_ptr
                    if not tgt.is_file() or tgt.stat().st_size == 0:
                        broken.append(
                            f"{rel} → evidence '{ev_ptr}' missing/empty")
    if broken:
        result.status = "FAIL"
        result.reasons.append(
            "EVIDENCE_MISSING (#433): verdict artifact(s) reference "
            "evidence that does not exist or is empty — a PASS nothing "
            "substantiates is not a PASS: " + "; ".join(broken[:4]))
    elif stub_hits:
        result.status = "WAIVED"
        result.reasons.append(
            "stub-backed (#434, review_required): evidence tagged "
            "deterministic_stub/low_confidence is DEFERRED work, not "
            "executed verification — excluded from strict PASS: "
            + "; ".join(stub_hits[:4]))
    elif self_skipped:
        result.status = "SKIPPED-CONDITION"
        result.reasons.append(
            "verdict artifact self-reports SKIPPED-CONDITION (#433c): "
            + "; ".join(self_skipped[:3]))
    return result


def _apply_capability_gap(result: "StepResult", sid) -> "StepResult":
    """#430 — convert a would-be-MISSING verdict on a capability-gap step
    to SKIPPED-CONDITION with the NAMED flag. Applied at EVERY MISSING
    exit of check_step (the early required_outputs return included) so the
    conversion is never silently skipped; evidence-backed verdicts are
    untouched."""
    if (result.status == "MISSING" and isinstance(sid, int)
            and sid in _PLATFORM_CAPABILITY_GAPS):
        flag = _PLATFORM_CAPABILITY_GAPS[sid]
        result.status = "SKIPPED-CONDITION"
        result.reasons.append(
            f"platform capability gap [{flag}]: the open-tool runner "
            f"chain does not implement this canonical step yet (#430); "
            f"converted from MISSING so every strict deduction names its "
            f"capability flag. Track/implement under this flag to "
            f"re-enable gating.")
    return result


def check_step(project: Path, step: Dict[str, Any], waivers: Dict,
               skip_analog: bool = False, skip_hardware: bool = False) -> StepResult:
    raw_id = step["id"]
    try:
        sid = int(raw_id)
    except (ValueError, TypeError):
        sid = str(raw_id)

    result = StepResult(
        id=sid,
        name=step.get("name", ""),
        stage=step.get("stage", ""),
        status="MISSING",
    )

    if skip_analog and isinstance(sid, str) and sid.startswith("A"):
        result.status = "SKIPPED-CONDITION"
        result.reasons.append("analog track skipped via --skip-analog")
        return result

    # v0.2.55 — --skip-hardware: the two FPGA-board steps (6 = early-prototype
    # SOF, 37 = final on-board sign-off) require a physical FPGA (DE10-Lite-
    # class) attached. A pure doc→GDS run launched with --skip-hardware (the
    # documented headless flow) cannot produce a .sof or run an on-board test,
    # so these steps FAILed unconditionally with no way to honor the run mode.
    # Mirror --skip-analog: downgrade them to WAIVED (review_required at
    # foundry/board-bringup time). All OTHER steps still gate normally — the
    # GDS, STA, DRC, LVS sign-off is unaffected. chip-AGNOSTIC.
    if skip_hardware and isinstance(sid, int) and sid in (6, 37):
        result.status = "WAIVED"
        result.reasons.append(
            "FPGA-board step waived via --skip-hardware: no physical FPGA "
            "attached for a headless doc→GDS run (review_required at "
            "board-bringup; GDS/STA/DRC/LVS sign-off unaffected)")
        return result

    # v0.2.55 — pure-analog flow profile. For a pure-analog IC (no digital
    # RTL track), the digital backend stages (stage1-4) and mixed-signal
    # (M1-M4) are N/A; the analog A1..A9 track produces the silicon. Mark
    # those steps SKIPPED-CONDITION with a class-N/A reason instead of
    # MISSING (which would fail the SOLE-ACCEPTANCE gate). The analog
    # A-steps + D1 doc-completeness + manufacturing steps still gate.
    # chip-AGNOSTIC + fail-closed (see _project_is_pure_analog).
    step_stage = step.get("stage", "")
    if step_stage in _PURE_ANALOG_NA_STAGES:
        is_pa, pa_reason = _project_is_pure_analog(project)
        if is_pa:
            result.status = "SKIPPED-CONDITION"
            result.reasons.append(
                f"N/A for pure-analog IC: stage {step_stage!r} is the "
                f"digital RTL→GDS backend — {pa_reason}.")
            return result

    condition = step.get("condition")
    if condition and not _check_condition(project, condition):
        # v0.114 (BACKLOG-v10 P1.5): two-kind condition handling.
        #   condition_kind: design_dependent → silent skip (default;
        #     analog A1-A8 for digital-only IC, etc.). False-positive
        #     guard: this is the conservative default — never alarms.
        #   condition_kind: setup_required → setup-mistake skip; the
        #     trigger SHOULD have been authored. Reports as
        #     SKIPPED-SETUP-REQUIRED unless an explicit waiver exists.
        kind = step.get("condition_kind", "design_dependent")
        if kind == "setup_required" and sid not in waivers:
            result.status = "SKIPPED-SETUP-REQUIRED"
            result.reasons.append(
                f"condition not met: {condition} — step is marked "
                f"`setup_required` but no waiver exists. Either author "
                f"the trigger artefact or add a waiver to "
                f"<project>/waivers.json with explicit justification."
            )
        else:
            result.status = "SKIPPED-CONDITION"
            result.reasons.append(f"condition not met: {condition}")
        return result

    # v1.6.269 (#126) — ENV_UNAVAILABLE-tier waivers are "fallback"
    # waivers: they only apply if the step would otherwise FAIL or
    # MISSING. If the step can produce its own PASS evidence (e.g.
    # the SOF + on-board verdict was created on a host that DID have
    # Quartus), the original PASS wins. Legacy waived_steps waivers
    # without `_env_unavailable` keep the historical short-circuit
    # behaviour (always WAIVED).
    if sid in waivers:
        is_env_unavailable = bool(waivers[sid].get("_env_unavailable"))
        if not is_env_unavailable:
            result.status = "WAIVED"
            result.reasons.append(
                f"waived: {waivers[sid].get('reason', '(no reason)')}"
                f" (approver: {waivers[sid].get('approver', '?')})"
            )
            return result
        # ENV_UNAVAILABLE: fall through; only convert to WAIVED-DEFERRED
        # at the very end if the natural verdict would be FAIL or
        # MISSING. Continue into the normal evidence + gate path.

    # First check required_outputs presence (cheap)
    outputs = step.get("required_outputs", [])
    for pat in outputs:
        # split "A OR B"
        hit_any = False
        for sp in (p.strip() for p in pat.split(" OR ")):
            if _glob_first(project, sp):
                hit_any = True
                break
        if hit_any:
            # record evidence
            for sp in (p.strip() for p in pat.split(" OR ")):
                for h in _glob_first(project, sp):
                    result.evidence.append(h)
                    break

    if outputs and not result.evidence:
        result.status = "MISSING"
        result.reasons.append(f"no required_outputs found (expected: {outputs})")
        # v1.6.269 (#126) — ENV_UNAVAILABLE fallback at early MISSING.
        if sid in waivers and bool(waivers[sid].get("_env_unavailable")):
            natural_reason = result.reasons[-1] if result.reasons else "MISSING"
            result.status = "WAIVED"
            result.reasons = [
                f"ENV_UNAVAILABLE waiver applied (required artefact "
                f"absent because tool not on host): "
                f"{waivers[sid].get('reason', '(no reason)')} "
                f"(approver: {waivers[sid].get('approver', '?')})",
                f"  ↳ natural: {natural_reason}",
            ]
        return _apply_capability_gap(
            _evidence_integrity_scan(project, result), sid)

    # Now evaluate the gate predicate
    gate = step.get("gate")

    # ── ORGANIC-20260606 #470 DEFENSE: gate-promotion safety net ──────────
    # A hand-authoring slip can place a gate-shaped predicate block (all_of /
    # any_of / program_exit_zero / optional_program_exit_zero / files_exist)
    # at the STEP level — a sibling of `gate:` — instead of nested inside it.
    # When that happens, `step.get("gate")` returns None, the whole gate
    # silently becomes DEAD CODE, and the step degrades to "outputs present →
    # PASS" (effectively any-of-one of its required_outputs). For a sign-off
    # step (e.g. Step 31 PV: DRC+LVS+ERC+Density) that means a run with NO
    # DRC sign-off, NO ERC report and a verdict-less LVS log would PASS the
    # most safety-critical gate. The structural fix lives in the flow YAML and
    # is regression-guarded by a meta-test, but a future hand-slip must NEVER
    # silently void a whole gate again — so PROMOTE any stray predicate keys
    # carried directly on the step node into the gate dict here, and emit a
    # visible WARNING finding so the authoring slip is surfaced, not hidden.
    _GATE_PREDICATE_KEYS = (
        "all_of", "any_of", "program_exit_zero",
        "optional_program_exit_zero", "files_exist", "json_field_true",
    )
    if not gate:
        _stray = {k: step[k] for k in _GATE_PREDICATE_KEYS if k in step}
        if _stray:
            gate = _stray
            result.reasons.append(
                "WARNING: gate-shaped predicate key(s) "
                f"{sorted(_stray.keys())} found at the STEP level instead of "
                "inside `gate:` — promoting them into the gate so the sign-off "
                "predicates execute. FIX THE FLOW YAML: nest them under "
                "`gate:` (authoring slip; a meta-test guards against "
                "regression). [ORGANIC-20260606 #470]"
            )

    if gate:
        passed, reasons = _evaluate_gate(project, gate)
        # Wave 93 — VACUOUS_PASS verdict tier promotion. If the gate
        # passed AND every reason carries the __VACUOUS_HINT__ marker
        # (and at least one was emitted), the step ran but every
        # executed sub-gate was vacuously satisfied (its audited input
        # didn't apply to this project). Surface that as VACUOUS_PASS
        # so the per-step listing labels it explicitly. Filter out the
        # internal markers before display either way.
        vacuous_hints = [r for r in reasons
                         if r.startswith(_VACUOUS_HINT_PREFIX)]
        non_vacuous_reasons = [r for r in reasons
                               if not r.startswith(_VACUOUS_HINT_PREFIX)]
        if passed and vacuous_hints and not non_vacuous_reasons:
            result.status = "VACUOUS_PASS"
            for h in vacuous_hints:
                # Strip the internal prefix; surface a human-friendly
                # diagnostic so reviewers see *why* it was vacuous.
                cmd = h[len(_VACUOUS_HINT_PREFIX):]
                result.reasons.append(
                    f"vacuous: gate program signalled VACUOUS_PASS "
                    f"(input not applicable): {cmd}"
                )
        else:
            result.status = "PASS" if passed else "FAIL"
            result.reasons.extend(non_vacuous_reasons)
    else:
        # No gate — just presence of outputs counts
        result.status = "PASS" if result.evidence else "MISSING"

    # v1.6.269 (#126) — ENV_UNAVAILABLE fallback promotion. If the
    # natural verdict is FAIL or MISSING AND an ENV_UNAVAILABLE-tier
    # waiver matches this step, convert to WAIVED-DEFERRED. The
    # waiver entry carries ticket + review_required=true so foundry
    # tapeout review must still close it before production. The PASS
    # path is NOT touched — a real evidence + gate-PASS keeps PASS.
    if (result.status in ("FAIL", "MISSING")
            and sid in waivers
            and bool(waivers[sid].get("_env_unavailable"))):
        original_reasons = list(result.reasons)
        result.status = "WAIVED"
        result.reasons = [
            f"ENV_UNAVAILABLE waiver applied (natural verdict was "
            f"{original_reasons and 'FAIL/MISSING' or 'FAIL/MISSING'}): "
            f"{waivers[sid].get('reason', '(no reason)')} "
            f"(approver: {waivers[sid].get('approver', '?')})"
        ]
        # Preserve original natural reasons as breadcrumb for audit.
        for r in original_reasons[:3]:
            result.reasons.append(f"  ↳ natural: {r}")

    # v0.2.64 (#433/#434) — evidence-integrity scan on the natural PASS,
    # then v0.2.63 (#430) capability-gap conversion (the early
    # required_outputs exit applies the same helpers).
    result = _evidence_integrity_scan(project, result)
    return _apply_capability_gap(result, sid)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument("project_dir", nargs="?",
                   help="Project directory to audit (omit when using "
                        "--list-structural-gates)")
    p.add_argument("--flow", default="phase1_phase2_phase3", help="Flow name (default: phase1_phase2_phase3)")
    p.add_argument("--flow-def", help="Override path to flow YAML")
    p.add_argument("--strict", action="store_true", help="Strict mode (default). Non-waived MISSING/FAIL → exit 1.")
    p.add_argument("--lenient", action="store_true", help="Lenient mode: MISSING → WARN, only gate FAIL fails.")
    p.add_argument("--stage", type=int, choices=[1, 2, 3, 4],
                   help="Only check steps belonging to this stage (for interim gating).")
    p.add_argument(
        "--skip-yosys-gates", action="store_true",
        help=("v0.70: disable the pre-PnR Yosys auditor gate "
              "(yosys_hilomap_required_check + yosys_script_template_check). "
              "Intended for sim-only flows that never reach PnR. Mirrors "
              "yosys_script_template_check.py's --simulation-only escape "
              "hatch."),
    )
    p.add_argument(
        "--skip-analog", action="store_true",
        help=("v0.108: skip analog track steps (A1-A8). Intended for "
              "pure-digital ICs that have no analog blocks."),
    )
    p.add_argument(
        "--skip-hardware", action="store_true",
        help=("v0.2.55: waive the two FPGA-board steps (6 early-prototype "
              "SOF, 37 final on-board sign-off) for a headless doc→GDS run "
              "with no physical FPGA attached. Mirrors the runner's "
              "--skip-hardware. GDS/STA/DRC/LVS sign-off is unaffected."),
    )
    p.add_argument(
        "--phase", choices=["2", "3", "all"],
        default="all",
        help=("v0.119.29: limit step set to a single phase. `--phase 2` "
              "scopes to steps 1-6 (Phase-2 docs + RTL + sim + FPGA "
              "compile + burn) and treats Phase-3 steps (7-40) as "
              "OUT-OF-SCOPE rather than MISSING — closes the "
              "vendor-benchmark complaint that legitimate Phase-2-only "
              "runs were forced to FAIL because Phase-3 sign-off steps "
              "were absent. `--phase 3` does the inverse (Phase-2 "
              "OUT-OF-SCOPE). `--phase all` is the default."),
    )
    p.add_argument("--json", help="Write JSON report to this path")
    p.add_argument(
        "--strict-structural", action="store_true",
        help=("v0.119.53 (Wave 21) — semantic fix: when --phase 2 is "
              "also set, the verdict is decided ONLY by gates registered "
              "in `_STRUCTURAL_RTL_GATES` (the chip-AGNOSTIC pattern "
              "checkers). Step-level verdicts that need real EDA tool "
              "harnesses (lint coverage, CDC report, Verilator coverage, "
              "SymbiYosys formal proof, post-route STA, etc.) are "
              "REPORTED but NOT factored into Overall. ANY structural-"
              "RTL gate FAIL still propagates to Overall: FAIL with each "
              "failing gate listed by name. Closes the v0.119.52 26th-"
              "attempt complaint that `--strict-structural` rejected a "
              "structurally-clean Phase-2 project because step-level "
              "EDA artefacts were incomplete. For the broader gate "
              "(real EDA tool artefacts), use --strict-step-artifacts. "
              "Honors per-gate waivers; existing --strict callers "
              "without --phase 2 see NO behaviour change."),
    )
    p.add_argument(
        "--strict-step-artifacts", action="store_true",
        help=("v0.119.53 (Wave 21) — broader gate: when --phase 2 is "
              "also set, EVERY phase-2 step (1-6) plus the structural-"
              "RTL gate set must PASS. Step-level MISSING/FAIL "
              "(missing lint report, missing CDC report, missing "
              "Verilator coverage, missing formal proof, etc.) "
              "propagates to Overall: FAIL. Use this for tape-out-"
              "ready audits where real EDA tool artefacts are "
              "expected. --strict-structural is the looser variant "
              "that scopes the verdict to chip-AGNOSTIC structural "
              "gates only."),
    )
    p.add_argument(
        "--strict-timing", action="store_true",
        help=("v1.6.32: forward --strict-timing to "
              "provenance_output_hash_completeness_check so that the "
              "ATTEST_TIMING_SUSPICIOUS warning becomes a fatal "
              "ERROR. Useful for tape-out-ready audits where "
              "synthetic-timestamp patterns must not pass."),
    )
    p.add_argument(
        "--strict-no-os-constraints", action="store_true",
        help=("v1.6.210 (#91) — disable the "
              "PASS_WITH_OPEN_SOURCE_CONSTRAINTS promotion. By default, "
              "when the only failing/missing steps are ones whose "
              "required tools are not present in iic-osic-tools (e.g. "
              "DFT / EM / SI / SPICE-PV / M1-M4 mixed-signal) AND the "
              "chip is engineering-complete (Step 6 + Step 36 PASS), "
              "the verdict promotes to a distinct tier carrying a "
              "structured deferral list with review_required=true. "
              "Pass this flag for tape-out-ready audits where every "
              "step must run on real EDA tools."),
    )
    p.add_argument(
        "--allow-thin-input", action="store_true",
        help=("v1.6.97 (issue #29 Bugs 1+2), v1.6.98 (issue #30 Bug "
              "2 — coverage-shape eligibility) — convert FAILs from "
              "the extractor-coverage gates "
              "(phase1_doc_input_completeness_check, "
              "l_doc_structured_field_count_check) to WAIVED entries "
              "when the project shows a coverage-shape gap (any input "
              "doc below 100%% capture per phase1_input_vs_generated_"
              "completeness.json) AND the input doc count is <= "
              f"{MAX_THICK_DOC_THRESHOLD} (anti-gaming floor). Falls "
              "back to the legacy doc-count predicate (count < "
              f"{THIN_INPUT_DOC_COUNT_THRESHOLD}) when the "
              "completeness report is missing. Other gates' FAILs "
              "are NOT waived; projects with full coverage STAY FAIL "
              "on the same gates because those failures are real "
              "bugs, not thin-input artefacts. Each waiver entry is "
              "recorded with review_required=true and ticket="
              f"{_THIN_INPUT_WAIVER_TICKET}; foundry tape-out review "
              "must close them before production."),
    )
    p.add_argument(
        "--list-structural-gates", action="store_true",
        help=("v0.119.24: print the full _STRUCTURAL_RTL_GATES tuple "
              "(every gate the P0 umbrella runs) to stdout and exit. "
              "Use this to discover which structural gates exist before "
              "starting Phase 2 — closes the vendor-benchmark complaint "
              "that real-bug-catching gates like fpga_pad_fanout_check "
              "weren't visible in the brief."),
    )
    args = p.parse_args(argv)

    if args.list_structural_gates:
        print(f"# {len(_STRUCTURAL_RTL_GATES)} structural-RTL gates "
              "registered in flow_compliance_check (P0 umbrella):")
        for g in _STRUCTURAL_RTL_GATES:
            print(g)
        return 0

    if not args.project_dir:
        print("flow_compliance_check: project_dir is required "
              "(or pass --list-structural-gates)", file=sys.stderr)
        return 2

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"flow_compliance_check: not a directory: {project}", file=sys.stderr)
        return 2

    flow_path = Path(args.flow_def) if args.flow_def else DEFAULT_FLOW_DEF
    if not flow_path.exists():
        print(f"flow_compliance_check: flow def not found: {flow_path}", file=sys.stderr)
        return 2

    try:
        flow = yaml.safe_load(flow_path.read_text())
    except yaml.YAMLError as exc:
        print(f"flow_compliance_check: YAML parse error: {exc}", file=sys.stderr)
        return 2

    steps = flow.get("steps", [])
    if not steps:
        print("flow_compliance_check: flow has no steps defined", file=sys.stderr)
        return 2

    # Apply --stage filter if requested.
    if args.stage is not None:
        target_stage = f"stage{args.stage}"
        steps = [s for s in steps if s.get("stage") == target_stage]
        if not steps:
            print(f"flow_compliance_check: no steps for {target_stage}", file=sys.stderr)
            return 2

    # v0.119.29: --phase filter via canonical step-ID ranges. The flow
    # YAML doesn't tag steps with a phase keyword, but the conventional
    # split is Phase 2 = steps 1-6 (Spec-to-RTL through FPGA early
    # prototype + verification report audit) and Phase 3 = steps 7-40
    # (constraints through tapeout sign-off + manufacturing).
    # String IDs (`stage1`, `stage_analog`, etc.) and analog `A*` /
    # mixed-signal `M*` / preflight `P0` are phase-agnostic and kept.
    # Closes the v0.119.27 vendor complaint that Phase-2-only runs were
    # forced to FAIL because Phase-3 sign-off steps showed up as MISSING.
    # v1.6.15 Wave 91: phase-3 cap raised 39 → 40 (pre-PnR Yosys gate
    # promoted to Step 14, stage3-5 cascade +1).
    if args.phase != "all":
        phase_range = (1, 6) if args.phase == "2" else (7, 40)
        kept = []
        for s in steps:
            sid = s.get("id")
            if isinstance(sid, int):
                if phase_range[0] <= sid <= phase_range[1]:
                    kept.append(s)
            else:
                # Non-integer id (stage* / A*) — phase-agnostic, keep.
                kept.append(s)
        steps = kept
        if not steps:
            print(f"flow_compliance_check: no steps for phase {args.phase}",
                  file=sys.stderr)
            return 2

    waivers = _load_waivers(project)

    # ------------------------------------------------------------------
    # v0.70 Item 1 — Pre-PnR Yosys auditor gate.
    #
    # Runs yosys_hilomap_required_check + yosys_script_template_check
    # against the first .ys file found in the project. Both auditors
    # were shipped in v0.69 as CLI-only helpers; v0.70 wires them into
    # the canonical phase 2+3 flow so a PnR stage can't proceed when
    # the synth script skipped hilomap.
    #
    # The gate is skipped when:
    #   - --skip-yosys-gates was passed (explicit opt-out), OR
    #   - --stage 1 was requested (stage1 can't reach PnR), OR
    #   - --stage 2 was requested alone AND the .ys file is absent
    #     (step 9 will catch the missing synth netlist separately), OR
    #   - the project ships no .ys file (non-Yosys flow).
    #
    # When the gate runs AND fails, a synthetic StepResult is inserted
    # at position 0 so the operator sees it before the per-step list,
    # and `ok` is forced False.
    # ------------------------------------------------------------------
    yosys_gate_needed = not args.skip_yosys_gates
    if args.stage == 1:
        yosys_gate_needed = False
    # If only stage2 was requested and no .ys yet, step 9 catches it.
    # For stage2+ or all stages, we run the gate whenever a .ys exists.
    if yosys_gate_needed:
        passed, reasons = _run_yosys_gates(project)
        if reasons:  # only insert a result when the gate actually ran
            synth_result = StepResult(
                # Wave 91 / v1.6.15 — pre-PnR Yosys gate is canonical
                # Step 14 in the flow YAML; this in-process result wraps
                # the same gate set so legacy callers keep their reports.
                id=14,
                name="Pre-PnR Yosys auditor gate (Step 14, Wave 91)",
                stage="stage2",
                status="PASS" if passed else "FAIL",
                reasons=reasons,
                evidence=[],
            )
            # Prepend so the operator sees it first in the per-step
            # listing; the flow's real steps follow.
            pre_pnr_result: Optional[StepResult] = synth_result
        else:
            pre_pnr_result = None
    else:
        pre_pnr_result = None

    # ------------------------------------------------------------------
    # v0.104 — Structural-RTL mandatory gate.
    # Runs all _STRUCTURAL_RTL_GATES against the project's RTL dir.
    # Wave 91 / v1.6.15 — inserted as synthetic step "P0" (preflight
    # stage marker, like A*/M*); legacy id=-1 retired. P0 still appears
    # first in the report because the umbrella result is prepended.
    # Skipped when --stage 3/4 (post-silicon) or no RTL present.
    # ------------------------------------------------------------------
    structural_result: Optional[StepResult] = None
    structural_waivers: List[Dict[str, Any]] = []
    if args.stage not in (3, 4):
        s_passed, s_fails, s_skips, s_waivers = _run_structural_rtl_gates(
            project,
            strict_timing=getattr(args, "strict_timing", False),
            allow_thin_input=getattr(args, "allow_thin_input", False),
        )
        structural_waivers = s_waivers
        if s_fails or s_skips or s_waivers:
            # v0.119.41 Wave 9 — when ≥2 structural gates FAIL, surface
            # a "Failed gates (N):" header so the operator sees each
            # failing gate name + first-line message even when the
            # composite verdict is one terse FAIL line. This addresses
            # the v0.119.40 RESULT.md complaint that 10 distinct
            # structural FAILs collapse into a single composite FAIL
            # without operator-actionable detail.
            failed_gate_lines: List[str] = []
            if len(s_fails) >= 2:
                failed_gate_lines.append(
                    f"Failed gates ({len(s_fails)}):")
                for f_line in s_fails:
                    # Each entry is "FAIL: <gate_name> — <first_line>".
                    failed_gate_lines.append(f"  - {f_line[len('FAIL: '):]}"
                                              if f_line.startswith("FAIL: ")
                                              else f"  - {f_line}")
            else:
                failed_gate_lines.extend(s_fails)
            # v1.6.97 (issue #29 Bugs 1+2) — surface thin-input waivers
            # in the structural umbrella reasons so the operator can
            # see exactly which gates were converted from FAIL to
            # WAIVED via --allow-thin-input. Each waiver entry remains
            # explicit (review_required: true; ticket id) — they are
            # DEFERRED open work, not silent passes.
            waiver_lines = [
                (f"WAIVED-DEFERRED: {w['gate']} — thin-input "
                 f"(ticket={w['ticket']}, review_required=true): "
                 f"{w['first_line']}")
                for w in s_waivers
            ]
            reasons_combined = (failed_gate_lines
                                + [f"SKIP: {s}" for s in s_skips]
                                + waiver_lines)
            # #447 — s_passed is None when NO checker executed (no RTL):
            # the umbrella reports SKIPPED-CONDITION, never PASS; a
            # pure-analog project's strict verdict is decided by the
            # A-track gates, not by 0/226 skipped digital checkers.
            structural_result = StepResult(
                id="P0",
                name=f"Structural-RTL gates (P0 umbrella, {len(_STRUCTURAL_RTL_GATES)} checkers)",
                stage="stage1",
                status=("SKIPPED-CONDITION" if s_passed is None
                        else "PASS" if s_passed else "FAIL"),
                reasons=reasons_combined,
                evidence=[],
            )

    results: List[StepResult] = []
    if structural_result is not None:
        results.append(structural_result)
    if pre_pnr_result is not None:
        results.append(pre_pnr_result)
    skip_analog = getattr(args, 'skip_analog', False)
    skip_hardware = getattr(args, 'skip_hardware', False)
    # Wave 91 / v1.6.15 — when the in-process pre-PnR Yosys gate emitted
    # a synthetic StepResult for id=14, suppress the YAML-driven Step 14
    # entry so the report doesn't list the same gate twice. The YAML
    # entry exists so the flow doc itself enumerates Step 14 as a
    # canonical step in the integer track. The YAML P0 entry is always
    # suppressed: it's a pure documentation marker for the structural-
    # RTL umbrella, which is emitted in-process from
    # `_run_structural_rtl_gates` (when applicable; if the in-process
    # gate didn't fire because no RTL is present yet, the marker is
    # still suppressed because nothing to verify).
    suppress_yaml_step14 = pre_pnr_result is not None
    for step in steps:
        sid = step.get("id")
        if sid == "P0":
            continue
        if suppress_yaml_step14 and sid == 14:
            continue
        r = check_step(project, step, waivers, skip_analog=skip_analog,
                       skip_hardware=skip_hardware)
        results.append(r)

    # v0.100 H2: advisory — warn if post-route STA passed single-corner only
    advisories: List[str] = []
    step20_pass = any(r.id == 20 and r.status == "PASS" for r in results)
    has_mcorner = bool(
        list(project.glob("sta/mcorner_*.rpt"))
        or list(project.glob("reports/sta/mcorner_*.json"))
        or list(project.glob("**/sta_mcorner*"))
    )
    if step20_pass and not has_mcorner:
        advisories.append(
            "Step 20 (post-route STA) passed single-corner only. "
            "Consider running eda_sta_mcorner for SS/FF coverage."
        )

    # Summary
    # Wave 93 — VACUOUS_PASS is a first-class verdict tier counted into
    # `pass_count` for aggregation, displayed separately so reviewers
    # see how many steps were structurally executed vs. vacuously
    # satisfied (input not applicable to this project).
    counts = {"PASS": 0, "FAIL": 0, "MISSING": 0, "WAIVED": 0,
              "SKIPPED-CONDITION": 0, "SKIPPED-SETUP-REQUIRED": 0,
              "VACUOUS_PASS": 0}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    # v1.6.97 (issue #29 Bugs 1+2) — thin-input waivers count toward
    # the WAIVED bucket so Overall verdict resolves to
    # PASS_WITH_WAIVERS (not bare PASS) whenever the --allow-thin-input
    # waiver actually fired. Each waiver is review_required=true and
    # carries a ticket id so foundry tape-out review can close them.
    counts["WAIVED"] += len(structural_waivers)

    # v0.119.53 Wave 21 — `--strict-structural` semantic fix. When
    # `--phase 2 --strict-structural` is requested (and the broader
    # `--strict-step-artifacts` is NOT), verdict scope is the
    # structural-RTL `P0` umbrella result only — step-level MISSING/FAIL
    # for steps 1-6 is REPORTED but not factored into Overall. This
    # closes the v0.119.52 26th-attempt complaint that a structurally
    # clean Phase-2 project was rejected because lint/CDC/coverage/
    # formal step artefacts were incomplete (those need real EDA
    # tool harnesses, not structural-RTL pattern checks).
    # Wave 91 / v1.6.15 — Step-id ⇒ `P0` umbrella + the pre-PnR Yosys
    # gate at Step 14. Both are scoped into the structural-only
    # verdict (preflight + sanity gates only).
    structural_only_verdict = (
        args.phase == "2"
        and args.strict_structural
        and not args.strict_step_artifacts
    )

    # Decide exit code
    if structural_only_verdict:
        # Verdict scope: ONLY the structural-RTL `P0` umbrella. Step-
        # level gates (1-40) — including the pre-PnR Yosys Step 14 —
        # are REPORTED for info but not gating, because they need real
        # EDA tool harnesses that aren't expected to be in scope when
        # `--phase 2 --strict-structural` is run.
        scoped = [r for r in results if r.id == "P0"]
        failing = [r for r in scoped if r.status == "FAIL"]
        missing = [r for r in scoped if r.status == "MISSING"]
        setup_required_skipped = [r for r in scoped
                                  if r.status == "SKIPPED-SETUP-REQUIRED"]
    else:
        failing = [r for r in results if r.status == "FAIL"]
        missing = [r for r in results if r.status == "MISSING"]
        setup_required_skipped = [r for r in results
                                  if r.status == "SKIPPED-SETUP-REQUIRED"]

    # v1.6.99 (issue #31 Bug 2) — informational-only step exclusion.
    # Steps whose ONLY failures cite gates in INFORMATIONAL_GATES are
    # still REPORTED in the per-step listing above, but EXCLUDED from
    # `failing` for verdict computation. Steps that fail for both an
    # informational gate AND a real gate stay in `failing` (the real
    # gate's FAIL still drives the verdict — informational suppression
    # never masks real fails).
    informational_only_failing = [
        r for r in failing if _step_failure_is_informational_only(r)
    ]
    if informational_only_failing:
        excluded_ids = {id(r) for r in informational_only_failing}
        failing = [r for r in failing if id(r) not in excluded_ids]
        for r in informational_only_failing:
            r.reasons.append(
                "(informational gate — excluded from Phase 2 verdict; "
                "see INFORMATIONAL_GATES in flow_compliance_check.py)"
            )

    if args.lenient:
        ok = len(failing) == 0 and len(setup_required_skipped) == 0
    else:
        ok = (len(failing) == 0 and len(missing) == 0
              and len(setup_required_skipped) == 0)

    # Output
    total_required = len(steps) - counts["WAIVED"] - counts.get("SKIPPED-CONDITION", 0)
    # Wave 93 — VACUOUS_PASS rolls into `pass_count` for the X/Y metric
    # since it represents a step that *did* run cleanly (just on input
    # that didn't apply); the discrete count is still surfaced below.
    pass_count = counts["PASS"] + counts["VACUOUS_PASS"]

    scope = f"{args.flow}" + (f" stage{args.stage}" if args.stage else "")
    print(f"\n=== Vibe-IC {scope} compliance ===")
    print(f"Project: {project}")
    print(f"Flow def: {flow_path}")
    print(f"Steps: {len(steps)} total ({pass_count}/{total_required} executed PASS, "
          f"{counts['WAIVED']} DEFERRED via waiver)")
    skipped_str = f"  SKIPPED={counts.get('SKIPPED-CONDITION', 0)}" if counts.get("SKIPPED-CONDITION") else ""
    vacuous_str = (f"  VACUOUS-PASS={counts['VACUOUS_PASS']}"
                   if counts.get("VACUOUS_PASS") else "")
    print(
        f"  PASS={counts['PASS']}  FAIL={counts['FAIL']}  "
        f"MISSING={counts['MISSING']}  WAIVED-DEFERRED={counts['WAIVED']}"
        f"{skipped_str}{vacuous_str}\n"
    )

    _icon = {"PASS": "✓", "FAIL": "✗", "MISSING": "·", "WAIVED": "~",
             "SKIPPED-CONDITION": "-", "SKIPPED-SETUP-REQUIRED": "!",
             "VACUOUS_PASS": "○"}
    _label = {"PASS": "PASS", "FAIL": "FAIL", "MISSING": "MISSING", "WAIVED": "WAIVED-DEFERRED",
              "SKIPPED-CONDITION": "SKIPPED-CONDITION",
              "SKIPPED-SETUP-REQUIRED": "SKIPPED-SETUP-REQUIRED",
              "VACUOUS_PASS": "VACUOUS-PASS"}
    for r in results:
        icon = _icon.get(r.status, "?")
        label = _label.get(r.status, r.status)
        sid_str = f"{r.id:>2}" if isinstance(r.id, int) else f"{r.id:>2}"
        print(f"  {icon} [{label:<17}] Step {sid_str}: {r.name}  ({r.stage})")
        for reason in r.reasons:
            print(f"       └─ {reason}")

    # v0.119.43 Wave 11 / v0.119.53 Wave 21 — strict-structural
    # Phase-2 verdict.
    # When --phase 2 + --strict-structural is requested, harvest every
    # individual structural-RTL gate FAIL from the P0 umbrella (and,
    # when the broader --strict-step-artifacts is also set, from
    # Phase-2b step results 1-13 as well). Emit an explicit "Phase 2
    # strict-structural mode" block listing each failing gate so the
    # agent can ECO-loop. Wave-21 fix: when --strict-structural is set
    # WITHOUT --strict-step-artifacts, only structural-RTL P0 umbrella
    # contributes to the gate listing (step-level FAILs are reported
    # in the per-step listing but not under the strict-structural
    # block, and don't cascade into Overall).
    # Wave 91 / v1.6.15 — id key for the umbrella was renamed -1 → "P0".
    structural_fail_lines: List[str] = []
    step_artifact_fail_lines: List[str] = []
    if args.phase == "2" and (
            args.strict_structural or args.strict_step_artifacts):
        for r in results:
            if r.id == "P0" and r.status == "FAIL":
                for reason in r.reasons:
                    line = None
                    if reason.startswith("FAIL: "):
                        line = reason[len("FAIL: "):]
                    elif reason.lstrip().startswith("- "):
                        line = reason.lstrip()[2:]
                    if line is None:
                        continue
                    # v0.1.62 — INFORMATIONAL_GATES (e.g.
                    # bit_level_full_stack_tb_check) are coverage gaps, not
                    # deployment blockers, and are already excluded from the
                    # step-level verdict. Exclude them from the strict-
                    # structural P0 count too so the treatment is consistent
                    # (they still appear in the per-step listing). Without
                    # this, a non-protocol IC (spm multiplier, sha256 hash)
                    # hard-failed on a single-wire bit-level TB gate that
                    # does not apply to it.
                    if any(g in line for g in INFORMATIONAL_GATES):
                        continue
                    structural_fail_lines.append(line)
            elif r.status in ("FAIL", "MISSING") and \
                    isinstance(r.id, int) and 1 <= r.id <= 13:
                # Phase-2b step-level FAIL/MISSING. With --strict-step-
                # artifacts these contribute. With --strict-structural
                # alone they are info-only.
                first_reason = r.reasons[0] if r.reasons else r.status
                step_artifact_fail_lines.append(
                    f"step{r.id} ({r.name}): {r.status} — {first_reason}")

    # Verdict triage. Waivers are NOT pass — they are deferred to
    # foundry sign-off / production tapeout review. Emit a distinct
    # verdict so a downstream gate / human reader cannot mistake
    # "audit passed" for "every step actually executed".
    forced_fail = False
    if args.strict_step_artifacts and (
            structural_fail_lines or step_artifact_fail_lines):
        forced_fail = True
    elif structural_only_verdict and structural_fail_lines:
        # Wave-21 fix: only structural-RTL gate FAILs force the verdict
        # in structural-only mode. Step-level FAIL/MISSING is info.
        forced_fail = True
    elif (not structural_only_verdict
          and not args.strict_step_artifacts
          and structural_fail_lines):
        # Backwards-compat: --strict-structural without --phase 2 keeps
        # legacy Wave-11 behaviour (any structural FAIL forces verdict).
        forced_fail = True

    if not ok or forced_fail:
        overall = "FAIL"
    elif counts["WAIVED"] > 0:
        overall = "PASS_WITH_WAIVERS"
    else:
        overall = "PASS"

    # v1.6.210 (#91) — PASS_WITH_OPEN_SOURCE_CONSTRAINTS promotion.
    # v1.6.211 (#92) — extended to recognise P0 as deferrable when
    # every failing structural-RTL sub-gate inside P0 is in
    # _P0_THIN_INPUT_DEFERRABLE_SUBGATES.
    #
    # Promotion fires IFF:
    #   1. CLI flag --strict-no-os-constraints NOT set (default off).
    #   2. forced_fail is False (no non-deferrable structural defect).
    #   3. Every failing / missing item is EITHER
    #      (a) a step id in _OPEN_SOURCE_CONTAINER_BLOCKED_STEPS, OR
    #      (b) the P0 umbrella whose failing sub-gates are ALL in
    #          _P0_THIN_INPUT_DEFERRABLE_SUBGATES (#92).
    #   4. Each of _OS_CONSTRAINTS_PREREQ_STEPS is PASS (chip is
    #      engineering-complete on FPGA + on-board test).
    # Anti-fabrication: the tier is NOT a silent green pass. It
    # carries its own label, a structured deferral list, and
    # review_required=true. The P0 deferral includes a per-sub-gate
    # breakdown so the tape-out reviewer sees exactly which structural
    # gaps were deferred and why.
    os_constraints_deferrals: List[Dict[str, Any]] = []
    if (overall == "FAIL"
            and not args.strict_no_os_constraints):
        # v1.6.211 — locate P0 result + categorise its sub-gate fails.
        p0_result = next((r for r in results if r.id == "P0"), None)
        p0_subgate_fails = _parse_p0_failing_subgates(p0_result)
        p0_is_deferrable = (
            p0_result is not None
            and p0_result.status == "FAIL"
            and p0_subgate_fails
            and all(g in _P0_THIN_INPUT_DEFERRABLE_SUBGATES
                    for g in p0_subgate_fails)
        )

        # forced_fail is recomputed here to allow P0 deferral to
        # bypass it. If the only forced-fail source is the P0
        # umbrella AND P0 is deferrable, we allow promotion.
        forced_fail_effective = forced_fail
        if forced_fail and p0_is_deferrable:
            # Check whether forced_fail was driven SOLELY by
            # structural_fail_lines (the P0 umbrella's sub-gate fails);
            # if so, P0 deferrability neutralises it.
            non_p0_forced = (step_artifact_fail_lines
                             and args.strict_step_artifacts)
            if not non_p0_forced:
                forced_fail_effective = False

        non_blocked_failing = []
        for r in failing + missing:
            if r.id in _OPEN_SOURCE_CONTAINER_BLOCKED_STEPS:
                continue
            if r.id == "P0" and p0_is_deferrable:
                continue
            non_blocked_failing.append(r)

        prereq_pass = all(
            any(r.id == sid and r.status == "PASS"
                for r in results)
            for sid in _OS_CONSTRAINTS_PREREQ_STEPS
        )
        # v1.6.212 (#93) — include informational_only_failing items in
        # the deferral source. The informational filter (#31 Bug 2)
        # excludes them from `failing` for verdict computation, but
        # they remain real engineering deferrals that the tapeout
        # vendor's must-close list cannot omit. Step 5 (Formal) is the
        # canonical case: its only FAIL reason cites
        # `bit_level_full_stack_tb_check` (informational), so pre-fix
        # the deferral count under-counted by 1. The informational
        # filter still keeps these items out of `non_blocked_failing`
        # (so they don't gate promotion) but the print/audit emission
        # now sees the full list. chip-AGNOSTIC.
        deferral_source = list(failing) + list(missing)
        deferral_source += [r for r in informational_only_failing
                            if (r.id in _OPEN_SOURCE_CONTAINER_BLOCKED_STEPS
                                or (r.id == "P0" and p0_is_deferrable))]
        if (not non_blocked_failing
                and not forced_fail_effective
                and (failing or missing or informational_only_failing)
                and prereq_pass):
            for r in deferral_source:
                if r.id == "P0":
                    # Emit per-sub-gate breakdown so the deferral
                    # list shows exactly which structural gaps were
                    # deferred and why.
                    breakdown = [
                        {"sub_gate": g,
                         "rationale":
                             _P0_THIN_INPUT_DEFERRABLE_SUBGATES[g]}
                        for g in p0_subgate_fails
                    ]
                    os_constraints_deferrals.append({
                        "step_id": "P0",
                        "step_name": r.name,
                        "status": r.status,
                        "p0_thin_input_subgates": breakdown,
                        "review_required": True,
                    })
                    continue
                tool = _OPEN_SOURCE_CONTAINER_BLOCKED_STEPS.get(r.id, "?")
                os_constraints_deferrals.append({
                    "step_id": r.id,
                    "step_name": r.name,
                    "status": r.status,
                    "commercial_tool_required": tool,
                    "review_required": True,
                })
            overall = "PASS_WITH_OPEN_SOURCE_CONSTRAINTS"

    print(f"\nOverall: {overall}  (strict={not args.lenient})")
    if overall == "PASS_WITH_WAIVERS":
        print(f"  ⚠ {counts['WAIVED']} step(s) DEFERRED via waiver — production tapeout review must close them.")
    if overall == "PASS_WITH_OPEN_SOURCE_CONSTRAINTS":
        print(f"  ⚠ {len(os_constraints_deferrals)} step(s) DEFERRED — "
              f"required commercial tools unavailable in iic-osic-tools "
              f"container. NOT a green pass; tapeout vendor must close "
              f"each entry before production.")
        for d in os_constraints_deferrals:
            if d["step_id"] == "P0" and "p0_thin_input_subgates" in d:
                # v1.6.211 (#92) — P0 deferral surfaces per-sub-gate
                # breakdown.
                print(f"    • Step P0 ({d['step_name']}): {d['status']} — "
                      f"{len(d['p0_thin_input_subgates'])} thin-input "
                      f"sub-gate(s) deferred:")
                for sg in d["p0_thin_input_subgates"]:
                    print(f"        ▸ {sg['sub_gate']}: "
                          f"{sg['rationale']}")
            else:
                print(f"    • Step {d['step_id']} ({d['step_name']}): "
                      f"{d['status']} — needs "
                      f"{d['commercial_tool_required']}")
    if structural_fail_lines:
        print(f"Phase 2 strict-structural mode: "
              f"{len(structural_fail_lines)} structural gates FAILed")
        for line in structural_fail_lines:
            print(f"  {line}")
    if structural_only_verdict and step_artifact_fail_lines:
        # Wave-21 info block — surface step-level gate FAIL/MISSING
        # without affecting Overall verdict.
        print(f"\nStep-level gates (informational, not gating "
              f"--strict-structural): {len(step_artifact_fail_lines)} "
              "step(s) FAIL/MISSING")
        for line in step_artifact_fail_lines:
            print(f"  • {line}")
        print("  (Use --strict-step-artifacts to gate on these too.)")
    if args.strict_step_artifacts and step_artifact_fail_lines:
        print(f"\nPhase 2 strict-step-artifacts mode: "
              f"{len(step_artifact_fail_lines)} step(s) FAIL/MISSING")
        for line in step_artifact_fail_lines:
            print(f"  {line}")

    if advisories:
        print("\nAdvisories:")
        for adv in advisories:
            print(f"  ⚠ {adv}")

    if args.json:
        out = {
            "flow": args.flow,
            "project": str(project),
            "strict": not args.lenient,
            "strict_structural": args.strict_structural,
            "strict_step_artifacts": args.strict_step_artifacts,
            "phase": args.phase,
            "counts": counts,
            "overall": overall,
            "advisories": advisories,
            "structural_fail_lines": structural_fail_lines if (
                args.phase == "2"
                and (args.strict_structural or args.strict_step_artifacts)
            ) else [],
            "step_artifact_fail_lines": step_artifact_fail_lines if (
                args.phase == "2"
                and (args.strict_structural or args.strict_step_artifacts)
            ) else [],
            # v1.6.97 (issue #29 Bugs 1+2) — record thin-input waivers
            # in the JSON report so downstream tooling (foundry sign-off
            # review, regression dashboards) can enumerate every gate
            # that was converted from FAIL to WAIVED via
            # --allow-thin-input.
            "thin_input_waivers": structural_waivers,
            "allow_thin_input": bool(getattr(args, "allow_thin_input", False)),
            "input_doc_count": _count_input_docs(project),
            "steps": [asdict(r) for r in results],
        }
        Path(args.json).write_text(json.dumps(out, indent=2))

    # Wave 30 (v0.119.62) — emit a canonical machine-readable audit
    # artifact at `<project>/reports/phase23_completion_audit.json`
    # whenever flow_compliance_check runs. This is the contract the
    # mcp-eda-server pre-burn guard now consumes (replacing the
    # brittle stdout regex parser that produced 0 failed_gates from
    # 14 real FAILs in the v0.119.61 35th-attempt). The artifact is
    # always written; missing => agent never ran the audit => burn
    # blocked by mcp-eda guard.
    try:
        # Extract per-gate verdicts from the P0 (structural-RTL)
        # umbrella result so the JSON is self-contained.
        # Wave 91 / v1.6.15 — id key was renamed -1 → "P0".
        per_gate: List[Dict[str, Any]] = []
        for r in results:
            if r.id != "P0":
                continue
            for reason in r.reasons:
                msg = reason.strip()
                # Matches "FAIL: gate_name — ..." or "  - gate_name ..."
                fail_match = re.match(
                    r"^FAIL:\s*([\w\.]+)\s*[—\-:]?\s*(.*)$", msg)
                pass_match = re.match(
                    r"^PASS:\s*([\w\.]+)\s*[—\-:]?\s*(.*)$", msg)
                if fail_match:
                    per_gate.append({
                        "name": fail_match.group(1),
                        "verdict": "FAIL",
                        "message": fail_match.group(2)[:240],
                    })
                elif pass_match:
                    per_gate.append({
                        "name": pass_match.group(1),
                        "verdict": "PASS",
                        "message": pass_match.group(2)[:240],
                    })
                else:
                    inline = re.match(
                        r"^([\w\.]+_check)\s*[—\-:]?\s*(.*)$", msg)
                    if inline:
                        verdict_tok = "FAIL" if (
                            "FAIL" in inline.group(2).upper()
                            or "ERROR" in inline.group(2).upper()
                        ) else "PASS"
                        per_gate.append({
                            "name": inline.group(1),
                            "verdict": verdict_tok,
                            "message": inline.group(2)[:240],
                        })
        # Build a canonical failed-gate list combining the structural-
        # RTL gates above and the explicit `structural_fail_lines`
        # collected earlier (covers cases where reasons are formatted
        # differently between gate implementations).
        failed_gate_names: List[str] = []
        seen: set[str] = set()
        for g in per_gate:
            if g["verdict"] == "FAIL" and g["name"] not in seen:
                failed_gate_names.append(g["name"])
                seen.add(g["name"])
        for line in structural_fail_lines:
            m = re.match(r"^([\w\.]+_check)\b", line.lstrip("-•* "))
            if m and m.group(1) not in seen:
                failed_gate_names.append(m.group(1))
                seen.add(m.group(1))

        passed_gate_count = sum(
            1 for g in per_gate if g["verdict"] == "PASS")

        # Detect missing required artifacts that drove FAILs (best-
        # effort, chip-AGNOSTIC). Mostly a hint for humans; the
        # canonical signal is `verdict` + `failed_gates`.
        missing_required: List[str] = []
        for cand in (
            "reports/extraction_coverage_report.md",
            "reports/extraction_coverage_report.json",
            "waivers.json",
            "generated_docs",
            "extraction_patterns.json",
        ):
            p = project / cand
            if not p.exists():
                missing_required.append(cand)

        from datetime import datetime, timezone
        audit = {
            "schema_version": 1,
            "version": "0.119.62",
            "run_at": datetime.now(timezone.utc).isoformat(),
            "phase": args.phase,
            "strict_structural": bool(args.strict_structural),
            "strict_step_artifacts": bool(args.strict_step_artifacts),
            "verdict": overall,
            "gates": per_gate,
            "failed_gates": failed_gate_names,
            "failed_gate_count": len(failed_gate_names),
            "passed_gate_count": passed_gate_count,
            "step_counts": counts,
            "structural_fail_lines": structural_fail_lines,
            "step_artifact_fail_lines": step_artifact_fail_lines,
            "missing_required_artifacts": missing_required,
            # v1.6.210 (#91) — surface OS-constraints deferral list in
            # the audit JSON so downstream tooling can render the
            # tape-out vendor's "must-close" list without re-deriving
            # it. Empty list when the verdict is not
            # PASS_WITH_OPEN_SOURCE_CONSTRAINTS.
            "open_source_constraints_deferrals": os_constraints_deferrals,
            "command_argv": list(sys.argv),
        }
        # v1.6.27: route via auto-router so the audit lands at
        # reports/audit/ (canonical), not stray reports/ root.
        audit_path = _pl.report_path(project, "phase23_completion_audit.json")
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit_path.write_text(
            json.dumps(audit, indent=2, ensure_ascii=False))
    except Exception as e:
        # Never let the audit-emission step fail the gate itself.
        # Surface a stderr warning so a human reviewer can spot it.
        print(f"flow_compliance_check: WARN — could not emit "
              f"phase23_completion_audit.json: {e}", file=sys.stderr)

    # v1.6.210 (#91) — PASS_WITH_OPEN_SOURCE_CONSTRAINTS exits 0 (it is
    # a recognised verdict tier, not a FAIL). PASS, PASS_WITH_WAIVERS,
    # and PASS_WITH_OPEN_SOURCE_CONSTRAINTS all exit 0; FAIL exits 1.
    if overall in ("PASS", "PASS_WITH_WAIVERS",
                   "PASS_WITH_OPEN_SOURCE_CONSTRAINTS"):
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
