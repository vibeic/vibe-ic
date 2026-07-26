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
import functools
import glob
import json
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor
import _path_layout as _pl
import _sim_results_bridge as _srb

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

    Pre-v1.0 split layout (deprecated): the retired two-plugin split.
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
    # five gates derive constraints from the project's own L1-L23 specs
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
    # wake-pulse FSM. Both gates derive constraints from L1-L23 + QSF
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
    # Non-Phase 1 waivers (RTL-bug intentional, vendor table choice,
    # tester quirk, etc.) remain valid.
    "phase1_no_waivers_used_check",
    # v0.119.55 / Wave 23 — closes the v0.119.54 fresh-agent benchmark
    # (28th attempt) where Phase 1 (doc-extraction) produced ONLY 4 of 13 L docs
    # (L2/L8/L9/L11) and the agent silenced LL-38/LL-39/LL-40 with
    # three Phase 1 (doc-extraction)-named waivers. extraction coverage measured
    # 13.7% (149/1091) yet flow_compliance_check returned
    # `Overall: PASS_WITH_WAIVERS`. Wave 23 forbids those waivers
    # (`phase1_no_waivers_used_check` above) AND requires every L1-L23
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
    # PDK-substitution disclosure, DIGITAL track. The existing doctrine
    # (`analog_netlist_pdk_check` / `_pdk_substitution_disclosed`) scans
    # analog_dir for *.sp decks and returns None when there is no analog
    # directory — so on a pure-digital run it never fires. Measured on
    # spm × ihp-sg13g2 (8HD-8): `analog dir exists: False`, the check never
    # ran, and a full DRC/LVS/STA/antenna/IR sign-off completed against
    # ihp-sg13g2 while L19.fields.pdk_target said "sky130", with no artefact
    # reconciling the two. Both gates below SKIP (rc 0) when the project has
    # no declared target or never reached phase 3, so they stay silent on
    # every project the defect cannot apply to.
    #
    # NOTE: `digital_pdk_substitution_disclosure_check` ships on the sibling
    # branch capture/digital-pdk-substitution-disclosure. The dispatch loop
    # does `if not prog.exists(): continue`, so naming it here is safe and
    # inert until that branch lands — it is registered in canonical order now
    # so the two captures need not land in a fixed sequence.
    "digital_pdk_substitution_disclosure_check",
    # ...and the same substitution a second time, in the one place where it
    # silently converts into a timing PASS: the sign-off clock period. The
    # spec keys <PERIOD> by standard-cell library and has no sg13g2 row, so
    # the period in force traced to the *SKY130* row of the design's own
    # table (input/docs/L1_product_metadata.md:35, "10 ns (100 MHz)") and
    # STA reported "setup met, worst slack +6.11 ns" against it.
    "sdc_clock_period_library_basis_check",
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
    status: str  # PASS, FAIL, MISSING, WAIVED, DEFERRED-BY-UPSTREAM, SKIPPED-CONDITION
    reasons: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)
    gate_output: str = ""
    # v0.3.5 — #502/#503 cascade attribution marker, printed inline on
    # the step line (e.g. "blocked-by-upstream(5)" /
    # "deferred-by-upstream(A5, ticket=...)"). Empty = no cascade.
    cascade_note: str = ""


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


def _sibling_self_skip_for_missing(project: Path,
                                   missing_patterns: List[str]) -> Optional[str]:
    """ORGANIC #675 — for a `files_exist` gate that FAILed because a canonical
    output is absent, look for a co-located sibling self-skip artifact in the
    SAME directory that HONESTLY self-reports it was skipped
    (verdict ∈ SKIP/SKIPPED/SKIPPED-CONDITION). Return a human-readable hint
    string (the sibling rel path + verdict + reason) when one is found, else
    None.

    This mirrors `_check_json_field_true`'s ABSENT-field skip promotion (#608),
    extending the same honest-deferral acceptance to the only gate form that
    lacked it (`_check_files_exist`). The canonical case is the formal step
    (#440): the runner emits `formal/formal_not_run.json`
    (verdict=SKIPPED-CONDITION) but NEVER `formal/results.json`, so the
    `files_exist:['formal/results.json']` sub-gate hard-FAILed even though the
    sibling honestly disclosed the skip. The same shape covers any future
    runner that drops a `*_not_run.json` / `*_skipped.json` self-report beside
    an absent canonical output.

    chip-AGNOSTIC: keyed purely on (a) the missing pattern's parent directory
    and (b) a sibling JSON whose `verdict` is a self-skip verdict — no chip,
    vendor, SKU or class literal. CRITICAL §4.05 no-leak: this fires ONLY when
    the canonical output is ABSENT *and* a sibling honestly self-reports a skip;
    a REAL authored artifact (results.json present) never reaches this path
    (the gate already passed), and a sibling that does NOT self-report a skip
    (e.g. a real FAIL verdict, or no sibling at all) returns None → the gate
    stays FAILed. A real formal FAIL still FAILs.
    """
    seen_dirs: set = set()
    for pat in missing_patterns:
        # The directory the absent canonical output lives in (e.g.
        # "phase2/stage1/formal" for "phase2/stage1/formal/results.json").
        parent_rel = str(Path(pat).parent)
        if parent_rel in seen_dirs:
            continue
        seen_dirs.add(parent_rel)
        # Resolve the directory through the same glob-fallback as the gate so
        # canonical-analog-dir / reports-subdir remaps are honored.
        dir_candidates: List[Path] = []
        direct = project / parent_rel
        if direct.is_dir():
            dir_candidates.append(direct)
        # Probe via _glob_first on the dir pattern so reports/ and analog/
        # remaps resolve the same way the missing pattern would have.
        for hit in _glob_first(project, parent_rel):
            hp = project / hit
            if hp.is_dir():
                dir_candidates.append(hp)
        for d in dir_candidates:
            try:
                json_siblings = sorted(d.glob("*.json"))
            except OSError:
                continue
            for sib in json_siblings:
                try:
                    data = json.loads(sib.read_text())
                except Exception:
                    continue
                if not isinstance(data, dict):
                    continue
                vd = str(data.get("verdict", "")).upper().replace("_", "-")
                if vd in _SELF_SKIP_VERDICTS:
                    try:
                        sib_rel = str(sib.relative_to(project))
                    except ValueError:
                        sib_rel = sib.name
                    reason = str(data.get("reason", ""))[:160]
                    return (f"{sib_rel}: sibling self-reports verdict={vd}"
                            + (f" ({reason})" if reason else ""))
    return None


def _norm_out_path(s: str) -> str:
    """Normalize an output path for exact ownership comparison: trim, drop a
    leading `./`. Pure."""
    s = s.strip()
    while s.startswith("./"):
        s = s[2:]
    return s


def _output_claim_matches(declared: str, missing_patterns: List[str]) -> bool:
    """A marker's declared skipped-output OWNS one of the step's missing
    required-output specs — by EXACT (normalized) string equality against one of
    the split "A OR B" alternatives. Pure.

    EXACT match ONLY — deliberately NOT fnmatch. A glob match (in either
    direction) would reopen two masking vectors the adversarial review flagged:
    (a) a forged broad-glob declaration like `reports/phase3/*` would match a
    sign-off `drc_signoff.rpt`; (b) a step with a glob required-output like
    `phase2/stage2/synth/*.v` could be masked by a foreign concrete marker naming
    any `.v` in the shared dir. Requiring the declaration to be the literal
    required-output spec the step expects removes both — a marker can only own the
    exact output string it declares, never a wildcard family. A future marker that
    must own a glob-only required-output declares that spec string verbatim."""
    d = _norm_out_path(declared)
    return any(d == _norm_out_path(p) for p in missing_patterns)


def _declared_sibling_self_skip_for_missing(project: Path,
                                            missing_patterns: List[str]
                                            ) -> Optional[str]:
    """STRICT variant of `_sibling_self_skip_for_missing`, for the EARLY
    required_outputs-MISSING path where there is NO substantive gate to run as a
    backstop (a step whose only evidence is output-presence).

    The loose variant matches ANY skip-verdict sibling in the missing output's
    directory — SAFE at the `files_exist` gate path (a second sub-gate still runs
    and FAILs a real defect) but UNSAFE at the early-return, because output
    directories are SHARED between steps (phase2/stage2/synth/ holds BOTH step-9
    `netlist.v` and step-12 `post_dft_not_run.json`; reports/phase3/ holds many
    sign-off reports). A dir-level match there could let one step's honest
    skip-marker MASK a DIFFERENT step's genuinely-absent output — e.g. mask a
    real synthesis FAIL (step 9) or a DRC/LVS sign-off FAIL (step 31) — turning a
    true MISSING/FAIL into a false SKIPPED-CONDITION.

    This strict form promotes MISSING→SKIPPED-CONDITION ONLY when a co-located
    sibling UNAMBIGUOUSLY OWNS this step's absent output. The sibling must carry:
      (1) a self-skip verdict (SKIP / SKIPPED / SKIPPED-CONDITION);
      (2) a NON-EMPTY `capability_flag` — the disclosed OSS/analog capability gap
          it defers under (capability-AWARE, not capability-blind). A hard
          sign-off (DRC/LVS/ERC/STA) has NO disclosed capability gap, so no
          legitimate runner marker ever defers it; and
      (3) a `skips_required_output` (str or list) matching one of THIS step's
          missing canonical outputs (exact or glob, either direction).
    A marker that omits (2) or (3), or whose `skips_required_output` names a
    DIFFERENT output, is IGNORED → the step stays MISSING. So a step-12 marker
    (owns `post_dft_netlist.v`) can never mask step-9's `netlist.v`, and a stray
    skip-json in reports/phase3/ can never mask a DRC/LVS sign-off. chip-AGNOSTIC;
    the trust model is the same runner-emitted-evidence one the §4.05 blindness /
    evidence-integrity audits already police, and a promotion yields only a
    review-flagged SKIPPED-CONDITION (excluded from executed-PASS), never a clean
    PASS.
    """
    seen_dirs: set = set()
    for pat in missing_patterns:
        parent_rel = str(Path(pat).parent)
        if parent_rel in seen_dirs:
            continue
        seen_dirs.add(parent_rel)
        dir_candidates: List[Path] = []
        direct = project / parent_rel
        if direct.is_dir():
            dir_candidates.append(direct)
        for hit in _glob_first(project, parent_rel):
            hp = project / hit
            if hp.is_dir():
                dir_candidates.append(hp)
        for d in dir_candidates:
            try:
                json_siblings = sorted(d.glob("*.json"))
            except OSError:
                continue
            for sib in json_siblings:
                try:
                    data = json.loads(sib.read_text())
                except Exception:
                    continue
                if not isinstance(data, dict):
                    continue
                vd = str(data.get("verdict", "")).upper().replace("_", "-")
                if vd not in _SELF_SKIP_VERDICTS:
                    continue
                if not str(data.get("capability_flag", "")).strip():
                    continue  # capability-AWARE: no disclosed gap → not eligible
                declared = data.get("skips_required_output")
                declared_list = ([declared] if isinstance(declared, str)
                                 else list(declared)
                                 if isinstance(declared, (list, tuple)) else [])
                if not any(_output_claim_matches(do, missing_patterns)
                           for do in declared_list if isinstance(do, str)):
                    continue  # marker does not OWN this step's absent output
                try:
                    sib_rel = str(sib.relative_to(project))
                except ValueError:
                    sib_rel = sib.name
                reason = str(data.get("reason", ""))[:150]
                flag = str(data.get("capability_flag", ""))
                return (f"{sib_rel}: owns this output "
                        f"(skips_required_output) and self-reports "
                        f"verdict={vd} [{flag}]"
                        + (f" ({reason})" if reason else ""))
    return None


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
      * rc == 3  → PASS_WITH_WAIVERS — the #651 waiver convention used by
                   `tapeout_signoff_check` (signoff_audit) when the tapeout
                   threshold was met but a DRC/LVS slot was credited via a
                   waiver. The snippet is prefixed with the `__WAIVER_HINT__:`
                   sentinel so check_step promotes the step to WAIVED-DEFERRED
                   (→ Overall PASS_WITH_WAIVERS) instead of a bare PASS. Only
                   honoured when the program ALSO printed the
                   `PASS_WITH_WAIVERS` stdout sentinel — a bare rc=3 with no
                   sentinel stays a FAIL (an unrelated program's exit 3 is
                   never silently waived).
      * rc == 1  → FAIL
      * other    → FAIL
    """
    argv = _resolve_program_cmd(cmd_str, cwd=project)
    if not argv:
        return False, f"program not found: {cmd_str.split()[0]}"
    # #525 — per-gate budget from the SHARED resolver (default 900s, env
    # VIBE_IC_GATE_TIMEOUT_S, cap 3600s). The old fixed 300s killed honest
    # slow gates on large SoCs (reset_dependency_check ~6 min on a 7.5MB
    # post-PnR netlist; provenance sha256 over multi-GB GDS) and reported
    # the kill as a plain gate FAIL.
    gate_budget = _pl.gate_timeout_s()
    try:
        r = subprocess.run(
            argv,
            cwd=project,
            capture_output=True,
            text=True,
            timeout=gate_budget,
        )
        snippet = (r.stdout[-300:] + "\n" + r.stderr[-300:]).strip()
        if r.returncode == 0:
            return True, snippet
        if r.returncode == 2:
            # Treat as vacuous pass — surface the program command so
            # reviewers know which gate vacuously passed.
            return True, f"{_VACUOUS_HINT_PREFIX}{cmd_str}"
        if (r.returncode == _WAIVER_EXIT_CODE
                and _stdout_signals_waiver(r.stdout)):
            # #651 — PASS_WITH_WAIVERS: the gate passed its threshold but a
            # slot was credited via a waiver. Promote to WAIVED-DEFERRED (not
            # bare PASS) so the WITH_WAIVERS distinction survives the rc-only
            # gate. Requires the stdout sentinel too, so a stray rc=3 from an
            # unrelated program is NOT silently waived.
            return True, f"{_WAIVER_HINT_PREFIX}{cmd_str}"
        return False, snippet
    except subprocess.TimeoutExpired:
        # #525 — a timeout is NOT a verdict: the gate program was killed
        # mid-run, so the step is INCONCLUSIVE (still FAILs the audit —
        # an unevaluated gate cannot pass — but the message must never
        # read as a substantive gate failure).
        return False, (f"program TIMED OUT after {gate_budget}s — timeout "
                       f"is NOT a verdict (INCONCLUSIVE; raise "
                       f"{_pl.GATE_TIMEOUT_ENV} to extend): {cmd_str}")
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

# ORGANIC #608 — internal marker a gate can emit to promote its step to
# SKIPPED-CONDITION (not FAIL) when the gate's own evidence artifact HONESTLY
# self-reports it was skipped (verdict ∈ SKIP/SKIPPED/SKIPPED-CONDITION) and the
# success field the gate checks is therefore absent. Mirrors the #433c
# verdict-self-report doctrine + the VACUOUS_HINT promotion pattern.
_SKIP_HINT_PREFIX = "__SKIP_HINT__: "
# Verdict tokens (normalised upper, `_`→`-`) that count as an honest skip.
_SELF_SKIP_VERDICTS = frozenset({"SKIP", "SKIPPED", "SKIPPED-CONDITION"})

# #651 — PASS_WITH_WAIVERS hint. A `program_exit_zero` gate program (notably
# `tapeout_signoff_check` = signoff_audit --mode tapeout) signals "I PASSED
# the threshold but a slot was credited via a WAIVER" by BOTH:
#   * exiting with rc == _WAIVER_EXIT_CODE (3), AND
#   * printing a line starting with _WAIVER_STDOUT_SENTINEL.
# When both fire, check_step promotes the step to WAIVED-DEFERRED (counted as
# a waiver, never a bare PASS) so the Overall verdict resolves to
# PASS_WITH_WAIVERS — carrying the distinction the rc-only gate used to lose
# (CLAUDE.md rule 11). Requiring BOTH the rc AND the sentinel keeps an
# unrelated rc-3 program from being mis-promoted into a waiver.
_WAIVER_HINT_PREFIX = "__WAIVER_HINT__: "
_WAIVER_EXIT_CODE = 3
_WAIVER_STDOUT_SENTINEL = "PASS_WITH_WAIVERS"


def _stdout_signals_waiver(snippet: str) -> bool:
    """Return True iff the program's combined stdout/stderr snippet contains
    a `PASS_WITH_WAIVERS` token at line-start (leading whitespace allowed)."""
    if not snippet:
        return False
    for line in snippet.splitlines():
        if line.lstrip().startswith(_WAIVER_STDOUT_SENTINEL):
            return True
    return False


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
        # No .ys file — the project may still have synthesised via the
        # runner's inline `yosys -p '<cmds>'` path (no .ys script). ORGANIC
        # #649: returning an unconditional PASS here structurally BYPASSED
        # the hilomap / -flatten conformance check for EVERY inline-yosys
        # flow (the gate emitted VACUOUS_PASS and PnR could ship a netlist
        # missing tie cells that detailed_route then crashes on, DRT-0305).
        #
        # Extract the ACTUAL inline command yosys echoed into
        # phase{2,3}/stage2/synth/{yosys,synth}.log and verify hilomap /
        # -flatten conformance against THAT command. A real-PDK inline synth
        # (binds a Liberty library) that runs hilomap → PASS; one missing
        # hilomap → FAIL (not VACUOUS_PASS). A simulation-only inline synth
        # (no Liberty) legitimately waives hilomap. chip-AGNOSTIC.
        if str(PROGRAMS_DIR) not in sys.path:
            sys.path.insert(0, str(PROGRAMS_DIR))
        try:
            from _yosys_inline_mode_detect import audit_inline_yosys
        except Exception:
            # Detector unavailable (incomplete install): fall back to the
            # pre-#649 behaviour rather than hard-erroring the whole flow.
            return True, []
        verdict, evidence_logs, inline_reasons = audit_inline_yosys(project)
        if verdict == "FAIL":
            reasons = [
                "FAIL: inline `yosys -p` real-PDK synthesis command "
                "(extracted from the runner's synth log) is non-conformant "
                "— PnR will crash at detailed_route with DRT-0305 'zero_ "
                "GROUND' on the unmapped tie net (CLAUDE.md rule 4)."
            ]
            reasons.extend(f"    {r}" for r in inline_reasons)
            return False, reasons
        # verdict in {"PASS", "NO_INLINE_COMMAND"}:
        #   PASS              — inline command verified conformant (or only a
        #                       sim-only inline synth ran); no .ys to audit.
        #   NO_INLINE_COMMAND — no inline yosys command was echoed at all;
        #                       flows without Yosys are legitimate (Cadence
        #                       Genus / GF flows), and the wider
        #                       flow_compliance_check still catches a missing
        #                       netlist via step 9's required_outputs.
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


# ─── ORGANIC #708 — reused-IP RTL-only-FSM deferral cap ──────────────────────
# Monotonicity bug: reaching 100% doc completeness REVOKES the only deferral
# (--allow-thin-input, predicate _is_thin_input_eligible, keyed on doc-
# completeness < 100%) for the non-waivable L6 ≥2-fsm_states floor of
# `l_doc_structured_field_count_check`. The trapped class is REUSED-IP whose
# control FSM lives ONLY in vendor RTL (states never appear in any input doc):
#   - cannot claim the #462 no_fsm N/A escape (no_fsm_in_input=false is CORRECT
#     — the IP really HAS an FSM),
#   - cannot reach the floor (anti-fabrication forbids inventing a doc-traceable
#     2nd state),
#   - cannot lift via the #706 ai_deep_review sidecar (no qualifying doc-
#     traceable FSM patch exists),
#   - and now cannot defer (thin-input is revoked at 100% completeness).
# Every path is closed for a STRUCTURALLY-CORRECT extraction.
#
# This cap is an ORTHOGONAL, fail-closed deferral that fires at 100%
# completeness — the regime --allow-thin-input does NOT cover — and ONLY for
# the L6 fsm_states floor FAIL. It NEVER touches _is_thin_input_eligible (which
# owns the < 100% regime). All FOUR keys must hold (see
# _reused_ip_rtl_only_fsm_cap_eligible); a single false key keeps the FAIL.
_REUSED_IP_RTL_ONLY_FSM_CAP_TICKET = "reused-ip-rtl-only-fsm-v1.6.708"
_REUSED_IP_RTL_ONLY_FSM_CAP_GATE = "l_doc_structured_field_count_check"
# Tokens that mark the L6 FSM-states floor detail line (case-insensitive). The
# L6 floor FAIL reads uniquely:
#   "L6 control_logic must carry ≥N typed FSM states in `fsm_states` …"
# round-2 fix (2): the L9 floor detail line ALSO contains the substring
# `fsm_states` (it lists "… among (top_module string, fsm_states[], port list,
# …)"), so a bare `fsm_states` token would mis-classify the L9 line as the FSM
# floor and let the cap MASK a co-occurring L9 failure. The discriminator
# phrase `typed fsm states` appears ONLY in the L6 control-logic floor message,
# never in the L9 message — use it to identify the L6 FSM-states floor line
# precisely (still chip-AGNOSTIC: a gate-message phrase, no chip/vendor name).
_FSM_STATES_FLOOR_TOKENS = ("typed fsm states",)
# Also accept the explicit L6 control-logic floor wording as a second
# (redundant) discriminator so a future message reword that drops "typed" but
# keeps "control_logic … fsm_states" is still recognised — both require the L6
# control-logic context, so neither matches the L9 line.
_L6_FSM_FLOOR_DISCRIMINATORS = (
    "typed fsm states",
    "control_logic must carry",
)

# ─── ORGANIC #708 round-3: trusted-extractor-anchored key-(c) FSM scan ────────
# History: the round-1 ALL-CAPS-only scanner and the round-2 generous shape +
# position scanner were BOTH wrong — the regex arms race leaked on lowercase
# datasheet prose AND over-blocked on bus/IP/register/acronym names (a token
# like CTRL_REG / AXI4 / DDR4 wrongly KEEPS a FAIL on a correct reused-IP
# design — the false-positive the second adversarial review surfaced). A
# hardware-acronym stopword set was an even WORSE fix: it erased real states
# (an FSM state literally named DMA / RX / SCAN). Both failure directions are
# harmful here (the cap RELAXES a non-waivable floor: an over-collected token
# wrongly FAILs a correct design, an under-collected one leaks).
#
# Round-3 design: anchor key (c) on the plugin's OWN trusted FSM-state
# extractor — `phase1_doc_one_shot_runner._classify_modes_vs_states_from_text`
# + `_is_real_fsm_state` — the SAME deterministic walker whose output populates
# L6.fsm_states. By construction this cannot diverge from the walker: a
# doc-traceable state the trusted extractor finds is, by the plugin's own
# definition, a state the walker would have extracted (so it is already in
# fsm_states, not "missed"); a token the trusted extractor does NOT find is, by
# the same definition, not a doc-traceable state. The genuine residual — a
# state the deterministic extractor truly cannot parse — is exactly what the
# #706 ai_deep_review channel (key (d)) exists to recover. This eliminates the
# acronym/register/IP-name over-blocks (those never sit in the trusted
# extractor's `state:`/`fsm states:` narrative positions) AND the acronym-state
# erasure (no hardware-acronym stopword set), and stays consistent with the
# walker (no parallel worse extractor).
#
# A SMALL set of high-precision SUPPLEMENTARY position patterns augments the
# trusted extractor for the explicit-enumeration surface forms the reviewer
# requires (lowercase "states: idle and active", "from X to Y", transition
# arrows, "the X state", bullet/table rows, motion-verb-to-SHAPED). These are
# UNAMBIGUOUS state enumerations; they do NOT include the loose copula /
# predicate / whole-region-shape scans that caused the over-blocks. The
# stopword set holds ONLY grammatical / doc-structural English words (never a
# state name) — NEVER hardware acronyms (which CAN be state names).
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# Explicit enumerated-set position: "states/phases/modes are/:/=/include/named …"
# CAPTURE ONLY A DELIMITED LIST TAIL — a run of identifiers joined by `,`/`/`/
# `;`/`and`/`or` — and stop at the first word that is NOT part of such a list.
# This is the round-3 over-block fix: "states are implemented in the supplier's
# RTL …" is a passive VERB phrase, NOT an enumeration, so it must capture
# NOTHING (the greedy `(.+)` grabbed the whole sentence and pulled SUPPLIER /
# NETLIST / REPRODUCED / …). "states are idle, active and done" IS a list, so
# it captures idle/active/done. The list grammar: IDENT (delim IDENT)+ — i.e. a
# real enumeration has at least one delimiter, which "are implemented in …"
# (verb + preposition) does not match (its second token "in" is a stopword and
# there is no list-delimiter joining bare identifiers).
_RE_STATES_LIST = re.compile(
    r"\b(?:states?|phases?|modes?)\s*"
    r"(?:are|:|=|include[s]?|comprise[s]?|consist[s]?\s+of|named|called|"
    r"labell?ed)\s+"
    r"([A-Za-z_][A-Za-z0-9_]*"
    r"(?:\s*(?:,|/|;|\band\b|\bor\b)\s*[A-Za-z_][A-Za-z0-9_]*)+)",
    re.IGNORECASE)
# "the X state|phase|mode" / "X state|phase|mode" (adjective-position name).
# Excludes the false adjectives "full/control/finite/next/current/…" via the
# stopword subtraction in the caller; "full state machine" → FULL is a stopword.
_RE_X_STATE = re.compile(
    r"\b([A-Za-z_][A-Za-z0-9_]*)\s+(?:state|phase|mode)\b", re.IGNORECASE)
_RE_IN_X_STATE = re.compile(
    r"\b(?:in|during|the)\s+(?:the\s+)?([A-Za-z_][A-Za-z0-9_]*)\s+"
    r"(?:state|phase|mode)\b", re.IGNORECASE)
# "from X to Y".
_RE_FROM_TO = re.compile(
    r"\bfrom\s+([A-Za-z_][A-Za-z0-9_]*)\s+to\s+([A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE)
# Transition arrows incl. double-dash mermaid `-->`, `=>`, Unicode `→`/`⟶`, RTL
# `<=`, and en-/em-dash sequence chains ("idle – armed – idle"). The dash forms
# require spaces around the dash so an ordinary hyphenated word ("power-down")
# is not split.
_RE_ARROW = re.compile(
    r"([A-Za-z_][A-Za-z0-9_-]*)\s*(?:-+>|=+>|→|⟶|<=|\s[–—-]\s)\s*"
    r"([A-Za-z_][A-Za-z0-9_-]*)")
# Brace/bracket/paren enumerated set.
_RE_BRACE_SET = re.compile(r"[\{\[\(]([^\}\]\)]*)[\}\]\)]")
# Motion verb + (to/into) + state. The captured object is kept ONLY when it is
# state-name-SHAPED (ALL-CAPS≥3 / underscore / digit / mixedCase) so ordinary
# lowercase prose objects ("goes to sleep") do NOT over-collect, while a shaped
# state ("advances to DONE", "enters BUSY", "switches to FLUSH") is caught.
_RE_VERB_STATE = re.compile(
    r"\b(?:advances?|goes?|moves?|transitions?|returns?|jumps?|proceeds?|"
    r"enters?|reaches?|switch(?:es)?|leaves?|exits?|becomes?|slips?|occupies|"
    r"occupy|lands?|settles?|drops?|falls?|waits?\s+in|sits?\s+in|"
    r"rests?\s+in|parks?\s+in)\s+"
    r"(?:back\s+|quietly\s+|then\s+)?(?:to|into|in|at)?\s*(?:the\s+)?"
    r"([A-Za-z_][A-Za-z0-9_-]*)",
    re.IGNORECASE)
# Copula / predicate naming a state: "is/are/becomes/remains/is now X",
# "sits in X", "parks at X". Captures the single predicate token (filtered by
# stopwords downstream). Closes the lowercase-prose copula leak ("becomes
# ready", "is now granted", "remains done").
_RE_COPULA_STATE = re.compile(
    r"\b(?:is|are|was|were|be|becomes?|remains?|stays?|rests?|sits?\s+in|"
    r"parks?\s+at|is\s+now|are\s+now)\s+(?:either\s+|both\s+|currently\s+|"
    r"the\s+)?([A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE)
# List-verb enumeration WITHOUT the literal word "states": "cycles through X, Y,
# Z", "sequences X, Y, Z", "iterates over X, Y" — capture the delimited list.
_RE_LIST_VERB = re.compile(
    r"\b(?:cycles?\s+through|sequences?|iterates?\s+(?:over|through)|"
    r"steps?\s+through|progresses?\s+through|runs?\s+through|"
    r"loops?\s+through|visits?)\s+"
    r"([A-Za-z_][A-Za-z0-9_]*"
    r"(?:\s*(?:,|/|;|\band\b|\bor\b)\s*[A-Za-z_][A-Za-z0-9_]*)+)",
    re.IGNORECASE)
# "X denotes/represents/means/indicates [a/the] state".
_RE_DENOTES = re.compile(
    r"\b([A-Za-z_][A-Za-z0-9_]*)\s+(?:denotes|represents|means|indicates|"
    r"signifies)\b",
    re.IGNORECASE)
# `S0..Sn` short-form state names.
_FSM_STATE_SHORT_RE = re.compile(r"\bS\d+\b", re.IGNORECASE)
# Quoted state literal: 'ACTIVE' / "ACTIVE".
_RE_QUOTED = re.compile(r"['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]")


def _token_is_state_shaped(token: str) -> bool:
    """True iff `token` LOOKS like an enumerated state identifier — ALL-CAPS
    (≥3, so OK/RX are not falsely shaped but BUSY/DONE are), has `_`, has a
    digit, or is mixedCase — rather than an ordinary lowercase prose word. Used
    to gate the motion-verb object so lowercase prose ("goes to sleep") does not
    over-collect."""
    if not token or len(token) < 3:
        return False
    if re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", token):
        return True
    if "_" in token:
        return True
    if any(c.isdigit() for c in token):
        return True
    if re.fullmatch(r"[A-Za-z][a-z0-9]*[A-Z][A-Za-z0-9]*", token):  # mixedCase
        return True
    return False


# Grammatical + doc-structural stopwords — words that are NEVER an FSM state
# name. CRITICAL: this set must NOT contain hardware acronyms (CPU/AXI/DMA/RX/…)
# — those CAN be real state names, and erasing them re-opens a leak. It holds
# ONLY English glue + FSM/doc vocabulary. The trusted extractor + high-precision
# positions already avoid grabbing acronyms (they are not in `state:` positions
# in real prose), so no acronym filter is needed.
_FSM_STOPWORDS = frozenset(w.upper() for w in (
    # FSM / doc structural vocabulary (never a state name)
    "state", "states", "fsm", "fsms", "finite", "machine", "machines",
    "control", "logic", "transition", "transitions", "phase", "phases",
    "mode", "modes", "step", "steps", "next", "current", "diagram", "figure",
    "table", "row", "rows", "column", "columns", "see", "details", "detail",
    "implementation", "implemented", "implements", "described", "describes",
    "enumerated", "enumerate", "enumerates", "documented", "field", "fields",
    "typed", "structured", "name", "names", "named", "called", "labelled",
    "labeled", "entry", "entries", "controller", "sequencer", "unit", "block",
    "design", "document", "datasheet", "section", "spec", "specification",
    "rtl", "vendor", "core", "module", "reset", "clock",
    # generic English glue
    "the", "a", "an", "and", "or", "of", "to", "from", "in", "on", "at", "by",
    "for", "with", "is", "are", "be", "as", "it", "this", "that", "these",
    "those", "then", "when", "while", "which", "into", "back", "via", "per",
    "all", "any", "each", "one", "two", "three", "four", "five", "no", "not",
    "has", "have", "having", "must", "should", "may", "can", "will", "shall",
    "only", "also", "such", "where", "between", "after", "before", "until",
    "during", "upon", "if", "else", "but", "we", "they", "its", "their",
    "our", "you", "your", "here", "there", "small", "large", "internal",
    "external", "remaining", "remain", "left", "once", "still", "more", "less",
    "many", "few", "etc", "eg", "ie", "shown", "defined", "inside", "other",
    "above", "below", "various", "several", "multiple", "some",
    "l6", "l1", "l5", "l9",
    # Additional ordinary-English doc-prose words the high-precision positions
    # ("X state", states-list, table rows) may incidentally capture from a
    # reused-IP datasheet — never FSM state names (round-3 over-block fix):
    "supplier", "supplied", "netlist", "release", "releases", "reproduced",
    "reproduce", "solely", "part", "parts", "notes", "note", "built", "full",
    "interface", "interfaces", "register", "registers", "signal", "signals",
    "bus", "buses", "memory", "macro", "wrapper", "peripheral", "instance",
    "configure", "configures", "configured", "configuration", "power", "boot",
    "powers", "initialises", "initializes", "connects", "drives", "exposes",
    "provides", "supports", "talks", "sits", "starts", "powered", "available",
    "downstream", "upstream", "rest", "complete", "completes",
    "intentionally", "generated", "queued", "described", "available",
    "left", "blank", "empty", "unused", "reserved", "todo", "tbd", "na",
    "order", "sequence", "repeats", "without", "delay", "quietly", "most",
    "occasionally", "between", "bursts", "entirely", "cuts", "holding",
    "request", "transfer", "bus", "sensor",
    # NOTE: deliberately NOT including words commonly used AS state names —
    # running / pending / active / busy / idle / done / wait / fetch / decode /
    # execute / flush / stall / sleep / armed / granted / … — nor any hardware
    # acronym (cpu/axi/dma/rx/scan/…). Filtering any of those would erase a real
    # doc-enumerated state (a LEAK). The extracted-state-name + internal-label
    # subtraction (done by the caller) removes the already-extracted ones.
))


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


# ─── ORGANIC #708 — reused-IP RTL-only-FSM deferral cap helpers ──────────────
def _detected_class_rtl_gen_null_and_vendor_rtl(project: Path) -> bool:
    """KEY (a): the detected IC class has rtl_gen=null in
    ic_class_registry.json (a from-spec-RTL / vendor-IP class — processor_cpu /
    digital_arithmetic_primitive / crypto_accelerator / digital_cmd_driven /
    … — read from the registry, NEVER a chip-name literal) AND vendor/reused RTL
    is present (input/vendor_rtl/ has ≥1 .v/.sv, OR the rtl_dir's
    SOURCE_MANIFEST.json declares reused_ip=true).

    Excludes from-scratch/authored designs (whose docs MUST fully specify the
    FSM): a class with a deterministic rtl_gen, or a project with no vendor RTL,
    keeps the FAIL. Fail-closed: any read/import error → False."""
    import sys as _sys
    if str(PROGRAMS_DIR) not in _sys.path:
        _sys.path.insert(0, str(PROGRAMS_DIR))
    # (a.1) class rtl_gen=null via the registry (same resolution the
    # pure-analog detector uses above — name OR synonym match).
    try:
        from ic_class_profile import detect_ic_class as _detect
        profile = _detect(project) or {}
    except Exception:
        return False
    ic_class = str(profile.get("ic_class") or "unknown")
    # ORGANIC #708 round-2 fix (3): an UNRESOLVED / unknown detection must be
    # fail-closed — a design we couldn't classify gets NO floor relaxation. The
    # registry carries an `unknown_protocol_class` entry (rtl_gen=null, synonym
    # `unknown`) used as the runner's fallback target; matching it here would
    # let an UNCLASSIFIED design with a stray vendor .v ride the cap. Reject the
    # unknown class (and its registry alias) BEFORE the registry lookup so the
    # docstring's "unknown/unresolvable → False" contract actually holds.
    if ic_class in ("", "unknown", "unknown_protocol_class"):
        return False
    config = None
    try:
        reg = json.loads(
            (PROGRAMS_DIR / "ic_class_registry.json").read_text())
        for c in (reg.get("classes") or []):
            cname = c.get("name")
            if cname == "unknown_protocol_class":
                continue  # never the cap's eligibility target (fail-closed)
            if (cname == ic_class
                    or ic_class in (c.get("synonyms") or [])):
                config = c
                break
    except Exception:
        return False
    if config is None:
        return False  # unknown/unresolvable class → fail-closed
    if config.get("rtl_gen") is not None:
        return False  # from-spec/deterministic-RTL class → docs must specify
    # (a.2) vendor/reused RTL must be present.
    vendor_dir = project / "input" / "vendor_rtl"
    if vendor_dir.is_dir() and (any(vendor_dir.rglob("*.v"))
                                or any(vendor_dir.rglob("*.sv"))):
        return True
    mf = _pl.rtl_dir(project) / "SOURCE_MANIFEST.json"
    if mf.is_file():
        try:
            mdata = json.loads(mf.read_text())
        except Exception:
            return False
        if isinstance(mdata, dict) and mdata.get("reused_ip") is True:
            return True
    return False


def _completeness_is_full_and_not_tiny(project: Path) -> bool:
    """KEY (b): every non-reference doc with raw_total>0 in
    phase1_input_vs_generated_completeness.json has captured_pct >= 1.0 AND the
    input is NOT tiny (sum(raw_total non-ref) > TINY_INPUT_TOTAL_RAW_TOKENS).

    This is essentially the NEGATION of the thin-input coverage predicate — at
    < 100% capture the EXISTING --allow-thin-input path owns the deferral, so
    this cap must NOT fire (no double-demote). Report missing / malformed /
    empty → False (fail-closed)."""
    report_path = _pl.report_path(
        project, "phase1_input_vs_generated_completeness.json")
    if not report_path.is_file():
        return False
    try:
        data = json.loads(report_path.read_text())
    except Exception:
        return False
    per_doc = data.get("per_doc")
    if isinstance(per_doc, dict):
        per_doc = list(per_doc.values())
    if not isinstance(per_doc, list) or not per_doc:
        return False
    total_raw = 0
    saw_real_doc = False
    for entry in per_doc:
        if not isinstance(entry, dict):
            continue
        if entry.get("reference_doc") is True:
            continue
        raw = int(entry.get("raw_total") or 0)
        if raw <= 0:
            continue
        saw_real_doc = True
        total_raw += raw
        captured = entry.get("captured_pct", entry.get("capture_pct"))
        try:
            if float(captured) < 1.0:
                return False  # a sub-100% doc → thin-input regime owns it
        except (TypeError, ValueError):
            return False  # malformed capture value → fail-closed
    if not saw_real_doc:
        return False
    # NOT tiny: the negation of the v0.1.57 tiny-input thin path.
    return total_raw > TINY_INPUT_TOTAL_RAW_TOKENS


def _l6_doc_records_fsm_present(project: Path) -> tuple[bool, dict]:
    """Return (no_fsm_in_input_is_false, l6_data). The cap requires the L6
    generated doc (`generated_docs/L6_CONTROL_LOGIC.json`) to record
    no_fsm_in_input == false (the IP really HAS FSMs). A missing doc, a missing
    flag, or no_fsm_in_input==true → (False, {}) — the latter is the existing
    #462 honest no-FSM N/A escape, NOT this cap."""
    gd = _pl.generated_docs_dir(project)
    if not gd.is_dir():
        gd = project / "generated_docs"
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return False, {}
    try:
        data = json.loads(p.read_text(errors="replace"))
    except Exception:
        return False, {}
    if not isinstance(data, dict):
        return False, {}
    # EXPLICIT boolean False only — a missing/true/string flag does NOT qualify.
    return (data.get("no_fsm_in_input") is False), data


def _extracted_fsm_state_names(l6_data: dict) -> set:
    """The set of already-extracted FSM-state names (case-insensitive,
    normalised upper), read from the L6 doc's fsm_states / states / state_table
    list-of-dicts. These are SUBTRACTED from the doc-scan candidates in
    key (c)."""
    out: set = set()
    states = (l6_data.get("fsm_states") or l6_data.get("states")
              or l6_data.get("state_table") or [])
    if isinstance(states, list):
        for s in states:
            if isinstance(s, dict):
                nm = s.get("name") or s.get("state")
            else:
                nm = s
            if isinstance(nm, str) and nm.strip():
                out.add(nm.strip().upper())
    # Multi-FSM container schema: fsms:[{name, states:[…]}, …]
    fsms = l6_data.get("fsms")
    if isinstance(fsms, list):
        for f in fsms:
            if isinstance(f, dict):
                for s in (f.get("states") or []):
                    if isinstance(s, dict):
                        nm = s.get("name") or s.get("state")
                    else:
                        nm = s
                    if isinstance(nm, str) and nm.strip():
                        out.add(nm.strip().upper())
    return out


def _doc_state_candidates_one_doc(text: str) -> set:
    """Round-3 key-(c) core: candidate uppercase FSM-state-name tokens in ONE
    doc's text. Two sources, unioned:

    (A) the plugin's OWN trusted extractor
        (phase1_doc_one_shot_runner._classify_modes_vs_states_from_text) — the
        SAME deterministic walker that populates L6.fsm_states. Consistent by
        construction (never finds a state the walker wouldn't), so it cannot
        diverge to either leak or over-block relative to the walker.

    (B) a SMALL set of HIGH-PRECISION enumeration positions for the explicit
        surface forms the trusted extractor's `state:`/`fsm states:` narrative
        anchor does not cover (lowercase `states: idle and active`, `from X to
        Y`, transition arrows, `the X state`, brace sets, bullet/table/numbered/
        `Step N:` rows, motion-verb-to-SHAPED, quoted-SHAPED, `S\\d+`). These are
        unambiguous enumerations; the loose copula/predicate/whole-region-shape
        scans that caused the over-blocks are deliberately ABSENT.

    Tokens normalised upper. The caller subtracts the stopword set + the already-
    extracted state names + their internal transition/action labels."""
    out: set = set()
    # ---- (A) trusted extractor (authoritative, walker-consistent) ----
    # ORGANIC #708 round-3 fix (third adversarial pass): the raw
    # `_classify_modes_vs_states_from_text` is GREEDY — its narrative regex
    # fires on any `state[s]?\s` / `mode[s]?\s` occurrence, captures the next
    # ~300 chars, and harvests EVERY all-caps token in that tail. On its own it
    # therefore OVER-BLOCKS: an ordinary sentence "… in the IDLE state. The
    # RGMII and SGMII MAC …" would pull RGMII/SGMII/MAC/CTRL_REG/… as "states".
    # The walker's REAL per-candidate guard is `_is_real_fsm_state` (±5-token
    # state-noun-context anchor + FSM blacklist + chip-part-number rejector),
    # which `_classify_modes_vs_states_from_text` does NOT apply on this path.
    # We re-apply it here so source (A) inherits the walker's exact precision —
    # a register/bus/IP/acronym token (not anchored to a real state-noun
    # context) is dropped, while a genuine state name (incl. one named DMA) that
    # IS state-context-anchored survives. This is what makes source (A)
    # over-block-SAFE AND walker-consistent.
    try:
        import sys as _sys
        if str(PROGRAMS_DIR) not in _sys.path:
            _sys.path.insert(0, str(PROGRAMS_DIR))
        import phase1_doc_one_shot_runner as _p1
        _op, _fsm = _p1._classify_modes_vs_states_from_text(text)
        for s in _fsm:
            if not (isinstance(s, str) and s.strip()):
                continue
            try:
                if _p1._is_real_fsm_state(s, text):
                    out.add(s.strip().upper())
            except Exception:
                # If the validator is unavailable, DROP the raw candidate
                # (fail-closed toward NOT over-collecting — the high-precision
                # positions below still catch explicit enumerations).
                continue
    except Exception:
        # Trusted extractor unavailable → fall back to the high-precision
        # positions only (still leak-safe; never silently empties the scan).
        pass
    # ---- (B) high-precision enumeration positions ----
    # IMPORTANT (three adversarial reviews): no deterministic scan can perfectly
    # separate an FSM-state enumeration from a register/bus/acronym enumeration
    # in natural datasheet prose — they are linguistically identical ("idle,
    # active, done" vs "AXI, AHB, APB"; "from IDLE to BUSY" vs "from CTRL_REG to
    # STATUS_REG"). This scan therefore errs toward OVER-COLLECTION: it catches
    # every explicit/position-anchored enumeration (the reviewer's required
    # forms, incl. a state named DMA) and may ALSO collect some register/bus
    # tokens. For a floor-RELAXING cap that is the SAFE error direction — an
    # over-collected token only makes _docs_name_no_further_fsm_states return
    # False → the cap conservatively does NOT fire → the design keeps FAILing
    # (the pre-#708 status quo). The cap NEVER relies on this scan ALONE to
    # FIRE: the firm fire-gate is no_fsm_in_input==false (key c) PLUS the AI
    # deep-review channel (keys d+e) — the strong LLM is the reliable judge of
    # "does this prose name an FSM state", which no regex is.
    for raw_line in text.splitlines():
        line = raw_line.strip()
        low = line.lower()
        m = _RE_STATES_LIST.search(line)
        if m:
            for ident in _IDENT_RE.findall(m.group(1)):
                out.add(ident.upper())
        for grp in _RE_BRACE_SET.findall(line):
            for ident in _IDENT_RE.findall(grp):
                out.add(ident.upper())
        for a, b in _RE_ARROW.findall(line):
            out.add(a.upper()); out.add(b.upper())
        for a, b in _RE_FROM_TO.findall(line):
            out.add(a.upper()); out.add(b.upper())
        for a in _RE_IN_X_STATE.findall(line):
            out.add(a.upper())
        for a in _RE_X_STATE.findall(line):
            out.add(a.upper())
        for a in _RE_VERB_STATE.findall(line):
            if _token_is_state_shaped(a):
                out.add(a.upper())
        for a in _RE_COPULA_STATE.findall(line):
            if _token_is_state_shaped(a):
                out.add(a.upper())
        for a in _RE_LIST_VERB.findall(line):
            for ident in _IDENT_RE.findall(a):
                out.add(ident.upper())
        for a in _RE_DENOTES.findall(line):
            if _token_is_state_shaped(a):
                out.add(a.upper())
        for m2 in _FSM_STATE_SHORT_RE.findall(line):
            out.add(m2.upper())
        for q in _RE_QUOTED.findall(line):
            if _token_is_state_shaped(q):
                out.add(q.upper())
        if (low.startswith(("-", "*", "+", "•"))
                or line.startswith("|") or "|" in line
                or re.match(r"^\d+[\.\)]", line)
                or re.match(r"^step\s+\d+", low)):
            for ident in _IDENT_RE.findall(line):
                out.add(ident.upper())
    return out


def _doc_fsm_state_literals(text: str) -> set:
    """KEY (c) SUPPLEMENT — return doc-named FSM-state-name candidates in `text`,
    MINUS the grammatical/doc-structural stopword set. Anchored on the plugin's
    own trusted FSM-state extractor (filtered through its `_is_real_fsm_state`
    guard) PLUS explicit-enumeration positions (see _doc_state_candidates_one_doc).

    DESIGN NOTE (three adversarial reviews): natural datasheet prose makes an
    FSM-state enumeration and a register/bus/acronym enumeration syntactically
    indistinguishable, so NO deterministic scan is simultaneously leak-free and
    over-block-free. This scan deliberately errs toward OVER-COLLECTION (catches
    every explicit enumeration incl. a state named DMA; may also collect some
    register/bus tokens). For a floor-RELAXING cap that is the SAFE direction:
    an over-collected token only makes _docs_name_no_further_fsm_states return
    False → the cap conservatively does NOT fire → the design keeps FAILing (the
    pre-#708 status quo, never a NEW defect-ship). The cap's FIRE decision does
    NOT rest on this scan alone — see _reused_ip_rtl_only_fsm_cap_eligible keys
    (c)=no_fsm_in_input + (d)+(e)=the AI deep-review channel, which is the
    reliable judge of doc-named states that a regex cannot be."""
    return _doc_state_candidates_one_doc(text) - _FSM_STOPWORDS


def _l6_prose_text(l6_data: dict) -> str:
    """Collect the L6 doc's human-PROSE strings (description / notes / summary /
    comment / overview / behaviour text) — NOT its structured JSON keys/values.
    Scanning the raw L6 JSON serialization would wrongly pick up the field name
    `fsm_states` and the transition/action LABELS of the ALREADY-extracted
    states (e.g. "start"/"hold") as if they were further state names. We instead
    walk the dict and concatenate string values under prose-bearing keys."""
    PROSE_KEYS = ("description", "desc", "notes", "note", "summary", "overview",
                  "comment", "comments", "behavior", "behaviour", "details",
                  "text", "prose", "rationale", "remarks")
    chunks: List[str] = []

    def _walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                kl = str(k).lower()
                if isinstance(v, str) and any(p in kl for p in PROSE_KEYS):
                    chunks.append(v)
                else:
                    _walk(v)
        elif isinstance(obj, list):
            for it in obj:
                _walk(it)

    _walk(l6_data)
    return "\n".join(chunks)


def _extracted_state_internals(l6_data: dict) -> set:
    """The transition/action/next/output LABELS belonging to the
    already-extracted FSM states (normalised upper). These are INTERNALS of
    extracted states, never NEW states, so they are subtracted from the doc
    candidates to avoid false-positives (e.g. a state {name:IDLE,
    transitions:[start], actions:[hold]} must not make `start`/`hold` look like
    undiscovered states)."""
    out: set = set()

    def _collect_labels(states) -> None:
        if not isinstance(states, list):
            return
        for s in states:
            if not isinstance(s, dict):
                continue
            for key in ("transitions", "actions", "next", "on", "outputs",
                        "output", "events", "guards", "conditions"):
                v = s.get(key)
                if isinstance(v, str):
                    for ident in _IDENT_RE.findall(v):
                        out.add(ident.upper())
                elif isinstance(v, list):
                    for item in v:
                        if isinstance(item, str):
                            for ident in _IDENT_RE.findall(item):
                                out.add(ident.upper())
                        elif isinstance(item, dict):
                            for iv in item.values():
                                if isinstance(iv, str):
                                    for ident in _IDENT_RE.findall(iv):
                                        out.add(ident.upper())

    _collect_labels(l6_data.get("fsm_states") or l6_data.get("states")
                    or l6_data.get("state_table"))
    fsms = l6_data.get("fsms")
    if isinstance(fsms, list):
        for f in fsms:
            if isinstance(f, dict):
                _collect_labels(f.get("states"))
    return out


def _docs_name_no_further_fsm_states(project: Path, l6_data: dict) -> bool:
    """KEY (c): scanning the INPUT DOCS (input/docs/*, phase1/input_doc/*) AND
    the L6 doc's own PROSE, there is NO FSM-state-name literal beyond the
    already-extracted fsm_states set.

    Returns True ONLY when the remainder (doc candidates − extracted state names
    − extracted state internal labels) is EMPTY. A non-empty remainder → a
    doc-enumerated state the walker MISSED → return False so the design keeps
    FAILing (surfacing the real walker bug — the load-bearing leak guard).
    Unreadable docs → False (fail-closed)."""
    extracted = _extracted_fsm_state_names(l6_data)
    internals = _extracted_state_internals(l6_data)
    blobs: List[str] = []
    read_any = False
    # The L6 doc's own PROSE only (NOT the raw JSON: see _l6_prose_text).
    try:
        l6_path = (_pl.generated_docs_dir(project) / "L6_CONTROL_LOGIC.json")
        if not l6_path.is_file():
            l6_path = project / "generated_docs" / "L6_CONTROL_LOGIC.json"
        if l6_path.is_file():
            try:
                _l6 = json.loads(l6_path.read_text(errors="replace"))
            except Exception:
                _l6 = l6_data if isinstance(l6_data, dict) else {}
            blobs.append(_l6_prose_text(_l6 if isinstance(_l6, dict)
                                        else (l6_data or {})))
            read_any = True
    except Exception:
        return False
    # Input docs (Path A verbatim extracts + any input/docs/ corpus). These are
    # raw human docs → scanned in full.
    doc_dirs = [
        project / "input" / "docs",
        _pl.input_doc_dir(project),          # phase1/input_doc
        project / "phase1" / "input_doc",
    ]
    seen_dirs: set = set()
    for d in doc_dirs:
        try:
            rp = d.resolve()
        except Exception:
            rp = d
        if rp in seen_dirs:
            continue
        seen_dirs.add(rp)
        if not d.is_dir():
            continue
        for f in sorted(d.rglob("*")):
            if not f.is_file():
                continue
            if f.suffix.lower() not in (
                    ".txt", ".md", ".json", ".rst", ".csv",
                    ".log", ".yaml", ".yml", ""):
                continue
            # ORGANIC #708 round-2 (field-agent reopen) — RTL files
            # (.v/.sv/.svh) are EXCLUDED from the doc-enumeration scan. RTL is
            # NOT a "doc". A reused-IP design routinely STAGES a vendor RTL
            # package under input/docs/ (e.g. input/docs/<core>_pkg.sv with
            # `typedef enum {BOOT_SET, FIRST_FETCH, WAIT_SLEEP, ...}`). Those are
            # the EXACT RTL-only state names whose RTL-only-ness is THIS cap's
            # whole justification — scanning the RTL therefore GUARANTEES a
            # non-empty remainder, so key (c) is always False and the cap is a
            # FUNCTIONAL NO-OP on the very artifact it exists for (the v1.0.67/68
            # over-block the field agent reopened: 1151–1732 remainder tokens,
            # never 0). The earlier "scan broadly incl .v/.sv → fires LESS → SAFE"
            # reasoning was wrong: it makes the cap unable to EVER fire.
            # §4.05 NO-LEAK is preserved by the cap's other keys: a 2nd state
            # present ONLY in RTL and NOT in any human doc is PRECISELY the
            # RTL-only-FSM case to defer; human docs are .txt/.md/.rst/.json,
            # never .v/.sv/.svh. (The L6 generated doc is read prose-only via
            # _l6_prose_text; its structured fsm_states/transition labels are
            # extraction internals, not doc-enumerated states.)
            try:
                blobs.append(f.read_text(errors="replace"))
                read_any = True
            except Exception:
                return False
    if not read_any:
        return False  # cannot read the docs at all → fail-closed (no leak)
    candidates: set = set()
    for blob in blobs:
        candidates |= _doc_fsm_state_literals(blob)
    # Stopwords/FSM-vocabulary are already subtracted inside
    # _doc_fsm_state_literals; here the already-extracted state NAMES and their
    # internal transition/action LABELS are removed (case-insensitive). A
    # non-empty remainder = a doc-enumerated 2nd state the walker missed →
    # key (c) False (still FAIL, no leak).
    remainder = candidates - extracted - internals
    return len(remainder) == 0


def _sidecar_has_qualifying_fsm_patch(project: Path) -> bool:
    """KEY (d): True iff #706's ai_deep_review sidecar carries ≥1 layer-6 entry
    that passes the FSM typed shape (name + transitions/actions). If the strong
    AI deep-review CAN recover a doc-traceable 2nd state, it must lift the count
    via #706 — so a present qualifying FSM patch makes the cap NOT fire. Reuses
    the SAME helpers the #706 field-count gate uses (no looser channel)."""
    import sys as _sys
    if str(PROGRAMS_DIR) not in _sys.path:
        _sys.path.insert(0, str(PROGRAMS_DIR))
    try:
        import l_doc_structured_field_count_check as _fc
        sidecar = _fc._load_field_count_sidecar(project)
    except Exception:
        # Fail-closed for the CAP's purpose: if we cannot determine the
        # sidecar state, do NOT defer — keep FAILing (safe direction).
        return True
    entries = sidecar.get(6) or []
    spec = _fc._SIDECAR_FLOOR_LAYERS.get(6)
    if not spec:
        return False
    _aliases, name_keys, shape_keys = spec
    for e in entries:
        try:
            if _fc._typed_patch_ok(e, name_keys, shape_keys):
                return True
        except Exception:
            continue
    return False


def _field_count_fail_is_solely_fsm_floor(gate_stdout: str) -> bool:
    """ORGANIC #708 round-2 fix (2): demote ONLY when the field-count gate's
    failure is SOLELY the L6 fsm_states floor — never when another floor (e.g.
    the L9 ≥3-typed-structural-fields floor, or an L3 opcode floor) ALSO failed
    on the same gate, which the by-name demotion would MASK.

    The gate prints one detail line per failing L doc:
        FAIL — Wave 31/32 (...): N L doc(s) carry fewer ...:
          - L6_CONTROL_LOGIC.json: L6 control_logic must carry ≥2 typed FSM
            states in `fsm_states` ...
          - L9_INTEGRATION.json: L9 integration_spec must carry ≥3 ...
    We collect every `  - <Ldoc>: <reason>` detail line and require that AT
    LEAST ONE names the fsm_states floor AND EVERY such detail line names it.
    If no detail lines parse (unexpected format) → False (fail-closed: keep the
    FAIL rather than risk masking)."""
    detail_lines = []
    for raw in gate_stdout.splitlines():
        s = raw.strip()
        # Per-doc detail lines are rendered as "- <Ldoc.json>: <reason>".
        if s.startswith("- ") and ".json:" in s.lower():
            detail_lines.append(s)
    if not detail_lines:
        return False
    saw_fsm = False
    for ln in detail_lines:
        lo = ln.lower()
        # The L6 FSM-states floor line uniquely carries one of the L6
        # control-logic discriminator phrases (NOT a bare `fsm_states`, which
        # also appears in the L9 line's allowed-field list — round-2 fix (2)).
        is_fsm = any(d in lo for d in _L6_FSM_FLOOR_DISCRIMINATORS)
        if is_fsm:
            saw_fsm = True
        else:
            # A non-FSM floor also failed → do NOT demote (would mask it).
            return False
    return saw_fsm


def _ai_deep_review_sidecar_present(project: Path) -> bool:
    """ORGANIC #708 round-3 — KEY (e): the #706 ai_deep_review sidecar FILE
    EXISTS (a parseable phase1/ai_deep_review_patches.json). This is positive,
    deterministic evidence that the STRONG AI deep-review channel actually
    examined the input docs for FSM-state content — the AI-ADJUDICATION exit the
    classifier doctrine requires for a non-deterministic NL judgment.

    WHY it is load-bearing: key (c)'s deterministic doc-scan is over-block-SAFE
    but, by that conservatism, cannot reliably parse PURE-LOWERCASE-PROSE state
    enumerations (e.g. "the sequence; idle; active; done") that lack an explicit
    position keyword or the universal UPPERCASE state-name convention. Rather
    than chase those with an ever-more-aggressive regex (which empirically
    re-introduces acronym/register OVER-BLOCKS — wrongly FAILing correct reused-
    IP designs), the cap requires that an AI deep-review HAS RUN. The AI is the
    reliable judge of "do the docs name an FSM state the deterministic walker
    missed"; if it ran and produced no qualifying FSM patch (key (d)), that is a
    far stronger no-missed-state signal than any regex. If the sidecar is ABSENT
    (no AI deep-review ran), the cap fail-closes (returns no deferral) — the
    design keeps FAILing, exactly the pre-#708 status quo (SAFE: a floor-relaxing
    cap must never fire on un-reviewed docs). Parse error / absent → False."""
    try:
        side = _pl.phase1_ai_deep_review_patches_file(project)
    except Exception:
        return False
    if not side.is_file():
        return False
    try:
        json.loads(side.read_text(errors="replace"))
    except Exception:
        return False
    return True


def _reused_ip_rtl_only_fsm_cap_eligible(project: Path) -> bool:
    """ORGANIC #708 — fail-closed deferral cap for the L6 ≥2-fsm_states floor
    FAIL of `l_doc_structured_field_count_check` on a REUSED-IP design whose
    control FSM lives ONLY in vendor RTL. ALL keys must hold; any single false
    key keeps the FAIL (no leak). Orthogonal to _is_thin_input_eligible: fires
    at 100% completeness, the regime thin-input does NOT cover.

    (a) class rtl_gen=null + vendor/reused RTL present,
    (b) completeness == 100% AND input not tiny (negation of thin-input cover),
    (c1) L6 records no_fsm_in_input==false (the IP honestly HAS an FSM),
    (e) the #706 ai_deep_review sidecar FILE is PRESENT — positive evidence the
        strong AI channel examined the docs for FSM content,
    (d) and it yielded ZERO qualifying FSM patch (the AI found no doc-traceable
        2nd state to recover — else lift via #706, cap not needed).

    ORGANIC #708 round-3 (field-agent reopen, DIRECTION (b)) — the deterministic
    `_docs_name_no_further_fsm_states` prose-scan veto is REMOVED from the
    conjunction. It provably can NEVER return True on real CPU documentation:
    distinguishing an FSM-state-name literal from an ordinary capitalized doc
    token (ACCESS / DECODE / FLUSH / ACTION / ...) is an irreducible NL judgment
    a regex cannot make, so the candidate scan over-collects an always-non-empty
    remainder (the field agent measured 1087–1732 tokens across three rounds,
    never 0) → the cap was a FUNCTIONAL NO-OP on the very reused-IP artifact it
    exists for (3 consecutive no-ops). Per the classifier three-tier doctrine,
    the irreducible "did the docs name a state the walker missed?" judgment is
    ROUTED to the AI-adjudication channel that already exists — the MANDATORY
    #706 ai_deep_review — instead of a deterministic regex that can't decide it.

    §4.05 NO-LEAK (preserved WITHOUT the prose-scan veto): a genuinely
    doc-enumerated 2nd state is recovered by ONE of two independent extractors,
    BOTH gating the cap off — never deferred:
      * the deterministic L6 FSM prose-walker extracts it → count ≥ floor → the
        field-count gate PASSES and this cap is never consulted; AND/OR
      * the mandatory AI deep-review (key (e) ran) reads the SAME prose with NL
        judgment and emits a qualifying FSM patch → key (d) flips → the count is
        lifted to ≥ floor via #706 (PASS on merit, cap not engaged).
    The cap engages ONLY when the walker extracted < floor AND the AI deep-review
    ALSO found nothing doc-traceable — i.e. the state genuinely lives only in
    vendor RTL. A from-scratch design is excluded by (a); a thin (<100%) design
    routes to thin-input by (b). Resting on the strongest available evidence (the
    AI deep-review) is the honest fail-closed position; a provably-undecidable
    regex veto is not."""
    # (a) — class + vendor RTL.
    if not _detected_class_rtl_gen_null_and_vendor_rtl(project):
        return False
    # (b) — 100% completeness, not tiny (else thin-input owns it).
    if not _completeness_is_full_and_not_tiny(project):
        return False
    # (c1) — L6 honestly records an FSM is present (no_fsm_in_input==false).
    no_fsm_is_false, _l6_data = _l6_doc_records_fsm_present(project)
    if not no_fsm_is_false:
        return False
    # (e) — AI deep-review must have RUN (sidecar file present): the residual
    #       NL judgment ("did the docs name a state the walker missed?") rests on
    #       the strong AI channel (#708 round-3 direction (b)), NOT on a
    #       deterministic prose scan that provably over-collects on real docs.
    if not _ai_deep_review_sidecar_present(project):
        return False
    # (d) — and it yielded no qualifying FSM patch (else lift via #706).
    if _sidecar_has_qualifying_fsm_patch(project):
        return False
    return True


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


# ORGANIC-20260614 (#632) — structural-name prefixes that identify the
# analog / mixed-signal sub-gates inside the P0 structural-RTL umbrella.
# Derived from the canonical gate FILE names (analog_*, mixed_signal_*,
# pdk_analog_*, spice_correlation_*), NOT from any chip / vendor / SKU
# literal — so it auto-extends as new analog gates are registered in
# `_STRUCTURAL_RTL_GATES` and stays chip-AGNOSTIC. This is the same
# naming convention `_CLASS_SKIPPABLE_ANALOG_GATES` (above) already keys
# off and that the A-step (A1..A9) suppression uses.
_ANALOG_STRUCTURAL_GATE_PREFIXES: tuple[str, ...] = (
    "analog_",
    "mixed_signal_",
    "pdk_analog_",
    "spice_correlation_",
)


def _is_analog_structural_gate(gate_name: str) -> bool:
    """True when `gate_name` is an analog / mixed-signal sub-gate of the
    P0 structural-RTL umbrella (by canonical file-name prefix).

    chip-AGNOSTIC: matches on the gate program's own name prefix, never
    on a chip / vendor / SKU string. `_skip_analog_p0_gates()` filters
    this against the registered `_STRUCTURAL_RTL_GATES` tuple so only
    real, registered gates are ever returned.
    """
    return any(gate_name.startswith(p)
               for p in _ANALOG_STRUCTURAL_GATE_PREFIXES)


def _skip_analog_p0_gates() -> frozenset[str]:
    """The set of analog / mixed-signal structural-RTL gates suppressed
    by `--skip-analog` inside the P0 umbrella.

    Derived from `_STRUCTURAL_RTL_GATES` (the single source of truth for
    which gates the umbrella runs) by analog name-prefix — so it can
    never name a gate that the umbrella does not actually run, and it
    auto-extends when new analog gates are added. chip-AGNOSTIC.
    """
    return frozenset(
        g for g in _STRUCTURAL_RTL_GATES if _is_analog_structural_gate(g)
    )


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


_ANALOG_IFACE_NA_CACHE: Dict[str, Tuple[bool, str]] = {}


def _digital_backend_is_na(project: Path) -> Tuple[bool, str]:
    """True when the digital RTL→GDS backend stages are N/A for this project —
    EITHER because it is a pure-analog class (registry contract), OR (ORGANIC
    #141) because it is an analog-APPLICABLE class whose ACTUAL L9 top
    interface exposes NO digital clock/reset/data INPUT (all-analog: analog
    ins, analog supplies/refs, raw 1-bit modulator-bitstream OUTs). The latter
    is the interface-aware discriminator: a `data_converter` with an all-analog
    pinout has no honest synthesizable digital datapath to author, so its
    digital steps are N/A (like the analog A-steps on a digital-only design),
    NOT a hard-FAIL on the absent RTL. A converter that DOES expose a digital
    clk/rst/data interface keeps its digital track.

    Fail-CLOSED + chip-AGNOSTIC (mirrors `_project_is_pure_analog`): requires
    NO synthesisable RTL present, an analog-applicable class, an analog block
    list, AND the structural all-analog-interface signal."""
    # (1) the registry-contract pure-analog path (unchanged).
    is_pa, pa_reason = _project_is_pure_analog(project)
    if is_pa:
        return (True, pa_reason)

    key = str(project.resolve())
    if key in _ANALOG_IFACE_NA_CACHE:
        return _ANALOG_IFACE_NA_CACHE[key]
    result: Tuple[bool, str] = (False, "")
    try:
        # (2) no synthesisable RTL may exist (a real digital datapath present →
        # the digital backend is NOT N/A).
        for cand in ("phase2/stage1/rtl", "rtl", "src", "hdl"):
            d = project / cand
            if d.is_dir() and (any(d.glob("*.sv")) or any(d.glob("*.v"))):
                _ANALOG_IFACE_NA_CACHE[key] = result
                return result
        # (3) analog-applicable class + analog block list (guards a digital
        # project that merely lacks RTL from being mislabelled).
        import sys as _sys
        if str(PROGRAMS_DIR) not in _sys.path:
            _sys.path.insert(0, str(PROGRAMS_DIR))
        from ic_class_profile import detect_ic_class as _detect
        profile = _detect(project) or {}
        ic_class = str(profile.get("ic_class") or "unknown")
        analog_applicable = False
        try:
            reg = json.loads((PROGRAMS_DIR / "ic_class_registry.json").read_text())
            for c in (reg.get("classes") or []):
                if (c.get("name") == ic_class
                        or ic_class in (c.get("synonyms") or [])):
                    analog_applicable = bool(c.get("analog_applicable"))
                    break
        except Exception:
            analog_applicable = bool(profile.get("is_mixed_signal")
                                     or profile.get("is_pure_analog"))
        if not analog_applicable:
            _ANALOG_IFACE_NA_CACHE[key] = result
            return result
        if not _has_canonical_analog_blocks(project):
            _ANALOG_IFACE_NA_CACHE[key] = result
            return result
        # (4) the structural all-analog-interface signal.
        import analog_interface_classify as _aic
        absent, why, _ev = _aic.digital_datapath_absent(project)
        if absent:
            result = (
                True,
                f"analog-applicable class {ic_class!r} with an all-analog top "
                f"interface ({why}); no digital RTL — digital backend "
                f"(stages 1-4) + mixed-signal replaced by the analog A1..A9 "
                f"track")
    except Exception as e:
        result = (False, f"interface-aware N/A detection unavailable: {e}")
    _ANALOG_IFACE_NA_CACHE[key] = result
    return result


def _run_structural_rtl_gates(project: Path,
                              strict_timing: bool = False,
                              allow_thin_input: bool = False,
                              skip_analog: bool = False
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

    ORGANIC-20260614 (#632) — when ``skip_analog=True`` the analog /
    mixed-signal sub-gates of this umbrella (``_skip_analog_p0_gates()``)
    are DOWNGRADED to a SKIP entry with a deferred-track reason instead
    of being run / FAILed — mirroring the A-step (A1..A9) suppression in
    ``check_step`` and the ``--skip-hardware`` FPGA-board downgrade. This
    is the SAME mechanism the per-IC-class ``_class_skipped_gates`` skip
    uses, so a deferred-analog digital deliverable can reach
    PASS_WITH_WAIVERS while the analog track is an explicit deferred
    open-work item (review_required at analog / foundry sign-off). The
    NON-analog gates still run and still FAIL — the flag never relaxes a
    digital floor (an empty / digital-only doc is unaffected; this only
    changes how the analog sub-gates report under the explicit flag).
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
    # ORGANIC-20260614 (#632) — --skip-analog suppression of the analog /
    # mixed-signal sub-gates inside this umbrella. Only active when the
    # flag is explicitly set; derived from `_STRUCTURAL_RTL_GATES` by
    # analog name-prefix so it stays chip-AGNOSTIC and never names a
    # gate the umbrella does not run.
    analog_skip_gates = _skip_analog_p0_gates() if skip_analog else frozenset()
    # ── #NNN: parallel structural-gate evaluation ─────────────────────────
    # Each structural gate is an INDEPENDENT read-only validator run as its own
    # subprocess with `cwd=project` (no `os.chdir`); the only per-gate output is
    # a (skip|waiver|fail|pass) classification of its result. So the gates can
    # run CONCURRENTLY — this is the dominant cost on structural-heavy chips
    # (a ~200-gate P0 umbrella) — as long as the fails/skips/waivers
    # lists stay in canonical `_STRUCTURAL_RTL_GATES` order (they feed the JSON
    # report + verdict). The worker below is EXACTLY the former loop body,
    # returning `(kind, payload)` instead of appending in place; the ordered
    # dispatch loop then appends in gate order, so the report is byte-identical
    # to the sequential path (env `VIBE_IC_COMPLIANCE_WORKERS=1` forces serial).
    def _eval_gate_worker(gate_name: str):
        prog = PROGRAMS_DIR / f"{gate_name}.py"
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
            return ("fail", f"FAIL: {gate_name} timed out")
        if r.returncode == 2:
            return ("skip", gate_name)
        elif r.returncode == 1:
            _full_out = (r.stdout.strip() or r.stderr.strip())
            first_line = _full_out.split("\n")[0][:200]
            # ORGANIC #708 — the L6 ≥2-fsm_states floor message lands on a
            # detail line ("  - L6_…: L6 control_logic must carry ≥N typed FSM
            # states in `fsm_states` …"), NOT the umbrella's first header line
            # ("FAIL — Wave 31/32 …"). Scan the FULL gate output (case-
            # insensitive) using the L6-specific discriminator phrases (round-2
            # fix (2): a bare `fsm_states` token also matches the L9 line) so the
            # cap recognises the L6 floor precisely; record that exact floor
            # line as the cap's first_line evidence.
            _out_lower = _full_out.lower()
            _names_fsm_floor = any(
                d in _out_lower for d in _L6_FSM_FLOOR_DISCRIMINATORS)
            _fsm_floor_line = first_line
            if _names_fsm_floor:
                for _ln in _full_out.split("\n"):
                    if any(d in _ln.lower()
                           for d in _L6_FSM_FLOOR_DISCRIMINATORS):
                        _fsm_floor_line = _ln.strip()[:200]
                        break
            # v1.6.97 — thin-input waiver eligibility.
            # v1.6.98 — eligibility shifted to coverage-shape; see
            # _is_thin_input_eligible.
            if (thin_input_eligible
                    and gate_name in _THIN_INPUT_WAIVER_GATES):
                return ("waiver", {
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
            # ORGANIC #708 — ORTHOGONAL reused-IP RTL-only-FSM deferral cap.
            # Fires at 100% completeness (the regime thin-input does NOT cover)
            # for the L6 ≥2-fsm_states floor FAIL of
            # `l_doc_structured_field_count_check` ONLY. Entirely separate from
            # thin_input_eligible above (no double-demote: key (b) requires
            # 100% capture, which makes _is_thin_input_eligible False). Gated on
            # the gate output naming the FSM-states floor, the failure being
            # SOLELY the FSM floor (round-2 fix (2): a co-occurring L9/L3 floor
            # FAIL must NOT be masked), AND all four keys of
            # _reused_ip_rtl_only_fsm_cap_eligible. Otherwise the FAIL
            # propagates exactly as today (fail-closed).
            elif (gate_name == _REUSED_IP_RTL_ONLY_FSM_CAP_GATE
                  and _names_fsm_floor
                  and _field_count_fail_is_solely_fsm_floor(_full_out)
                  and _reused_ip_rtl_only_fsm_cap_eligible(project)):
                return ("waiver", {
                    "gate": gate_name,
                    "review_required": True,
                    "ticket": _REUSED_IP_RTL_ONLY_FSM_CAP_TICKET,
                    "evidence": (
                        "reused-IP RTL-only FSM: the detected IC class has "
                        "rtl_gen=null (vendor/reused RTL present) and the L6 "
                        "control FSM exists ONLY in vendor RTL — no input doc "
                        "enumerates a 2nd FSM-state literal beyond the "
                        "extracted set, the #706 ai_deep_review sidecar yielded "
                        "no qualifying FSM patch, and completeness is 100% "
                        "(so --allow-thin-input does not apply). Inventing a "
                        "doc-traceable 2nd state would be fabrication; the L6 "
                        "≥2-fsm_states floor is DEFERRED to vendor-RTL FSM "
                        "review instead of FAILing a structurally-correct "
                        "extraction."),
                    "reason": (
                        "reused-IP RTL-only FSM (class rtl_gen=null + vendor "
                        "RTL + 100% completeness + no further doc state literal "
                        "+ no #706 FSM patch)"),
                    "first_line": _fsm_floor_line,
                })
            else:
                return ("fail", f"FAIL: {gate_name} — {first_line}")
        return ("pass", None)

    # Build the ordered task list: filter-skips resolve immediately (preserving
    # their position); runnable gates are submitted to the pool. Then dispatch
    # every result into fails/skips/waivers in canonical gate order.
    _sworkers = _compliance_workers(len(_STRUCTURAL_RTL_GATES))
    _pending: List[tuple] = []  # (tag, item) tag∈{"imm","fut"}
    _ex = ThreadPoolExecutor(max_workers=_sworkers) if _sworkers > 1 else None
    try:
        for gate_name in _STRUCTURAL_RTL_GATES:
            prog = PROGRAMS_DIR / f"{gate_name}.py"
            if not prog.exists():
                continue
            if gate_name in class_skips:
                _pending.append(
                    ("imm", ("skip",
                             f"{gate_name} (SKIP: {class_skips[gate_name]})")))
                continue
            if gate_name in analog_skip_gates:
                _pending.append(
                    ("imm", ("skip",
                             f"{gate_name} (SKIP: analog track deferred via "
                             "--skip-analog (review_required at analog / "
                             "foundry sign-off))")))
                continue
            if _ex is not None:
                _pending.append(("fut", _ex.submit(_eval_gate_worker, gate_name)))
            else:
                _pending.append(("imm", _eval_gate_worker(gate_name)))
        for _tag, _item in _pending:
            kind, payload = _item if _tag == "imm" else _item.result()
            if kind == "skip":
                skips.append(payload)
            elif kind == "waiver":
                waivers.append(payload)
            elif kind == "fail":
                fails.append(payload)
            # "pass" → nothing appended
    finally:
        if _ex is not None:
            _ex.shutdown(wait=True)

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
            # ORGANIC #608 — the success field is ABSENT. If the SAME artifact
            # HONESTLY self-reports it was skipped (verdict ∈ SKIP/…), this is a
            # legitimate no-evidence skip (e.g. a hardware-skipped FPGA-final
            # run whose on_board_pass.json says {"verdict":"SKIP"}), NOT a
            # fabricated PASS or a real FAIL — promote to SKIPPED-CONDITION via
            # the skip hint. (#433c doctrine; only fires on the ABSENT-field
            # path, so a present-but-false field still FAILs.)
            if isinstance(data, dict):
                _vd = str(data.get("verdict", "")).upper().replace("_", "-")
                if _vd in _SELF_SKIP_VERDICTS:
                    return True, (f"{_SKIP_HINT_PREFIX}{rel}: artifact "
                                  f"self-reports verdict={_vd} (field "
                                  f"{field_key!r} N/A on a skipped run)")
            return False, f"field not found: {field_key}"
        v = v[part]
    return (v == expect), f"{field_key} = {v!r}"


# ORGANIC #789 GAP-B — --skip-analog forwarding into optional/required gate
# commands.
#
# The P0 structural-RTL umbrella (#632) and the final-audit aggregation
# (#609) already honour ``skip_analog`` by SUPPRESSING analog sub-gates.
# But the per-step ``optional_program_exit_zero`` / ``program_exit_zero``
# gate branches ran ``spec["command"]`` VERBATIM and never forwarded the
# flag. So an analog-aware gate that ITSELF knows how to defer its
# analog-only cases under ``--skip-analog`` (e.g. the L10/L12 tb-conformance
# gates, #773) was invoked WITHOUT it — and hard-FAILed Step 4 for a
# legitimately-deferred analog track. This is a WIRING gap, not a gate-logic
# gap: the gate CAN honour the flag; the runner just never handed it over.
#
# The fix is generic + structural: when ``skip_analog`` is set, we ask the
# gate's OWN program (via its ``--help``) whether it ACCEPTS ``--skip-analog``
# and only then append it. There is NO chip / vendor / SKU / program literal
# anywhere — the decision is "does this program's argparse declare the flag",
# discovered at runtime, so it auto-extends to any future analog-aware gate
# and never touches a gate that doesn't opt in.
@functools.lru_cache(maxsize=256)
def _program_accepts_flag(prog_name: str, flag: str) -> bool:
    """True iff the gate program named ``prog_name`` declares ``flag`` in its
    ``--help`` output. chip-AGNOSTIC + structural: a capability probe of the
    program's own argparse, never a hard-coded program/chip allow-list.

    Fail-closed: any resolution / probe error returns False so the flag is
    NOT appended (the gate runs exactly as before — no behaviour change).
    Cached so a single compliance run probes each program at most once.
    """
    try:
        prog = prog_name if prog_name.endswith(".py") else f"{prog_name}.py"
        prog_path = PROGRAMS_DIR / prog
        if not prog_path.is_file():
            return False
        r = subprocess.run(
            [sys.executable, str(prog_path), "--help"],
            capture_output=True, text=True, timeout=30,
        )
        help_text = (r.stdout or "") + (r.stderr or "")
        # Match the flag as a whole token (argparse renders it as `--skip-analog`
        # possibly followed by space / `=` / `,` / newline / metavar).
        return bool(re.search(rf"(?<![\w-]){re.escape(flag)}(?![\w-])",
                              help_text))
    except Exception:
        return False


def _resolve_skip_analog_anchor(project: Path) -> Optional[str]:
    """Resolve a REVIEWABLE capability-gap anchor for an analog-deferral
    waiver, mirroring the precedence the analog-aware gates use themselves
    (#773 ``analog_skip_anchor``): the runner's connectivity-bridge
    ``sim/results.xml``. Returns the RELATIVE path string if a candidate FILE
    exists (resolved relative to the project, which is the cwd the gate program
    runs under), else None (the gate then re-FAILs an unanchored deferral — no
    blanket pass). chip-AGNOSTIC: structural project paths, no chip literal."""
    for rel in ("phase2/stage1/sim/results.xml",
                "sim/results.xml",
                "reports/sim/results.xml"):
        cand = project / rel
        if cand.is_file():
            return rel
    return None


# ORGANIC #171 (A11) — the Step-4 Simulation artifact gate keys on the canonical
# connectivity-bridge outputs (`phase2/stage1/sim/results.xml` OR `.../pass.flag`).
# A design whose functional oracle IS derivable (e.g. the spm bit-serial
# multiplier) gets a REAL cocotb functional PASS from `professional_tb_gen`,
# written under `phase2/stage1/sim_professional/<top>/results.xml` (a genuine
# streaming-scoreboard transcript, failures=0). The runner does not ALSO emit the
# canonical `sim/results.xml` / `pass.flag` for that class, so the files_exist gate
# hard-FAILed Step-4 even though functional verification actually CLOSED. This
# helper recognises that real professional-TB PASS as satisfying the Step-4
# simulation-evidence requirement — the exact sibling of the coverage self-skip
# supersede (#654) that already reads the SAME transcript at the coverage gate.
#
# §4.05 / anti-fabrication: fires ONLY when (a) the FAILing gate is the sim
# functional-evidence gate — its missing set names `phase2/stage1/sim/results.xml`
# — AND (b) `_srb.find_professional_tb_pass` returns a REAL PASS (tests>0,
# failures==0, errors==0, passed>0). A missing / failing / vacuous professional
# result → None → the gate stays FAILed EXACTLY as before. It never turns a fail
# into a pass; it only recognises a transcript the canonical-path-only check could
# not see. chip/PDK-AGNOSTIC: structural paths + JUnit structure, no chip literal.
_SIM_STEP4_CANONICAL_RESULTS = "phase2/stage1/sim/results.xml"


def _sim_files_superseded_by_professional_tb(
        project: Path, missing_patterns: List[str]) -> Optional[str]:
    """Return a reviewable reason string when a FAILing Step-4 sim ``files_exist``
    gate is SUPERSEDED by a real ``professional_tb`` functional PASS, else None.

    Scoped to the Step-4 simulation-evidence gate: at least one missing pattern
    must be the canonical ``phase2/stage1/sim/results.xml`` (the functional-sim
    connectivity bridge). For any OTHER ``files_exist`` gate this returns None →
    byte-identical behaviour. Anti-fabrication is delegated to
    ``_srb.find_professional_tb_pass`` (real functional PASS only). chip-AGNOSTIC."""
    if not any(_SIM_STEP4_CANONICAL_RESULTS in (p or "")
               for p in missing_patterns):
        return None
    pro = _srb.find_professional_tb_pass(project)
    if not pro:
        return None
    return (f"Step-4 sim evidence: canonical {_SIM_STEP4_CANONICAL_RESULTS} / "
            f"pass.flag absent, but a REAL professional_tb functional PASS is "
            f"present at {pro.get('rel_path')} (tests={pro.get('tests')}, "
            f"failures={pro.get('failures')}, errors={pro.get('errors')}, "
            f"passed={pro.get('passed')}) — accepted as Step-4 functional-sim "
            f"evidence (#171).")


def _maybe_forward_skip_analog(project: Path, cmd_str: str,
                               skip_analog: bool) -> str:
    """Return ``cmd_str`` with ``--skip-analog`` (and, when the program also
    accepts it, a reviewable ``--analog-anchor <path>``) appended IFF
    ``skip_analog`` is set AND the gate's program declares ``--skip-analog``.

    §4.05 NO-LEAK guarantees:
      * ``skip_analog=False`` → returns ``cmd_str`` BYTE-IDENTICAL (the flag
        is never appended; behaviour is unchanged for every non-deferred run).
      * a non-analog optional gate (one whose program does NOT declare
        ``--skip-analog``) → returns ``cmd_str`` unchanged (the flag is never
        forced onto a gate that can't honour it).
      * already-present ``--skip-analog`` in the authored command → not
        duplicated.
      * the gate program is the one that scopes the relaxation to ANALOG-only
        intents (#773): a DIGITAL intent with no evidence STILL FAILs even
        with ``--skip-analog`` appended. This wiring only HANDS OVER the flag;
        it never weakens any digital floor.
    """
    if not skip_analog:
        return cmd_str
    try:
        parts = shlex.split(cmd_str)
    except ValueError:
        return cmd_str
    if not parts:
        return cmd_str
    prog_name = parts[0]
    if not _program_accepts_flag(prog_name, "--skip-analog"):
        return cmd_str
    extra: List[str] = []
    if "--skip-analog" not in parts:
        extra.append("--skip-analog")
    # Append a reviewable analog anchor only if (a) the program accepts the
    # flag, (b) one isn't already authored, and (c) one resolves. The gate
    # itself re-FAILs an unanchored deferral, so a missing anchor degrades
    # safely to the pre-fix FAIL rather than a blanket pass.
    if ("--analog-anchor" not in parts
            and _program_accepts_flag(prog_name, "--analog-anchor")):
        anchor = _resolve_skip_analog_anchor(project)
        if anchor:
            extra += ["--analog-anchor", anchor]
    if not extra:
        return cmd_str
    return cmd_str + " " + " ".join(shlex.quote(t) for t in extra)


def _evaluate_gate(project: Path, gate: Dict[str, Any],
                   skip_analog: bool = False) -> tuple[bool, List[str]]:
    """Evaluate a gate spec, return (passed, reasons).

    ``skip_analog`` (GAP-B, #789) is threaded down to the program-running
    branches so an analog-aware optional/required gate is invoked WITH
    ``--skip-analog`` (and a reviewable ``--analog-anchor``) when the run
    defers the analog track. Defaults to False → byte-identical to the
    pre-fix behaviour."""
    reasons: List[str] = []

    # `files_exist` - top-level (any_of / all_of via flag)
    if "files_exist" in gate:
        any_of = gate.get("any_of", False)
        all_of = gate.get("all_of", True) and not any_of
        passed, found, missing = _check_files_exist(
            project, gate["files_exist"], any_of=any_of
        )
        if not passed:
            # ORGANIC #675 — before declaring a hard FAIL, honor an honest
            # sibling self-skip artifact co-located with the absent canonical
            # output (verdict ∈ SKIP/SKIPPED/SKIPPED-CONDITION), the way
            # `_check_json_field_true` already promotes an ABSENT-field skip to
            # SKIPPED-CONDITION (#608). The canonical case is the formal step:
            # the runner emits `formal/formal_not_run.json` but never
            # `formal/results.json`, so this `files_exist` sub-gate hard-FAILed
            # despite the honest disclosure → cascade-blocked all of Phase 3.
            # §4.05 no-leak: only fires on a genuine ABSENT-output + honest
            # sibling-skip pair; a real authored output (results.json present)
            # passes above and never reaches here, and a real FAIL verdict in
            # the sibling is NOT a self-skip verdict → stays FAILed.
            skip_hint = _sibling_self_skip_for_missing(project, missing)
            if skip_hint is not None:
                reasons.append(f"{_SKIP_HINT_PREFIX}{skip_hint}")
                return True, reasons
            # ORGANIC #171 (A11) — the Step-4 Simulation gate FAILs when the
            # canonical sim/results.xml + pass.flag are both absent, but a design
            # whose functional oracle is derivable wrote its REAL cocotb PASS under
            # sim_professional/<top>/. Accept that real professional_tb PASS as
            # Step-4 functional-sim evidence (plain reason → clean PASS, never a
            # skip/vacuous promotion). None for every non-sim gate / no real pass.
            pro_hint = _sim_files_superseded_by_professional_tb(project, missing)
            if pro_hint is not None:
                reasons.append(pro_hint)
                return True, reasons
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
        # GAP-B (#789) — forward --skip-analog (+ reviewable --analog-anchor) to
        # an analog-aware required gate so a deferred analog track doesn't hard-
        # FAIL it. No-op when skip_analog is False or the program doesn't
        # accept the flag (byte-identical command otherwise).
        _cmd = _maybe_forward_skip_analog(project, _cmd, skip_analog)
        passed, out = _check_program_exit_zero(project, _cmd)
        if not passed:
            reasons.append(f"program failed: {_cmd}")
            reasons.append(f"output: {out[:200]}")
        elif out.startswith(_VACUOUS_HINT_PREFIX):
            # Wave 93 — bubble the rc=2 vacuous signal up so check_step
            # promotes the step's status to VACUOUS_PASS instead of PASS.
            reasons.append(out)
        elif out.startswith(_WAIVER_HINT_PREFIX):
            # #651 — bubble the rc=3 PASS_WITH_WAIVERS signal up so check_step
            # promotes the step's status to WAIVED-DEFERRED instead of a bare
            # PASS, carrying the WITH_WAIVERS distinction to the Overall verdict.
            reasons.append(out)
        return passed, reasons

    # `json_field_true`
    if "json_field_true" in gate:
        passed, out = _check_json_field_true(project, gate["json_field_true"])
        if not passed:
            reasons.append(f"json gate failed: {out}")
        elif out.startswith(_SKIP_HINT_PREFIX):
            # ORGANIC #608 — bubble the self-reported-skip signal up so
            # check_step promotes the step to SKIPPED-CONDITION, not PASS.
            reasons.append(out)
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
        # GAP-B (#789) — forward --skip-analog (+ reviewable --analog-anchor)
        # when the run defers the analog track AND this optional gate's program
        # declares the flag (e.g. l10/l12 tb-conformance, #773). Verbatim
        # otherwise. The gate program itself scopes the relaxation to ANALOG-only
        # intents, so a digital intent with no evidence STILL FAILs; this only
        # hands over the flag the gate already knows how to honour.
        cmd = _maybe_forward_skip_analog(project, cmd, skip_analog)
        passed, out = _check_program_exit_zero(project, cmd)
        if not passed:
            reasons.append(f"optional program failed: {cmd}")
            reasons.append(f"output: {out[:200]}")
        elif out.startswith(_WAIVER_HINT_PREFIX):
            # ORGANIC #654 — an OPTIONAL gate program may also signal
            # PASS_WITH_WAIVERS (rc=3 + sentinel). _check_program_exit_zero
            # already validated the rc+sentinel pair and returned the
            # `__WAIVER_HINT__:` tuple; forward it so check_step promotes the
            # step to WAIVED-DEFERRED (Overall PASS_WITH_WAIVERS) instead of a
            # bare PASS — mirrors the non-optional `program_exit_zero` branch.
            reasons.append(out)
        elif out.startswith(_VACUOUS_HINT_PREFIX):
            # An OPTIONAL gate program may signal the disclosed-skip tier by
            # EXIT CODE (rc 2) exactly as a required one does. In that case
            # `_check_program_exit_zero` already replaced the snippet with the
            # `__VACUOUS_HINT__:` marker, so the stdout-token test below can no
            # longer see the program's own `VACUOUS_PASS:` line and the
            # disclosure was silently downgraded to a bare pass. Forward the
            # marker instead — mirrors the `__WAIVER_HINT__` branch above.
            reasons.append(out)
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
            p, r = _evaluate_gate(project, sub, skip_analog=skip_analog)
            if not p:
                reasons.extend(r)
                return False, reasons
            for hint in r:
                if hint.startswith(_VACUOUS_HINT_PREFIX):
                    reasons.append(hint)
                elif hint.startswith(_WAIVER_HINT_PREFIX):
                    # #651 — a PASS_WITH_WAIVERS sub-gate makes the whole
                    # all_of step WAIVED-DEFERRED (carried via the hint).
                    reasons.append(hint)
                elif hint.startswith(_SKIP_HINT_PREFIX):
                    # ORGANIC #675 — an honest sibling-self-skip sub-gate makes
                    # the whole all_of step SKIPPED-CONDITION (carried via the
                    # hint), the same way a vacuous/waiver sub-gate promotes
                    # the step. A skip is more specific than a vacuous-pass, so
                    # the step-level handler resolves SKIPPED-CONDITION ahead of
                    # VACUOUS_PASS when both hints are present.
                    reasons.append(hint)
        return True, reasons

    # `any_of` - list of sub-gates, any one passes
    if "any_of" in gate and isinstance(gate["any_of"], list):
        for sub in gate["any_of"]:
            if not isinstance(sub, dict):
                continue
            p, _ = _evaluate_gate(project, sub, skip_analog=skip_analog)
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
#: #216 — ENV_UNAVAILABLE waiver entries that were REJECTED (not bound to a
#: step) during the last `_load_waivers` call, each with the reason and the
#: remedy. Surfaced as report advisories so a rejected waiver is visible
#: instead of silently discarded. Populated by `_load_waivers`, which clears
#: it on entry so repeated calls in one process do not accumulate.
_ENV_WAIVER_REJECTIONS: List[str] = []


_ENV_UNAVAILABLE_STEP_NAME_TO_ID: Dict[str, Any] = {
    # #216 — the formal (Step 5) role-names. Their ABSENCE was itself the
    # defect: an ENV_UNAVAILABLE waiver naming `formal` matched nothing here,
    # hit the `sid is None -> continue` branch, and was dropped WITHOUT A
    # TRACE — the step then reported a bare MISSING that never mentioned the
    # formal engine, the waiver, or the ticket. Role names only, never a chip
    # or vendor literal.
    "formal":                  5,
    "formal_verify":           5,
    "formal_verification":     5,
    "formal_proof":            5,
    "formal_property_proof":   5,
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


# ORGANIC #608 — the FPGA-board step ids that --skip-hardware waives, DERIVED
# from the canonical name→id table above (single source of truth, kept in sync
# with the flow YAML) instead of a stale magic-number literal. A Wave 90 /
# v1.6.14 renumber shifted the FPGA-final-signoff step 37→39 (37 became "GDSII
# output"), but the old literal `(6, 37)` was never updated — so --skip-hardware
# both failed to waive the real FPGA-final step (39) AND wrongly waived a
# non-FPGA backend step (37=GDSII). Deriving the set here makes it renumber-
# proof: any future YAML renumber updates the table once, and this set follows.
_FPGA_BOARD_STEP_NAMES = (
    "fpga_compile", "fpga_early_prototype",
    "fpga_onboard_test", "fpga_final_signoff", "fpga_signoff",
)
_FPGA_BOARD_STEP_IDS = frozenset(
    _ENV_UNAVAILABLE_STEP_NAME_TO_ID[_n] for _n in _FPGA_BOARD_STEP_NAMES
)  # = {6, 39}


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
            # #525 perf — only the deck HEAD matters here (PDK include /
            # model lines sit at the top); post-layout extracted decks can
            # be huge. 64 KiB covers any realistic header.
            with open(sp, "rb") as fh:
                text = fh.read(65536).decode(errors="replace")
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


# ORGANIC #607 — FPGA-board prototype capability-gap auto-deferral.
_FPGA_SKIP_WAIVER_TICKET = "fpga-board-prototype-capgap-v1.0.18"


def _fpga_skip_disclosed(project: Path) -> bool:
    """ORGANIC #607 — True iff the runner HONESTLY self-reports a deliberate
    FPGA skip: reports/phase2/fpga/quartus_map_audit.json carries
    verdict==SKIP AND sof_present==False. This is the disclosed-skip predicate;
    an UNDISCLOSED missing .sof (no audit file, a non-SKIP verdict, or
    sof_present claimed True) returns False so the step's natural FAIL/MISSING
    stands. chip-AGNOSTIC: keyed on the runner's own SKIP self-report, no chip
    name."""
    audit = project / "reports" / "phase2" / "fpga" / "quartus_map_audit.json"
    try:
        d = json.loads(audit.read_text())
    except (OSError, ValueError):
        return False
    if not isinstance(d, dict):
        return False
    return (str(d.get("verdict", "")).upper() == "SKIP"
            and d.get("sof_present") is False)


def _synthesise_fpga_skip_waivers(
        project: Path, out: Dict[Any, Dict[str, Any]]) -> None:
    """ORGANIC #607 — when the runner discloses a deliberate FPGA skip
    (quartus_map_audit.json verdict=SKIP, sof_present=false — e.g. an IC class
    with no DE10 board-pin contract, or no Quartus on host), add an
    ENV_UNAVAILABLE-tier cap-gap waiver for EVERY FPGA-board step so its
    natural MISSING/FAIL (no .sof) converts to WAIVED-DEFERRED via check_step's
    existing fallback, instead of hard-FAILing and cascading
    blocked-by-upstream across stage2/stage3 → Overall:FAIL. Mirrors
    `_synthesise_pdk_substitution_waivers` (#496) and the #430 cap-gap doctrine.
    Mutates `out` in place; no-op when nothing is disclosed (undisclosed missing
    .sof still hard-FAILs). chip-AGNOSTIC.

    ORGANIC #663 — the early-prototype step (id 6) AND the final on-board
    sign-off step (id 39) are BOTH board-absent capability gaps under the SAME
    disclosed-skip predicate. v1.0.18 hard-coded only the early-prototype id, so
    the canonical no-flag `--strict` audit left the final-signoff step at a hard
    FAIL ('no-hardware-evidence' from the program_exit_zero attestation gate)
    while only the early step deferred — asymmetric with the --skip-hardware
    board-step downgrade (which already covers the whole renumber-proof set
    `_FPGA_BOARD_STEP_IDS`). Iterate that same renumber-proof set so the cap-gap
    auto-deferral is SYMMETRIC across all board steps. The waiver-synthesis layer
    is the right place because the final-signoff gate is an all_of containing a
    program_exit_zero attestation check that the #608 json_field_true self-skip
    promotion never reaches; check_step's fallback honours this waiver."""
    if not _fpga_skip_disclosed(project):
        return
    # renumber-proof: derive from the canonical step-name→id table (single
    # source of truth, kept in sync with the flow YAML) rather than literals.
    for sid in sorted(_FPGA_BOARD_STEP_IDS, key=lambda x: (str(type(x)), x)):
        if sid in out:
            continue  # an explicit waiver for this step takes precedence
        out[sid] = {
            "id": sid,
            "reason": (
                "ENV_UNAVAILABLE (fpga-board-prototype cap-gap): the runner "
                "HONESTLY self-reports a deliberate FPGA skip "
                "(reports/phase2/fpga/quartus_map_audit.json verdict=SKIP, "
                "sof_present=false) — no DE10-class board-pin contract for this "
                "IC class and/or no Quartus on host. The on-board .sof "
                "(early-prototype AND final sign-off) is DEFERRED to board "
                "bring-up (NOT executed-PASS) "
                f"[ticket={_FPGA_SKIP_WAIVER_TICKET}, review_required=True, "
                "cap:fpga_board_prototype]"),
            "approver": "field-agent-attest (fpga-board cap-gap tier)",
            "ticket": _FPGA_SKIP_WAIVER_TICKET,
            "verdict_tier": "ENV_UNAVAILABLE",
            "review_required": True,
            "evidence": ["reports/phase2/fpga/quartus_map_audit.json"],
            "_env_unavailable": True,
            "_fpga_skip": True,
        }


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


def _refuse_stale_waivers(project: Path, out: Dict[Any, Dict[str, Any]]) -> None:
    """FALSE-CLEAN GUARD — refuse a STALE waiver (in-place on `out`).

    An ENV_UNAVAILABLE waiver is issued under exactly ONE condition: the step
    COULD NOT RUN on this host. But `waivers.json` is a FILE and it SURVIVES
    into the next run — so a waiver written when the tool was absent could
    excuse a DRC/LVS that a LATER run actually EXECUTED and that actually
    FAILED. That is a false-clean: the failure really happened and the audit
    reports it as waived.

    Re-evaluate each waiver's condition against THIS run's own phase-report
    evidence and drop any whose excused step demonstrably EXECUTED. Only
    POSITIVE execution evidence refuses a waiver — no evidence honors it, so a
    genuine ENV_UNAVAILABLE deferral is unaffected. Refusals are printed, never
    silent. chip-AGNOSTIC: keys on step status, never a design literal."""
    try:
        import waiver_staleness as _ws
        refused = _ws.prune_stale_mapping(out, project)
        for sid, why in sorted(refused.items(), key=lambda kv: str(kv[0])):
            print(f"flow_compliance_check: step {sid}: {why}", file=sys.stderr)
    except Exception:  # pragma: no cover - the guard must never crash the load
        pass


def _load_waivers(project: Path, max_step: int = 40) -> Dict[int, Dict[str, str]]:
    """Load waivers AFTER validating schema. Returns {} if file missing.
    Raises SystemExit(1) if waivers.json exists but is malformed/rubber-stamped."""
    _ENV_WAIVER_REJECTIONS.clear()  # #216 — fresh per call
    wpath = project / "waivers.json"
    if not wpath.exists():
        # v0.2.103 (#496) — even with no waivers.json, the disclosed
        # PDK-substitution predicate auto-synthesises the A-step deferral
        # waivers so a non-default-target analog chip on the open path is
        # not permanently unpassable. An UNDISCLOSED mismatch → {} → FAIL.
        out: Dict[Any, Dict[str, Any]] = {}
        _synthesise_pdk_substitution_waivers(project, out)
        _synthesise_fpga_skip_waivers(project, out)  # ORGANIC #607
        _refuse_stale_waivers(project, out)
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
        # #216 — a REJECTED ENV_UNAVAILABLE waiver must never vanish. Every
        # `continue` below used to drop the entry silently: the step then
        # reported a bare MISSING with no mention of the waiver, the missing
        # capability, or the ticket, and the person holding the report had no
        # way to learn a waiver had even been attempted. Rejections are now
        # collected and surfaced as named advisories. Rejection still means
        # the step is NOT waived and strict mode still fails it — this makes
        # the report LOUDER, never greener.
        for w in data.get("waivers", []) or []:
            if not isinstance(w, dict):
                continue
            tier = (w.get("verdict_tier") or "").strip().upper()
            if tier != "ENV_UNAVAILABLE":
                continue
            step_name = (w.get("step") or "").strip().lower()
            sid = _ENV_UNAVAILABLE_STEP_NAME_TO_ID.get(step_name)
            if sid is None:
                _ENV_WAIVER_REJECTIONS.append(
                    f"ENV_UNAVAILABLE waiver for step {step_name!r} was "
                    f"NOT applied: that step role-name is not recognised, so "
                    f"the waiver could not be bound to a flow step and the "
                    f"step is reported on its own merits. Use one of the "
                    f"known role names ("
                    + ", ".join(sorted(_ENV_UNAVAILABLE_STEP_NAME_TO_ID))
                    + ")."
                )
                continue
            # Required attestation fields. An ENV_UNAVAILABLE waiver is a
            # claim that an environment could not be reached; it is only
            # honoured when it is ACTIONABLE and reviewable.
            ticket = w.get("ticket")
            reviewer_required = w.get("review_required") is True
            evidence = w.get("evidence") or []
            rationale = (w.get("rationale") or "").strip()
            missing: List[str] = []
            if not (isinstance(ticket, str) and ticket):
                missing.append("a non-empty `ticket`")
            if not reviewer_required:
                missing.append("`review_required: true`")
            if not (isinstance(evidence, list) and evidence):
                missing.append("a non-empty `evidence` list")
            if len(rationale) < 40:
                missing.append(
                    "a `rationale` of at least 40 characters naming the "
                    "missing capability, where the flow looked for it, and "
                    "what to install or stage")
            if missing:
                _ENV_WAIVER_REJECTIONS.append(
                    f"ENV_UNAVAILABLE waiver for step {step_name!r} "
                    f"(flow step {sid}) was NOT applied — it is missing "
                    + "; ".join(missing)
                    + ". The step is reported on its own merits until the "
                      "waiver is completed."
                )
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
        _synthesise_fpga_skip_waivers(project, out)  # ORGANIC #607
        _refuse_stale_waivers(project, out)
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
    # `any_of: true` — the step runs if ANY listed file is present, matching the
    # long-standing `gate:` semantics (flow_compliance line ~3993). Default
    # stays ALL-of, so every existing step's condition is byte-unchanged.
    #
    # Why a condition needs it at all: a step whose ONLY trigger is the artefact
    # it consumes disappears silently when that artefact is missing — the very
    # case where something went wrong. Listing the step's own not-run record
    # alongside its input lets an unrunnable step still reach its gate and say
    # so, instead of being skipped by condition and read as nothing to report.
    if files and condition.get("any_of", False):
        if not any(_glob_first(project, pat) for pat in files):
            return False
        return True
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
    # EMPTY since the last gap closed — every canonical step now gates on a real
    # OSS engine (a genuinely absent artifact stays MISSING = a real defect,
    # never masked). History of the closures (all real tools, no stubs):
    #   22 SPEF  → OpenRCX v2 `-lef_rc` from tech-LEF RC (304/304 nets)
    #             + analytical lateral-coupling augment (_spef_coupling,
    #             disclosed generic-dielectric, NOT foundry-calibrated).
    #   11 DFT   → AUCOHL/Fault real stuck-at ATPG (96.12% measured coverage).
    #   12 post  → yosys opt_clean scan netlist → post_dft_netlist.v.
    #   29 SDF   → iverilog $sdf_annotate gate sim (634 net delays, 50/50 vectors).
    #   30 SPICE → ngspice cell-delay + critical-path (top-N via OpenSTA)
    #             correlation vs Liberty NLDM / STA.
    #   13 LEC   → RTL==synth via Yosys equiv with `read_liberty -ignore_miss_func`
    #             (reads commercial-Liberty cell FUNCTIONS as SAT-modelable logic,
    #             not `-lib` blackboxes) → 65/65 proven, 0 unproven; false-clean-
    #             PROOF (a corrupted NAND2D1→NOR2D1 netlist → NOT-equivalent).
    #             (routed==synth was already proven by lec_post_layout_check.)
    #   5  FORMAL → formal_property_run: real SymbiYosys proof with the built-in
    #             ABC engines (abc pdr = UNBOUNDED safety prove; abc bmc3 =
    #             disclosed BOUNDED functional BMC) — no external SMT solver
    #             needed. The runner's formal_not_run.json sentinel stays the
    #             honest SKIP when no formal harness was authored; a real proof
    #             gates normally via formal_proof_evidence_check.
}

# v1.3.94 — per-flag ACCURATE rationale overrides. The generic
# _apply_capability_gap message ("the open-tool runner chain does not implement
# this canonical step yet") is correct for the truly-unimplemented gaps but
# MISLEADING for a step the runner DOES implement yet cannot complete for a
# DATA/model-availability reason. A flag present here uses this text instead, so
# the audit never overstates the gap as "unimplemented" when it is "implemented
# but the NDA PDK ships no OSS-consumable model". chip-AGNOSTIC.
_CAP_GAP_RATIONALE: Dict[str, str] = {}


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

# ORGANIC #636 — a verdict-JSON `evidence` field is dereferenced as a file
# pointer ONLY when it is structurally path-SHAPED, not merely because it
# contains a '/'. Prose evidence notes legitimately carry slashes INSIDE words
# ("derived/gated clock tokens", "input/output delay", "REQ/ACK", "and/or",
# "RTL file(s)"); the old `"/" in ev_ptr` heuristic resolved the WHOLE sentence
# as `project / <sentence>`, found no file, and false-FAILed EVIDENCE_MISSING —
# the dominant trigger for single-clock-domain designs whose CDC/RDC checker
# emits the standard "derived/gated clock tokens attributed to root" prose, and
# it cascaded to ~25 downstream steps. A real path pointer has NO embedded
# whitespace AND (a known artifact extension OR a known project-output dir
# prefix). This restores the line-3151 prose-exemption intent while still
# catching the genuine broken-pointer case (#433b: the empty
# sim/reference_tb/ref_tb.log chain — `sim/` prefix + `.log` ext → still
# dereferenced). chip-AGNOSTIC: pure path-shape structure, no IC-class/token
# literals.
_EVIDENCE_PATH_EXT_RE = re.compile(
    r"\.(?:json|log|xml|rpt|txt|def|gds|gds2|spef|sdc|sdf|saif|vcd|csv|"
    r"ya?ml|lef|lib|v|sv|drc|lvs|out)$",
    re.IGNORECASE)
_EVIDENCE_PATH_PREFIX_RE = re.compile(
    r"^(?:\./)?(?:reports|phase1|phase2|phase3|sim|synth|pnr|sta|drc|lvs|"
    r"layout|gds|fpga|analog|input|rtl|work|build|out|results)/")


def _looks_like_evidence_path(s: str) -> bool:
    """ORGANIC #636 — True iff `s` is structurally a dereferenceable artifact
    path, NOT a prose note that merely contains a '/'. A real pointer has no
    embedded whitespace AND (a known artifact extension OR a known project-
    output dir prefix). chip-AGNOSTIC: path-shape only."""
    s = s.strip()
    if not s or any(ch.isspace() for ch in s):
        return False
    return bool(_EVIDENCE_PATH_EXT_RE.search(s)
                or _EVIDENCE_PATH_PREFIX_RE.match(s))


# 2026-07-13 — a coverage/simulation verdict that self-reports
# SKIPPED-CONDITION on the premise that "no functional transcript ran for THIS
# project" (the #436 reference-TB-absent coverage skip: "no reference-TB
# transcript … cannot cite scenarios that never ran") is SUPERSEDED when the
# project has a REAL professional_tb functional PASS
# (phase2/stage1/sim_professional/<top>/results.xml, failures=0). The
# professional cocotb streaming-scoreboard IS a functional transcript that
# actually ran, so the skip's own premise is contradicted by real evidence and
# must not drag the step down to SKIPPED-CONDITION. chip-AGNOSTIC (canonical
# artifact basename + premise keywords, no chip literal) and anti-fabrication-
# safe (only a REAL professional_tb PASS overrides, and only the specific
# "transcript never ran" skip — a threshold-below or any other skip is
# untouched).
_COVERAGE_SELFSKIP_ARTIFACT = "coverage_actual.json"
_NO_TRANSCRIPT_PREMISE_RE = re.compile(
    r"reference[- ]?tb|never ran|no .*transcript|scenarios that never",
    re.IGNORECASE)


def _coverage_selfskip_superseded_by_professional_tb(
        project: Path, artifact_rel: str, reason: str,
        pro_pass: Optional[Dict[str, Any]]) -> bool:
    """True iff a SKIPPED-CONDITION coverage verdict (artifact basename
    ``coverage_actual.json``) whose reason cites the "no functional transcript
    ran" premise is SUPERSEDED by a real professional_tb functional PASS.
    chip-AGNOSTIC: structural basename + premise keywords + real JUnit PASS."""
    if not pro_pass:
        return False
    if Path(artifact_rel).name != _COVERAGE_SELFSKIP_ARTIFACT:
        return False
    return bool(_NO_TRANSCRIPT_PREMISE_RE.search(reason or ""))


def _evidence_integrity_scan(project: Path,
                             result: "StepResult") -> "StepResult":
    if result.status != "PASS" or not result.evidence:
        return result
    stub_hits: List[str] = []
    broken: List[str] = []
    self_skipped: List[str] = []
    superseded: List[str] = []
    # Computed lazily on the first coverage self-skip encountered.
    _pro_pass: Optional[Dict[str, Any]] = None
    _pro_computed = False
    for rel in list(result.evidence):
        rel_s = str(rel)
        p = Path(rel_s) if rel_s.startswith("/") else project / rel_s
        try:
            if p.stat().st_size == 0:
                broken.append(f"{rel} (0 bytes)")
                continue
            # #525 perf — the old `read_text()[:8000]` read the ENTIRE
            # file (evidence lists routinely include multi-hundred-MB
            # DEF/GDS/SPEF) before slicing; on a large SoC this single
            # loop dominated the audit wall-time. Read only the head.
            with open(p, "rb") as fh:
                txt = fh.read(8192).decode(errors="replace")
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
                    reason = str(d.get("reason", ""))
                    if not _pro_computed:
                        _pro_pass = _srb.find_professional_tb_pass(project)
                        _pro_computed = True
                    if _coverage_selfskip_superseded_by_professional_tb(
                            project, rel_s, reason, _pro_pass):
                        superseded.append(
                            f"{rel} (superseded by professional_tb PASS "
                            f"{_pro_pass['rel_path']}: tests={_pro_pass['tests']}"
                            f" failures={_pro_pass['failures']})")
                        continue
                    self_skipped.append(f"{rel}: {reason[:160]}")
                    continue
                ev_ptr = d.get("evidence")
                # ORGANIC #636 — dereference ONLY a path-SHAPED pointer, never
                # a prose note that merely contains a '/' (e.g. "derived/gated").
                if isinstance(ev_ptr, str) and _looks_like_evidence_path(ev_ptr):
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
    elif superseded:
        # Status stays PASS: the only self-skip was a coverage verdict whose
        # "no functional transcript ran" premise is contradicted by a real
        # professional_tb functional PASS. Record the real-evidence pointer.
        result.reasons.append(
            "coverage self-skip SUPERSEDED by real professional_tb functional "
            "PASS (functional transcript DID run): " + "; ".join(superseded[:3]))
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
        # v1.3.94 — a flag with an ACCURATE rationale override (a step the
        # runner DOES implement but cannot complete for a data/model gap) uses
        # its own text; the rest use the generic "not implemented yet".
        if flag in _CAP_GAP_RATIONALE:
            result.reasons.append(_CAP_GAP_RATIONALE[flag])
        else:
            result.reasons.append(
                f"platform capability gap [{flag}]: the open-tool runner "
                f"chain does not implement this canonical step yet (#430); "
                f"converted from MISSING so every strict deduction names its "
                f"capability flag. Track/implement under this flag to "
                f"re-enable gating.")
    return result


_STOPWORDS = {"the", "and", "a", "of", "to", "for", "step", "sign", "off",
              "signoff", "final", "check", "gate", "stage"}


def _name_tokens(name: str) -> set:
    """Significant lowercase alnum tokens of a step name (stopwords removed)."""
    toks = re.findall(r"[a-z0-9]+", (name or "").lower())
    return {t for t in toks if t not in _STOPWORDS and len(t) > 1}


def _waiver_step_name_mismatch(waiver: Dict[str, Any],
                               step_name: str):
    """ORGANIC #572 — when a waiver carries an explicit `step_name` (the
    human label of the step it claims to waive), cross-check it against the
    canonical name of the step at that id. A mis-filed waiver
    (e.g. id=37=GDSII but step_name='FPGA final') would otherwise silently
    waive the WRONG step while the intended one stays FAIL. Returns a
    message string on mismatch, else None. The check fires ONLY when the
    waiver opts in by declaring step_name — existing waivers are unaffected.
    chip-AGNOSTIC: pure token comparison, no step literal hard-coded."""
    declared = waiver.get("step_name") or waiver.get("step")
    if not declared or not isinstance(declared, str):
        return None
    dt = _name_tokens(declared)
    st = _name_tokens(step_name)
    if not dt or not st:
        return None
    # accept when the names share any significant token (tolerant to
    # phrasing differences like "FPGA final" vs "FPGA on-board sign-off").
    if dt & st:
        return None
    return (f"waiver step_name {declared!r} does not match the canonical "
            f"name of this step ({step_name!r}) — waiver appears mis-filed "
            f"to the wrong step id; refusing to apply it")


# ── #NNN: parallel per-step gate evaluation ──────────────────────────────
# The per-step compliance gates are INDEPENDENT read-only validators of
# already-produced artifacts. `check_step()` is a pure function of
# (project, step, waivers, flags): it spawns each gate subprocess with
# `cwd=project` (never `os.chdir`, which is process-global and thread-unsafe),
# touches NO shared mutable module state (the only module caches on its call
# graph are the deterministic-idempotent `_PURE_ANALOG_CACHE` — same key →
# same value, so a benign write race stores identical data — and a thread-safe
# `functools.lru_cache`), prints nothing (all output is driven later from the
# ordered `results` list), and never reads an artifact that another step's gate
# writes. So the steps can be evaluated CONCURRENTLY; the per-step verdict is
# order-independent, and only the RESULTS-LIST ORDER (for display + the
# downstream cascade attribution) must be preserved — which we do by collecting
# the futures in submission order. This turns a large-SoC compliance sweep
# (e.g. `final_audit` over 44 steps) from SUM-of-gate-times into
# MAX-of-gate-times WITHOUT changing a single verdict (proven byte-identical
# seq-vs-parallel across the benchmark IC suite).
#
# Bounded so the heavy honest gates (reset_dependency_check ~6 min, provenance
# sha256 over multi-GB GDS) can't oversubscribe the box — each worker may itself
# fork a gate subprocess, so we leave a core of headroom. `VIBE_IC_COMPLIANCE_
# WORKERS` overrides (1 = the sequential fallback), mirroring the env-driven
# `VIBE_IC_GATE_TIMEOUT_S` knob.
def _compliance_workers(n_steps: int) -> int:
    import os
    if n_steps <= 1:
        return 1
    raw = os.environ.get("VIBE_IC_COMPLIANCE_WORKERS")
    if raw:
        try:
            w = int(raw)
        except ValueError:
            w = 0
        if w >= 1:
            return max(1, min(w, n_steps))
    cpu = os.cpu_count() or 2
    return max(1, min(8, cpu - 1, n_steps))


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

    # v0.2.55 — --skip-hardware: the FPGA-board steps (early-prototype SOF +
    # final on-board sign-off) require a physical FPGA (DE10-Lite-class)
    # attached. A pure doc→GDS run launched with --skip-hardware (the
    # documented headless flow) cannot produce a .sof or run an on-board test,
    # so these steps FAILed unconditionally with no way to honor the run mode.
    # Mirror --skip-analog: downgrade them to WAIVED (review_required at
    # foundry/board-bringup time). All OTHER steps still gate normally — the
    # GDS, STA, DRC, LVS sign-off is unaffected. chip-AGNOSTIC.
    # ORGANIC #608 — the waived set is now DERIVED from the canonical name→id
    # table (_FPGA_BOARD_STEP_IDS = {6, 39}), not the stale literal (6, 37) that
    # a Wave 90 renumber broke (37 became GDSII; FPGA-final moved to 39).
    if skip_hardware and isinstance(sid, int) and sid in _FPGA_BOARD_STEP_IDS:
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
        # ORGANIC #141 — the digital backend is N/A for a pure-analog class OR
        # for an analog-applicable class whose L9 top interface is all-analog
        # (no digital clock/reset/data INPUT). Both route the digital RTL→GDS
        # stages to SKIPPED-CONDITION instead of MISSING/FAIL.
        is_na, na_reason = _digital_backend_is_na(project)
        if is_na:
            result.status = "SKIPPED-CONDITION"
            result.reasons.append(
                f"N/A for analog IC (no digital datapath): stage "
                f"{step_stage!r} is the digital RTL→GDS backend — {na_reason}.")
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
        # ORGANIC #572 — reject a waiver mis-filed to the wrong step id
        # (id+name disagree). The intended step then stays un-waived and
        # gates normally; the mis-filed step surfaces the mismatch.
        _name_mismatch = _waiver_step_name_mismatch(
            waivers[sid], step.get("name", ""))
        if _name_mismatch:
            result.reasons.append(f"WAIVER REJECTED: {_name_mismatch}")
            # fall through WITHOUT applying the waiver — the step is judged
            # on its real evidence below.
        else:
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
        else:
            # ORGANIC #675 (extension) — the `files_exist` gate path already
            # honors an honest co-located `*_not_run.json` / `*_skipped.json`
            # sibling that discloses the runner deliberately skipped this step
            # (see `_sibling_self_skip_for_missing`, called ~line 3735). A step
            # whose ONLY evidence is a required_output (empty
            # `verification.commands`) early-returns HERE and never reached that
            # path, so an honestly-disclosed downstream cap-gap skip (post-DFT
            # optimization when scan insertion was disclosed-skipped, SDF
            # gate-level sim / post-layout SPICE correlation which the OSS chain
            # discloses it cannot drive) fell through to a hard MISSING.
            #
            # We honor it here with the STRICT
            # `_declared_sibling_self_skip_for_missing` — NOT the loose dir-level
            # match — because at the early-return there is NO second sub-gate to
            # backstop a false promotion, and output DIRECTORIES are shared
            # between steps (phase2/stage2/synth/ holds both step-9 netlist.v and
            # step-12's marker; reports/phase3/ holds many sign-offs). The strict
            # form promotes ONLY when a sibling UNAMBIGUOUSLY OWNS this step's
            # absent output (self-skip verdict + a named capability_flag + a
            # `skips_required_output` matching one of THIS step's missing
            # patterns), so a step-12 marker can never mask a step-9 synth FAIL
            # and no marker can mask a DRC/LVS sign-off. A marker lacking the
            # ownership claim, or naming a different output, stays MISSING.
            missing_pats = [sp for pat in outputs
                            for sp in (p.strip() for p in pat.split(" OR "))]
            skip_hint = _declared_sibling_self_skip_for_missing(
                project, missing_pats)
            if skip_hint:
                result.status = "SKIPPED-CONDITION"
                result.reasons.append(
                    "SKIPPED-CONDITION: canonical output absent but a co-located "
                    "sibling that OWNS it honestly self-reports a disclosed "
                    f"capability-gap skip (#675 strict): {skip_hint}")
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
        # GAP-B (#789) — thread the run's skip_analog into the gate evaluation
        # so an analog-aware optional/required gate (#773) is invoked WITH
        # --skip-analog when the analog track is explicitly deferred. The P0
        # umbrella (#632) + final_audit (#609) already honour the flag; this
        # closes the per-step optional/required gate wiring gap. No-op when
        # skip_analog is False.
        passed, reasons = _evaluate_gate(project, gate, skip_analog=skip_analog)
        # Wave 93 — VACUOUS_PASS verdict tier promotion. If the gate
        # passed AND every reason carries the __VACUOUS_HINT__ marker
        # (and at least one was emitted), the step ran but every
        # executed sub-gate was vacuously satisfied (its audited input
        # didn't apply to this project). Surface that as VACUOUS_PASS
        # so the per-step listing labels it explicitly. Filter out the
        # internal markers before display either way.
        vacuous_hints = [r for r in reasons
                         if r.startswith(_VACUOUS_HINT_PREFIX)]
        # ORGANIC #608 — a gate whose evidence artifact honestly self-reports a
        # skip verdict emits a __SKIP_HINT__ marker; promote the step to
        # SKIPPED-CONDITION (not PASS, not FAIL) the same way VACUOUS_PASS is
        # promoted from __VACUOUS_HINT__.
        skip_hints = [r for r in reasons
                      if r.startswith(_SKIP_HINT_PREFIX)]
        # #651 — a gate program that PASSed-WITH-WAIVERS emits a
        # __WAIVER_HINT__ marker; promote the step to WAIVED-DEFERRED so the
        # Overall verdict resolves to PASS_WITH_WAIVERS, never a bare PASS.
        waiver_hints = [r for r in reasons
                        if r.startswith(_WAIVER_HINT_PREFIX)]
        non_hint_reasons = [r for r in reasons
                            if not r.startswith(_VACUOUS_HINT_PREFIX)
                            and not r.startswith(_SKIP_HINT_PREFIX)
                            and not r.startswith(_WAIVER_HINT_PREFIX)]
        if (passed and waiver_hints and not non_hint_reasons
                and not skip_hints and not vacuous_hints):
            # WAIVED here means "DEFERRED via waiver": it leaves the required
            # denominator the same way an explicit waivers.json entry does and
            # drives Overall → PASS_WITH_WAIVERS. The gate DID pass its
            # threshold; the WITH_WAIVERS distinction is the whole point (#651).
            result.status = "WAIVED"
            for h in waiver_hints:
                result.reasons.append(
                    f"WAIVED-DEFERRED: gate program signalled PASS_WITH_WAIVERS "
                    f"(#651 — a slot credited via a waiver, NOT a bare PASS; "
                    f"production tapeout review must close it): "
                    f"{h[len(_WAIVER_HINT_PREFIX):]}")
        elif passed and skip_hints and not non_hint_reasons:
            # ORGANIC #675 — a skip is MORE specific than a vacuous-pass: when
            # an all_of step carries BOTH an honest sibling-self-skip hint and a
            # vacuous-pass hint (e.g. the formal step where the absent
            # results.json is disclosed by formal_not_run.json AND the
            # bit-level full-stack TB is vacuous for a non-protocol IC),
            # resolve to SKIPPED-CONDITION rather than VACUOUS_PASS so the
            # disclosed deferral (review_required, NOT executed-PASS) is what
            # surfaces. (#608 originally required `not vacuous_hints`; that left
            # the formal step FALLING THROUGH to VACUOUS_PASS, masking the
            # disclosed skip — relaxed here.)
            result.status = "SKIPPED-CONDITION"
            for h in skip_hints:
                result.reasons.append(
                    f"SKIPPED-CONDITION: gate evidence self-reports a skip "
                    f"(#608/#675): {h[len(_SKIP_HINT_PREFIX):]}")
        elif passed and vacuous_hints and not non_hint_reasons and not skip_hints:
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
            result.reasons.extend(non_hint_reasons)
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


def _track_of(sid: Any) -> Optional[str]:
    """v0.3.5 — #502/#503: classify a step id into its declared chain.
    Integer ids = the main digital track; "A*" = analog; "M*" =
    mixed-signal; "P0" (preflight umbrella) belongs to no chain."""
    if isinstance(sid, int):
        return "main"
    s = str(sid)
    if s == "P0":
        return None
    if s.startswith("A"):
        return "analog"
    if s.startswith("M"):
        return "mixed"
    return None


def _attribute_cascade_verdicts(
        results: List["StepResult"],
        steps: List[Dict[str, Any]],
        waivers: Dict[Any, Dict[str, Any]],
        skip_analog: bool = False,
) -> Dict[str, Any]:
    """v0.3.5 — ORGANIC #502 + #503: deterministic cascade attribution
    so the summary separates ROOT CAUSES from their inevitable
    downstream consequences. Chip-AGNOSTIC: pure graph/order walk over
    the flow definition's declared `blocks_on` edges and step order —
    no step-id or chip-class literal participates in the logic.

    ORGANIC #667 — when ``skip_analog=True``, a mixed-signal (M-track)
    sign-off step whose ``blocks_on`` ancestry transitively reaches an
    analog (A-track) step that was downgraded to SKIPPED-CONDITION (via
    ``--skip-analog`` in ``check_step``) is the inevitable downstream
    consequence of that same skip: the M-step's required mixed-signal
    artefacts can only exist once the analog track has been run, and the
    analog track was deliberately skipped. Such a MISSING M-step is
    downgraded to SKIPPED-CONDITION (skip inherited from the skipped
    analog ancestry) rather than left as a hard MISSING that drives
    Overall: FAIL. This mirrors how A-steps and the #632 P0 analog
    sub-gates are already suppressed under --skip-analog. The #502 cascade
    (next) only converts a MISSING descendant when the ancestor is WAIVED,
    never SKIPPED-CONDITION, so without this pass a legitimate
    --skip-analog digital-scope run on ANY mixed-signal-class IC could
    never reach Overall: PASS. Chip-AGNOSTIC: gated purely on the
    structural ``_track_of`` classification (M-track step, A-track skipped
    ancestor) reached over declared ``blocks_on`` edges — no step-id or
    chip literal. A GENUINE M-step FAIL (real counter-evidence) is NOT
    touched, and the skip only fires when --skip-analog is DISCLOSED.

    #502 (waiver chain must propagate): a MISSING step whose
    `blocks_on` ancestry (transitive) reaches a WAIVED-DEFERRED step is
    the inevitable consequence of that SAME waiver — its inputs are
    exactly what the parent's waiver deferred. Verdict becomes
    DEFERRED-BY-UPSTREAM(parent, ticket): counted separately, excluded
    from strict MISSING (one waiver = one deduction, not two).
    A FAIL never converts — real counter-evidence always survives.

    #503 (mid-chain FAIL cascade): within each declared chain (main /
    analog / mixed, in YAML declaration order) every MISSING step AFTER
    the first FAIL is annotated blocked-by-upstream(<first-fail id>).
    Status stays MISSING — the work IS still missing and strict mode
    still fails — only the ATTRIBUTION changes, and the summary splits
    the cascade count so triage sees the real root-cause surface.

    Returns {"deferred_by_upstream": [(id, parent, ticket), ...],
             "blocked_by_upstream": {first_fail_id: count}}.
    """
    by_id: Dict[Any, StepResult] = {r.id: r for r in results}
    parents_of: Dict[Any, List[Any]] = {}
    order: List[Any] = []
    for st in steps:
        sid = st.get("id")
        if sid is None or str(sid) == "P0":
            continue
        order.append(sid)
        edges = st.get("blocks_on") or []
        if isinstance(edges, (list, tuple)):
            parents_of[sid] = list(edges)

    info: Dict[str, Any] = {"deferred_by_upstream": [],
                            "blocked_by_upstream": {}}

    # ── #667: --skip-analog → propagate SKIPPED-CONDITION analog ──────
    # ancestry to its mixed-signal descendants. Runs BEFORE the #502 /
    # #503 passes so a now-SKIPPED M-step is no longer a MISSING that
    # those passes would re-attribute. A MISSING M-track step whose
    # blocks_on ancestry transitively reaches an analog step that is
    # SKIPPED-CONDITION inherits the skip. Gated purely on the structural
    # _track_of classification + declared blocks_on edges — chip-AGNOSTIC.
    if skip_analog:
        skipped_analog_ids = {
            r.id for r in results
            if r.status == "SKIPPED-CONDITION" and _track_of(r.id) == "analog"
        }
        if skipped_analog_ids:
            for r in results:
                if r.status != "MISSING" or _track_of(r.id) != "mixed":
                    continue
                # BFS over blocks_on ancestry → reaches a skipped analog step?
                queue = list(parents_of.get(r.id, []))
                seen: set = set()
                hit = None
                while queue:
                    pid = queue.pop(0)
                    if pid in seen:
                        continue
                    seen.add(pid)
                    if pid in skipped_analog_ids:
                        hit = pid
                        break
                    queue.extend(parents_of.get(pid, []))
                if hit is None:
                    continue
                r.status = "SKIPPED-CONDITION"
                r.cascade_note = f"skipped-by-upstream-analog({hit})"
                r.reasons.insert(0, (
                    f"mixed-signal track skipped via --skip-analog: this "
                    f"step's blocks_on ancestry reaches the SKIPPED-CONDITION "
                    f"analog step {hit}; its mixed-signal sign-off artefacts "
                    f"only exist once the deliberately-skipped analog track "
                    f"has run — skip inherited (review_required at "
                    f"analog/foundry sign-off), not an independent gap"
                ))

    # ── #502: waiver-chain propagation over blocks_on ancestry ──────
    deferred_ids = {r.id for r in results if r.status == "WAIVED"}
    _ticket_re = re.compile(r"ticket=([^\s,\]]+)")

    def _ticket_for(pid: Any) -> str:
        w = waivers.get(pid) or {}
        if w.get("ticket"):
            return str(w["ticket"])
        parent = by_id.get(pid)
        if parent is not None:
            for reason in parent.reasons:
                m = _ticket_re.search(reason)
                if m:
                    return m.group(1)
        return "?"

    for r in results:
        if r.status != "MISSING":
            continue
        # BFS over blocks_on ancestry → nearest deferred ancestor wins.
        queue = list(parents_of.get(r.id, []))
        seen: set = set()
        hit = None
        while queue:
            pid = queue.pop(0)
            if pid in seen:
                continue
            seen.add(pid)
            if pid in deferred_ids:
                hit = pid
                break
            queue.extend(parents_of.get(pid, []))
        if hit is None:
            continue
        ticket = _ticket_for(hit)
        r.status = "DEFERRED-BY-UPSTREAM"
        r.cascade_note = f"deferred-by-upstream({hit}, ticket={ticket})"
        r.reasons.insert(0, (
            f"deferred-by-upstream({hit}, ticket={ticket}): this step "
            f"consumes outputs that step {hit}'s waiver deferred — same "
            f"waiver, not an independent gap"
        ))
        info["deferred_by_upstream"].append((r.id, hit, ticket))

    # ── #503: first-FAIL cut point per declared chain ────────────────
    tracks: Dict[str, List[Any]] = {}
    for sid in order:
        track = _track_of(sid)
        if track:
            tracks.setdefault(track, []).append(sid)
    for track_ids in tracks.values():
        first_fail: Any = None
        for sid in track_ids:
            r = by_id.get(sid)
            if r is None:
                continue
            if first_fail is None:
                if r.status == "FAIL":
                    first_fail = sid
                continue
            if r.status == "MISSING":
                r.cascade_note = f"blocked-by-upstream({first_fail})"
                r.reasons.append(
                    f"blocked-by-upstream(step {first_fail}): cascade of "
                    f"the first mid-chain FAIL — the chain stops at step "
                    f"{first_fail}; fix that root cause first"
                )
                info["blocked_by_upstream"][first_fail] = (
                    info["blocked_by_upstream"].get(first_fail, 0) + 1)
    return info


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
            # ORGANIC-20260614 (#632) — thread --skip-analog into the P0
            # umbrella the same way check_step receives it, so the analog
            # sub-gates obey the flag instead of FAILing the umbrella for
            # an explicitly-deferred analog track.
            skip_analog=getattr(args, "skip_analog", False),
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
    # Build the per-step evaluation list, preserving canonical YAML order
    # (P0 umbrella + suppressed duplicate Step 14 already emitted above).
    _eval_steps = [
        step for step in steps
        if step.get("id") != "P0"
        and not (suppress_yaml_step14 and step.get("id") == 14)
    ]
    _workers = _compliance_workers(len(_eval_steps))
    if _workers <= 1:
        for step in _eval_steps:
            results.append(check_step(
                project, step, waivers,
                skip_analog=skip_analog, skip_hardware=skip_hardware))
    else:
        # Independent read-only gates → evaluate concurrently; collect the
        # futures in SUBMISSION order so `results` stays byte-for-byte the
        # same list the sequential path produced (see `_compliance_workers`).
        with ThreadPoolExecutor(max_workers=_workers) as _ex:
            _futs = [
                _ex.submit(check_step, project, step, waivers,
                           skip_analog=skip_analog, skip_hardware=skip_hardware)
                for step in _eval_steps
            ]
            for _fut in _futs:
                results.append(_fut.result())

    # v0.3.5 — ORGANIC #502/#503: cascade attribution AFTER all step
    # verdicts are final (waiver conversions included): waiver chains
    # propagate over blocks_on edges; post-FAIL MISSING runs are
    # attributed to their first-FAIL root cause.
    cascade_info = _attribute_cascade_verdicts(
        results, steps, waivers, skip_analog=skip_analog)

    # v0.100 H2: advisory — warn if post-route STA passed single-corner only
    advisories: List[str] = []

    # #216 — a rejected ENV_UNAVAILABLE waiver is reported, never dropped.
    # Without this the step showed a bare MISSING and the reader could not
    # tell that a waiver had been attempted, let alone why it did not apply.
    advisories.extend(_ENV_WAIVER_REJECTIONS)
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
              "DEFERRED-BY-UPSTREAM": 0,
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
    # v0.3.5 — #502: DEFERRED-BY-UPSTREAM is deferred work tied to the
    # parent's waiver ticket, so it leaves the required denominator the
    # same way the parent's WAIVED does.
    total_required = (len(steps) - counts["WAIVED"]
                      - counts["DEFERRED-BY-UPSTREAM"]
                      - counts.get("SKIPPED-CONDITION", 0))
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
    # v0.3.5 — #503: split cascade MISSING from independent gaps in the
    # summary so the actionable root-cause surface is visible at a
    # glance; #502: surface the waiver-chain bucket separately.
    missing_str = f"MISSING={counts['MISSING']}"
    _blocked = cascade_info.get("blocked_by_upstream") or {}
    if _blocked:
        missing_str += " (" + ", ".join(
            f"{n} blocked-by-upstream of step {sid}"
            for sid, n in _blocked.items()) + ")"
    dbu_str = (f"  DEFERRED-BY-UPSTREAM={counts['DEFERRED-BY-UPSTREAM']}"
               if counts.get("DEFERRED-BY-UPSTREAM") else "")
    print(
        f"  PASS={counts['PASS']}  FAIL={counts['FAIL']}  "
        f"{missing_str}  WAIVED-DEFERRED={counts['WAIVED']}"
        f"{dbu_str}{skipped_str}{vacuous_str}\n"
    )

    _icon = {"PASS": "✓", "FAIL": "✗", "MISSING": "·", "WAIVED": "~",
             "DEFERRED-BY-UPSTREAM": "~",
             "SKIPPED-CONDITION": "-", "SKIPPED-SETUP-REQUIRED": "!",
             "VACUOUS_PASS": "○"}
    _label = {"PASS": "PASS", "FAIL": "FAIL", "MISSING": "MISSING", "WAIVED": "WAIVED-DEFERRED",
              "DEFERRED-BY-UPSTREAM": "DEFERRED-BY-UPSTREAM",
              "SKIPPED-CONDITION": "SKIPPED-CONDITION",
              "SKIPPED-SETUP-REQUIRED": "SKIPPED-SETUP-REQUIRED",
              "VACUOUS_PASS": "VACUOUS-PASS"}
    for r in results:
        icon = _icon.get(r.status, "?")
        label = _label.get(r.status, r.status)
        sid_str = f"{r.id:>2}" if isinstance(r.id, int) else f"{r.id:>2}"
        note = f"  [{r.cascade_note}]" if r.cascade_note else ""
        print(f"  {icon} [{label:<17}] Step {sid_str}: {r.name}  ({r.stage}){note}")
        for reason in r.reasons:
            print(f"       └─ {reason}")

    # v0.119.43 Wave 11 / v0.119.53 Wave 21 — strict-structural
    # Phase-2 verdict.
    # When --phase 2 + --strict-structural is requested, harvest every
    # individual structural-RTL gate FAIL from the P0 umbrella (and,
    # when the broader --strict-step-artifacts is also set, from
    # Phase 2 step results 1-13 as well). Emit an explicit "Phase 2
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
                # Phase 2 step-level FAIL/MISSING. With --strict-step-
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

    # ── step-execution ordering guard (flow_step_execution_coverage_check) ──
    # compute_cascade only cascades FAIL/WAIVED ancestors and NEVER demotes an
    # already-PASS terminal step, so a hand-off step (GDSII / Foundry Handoff /
    # Tapeout) can be marked done while a step it transitively `blocks_on`
    # (Physical Verification / DRC / LVS / STA / extraction / antenna) is still
    # MISSING or FAIL — i.e. a GDS emitted before DRC ever ran. Enforce the
    # invariant here as a NON-promotable hard fail (set before the verdict and
    # the open-source-constraints promotion so it cannot be softened away).
    ordering_fail_lines: List[str] = []
    try:
        import flow_step_execution_coverage_check as _cov
        _cov_graph = {
            str(st.get("id")): [str(e) for e in (st.get("blocks_on") or [])]
            for st in steps if st.get("id") is not None}
        _cov_report = {"steps": [
            {"id": r.id, "name": r.name, "status": r.status,
             "stage": getattr(r, "stage", "")} for r in results]}
        for v in _cov.analyze(_cov_report, _cov_graph).get(
                "ordering_violations", []):
            ordering_fail_lines.append(
                f"[{v['terminal_id']}] {v['terminal']} = "
                f"{v['terminal_status']} marked done while dependency "
                f"[{v['signoff_id']}] {v['signoff']} = {v['signoff_status']}")
        if ordering_fail_lines:
            forced_fail = True
    except Exception:  # nosec — additive enforcement must never crash the audit
        ordering_fail_lines = []

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

    if ordering_fail_lines:
        print(f"\nStep-execution ordering violations "
              f"({len(ordering_fail_lines)}) — a hand-off step was marked done "
              f"before a step it depends on completed:")
        for line in ordering_fail_lines:
            print(f"  ✗ {line}")

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
            "ordering_violations": ordering_fail_lines,
            "steps": [asdict(r) for r in results],
        }
        Path(args.json).write_text(json.dumps(out, indent=2))

    # Wave 30 (v0.119.62) — emit a canonical machine-readable audit
    # artifact at `<project>/reports/phase23_completion_audit.json`
    # whenever flow_compliance_check runs. This is the contract the
    # mcp-eda pre-burn guard now consumes (replacing the
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
        # spm clean-run (2026-07-11) — resolve each artifact at BOTH the canonical
        # phase1/ (reports/phase1/) layout AND the legacy root layout, so this
        # human hint does not falsely list an artifact as "missing" when Phase 1
        # emitted it under phase1/. (Phase 1 canonically writes generated_docs →
        # phase1/generated_docs, extraction_patterns.json → phase1/, and the
        # coverage reports → reports/phase1/.) The label is kept stable for the
        # schema; only the existence probe is location-aware. This stays a hint —
        # the canonical FAIL signal is `verdict` + `failed_gates`.
        missing_required: List[str] = []
        _required_artifact_candidates = {
            "reports/extraction_coverage_report.md": (
                "reports/extraction_coverage_report.md",
                "reports/phase1/extraction_coverage_report.md"),
            "reports/extraction_coverage_report.json": (
                "reports/extraction_coverage_report.json",
                "reports/phase1/extraction_coverage_report.json"),
            "waivers.json": ("waivers.json",),
            "generated_docs": ("generated_docs", "phase1/generated_docs"),
            "extraction_patterns.json": (
                "extraction_patterns.json", "phase1/extraction_patterns.json"),
        }
        for label, cands in _required_artifact_candidates.items():
            if not any((project / c).exists() for c in cands):
                missing_required.append(label)

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
