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
SPICE correlation, post-route timing repair, power, metal fill, tapeout checklist) and
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

(b) has ONE documented exception, and it never yields a PASS. When EVERY
declared output of a step is absent AND a co-located sibling marker
unambiguously OWNS those outputs with a named capability flag, the step
resolves to SKIPPED-CONDITION (#675 strict) without the gate predicate being
evaluated — the gate reads the same absent outputs, so it could only restate
the absence. The step listing then names the gate that did not run, as an
ADVISORY line, so the omission is disclosed rather than inferred.

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

import ast
import argparse
import fnmatch
import functools
import glob
import json
import os
import re
import shlex
import sys
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple
from concurrent.futures import ThreadPoolExecutor
import _path_layout as _pl
import _reused_ip_predicate as _reused_ip
import _waiver_entries as _we
import _evidence_independence as _ev_ind  # #524
import _sim_results_bridge as _srb
import _gate_invocation
import _flow_reason_taxonomy as _reason_taxonomy
import _watchdog
import l_doc_consumer_contract as _ldoc
# vibe-ic#634 — the ONE classification of verdict words, shared with
# `flow_step_execution_coverage_check` so a tier added here cannot be
# unknown to the guard that adjudicates dependency ordering.
import _flow_verdict_tiers as _T
# The classified blocker list emitted BESIDE the tally. Import-only-downward:
# this module reads `_flow_verdict_tiers` and nothing from here, so the verdict
# path above cannot acquire a dependency on a classification.
import _blocker_classification as _bc
# The GUARD on the list `_bc` builds. Same downward direction: it reads
# `_blocker_classification` and `_flow_verdict_tiers` and nothing from here, so
# importing it cannot give the verdict path a dependency on a classification.
import blocker_classification_check as _bcc
import fpga_board_capability as _fpga_cap

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _progress_run as _pr  # noqa: E402

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
    # layergate-7 — l22_verification_plan_measurable_check FAILs (rc=1)
    # by its own contract: a measurable verification target stated in the
    # design's own inputs and carried by L22 zero times is the L21 defect
    # one layer over, and the gate blocks on it.
    #
    # It is listed here — reported per-step, excluded from the strict-
    # structural FAIL count — because of a MEASURED deployment fact, not
    # because the finding is soft. Fleet sweep 2026-07-25 over 136 real
    # Phase-1 runs on 5 machines: 50 runs FAIL, and every one is a TRUE
    # positive tracing to just TWO distinct evidence sites (the same two
    # designs repeated across plugin versions and PDKs):
    #   * <design-A>/phase1/input_doc/<name>_verification_plan.txt:45 — an
    #     acceptance table with "100% PASS" rows and a ">= 95%"
    #     toggle/branch row, while L22.coverage_goals == []  (34 runs)
    #   * <design-B>/phase1/input_doc/<core>_verification.txt:86 — "The
    #     goal of this bench is to fully verify the ... core with 100%
    #     coverage", while L22.coverage_goals == []            (16 runs)
    # Zero false positives; nothing to narrow. The gap is in Phase-1
    # extraction, not in the gate.
    #
    # Counting it as a blocker today would stop ~37% of in-flight
    # campaign runs on a pre-existing extraction gap that no downstream
    # step currently consumes (L22's only reader is
    # phase2_scaffold_gen.py, which greps it for a truncated 120-char
    # prose line). PROMOTION CRITERION: delete this entry once Phase-1
    # emits coverage_goals[] with numeric targets for those two designs
    # — the gate already returns rc=1 and needs no change.
    "l22_verification_plan_measurable_check",
    # batch-8 / layergate-8 — L25_RELIABILITY_MISSION_PROFILE has NO consumer
    # anywhere in the plugin: nothing derates STA or IR-drop by an aging
    # margin, nothing widens a corner set from a mission profile. Nothing
    # downstream is wrong today as a consequence of a bad L25, so blocking a
    # tapeout flow on it would be a gate asserting authority it does not have.
    # Its actionability rules also necessarily interpret free text, unlike the
    # purely-derivational L24/L26 gates in the same batch, and an interpretive
    # rule with no consumer should advise.
    #
    # PROMOTION TRIGGER (stated so it is not forgotten): the moment ANY
    # program reads L25 to derate STA/IR-drop or to widen a corner set, delete
    # this entry. From that point an unusable L25 silently produces optimistic
    # timing, and "advisory" becomes the same "FAIL and the flow continued
    # anyway" mistake that compounded the 2026-07 route-abort defect.
    "l25_reliability_envelope_actionable_check",
})


def _step_failure_is_informational_only(result: "StepResult") -> bool:
    """Return True iff every FAIL reason in `result` cites a gate in
    INFORMATIONAL_GATES (and at least one such reason exists). Used by
    the verdict pass to exclude informational-only step failures from
    `failing`. Reasons emitted by `_evaluate_gate` for failing
    program_exit_zero sub-gates start with `program failed: <cmd>`;
    we substring-scan for any informational gate name.

    THE P0 UMBRELLA USES A DIFFERENT REASON SHAPE. `_run_structural_rtl_gates`
    emits `FAIL: <gate> — <msg>` (and `  - <gate> — <msg>` when >=2 gates fail);
    the string `program failed:` never appears in that composition path. So the
    `startswith("program failed:")` scan below skipped EVERY P0 reason, left
    `saw_informational` False, and returned False for every P0 result — which
    silently disabled the exclusion for the three INFORMATIONAL_GATES that can
    only ever run INSIDE the umbrella (`l22_verification_plan_measurable_check`,
    `l25_reliability_envelope_actionable_check`,
    `periodic_timer_vs_rx_activity_check`). A P0 umbrella failing on nothing but
    those still reached `failing` -> `ok=False` -> `overall="FAIL"`, the exact
    outcome INFORMATIONAL_GATES exists to prevent, and the opposite of what the
    caller at the `informational_only_failing` deferral site already assumes
    (it carries an `r.id == "P0"` branch that was unreachable).

    #497 STEP 2 — the P0 half no longer parses anything. It reads the failing
    gates out of the umbrella's structured `gate_records`, so a line shape the
    umbrella adds tomorrow cannot change what this `all(...)` returns. That is
    the whole point: this predicate decides whether a step reaches `failing`,
    so a mis-parse here is a VERDICT change. Non-P0 steps take the original
    path unchanged (they publish no records; their reasons are a different
    grammar written by `_evaluate_gate`)."""
    if result.status != "FAIL" or not result.reasons:
        return False
    saw_informational = False
    if getattr(result, "id", None) == "P0":
        p0_failing = _p0_failing_gate_names(_p0_gate_records(result))
        if not p0_failing:
            # No sub-gate FAILed (only SKIP / NOT_INVOCABLE / WAIVED records,
            # or no records at all) — say nothing rather than assert
            # informational-only.
            return False
        return all(g in INFORMATIONAL_GATES for g in p0_failing)
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
    # Storage-buffer occupancy flags (empty/full family) registered from a
    # STALE same-block-advanced pointer settle one cycle late. A FIFO / LIFO /
    # stack / queue whose `full`/`empty` is `flag <= (ptr == LVL)` in the same
    # posedge block that does `ptr <= ptr +/- k` samples the OLD pointer, so
    # the flag asserts one cycle after the push/pop that changed occupancy —
    # the boundary vector that samples the flag on the transition cycle fails
    # deterministically. Chip-AGNOSTIC: keys only on the occupancy-flag output
    # name + an advancing pointer; SKIPs any design without such a flag.
    "buffer_occupancy_flag_latency_check",
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
    # P0's own `notes` in flow/phase1_phase2_phase3.yaml name
    # `cdc_async_input_check` as one of the gate names that appear in the
    # audit JSON's `gates:` array. That array is built exclusively from this
    # tuple (see `_run_structural_rtl_gates` -> the P0 StepResult), and the
    # checker was NOT in it — so the flow's own documentation advertised a
    # checker P0's mechanism could not emit. It is a chip-AGNOSTIC structural
    # RTL screen (>=2-stage synchroniser on asynchronous inputs) of exactly
    # the kind this registry holds, it ships as `programs/cdc_async_input_check
    # .py`, and it takes the `<project_dir>` argv shape the umbrella
    # dispatches. Registering it is what makes P0's prose true; the ASIC-side
    # twin of `fpga_async_input_synchronizer_check` directly above. It also
    # remains Step 3's own blocking gate, so this changes WHEN a project with
    # unsynchronised async inputs is told, not WHETHER.
    "cdc_async_input_check",
    # The RTL-level counterpart of the two CDC gates above. `cdc_async_input_
    # check` screens top-level INPUT PORTS for a 2-flop synchroniser, and
    # `cdc_crossing_check` reads a CDC REPORT (accepting SKIPPED-CONDITION for a
    # multi-clock design as a disclosed capability gap). Between them, an
    # INTERNAL register written under one clock and read under another — not a
    # port, not conventionally named — was screened by neither, so a multi-clock
    # design could clear Step 3 with no RTL crossing analysis at all. This gate
    # reads the RTL and reports an unsynchronised crossing, the shape that makes
    # a status flag in the receiving domain fail to assert. Single-clock modules
    # are skipped by construction, so it cannot fire on them.
    "clock_domain_reg_crossing_check",
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
    # batch layergate-1 — SEMANTIC layer gates. Where the B-wave gates
    # above assert that a KEY EXISTS, these assert that the VALUE is
    # something the consumer can act on, and derive the requirement from
    # the design's OWN machine-readable inputs / sibling L-docs. All
    # three also run inside phase1_doc_one_shot_runner (blocking), so
    # the phase1 convergence loop sees them — unlike the B-wave gates,
    # which are reachable only from here.
    #   L1: a pin the design's own inputs declare as a multi-bit bus
    #       must resolve to an integer width, or phase2 emits a 1-bit
    #       port and l9_rtl_pin_consistency_check diffs five steps later.
    "l1_pin_bus_width_actionable_check",
    #   L2: a constant a sibling L-doc dereferences BY NAME must resolve
    #       to a concrete number in L2. Both known dereference paths
    #       (l8_frame_end_gap_derivation, l9_response_delay_schema) fail
    #       SILENTLY when it is absent.
    "l2_named_constant_resolvable_check",
    #   L3: the dispatcher keys on `hex`, not on `name`. An unparseable
    #       or colliding hex is silently dropped/overwritten by
    #       design_one_shot_runner's `l3_by_hex[h] = op`.
    "l3_opcode_dispatch_key_actionable_check",
    #   B3: L4 multi-bit register fields with enum-style names
    #       (DLY/MODE/SEL/CFG/...) must declare enumerated_values[].
    #       Closes 4-state debounce / filter mode gap (audit line
    #       28, 67, 77).
    "l4_regmap_enumerated_values_typed_check",
    #   L4 denominator (#507): the enum-typing gate above audits the
    #       fields that are PRESENT and has no view of how many
    #       registers the input DECLARES, so a layer missing 84 of the
    #       145 address bindings its own staged HDL input declares
    #       reported PASS. This gate re-derives both sides — declared
    #       from the input, carried from L4 — so a shortfall cannot sit
    #       behind a numerator with no denominator.
    "l4_regmap_declared_register_coverage_check",
    # layergate-2 — SEMANTIC layer gates for L4/L5/L6. Each asserts the
    # layer carries what its CONSUMER needs in an ACTIONABLE form, by
    # importing the consuming program and inspecting its real output —
    # never by matching a token. All three BLOCK (see their docstrings)
    # because every failure mode they cover degrades SILENTLY in the
    # PASS direction several steps downstream.
    #   L4: diff L4 against the register block phase2_scaffold_gen
    #       actually emits — duplicate Verilog identifiers (uncompilable
    #       <top>_regs.v), an address present under a key
    #       derive_registers() never reads, ambiguous decode.
    "l4_regmap_phase2_emitter_contract_check",
    #   L5: every analog_blocks[] entry must yield a numerically-bounded
    #       spec through analog_real_corner_sweep.l5_block_specs() — the
    #       consumer's own parser. A prose spec string leaves the A-track
    #       grading against a generic default and stamping
    #       PASS_INFORMATIONAL. SKIPs on a pure-digital design.
    "l5_analog_block_spec_actionable_check",
    #   L6: derive_fsm_states() must yield a scaffoldable FSM (>=2 states,
    #       >=1 transition, no dangling targets), and every reject_rule
    #       must be machine-matchable by the L11/L12 coverage gate's own
    #       extractor — otherwise that gate takes its "accept any silent
    #       sequence" branch and goes vacuous.
    "l6_fsm_scaffold_actionable_check",
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
    # layergate-7 — SEMANTIC completeness gates for the consumer-less
    # backend-flow layers L20 / L22 / L23. These generalise the L21
    # post-mortem: the old `phase1_doc_input_completeness_check` models
    # completeness as "does this token appear in ANY layer", so a hard
    # macro's supply pin read as CAPTURED (L1 7x, L2 8x) while
    # L21_POWER_INTENT — the layer the BACKEND consumes — held it 0
    # times. The PDN got no rail, synthesis tied the pin off, a SIGNAL
    # net landed on a POWER terminal and TritonRoute aborted the whole
    # detailed route (3278 nets, 0 routed) five steps downstream.
    #
    # Each gate asserts the requirement is present IN THE LAYER THAT
    # CONSUMES IT, in actionable form, and derives its trigger from the
    # design's OWN inputs (its input docs, its sibling L-docs, its own
    # emitted backend artifacts) — never a design/PDK/vendor token.
    #
    #   L20: BLOCKS on an asserted-but-unbacked scan topology and on a
    #        DFT requirement stated in the design's own inputs but
    #        missing from L20. ADVISES when scan insertion demonstrably
    #        ran while L20 declares none — advisory only because NOTHING
    #        reads L20 today (dft_signoff_check / dft_atpg_coverage_check
    #        / dft_signoff_common / eda_dft all read coverage.json +
    #        bsdl_plan.json). Promote that finding to blocking the moment
    #        DFT insertion is wired to L20. Swept 136 real runs across 5
    #        machines: 0 blocking, 97 advisory, 39 skip.
    "l20_dft_scan_topology_actionable_check",
    #   L22: BLOCKS on a coverage goal with no comparable numeric target
    #        and on a measurable target stated in the design's own inputs
    #        but absent from L22. ADVISES on the `verification_plan_
    #        present: "implicit"` + prose-category shape that reads as
    #        populated to any non-empty heuristic while carrying zero
    #        enforceable target. See INFORMATIONAL_GATES for why its
    #        blocking verdict is not yet counted as a deployment blocker.
    "l22_verification_plan_measurable_check",
    #   L23: BLOCKS only on SELF-contradiction (asserting secure boot /
    #        key handling while carrying zero typed records with
    #        evidence) — that needs no consumer to be wrong. The
    #        cross-layer half ADVISES, because L23 has NO consumer
    #        anywhere in the plugin and there is no downstream contract
    #        to protect by stopping. Swept 136 runs: 0 blocking, 13
    #        advisory (all on one crypto-accelerator design whose own
    #        docs specify side-channel + fault-injection countermeasures
    #        while L23 says security_requirements_present=false), 123
    #        skip.
    "l23_security_requirements_typed_check",
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
    #   the actual RTL port list. VACUOUS_PASS when L9 is absent, when it
    #   carries no submodules, OR when every declared submodule is one the
    #   gate cannot assert on (bare string / naming-delegated
    #   `low_confidence`) — that last arm used to report PASS having
    #   examined nothing; the gate now reports `submodule_census`
    #   (declared / examined / skipped-by-reason) on every arm, so read it
    #   before treating a PASS here as submodule coverage. Real-world
    #   signal: v0117-vendor flags 9 genuine submodule gaps (L9 declares
    #   12 submodules, rtl/ emits 4).
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
    # Chip-level counterpart of analog_artefact_substance_check above.
    #   That gate catches 64-byte HEADER+ENDLIB stubs for ANALOG blocks;
    #   the top-level chip GDS had no equivalent. Its only content check
    #   was gds_size_check (flow step 37), which compares against a
    #   flow-wide 100 KB constant and demotes an invalid GDSII header to
    #   a WARNING — so 150 KB of random bytes behind a 4-byte HEADER, a
    #   zero-padded library with zero structures, and even-length junk
    #   that never reaches ENDLIB all reported `pass: true, errors: 0`
    #   and took Step 37 to PASS. This gate walks the full record stream
    #   and requires layout elements >= the design's own placed-instance
    #   count from routed.def (derived floor, no per-design constants).
    #   VACUOUS_PASS before GDS stream-out, so it is silent on
    #   phase-incomplete projects.
    "gds_substance_check",
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
    # #693 family `analog-hil` — the DE10-Lite board gate. Registered here for
    # the DIGITAL side of the corpus; A9 drives it separately at its declared
    # analog subject, because this umbrella never dispatches on a pure-analog
    # project (no rtl_dir -> `_P0_NO_RTL_NOTE`, measured 0 of 3 analog runs).
    # It takes the umbrella's default argv shape (one positional project path),
    # so unlike its sibling `fpga_qsf_lint` — which needs `--qsf-file
    # --rtl-dir` and is therefore parked in KNOWN_NOT_INVOCABLE, i.e. never
    # actually run — it is invocable here and DOES run. Measured over the 17
    # published runs: 13 dispatch, 1 (a real Phase-2 FPGA run) returns rc 0
    # PASS on a genuine DE10-Lite QSF, 12 return rc 2 NO_DATA into the skip
    # bucket. 0 newly red.
    "analog_hw_tb_de10lite_budget_check",
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
    # `skill_compliance_triangle_check` was registered here but the program
    # was never authored — `programs/skill_compliance_triangle_check.py` does
    # not exist and never has. The dispatch loop below used to `continue` past
    # a registry entry with no backing file WITHOUT recording anything, so the
    # umbrella advertised `len(_STRUCTURAL_RTL_GATES)` checkers while one
    # fewer ran. MEASURED two ways: (a) the reference run spm × ihp-sg13g2
    # (plugin 1.6.71-pr427) prints "P0 umbrella, 241 checkers" and its
    # flow_compliance_check.log never mentions this gate — not as PASS, SKIP,
    # FAIL or WAIVER; (b) re-running that project on this tree's parent
    # printed "242 checkers" while exactly 241 subprocesses were spawned.
    # Removed from the registry so the advertised count equals the dispatched
    # count; the dispatch loop now also records a named SKIP for any future
    # entry whose program is missing, so this cannot go silent again.
    # Authoring the real skill-triangle checker (SKILL.md / compliance.yaml /
    # tests) is still open work — it is NOT covered by
    # phase1_gate_contract_check, which audits deterministic flow programs,
    # not skills.
    # The spec said the plugin MUST declare an artifact, the plugin did not,
    # and NO gate noticed — because a gate that nothing invokes notices
    # nothing.  spec_required_artifact_check reads the project's OWN Phase-1
    # input docs (BOTH the Layout-P canonical `phase1/input_doc/` and the
    # legacy `input/docs/`) and generated L-docs, and asserts that each
    # PATH-SHAPED artifact those docs make mandatory exists non-empty.
    # Silent-skips cleanly on incomplete projects: a project with no
    # imperative clause returns VACUOUS_PASS / rc=0, which is why it meets
    # the v1.6.4 wiring criterion.  Only path-shaped tokens are asserted on
    # (a backticked `valid` / `rst_n` after a MUST-verb is a signal name, not
    # a required artifact) — see _is_path_shaped in that program.
    "spec_required_artifact_check",
    "testbench_exists_check",
    "tester_oracle_health_check",
    # The deliverable may not contradict the orchestrator it summarises.
    # MEASURED escape (2026-07-26): RESULT.md written 01:39 with headline
    # `PASS_WITH_WAIVERS`; a 09:44 invocation rewrote
    # reports/orchestrator/vibe_ic_one_shot.json to `verdict: FAIL`
    # (halted_at=phase3) and nothing re-read it, so the run SHIPPED a PASS over
    # its own FAIL with every gate green. Compares the deliverable's own
    # headline (agent-produced markdown) against the runner's JSON — two
    # independently-produced values — and fails ONLY the escape direction
    # (deliverable PASS over orchestrator FAIL). rc 2 = genuine SKIP when no
    # headline is stated or no orchestrator report exists, so it stays silent
    # on every project the defect cannot apply to: measured over 101 corpus
    # deliverables (benchmark-data/ + benchmark_external/ + campaign_*), it
    # fired ZERO times and compared 8.
    "deliverable_verdict_consistency_check",
    # batch-8 / layergate-8 — SEMANTIC gates for the three consumer-less
    # completeness layers (L24 / L25 / L26). None of the three has a consumer
    # today, so none demands CONTENT. Each instead forbids the one shape that
    # would be a lie if a consumer were ever wired in: a verdict asserted
    # without evidence. Motivated by the 2026-07 route abort, where a
    # completeness verdict computed from the wrong premise ("the token appears
    # in SOME layer") left L21 — the layer the backend consumes — empty, and
    # TritonRoute aborted 3278 nets five steps downstream.
    #   L24: every asserted sign-off status must trace to a report path INSIDE
    #        the project plus the value read back from it. SKIPs on the inert
    #        layer all real runs emit today (144/144 swept, 0 false positives).
    #        BLOCKS — Phase 1 runs before DRC/LVS/STA exist, so it has no
    #        legitimate reason to certify their outcome.
    "l24_signoff_evidence_backed_check",
    #   L25: a reliability margin must be a number BOUND TO A UNIT, traceable
    #        to this design's own source, and its envelope must cover the
    #        operating temperatures the design's own L-docs declare. ADVISES
    #        (see INFORMATIONAL_GATES) — nothing derates STA or IR-drop from
    #        L25 yet, so it must not block a tapeout flow.
    "l25_reliability_envelope_actionable_check",
    #   L26: applicability must be DERIVED from the run's own ic_class via
    #        l_doc_taxonomy, never asserted, and an N/A must say why. Purely
    #        derivational — no keyword scan, no threshold — so it cannot fire
    #        on a legitimately-N/A design. BLOCKS.
    "l26_mechanical_applicability_derived_check",
    # harvest(#319 via #349) — L19 SEMANTIC completeness gate: the fixed die
    # phase3 honors verbatim (L19-1), and the PDK target the foundry pack
    # states / the analog substitution discloses must be TRACEABLE to the
    # design's own inputs (L19-2) and non-null when the design stages a PDK
    # enablement (L19-3). Untraceable target = fabricated foundry statement.
    # SKIPs (rc=2) without an L19 doc, so incomplete projects never fail on
    # a missing prerequisite (the v1.6.4-retraction lesson, honored here).
    # Corpus-verified: sha256/subservient PASS (sky130 traceable), spm SKIP,
    # both injected negatives FAIL. Honors waiver
    # `l19_pdk_floorplan_contract_disclosed` (>=40 chars).
    "l19_pdk_floorplan_contract_check",
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
    # DFT_FCC / 11-d7 — True when this step is SKIPPED-CONDITION because the
    # runner emitted a DISCLOSED CAPABILITY-GAP marker for it (the #608/#675
    # self-skip evidence: a self-skip verdict + a named capability_flag).
    #
    # SKIPPED-CONDITION covers three quite different situations and they must
    # not be conflated:
    #   (a) the step is genuinely INAPPLICABLE — its `condition` is unmet
    #       (no analog blocks on a digital chip), or the operator deferred a
    #       whole track (`--skip-analog`). Costs nothing; correct.
    #   (b) a class-N/A skip attributed by the IC-class table.  Same.
    #   (c) the step SHOULD have run, its sign-off artefact does NOT exist,
    #       and the runner DISCLOSED a capability gap instead. That is a real
    #       unmet requirement wearing an explanation.
    # Only (c) sets this flag, and only (c) is routed into the verdict.
    self_skip_disclosed: bool = False
    # True when a gate on this step disclosed that an artefact it certifies
    # carries no design-bound content. Set INDEPENDENTLY of `status`: when the
    # step otherwise passes the status becomes STRUCTURE-ONLY, and when it
    # fails for another reason the FAIL stands and this flag is what puts the
    # disclosure on the tally line anyway.
    structure_only_disclosed: bool = False
    # vibe-ic#901 - True when SOME (not all) of this step's dispatched gate
    # clauses declared, in their own --json report, that they examined nothing.
    # The step KEEPS whatever tier its other clauses earned, because those DID
    # examine the design; this field, the `reasons` line beside it and the
    # tally annotation are what stop that partial emptiness from vanishing into
    # a bare PASS. False on a step whose EVERY dispatched clause was vacuous -
    # that one is VACUOUS_PASS, which already says so.
    partial_vacuity_disclosed: bool = False
    # vibe-ic#901 - True when THIS step reached VACUOUS_PASS through the
    # structured-JSON channel added here rather than through the pre-existing
    # rc=2 / stdout channel. Read by the ordering-violation pass so the new
    # channel cannot DELETE a `PASS voided: dependency ...` line that origin/main
    # would have printed. Never read as a tier.
    json_vacuity_promoted: bool = False
    # W4 - one entry per `optional_program_exit_zero` clause on this step whose
    # `condition_files_exist` matched NO path, so the program never ran and the
    # clause concluded nothing. Each entry carries the command and the reason
    # the clause DECLARED for why an absent input is a genuine not-applicable;
    # a clause that declares none is a FAIL and never reaches this list. Empty
    # on a step where every declared clause was executed, which is the only
    # state in which a bare PASS means what it says.
    declared_not_applicable: List[str] = field(default_factory=list)
    # #497 step 1 — the STRUCTURED per-gate payload, emitted ALONGSIDE
    # `reasons` and read by nothing yet.
    #
    # `reasons` is a prose list carrying six distinct line shapes, and four
    # separate consumers re-derive its grammar from prefixes. Two of those
    # consumers are `all(...)` predicates, so a mis-parse changes a VERDICT
    # rather than a report. Three production breakages have come out of that
    # one mechanism (empty `failed_gates` at >=2 failures; the #492 NOT-INVOKED
    # disclosure scraped as 75 phantom failing gates; `passed_gate_count`
    # pinned at 0 for its whole existence). This field is the beginning of the
    # removal: the umbrella states each gate's outcome ONCE, in a typed record,
    # with `NOT_INVOCABLE` a first-class verdict instead of a prose marker.
    #
    # THREE-STATE ON PURPOSE.  `None` means "this step publishes no structured
    # gate records" — the honest answer for the ~56 flow steps, the A1-A9 and
    # M1-M4 tracks, and any P0 whose umbrella did not run at all. `[]` means
    # "published, and no gate was considered" — a real and different state (a
    # project with no RTL: the umbrella reports SKIPPED-CONDITION having
    # dispatched nothing). A `default_factory=list` would have merged those two
    # into one `[]` and reintroduced, in the replacement, the exact ambiguity
    # the replacement exists to remove.
    #
    # Serialisation note: `asdict` emits every field, so the `--json` report
    # gains `"gate_records": null` on every step that does not publish. That is
    # deliberate — a KEY THAT IS SOMETIMES ABSENT would force each consumer to
    # decide for itself what a missing key means, which is the same
    # re-derive-the-contract failure in a new place. One uniform key, one
    # explicit "not published" value.
    #
    # Record shape (see `_p0_gate_record`):
    #   {"name": str, "verdict": one of P0_GATE_VERDICTS,
    #    "message": str, "evidence": dict}
    gate_records: Optional[List[Dict[str, Any]]] = None
    # Issue #1980 — one lossless record for every dispatched
    # `advisory_program_exit_zero` clause.  Unlike the historical prose hint,
    # this preserves the process exit code, the program's structured verdict,
    # and the enforcement disposition as separate machine-readable facts.
    advisory_gate_records: List[Dict[str, Any]] = field(default_factory=list)
    # Programs that produce or classify evidence are declared on the step but
    # are not predicates.  Their pre-existing outputs remain visible in the
    # final audit here without entering the gate denominator.
    program_output_records: List[Dict[str, Any]] = field(default_factory=list)
    # WHICH QUESTION THIS STEP'S `required_outputs` VERDICT ANSWERS.
    #
    # Until this field existed, a `required_outputs` PASS meant only "a file
    # matching the glob exists somewhere under the project" and was printed
    # identically whether or not anything tied that file to this step. This
    # says which of the two it is, per step:
    #
    #   {"mode": "step_attributed" | "project_glob" | "mixed",
    #    "n_specs": int, "n_step_attributed": int, "n_project_glob": int,
    #    "source": "step_folder" | "run_ledger" | None,
    #    "notes": [str, ...]}
    #
    # `None` means the step declares no `required_outputs` — there was no
    # resolution to attribute, which is a third state and not a degraded one.
    # `project_glob` is the BACKWARD-COMPATIBLE path and is never silent: the
    # `notes` say why (`no_steps_tree` for a published cell or a phase-driven
    # run, `no_step_record`, a named resolver disagreement), and a PASS-tier
    # step additionally carries a line in `reasons` so a reader of the TEXT
    # report can tell a step-attributed PASS from a project-wide one without
    # opening the JSON.
    output_binding: Optional[Dict[str, Any]] = None


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


def _resolves_to_real_artefact(p: Path) -> bool:
    """True when a glob hit is a path that ACTUALLY EXISTS once links are
    followed — i.e. when something was really produced there.

    `Path.glob` answers a question about DIRECTORY ENTRIES, not about files.
    For a wildcard component it walks `os.scandir` and yields every matching
    NAME without ever following it, so a symlink whose target was never
    written — or was deleted afterwards — comes back as a match. `stat` (and
    therefore `Path.exists`) follows the link and answers about the TARGET,
    which is the thing the flow step was required to produce.

    That split is already visible INSIDE `Path.glob` itself and is the whole
    bug. A pattern with NO wildcard is served by pathlib's precise selector,
    which existence-checks the name before yielding it, so a literal pattern
    ALREADY drops a dangling link; a pattern with a wildcard is served by the
    scandir selector and does not. Measured on CPython 3.10.12 with
    `sub/chip.gds -> ./nowhere.gds`:

        d.glob("sub/*.gds")    -> ['chip.gds']     # dangling link yielded
        d.glob("sub/chip.gds") -> []               # dangling link dropped

    So `phase3/stage4/gds/*.gds` (step 37's `required_outputs`) counted a
    link-to-nowhere as a produced tape-out GDS while
    `phase2/stage2/synth/post_dft_netlist.v` (step 12's, no wildcard) did not.
    This predicate removes the inconsistency by giving every pattern the
    literal pattern's already-correct behaviour.

    Non-symlinks are returned True UNCONDITIONALLY and deliberately: `glob`
    only yields entries `scandir` just reported, so re-stat'ing an ordinary
    file could only ever manufacture a FALSE absence (EACCES on a parent, a
    racing writer) for an artefact that is really there. Narrowing the new
    rejection to `is_symlink()` is what keeps this fix from being able to
    invent a new MISSING for any non-symlink path.

    A symlink is NOT rejected for being a symlink — it is judged on what it
    points at. Link -> real file (or real dir, or a chain ending at one) is
    kept and every downstream read of it follows through to the target's own
    bytes, size and mtime, because every such read goes through `stat`/`open`.
    Only link -> nothing is dropped. A symlink LOOP resolves to nothing and is
    therefore dropped too (`Path.exists` swallows the ELOOP `OSError` and
    returns False).

    This is the same rule `chip_gds_canonical_real_file_check.py` already
    ships for the canonical GDS paths, quoted from its own module docstring:
    "Existing `gds_size_check` follows symlinks transparently and reports the
    target's size, so a symlink masking a missing tape-out artefact passes
    audit." That gate is stricter — it bans symlinks at canonical GDS paths
    outright. This one is the weakest rule that closes the falsely-green hole
    everywhere, and it is deliberately weaker so that a symlink TREE stays
    legal: see `_glob_first`.
    """
    try:
        if not p.is_symlink():
            return True
        return p.exists()
    except OSError:
        return False


def _glob_real(root: Path, pattern: str) -> List[Path]:
    """`root.glob(pattern)`, sorted, with dangling symlinks removed.

    Applied at EACH probe site in `_glob_first` rather than once over the
    final result: a probe that matched nothing but dangling links must count
    as a MISS so the `reports/<subdir>/` and canonical-analog fallbacks still
    get their turn. Filtering only at the end would let a link-to-nowhere in
    the first probe suppress the fallbacks and turn a findable artefact into
    a spurious MISSING.

    A pattern that names the ROOT rather than something under it matches no
    artefact, and is answered here instead of being handed to `Path.glob`,
    which THROWS on all three of its spellings (3.12 — each compiles to no
    selectable part):

        Path.glob(".")   IndexError: tuple index out of range
        Path.glob("")    ValueError: Unacceptable pattern
        Path.glob("./")  AttributeError: '_TerminatingSelector' object has no
                         attribute 'select_from'

    None is hypothetical. `"."` is what `Path("seed.flag").parent` is for ANY
    project-root-relative declaration, and `_sibling_self_skip_for_missing`
    hands that parent straight to this function for every missing `files_exist`
    pattern; `""` is what the analog-remap branch of `_glob_first` computes as
    `tail` when a pattern equals its own prefix. `check_step` runs in a
    `ThreadPoolExecutor` and `main()` re-raises via `_fut.result()`, so the
    throw does not fail one gate — it aborts the entire audit with a traceback,
    no report and no exit code, which is strictly worse than the MISSING it was
    on its way to computing.

    Empty rather than "the root itself": the root is not an artefact any caller
    is looking for, and the one caller that wants it as a DIRECTORY
    (`_sibling_self_skip_for_missing`) already holds it as `project /
    parent_rel` — `Path(p) / "." == Path(p)` — so nothing is lost.
    """
    if pattern.strip() in ("", ".", "./"):
        return []
    return sorted(m for m in root.glob(pattern)
                  if _resolves_to_real_artefact(m))


def _glob_first(project: Path, pattern: str) -> List[str]:
    """Return list of paths (relative to project) matching the glob pattern.

    Only paths that RESOLVE are returned. A dangling symlink is a directory
    entry, not a produced artefact, and this is the function every caller uses
    to decide whether a flow step delivered what it declared: `check_step`'s
    `required_outputs` probe and the `files_exist` gate
    (`_check_files_exist`) both go through here. MEASURED before the fix on
    the tracked run root `benchmark-data/ic/spm/v1.5.66_gf180mcuD`, step 1
    (`required_outputs: phase2/stage1/rtl/*.sv OR phase2/stage1/rtl/*.v`,
    gate `files_exist`): move every RTL file out of the project and leave a
    symlink to a name that exists nowhere, and `check_step` returns
    status='PASS' evidence=['phase2/stage1/rtl/spm.v']; delete those same
    files outright and it returns 'FAIL'. Both trees contain no RTL, so
    LEAVING A LINK TO NOTHING scored strictly BETTER than deleting the file —
    the audit rewarded the tidier way of shipping nothing.

    A symlink to a real file is kept and is judged on its target. That is not
    a loophole, it is required: the owner's step-folder design IS a symlink
    tree — `<run>/steps/<n>_<name>/<artefact> -> ../../phase2/...` — and the
    tracked run roots carry 142 such links. 111 of them point at real files
    and this function still returns every one; the 31 that point at files
    which no longer exist (e.g.
    `steps/9_synthesis_yosys_mapped_netlist/netlist.v ->
    ../../phase2/stage2/synth/netlist.v`, target absent) are exactly the
    artefacts-that-exist-nowhere this rule refuses to count. The step-folder
    design is unaffected; only its broken entries stop counting as delivery.

    For patterns starting with ``reports/`` and finding no direct match,
    also probe ``reports/<subdir>/<rest>`` to accommodate the post-
    generate sweep that moves flat reports/ artefacts into category
    subdirs (sourced by `_REPORTS_SUBDIR_FALLBACK`).
    """
    matches = _glob_real(project, pattern)
    if not matches and pattern.startswith("reports/"):
        rest = pattern[len("reports/"):]
        for sd in _REPORTS_SUBDIR_FALLBACK:
            matches = _glob_real(project, f"reports/{sd}/{rest}")
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
                    canon_matches = _glob_real(canon, tail)
                    if canon_matches:
                        matches = canon_matches
                        break
                except Exception:
                    pass
    return [str(m.relative_to(project)) for m in matches]


# ── STEP-ATTRIBUTED OUTPUT RESOLUTION ───────────────────────────────────────
#
# `_glob_first` answers "does a file matching this glob exist SOMEWHERE under
# the project". `check_step` then reads that answer as "did THIS step produce
# its declared output". Those are two different questions and the report has
# never distinguished them: every `required_outputs` PASS in the 63xN matrix
# looks the same whether the artefact sits where this step writes it or merely
# somewhere a project-wide glob could reach.
#
# `step_output_collector.materialize()` builds `steps/<phase>/<stage>/
# <id>_<slug>/` per step, and `step_write_ledger` writes the OBSERVATION half
# beside it (`written.json`, plus the run-level `reports/write_ledger.json`).
# Until this change NOTHING read either of them —
#   grep -rl 'write_ledger' programs/*.py flow/*.yaml
# returned only the two programs that WRITE it. This is the consumer.
#
# WHICH FILE IN THE STEP FOLDER IS THE SOURCE, AND WHY NOT THE OTHER ONE
# ---------------------------------------------------------------------
# The folder holds two files and only one of them is evidence.
#
#   outputs.json  is built from `required_outputs` via
#                 flow_dashboard_data._resolve_spec. It is a RESTATEMENT of
#                 the declaration; reading it to check the declaration is
#                 reading a cache of the question. It also LIES on a real run:
#                 on $HOME/_car15_evidence (a converged run,
#                 phase23_completion_audit = PASS_WITH_WAIVERS) the step
#                 folders record 90 outputs, and 7 of them — steps 15, 17, 19,
#                 20, 21, 22 and 34, every one of those folders carrying
#                 "status": "pass" — name a `rel` that does not exist in the
#                 run directory at all (floorplan.def, placed.def,
#                 post_cts.def, post_hold.def, routed.def,
#                 user_project_wrapper.spef, filled.def). Trusting it would
#                 have turned 7 currently-MISSING steps GREEN.
#   written.json  is the lstat observation: kind, size, mtime, and the
#                 declared-vs-landed residual, per THIS step's own specs.
#                 That is what this resolver binds to.
#
# WHAT "PRODUCED BY THIS STEP" CAN AND CANNOT MEAN HERE
# ----------------------------------------------------
# CAN: the resolution is scoped to the step's OWN declaration and the answer
# is recorded in the step's OWN folder, so a PASS is auditable at the step
# instead of re-derived from a project-wide scan; and the artefact the PASS
# rests on is the one that step's record names, re-verified live.
# CANNOT: name the writing STEP. The flow declares `programs:` / `mcp_tools:`
# per step; `provenance.jsonl` records EDA BINARIES (yosys/openroad/klayout)
# and, where it carries a `step` field at all, phase-scoped labels like
# "phase2:yosys_synth" (ONE distinct non-null value across the 32 records of
# $HOME/_sky130A_r3_run). There is no mapping between those
# vocabularies in this repo and this change does not invent one. So this is
# STEP-SCOPED ATTRIBUTION, not producer attribution, and it says so in the
# field name (`output_binding.mode = "step_attributed"`) rather than claiming
# more.
#
# SHARED ARTEFACTS ARE NOT A FAILURE — BY CONSTRUCTION
# ---------------------------------------------------
# Some outputs are legitimately written once and read by many. Measured on the
# shipped flow: of 161 distinct output patterns across 61 steps, exactly TWO
# are declared by more than one step (`phase2/stage2/synth/netlist.v` by steps
# 9 and 14; `phase3/mixed_signal/cosim/mixed_signal_results.json` by A9 and
# M3). Because the unit of attribution is the step's DECLARATION and not a
# single producer, both declaring steps resolve the same path independently
# and BOTH stay green — the ledger builds each step's row against the same
# snapshot. Had this been bound to "exactly one step may claim this write",
# one of each pair would have gone red for doing nothing wrong. It is not.
#
# MONOTONE ON PURPOSE — IT CAN ONLY TAKE AWAY
# -------------------------------------------
# Every branch below either returns the project-wide answer unchanged or
# returns a STRICTER one. There is no path on which a spec the project-wide
# glob calls MISSING becomes satisfied. A step-folder record can therefore
# never manufacture a green — which is what the `_car15_evidence` measurement
# above says it would have done if it could.
_STEP_BINDING_SCHEMA = 1


def _binding_stat_key(project: Path) -> Tuple[Any, ...]:
    """Cache key that INVALIDATES when the record changes.

    Keyed on (project, stat of steps/index.json, stat of the run ledger)
    rather than on the path alone: `check_step` is called ~63 times per audit
    in a thread pool and re-reading 63 `written.json` files per step would be
    63x the I/O, but a plain path-keyed cache would go stale the moment a
    caller (a test, a re-run) regenerates the tree inside one process."""
    def k(p: Path) -> Optional[Tuple[int, int]]:
        try:
            st = p.stat()
        except OSError:
            return None
        return (int(st.st_mtime_ns), int(st.st_size))
    return (str(project),
            k(project / "steps" / "index.json"),
            k(project / "reports" / "write_ledger.json"))


def _index_ledger_row(row: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """One `written.json` / run-ledger step row -> {spec: verdict}.

    The ledger emits exactly one of the two per declared spec: a `produced`
    entry (regular file, size > 0) or a D3 `declared_output_not_produced`
    finding carrying the reason it is not one (`absent` / `zero_byte` /
    `dangling_symlink` / `symlink_alias`). Both directions are indexed; a spec
    the row does not mention at all stays ABSENT from this map and is treated
    as "this step has no record for it", never as "not produced"."""
    specs: Dict[str, Dict[str, Any]] = {}
    for entry in (row.get("produced") or []):
        if not isinstance(entry, dict):
            continue
        spec = str(entry.get("spec", ""))
        rel = entry.get("rel")
        if not spec or not rel:
            continue
        slot = specs.setdefault(spec, {"produced": [], "not_produced": None})
        slot["produced"].append(str(rel))
    for finding in (row.get("findings") or []):
        if not isinstance(finding, dict):
            continue
        if finding.get("dimension") != "D3":
            continue
        spec = str(finding.get("spec", ""))
        if not spec:
            continue
        slot = specs.setdefault(spec, {"produced": [], "not_produced": None})
        if slot["not_produced"] is None:
            slot["not_produced"] = str(finding.get("reason") or "not_produced")
    return specs


@functools.lru_cache(maxsize=32)
def _load_step_binding_cached(key: Tuple[Any, ...]) -> Dict[str, Any]:
    project = Path(key[0])
    steps_root = project / "steps"
    index_path = steps_root / "index.json"

    def unavailable(reason: str) -> Dict[str, Any]:
        return {"schema": _STEP_BINDING_SCHEMA, "available": False,
                "reason": reason, "rows": {}, "sources": {}}

    if not index_path.is_file():
        # The BACKWARD-COMPATIBLE path, and the common one. Published cells
        # carry no `steps/` (benchmark_evidence_publish excludes it by name as
        # "per-step scratch"), and any run driven straight at a phase runner
        # never built one. Those runs get today's behaviour EXACTLY, and the
        # verdict records that they did.
        return unavailable("no_steps_tree")
    try:
        index = json.loads(index_path.read_text())
        folders = {str(s.get("id")): str(s.get("folder"))
                   for s in (index.get("steps") or [])
                   if isinstance(s, dict) and s.get("folder")}
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        return unavailable(f"steps_index_unreadable ({type(exc).__name__})")

    rows: Dict[str, Dict[str, Dict[str, Any]]] = {}
    sources: Dict[str, str] = {}
    for sid, folder in folders.items():
        wj = steps_root / folder / "written.json"
        try:
            row = json.loads(wj.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(row, dict) or str(row.get("id")) != sid:
            # A slice whose own `id` does not match the folder it sits in was
            # grafted from somewhere else. It is not this step's record.
            continue
        rows[sid] = _index_ledger_row(row)
        sources[sid] = "step_folder"

    # Run-level ledger fills gaps. It is the SAME observation written by the
    # same call (step_write_ledger.emit writes reports/write_ledger.json and
    # then slices it into the step folders), so it is step-scoped evidence
    # too — but a reader is told which of the two answered, because "the step
    # folder said so" and "the run ledger said so" are not the same claim.
    ledger_path = project / "reports" / "write_ledger.json"
    if ledger_path.is_file():
        try:
            led = json.loads(ledger_path.read_text())
            for row in (led.get("steps") or []):
                if not isinstance(row, dict):
                    continue
                sid = str(row.get("id"))
                if sid and sid not in rows:
                    rows[sid] = _index_ledger_row(row)
                    sources[sid] = "run_ledger"
        except (OSError, ValueError, TypeError):
            pass

    if not rows:
        return unavailable("steps_tree_without_write_record")
    return {"schema": _STEP_BINDING_SCHEMA, "available": True, "reason": None,
            "rows": rows, "sources": sources}


def _load_step_binding(project: Path) -> Dict[str, Any]:
    try:
        return _load_step_binding_cached(_binding_stat_key(project))
    except Exception as exc:                                  # noqa: BLE001
        # An unreadable record degrades to today's behaviour and SAYS SO. It
        # never fails a step: the thing that would be lost is an attribution,
        # not a verdict.
        return {"schema": _STEP_BINDING_SCHEMA, "available": False,
                "reason": f"binding_unreadable ({type(exc).__name__})",
                "rows": {}, "sources": {}}


def _live_artefact_state(p: Path) -> Tuple[bool, str]:
    """(is a produced artefact, kind) — decided LIVE, from lstat, right now.

    The step folder's record says WHICH path this step's spec resolved to;
    this says whether that path is still an artefact. Both halves are needed
    and neither is sufficient: a record alone is a claim about the past (the
    `_car15_evidence` folders claim 7 files that are not there), and a live
    scan alone is the project-wide glob this change exists to replace.

    `produced` mirrors step_write_ledger._classify's rule — a regular file
    with size > 0 — with ONE deliberate widening: a symlink that RESOLVES to a
    non-empty regular file counts. The ledger records that as `symlink_alias,
    produced=False` because an alias is not a write; but `_glob_first` accepts
    it today (its own docstring: "the owner's step-folder design IS a symlink
    tree ... the step-folder design is unaffected"), and rejecting it here
    would be a NEW red on a path whose bytes are really there. Measured across
    the 20 real run directories on this host that carry a `steps/` tree, ZERO
    of the 92-106 declared outputs per run is a symlink, so the widening
    costs nothing measurable and the narrowing would have been an unmeasured
    risk taken for free. A DANGLING link and a ZERO-BYTE file are not
    artefacts either way.
    """
    try:
        st = os.lstat(str(p))
    except OSError:
        return False, "absent"
    import stat as _stat
    if _stat.S_ISLNK(st.st_mode):
        try:
            tst = os.stat(str(p))
        except OSError:
            return False, "dangling_symlink"
        if _stat.S_ISDIR(tst.st_mode):
            return True, "symlink_to_dir"
        if not _stat.S_ISREG(tst.st_mode):
            return False, "symlink_to_non_file"
        return (tst.st_size > 0), (
            "symlink_alias" if tst.st_size > 0 else "symlink_to_empty_file")
    if _stat.S_ISREG(st.st_mode):
        return (st.st_size > 0), ("file" if st.st_size > 0 else "empty_file")
    if _stat.S_ISDIR(st.st_mode):
        # `_glob_first` accepts a directory match today; keeping that keeps
        # this resolver monotone.
        return True, "dir"
    return False, "other"


_GLOB_MAGIC = "*?["


def _alt_is_wildcard(alt: str) -> bool:
    """Does this ONE " OR " alternative name a set, or a path?

    `phase2/stage1/rtl/*.sv` names a set; `phase2/stage1/sim/results.xml`
    names a path. The distinction decides whether a live file that the step's
    write record does NOT name may stand in for one that it does — see
    WHAT A WILDCARD BINDS TO below. Split per ALTERNATIVE, not per spec,
    because the shipped flow really does mix the two inside one entry (step
    4: `phase2/stage1/sim/*.log OR phase2/stage1/sim/results.xml OR ...`;
    step 22: `.../parasitic.spef OR .../*.spef`)."""
    return any(c in alt for c in _GLOB_MAGIC)


def _bind_detail(code: str, **kw: Any) -> Dict[str, Any]:
    """One typed record of HOW a spec resolved, for a machine to act on.

    The prose `note` is for a person; this is the field a caller branches on.
    Closed vocabulary of `code` (anything else is a bug):

      step_attributed      the record names it, it is still an artefact
      recorded_set_partial the record names N, M<N survive — satisfied, and
                           the residual is stated as a NUMBER, not a mood
      wildcard_unbound     the record names N for a wildcard, ZERO survive,
                           and the only live matches are files this step
                           never recorded -> NOT satisfied
      recorded_but_absent  the record names N, zero survive, nothing else
                           matches -> not satisfied (pre-existing behaviour)
      credited_unrecorded_alt  a LITERAL " OR " alternative the spec names by
                           path is live while the recorded one is not — the
                           any-of the OR spelling exists for
      resolver_disagreement the record says not-produced, the project-wide
                           glob (with its reports/ sweep + analog remap)
                           found something live
      not_produced         the record says not-produced and nothing live
      no_step_record       this run's record does not mention this spec
      no_binding           this run has no usable record at all (the
                           BACKWARD-COMPATIBLE path: published cells,
                           phase-driven runs, corrupt index)
      audit_created        credited to a file this audit's own gate wrote
                           (set by the caller, after the gate has run)
    """
    d: Dict[str, Any] = {"code": code}
    d.update(kw)
    return d


def _resolve_required_output(project: Path, sid: Any, spec: str,
                             binding: Dict[str, Any]
                             ) -> Tuple[bool, List[str], str, Optional[str],
                                        Dict[str, Any]]:
    """Resolve ONE `required_outputs` entry for ONE step.

    Returns (satisfied, evidence_rels, mode, note, detail) where mode is
    "step_attributed" or "project_glob". `project_glob` is today's answer,
    unchanged, and always carries a note saying why the step-scoped record
    could not be used. `detail` is the same answer TYPED — see `_bind_detail`.

    WHAT A WILDCARD BINDS TO
    ========================
    `phase2/stage1/rtl/*.sv` had no binding force at all: rename the recorded
    `spm.v` to `spm_copy.v` and step 1 still PASSED, downgraded only to
    `mode: "mixed"` with a sentence a human was asked to read. Three readings
    of that pattern, and only one of them survives contact with the flow:

      "exactly the files the record names" — WRONG. A design legitimately
        gains an RTL file between runs, and set equality would red a step for
        someone adding a module. Additions are still green here, and the new
        file still enters the evidence list through the glob union below.
      "any file at all that matches the glob" — WRONG, and it is the defect.
        Under it, a file some OTHER step wrote, or a copy someone left
        behind, discharges this step's declaration. That is what the rename
        exploited.
      "the recorded output set still EXISTS, in part or in whole" — the rule
        implemented here. A wildcard spec whose record names N outputs is
        satisfied when at least ONE of those N is still an artefact.
        M-of-N is reported as `recorded_set_partial` with both numbers,
        because "recorded 5, resolves 4" and "recorded 5, resolves 0" are
        different facts and only the second is an absence.

    WHY "AT LEAST ONE" AND NOT "ALL N"
    ----------------------------------
    Measured on the three real ledger-bearing runs ($HOME/_sky130A_r3_run,
    campaign_v1544 gf180mcuD, campaign_v1574 sky130A, ledger generated by
    `step_write_ledger.emit`): 24 wildcard specs per run, 6-7 of
    them carrying a record, and the M-of-N state occurs ZERO times — every
    recorded wildcard output is either wholly present or wholly absent. So
    "all N" and "at least one" are INDISTINGUISHABLE on every real run
    available, and the choice must be made on which failure they invent.
    "All N" reds a step for a partial residual it has no evidence is a defect,
    and it keys the verdict on a list `step_write_ledger` truncates at
    `_MAX_LISTED` (4000) on a large SoC. "At least one" closes the measured
    hole — the demonstrated rename goes MISSING — and hands the residual to
    the caller as a number instead of spending it on a verdict it cannot
    justify.

    A LITERAL ALTERNATIVE IS NOT A WILDCARD, and keeps its any-of credit. The
    " OR " spelling exists for one artefact with two accepted names; a spec
    that NAMES `results.xml` by path and finds it is satisfied by it whether
    or not the record happens to name the other alternative. Only the
    wildcard alternatives lose the right to be discharged by a file the step
    never recorded writing.

    EVIDENCE SHAPE IS PRESERVED, and that is not cosmetic. The pre-change loop
    appended the FIRST hit of EVERY matching " OR " alternative, not one hit
    per spec, and `_evidence_integrity_scan` (#433/#434) then scans each
    entry — a shorter evidence list is a smaller scan and therefore a WEAKER
    check. Measured on real runs, 9 specs across four run roots really do
    contribute more than one entry (step 4's four-way sim spec, step 27's
    `si_crosstalk.rpt OR .json`, step 34's `filled.def OR metal_fill.done`),
    so collapsing to one would have quietly reduced what gets scanned.
    """
    alts = [a.strip() for a in str(spec).split(" OR ") if a.strip()]
    glob_ev: List[str] = []       # exactly what the pre-change loop collected
    glob_hits: List[str] = []     # every hit, for classification
    literal_hits: List[str] = []  # hits a NON-wildcard alternative NAMED
    n_wild = 0
    for sp in alts:
        if _alt_is_wildcard(sp):
            n_wild += 1
        hits = _glob_first(project, sp)
        if hits:
            glob_ev.append(hits[0])
            glob_hits.extend(hits)
            if not _alt_is_wildcard(sp):
                literal_hits.extend(hits)
    glob_sat = bool(glob_hits)

    if not binding.get("available"):
        return (glob_sat, glob_ev, "project_glob", binding.get("reason"),
                _bind_detail("no_binding", reason=binding.get("reason")))
    rec = (binding.get("rows") or {}).get(str(sid), {}).get(str(spec))
    if rec is None:
        return (glob_sat, glob_ev, "project_glob", "no_step_record",
                _bind_detail("no_step_record"))

    # (a) THE STEP'S OWN RECORD NAMES THE PATH(S). Re-verify live; the record
    #     is a statement about the past and must not outlive the file. Every
    #     one that survives is evidence, for the reason in the docstring.
    live_rec: List[str] = []
    for rel in rec["produced"]:
        if _live_artefact_state(project / rel)[0] and rel not in live_rec:
            live_rec.append(rel)
    if live_rec:
        # Emit the pre-change evidence SHAPE — the record's paths intersected
        # with what the old loop would have listed — rather than every path
        # the record names. Two reasons, both measured. (1) It keeps the
        # population `_evidence_integrity_scan` reads IDENTICAL, so any verdict
        # difference this change produces is attributable to the binding and
        # not to a scan that ran over a different set. (2) The record lists
        # EVERY match of a wildcard spec: on $HOME/_car15_evidence
        # step 1's `phase2/stage1/rtl/*.v` grew the evidence list from 1 entry
        # to 5, and #525 already had to stop that scan reading whole files
        # because it dominated audit wall-time on a large SoC. Falling back to
        # the record's own first path when the two do not intersect keeps the
        # step-attributed claim honest.
        # UNION, NOT INTERSECTION. This was
        #     ev = [r for r in glob_ev if r in live_rec] or live_rec[:1]
        # and it SHRANK the population `_evidence_integrity_scan` reads, which is
        # the one thing this binding must never do. MEASURED on a real run: with
        # `phase2/stage2/synth/area.rpt` truncated to 0 bytes, step 9 went
        # FAIL (#433, "evidence 0 bytes") -> PASS, because the 0-byte artefact was
        # not in the ledger's produced list and the intersection dropped it — a
        # change written to CATCH zero-byte outputs filtered a zero-byte output
        # out of view.
        #
        # A path the glob resolves is a path the scan must judge, whether or not
        # this step's ledger claims it. The ledger adds attribution; it does not
        # get to remove evidence.
        _seen: set = set()
        ev = [r for r in list(live_rec) + list(glob_ev)
              if not (r in _seen or _seen.add(r))]
        # Set-backed, not list-scan: `step_write_ledger` lists up to
        # `_MAX_LISTED` (4000) paths per row and this runs once per spec per
        # step in a thread pool. An O(n^2) dedup here is 16M comparisons on a
        # large SoC for a number nobody's verdict depends on.
        _seen_rec: set = set()
        _recorded = [r for r in rec["produced"]
                     if not (r in _seen_rec or _seen_rec.add(r))]
        _live_set = set(live_rec)
        _lost = [r for r in _recorded if r not in _live_set]
        if _lost:
            # M OF N. Satisfied — the recorded output set still exists in
            # part, and a design that drops one file of a wildcard set has
            # not failed to produce the set. Reported as two NUMBERS so a
            # consumer can act on the residual; a wildcard whose whole
            # recorded set is gone is the branch below, and it is not this.
            return True, ev, "step_attributed", (
                f"{len(live_rec)} of {len(_recorded)} recorded output(s) for "
                f"this pattern are still artefacts; no longer present: "
                f"{_lost[:3]}"), _bind_detail(
                    "recorded_set_partial", recorded=len(_recorded),
                    live=len(live_rec), lost=_lost[:6],
                    wildcard_alternatives=n_wild)
        return True, ev, "step_attributed", None, _bind_detail(
            "step_attributed", recorded=len(_recorded), live=len(live_rec))
    if rec["produced"]:
        detail = "; ".join(
            f"{r} ({_live_artefact_state(project / r)[1]})"
            for r in rec["produced"][:2])
        _rec_set = set(rec["produced"])
        alt = [h for h in glob_hits
               if h not in _rec_set and _live_artefact_state(project / h)[0]]
        _lit_set = set(literal_hits)
        alt_literal = [h for h in alt if h in _lit_set]
        if alt_literal:
            # ANY-OF, and it is the reason " OR " exists. The spec NAMES this
            # path — it is not a set the step happened to land in — so a live
            # one discharges the entry whichever alternative the record
            # happened to resolve. Do NOT invent an absence: today's verdict
            # stands, disclosed. Evidence is the pre-change list so the
            # integrity scan sees what it saw.
            return True, glob_ev, "project_glob", (
                f"step record names {detail}; credited instead to "
                f"{alt_literal[0]}, a literal alternative this spec names"
            ), _bind_detail("credited_unrecorded_alt",
                            recorded=len(rec["produced"]), live=0,
                            credited=alt_literal[0])
        if alt:
            # THE WILDCARD DID NOT BIND. Every live match came from a
            # wildcard alternative and NONE of them is on this step's write
            # record: the pattern proves that SOME file of that shape exists
            # under the project, which is exactly what a file another step
            # wrote also proves. The step's own recorded output set is gone,
            # and that is an absence — reported as one instead of as a note.
            return False, [], "step_attributed", (
                f"wildcard did not bind: this step's write record names "
                f"{len(rec['produced'])} output(s) for this pattern "
                f"({detail}) and none is still an artefact; {alt[0]} matches "
                f"the pattern but is on no write record of this step, so it "
                f"evidences that a file of this shape exists, not that THIS "
                f"step produced one"
            ), _bind_detail("wildcard_unbound",
                            recorded=len(rec["produced"]), live=0,
                            unrecorded_matches=alt[:6],
                            wildcard_alternatives=n_wild)
        return False, [], "step_attributed", (
            f"this step's own write record names {detail}"
        ), _bind_detail("recorded_but_absent",
                        recorded=len(rec["produced"]), live=0)

    # (b) THE STEP'S OWN RECORD SAYS NOTHING WAS PRODUCED FOR THIS SPEC.
    reason = rec.get("not_produced") or "not_produced"
    live = [h for h in glob_hits if _live_artefact_state(project / h)[0]]
    if live:
        # The project-wide glob reaches places the ledger's plain glob does
        # not (the `reports/<subdir>/` sweep fallback, the canonical-analog
        # remap). A disagreement between two resolvers is not evidence of
        # absence, so the green stands and the disagreement is disclosed.
        #
        # NOT TIGHTENED with the wildcard rule above, deliberately. Here the
        # two resolvers disagree about whether ANYTHING was produced, and the
        # documented reason they can disagree — `_glob_first`'s reports/
        # sweep and its canonical-analog remap, neither of which
        # `step_write_ledger._spec_candidates` implements — is a resolver
        # limitation, not an absence. It occurs ZERO times on the three real
        # ledger-bearing runs measured, all of them digital; the remap fires
        # on ANALOG steps and no ledger-bearing analog run exists on this
        # host to measure it against. Refusing it on that evidence would be
        # taking an unmeasured risk for free. Typed as its own code so the
        # decision is a field, not a silence.
        return True, glob_ev, "project_glob", (
            f"resolver disagreement — this step's write record says "
            f"{reason!r}, the project-wide glob matched {live[0]}"
        ), _bind_detail("resolver_disagreement", recorded=0,
                        not_produced_reason=reason, credited=live[0])
    if glob_sat:
        return False, [], "step_attributed", (
            f"not produced ({reason}); the project-wide glob matched "
            f"{glob_hits[:1]}, which is not a produced artefact"
        ), _bind_detail("not_produced", recorded=0,
                        not_produced_reason=reason)
    return (False, [], "step_attributed", f"not produced ({reason})",
            _bind_detail("not_produced", recorded=0,
                         not_produced_reason=reason))


def _disclose_output_binding(result: "StepResult") -> "StepResult":
    """Put the attribution on the TEXT report, for every step that has one.

    BOTH directions are stated, deliberately. Annotating only the degraded
    case would make "step-attributed" the meaning of SILENCE, and a reader
    would be inferring the stronger claim from the absence of a line — which
    is the shape this repo keeps finding under other names. One line per step
    that declares outputs (at most 61 on the shipped flow), stating which
    question the verdict above it answered."""
    b = result.output_binding
    if not b or not b.get("n_specs"):
        return result
    if any(r.startswith("OUTPUT ATTRIBUTION:") for r in result.reasons):
        return result                       # both exits can reach this helper
    n, k = b["n_specs"], b["n_step_attributed"]
    # The typed codes go on the line in BOTH directions. `mixed` used to be a
    # word whose content lived only in prose; a reader (human or grep) now
    # gets the closed vocabulary that produced it.
    codes = [c for c in (b.get("codes") or []) if c != "step_attributed"]
    tail = f" codes={codes}" if codes else ""
    if b["mode"] == "step_attributed":
        src = b.get("source") or "step record"
        where = ("steps/<phase>/<stage>/<id>_<slug>/written.json"
                 if src == "step_folder" else "reports/write_ledger.json")
        # A step-attributed verdict can still carry a residual
        # (`recorded_set_partial`: the record named 5, 4 survive). Printing
        # notes only on the degraded branch would have made that residual
        # visible in the JSON and invisible in the report a person reads.
        notes = "; ".join(b.get("notes") or [])
        result.reasons.append(
            f"OUTPUT ATTRIBUTION: step-attributed ({k}/{n} declared output(s) "
            f"resolved against THIS step's own write record in {where}, "
            f"re-verified live){tail}"
            + (f" [{notes[:400]}]" if notes else ""))
        return result
    head = ("PROJECT-WIDE" if k == 0 else f"MIXED ({k}/{n} step-attributed)")
    notes = "; ".join(b.get("notes") or []) or "no reason recorded"
    result.reasons.append(
        f"OUTPUT ATTRIBUTION: {head} — {n - k} of {n} declared output(s) were "
        f"resolved by the project-wide glob, which answers 'a file matching "
        f"this pattern exists somewhere under the project', NOT 'this step "
        f"produced it'{tail} [{notes[:400]}]")
    return result


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


def _sibling_authoring_incomplete_for_missing(
        project: Path, missing_patterns: List[str]) -> Optional[str]:
    """Loose gate-path peer of `_sibling_self_skip_for_missing` for INCOMPLETE.

    Safe only at a `files_exist` gate whose next sub-gate independently reads
    the artifact. It never applies on the early required-output return.
    """
    seen_dirs: set = set()
    for pat in missing_patterns:
        parent_rel = str(Path(pat).parent)
        if parent_rel in seen_dirs:
            continue
        seen_dirs.add(parent_rel)
        candidates = [project / parent_rel]
        candidates += [project / hit for hit in _glob_first(project, parent_rel)]
        for directory in candidates:
            if not directory.is_dir():
                continue
            for sib in sorted(directory.glob("*.json")):
                try:
                    data = json.loads(sib.read_text())
                except Exception:
                    continue
                if not isinstance(data, dict):
                    continue
                vd = str(data.get("verdict", "")).upper().replace("_", "-")
                if vd != "INCOMPLETE":
                    continue
                unresolved = data.get("unresolved_obligations") or []
                ids = [str(row.get("id", "?")) for row in unresolved
                       if isinstance(row, dict)]
                try:
                    rel = str(sib.relative_to(project))
                except ValueError:
                    rel = sib.name
                return (f"{rel}: applicable formal property authoring remains "
                        f"({', '.join(ids) or 'unnamed obligation'})")
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


# ---------------------------------------------------------------------------
# The DECLARATION side of the disclosed-capability-gap contract
# ---------------------------------------------------------------------------
# 29/d7 tail (bucket `signoff_adj`, deferred item 8). The #675-strict promoter
# below converts a step's MISSING required output into SKIPPED-CONDITION when a
# co-located marker carries a `capability_flag`. Until now it only asked that
# the flag be a NON-EMPTY STRING, so the "disclosure" was self-certifying: ANY
# value promoted, including a flag naming a gap the platform declares CLOSED.
#
# MEASURED on the completed spm x ihp-sg13g2 run
# (~/campaign_pr427/spm/converge_ihp-sg13g2, plugin @ origin/main v1.7.61):
#
#   _declared_sibling_self_skip_for_missing(proj, <step-29 outputs>)
#     -> "phase3/stage3/sim_postlayout/sdf_sim_skipped.json: owns this output
#         ... verdict=SKIPPED-CONDITION [cap:sdf_annotated_gatelevel_sim]"
#
# `cap:sdf_annotated_gatelevel_sim` was RETIRED in v1.7.37 — the runner HAS
# driven a back-annotated sim since v1.3.94, `_PLATFORM_CAPABILITY_GAPS` records
# step 29's gap as closed, and `test_phase3_sdf_skip_disclosure` forbids any
# code path from emitting it. The gate still honoured it and step 29 came out
# SKIPPED-CONDITION instead of MISSING. The producer-side half of that defect
# was fixed where it belongs (phase3_one_shot_runner._SDF_SIM_CAP_GAPS now
# hands out a flag only for an observed missing simulator); what stayed open was
# the GENERIC vector: nothing stopped the NEXT marker — or a hand-edited one —
# from minting `cap:anything` and being believed.
#
# This frozenset is that missing declaration. A marker may defer only under a
# flag NAMED HERE. Registering a flag is a deliberate, reviewed edit to the
# gate; it is not a judgement this file can make from the marker's own text.
#
# NOTE the direction of the test: the guard asserts the claimed flag IS ON this
# list, never that some bad token is absent. A "known-retired flags" denylist
# would pass for every not-yet-invented name, which is exactly the hole.
#
# `test_capability_gap_flag_registry.py` keeps this in sync with the producers
# and explains what its source scan can and cannot see.
# 2026-07-27 REVIEW FOLLOW-UP — the flag list alone narrowed only the
# ENTRANCE. A bare allowlist of NAMES says which claims exist; it says nothing
# about WHAT each claim covers, so all eleven registered flags were accepted
# for ANY output. MEASURED against step 31 (Physical Verification — DRC + LVS
# + ERC), the single most safety-critical gate in the flow: `cap:cdc`,
# `cap:verilator_coverage_toolchain`, `cap:atpg_signoff_coverage` and
# `cap:post_layout_spice_correlation` EACH deferred it to SKIPPED-CONDITION.
# The forgery space went from infinite to eleven; forging a DRC/LVS/ERC
# deferral with a LEGITIMATE token stayed reachable. The docstring below
# already asserted this could not happen ("A hard sign-off (DRC/LVS/ERC/STA)
# has NO disclosed capability gap, so no legitimate runner marker ever defers
# it") — nothing executed that sentence.
#
# So the registry is a MAPPING, flag -> the required-output patterns that flag
# is entitled to defer, and there is a hard-sign-off DENYLIST that no flag may
# cross whatever it is bound to. The two are independent on purpose: the
# binding is the positive statement (this gap explains exactly these absent
# artefacts) and the denylist is the executable form of the sentence above, so
# a future registry edit cannot re-open the hole by accident.
#
# WHERE EACH BINDING COMES FROM — the producer that mints the flag, not a
# guess. `skips_required_output` is emitted by exactly two modules, and each
# emission site pairs one flag with one fixed output set:
#   design_one_shot_runner._POST_DFT_SKIP_OWN / ._TDF_CAP
#   phase3_one_shot_runner.atpg_disclose_not_run / step-29 / step-30 markers
# A flag that no producer ever pairs with `skips_required_output` defers
# NOTHING here — it is registered because a producer emits the literal in some
# OTHER contract (a gate's stdout waiver, a `capability_gap` JSON field), and
# an empty binding states exactly that. Minting a NEW deferral is then the
# deliberate, reviewed edit the whole design is for: add the output.
#
# Patterns are fnmatch globs over the normalized declared output. A glob is
# safe HERE, unlike in `_output_claim_matches`, because it is an extra AND:
# the marker must ALSO exactly own one of this step's own missing canonical
# outputs. The glob can only ever SHRINK what an already-owned claim covers.
_DECLARED_CAPABILITY_GAP_FLAGS: Mapping[str, Tuple[str, ...]] = MappingProxyType({
    # --- phase2 / design_one_shot_runner ---------------------------------
    # No OSS scan-insertion path produced a library-mapped scan netlist, so
    # sign-off stuck-at coverage could not be measured. Step 11's coverage
    # artefacts only — scan insertion itself DID run, so the scan netlist is
    # not covered by this gap.
    "cap:atpg_signoff_coverage": (
        "phase2/stage2/dft/coverage.json",
        "phase2/stage2/dft/atpg_coverage.rpt",
        "reports/phase2/dft/coverage.json",
    ),
    # No scan netlist exists to re-optimise (downstream of the above).
    # `design_one_shot_runner._POST_DFT_SKIP_OWN`.
    "cap:post_dft_scan_optimization": (
        "phase2/stage2/synth/post_dft_netlist.v",
    ),
    # Transition/at-speed ATPG needs a timing-graded fault model the OSS
    # ATPG chain does not provide. `design_one_shot_runner._TDF_CAP` and
    # `phase3_one_shot_runner._ATPG_COVERAGE_REL` (DT1/DT2/DT3).
    "cap:at_speed_timing_graded_atpg": (
        "reports/phase2/dft/transition_coverage.json",
        "reports/phase2/dft/path_delay_coverage.json",
        "reports/phase2/dft/sdd_coverage.json",
    ),
    # The design's own spec binds no reference OUTPUT for the case, so there is
    # nothing to check a produced result against. ORGANIC #786 r5 — the
    # sentence used to read "a CPU-class design has no reference ISA model to
    # check results against", which was wider than what the waiver reaches and
    # narrower than why. It reaches exactly two populations, both CPU-class and
    # both anchored on `sim/results.xml`:
    #   (a) a `functional_vector` L10 case (Phase 1 lifts these out of an input
    #       verification-plan table; they carry no opcode), whose oracle is the
    #       instruction-set model this pass did not author; and
    #   (b) an opcode-derived L10 case whose entry in the design's OWN L3 RECORD
    #       binds no concrete response template AND carries no document-derived
    #       response extraction. `l10_tb_conformance_check` RESOLVES that
    #       pointer in L3 and REFUSES the waiver when the record does bind a
    #       reference output, when the document-derived sibling exists, or when
    #       the entry holds document bytes the record cannot attribute to a
    #       side.
    #
    # ORGANIC #786 r7 — SCOPE OF (b), stated because absence does not establish
    # it: this is a claim about the design's L3 RECORD, NOT about the input
    # document. Whether the document stated a response is NOT established here
    # — the extraction that would record one runs at one of seven
    # opcode-construction sites in `gen_l3_cmd_protocol`, and 0 of 203 corpus
    # entries carry it, so its absence is equally consistent with a document
    # that states the response somewhere the extractor does not look. The gate
    # emits `cpu_oracle_binding_census.document_derived_records` ("k/N") next
    # to every such waiver so a reviewer can see how much input the refusal
    # arms had. An earlier revision of this sentence read "a fact read off the
    # design's document" and was wrong.
    # Carried as a `capability_gap` FIELD on TB-conformance evidence
    # (l10_tb_conformance_check, arith_oracle_tb_gen, bit_level_full_stack_tb_
    # check); no producer ever pairs it with `skips_required_output`.
    "cap:cpu_functional_oracle": (),
    # An analog verification intent has no digital oracle to check against.
    # Same shape as above (l10_tb_conformance_check).
    "cap:analog_verification_intent_oracle": (),
    # The spec declares a feature conditionally, with no declared trigger.
    # Same shape as above (l10_tb_conformance_check).
    "cap:conditional_feature_undeclared": (),
    # No CDC engine is wired for this design's clock-domain topology.
    # `cdc_crossing_check` reports it as its own WAIVED-DEFERRED verdict; it
    # never stands in for another step's absent required output.
    "cap:cdc": (),
    # The coverage toolchain (verilator --coverage) is unavailable.
    # `verilator_coverage_measure` prints it on its own waiver exit.
    "cap:verilator_coverage_toolchain": (),
    # --- phase3 / phase3_one_shot_runner ---------------------------------
    # The execution environment lacks the gate-level simulator executables.
    # A missing TB/model/SDF/netlist or a failed invocation is not eligible.
    "cap:sdf_gatelevel_simulator_toolchain": (
        "phase3/stage3/sim_postlayout/results.log",
        "phase3/stage3/sim_postlayout/pass.flag",
    ),
    # The execution environment genuinely lacks ngspice. Missing models,
    # netlist/SPEF/STA inputs, or a failed run are not eligible. Step 30 only.
    "cap:post_layout_spice_correlation": (
        "phase3/stage3/spice/correlation.json",
        "reports/phase3/spice_correlation.json",
    ),
})


# The executable form of "a hard sign-off has NO disclosed capability gap".
#
# DRC, LVS, ERC and STA sign-off are the artefacts a tape-out is DEFINED by.
# The platform declares no capability gap for any of them — it ships and drives
# the deck for each — so no runner marker can honestly stand in for one, and a
# marker that claims to is either a bug or a forgery. Either way the step keeps
# its real status.
#
# Matched against the BASENAME of the declared / missing output, case-folded,
# never against the whole path: every phase3 path contains "sta" inside
# "stage", and a whole-path test would refuse half the flow.
# chip-AGNOSTIC — artefact KINDS, never a design / PDK / vendor name.
#
# Two lists, because the risk is not symmetric. These names occur in no other
# word, so a SUBSTRING test is both safe and robust to `drcreport.rpt`-style
# run-together naming:
_HARD_SIGNOFF_SUBSTRINGS: Tuple[str, ...] = (
    "drc",          # reports/phase3/drc_signoff.rpt   (step 31)
    "lvs",          # reports/phase3/lvs.rpt           (step 31)
    "netgen",       # the LVS engine's own report name
    "timing",       # post-route / multi-corner STA    (step 23+)
    "slack",
)
# These DO occur inside ordinary words ("commercial" and "percent" both contain
# "erc"; "stage" and "instances" both contain "sta"), so they are matched as
# whole NAME TOKENS only — the basename split on non-alphanumerics:
_HARD_SIGNOFF_TOKENS: Tuple[str, ...] = (
    "erc",          # reports/phase3/erc.rpt           (step 31)
    "sta",          # reports/phase3/sta.rpt           (step 23+)
    "checklist",    # reports/audit/tapeout_checklist.json (step 36)
)
_NAME_TOKEN_RE = re.compile(r"[^a-z0-9]+")


def _is_hard_signoff_output(output: str) -> bool:
    """True when `output` names a DRC / LVS / ERC / STA sign-off artefact —
    the class of evidence no disclosed capability gap may ever stand in for.
    Pure."""
    name = Path(str(output).strip()).name.lower()
    if any(s in name for s in _HARD_SIGNOFF_SUBSTRINGS):
        return True
    tokens = set(_NAME_TOKEN_RE.split(name))
    return any(t in tokens for t in _HARD_SIGNOFF_TOKENS)


def _is_declared_capability_gap(flag: str) -> bool:
    """True when `flag` NAMES a capability gap this module declares open.

    Pure. An unregistered flag — a retired one, a typo, or a forged one — is
    not a disclosure the gate can act on: the step keeps its real status.

    Being NAMED is necessary and no longer sufficient: what the flag is
    entitled to defer is `_capability_flag_may_defer`.
    """
    return flag.strip() in _DECLARED_CAPABILITY_GAP_FLAGS


def _capability_flag_may_defer(flag: str, output: str) -> bool:
    """True when `flag` is registered AND entitled to defer `output`. Pure.

    Three independent refusals, in order:
      1. the flag is not registered at all;
      2. `output` is a hard sign-off artefact — no flag defers one, ever;
      3. `output` is outside the flag's declared binding (a registered flag
         standing in for an artefact its own gap does not explain).
    """
    f = flag.strip()
    allowed = _DECLARED_CAPABILITY_GAP_FLAGS.get(f)
    if allowed is None:
        return False
    if _is_hard_signoff_output(output):
        return False
    o = _norm_out_path(output)
    return any(fnmatch.fnmatchcase(o, _norm_out_path(pat)) for pat in allowed)


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
      (2) a `capability_flag` naming a gap `_DECLARED_CAPABILITY_GAP_FLAGS`
          declares OPEN (capability-AWARE, not capability-blind). A hard
          sign-off (DRC/LVS/ERC/STA) has NO disclosed capability gap, so no
          legitimate runner marker ever defers it; and an unregistered flag —
          retired, mistyped or forged — is a claim the platform does not make,
          so it defers nothing; and
      (2b) that flag must be ENTITLED to defer the output it claims —
          `_capability_flag_may_defer`. Registering a NAME never granted a
          scope, so until 2026-07-27 all eleven registered flags were accepted
          for ANY output and `cap:cdc` measurably deferred step 31's DRC/LVS/
          ERC. The registry now BINDS each flag to the outputs its producer
          actually stands in for, and `_is_hard_signoff_output` refuses a
          sign-off artefact for every flag — which is the sentence in (2)
          finally executing instead of merely being asserted; and
      (3) a `skips_required_output` (str or list) matching one of THIS step's
          missing canonical outputs (EXACT normalized match, see
          `_output_claim_matches`).
    A marker that omits (2), (2b) or (3), or whose `skips_required_output` names
    a DIFFERENT output, is IGNORED → the step stays MISSING. So a step-12 marker
    (owns `post_dft_netlist.v`) can never mask step-9's `netlist.v`, and a stray
    skip-json in reports/phase3/ can never mask a DRC/LVS sign-off. chip-AGNOSTIC;
    the trust model is the same runner-emitted-evidence one the §4.05 blindness /
    evidence-integrity audits already police, and a promotion yields only a
    review-flagged SKIPPED-CONDITION (excluded from executed-PASS), never a clean
    PASS.
    """
    # A step whose missing evidence INCLUDES a hard sign-off artefact is not
    # deferrable at all, whatever any marker owns. Checked over the whole
    # missing set, not just the owned entry: under an ALL-of required_outputs
    # (step 31 = drc_signoff.rpt + lvs.rpt + erc.rpt) a promotion carries the
    # WHOLE step to SKIPPED-CONDITION, so owning one non-sign-off member would
    # otherwise excuse the sign-off members alongside it.
    if any(_is_hard_signoff_output(p) for p in missing_patterns):
        return None

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
                if not _is_declared_capability_gap(
                        str(data.get("capability_flag", ""))):
                    # capability-AWARE: absent, retired, mistyped or forged
                    # flag → the platform makes no such claim → not eligible.
                    continue
                declared = data.get("skips_required_output")
                declared_list = ([declared] if isinstance(declared, str)
                                 else list(declared)
                                 if isinstance(declared, (list, tuple)) else [])
                owned = [do for do in declared_list if isinstance(do, str)
                         and _output_claim_matches(do, missing_patterns)]
                if not owned:
                    continue  # marker does not OWN this step's absent output
                flag_claim = str(data.get("capability_flag", ""))
                if not any(_capability_flag_may_defer(flag_claim, do)
                           for do in owned):
                    # The flag is registered but is not ENTITLED to this
                    # output: a real gap standing in for an artefact it does
                    # not explain. The step keeps its real status.
                    continue
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


# ── ORGANIC #682 — a gate that never ran read exactly like one that passed ────
#
# This program reported a STEP's verdict and never named the GATE that produced
# it. Only the failing branches wrote the command; a gate that ran and passed
# left no trace at all. So `grep -c <gate> flow_compliance_check.log` returned 0
# for a gate that had just written `{"verdict": "FAIL", "rc": 1}`, and 0 for one
# that certainly ran, and 0 for one that was never wired — three different facts,
# one answer.
#
# It cost a false alarm: a round-report concluded from that grep that
# `drv_promotion_corroboration` writes a blocking FAIL the compliance gate never
# reads. Verified false — the gate is wired at step 23, it ran, it wrote its
# verdict, and step 23 was FAIL. The inference only looked sound because the
# record could not separate "never read" from "not recorded".
#
# Same shape as #544 ("the run looked clean because the only gate that would have
# disagreed had not spoken"), which fixed the AGGREGATION and left the
# OBSERVABILITY open. And the same shape as the P0-umbrella registry entry above,
# which was fixed for one registry and not in general.
#
# Every invocation is recorded, whatever it returns. Recording only failures is
# how an absence became indistinguishable from a pass in the first place.
_GATE_LEDGER: List[Dict[str, Any]] = []


def _record_gate_execution(cmd: str, rc: Optional[int], verdict: str,
                           reason_class: Optional[str] = None) -> Dict[str, Any]:
    """One row per gate INVOCATION. `rc=None` means the program could not be
    launched at all — itself a distinct fact from any exit code."""
    if verdict not in ("PASS", "FAIL", "PASS_WITH_WAIVERS"):
        reason_class = _reason_taxonomy.infer_nonverdict_reason(
            verdict=verdict, explicit=reason_class)
    else:
        reason_class = _reason_taxonomy.normalise(reason_class)
    row = {"gate": _gate_name(cmd), "cmd": cmd,
           "rc": rc, "verdict": verdict,
           "reason_class": reason_class}
    _GATE_LEDGER.append(row)
    return row


def _gate_ledger_payload() -> List[Dict[str, Any]]:
    """Deterministic machine-readable view of concurrently appended rows."""
    return sorted((dict(row) for row in _GATE_LEDGER), key=lambda row: (
        str(row.get("gate") or ""), str(row.get("cmd") or ""),
        -1 if row.get("rc") is None else int(row["rc"]),
        str(row.get("verdict") or ""), str(row.get("reason_class") or "")))


def _gate_name(cmd: str) -> str:
    """The program name a reader would grep for — the first token that looks
    like a checker, not the whole command line with its paths and flags."""
    for tok in (cmd or "").split():
        base = tok.rsplit("/", 1)[-1]
        if base.endswith(".py"):
            return base[:-3]
        if base.endswith(("_check", "_audit")):
            return base
    return (cmd or "").split(" ", 1)[0] or "<empty>"


def gate_ledger_lines() -> List[str]:
    """The attribution block, for the log. Emitted even when every gate passed —
    a record that appears only on failure cannot be used to prove a gate ran."""
    if not _GATE_LEDGER:
        return ["GATE EXECUTION LEDGER: no program gate was invoked in this run."]
    out = [f"GATE EXECUTION LEDGER: {len(_GATE_LEDGER)} invocation(s) — "
           f"every program gate this run dispatched, whatever it returned."]
    for row in _GATE_LEDGER:
        rc = "launch-failed" if row["rc"] is None else f"rc={row['rc']}"
        cls = row.get("reason_class") or "-"
        out.append(f"  GATE_RAN {row['gate']:44} {rc:14} {row['verdict']} "
                   f"reason_class={cls}")
    return out


#: How long a gate's process tree may show NO forward progress before it is
#: called wedged. NOT a bound on how long a gate may legitimately run: the
#: structural gates read post-PnR netlists and multi-GB GDS, and a gate that is
#: reading one is working.
_GATE_STALL_GRACE_S = 60


class _GateStalled(Exception):
    """A gate whose whole process tree was idle across the grace."""

    def __init__(self, res):
        super().__init__("gate stalled")
        self.res = res


@dataclass(frozen=True)
class _ProgramCheckOutcome:
    """The private runner result, including the process exit code.

    Iteration deliberately yields the historical ``(passed, output)`` pair so
    the public wrapper and existing tests keep their tuple contract.  The
    private attribute is the lossless channel used by the execution ledger and
    advisory evidence records.
    """

    passed: bool
    output: str
    exit_code: Optional[int]

    def __iter__(self):
        yield self.passed
        yield self.output


class _ProgramCheckResult(tuple):
    """Tuple-compatible public result with lossless execution metadata."""

    def __new__(cls, passed: bool, output: str, exit_code: Optional[int],
                structured_verdict: Optional[str], verdict: str,
                reason_class: Optional[str]):
        return super().__new__(cls, (passed, output, exit_code,
                                     structured_verdict, verdict,
                                     reason_class))

    def __iter__(self):
        yield self[0]
        yield self[1]

    @property
    def exit_code(self) -> Optional[int]:
        return self[2]

    @property
    def structured_verdict(self) -> Optional[str]:
        return self[3]

    @property
    def verdict(self) -> str:
        return self[4]

    @property
    def reason_class(self) -> Optional[str]:
        return self[5]


def _check_program_exit_zero(project: Path, cmd_str: str) -> tuple[bool, str]:
    """#682 attribution wrapper. Records the invocation whatever it returns, then
    delegates. WRAPPING rather than inserting a `_record_gate_execution` call at
    each of the eleven return points: a return added later would otherwise be
    unrecorded, and an unrecorded gate is the exact defect this exists to close.
    The exit shape comes from the snippet the inner function already builds;
    when the command names a JSON report, its typed reason class is consumed
    here. One invocation therefore produces one published classification plus
    the exact process exit and structured verdict required by issue #1980."""
    _inner = __check_program_exit_zero(project, cmd_str)
    ok, out = _inner
    _actual_rc = (_inner.exit_code
                  if isinstance(_inner, _ProgramCheckOutcome) else None)
    report = _command_json_report(project, cmd_str)
    report_cls = _reason_taxonomy.report_reason_class(report)
    report_message = _report_reason_text(report)
    _structured_verdict = _report_verdict(report)
    reason_class: Optional[str] = None
    if out.startswith(_VACUOUS_HINT_PREFIX):
        legacy_message = out.partition("\n")[2]
        rc = 2
        substantive_alternate = _stdout_signals_token(
            legacy_message, _SUBSTANTIVE_STDOUT_TOKEN)
        if substantive_alternate:
            # Some gates retain rc=2 for the missing primary artefact while
            # explicitly proving the equivalent through another route.  That
            # is a substantive PASS, not a non-verdict reason to classify.
            verdict = "PASS"
            out = legacy_message
        else:
            reason_class = _reason_taxonomy.infer_nonverdict_reason(
                verdict="VACUOUS_PASS",
                message=report_message or legacy_message,
                explicit=report_cls)
        if substantive_alternate:
            pass
        elif reason_class in _reason_taxonomy.SKIP_ELIGIBLE:
            verdict = "VACUOUS_PASS"
            # Downstream aggregation treats everything after the prefix as
            # the command identity.  The diagnostic suffix was needed here
            # for classification, not in that established marker payload.
            out = f"{_VACUOUS_HINT_PREFIX}{cmd_str}"
        else:
            verdict = ("BLOCKED" if reason_class
                       == _reason_taxonomy.BLOCKED_BY_UPSTREAM
                       else "INCOMPLETE")
            detail = (report_message or legacy_message
                      or "no classified reason was emitted")
            out = (f"INCOMPLETE: {cmd_str} — reason_class={reason_class}; "
                   f"{detail}")
    elif out.startswith(_WAIVER_HINT_PREFIX):
        verdict, rc = "PASS_WITH_WAIVERS", _WAIVER_EXIT_CODE
    elif out.startswith("program not found:"):
        verdict, rc = "NOT_FOUND", None
        reason_class = _reason_taxonomy.EXECUTION_ERROR
    elif out.startswith(_CRASH_HINT_PREFIX):
        verdict, rc = "CRASHED", None
        reason_class = _reason_taxonomy.EXECUTION_ERROR
    elif out.startswith("program STALLED"):
        verdict, rc = "STALLED", None
        reason_class = _reason_taxonomy.EXECUTION_ERROR
    elif out.startswith("program invocation error:"):
        verdict, rc = "INVOCATION_ERROR", None
        reason_class = _reason_taxonomy.EXECUTION_ERROR
    else:
        verdict, rc = ("PASS", 0) if ok else ("FAIL", 1)
        if verdict == "PASS" and _json_report_declares_nonverdict(report):
            reason_class = _reason_taxonomy.infer_nonverdict_reason(
                verdict="VACUOUS_PASS", message=report_message,
                explicit=report_cls)
            # vibe-ic#901 — the ledger row is the GATE-granular verdict, and a
            # gate that wrote `{"verdict": "NOT_APPLICABLE"}` into the report
            # this very command named did not PASS anything. rc stays 0 (that
            # is what the process returned, and the row states both) while the
            # word matches what the gate said about itself. Derived from the
            # SAME helper `_evaluate_gate` uses, so the ledger row and the step
            # tier cannot disagree about one gate's own report.
            if reason_class in _reason_taxonomy.SKIP_ELIGIBLE:
                verdict = "VACUOUS_PASS"
            else:
                verdict = ("BLOCKED" if reason_class
                           == _reason_taxonomy.BLOCKED_BY_UPSTREAM
                           else "INCOMPLETE")
                detail = (report_message
                          or "the gate declared a non-verdict without a "
                             "classified reason")
                out = (f"INCOMPLETE: {cmd_str} — reason_class={reason_class}; "
                       f"{detail}")
    _ledger_row = _record_gate_execution(cmd_str, rc, verdict, reason_class)
    # Keep the legacy ``rc`` and ``verdict`` fields stable for existing ledger
    # consumers, and add the lossless #1980 facts without flattening #1978's
    # non-verdict classification into a generic skip.
    _exact_rc = _actual_rc if _actual_rc is not None else rc
    _ledger_row["exit_code"] = _exact_rc
    _ledger_row["structured_verdict"] = _structured_verdict
    return _ProgramCheckResult(
        ok, out, _exact_rc, _structured_verdict, verdict,
        _ledger_row.get("reason_class"))


def __check_program_exit_zero(project: Path, cmd_str: str) -> _ProgramCheckOutcome:
    """Run program in project dir (with globs expanded relative to project),
    return (passed, output_snippet).

    Exit-code semantics align with the structural-RTL-gates runner
    (`_run_structural_rtl_gates`):
      * rc == 0  → PASS
      * rc == 2  → NON-VERDICT CANDIDATE. The snippet carries the Wave 93
                   marker plus the callee's evidence to the outer wrapper;
                   #1978 promotes only a typed design/capability/external
                   absence to VACUOUS_PASS. Upstream, execution, and empty-
                   denominator reasons become BLOCKED/INCOMPLETE.
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
        return _ProgramCheckOutcome(
            False, f"program not found: {cmd_str.split()[0]}", None)
    # #525 — per-gate budget from the SHARED resolver (default 900s, env
    # VIBE_IC_GATE_TIMEOUT_S, cap 3600s). The old fixed 300s killed honest
    # slow gates on large SoCs (reset_dependency_check ~6 min on a 7.5MB
    # post-PnR netlist; provenance sha256 over multi-GB GDS) and reported
    # the kill as a plain gate FAIL.
    # PROGRESS, NOT RUNTIME. `gate_budget` used to be "how long may this gate
    # take" — the #525 comment below already recorded what that cost: the old
    # fixed 300 s "killed honest slow gates on large SoCs
    # (reset_dependency_check ~6 min on a 7.5MB post-PnR netlist; provenance
    # sha256 over multi-GB GDS)". Raising it to 900 was the same defect
    # restated, and so would be raising it again. A gate that is reading a
    # multi-GB GDS is WORKING, and no wording of the kill gives its answer back.
    #
    # The number now bounds NO PROGRESS: how long the gate's whole process tree
    # may show no CPU, no I/O and no output before it is called wedged. That can
    # only ever kill LESS than the budget did — both stop a gate idle for N, and
    # only the budget stopped a gate still working at N — so no gate that passes
    # today can start failing.
    #
    # THE VERDICT TIER IS DELIBERATELY UNTOUCHED. A wedged gate still returns
    # False and still FAILs the audit, exactly as a timed-out one did. This
    # changes WHEN the kill happens, not what the flow concludes from it, which
    # is why it does not disturb the VACUOUS_PASS / PASS_WITH_WAIVERS tiers that
    # have a measured regression history in this file (v1.10.14 -> 1.10.16).
    gate_budget = _pl.gate_timeout_s()
    try:
        # `env=_child_env()` carries the scope stack DOWN to the gate program,
        # and is None when there is nothing to carry, which is the inherit-as-
        # before path. Passed explicitly rather than by mutating `os.environ`:
        # this module's `main` is called IN PROCESS by `stageN_compliance`, and a
        # process-global mutation would outlive the call that made it.
        _res = _watchdog.run_host_supervised(argv, cwd=str(project),
                                       env=_child_env(),
                                       stall_grace_s=gate_budget)
        if _res.outcome in ("stalled", "ceiling"):
            raise _GateStalled(_res)
        r = _watchdog.completed_process(argv, _res)
        snippet = output_snippet(r.stdout, r.stderr)
        if r.returncode == 0:
            return _ProgramCheckOutcome(True, snippet, r.returncode)
        if r.returncode == 2:
            # Treat as vacuous pass — surface the program command so
            # reviewers know which gate vacuously passed.
            return _ProgramCheckOutcome(
                True, f"{_VACUOUS_HINT_PREFIX}{cmd_str}\n{snippet}",
                r.returncode)
        if (r.returncode == _WAIVER_EXIT_CODE
                and _stdout_signals_waiver(r.stdout)):
            # #651 — PASS_WITH_WAIVERS: the gate passed its threshold but a
            # slot was credited via a waiver. Promote to WAIVED-DEFERRED (not
            # bare PASS) so the WITH_WAIVERS distinction survives the rc-only
            # gate. Requires the stdout sentinel too, so a stray rc=3 from an
            # unrelated program is NOT silently waived.
            return _ProgramCheckOutcome(
                True, f"{_WAIVER_HINT_PREFIX}{cmd_str}", r.returncode)
        # The gate exited non-zero. Decide HERE, while the UNTRUNCATED output
        # is still in hand, whether that was a verdict or a crash — see
        # `_CRASH_HINT_PREFIX`. Deciding it downstream from `snippet` makes the
        # answer a function of the checkout's path length, which is measurably
        # not a property of the gate.
        #
        # `argv[1]` is the gate program's own file: `_resolve_program_cmd`
        # builds `[sys.executable, <PROGRAMS_DIR>/<gate>.py, ...]`. That path
        # is what separates "this gate died" from "this gate QUOTED a
        # sub-tool's traceback in its report" — see `_process_crashed`.
        if _process_crashed(r.stderr, argv[1]):
            # The exception line goes FIRST so it survives `out[:200]` in
            # `_evaluate_gate`; the snippet goes SECOND so the gate's own
            # output survives it too. The prose sits at the END, where a cut
            # costs nothing: a reader who lost it still has the sentinel.
            return _ProgramCheckOutcome(
                False,
                (f"{_CRASH_HINT_PREFIX}"
                 f"{python_traceback_summary(r.stderr)}\n"
                 f"{snippet}\n"
                 f"— an unhandled exception is NOT a gate verdict "
                 f"(INCONCLUSIVE: the gate died before reaching "
                 f"one): {cmd_str}"),
                r.returncode,
            )
        return _ProgramCheckOutcome(False, snippet, r.returncode)
    except _GateStalled as stalled:
        # #525's reading stands and is now MEASURED rather than inferred: the
        # gate was killed mid-run, so the step is INCONCLUSIVE and still FAILs
        # the audit (an unevaluated gate cannot pass) — but the reason is no
        # longer "it has been N seconds", which a correct gate on a busy host
        # reaches just as easily. It is "this gate's process tree did nothing
        # at all for N seconds", which only a wedged gate reaches.
        return _ProgramCheckOutcome(
            False,
            (f"program STALLED — no CPU, no I/O and no output from "
             f"its process tree for {gate_budget}s, stopped after "
             f"{stalled.res.elapsed_s:.0f}s. It was not slow; it was "
             f"doing nothing. A stall is NOT a verdict about the "
             f"design (INCONCLUSIVE; raise {_pl.GATE_TIMEOUT_ENV} to "
             f"extend the grace): {cmd_str}"),
            None,
        )
    except Exception as exc:
        return _ProgramCheckOutcome(
            False, f"program invocation error: {exc}", None)


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

# ── STRUCTURE-ONLY verdict tier ───────────────────────────────────────────
# The tally line had no way to say the third thing a step can be. It said a
# step executed and passed, or failed, or is missing. A fourth case was being
# reported as the first: the step RAN, it PRODUCED its declared artefact, and
# that artefact's content came from a library default because no bound input
# determined it.
#
# THE RULE, with no tool, step or block name in it:
#
#   A step that produced its declared artefact from a library default, because
#   no bound input determined its content, is neither an executed pass nor a
#   missing step. It is dispositioned in its own tier, it leaves the
#   executed-PASS numerator, it stays in the denominator, and its count is
#   printed on the one line a reader reads.
#
# Not MISSING: the artefact exists and re-running produces the same one.
# Not PASS: every number measured on it is a number about the default.
# Not FAIL: the bounded inputs did not determine the content, and inventing
# content to fill that gap is the failure the whole track exists to prevent —
# a run that is honest about its ceiling must not score below one that is not.
#
# The tier is signalled exactly the way VACUOUS_PASS is: a gate program prints
# a line beginning `STRUCTURE_ONLY:` on stdout. It is read WHETHER OR NOT the
# gate passed — a step can fail for one declared unit and still have produced a
# library-default artefact for another, and both facts are true. When the step
# passes, the tier REPLACES PASS; when it fails for another reason, FAIL stays
# (it is the louder news) and the disclosure is carried as a parenthetical on
# the FAIL count, the same shape `MISSING=n (k blocked-by-upstream…)` already
# uses.
_STRUCTURE_ONLY_HINT_PREFIX = "__STRUCTURE_ONLY_HINT__: "
_STRUCTURE_ONLY_STDOUT_SENTINEL = "STRUCTURE_ONLY:"
# vibe-ic#599 — the roll-up had no vocabulary between PASS and VACUOUS-PASS, so
# two different things arrived wearing the same word:
#
#   * step 14: `yosys_hilomap_required_check` prints `VACUOUS_PASS:` because no
#     `.ys` script existed, and in the same sentence reports that the runner's
#     INLINE `yosys -p` command was extracted and verified conformant. Its own
#     docstring says the verdict word stays vacuous ON PURPOSE and `reason_class`
#     carries how much was verified — a deliberate decision, so the gate is not
#     what is wrong. The roll-up read the token and never the reason.
#
#   * D1: `phase1_expert_parse_track` returns VACUOUS_PASS when no deterministic
#     rule applied AND the AI sub-track never answered. The input WAS applicable;
#     that is INCOMPLETE. "A vacuous step is one nobody needs to come back to."
#
# Both are disclosed by a PRINTED SENTINEL rather than by matching a gate's prose
# — matching prose is how a gate that says "I verified the inline command" got
# read as "I examined nothing" to begin with.
#
# AGGREGATION IS UNCHANGED: both tiers count exactly as VACUOUS_PASS did, so no
# design turns red on this alone. What changes is that the per-step listing can
# tell "audited by another route" and "not audited, and someone must return"
# apart from "nothing applied".
_SUBSTANTIVE_HINT_PREFIX = "__SUBSTANTIVE_HINT__: "
_INCOMPLETE_HINT_PREFIX = "__INCOMPLETE_HINT__: "

#: What a gate PRINTS to raise each. Line-start, leading whitespace allowed —
#: the same shape as the `VACUOUS_PASS:` disclosure that already exists.
_SUBSTANTIVE_STDOUT_TOKEN = "SUBSTANTIVE_PASS"
_INCOMPLETE_STDOUT_TOKEN = "INCOMPLETE"

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

# ══════════════════════════════════════════════════════════════════════
# CRASH — "the gate blew up" is not "the gate found a defect"
# ══════════════════════════════════════════════════════════════════════
# An unhandled Python exception exits non-zero, so on the exit code alone
# `_check_program_exit_zero` cannot tell a crashing gate from one that
# reached a FAIL verdict. Consumers that need the distinction — the
# dimension-2 falsifiability matrix is the one that DEPENDS on it, since a
# crash must never be counted as proof that a gate can fail — used to
# recover it by looking for a traceback marker in the evidence snippet.
#
# That snippet is a fixed-width tail (`_OUTPUT_SNIPPET_CHARS` of each
# stream), and a traceback's frame lines and its exception message both
# carry ABSOLUTE paths, so how much of the traceback survives the cut is a
# function of how deep the checkout lives. MEASURED on this tree, one
# crashing gate, one project, one variable:
#
#     project path 107 chars -> classified CRASH   (refused, correctly)
#     project path 108 chars -> classified FAIL    (a false certificate)
#
# The crash was graded a demonstration of falsifiability at 108 characters
# and refused at 107. The plugin's own checkout paths are routinely longer
# than that, so the failure mode was the default, not the corner case.
#
# The fix is not a bigger window — that only moves the threshold. The fact
# is available, exactly and for free, at the moment the subprocess returns:
# decide it HERE against the UNTRUNCATED streams and hand the answer down
# as an explicit sentinel that no truncation can remove, because it is the
# first thing in the string.
#
# And it is decided on a FACT, not on the shape of the prose — the traceback
# must contain a frame in the gate program's OWN file (`_process_crashed`).
# Deciding it on prose shape reproduces the same class of defect one level
# down: the first version of this mechanism required the exception line to be
# the last line of the stream, and an ordinary multi-line exception message,
# or one atexit line, put it back on the path-length lottery. Both were
# MEASURED at 80 and 400 character project paths (CRASH / FAIL) before the
# frame anchor replaced the prose rule.
_CRASH_HINT_PREFIX = "__CRASH_HINT__: "

#: Per-stream width of the evidence snippet's TAIL. Named so the one number is
#: quotable and greppable instead of appearing as a bare 300 at the cut site.
#: (`test_matrix_d6_skip_discipline::_consumer_snippet` no longer keeps a copy —
#: it calls `output_snippet` — so the width and the SHAPE move together.)
_OUTPUT_SNIPPET_CHARS = 300

#: Width of the STDOUT HEAD the snippet additionally keeps, in characters.
#:
#: WHY A HEAD EXISTS AT ALL. A gate states its verdict FIRST — `verdict: FAIL`,
#: then the findings, then the offending paths. A pure tail cut therefore
#: deletes the headline and keeps the least specific part of the report, and
#: WHICH part it deletes is a function of how long the absolute paths in that
#: report are — i.e. of where the checkout lives, which is not a property of
#: the gate. MEASURED on `_VERDICT_HELPER_SRC`, whose stdout is
#: `155 + 2 * len(project)` characters, one variable:
#:
#:     len(project) = 72 -> stdout 299 -> `verdict: FAIL` SURVIVES the cut
#:     len(project) = 73 -> stdout 301 -> `verdict: FAIL` is GONE
#:
#: One character of `$TMPDIR` decided whether a legitimate FAIL still carried
#: its finding. `test_a_real_verdict_is_not_mistaken_for_a_crash` bounds its
#: shallow fixture to stay clear of that cliff; the bound is a workaround for
#: the window, and this is the window. The head removes the lottery: the first
#: line of a report is kept unconditionally, whatever follows it.
#:
#: WHY STDOUT ONLY, and this asymmetry is deliberate and measured. stderr is
#: the channel a CRASH lands on, and a crash's evidence is in its TAIL: the
#: exception type and message are the last lines, while its head is the
#: constant `Traceback (most recent call last):` banner. Keeping a stderr head
#: would put that banner into every deep-traceback snippet and so hand the
#: dimension-2 PROSE fallback a crash tell for free — which would silently
#: retire `test_crash_is_flagged_as_a_crash_at_any_checkout_depth`'s closing
#: measurement, the one that proves `_CRASH_HINT_PREFIX` rather than a lucky
#: truncation is what carries the crash on a deep checkout. The authoritative
#: crash channel is that sentinel, decided on the UNTRUNCATED streams; stderr's
#: window is left exactly as it was.
_OUTPUT_SNIPPET_HEAD_CHARS = 300

#: Emitted at column 0 between the kept head and the kept tail, naming how much
#: was dropped, so a reader is never shown a spliced report that looks
#: contiguous. Column 0 is load-bearing in the opposite direction too: it is
#: content, so `_bare_traceback_tail` — which believes a bare exception line
#: only when the text is NOTHING BUT that tail — keeps refusing a spliced
#: stream, exactly as it refuses any stream carrying a real report.
_OUTPUT_SNIPPET_ELISION = "[... {n} character(s) of stdout elided ...]"

_TRACEBACK_HEADER = "Traceback (most recent call last)"

#: A Python traceback FRAME line, whole.
#:
#: Anchored with ``, line <n>, in <name>`` because CPython always emits the
#: function name (``<module>`` at top level); that keeps it from matching an
#: EDA tool's ``File "top.v", line 12`` diagnostics.
_TRACEBACK_FRAME_RE = re.compile(
    r'^\s*File "[^"\n]+", line \d+, in \S', re.MULTILINE)

#: The SAME frame line after a cut landed INSIDE its path. The frame line
#: begins with an ABSOLUTE path, so on a deep checkout a fixed-offset cut
#: takes the ``File "`` prefix with it and leaves only the tail. Ending the
#: pattern at the line end keeps it specific: CPython emits nothing after the
#: function name, so a tool diagnostic reading ``… "top.v", line 12, in
#: module top`` carries trailing text and is not matched.
_TRACEBACK_FRAME_TRUNCATED_RE = re.compile(
    r'", line \d+, in (?:<[A-Za-z_]\w*>|[A-Za-z_]\w*)[ \t]*$', re.MULTILINE)

#: CPython 3.11+ fine-grained error location, e.g. ``    ~~~~~^^^^^``.
#: Emitted immediately above the exception line — and NOT emitted at all by
#: CPython 3.10, which is why it can only ever corroborate, never decide.
_TRACEBACK_CARET_RE = re.compile(r"^[ \t]*[~^][~^ \t]*$", re.MULTILINE)

#: The source line CPython echoes under each frame, indented 4 spaces. On
#: 3.10 — where there is no caret row — this is the only thing left between
#: the frame line and the exception line, so it is the 3.10 counterpart of
#: the caret corroboration.
#:
#: 2026-07-28, adversarial finding (HIGH): used on its own as corroboration
#: this pattern is a FALSE ALARM generator, because "an indented line" is not
#: a traceback-specific shape. MEASURED — a gate that exits 1 having printed
#: an indented finding list on stdout and a column-0 ``ConstraintError: …``
#: summary on stderr was graded FAIL on origin/main and CRASH once this
#: pattern corroborated a bare tail, at EVERY checkout depth: a working,
#: genuinely falsifiable gate reported as having blown up. It is therefore
#: admitted only inside :func:`_bare_traceback_tail`, which additionally
#: requires that the text carry NOTHING BUT the tail — no verdict line, no
#: report content, nothing at column 0 but the exception itself.
_TRACEBACK_SOURCE_ECHO_RE = re.compile(r"[ \t]{4,}\S")

#: The terminal ``SomeError: message`` line of a traceback, at line start.
#: Column 0 is load-bearing: a gate that legitimately REPORTS
#: ``  ValueError: corner name 'ss' is not in the PVT matrix`` as its finding
#: indents it, and must stay a FAIL.
_TRACEBACK_TAIL_RE = re.compile(
    r"^(?:[A-Za-z_][\w.]*\.)?[A-Z]\w*(?:Error|Exception|Interrupt|Exit)"
    r"\s*(?::|$)", re.MULTILINE)


def output_snippet(stdout: str, stderr: str) -> str:
    """The evidence snippet `_check_program_exit_zero` hands to its callers.

    Extracted from the call site so the width is one named constant rather
    than a literal repeated wherever someone needs to reason about what the
    consumer kept: the last :data:`_OUTPUT_SNIPPET_CHARS` characters of each
    stream, GROWN BACKWARD to the start of the line the cut landed in.

    WHY THE GROWTH. A fixed character offset cuts mid-token, and the first
    thing a reader sees is then a fragment of the gate's own verdict. Measured
    on `_pytest_verdict_helper`, whose finding is `verdict: FAIL`::

        AIL
          [ERROR] corner set incomplete under /tmp/.../p
          ValueError: corner name 'ss' is not in the PVT matrix

    The finding survived the cut and was unreadable anyway, and
    `test_a_real_verdict_is_not_mistaken_for_a_crash` refuses exactly that.
    This module already knew the hazard from the other side —
    `_TRACEBACK_FRAME_TRUNCATED_RE` exists because "on a deep checkout a
    fixed-offset cut takes the ``File "`` prefix with it and leaves only the
    tail" — and mended the DETECTOR each time rather than the cut.

    IT GROWS, NEVER SHRINKS, and that is the load-bearing half. Dropping the
    partial first line would have been the shorter fix and it is wrong: a
    truncated traceback FRAME line is exactly such a partial line, and deleting
    it would take a crash's only evidence with it — `looks_like_python_traceback`
    would start answering False where it answers True today. A superset can
    only help every consumer; a subset silently removes evidence.

    Bounded: the grown line may not itself exceed the budget, so a single
    enormous line falls back to the plain tail and the width stays bounded by
    ``2 * _OUTPUT_SNIPPET_CHARS`` per stream.
    """
    return (_head_and_tail(stdout or "") + "\n"
            + _grown_tail(stderr or "", _OUTPUT_SNIPPET_CHARS)).strip()


def _grown_tail(stream: str, n: int) -> str:
    """The last *n* characters of *stream*, grown backward to a line start.

    Main's cut, unchanged and now shared by both streams. See
    :func:`output_snippet` for why it grows and never shrinks.
    """
    text = stream or ""
    if len(text) <= n:
        return text
    cut = len(text) - n
    if text[cut - 1] == "\n":              # the cut already sits on a boundary
        return text[cut:]
    start = text.rfind("\n", 0, cut) + 1
    if cut - start > n:                    # that one line is wider than the
        return text[cut:]                  # budget; keep the old behaviour
    return text[start:]


def _head_and_tail(stream: str) -> str:
    """*stream* reduced to its head and its (line-grown) tail, gap named.

    Returned verbatim when both windows would cover it, so the elision marker
    can never appear in a snippet that elided nothing. The tail half is
    :func:`_grown_tail`, so stdout keeps the grow-backward property main added
    as well as the head this adds — the two repairs compose rather than
    replace each other.
    """
    head, tail = _OUTPUT_SNIPPET_HEAD_CHARS, _OUTPUT_SNIPPET_CHARS
    if len(stream) <= head + tail:
        return stream
    kept_tail = _grown_tail(stream, tail)
    dropped = len(stream) - head - len(kept_tail)
    if dropped <= 0:                       # growth closed the gap entirely
        return stream
    return (stream[:head].rstrip("\n") + "\n"
            + _OUTPUT_SNIPPET_ELISION.format(n=dropped) + "\n"
            + kept_tail.lstrip("\n"))


def looks_like_python_traceback(text: str) -> bool:
    """True when *text* carries a Python traceback, header present or not.

    THE SHARED DEFINITION. Consumers that need the crash/verdict distinction
    import this instead of re-deriving it, so the two cannot drift apart.

    Every branch is required to hold on a TRUNCATED traceback, because a
    snippet is the only form some callers ever see. The header alone is not
    enough: it is the first thing a tail cut removes.
    """
    if not text:
        return False
    if _TRACEBACK_HEADER in text:
        return True
    if _TRACEBACK_FRAME_RE.search(text):
        return True
    if _TRACEBACK_FRAME_TRUNCATED_RE.search(text):
        return True
    # A bare exception tail decides nothing on its own — a gate may print
    # `ValueError: ...` at column 0 as its finding. It counts only when the
    # line immediately above it is traceback-shaped: a frame line or a 3.11+
    # caret row.
    for m in _TRACEBACK_TAIL_RE.finditer(text):
        before = text[:m.start()]
        if re.search(r'^\s*File "', before, re.MULTILINE):
            return True
        prior = [ln for ln in before.splitlines() if ln.strip()]
        if not prior:
            continue
        if _TRACEBACK_CARET_RE.match(prior[-1]):
            return True
    # CPython 3.10 emits no caret rows, so a cut that lands below the last
    # frame leaves only `    <source echo>` + `SomeError: msg`. That pair IS a
    # crash, and it is what `_OUTPUT_SNIPPET_CHARS` produces from a deep
    # traceback on 3.10 — but "an indented line above an exception line" also
    # describes an ordinary gate report, so it is accepted ONLY when the text
    # is nothing else. See :func:`_bare_traceback_tail`.
    return _bare_traceback_tail(text)


def _bare_traceback_tail(text: str) -> bool:
    """True when *text* is a traceback tail AND NOTHING ELSE.

    The shape: one or more indented lines (CPython's echoed source lines, and
    on 3.11+ its caret rows), then a column-0 ``SomeError: message`` line, and
    no other content anywhere. That is what a fixed-width tail cut leaves of a
    3.10 traceback once the last frame line is gone, and it is the only form
    in which a bare exception line may be believed without a frame or a caret
    row to corroborate it.

    Requiring the text to be nothing else is what keeps this from firing on a
    real verdict. A gate that reached a verdict SAYS SO — `verdict: FAIL`, a
    `[ERROR]` line, a count — and every one of those sits at column 0 and is
    not an exception line, so the loop below refuses the whole text.
    """
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    if len(lines) < 2:
        return False
    if not _TRACEBACK_TAIL_RE.match(lines[-1]):
        return False
    for ln in lines[:-1]:
        if not (_TRACEBACK_SOURCE_ECHO_RE.match(ln)
                or _TRACEBACK_CARET_RE.match(ln)):
            return False
    return True


def _process_crashed(stderr: str, program_path: str) -> bool:
    """True when the gate process DIED of an unhandled Python exception.

    This is the AUTHORITATIVE answer — it is what the sentinel asserts — so it
    is decided on one fact rather than on the shape of the prose:

        does the traceback in *stderr* contain a frame in the gate program's
        OWN file, and does an exception line follow that frame?

    `_resolve_program_cmd` runs the gate as ``python3 <program_path> …``, so
    CPython's outermost frame is always that file when the process dies of an
    unhandled exception — including the frameless ``SyntaxError`` form, whose
    ``File "<program_path>", line N`` line names it too. A gate that instead
    QUOTES a sub-tool's traceback inside its own report names the SUB-TOOL's
    files, never its own, so it is not mistaken for a corpse. Two live
    examples of that shape in this tree: `waveform_table_conformance_check`
    (``print("WTC_COMPILE_FAIL:\\n" + r.stderr)``) and
    `pdk_yosys_flatten_for_quartus`.

    Only *stderr* is read: CPython writes tracebacks there and nowhere else,
    so a traceback on stdout was PUT there by the gate and is by construction
    a quotation.

    2026-07-28, adversarial findings (FATAL x2) against the first version of
    this function, which required the exception line to TERMINATE the stream.
    Both were reproduced end to end and both are closed by the rule above:

      * a multi-line exception message (``raise ValueError("…\\n  detail")``)
        leaves the message's continuation line last, so no sentinel was
        emitted and the classification fell back to the path-length lottery
        this whole mechanism exists to remove — MEASURED: still CRASH at an
        80-character project path and FAIL at 400;
      * one atexit / logging-shutdown / resource-tracker line printed after
        the traceback did the same.

    Neither is exotic; both are ordinary Python. The rule below cares only
    that the frame is there and that an exception line follows it, so what
    trails the traceback is irrelevant.

    RESIDUAL, stated rather than assumed away: a crash whose stderr does not
    name the gate program's file — a gate that sets ``sys.tracebacklimit`` low
    enough to drop its own outermost frame — is not disclosed here. It is not
    silently accepted either: the snippet still carries the traceback, and the
    consumer-side heuristic in :func:`looks_like_python_traceback` still reads
    it exactly as it did before this mechanism existed.
    """
    text = stderr or ""
    if not text.strip():
        return False
    frame_re = re.compile(
        r'^\s*File "' + re.escape(str(program_path)) + r'", line \d+',
        re.MULTILINE)
    last = None
    for m in frame_re.finditer(text):
        last = m
    if last is None:
        return False
    return bool(_TRACEBACK_TAIL_RE.search(text, last.end()))


def python_traceback_summary(stderr: str) -> str:
    """``ExceptionType: message`` for the crash in *stderr*.

    Placed FIRST in the hint so the exception type survives every downstream
    cut — including ``out[:200]`` in `_evaluate_gate` — which is the whole
    point of carrying an explicit signal instead of re-reading prose.

    The LAST column-0 exception line is the one reported: on a chained
    traceback (``During handling of the above exception…``) that is the
    exception the process actually died of.
    """
    matches = list(_TRACEBACK_TAIL_RE.finditer(stderr or ""))
    if not matches:
        return "unhandled exception"
    m = matches[-1]
    return (stderr or "")[m.start():].splitlines()[0].strip()[:160]


# vibe-ic#306 — the ADVISORY slot. Until this existed, every gate key in the
# flow definition BLOCKED once it ran: `optional_program_exit_zero` is
# conditional-on-inputs, not advisory, and fails its step on a non-zero exit.
# That left gates which DECLARE themselves advisory with no way to be wired at
# all — wiring one promoted it to blocking, contradicting its own declaration
# (#306's complaint in reverse: not "claims to block but cannot", but "claims
# not to block and does").
#
# Issue #1980 separates policy from refusal. The program runs and its exact
# rc/structured verdict are recorded. A structured warning stays nonblocking;
# a live FAIL (or an unclassified non-zero exit) blocks unless the step has an
# approved scoped waiver. Producers/classifiers do not belong in this slot.
#
# The finding must stay VISIBLE. A gate that runs and reports nothing is worse
# than one that never ran, because the run then looks audited. The hint is
# excluded from `non_hint_reasons` so it cannot disturb the VACUOUS / SKIP /
# WAIVED tier promotions, and re-appended after the status is resolved so it
# appears on the step line and in the JSON report whatever the tier.
_ADVISORY_HINT_PREFIX = "__ADVISORY_HINT__: "

# Issue #1980 — typed advisory execution record transported through the same
# recursive gate-reason channel as the older tier hints.  JSON keeps field
# boundaries intact; check_step removes the marker from prose and publishes it
# in StepResult.advisory_gate_records.
_ADVISORY_RECORD_HINT_PREFIX = "__ADVISORY_RECORD__: "

# vibe-ic#901 - THE DENOMINATOR OF "EVERY SUB-GATE".
#
# The VACUOUS_PASS tier says "the step ran and every executed sub-gate was
# vacuously satisfied", and it was decided by `vacuous_hints and not
# non_hint_reasons`. That is not the same statement: a sub-gate that PASSES
# SUBSTANTIVELY appends NOTHING, so silence and vacuity are indistinguishable
# to it and ONE vacuous clause beside nine substantive ones reads as "every".
#
# MEASURED on a published 63-step run root: wiring `_json_report_signals_vacuous`
# into the rc-0 path WITHOUT a denominator turned step 2 (Lint) from PASS into
# VACUOUS_PASS on the strength of 1 vacuous clause out of 10 that ran. That
# mis-fire is what withdrew the first #901 fix (v1.10.14 -> v1.10.18).
#
# So every gate clause that DISPATCHES A PROGRAM now says so. This marker is
# the denominator; the vacuity markers are the numerator. Held out of
# `non_hint_reasons` exactly like every other marker, so it can never itself
# become a reason a step failed.
_RAN_HINT_PREFIX = "__RAN_HINT__: "

# vibe-ic#901 - vacuity disclosed through the gate's OWN --json report, kept
# in a SEPARATE bucket from `_VACUOUS_HINT_PREFIX` on purpose.
#
# The legacy bucket (rc=2 sentinel, or `VACUOUS_PASS` at line-start in stdout)
# keeps its existing tier power byte-for-byte: a repo that pinned "an analog
# step that closed in simulation with no bench measurement must NOT be a bare
# PASS" must keep that pin. Making the count govern the LEGACY bucket breaks
# exactly those pins - MEASURED: 6 shipped test failures, three of them steps
# leaving a disclosure tier and rejoining the executed-PASS numerator.
#
# This bucket is therefore strictly ONE-DIRECTIONAL. It can only ever turn a
# step that would have been a BARE PASS into VACUOUS_PASS, and only when the
# count says every clause that dispatched a program examined nothing. It can
# never take a step OUT of a tier origin/main gave it.
_JSON_VACUOUS_HINT_PREFIX = "__JSON_VACUOUS_HINT__: "

# vibe-ic W4 - AN UNMET OPTIONAL CONDITION IS A NON-VERDICT, AND IT MUST BUY IT.
#
# `optional_program_exit_zero` runs its program only when at least one
# `condition_files_exist` glob matches. When none match, this file returned
# `True, reasons` — no marker, no reason, no record — and the clause became
# indistinguishable from one that ran and found nothing. The comment above the
# OPTIONAL branch stated the intent honestly ("no inputs -> N/A -> pass") and
# the intent is the defect: an absent input means the gate CONCLUDED NOTHING,
# and the whole of #539/#584/#1025 is the same sentence one layer up — "I could
# not look" must not reach a reader as "I looked and it was clean".
#
# THE OPPOSITE IDIOM, FOR CONTRAST. OpenROAD-flow-scripts' `util/checkMetadata.py`
# reads a rule set and exits 1 on `len(rules) == 0` ("No rules"), and exits 1
# again for a rule whose metric is absent from `metadata.json`
# ("[ERROR] Value not found for {field}"). Absent input is its FAILURE case. It
# is why a stage skipped with `SKIP_DETAILED_ROUTE=1` — which still produces a
# GDS and still lets `make finish` succeed — is caught: the missing
# `detailedroute__route__drc_errors` fails `make metadata-check`. This repo's
# default was the mirror image of that, and the same skipped stage would pass.
#
# WHAT REPLACES IT. An unmet condition now FAILS unless the clause DECLARES,
# at its own wiring site in the flow YAML, why an absent input is a genuine
# not-applicable:
#
#     optional_program_exit_zero:
#       command: "..."
#       condition_files_exist: ["..."]
#       absent_condition_reason: "<why nothing to check is legitimate here>"
#
# DECLARED AT THE WIRING SITE AND NOT IN A REGISTRY, for the reason
# `tools/ci/_gate_dispatch.sh` writes out at length for `uncheckable_until`: a
# separate list keyed by step id and program name desynchronises silently — a
# renamed program loses its entry, a deleted clause leaves a rotting one.
# Deleting the clause deletes its exemption with it.
#
# NOT THE SAME QUESTION AS `flow_condition_reachability_check`. That program
# asks whether a condition can be false EXACTLY WHEN the defect it guards
# occurs (the self-disabling shape). This asks what the RUN learned when the
# condition was in fact false, and demands that the answer be written down and
# visible in the record. A condition can be perfectly reachable and still leave
# a silent hole in every run where it does not fire.
#
# VISIBLE, NOT TIER-CHANGING. A declared not-applicable is held out of
# `non_hint_reasons` and re-appended after the tier resolves, exactly like
# `_ADVISORY_HINT_PREFIX`. It cannot promote or demote a step; it makes the
# non-verdict readable. Whether a step every one of whose clauses was skipped
# should leave the PASS tier is a separate decision with a corpus sweep in
# front of it, and this change deliberately does not take it.
_NOT_APPLICABLE_HINT_PREFIX = "__NA_HINT__: "

#: An `absent_condition_reason` shorter than this is refused. A one-word
#: "N/A" / "optional" is a declaration nobody can check, which is the hole
#: with a label on it rather than the hole closed. The number is a floor on
#: EFFORT, not a claim that length is truth; the shortest reason shipped in
#: `flow/phase1_phase2_phase3.yaml` is well above it.
_MIN_ABSENT_CONDITION_REASON = 40


def _stdout_signals_waiver(snippet: str) -> bool:
    """Return True iff the program's combined stdout/stderr snippet contains
    a `PASS_WITH_WAIVERS` token at line-start (leading whitespace allowed)."""
    if not snippet:
        return False
    for line in snippet.splitlines():
        if line.lstrip().startswith(_WAIVER_STDOUT_SENTINEL):
            return True
    return False


def _stdout_signals_token(snippet: str, token: str) -> bool:
    """True iff `token` starts a line of the snippet (leading space allowed).

    The generic form of `_stdout_signals_vacuous`, which is now one caller of
    it. #599 adds two more disclosures and three copies of the same loop would
    be three places for them to drift apart.
    """
    if not snippet:
        return False
    return any(line.lstrip().startswith(token) for line in snippet.splitlines())


#: vibe-ic#901 — verdicts a gate writes to its OWN --json report that mean
#: "I examined nothing". Read from the FILE, not from stdout: #887 established
#: that a disclosure a project-path length can delete is not a disclosure, and
#: stdout is exactly that channel (the consumer sees only the last 300 chars).
_VACUOUS_JSON_VERDICTS = {"NOT_APPLICABLE", "SKIPPED", "SKIP", "VACUOUS",
                          "VACUOUS_PASS", "NO_BUILD", "NOT_RUN"}


def _command_json_report(project: Path, cmd: str) -> Optional[Dict[str, Any]]:
    """Read the JSON report path named by a gate command, when available."""
    m = re.search(r"--json[= ]+(\S+)", cmd or "")
    if not m:
        return None
    p = Path(m.group(1).strip("'\""))
    if not p.is_absolute():
        p = project / p
    try:
        if not (p.is_file() and p.stat().st_size > 0):
            return None
        data = json.loads(p.read_text(errors="replace"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _report_verdict(report: Any) -> Optional[str]:
    """Return a report's top-level verdict without retiering it."""
    if not isinstance(report, dict):
        return None
    for key in ("verdict", "status"):
        v = report.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip().upper()
    return None


def _json_report_verdict(project: Path, cmd: str) -> Optional[str]:
    """Compatibility wrapper for callers that name the command."""
    return _report_verdict(_command_json_report(project, cmd))


def _report_reason_text(report: Any) -> str:
    """The report's own human explanation, used only after typed fields."""
    if not isinstance(report, dict):
        return ""
    for key in ("reason", "explanation", "message", "skipped_reason"):
        value = report.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    summary = report.get("summary")
    if isinstance(summary, dict):
        for key in ("reason", "explanation", "message", "skipped_reason"):
            value = summary.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _json_report_declares_nonverdict(report: Any) -> bool:
    if not isinstance(report, dict):
        return False
    for key in ("verdict", "status"):
        value = report.get(key)
        if (isinstance(value, str)
                and value.strip().upper() in _VACUOUS_JSON_VERDICTS):
            return True
    return False


def _json_report_signals_vacuous(project: Path, cmd: str) -> bool:
    """True iff the report declares a skip-eligible non-verdict.

    Only a typed, skip-eligible reason is wired into the N/A tier (#1978).

    Wiring this into the VACUOUS_PASS branch (v1.10.14) caused a MEASURED
    regression: it turned a genuinely converged cell red. Controlled proof —
    same run directory, byte-identical artefacts, only the audit binary
    changed:

        1.10.11  PASS=36 FAIL=0            -> PASS_WITH_WAIVERS
        1.10.16  PASS=25 FAIL=0 VOIDED=8   -> FAIL

    Root cause: the tier branch is `passed and vacuous_hints and not
    non_hint_reasons`, and its own docstring says the intent is "EVERY executed
    sub-gate was vacuously satisfied". `not non_hint_reasons` only approximates
    that, because a gate that passes SUBSTANTIVELY says nothing at all. Reading
    gates' JSON made far more gates emit a vacuity hint, so a step with one
    legitimately-inapplicable gate (`drv_promotion_corroboration_check`: "no
    route promotion this run") and several siblings that measured real design
    content flipped to VACUOUS_PASS — cascading into 8
    PASS_VOIDED_BY_DEPENDENCY and an overall FAIL with `failed_gate_count: 0`.

    A FAIL that enumerates nothing as failed is the same defect class this
    campaign exists to remove, so the hook is withdrawn rather than left in
    while a better fix is designed.

    Closing #901 properly needs the tier decision to compare vacuous hints
    against the NUMBER OF GATE CLAUSES THAT RAN, so "every sub-gate" is
    counted rather than inferred from silence. Until then the original #901
    hole (a gate declaring NOT_APPLICABLE in JSON the consumer never opened)
    remains open and is the lesser evil.

    vibe-ic#901. Six gates exited 0 on an empty project without the consumer
    seeing a disclosure — and the two sharpest were SELF-AWARE, printing
    `{"verdict": "NOT_APPLICABLE", "reason": "... (step did not run)"}` into a
    report the consumer never opened. `vacuous_testbench_check` was one of
    them, which is the whole campaign in one line: the gate against vacuous
    passes was itself consumed as a substantive pass.

    The clause already knows the path — it is the `--json <path>` in the
    command string it just ran — so this reads a channel that already exists
    rather than asking gates to print something new. Doing it here also covers
    gates written LATER, which patching six emitters would not.
    """
    report = _command_json_report(project, cmd)
    if not _json_report_declares_nonverdict(report):
        return False
    reason_class = _reason_taxonomy.infer_nonverdict_reason(
        verdict="VACUOUS_PASS", message=_report_reason_text(report),
        explicit=_reason_taxonomy.report_reason_class(report))
    return reason_class in _reason_taxonomy.SKIP_ELIGIBLE


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


def _stdout_signals_structure_only(snippet: str) -> bool:
    """True iff the gate disclosed that an artefact it certifies carries no
    design-bound content. Same line-start shape as the vacuous sentinel, and
    read on the FAILING path too — the disclosure is about what was produced,
    not about whether the gate was satisfied."""
    if not snippet:
        return False
    for line in snippet.splitlines():
        if line.lstrip().startswith(_STRUCTURE_ONLY_STDOUT_SENTINEL):
            return True
    return False


def _structure_only_note(snippet: str) -> str:
    """The disclosure line itself, so the per-step listing can print WHY."""
    for line in (snippet or "").splitlines():
        s = line.lstrip()
        if s.startswith(_STRUCTURE_ONLY_STDOUT_SENTINEL):
            return s[len(_STRUCTURE_ONLY_STDOUT_SENTINEL):].strip()
    return ""


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
        _argv = [sys.executable, str(hilomap_prog), "--ys-file", str(ys_path)]
        _res = _watchdog.run_host_supervised(_argv, stall_grace_s=_GATE_STALL_GRACE_S)
        if _res.outcome in ("stalled", "ceiling"):
            return False, [
                f"FAIL: yosys_hilomap_required_check STALLED on {ys_rel} — no "
                f"CPU, no I/O and no output for {_GATE_STALL_GRACE_S}s. It was "
                f"not slow; it was doing nothing. The techmap→hilomap→"
                f"write_verilog ordering is unverified, so PnR is unsafe. "
                f"Re-run the check manually."
            ]
        r1 = _watchdog.completed_process(_argv, _res)
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
        _argv2 = [sys.executable, str(tmpl_prog), "--ys-file", str(ys_path)]
        _res2 = _watchdog.run_host_supervised(_argv2, stall_grace_s=_GATE_STALL_GRACE_S)
        if _res2.outcome in ("stalled", "ceiling"):
            reasons.append(
                f"FAIL: yosys_script_template_check STALLED on {ys_rel} — no "
                f"CPU, no I/O and no output for {_GATE_STALL_GRACE_S}s. It was "
                f"not slow; it was doing nothing. -sv/-flatten/hilomap are "
                f"unverified; treat as fail for strict gating."
            )
        else:
            r2 = _watchdog.completed_process(_argv2, _res2)
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
    11: "DFT insertion (Tessent Scan / DFTMAX)",
    12: "Post-DFT optimisation (Design Compiler + DFT)",
    13: "RTL≡post-DFT equivalence (Formality / Conformal)",
    # v1.6.211 (#92) — added per field-agent verification that
    # iic-osic-tools open-source paths do not produce gate-required
    # signoff artefacts. OpenRCX / OpenSTA-IR / antenna_checker /
    # OpenROAD-fill / klayout-LVS work for development but not for
    # tapeout-grade signoff precision.
    # ── THE KEYS DRIFTED AWAY FROM THE LABELS, AND THE KEYS ARE WHAT RUNS ──
    #
    # Consumed as `r.id in _OPEN_SOURCE_CONTAINER_BLOCKED_STEPS`, so the step
    # ID decides what gets promoted to PASS_WITH_OPEN_SOURCE_CONSTRAINTS and
    # the prose is decoration. Every label from here down named a step ONE OR
    # TWO LATER than its key — two steps were inserted into the flow yaml (one
    # before Parasitic Extraction, one before Post-Layout SPICE) and this table
    # was never re-keyed. Measured against the yaml, by name:
    #
    #   key 21 "Parasitic Extraction"  -> yaml 21 is Routing
    #   key 23 "IR Drop"               -> yaml 23 is Post-route STA
    #   key 24 "EM check"              -> yaml 24 is IR Drop
    #   key 25 "Antenna check"         -> yaml 25 is EM check
    #   key 26 "Signal Integrity"      -> yaml 26 is Antenna check
    #   key 28 "Post-Layout SPICE PV"  -> yaml 28 is PERC / Reliability
    #   key 29 "PV ERC + Density"      -> yaml 29 is Post-Layout Gate-Level Sim
    #   key 32 "Metal Fill"            -> yaml 32 is Post-route timing repair
    #
    # So the flow was quietly deferring ROUTING, POST-ROUTE STA, GATE-LEVEL
    # SIMULATION and POST-ROUTE TIMING REPAIR — four steps the open-source
    # container performs perfectly well (TritonRoute, OpenSTA multi-corner,
    # iverilog+SDF, OpenROAD repair_design/repair_timing) — under labels that
    # describe entirely different, genuinely commercial-only work. A FAIL on
    # any of them could be promoted to a machine-attested deferral. That is a
    # false PASS, and it is the exact failure the deferral tier exists to avoid
    # producing: the tier's premise is "the OSS container CANNOT do this", and
    # for those four steps the premise is simply untrue.
    #
    # Corroborated inside this same tree: test_step23_25_signoff_gates_wired.py
    # exists to insist that step 23's sign-off checkers must actually RUN,
    # while this table let step 23's FAIL be promoted away.
    #
    # FIXED IN THE TIGHTENING DIRECTION ONLY. Keys 21 / 23 / 29 / 32 are
    # removed, and the entries that already sat on a genuinely commercial-only
    # step keep their deferral and get a label naming the step they defer.
    #
    # DELIBERATELY NOT DONE — this is a flow-owner decision, not a drift fix:
    # the removed labels also imply that yaml 22 (Parasitic Extraction), 27
    # (Signal Integrity), 30 (Post-Layout SPICE) and 34 (Metal Fill) were meant
    # to be deferrable and currently are not. Adding them would let MORE
    # failures be promoted, so it is left to the owner rather than smuggled in
    # under a bug fix. Likewise yaml 31 (Physical Verification): the old key-29
    # label defers only "ERC + density signoff variants" and says in its own
    # words that klayout/magic DRC/LVS cover the topology, so re-keying 29 to
    # 31 would defer DRC and LVS too. That needs a sub-gate, not a whole-step
    # deferral, so key 29 is dropped rather than moved.
    24: "IR Drop static+dynamic (RedHawk / Voltus; OpenSTA+PDNGEN "
        "only handles static average IR)",
    25: "EM check (RedHawk-EM / Totem)",
    26: "Antenna check (Calibre PERC antenna rules; OpenROAD "
        "antenna_checker only catches a subset)",
    28: "PERC / Reliability sign-off — ESD + latch-up + cross-domain "
        "(Calibre PERC; no open-source equivalent)",
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
    # level map matches how Steps 5/11/12/13/24/25/26/28 and the
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


# ── #497 step 4 — the four prose scrapers are GONE ───────────────────────────
#
# `_parse_p0_failing_subgates`, `_normalise_p0_reason_line`,
# `_per_gate_from_p0_reasons` and `_p0_passed_gate_count` stood here. Each
# recovered a name, a record or a number by re-deriving the P0 umbrella's
# English from line prefixes, and between them they produced three shipped
# defects and two latent ones. Every one of their answers now comes from the
# umbrella's typed records (`_p0_failing_gate_names`, `_p0_audit_gate_records`,
# `_p0_structural_fail_lines`, `_p0_passed_count`), and `reasons` is rendered
# from those same records rather than parsed back out of them.
#
# They are deleted rather than deprecated. A scraper left in the tree is a
# second grammar waiting for a caller: the next person to need a failing-gate
# name finds two ways to get one, and the one that reads prose looks like the
# cheaper option right up until a seventh line shape appears.


def _compose_p0_reasons_from_records(
    records: List[Dict[str, Any]],
    executed: Optional[bool],
    n_registered: Optional[int] = None,
) -> List[str]:
    """#497 step 3 — the P0 umbrella's ``reasons``, RENDERED FROM the records.

    This is the direction change the issue asks for. ``reasons`` used to be
    authored from buckets the umbrella built as it went; it is now a VIEW of
    the same structured records every machine consumer reads, produced by one
    function, in one direction. A line that disagrees with a record is no
    longer possible — not because a test compares them, but because there is
    only one of them.

    ``executed`` is the umbrella's own tri-state (``_run_structural_rtl_gates``
    returns ``None`` when it dispatched nothing at all). It is what emits the
    no-RTL note, so that non-gate line comes from the umbrella's own state
    rather than from a per-gate bucket it was never about. See
    ``_P0_NO_RTL_NOTE``.

    The rendered TEXT is deliberately unchanged, byte for byte, in all six
    shapes: the operator-facing per-step listing renders `reasons`, and #492
    exists precisely because unrun gates used to be invisible there.
    """
    decisive_or_skip = [r for r in records
                        if r.get("verdict") not in ("BLOCKED", "INCOMPLETE")]
    fails, skips, waivers = _p0_buckets_from_records(decisive_or_skip)
    reasons = _compose_p0_reasons(
        fails, skips, waivers, n_registered,
        umbrella_notes=[_P0_NO_RTL_NOTE] if executed is None else None)
    process_lines = [
        (f"{r['verdict']}: {r['name']} — reason_class="
         f"{r['reason_class']}: {r['message']}")
        for r in records if r.get("verdict") in ("BLOCKED", "INCOMPLETE")
    ]
    if process_lines:
        # `_compose_p0_reasons` emits a clean-sweep sentence when its filtered
        # input is empty.  A set containing only blocked/incomplete records is
        # not clean, so remove that synthetic sentence before adding the real
        # process-provenance lines.
        if (len(reasons) == 1
                and reasons[0].startswith("every registered structural-RTL")):
            reasons = []
        reasons.extend(process_lines)
    return reasons


def _compose_p0_reasons(s_fails: List[str],
                        s_skips: List[str],
                        s_waivers: List[Dict[str, Any]],
                        n_registered: Optional[int] = None,
                        umbrella_notes: Optional[List[str]] = None
                        ) -> List[str]:
    """Render the P0 umbrella's ``StepResult.reasons``.

    THE ONLY WRITER OF THE OPERATOR-FACING GRAMMAR.  Since #497 step 3 its
    input is a projection of the umbrella's structured records
    (``_compose_p0_reasons_from_records``), not a set of buckets built
    independently beside them — so this is a RENDERER with one upstream, no
    longer one half of a producer/parser pair with four downstreams.

    It was extracted from ``main()`` when it was still that half: every parser
    test had to hand-write a fixture of what it BELIEVED the producer emitted,
    which is exactly how the #492 disclosure block shipped with 1921 green unit
    tests and was found only by a real flow run — no test ever fed real
    producer output to a real parser. Keep it reachable from a test.

    THE SIX SHAPES:

      * 1 failure   -> ``FAIL: <gate> — <msg>``                  (Form 1)
      * >=2         -> ``Failed gates (N):`` + ``  - <gate> — <msg>``
                                                                 (Form 2)
      * disclosure  -> a heading + ``  - <gate> (NOT INVOKED: …)`` each
      * skips       -> ``SKIP: <gate>``
      * waivers     -> ``WAIVED-DEFERRED: <gate> — …``
      * nothing     -> one explicit clean-sweep line

    Form 2 and the disclosure bullets share the ``  - `` prefix. That collision
    is why the disclosure had to be recognised by the predicate shipped with
    its formatter rather than by prefix — and why, after step 4, nothing
    recognises anything here at all.

    ``umbrella_notes`` are the umbrella's statements about ITSELF, not about
    any gate. They render with the same ``SKIP: `` prefix the per-gate skips
    use (the operator's line is unchanged) but they are a separate input, so
    the per-gate population never contains a line that names no gate.
    """
    if n_registered is None:
        n_registered = len(_STRUCTURAL_RTL_GATES)
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
    # #492 — separate the two populations that rc 2 used to merge. A gate
    # that argument parsing rejected produced NO verdict; listing it under
    # the same "SKIP:" heading as a gate that looked and found no input is
    # what made 39 registered gates read as benign. They are counted and
    # headed separately, so the umbrella can no longer imply it checked
    # what those gates audit.
    not_invoked = [s for s in s_skips
                   if _gate_invocation.is_not_invocable_entry(s)]
    plain_skips = [s for s in s_skips
                   if not _gate_invocation.is_not_invocable_entry(s)]
    not_invoked_lines: List[str] = []
    if not_invoked:
        not_invoked_lines.append(
            _gate_invocation.format_not_invocable_heading(
                len(not_invoked), n_registered))
        not_invoked_lines += [f"  - {s}" for s in not_invoked]
    # #497 step 3 — the umbrella's notes about ITSELF render beside the
    # per-gate skips (same prefix, unchanged operator line) but arrive on
    # their own input, so no line that names no gate is ever inside the
    # per-gate population.
    reasons_combined = (failed_gate_lines
                        + not_invoked_lines
                        + [f"SKIP: {s}" for s in plain_skips]
                        + [f"SKIP: {n}" for n in (umbrella_notes or [])]
                        + waiver_lines)
    if not reasons_combined:
        # Clean sweep. Say so explicitly rather than emitting a
        # reason-less PASS that reads like a step that did nothing.
        reasons_combined = [
            "every registered structural-RTL gate that dispatched "
            "PASSED (0 FAIL / 0 SKIP / 0 WAIVED)"
        ]
    return reasons_combined


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
# KEY (a) — "the detected class has rtl_gen=null AND reused RTL is staged" —
# used to be implemented here, in full, and mirrored a second time inside
# `l_doc_structured_field_count_check` (whose copy said so in its own
# docstring). #504 measured what two copies of one idea cost: a third consumer
# (`l6_fsm_scaffold_actionable_check`) held NEITHER copy and blocked Phase 1 on
# a claim about a scaffold consumer that does not run for a reused-IP design.
# The predicate now lives once, in `_reused_ip_predicate`, and all three read
# it. Same semantics, same fail-closed behaviour — see that module's docstring
# for why the per-caller rejection set is an argument rather than a constant.
_detected_class_rtl_gen_null_and_vendor_rtl = (
    _reused_ip.detected_class_rtl_gen_null_and_vendor_rtl)


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
    "analog_hw_spice_correlation_check",
})


# ORGANIC-20260614 (#632) — the analog / mixed-signal NAMING CONVENTION for
# gates in the P0 structural-RTL umbrella: the canonical gate FILE names
# (analog_*, mixed_signal_*, pdk_analog_*, spice_correlation_*), NOT any
# chip / vendor / SKU literal.
#
# THIS TUPLE NO LONGER DECIDES ANY SKIP. It used to: `_skip_analog_p0_gates()`
# derived the `--skip-analog` suppression set from it, so a gate was silenced
# by how it was SPELLED. See `_ANALOG_TRACK_OWNS` below for the record that
# decides now, and for the gate that measurably lost its verdict to the prefix.
# What the convention is still for: demanding that a newly-registered
# analog-named gate DECLARE which side of that record it is on.
_ANALOG_STRUCTURAL_GATE_PREFIXES: tuple[str, ...] = (
    "analog_",
    "mixed_signal_",
    "pdk_analog_",
    "spice_correlation_",
)


def _is_analog_structural_gate(gate_name: str) -> bool:
    """True when `gate_name` FOLLOWS the analog / mixed-signal naming
    convention (canonical file-name prefix).

    NOT A SKIP PREDICATE, and it stopped being one deliberately — see
    `_ANALOG_TRACK_OWNS`. A name says how a gate is spelled; it does not say
    which track's deferral owns the gate's verdict, and the two diverge (a
    gate that POLICES whether an analog deferral is legitimate is spelled
    exactly like the gates that deferral covers). Its one remaining use is
    `_undeclared_analog_named_gates`, which uses it to DEMAND an ownership
    declaration for a newly-registered analog-named gate.

    chip-AGNOSTIC: matches on the gate program's own name prefix, never on a
    chip / vendor / SKU string.
    """
    return any(gate_name.startswith(p)
               for p in _ANALOG_STRUCTURAL_GATE_PREFIXES)


# ── OWNERSHIP, NOT RESEMBLANCE, DECIDES A DEFERRED-TRACK SKIP ───────────────
#
# THE DEFECT THIS REPLACES, MEASURED. `_skip_analog_p0_gates()` used to be
# `_STRUCTURAL_RTL_GATES` filtered by `_is_analog_structural_gate` — the name
# prefix above. So the question "may `--skip-analog` silence this gate?" was
# answered by how the gate is SPELLED. On a project whose input docs document
# an LDO and a bandgap while `L5_ADI_SPEC.json` carries `analog_blocks: []`,
# the SAME tree gives:
#
#   skip_analog=False  analog_content_detected_must_emit_l5_check  FAIL (rc 1)
#   skip_analog=True   analog_content_detected_must_emit_l5_check  SKIP
#                      ("analog track deferred via --skip-analog")
#
# That gate does not own the analog-track deferral. Its subject is the PHASE-1
# L5 RECORD: "the docs describe analog content that L5 never wrote down". It
# reads `input/docs/` + `generated_docs/L5_*.json` and no A-step artefact, so
# deferring A1..A9 does not make it unanswerable. It is the gate that decides
# whether an analog deferral is even REVIEWABLE — a deferred track whose
# content was never recorded is an open item nobody can cost. Silencing it
# because its file name starts with `analog_` means the one run that defers
# the analog track is the one run that never has to admit it has any.
#
# THE RULE. A gate is skipped for a deferred track only when the deferral
# record NAMES it as owned. Resemblance never decides. `_ANALOG_TRACK_OWNS`
# is that record: every entry is a gate whose VERDICT IS PRODUCED BY the
# deferred A1..A9 / M1..M4 work, so deferring the track legitimately defers
# the gate. chip-AGNOSTIC — the entries are checker program names and the
# rationale is track membership, never a chip / vendor / SKU / PDK literal.
_ANALOG_TRACK_OWNS: frozenset[str] = frozenset({
    # Per-block A1..A9 artefact + substance gates — the deferred steps' own
    # deliverables.
    "analog_a1_spec_extract_check",
    "analog_a2_topology_select_check",
    "analog_a3_netlist_gen_check",
    "analog_a4_corner_sweep_check",
    "analog_a5_layout_check",
    "analog_a6_block_pv_check",
    "analog_a7_post_layout_resim_check",
    "analog_a8_hardmacro_gen_check",
    "analog_a9_hw_verify_check",
    "analog_artefact_substance_check",     # substance OF those deliverables
    # Project-wide gates that read A-step outputs and can answer nothing
    # without them.
    "analog_block_coverage_check",         # per-block A5-A8 coverage
    "analog_corner_sweep_check",           # A4 PVT sweep
    "analog_netlist_pdk_check",            # A3 deck vs PDK
    "analog_pre_vs_post_layout_check",     # A5 vs A7
    "analog_hardmacro_check",              # A8 LEF/Liberty/GDS/Verilog
    "analog_flow_compliance_check",        # A1-A9 closure
    "analog_digital_interface_check",      # per-block interface contract
    "pdk_analog_completeness_check",       # PDK views A3/A4/A6 consume
    "spice_correlation_check",             # post-layout SPICE deck (A7)
    "analog_hw_spice_correlation_check",   # A9 bench vs SPICE
    "analog_hw_tb_de10lite_budget_check",  # A9 hardware TB
    # Mixed-signal merge — downstream of the A8 hardmacros.
    "mixed_signal_cosim_check",
})

# The other half of the SAME record, stated rather than left to be inferred
# from an absence. A gate here matches the analog naming convention and is
# deliberately NOT owned by the track deferral: it stays runnable, and stays
# required, on a run that defers the analog track. Keeping the reason beside
# the name is what stops the next reader from "restoring" the prefix rule.
_ANALOG_NAMED_NOT_OWNED: Dict[str, str] = {
    "analog_content_detected_must_emit_l5_check": (
        "subject is the Phase-1 L5 RECORD, not the A1..A9 work: it asks "
        "whether the input docs describe analog content that L5 never "
        "recorded. It reads input/docs + generated_docs only, so a deferred "
        "analog track leaves it fully answerable — and it is the gate that "
        "makes the deferral reviewable, because an unrecorded analog block "
        "is an open item nobody can cost."),
}


def _undeclared_analog_named_gates() -> tuple[str, ...]:
    """Registered gates that LOOK analog by name but carry NO ownership
    declaration, in canonical registry order.

    The naming convention is used here for ONE purpose — to demand a
    declaration — and never to decide a skip. At runtime such a gate is
    fail-closed: absent from `_skip_analog_p0_gates()`, so it RUNS. A
    non-empty result is registry drift (a new analog gate was registered
    without saying whether the track deferral owns it) and the regression
    suite pins it to empty, so the drift is loud instead of silent.
    """
    declared = _ANALOG_TRACK_OWNS | frozenset(_ANALOG_NAMED_NOT_OWNED)
    return tuple(g for g in _STRUCTURAL_RTL_GATES
                 if _is_analog_structural_gate(g) and g not in declared)


def _skip_analog_p0_gates() -> frozenset[str]:
    """The set of structural-RTL gates suppressed by `--skip-analog` inside
    the P0 umbrella: the OWNERSHIP record intersected with the registry.

    Two independent conditions, both required. `_ANALOG_TRACK_OWNS` says the
    analog-track deferral owns the gate's verdict; `_STRUCTURAL_RTL_GATES`
    says the umbrella actually runs it. The intersection can therefore never
    name a gate the umbrella does not run, and — the point of this function —
    never a gate that merely SPELLS like one the deferral owns. chip-AGNOSTIC.
    """
    return frozenset(g for g in _STRUCTURAL_RTL_GATES
                     if g in _ANALOG_TRACK_OWNS)


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

# The flow's OWN record of which steps belong to the analog track: the stage a
# step declares in `flow/phase1_phase2_phase3.yaml`. Same rule as
# `_ANALOG_TRACK_OWNS` one level up — a step is deferred by `--skip-analog`
# because the flow SAYS it is on the analog track, never because its id is
# spelled a certain way. See `_step_owned_by_analog_track`.
_ANALOG_TRACK_STAGE = "stage_analog"


def _step_owned_by_analog_track(step: Dict[str, Any]) -> bool:
    """True iff the FLOW DECLARES this step a member of the analog track.

    Replaces `str(sid).startswith("A")`. The old test read the first letter
    of the step id, which is name resemblance doing a skip's job: the analog
    track's membership is recorded — every A1..A9 step in the shipped flow
    carries `stage: stage_analog` — and the record was simply not consulted.
    Any future step whose id merely begins with "A" (an `AXI_*` lint step, an
    `ATPG*` step, an `AUDIT` step) was silently deferred by `--skip-analog`
    while owning none of that deferral.

    Fail-CLOSED: a step that declares no stage is NOT owned, so it runs and
    gates normally. An absent record is not a claim of ownership.
    chip-AGNOSTIC: reads the flow's stage field, never a chip / vendor name.
    """
    return str(step.get("stage") or "") == _ANALOG_TRACK_STAGE

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


# ── #492: the umbrella's argv, as ONE named construction ─────────────────────
# Gates whose CLI does NOT accept the umbrella's default `[<project>]` shape but
# which this umbrella can invoke correctly, because the flag they want is a value
# the umbrella already computed. ONE ENTRY HERE IS A CONVERSION, and a conversion
# is only honest when it has been measured: a gate that starts running must not
# start FAILing everything (that trades a false skip for a false FAIL), and it
# must not start PASSing over an empty denominator (that trades a false skip for
# a false PASS, which is worse — the umbrella would then be certifying a check
# that examined nothing).
#
# MEASURED at v1.7.68 over the 107 tracked RTL directories under benchmark-data,
# driving each candidate with `--rtl-dir <dir>` on a scratch MIRROR of the corpus
# (no gate CLI was pointed at the tracked tree). 14 of the rejected gates want
# only `--rtl-dir`, a value the umbrella already derives — but wanting it is not
# enough. TWO bars have to be cleared, and the second is the one that disqualifies
# most of them: the gate must not start FAILing everything (a false skip traded
# for a false FAIL), and it must actually EXAMINE something, because a PASS over
# an empty denominator is a false PASS and is strictly worse than the skip it
# replaces — the umbrella would then be certifying a check that looked at nothing.
#
# DENOMINATOR, stated so it reproduces: 107 is `git ls-files benchmark-data`
# filtered to directories named `rtl` holding .v/.sv. The sweep also covered one
# directory named `src` (subservient's vendored formal copy), because the filter
# used this function's own rtl_dir alternation ("phase2/stage1/rtl","rtl","src",
# "hdl") — 108 dirs in total. Every number below is quoted on the reproducible
# 107; including the 108th changes no verdict for either converted gate.
#
# Exactly two clear both bars:
#
#   sustained_vs_edge_check        0/107 FAIL, denominator disclosed on 107/107
#                                  ("27 files scanned" on the largest design)
#   timer_freeze_after_state_check 0/107 FAIL, `files_scanned` non-zero 107/107
#
# Six more add no FAIL but report an EMPTY denominator on all 107 (e.g.
# `pulse_decoder_edge_check` `files_checked: 0`, `tristate_self_rx_mask_check`
# `inout_ports: []`); one discloses no denominator at all; four would redden the
# corpus (`testbench_exists_check` 102/107). All stay disclosed as NOT INVOKED.
# The full table, and the rule that licenses a conversion, are pinned in
# `tests/test_issue492_gate_argv_conversions.py` so a future conversion has to
# re-derive the measurement rather than assume it.
# vibe-ic#559 — THE #492 MEASUREMENT, moved here from the test that owned it.
#
# The prose above names three of the eleven gates it describes; the other eight
# were only ever named in `tests/test_issue492_gate_argv_conversions.py`. A test
# file is not an importable decision record for the code under test, so nothing
# in this module could answer "is this gate deliberately unwired, or did nobody
# look?" — and that question is what separates a licensed silence from an
# accidental one (the remaining half of #559).
#
# The numbers are UNCHANGED. `test_issue492_gate_argv_conversions` still owns the
# RULE they license (convert iff 0 new FAILs AND a non-empty denominator on every
# project) and now asserts it against this table rather than its own copy.
#
# vibe-ic v1.9.0 — `fpga_wrapper_input_polluter_check` was CONVERTED in v1.8.82 and
# the row below was not written. The conversion was measured (the commit records
# 0 FAIL and a "Files scanned" of 1..102, never 0, over all 107); what was missing
# is the RECORD, and `test_only_gates_that_cleared_both_bars_were_converted` derives
# the licensed set from this table, so the adapters held a gate the table did not
# license. That test went red at the next minor-milestone full suite and stayed red
# through four patch releases, because patch cadence does not run it. A measurement
# that lives only in a commit message is not available to the code that has to honour
# it. Re-derived here before writing the row rather than copied from that message:
# same mirror, same `_structural_gate_argv`, rc=0 on 107/107, denominator >0 on 107/107.
#
# v1.8.82 also added a THIRD bar this table cannot express: can the gate FAIL at all?
# Without `--strict` a detected polluter is a WARNING and rc stays 0, so the gate
# would have cleared both columns below BY BEING INCAPABLE OF FAILING. That is why
# `_STRUCTURAL_GATE_BARE_FLAGS` exists and why the row above is only true of the
# `--strict` argv the umbrella actually builds.
#
# One honest limit on the second column, worth stating because it is not visible in
# the number: this gate's disclosed denominator counts FILES, while its subject is
# modules carrying >=2 inout ports — re-measured at 10 such modules across 5 of the
# 108, using the gate's own parser. The column means "the gate disclosed a non-zero
# denominator", which is the property the rule was written against and which
# `sustained_vs_edge_check` is also judged on, so the row is (0, 108) and not (0, 5).
# A gate disclosing a count whose subject is absent is the #564 family, not the #492
# one; recorded here so the next conversion reads it instead of re-deriving it from
# the corpus a second time.
#
# 2026-08-04 — RE-MEASURED OVER 108, AND THE PIN WAS WATCHING THE WRONG THING.
#
# `test_the_published_denominator_is_the_one_a_reader_reconstructs` went red because
# the corpus grew: `benchmark-data/ic/caravel_user_project/v1.9.43_sky130A/phase2/
# stage1/rtl` landed in cdc54d32f (2026-08-02) and is the 108th. Raising the pin on
# its own would have asserted "0 FAIL over ALL of them" about a directory no gate had
# been pointed at, so the sweep was re-run instead: 15 gates x 108 directories = 1620
# real subprocess runs, argv in the umbrella's own `_structural_gate_argv` shape, on a
# scratch MIRROR of the corpus — no gate CLI was pointed at the tracked tree. THE
# VERDICT IS UNCHANGED: the same three gates clear both bars, and on the 108th
# directory all three are rc 0 with a non-zero denominator (5 files each).
#
# NINE of the fifteen rows had rotted, and only ONE of the nine moved because of the
# corpus (`testbench_exists_check` 102 -> 103, the new directory shipping no
# testbench). The other eight moved because the GATES changed underneath a table that
# nothing but the corpus SIZE was pinned against:
#
#   v1.7.70 `090fe7128` ("make every zero say what it is") rewrote the denominator
#     disclosure of eight of these gates — ONE COMMIT after this table was written.
#     `cmd_arg_range_validation_check` went 4 -> 0, `pulse_decoder_edge_check` 0 -> 1,
#     `tristate_self_rx_mask_check` now decides `inout port + OE companion` (5 dirs
#     declare an inout, 0 pair it with a companion), `transient_signal_latch_check`
#     went from disclosing NO denominator to disclosing an empty one, and
#     `bit_count_modulo_check` started FINDING something: 0 -> 1 new FAIL, on
#     `evaluation/phase1_parity/hdlc/phase2/stage1/rtl`. ATTRIBUTED, not assumed — the
#     v1.7.69 gate is rc 0 on today's hdlc RTL and today's gate is rc 1 on the v1.7.69
#     hdlc RTL, so that is a gate change, not a corpus one. It moves that gate's
#     REASON for staying unconverted from "empty denominator" to "reddens the corpus";
#     it does not move the verdict.
#   v1.7.84 `d405db74b` (gate exit codes) made `pre_awake_silence_check` return rc 2
#     VACUOUS instead of rc 0 on 107 of the 108, so its denominator is 1, not 107.
#
# The four reddening rows' second column had never been a measurement: it was the
# corpus size, filled in because column 1 already disqualified them.
# `packet_length_check_present` discloses `files_checked: 0` on 104 of the 108 and
# always did, so 107 was not a reading of anything. Those cells now hold a measured
# number, and EVERY ROW NAMES THE COUNT IT WAS READ FROM — the second column was
# unreconstructable, which is how eight of them stayed wrong in plain sight.
#
# WHAT THIS PIN CANNOT SEE, recorded because it is the defect above: it compares a
# corpus SIZE, so it fires when a directory is added and is silent when a gate's
# behaviour moves. Eight rows were wrong for six minor versions with the pin green.
# The pin is KEPT — it demanded this re-measurement and got it, which is exactly the
# job, and a derived value could not have demanded anything — but a tripwire over the
# measured GATES is the missing half, and it is not in this change.
#
#   gate                              new FAIL/108   projects w/ denominator>0
P0_CORPUS_DENOMINATOR = 108
#: Each row's comment names the count column 2 was read from, so a reader
#: reconstructs it instead of trusting it. `denominator.examined` is the structured
#: block v1.7.70 gave eight of these gates; the rest disclose one scalar.
P0_RTL_DIR_GROUP_MEASUREMENT = {
    "sustained_vs_edge_check":          (0, 108),   # CONVERTED — `N files scanned`
    "timer_freeze_after_state_check":   (0, 108),   # CONVERTED — `files_scanned`
    "fpga_wrapper_input_polluter_check": (0, 108),  # CONVERTED v1.8.82 — `Files scanned`
    "cmd_arg_range_validation_check":   (0, 0),     # `denominator.examined` — was 4/107
    "bit_count_modulo_check":           (1, 2),     # `denominator.examined`; now REDDENS 1
    "l12_sequence_implementation_check": (0, 0),    # `denominator.examined` (L12 sequences)
    "otp_write_lock_gate_check":        (0, 0),     # `denominator.examined` (write-enable sites)
    "pulse_decoder_edge_check":         (0, 1),     # `denominator.examined` (decoder files)
    "response_payload_template_check":  (0, 0),     # `denominator.examined` (payload assignments)
    "tristate_self_rx_mask_check":      (0, 0),     # `denominator.examined` (driven tristate buses)
    "transient_signal_latch_check":     (0, 0),     # `examined N ... pairs` — was None
    "testbench_exists_check":           (103, 108),  # the l9-shaped trap; subject = the dir itself
    "rtl_precheck_gate":                (3, 108),   # `auditors_total: 7` on every project
    "packet_length_check_present":      (3, 4),     # `files_checked` — 107 was never measured
    "pre_awake_silence_check":          (1, 1),     # non-vacuous on 1 — 107 was never measured
}


_STRUCTURAL_GATE_ARGV_ADAPTERS: Dict[str, tuple[str, ...]] = {
    "sustained_vs_edge_check": ("--rtl-dir",),
    "timer_freeze_after_state_check": ("--rtl-dir",),
    # #559 — converted after re-deriving the #492 bar over the 107 tracked rtl
    # directories, on a scratch mirror. Both halves cleared, and a third
    # question had to be answered before the conversion was safe:
    #
    #   no new FAIL            rc=0 on 107/107, with --strict
    #   non-empty denominator  "Files scanned" is 1..102, never 0, on all 107
    #   CAN it fail at all?    an injected three-inout AND wrapper exits 1
    #
    # The third is why `--strict` is in _STRUCTURAL_GATE_BARE_FLAGS below.
    # Without it the gate DETECTS the polluter and still exits 0 (measured:
    # "Warnings: 1 ... PASS"), so wiring it plain would have added a checker
    # that cannot fail for the reason it exists — clearing the bar precisely
    # BECAUSE it is incapable of failing.
    "fpga_wrapper_input_polluter_check": ("--rtl",),
}


#: Flags a gate takes WITHOUT a value, appended after the valued ones.
#:
#: The adapter above pairs every flag with the same target, which cannot express
#: a store_true: `--strict <path>` is a different argv, and argparse would read
#: the path as a positional. Kept as a separate table rather than a sentinel
#: inside the first one so both stay plain data — a test can read them and
#: neither needs a decoder.
_STRUCTURAL_GATE_BARE_FLAGS: Dict[str, tuple[str, ...]] = {
    "fpga_wrapper_input_polluter_check": ("--strict",),
}


# ---------------------------------------------------------------------------
# vibe-ic#1968 — DECLARED INVOCATION CONTRACTS FOR NON-UNIFORM P0 GATES.
#
# The generic P0 argv is ``python gate.py <project>``.  That is a convention,
# not an interface: the 36 programs below declare different CLIs and therefore
# rejected the call before examining the design.  A parser crash is never an
# applicability decision.  This registry is the single declaration of HOW the
# umbrella asks each exceptional gate; gates absent from it keep the historical
# project-positional contract.  Applicability remains a separate, design-owned
# question and is resolved from ic_class/L-doc declarations before argv exists.
#
# Values are closed invocation shapes, not arbitrary shell fragments.  The
# builder below expands each shape from paths/values the design declares.  It
# never evals strings and never harvests a semantic expectation from the RTL it
# is checking (CRC signal, masks, periodic obligations, bus drivers and gap
# timing all come from L-docs).
# ---------------------------------------------------------------------------
_STRUCTURAL_GATE_INVOCATION_CONTRACTS: Mapping[str, str] = MappingProxyType({
    "backlog_sanitize_check": "backlog-dir",
    "bit_count_modulo_check": "rtl-dir",
    "cmd_arg_range_validation_check": "rtl-dir",
    "crc_bitorder_check": "crc-bitorder",
    "crc_seed_consistency_check": "crc-vectors",
    "cross_constant_invariant_check": "constant-invariants",
    "fpga_async_input_synchronizer_check": "fpga-top",
    "fpga_qsf_lint": "fpga-qsf",
    "fresh_agent_provenance_check": "reference-provenance",
    "interface_encoding_audit": "interface-encoding",
    "json_schema_check": "l3-schema",
    "l12_sequence_implementation_check": "l12-sequences",
    "l9_completeness_check": "l9",
    "mask_application_check": "declared-masks",
    "module_port_audit": "module-ports",
    "oe_pattern_check": "rtl-files-output",
    "openroad_tcl_deprecation_check": "no-args",
    "otp_write_lock_gate_check": "rtl-dir",
    "output_artifact_check": "rtl-artifacts",
    "packet_length_check_present": "rtl-dir",
    "payload_bit_position_check": "payload-bitmap",
    "periodic_signal_required_check": "periodic-signals",
    "phase1_gate_contract_check": "no-args",
    "practical_notes_specificity_check": "no-args",
    "pre_awake_silence_check": "rtl-dir",
    "protocol_gap_check": "protocol-gap",
    "pulse_decoder_edge_check": "rtl-dir",
    "response_payload_template_check": "rtl-dir",
    "rtl_precheck_gate": "rtl-precheck",
    "scope_periodic_pulse_check": "scope-samples",
    "testbench_exists_check": "testbench",
    "tester_oracle_health_check": "tester-oracle",
    "transient_signal_latch_check": "rtl-dir",
    "tristate_bus_check": "tristate-bus",
    "tristate_self_rx_mask_check": "rtl-dir",
    "warn_acceptance_policy_check": "warn-policy",
})

# The #559 disposition tables below are retained as the measured history that
# motivated #1968. They no longer license runtime silence: every one of their
# affected names is now askable through the closed contract registry above.


# ---------------------------------------------------------------------------
# #559 — GATES REGISTERED IN THE WRONG UMBRELLA.
#
# `_STRUCTURAL_RTL_GATES` is driven once per project over the corpus.  Four of
# the gates in it do not take a project, and reading them as "unwired" was my
# own mis-triage: three examine THIS PLUGIN's source, and one needs a physical
# instrument.  Driving a plugin-wide check per project would run it 107 times
# for 107 identical answers.
#
# Each disposition below is measured, not judged — the two marked READY were
# checked for an honest denominator first, because a gate that cannot tell a
# clean scan from a scan of nothing is worse wired than unwired.
# ---------------------------------------------------------------------------
_NOT_A_PROJECT_GATE: Dict[str, Dict[str, str]] = {
    "openroad_tcl_deprecation_check": {
        "scope": "plugin-self-check",
        "measured": (
            "Default --search-dir is the plugin tree containing the program; "
            "examines 3592 files, cwd-independent."),
        "disposition": (
            "READY — wired into tools/ci/repo_hygiene_gates.sh. v1.8.80 first "
            "made it state its denominator: before that an empty search "
            "directory and the whole plugin tree produced the same sentence "
            "and the same rc=0."),
    },
    "practical_notes_specificity_check": {
        "scope": "plugin-self-check",
        "measured": (
            "Scans every PRACTICAL_NOTES.md under skills/ — 16 files, matching "
            "the on-disk count exactly. An empty path set is rc=2 with a named "
            "reason, not a pass."),
        "disposition": (
            "READY — wired into tools/ci/repo_hygiene_gates.sh. It already "
            "refuses a zero denominator, which is why it needed no repair."),
    },
    "phase1_gate_contract_check": {
        "scope": "plugin-self-check",
        "measured": (
            "Its docstring says EVERY Phase 1 gate under programs/ must satisfy "
            "the contract; DEFAULT_GATES names 7, from v0.74. The flow YAML's "
            "stage1 now references 29 programs, and running the contract over "
            "all 29 gives 22 errors / 45 warnings, rc=1."),
        "disposition": (
            "NOT READY. Wiring it at the current scope buys a green over 7 of "
            "29; widening it to the population its own docstring claims turns "
            "every landing red. Which of the 29 the contract is meant to bind "
            "has to be decided, and the errors fixed, before it is a gate "
            "rather than a report."),
    },
    "scope_periodic_pulse_check": {
        "scope": "hardware-instrument",
        "measured": (
            "With no arguments: `ERROR: cannot open scope (vid=0x2a8d "
            "pid=0x1768): Device not found`. It drives a bench oscilloscope."),
        "disposition": (
            "KEEP registered, driven only where the instrument is attached. No "
            "CI runner and no per-project umbrella can satisfy it, and a "
            "synthetic capture would make it assert about a trace nobody "
            "measured."),
    },
}


# ---------------------------------------------------------------------------
# #559 — GATES NO GENERIC UMBRELLA CAN DRIVE, AND WHY THAT IS THE RIGHT ANSWER.
#
# #559 measured 33 registered gates that reject the umbrella's argv, and split
# them by whether the umbrella could supply what they ask for.  Seventeen want a
# project path, an RTL directory, an output directory or a top-module name —
# things the umbrella already computes, so their silence is an unfinished wiring
# job and each still has to clear #492's bar before conversion.
#
# The four below are a different kind.  Every one of them requires a value that
# is a fact ABOUT THE DESIGN and nowhere else: which signal carries the CRC,
# what the tristate bus is called, which drivers contend for it, which signal
# ends the frame.  No umbrella can synthesise those, and handing them a
# placeholder would convert an honest NOT_INVOCABLE into a verdict about a
# signal that does not exist — strictly worse than the silence, because a wrong
# PASS is indistinguishable from a real one.
#
# So this is not a to-do.  It is the decision, recorded: these four are driven
# explicitly with real values by whoever knows them, or they gain a discovery
# mode that derives the value and can say when it failed to.  What #559 found
# missing was never the wiring — it was this table saying so, which is why they
# read as "undecided" while being correctly configured.
#
# Recorded here rather than de-registered: removing them from
# `_STRUCTURAL_RTL_GATES` would shrink the denominator and delete the evidence
# that the check exists at all, which is the same disappearance by a tidier
# route.  Asserted by `tests/test_issue559_semantic_argv_gates.py`.
# ---------------------------------------------------------------------------
_SEMANTIC_ARGV_UNDRIVABLE: Dict[str, Dict[str, str]] = {
    "crc_bitorder_check": {
        "requires": "--rtl-files --crc-signal --out-dir",
        "design_value": "--crc-signal",
        "why_no_umbrella": (
            "The name of the signal carrying the CRC is a design fact. A "
            "corpus scan for `crc`-like identifiers returns candidates, not "
            "an answer: a design may compute a CRC into a differently-named "
            "register, or carry an unrelated signal whose name contains crc."),
        "disposition": (
            "KEEP registered, driven explicitly. NOT_INVOCABLE under the "
            "umbrella is the correct verdict and now has a reason attached."),
    },
    "crc_seed_consistency_check": {
        "requires": "--vectors-json",
        "design_value": "--vectors-json",
        "why_no_umbrella": (
            "Consumes generated test vectors, not RTL. There is nothing in an "
            "`rtl` directory for the umbrella to point it at, so this is not a "
            "structural-RTL check that happens to be unwired — it belongs to a "
            "different input class entirely."),
        "disposition": (
            "KEEP registered, driven from the vector-generation step that "
            "produces its input."),
    },
    "protocol_gap_check": {
        "requires": "--name --end-signal --bus-idle --min-cycles --out-dir",
        "design_value": "--end-signal, --bus-idle, --min-cycles",
        "why_no_umbrella": (
            "Needs the protocol's own timing contract: which signal ends a "
            "frame, what idle looks like on that bus, and how many cycles of "
            "it the spec requires. The third is a number no scan can recover — "
            "it lives in the datasheet, not the RTL."),
        "disposition": (
            "KEEP registered, driven per-protocol from the L-layer spec that "
            "states the inter-frame gap."),
    },
    "tristate_bus_check": {
        "requires": "--bus-name --drivers --out-dir",
        "design_value": "--bus-name, --drivers",
        "why_no_umbrella": (
            "The driver set is the whole question. Enumerating it from a scan "
            "is what the check exists to verify, so deriving the argument from "
            "the same source would make the check confirm its own input."),
        "disposition": (
            "KEEP registered, driven explicitly. A discovery mode is possible "
            "but must report when enumeration was incomplete, or it recreates "
            "the silence at one remove."),
    },
}


# ---------------------------------------------------------------------------
# #496 — WHY EACH ZERO-DENOMINATOR GATE IS STILL REGISTERED AND STILL UNWIRED.
#
# #492 disqualified eight gates for reporting an empty (or unstated)
# denominator and left the question open: if a gate has nothing to examine
# ANYWHERE in the corpus, on what basis is it a structural gate?  That cannot
# be answered from an exit code, so each trigger condition was taken back to
# the 107 tracked `rtl` directories with a probe deliberately LOOSER than the
# gate's own.  Three answers came back, and they are not interchangeable:
#
#   TRIGGER_ABSENT      the condition genuinely does not occur here. Keep the
#                       gate; its PASS must read as "examined 0".
#   EXTRACTION_BROKEN   the condition DOES occur and the gate cannot see it.
#                       A real bug wearing permanent cleanliness as a disguise.
#   ADVISORY_ONLY       structurally incapable of returning non-zero, so it is
#                       a report, not a gate.
#
# NOTHING here is wired into the umbrella by #496, and two of the entries are
# now specifically MORE dangerous to wire than before, because repairing their
# extraction gave them real findings: `bit_count_modulo_check` now FAILs on
# hdlc, for a defect confirmed by reading the RTL.  #492's bar (no new FAIL AND
# a non-empty denominator) is unchanged and still governs; this table records
# what a future conversion attempt has to answer, so it re-derives the
# measurement instead of assuming it.  Asserted by
# `tests/test_issue496_zero_denominator_gates.py`.
# ---------------------------------------------------------------------------
_ZERO_DENOMINATOR_CLASSIFICATION: Dict[str, Dict[str, str]] = {
    "otp_write_lock_gate_check": {
        "verdict": "TRIGGER_ABSENT",
        "gate_denominator": "write_enable_sites: 0 on 107/107",
        "corpus_probe": (
            "A probe with no line-shape, no `1'b1` requirement and no "
            "assignment requirement — any identifier matching "
            "(otp|fuse|efuse|nvm|mtp|eeprom|flash|nvram|ee)\\w*_?"
            "(we|wen|wr_en|write_en|prog|pgm|pwe|program)\\w* anywhere in any "
            "file — returns 0 hits in 0/107 directories. No corpus design has "
            "a non-volatile memory write path of any kind."),
        "disposition": (
            "KEEP, unwired. Valid rule, no coverage here. Its PASS now "
            "discloses `examined 0` with the reason, so it cannot be read as "
            "'no unguarded non-volatile write was found'."),
    },
    "response_payload_template_check": {
        "verdict": "TRIGGER_ABSENT + ADVISORY_ONLY",
        "gate_denominator": "total_assignments: 0 on 107/107",
        "corpus_probe": (
            "Buffer names hit in 3/107, none in a command dispatcher. A "
            "looser probe — any file with an opcode `case` AND any "
            "`<name>[<int>] <= ...` byte-indexed write, buffer name ignored — "
            "selects exactly 1 file corpus-wide, whose indexed signal is "
            "`ch_enable`, a per-channel enable vector, not a reply payload. "
            "No command/response packet handler exists here."),
        "disposition": (
            "KEEP, unwired, and recorded as ADVISORY. Every finding it can "
            "emit is severity WARN and `pass` is `not any(ERROR)`, so on any "
            "readable directory it cannot return non-zero. Registering a "
            "checker that is structurally incapable of failing is the "
            "category error; the summary now says `advisory_only: true`."),
    },
    "cmd_arg_range_validation_check": {
        "verdict": "TRIGGER_ABSENT (denominator was undisclosed, now stated)",
        "gate_denominator": (
            "disclosed nothing; measured 4/107 dispatcher files, of which "
            "0/107 reach the rule body"),
        "corpus_probe": (
            "The 4 dispatchers are ibex_decoder.sv, aes_ctrl_reg_shadowed.sv, "
            "serv_rv32i_core.v and an eSPI chip_top.v — instruction decoders "
            "and a register block, none of which buffers a command packet. "
            "The rule needs a command buffer AND a range-checkable argument "
            "in the same file; the command-buffer half is absent from all 4."),
        "disposition": (
            "KEEP, unwired. Note that `dispatcher_files` is non-zero and is "
            "NOT the denominator: publishing it as one would have overstated "
            "coverage 4-to-0. The disclosed denominator is the count of files "
            "the truncation rule was applied to."),
    },
    "transient_signal_latch_check": {
        "verdict": "TRIGGER_ABSENT (denominator was undisclosed, now stated)",
        "gate_denominator": (
            "disclosed nothing; measured 303 files read, 18 transient "
            "producers in 2/107, and 0/107 cross-file consumer reads"),
        "corpus_probe": (
            "The rule only evaluates a producer/consumer pair in DIFFERENT "
            "files (`if cf == prod_file: continue`). subservient has 17 "
            "transient producers and zero cross-file reads of them, so the "
            "rule never runs. `files_scanned` is non-zero on 107/107 and "
            "would read as full coverage; it is disclosed as detail, not as "
            "the denominator."),
        "disposition": (
            "KEEP, unwired. This gate was grouped apart from the other six "
            "as 'unknowable'; measured, it belongs WITH them — the answer is "
            "a zero denominator, it simply could not be seen from a verdict "
            "line that read `PASS — 0 errors, 0 warns`."),
    },
    "tristate_self_rx_mask_check": {
        "verdict": "EXTRACTION_BROKEN",
        "gate_denominator": (
            "recorded as `inout_ports: []` on 107/107 — WRONG FIELD AND WRONG "
            "VALUE: it collects 24 inout ports across 4/107. The real "
            "denominator, `checked`, was 0 for an unprinted reason."),
        "corpus_probe": (
            "All 24 ports were dropped by an output-enable lookup that knew "
            "exactly one spelling, `<name>_oe`. The narrowness is proven by "
            "tracked repo content OUTSIDE the 107-directory window: "
            "benchmark_external/cvdp/solved_design_db/rtl/"
            "cvdp_copilot_apb_gpio_0005.sv declares `inout wire [W-1:0] "
            "gpio`, drives it through `gpio_dir`, and taps it with a bare "
            "`assign gpio_in = gpio;` — the exact raw self-RX tap this gate "
            "exists to find, and it was skipped. STATED PRECISELY: inside the "
            "107 the trigger really is absent — those 24 ports are caravel "
            "power/analog pads and LPC blackbox stubs, and after the repair "
            "they still, correctly, skip (0 examined, 0 ERROR, 0 WARNING "
            "across all 107). So this gate is BOTH: extraction that was "
            "demonstrably too narrow, over a corpus window that would not "
            "have exercised it either way."),
        "disposition": (
            "REPAIRED, still unwired. Companion discovery covers the standard "
            "spellings and every skipped port records why. Severity tracks "
            "polarity confidence: only the active-high `_oe` form keeps "
            "ERROR, because for `_oeb`/`_oen` the correct mask reverses the "
            "ternary arms and `_dir` is a config register — widening what is "
            "EXAMINED must not silently widen what is FAILED."),
    },
    "pulse_decoder_edge_check": {
        "verdict": "EXTRACTION_BROKEN (two bugs that concealed each other)",
        "gate_denominator": "files_checked: 0 on 107/107",
        "corpus_probe": (
            "benchmark-data/evaluation/phase1_parity/sent/phase2/stage1/rtl/"
            "sent_rx.v is a SENT (SAE J2716) receiver — a multi-bucket "
            "pulse-period classifier, exactly this gate's subject. Bug 1: the "
            "selector required the literal token `low_cnt`; SENT spells it "
            "`period_cnt` / `last_period` / `ticks_meas`. Bug 2: the "
            "edge-detector recognizer only matched RISING idioms with the "
            "negation on the SECOND operand, so SENT's "
            "`wire falling = (~sin_s) & sin_s_d;` was invisible — fixing Bug "
            "1 alone would have produced a confident false NO_EDGE_DETECTOR "
            "against a design whose detector is on line 111."),
        "disposition": (
            "REPAIRED (both halves), still unwired. Measured after the "
            "repair: selection 0 -> 1/107, that one being SENT, and 0 new "
            "FAILs. Mutation control: replacing SENT's edge detector with a "
            "level test makes the gate FAIL."),
    },
    "bit_count_modulo_check": {
        "verdict": "EXTRACTION_BROKEN — was concealing a real RTL defect",
        "gate_denominator": "checked: 0 on 107/107",
        "corpus_probe": (
            "The gate's own bit-counter regex matches 125 times across 6/107; "
            "all were dropped by a symbol-valid conjunct enumerating five "
            "literal spellings, while the corpus receivers use `frame_valid`, "
            "`rx_char_valid`, `rx_bit_valid`, `rd_valid`, `left_valid`. "
            "hdlc_core.v asserts `frame_valid <= 1'b1` and computes `fcs_ok` "
            "at the closing flag with no `rx_bit_cnt == 0` test — its only "
            "comparison against that counter is `== 3'd7`, the octet-fill "
            "boundary. A frame ending mid-octet is accepted with its residual "
            "bits discarded, which ISO/IEC 13239 requires to be rejected."),
        "disposition": (
            "REPAIRED, EMPHATICALLY still unwired. Selection 0 -> 2/107 and "
            "the verdict changes on one: hdlc now FAILs, correctly. That is a "
            "NEW FAIL over the corpus, so #492's bar now excludes this gate "
            "for a second and better reason than before. Wiring it is a "
            "decision about the hdlc defect, not about the gate."),
    },
    "l12_sequence_implementation_check": {
        "verdict": "EXTRACTION_BROKEN (cannot reach its own input)",
        "gate_denominator": "sequences_checked: 0 on 107/107",
        "corpus_probe": (
            "Not absence: `--l12-json` is optional, the umbrella does not "
            "supply it, and the gate cannot discover the file from an RTL "
            "directory. 105 of the 106 project trees holding a tracked rtl/ "
            "directory ship a reachable L12 document; supplying it lifts "
            "`sequences_checked` above zero in 7 of them, and on those 7 the "
            "gate emits 3-4 ERROR findings each rather than passing."),
        "disposition": (
            "DISCLOSURE ONLY — the plumbing is deliberately NOT connected. "
            "Every one of those findings inspected is NO_IMPL_MODULE against "
            "a MONOLITHIC design (the eSPI project implements all three "
            "declared sequences inside one chip_top.v, which the rule reads "
            "as three missing modules because it matches sequence ids against "
            "file basenames). Handing it its input before fixing that rule "
            "would convert a silent gate into a loud wrong one. The zero now "
            "names the missing --l12-json as its cause."),
    },
}


# ---------------------------------------------------------------------------
# vibe-ic#559 (round 6) — THE LAST-12 UNDECIDED SILENCES, NOW MEASURED.
#
# `p0_gate_invocability_drift_check` split the un-invocable gates into
# `licensed_silence` (a recorded decision exists) and `undecided_silence`
# (measured to reject the umbrella's argv, but nobody had decided WHY). At
# v1.9.8 the undecided pile stood at 12 — every one of them classified by the
# drift check as a `wiring_gap` (the umbrella supplies the flags they name), so
# each looked mechanically fixable. It is not: a gate that "wants only --rtl-dir"
# still has to clear #492's two bars (0 new FAIL AND a non-empty *decidable*
# denominator over the corpus) before wiring is honest, and none of these 12
# clears them. Each row below is the MEASUREMENT that decides it, driven with the
# umbrella's own `_structural_gate_argv` over the 107 tracked `rtl` dirs (and, for
# the L9 gate, over the 196 tracked L9 docs) on a scratch MIRROR — never the
# tracked tree. This table is what turns "nobody looked" into "looked, measured,
# decided", which is the whole point of the licensed/undecided split; the drift
# check unions it into `_licensed_gates()` so the undecided count reaches 0 and
# `undecided_silence > 0` can finally become a HARD ERROR rather than a report.
#
# `category` is one of:
#   reddens-corpus          wiring adds >=1 new FAIL over the corpus (#492 bar 1)
#   zero-decidable-denom    0 new FAIL but the subject it decides is empty (bar 2)
#   cross-layer-contract    reddens 100% on a schema question that must be settled
#   semantic-design-value   needs a value that is a fact ABOUT THE DESIGN
#   later-flow-artifact     needs an input a LATER flow step produces
#   post-gate-policy         reads the reports the rest of the flow emits
#   utility-caller-supplied a library invoked by a caller with its own argument
#   plugin-governance       audits a non-project governance artifact
# Asserted by `tests/test_issue559_undecided_silence_last12.py`.
# ---------------------------------------------------------------------------
_UNDRIVABLE_BY_STRUCTURAL_UMBRELLA: Dict[str, Dict[str, str]] = {
    "interface_encoding_audit": {
        "category": "zero-decidable-denom",
        "requires": "--rtl-dir --top-module --out-dir (all umbrella-suppliable)",
        "measured": (
            "Umbrella argv over 107 tracked rtl dirs: 0 new FAIL, but the "
            "decidable denominator (matches+mismatches) is 0. On opentitan_aes "
            "all 21 module-boundary crossings resolve to encoding=UNKNOWN "
            "('encoding could not be determined'): total_interfaces=21, "
            "matches=0, mismatches=0. It discloses a non-zero interface count "
            "while its actual subject — gray-vs-binary mismatches it can DECIDE "
            "— is empty, so a PASS certifies a comparison that examined nothing."),
        "disposition": (
            "KEEP registered, unwired. Its decidable denominator must become "
            "non-empty (encoding inference improved beyond UNKNOWN) before it "
            "is a gate rather than a report."),
    },
    "module_port_audit": {
        "category": "zero-decidable-denom",
        "requires": "--rtl-dir --top-module --out-dir (all umbrella-suppliable)",
        "measured": (
            "SUPERSEDED by measurement. This entry recorded rc=1 on 7/107 as a "
            "blackbox/external-stub false-positive class. That diagnosis was "
            "wrong, and `Available ports: []` was the tell: not a stub the scan "
            "cannot see, but a header the parser truncated to ZERO ports. Five "
            "parse shapes, fixed in v1.9.10 — width bound to the net type, an "
            "`ifdef` inside the port list, an import on the module line (the "
            "`Available ports: []` case, 81 corpus files), multi-dimensional "
            "packed ranges, and a single-index select called 1 bit "
            "unconditionally. Re-measured over the SAME 101 directories, the "
            "pre-fix arm from `git show origin/main:` rather than by editing "
            "the tree: rc=1 8 -> 0, ERROR findings 715 -> 0, and 0/101 with "
            "the umbrella's own argv too. Proven not to be an accept-everything "
            "parser: renaming the declaration of the now-visible "
            "`aes_sub_bytes.data_i` in a COPY of the corpus takes it back to "
            "rc=1 on exactly that port. #492 bar 1 (no new FAIL) is CLEARED, "
            "and so is bar 3 (it can still fail for the reason it exists).\n"
            "What is NOT cleared is an honest denominator. `Parsed N modules` "
            "is 1 on many CVDP directories, where there is no instantiation to "
            "compare against a declaration — the gate's actual subject — so a "
            "PASS there certifies nothing. Same shape as "
            "`interface_encoding_audit` above."),
        "disposition": (
            "KEEP registered, unwired — but for the denominator, NOT for the "
            "corpus. Wiring needs the report to publish the number of "
            "instantiation-port comparisons it actually made, and to refuse "
            "when that is zero. See vibe-ic#559."),
    },
    "oe_pattern_check": {
        "category": "reddens-corpus",
        "requires": "--rtl-files --out-dir (both umbrella-suppliable)",
        "measured": (
            "Umbrella argv over 107 tracked rtl dirs: rc=1 on 3/107 (ahb_apb, "
            "mdio, subservient — real tristate designs it flags). On "
            "opentitan_aes it finds 0 OE signals across 96 files (trigger "
            "absent). A new FAIL over the corpus excludes it under #492's bar 1; "
            "the FAILs may well be real, which is exactly why wiring is a "
            "decision about those 3 designs, not about the gate."),
        "disposition": (
            "KEEP registered, unwired. Resolve whether the 3 FAILs are real "
            "before wiring."),
    },
    "l9_completeness_check": {
        "category": "cross-layer-contract",
        "requires": "--l9-file (umbrella-suppliable when generated_docs/L9*.json exists)",
        "measured": (
            "Umbrella argv over the 196 tracked L9 docs: rc=1 on 196/196. "
            "Cause: the gate requires a 'registers' section in L9, but phase1 "
            "emits the register map in L4, not L9, so every L9 doc lacks it "
            "(opentitan_aes L9: sections_present=3/4, MISSING_SECTION 'registers' "
            "ERROR). Wiring turns every landing red on a cross-layer schema "
            "question — does the L9 integration spec own the register map, or "
            "L4? — that must be settled first. This is the #492 docstring's own "
            "named poster child ('never examined an L9 document'); the reason it "
            "stays unexamined is now measured, not asserted."),
        "disposition": (
            "DISCLOSURE ONLY — plumbing deliberately not connected. Settle the "
            "L4/L9 register-map contract before wiring, else it is a loud wrong "
            "gate on every project."),
    },
    "cross_constant_invariant_check": {
        "category": "semantic-design-value",
        "requires": "--rtl plus --constants/--invariants/--inv",
        "measured": (
            "The ordering invariants ('A must be >= B') are a spec fact. The "
            "umbrella supplies --rtl but has no invariant set, and a scan of RTL "
            "parameters cannot recover which orderings the datasheet requires. "
            "Same undrivable class as crc_bitorder_check / protocol_gap_check."),
        "disposition": (
            "KEEP registered, driven explicitly from the L-layer spec that "
            "states the timing/protocol ordering invariant."),
    },
    "tester_oracle_health_check": {
        "category": "semantic-design-value",
        "requires": "--config (oracle.json)",
        "measured": (
            "Needs a design-specific tester-oracle config (burn target + "
            "bytewise oracle) describing a protocol tester. A pure-digital "
            "design like opentitan_aes ships none, and the config's contents are "
            "a design fact no generic umbrella can synthesise."),
        "disposition": (
            "KEEP registered, driven from the tester/oracle step that produces "
            "oracle.json."),
    },
    "fpga_qsf_lint": {
        "category": "later-flow-artifact",
        "requires": "--qsf-file --rtl-dir",
        "measured": (
            "Needs a Quartus .qsf, which is an FPGA-compile OUTPUT. At the RTL "
            "structural stage no .qsf exists in any of the 107 tracked rtl dirs, "
            "so the umbrella has nothing to point --qsf-file at."),
        "disposition": (
            "KEEP registered, driven from the FPGA-compile step that emits the "
            ".qsf."),
    },
    "fresh_agent_provenance_check": {
        "category": "later-flow-artifact",
        "requires": "rtl_dir reference_dir (positional)",
        "measured": (
            "Compares generated RTL against a plugin reference-template library. "
            "No 'references/' directory ships at a discoverable path in the "
            "plugin tree (find -type d -name references over the plugin returns "
            "nothing), so the umbrella cannot supply reference_dir; under the "
            "bare argv the gate argparse-rejects (rc=2)."),
        "disposition": (
            "KEEP registered, driven from the rtl-gen step that knows its "
            "reference-template directory."),
    },
    "warn_acceptance_policy_check": {
        "category": "post-gate-policy",
        "requires": "--project-dir --reports-dir",
        "measured": (
            "Reads the reports/ that the REST of the flow produces, to enforce "
            "that every WARN finding is addressed. Running it INSIDE the "
            "structural-RTL umbrella — before those downstream reports exist — "
            "is a stage inversion: it has no reports to read at P0."),
        "disposition": (
            "KEEP registered, driven at the final acceptance gate, after the "
            "report-producing steps have run."),
    },
    "output_artifact_check": {
        "category": "utility-caller-supplied",
        "requires": "--artifacts/--pattern --base-dir",
        "measured": (
            "Verifies that artifacts a caller CLAIMED to produce exist on disk. "
            "With no claim it has no subject; it is a library the "
            "artifact-producing steps call with their own --pattern, not a "
            "standalone per-project structural gate."),
        "disposition": (
            "KEEP registered, driven by the step that makes the artifact "
            "claim."),
    },
    "json_schema_check": {
        "category": "utility-caller-supplied",
        "requires": "--json-file --required-keys",
        "measured": (
            "A generic JSON-key checker; without a --json-file AND a "
            "--required-keys schema it has nothing to check. It is invoked by "
            "specific L-doc validators with their own schema, not standalone."),
        "disposition": (
            "KEEP registered, driven by the L-doc validators that supply the "
            "schema."),
    },
    "backlog_sanitize_check": {
        "category": "plugin-governance",
        "requires": "--file/--dir (a backlog YAML)",
        "measured": (
            "Validates that a community-backlog YAML submission is IC-agnostic "
            "and carries no vendor/confidential data. A design project ships no "
            "backlog YAML; its input class is a governance artifact, not project "
            "RTL/docs."),
        "disposition": (
            "KEEP registered, driven at backlog-submission time, not per "
            "project."),
    },

    # -----------------------------------------------------------------------
    # vibe-ic#559 (round 7) — THE FOUR THE RATCHET COULD NOT SEE.
    #
    # Everything above was found by `p0_gate_invocability_drift_check`, whose
    # discriminator was `rc == 2 and "usage:" in stderr` — `_gate_invocation`'s
    # RULE A, and only Rule A. The umbrella has always classified with
    # `classify_not_invocable`, which is Rule A **plus** RULE B: a gate that
    # hand-rolls its own required-argument check never reaches argparse, so no
    # `usage:` block is ever printed. Measured at v1.9.74 over the 246
    # registered gates, both arms driven from `_structural_gate_argv` against
    # the same empty probe: the umbrella 36, the ratchet 32.
    #
    # These four are that gap. They are NOT new silences — `_gate_invocation`'s
    # own docstring has named them as the Rule-B-only four since #492 — they are
    # four silences no PROGRAM could see, so they were neither licensed nor
    # flagged. They are recorded here rather than in `_SEMANTIC_ARGV_UNDRIVABLE`
    # because that table's re-derivation test asserts `usage:` on stderr, i.e.
    # it is a Rule-A-only table by construction and cannot hold a Rule-B gate.
    #
    # Each row below is measured against the same corpus as the twelve above.
    # -----------------------------------------------------------------------
    "mask_application_check": {
        "category": "semantic-design-value",
        "requires": "--masks/--mask (a spec's AND-mask table)",
        "measured": (
            "Rule B: exits 2 with its own `error: no masks supplied (--masks or "
            "--mask)`, no argparse usage block, on the umbrella's own argv. Its "
            "parser takes exactly `rtl` (positional), `--masks`, `--mask` and "
            "`--json` (mask_application_check.py:188-192), so unlike "
            "`payload_bit_position_check` below there is no project-artifact "
            "route to measure at all: the only input path is a caller-supplied "
            "value. That value is a list of {signal, and_mask} pairs — which "
            "RTL signal the spec masks and with what constant. Both halves are "
            "spec facts; a scan for `& 8'hXX` returns the masks the RTL DOES "
            "apply, which is the thing the gate exists to check, so deriving "
            "the argument from the RTL would make the check confirm its own "
            "input."),
        "disposition": (
            "KEEP registered, driven explicitly from the L-layer spec that "
            "declares the mask. NOT_INVOCABLE under the umbrella is the correct "
            "verdict and now has a reason a program can read."),
    },
    "periodic_signal_required_check": {
        "category": "semantic-design-value",
        "requires": "--periodic/--required (a periodic-signal manifest)",
        "measured": (
            "Rule B: exits 2 with its own `error: no required signals supplied "
            "(--periodic or --required)`, no argparse usage block, on the "
            "umbrella's own argv. Its parser takes exactly `rtl` (positional), "
            "`--periodic`, `--required` and `--json` "
            "(periodic_signal_required_check.py:182-186) — no project-artifact "
            "reader exists. The manifest is {name, period_const, output_port} "
            "per protocol-mandated periodic activity, and the gate's whole "
            "premise is that the RTL may DECLARE the period constant while no "
            "generator drives the signal. Harvesting the manifest from the RTL "
            "would therefore only ever list activities the RTL already "
            "implements, and the missing one — the defect — is invisible to "
            "exactly the scan that would build the argument."),
        "disposition": (
            "KEEP registered, driven explicitly from the L-layer spec that "
            "states the protocol's periodic obligations, not from the RTL that "
            "is under test."),
    },
    "payload_bit_position_check": {
        "category": "cross-layer-contract",
        "requires": "--bitmap, or --layer-l3/--layer-l4 (umbrella-suppliable)",
        "measured": (
            "Rule B: exits 2 with its own `error: empty bitmap (give --bitmap "
            "or --layer-l3/--layer-l4)`, no argparse usage block. Unlike the "
            "two above it DOES have an umbrella-suppliable route — the corpus "
            "ships 107 L3 and 107 L4 documents — so it was driven with them "
            "rather than judged. Denominator rule stated so it can be "
            "reproduced: the 107 distinct `<...>/rtl` prefixes of `git "
            "ls-files` paths containing `/rtl/`. Of those, 36 have a reachable "
            "phase1/generated_docs/L3_CMD_PROTOCOL.json; driven with "
            "--layer-l3 and --layer-l4 supplied: rc=2 on 36/36 and "
            "`checked_pairs` 0 on 36/36. Wiring it would not even stop it being "
            "NOT_INVOCABLE. Cause, not symptom: `_load_bitmap_from_layer` "
            "(payload_bit_position_check.py:80-88) reads a top-level "
            "`bit_layouts` object, and 0 of 108 L3 documents and 0 of 108 L4 "
            "documents under benchmark-data carry that key — phase1 emits "
            "`opcodes` and `payload_semantics`, never a byte->bit->signal map."),
        "disposition": (
            "KEEP registered, unwired. This is a schema question before it is a "
            "wiring question: which L-layer document owns the payload bitmap, "
            "and in what shape. Settle that and the wiring is one adapter row; "
            "wiring it first supplies a file that cannot answer the gate."),
    },
    "fpga_async_input_synchronizer_check": {
        "category": "later-flow-artifact",
        "requires": "--top or --qsf (an FPGA top-level entity)",
        "measured": (
            "Rule B: exits 2 with its own `error: top module not resolved (give "
            "--top or --qsf)` at fpga_async_input_synchronizer_check.py:265-268, "
            "no argparse usage block. `--qsf` is a Quartus settings file, an "
            "FPGA-compile artefact: exactly ONE .qsf is tracked in the whole "
            "repo (a phase2/stage1/fpga/ output), and 0 of the 107 tracked rtl "
            "directories holds one — the same measurement already recorded for "
            "its twin `fpga_qsf_lint` above, which the ratchet COULD see. "
            "`--top` is the other route and the umbrella has no top-module to "
            "give: `_structural_gate_argv` takes a gate name, a project, an rtl "
            "dir and a strict-timing flag, and computes no top. "
            "UMBRELLA_SUPPLIABLE lists --top-module aspirationally; nothing "
            "produces one at the structural stage."),
        "disposition": (
            "KEEP registered, driven from the FPGA-compile step that emits the "
            ".qsf — identical disposition to `fpga_qsf_lint`. Recording it "
            "beside its twin is the point: one of the pair was licensed and the "
            "other was invisible, for no reason but the discriminator."),
    },
}


#: How long a P0 structural gate may show NO forward progress at all — no
#: output, no CPU, no I/O anywhere in its process tree — before the umbrella
#: calls it hung. This is an IDLE tolerance, not a runtime budget: a gate that
#: is still moving is never killed, however long it legitimately takes.
_P0_GATE_STALL_GRACE_S = 60.0


def _p0_contract_json(path: Optional[Path]) -> tuple[Dict[str, Any], str]:
    """Read one declared L-doc and retain absent vs malformed provenance.

    Only an absent/valid declaration can support derived N/A.  A file that is
    present but malformed must stay live so its checker can report the defect;
    treating parse failure as absence would turn broken evidence into N/A.
    """
    if path is None or not path.is_file():
        return {}, "absent"
    try:
        value = json.loads(path.read_text(errors="replace"))
    except Exception:
        return {}, "malformed"
    return (value, "valid") if isinstance(value, dict) else ({}, "malformed")


def _p0_contract_doc(project: Path, prefix: str) -> Optional[Path]:
    gd = _pl.generated_docs_dir(project)
    if not gd.is_dir():
        gd = project / "generated_docs"
    matches = sorted(gd.glob(f"{prefix}*.json")) if gd.is_dir() else []
    return matches[0] if matches else None


def _p0_declared_path(project: Path, value: Any) -> Optional[Path]:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value)
    return path if path.is_absolute() else project / path


def _p0_contract_context(project: Path,
                         rtl_dir: Path) -> Dict[str, Any]:
    """Design-declared inputs available to exceptional gate contracts.

    Semantic values come only from generated L-docs or explicit project
    artefacts.  RTL supplies the implementation under test and file/topology
    paths; it is never mined to invent the spec expectation being checked.
    """
    l3_path = _p0_contract_doc(project, "L3_")
    l4_path = _p0_contract_doc(project, "L4_")
    l9_path = _p0_contract_doc(project, "L9_")
    l12_path = _p0_contract_doc(project, "L12_")
    l3, l3_state = _p0_contract_json(l3_path)
    l4, l4_state = _p0_contract_json(l4_path)
    l9, l9_state = _p0_contract_json(l9_path)
    l12, l12_state = _p0_contract_json(l12_path)

    crc = l3.get("crc_parameters")
    crc = crc if isinstance(crc, dict) else {}
    gap = l3.get("protocol_gap")
    gap = gap if isinstance(gap, dict) else {}
    otp_layout = l4.get("otp_layout")
    otp_layout = otp_layout if isinstance(otp_layout, dict) else {}
    masks = otp_layout.get("mask_sources")
    masks = masks if isinstance(masks, list) else []
    periodic = l12.get("periodic_signals")
    periodic = periodic if isinstance(periodic, list) else []
    invariants = l12.get("constant_invariants")
    invariants = invariants if isinstance(invariants, list) else []
    l12_sequences = next((l12.get(key) for key in (
        "sequences", "behavioral_sequences", "behavioural_sequences",
        "protocol_sequences", "transaction_sequences", "flows",
        "scenarios", "test_sequences")
        if isinstance(l12.get(key), list) and l12.get(key)), [])

    interfaces = l9.get("interfaces")
    interfaces = interfaces if isinstance(interfaces, list) else []
    l9_registers = next((l9.get(key) for key in (
        "registers", "regs", "reg_map", "register_map",
        "register_infrastructure")
        if isinstance(l9.get(key), (list, dict)) and l9.get(key)), None)
    tristate = next((v for v in interfaces
                     if isinstance(v, dict)
                     and str(v.get("direction", "")).lower() == "inout"
                     and isinstance(v.get("drivers"), list)
                     and v.get("drivers")), {})

    top = l9.get("top_module")
    if isinstance(top, dict):
        top = top.get("name")
    top = top if isinstance(top, str) and top.strip() else None

    vectors = _p0_declared_path(project, crc.get("vectors_json"))
    qsf = next(iter(sorted(project.rglob("*.qsf"))), None)
    reference_dir = next((p for p in (
        project / "references",
        project / "phase2" / "stage1" / "references",
    ) if p.is_dir()), None)
    backlog_dir = next((p for p in (
        project / "community" / "backlogs",
        project / "backlogs",
    ) if p.is_dir()), None)
    tester_config = next((p for p in (
        project / "reports" / "tester_oracle.json",
        project / "oracle.json",
        project / "reports" / "oracle.json",
    ) if p.is_file()), None)
    scope_samples = next((p for p in (
        project / "scope_samples.csv",
        project / "reports" / "scope_samples.csv",
    ) if p.is_file()), None)

    return {
        "rtl_files": tuple(sorted(
            list(rtl_dir.rglob("*.v")) + list(rtl_dir.rglob("*.sv")))),
        "l3_path": l3_path,
        "l3_state": l3_state,
        "l3_opcodes": l3.get("opcodes")
        if isinstance(l3.get("opcodes"), list) else [],
        "l4_path": l4_path,
        "l4_state": l4_state,
        "l9_path": l9_path,
        "l9_state": l9_state,
        "l9_registers": l9_registers,
        "l12_path": l12_path,
        "l12_state": l12_state,
        "l12_sequences": l12_sequences,
        "crc_signal": crc.get("signal"),
        "crc_vectors": vectors,
        "protocol_gap": gap,
        "masks": masks,
        "periodic": periodic,
        "invariants": invariants,
        "payload_bitmap": l3.get("bit_layouts"),
        "top_module": top,
        "tristate": tristate,
        "qsf": qsf,
        "reference_dir": reference_dir,
        "backlog_dir": backlog_dir,
        "tester_config": tester_config,
        "scope_samples": scope_samples,
    }


_P0_CONTRACT_REQUIRED_CONTEXT: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "backlog-dir": ("backlog_dir",),
    "crc-bitorder": ("rtl_files", "crc_signal"),
    "crc-vectors": ("crc_vectors",),
    "constant-invariants": ("invariants",),
    "fpga-top": ("top_module", "qsf"),
    "fpga-qsf": ("qsf",),
    "reference-provenance": ("reference_dir",),
    "interface-encoding": ("top_module",),
    # json_schema_check treats an explicitly-empty `opcodes` value as ERROR.
    # A no-protocol design declares that emptiness as N/A, not malformed JSON.
    "l3-schema": ("l3_path", "l3_opcodes"),
    "l12-sequences": ("l12_path", "l12_sequences"),
    # l9_completeness_check makes a non-empty register section mandatory.  The
    # canonical layer owner is often L4, so only invoke this L9-specific check
    # when the design actually declares a register section in L9.
    "l9": ("l9_path", "l9_registers"),
    "declared-masks": ("masks",),
    "rtl-files-output": ("rtl_files",),
    "payload-bitmap": ("l3_path", "payload_bitmap"),
    "periodic-signals": ("periodic",),
    "protocol-gap": ("protocol_gap",),
    "scope-samples": ("scope_samples",),
    "tester-oracle": ("tester_config",),
    "tristate-bus": ("tristate",),
})

# Gates can share the same CLI shape while asking different applicability
# questions.  Keep those feature requirements keyed by gate, not by argv kind:
# a generic RTL-dir checker must not inherit a protocol-only prerequisite.
_P0_GATE_REQUIRED_CONTEXT: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "pre_awake_silence_check": ("l3_opcodes",),
})

# Semantic declarations owned by a malformed document are not "absent".  The
# contract therefore runs with the real document path (and, where necessary,
# inert argv placeholders) so the gate can return a substantive parse/schema
# verdict instead of the umbrella manufacturing N/A.
_P0_CONTEXT_DOCUMENT_STATE: Mapping[str, str] = MappingProxyType({
    "crc_signal": "l3_state",
    "crc_vectors": "l3_state",
    "l3_opcodes": "l3_state",
    "payload_bitmap": "l3_state",
    "protocol_gap": "l3_state",
    "masks": "l4_state",
    "l9_registers": "l9_state",
    "top_module": "l9_state",
    "tristate": "l9_state",
    "invariants": "l12_state",
    "l12_sequences": "l12_state",
    "periodic": "l12_state",
})


def _p0_contract_na_reason(gate_name: str,
                           project: Path,
                           rtl_dir: Path) -> Optional[str]:
    """Why a declared contract is N/A before invocation, or ``None``.

    This is the allowed disposition-predicate arm from #1968.  It is narrow:
    only an explicitly-required declaration missing from the design roster can
    suppress invocation.  Path-only and no-argument contracts still run on a
    non-protocol design; unknown/default contracts run fail-closed.
    """
    kind = _STRUCTURAL_GATE_INVOCATION_CONTRACTS.get(gate_name)
    if kind is None:
        return None
    ctx = _p0_contract_context(project, rtl_dir)
    required = (*_P0_CONTRACT_REQUIRED_CONTEXT.get(kind, ()),
                *_P0_GATE_REQUIRED_CONTEXT.get(gate_name, ()))
    missing = []
    for name in required:
        if ctx.get(name):
            continue
        state_key = _P0_CONTEXT_DOCUMENT_STATE.get(name)
        if state_key and ctx.get(state_key) == "malformed":
            return None
        missing.append(name)
    if not missing:
        return None
    return (
        f"N/A from the design declaration roster: {gate_name} declares "
        f"invocation_contract={kind!r}, but the required declaration(s) "
        f"{', '.join(missing)} are absent. The gate was not given fabricated "
        f"placeholder arguments; a project that declares them keeps the gate "
        f"live.")


def _p0_contract_argv(gate_name: str,
                      project: Path,
                      rtl_dir: Path,
                      scratch_dir: Path) -> List[str]:
    """Expand one closed invocation contract into an argv list."""
    prog = PROGRAMS_DIR / f"{gate_name}.py"
    base = [sys.executable, str(prog)]
    kind = _STRUCTURAL_GATE_INVOCATION_CONTRACTS[gate_name]
    ctx = _p0_contract_context(project, rtl_dir)
    out = scratch_dir / gate_name
    rtl_files = [str(p) for p in ctx["rtl_files"]] or [str(rtl_dir / "missing.v")]

    if kind == "no-args":
        return base
    if kind == "rtl-dir":
        return base + ["--rtl-dir", str(rtl_dir)]
    if kind == "backlog-dir":
        return base + ["--dir", str(ctx.get("backlog_dir") or project / "backlogs")]
    if kind == "crc-bitorder":
        return base + ["--rtl-files", *rtl_files,
                       "--crc-signal", str(ctx.get("crc_signal") or "missing_crc"),
                       "--out-dir", str(out)]
    if kind == "crc-vectors":
        return base + ["--vectors-json", str(
            ctx.get("crc_vectors") or project / "missing_crc_vectors.json")]
    if kind == "constant-invariants":
        argv = base + ["--rtl", str(rtl_dir)]
        for inv in ctx.get("invariants") or []:
            if not isinstance(inv, dict):
                continue
            lhs = inv.get("lhs", inv.get("left"))
            rhs = inv.get("rhs", inv.get("right"))
            op = inv.get("op")
            if lhs and rhs and op:
                argv += ["--inv", f"{lhs} {op} {rhs}"]
        return argv
    if kind == "fpga-top":
        return base + [str(rtl_dir), "--top",
                       str(ctx.get("top_module") or "missing_top"),
                       "--qsf", str(ctx.get("qsf") or project / "missing.qsf")]
    if kind == "fpga-qsf":
        return base + ["--qsf-file", str(ctx.get("qsf") or project / "missing.qsf"),
                       "--rtl-dir", str(rtl_dir), "--out-dir", str(out)]
    if kind == "reference-provenance":
        return base + [str(rtl_dir), str(
            ctx.get("reference_dir") or project / "missing-references")]
    if kind == "interface-encoding":
        return base + ["--rtl-dir", str(rtl_dir), "--top-module",
                       str(ctx.get("top_module") or "missing_top"),
                       "--out-dir", str(out)]
    if kind == "l3-schema":
        return base + ["--json-file", str(
            ctx.get("l3_path") or project / "missing_l3.json"),
                       "--required-keys", "schema_version,doc_class,opcodes"]
    if kind == "l12-sequences":
        return base + ["--rtl-dir", str(rtl_dir), "--l12-json", str(
            ctx.get("l12_path") or project / "missing_l12.json")]
    if kind == "rtl-precheck":
        argv = base + ["--rtl-dir", str(rtl_dir)]
        if ctx.get("l12_path"):
            argv += ["--l12-json", str(ctx["l12_path"])]
        return argv
    if kind == "l9":
        return base + ["--l9-file", str(
            ctx.get("l9_path") or project / "missing_l9.json")]
    if kind == "declared-masks":
        argv = base + [str(rtl_dir)]
        for item in ctx.get("masks") or []:
            if isinstance(item, dict) and item.get("signal") and item.get("and_mask"):
                argv += ["--mask", f"{item['signal']} AND {item['and_mask']}"]
        return argv
    if kind == "module-ports":
        return base + ["--rtl-dir", str(rtl_dir)]
    if kind == "rtl-files-output":
        return base + ["--rtl-files", *rtl_files, "--out-dir", str(out)]
    if kind == "rtl-artifacts":
        return base + ["--base-dir", str(rtl_dir), "--pattern", "**/*v",
                       "--min-count", "1"]
    if kind == "testbench":
        return base + ["--rtl-dir", str(project)]
    if kind == "payload-bitmap":
        return base + [str(rtl_dir), "--layer-l3", str(
            ctx.get("l3_path") or project / "missing_l3.json")]
    if kind == "periodic-signals":
        argv = base + [str(rtl_dir)]
        for item in ctx.get("periodic") or []:
            if not isinstance(item, dict):
                continue
            if item.get("name") and item.get("period_const") and item.get("output_port"):
                argv += ["--required", (f"{item['name']}="
                                         f"{item['period_const']},"
                                         f"{item['output_port']}")]
        return argv
    if kind == "protocol-gap":
        gap = ctx.get("protocol_gap") or {}
        return base + ["--name", str(gap.get("name") or "protocol_gap"),
                       "--end-signal", str(gap.get("end_signal") or "missing_end"),
                       "--bus-idle", str(gap.get("bus_idle") or "missing_idle"),
                       "--min-cycles", str(gap.get("min_cycles") or 0),
                       "--out-dir", str(out)]
    if kind == "scope-samples":
        return base + ["--mock-samples-csv", str(
            ctx.get("scope_samples") or project / "missing_scope.csv")]
    if kind == "tester-oracle":
        return base + ["--config", str(
            ctx.get("tester_config") or project / "missing_oracle.json"),
                       "--dry-run"]
    if kind == "tristate-bus":
        bus = ctx.get("tristate") or {}
        drivers = bus.get("drivers") if isinstance(bus, dict) else []
        return base + ["--bus-name", str(bus.get("name") or "missing_bus"),
                       "--drivers", ",".join(map(str, drivers or ["missing_driver"])),
                       "--out-dir", str(out)]
    if kind == "warn-policy":
        return base + ["--project-dir", str(project), "--reports-dir",
                       str(project / "reports")]
    raise AssertionError(f"unknown structural gate invocation contract: {kind}")


def _structural_gate_argv(gate_name: str,
                          project: Path,
                          rtl_dir: Optional[Path] = None,
                          strict_timing: bool = False,
                          scratch_dir: Optional[Path] = None) -> List[str]:
    """Build the argv the P0 umbrella runs a structural gate with.

    #492 — this used to be an inline literal inside the worker, which meant a
    test could only ever re-type it, and a re-typed argv agrees with the umbrella
    by coincidence rather than by construction. It is a named function so the
    regression tests drive the SAME code the umbrella runs.
    """
    prog = PROGRAMS_DIR / f"{gate_name}.py"
    if gate_name in _STRUCTURAL_GATE_INVOCATION_CONTRACTS:
        target = rtl_dir if rtl_dir is not None else project
        # Production supplies a private TemporaryDirectory.  The fallback is
        # for read-only diagnostic callers such as the invocability ratchet,
        # whose project is itself a TemporaryDirectory.
        scratch = scratch_dir or (project / ".p0-gate-scratch")
        return _p0_contract_argv(gate_name, project, target, scratch)
    adapter = _STRUCTURAL_GATE_ARGV_ADAPTERS.get(gate_name)
    if adapter is not None:
        target = str(rtl_dir if rtl_dir is not None else project)
        argv = [sys.executable, str(prog)]
        for flag in adapter:
            argv += [flag, target]
        argv += list(_STRUCTURAL_GATE_BARE_FLAGS.get(gate_name, ()))
    else:
        # v0.118 fix: pass `project` (not `rtl_dir`) so gates can access
        # project-level artefacts (generated_docs/L*.json, waivers.json,
        # output_files/, *.qsf).
        argv = [sys.executable, str(prog), str(project)]
    # v1.6.32: forward --strict-timing to the provenance gate only.
    if strict_timing and gate_name == "provenance_output_hash_completeness_check":
        argv.append("--strict-timing")
    return argv


# ── #497 step 1: the P0 umbrella's structured per-gate payload ───────────────
#
# The outcome vocabulary, closed and enumerated. `NOT_INVOCABLE` is a VERDICT
# here, not a marker inside a message: the gate returned nothing, which is
# neither a pass, nor a failure, nor the input-missing skip that `SKIP` means.
# Merging it into `SKIP` is what made 39 registered gates read as benign (#492);
# expressing it as prose inside a `SKIP` line is what made them read as
# FAILURES at the four consumers. Adding a sixth outcome later must be a change
# to this tuple that a consumer has to handle, not a new sentence a consumer can
# ignore.
P0_GATE_VERDICTS: tuple[str, ...] = (
    "PASS", "FAIL", "SKIP", "WAIVED", "NOT_INVOCABLE", "BLOCKED",
    "INCOMPLETE")

# Outcomes that did not reach a substantive PASS/FAIL verdict.  Every one must
# carry one of `_flow_reason_taxonomy.REASON_CLASSES`; this is the population
# issue #1978 found collapsed into SKIP.  FAIL and WAIVED are decisive outcomes
# and therefore do not acquire a fabricated "why no verdict" class.
_P0_NONDECISIVE_VERDICTS = frozenset({
    "SKIP", "NOT_INVOCABLE", "BLOCKED", "INCOMPLETE",
})

#: #497 step 3 — the umbrella's ONE note about ITSELF rather than about a gate.
#:
#: When the project has no RTL the umbrella dispatches nothing and says so in a
#: single line. That line NAMES NO GATE, yet it has always worn the per-gate
#: ``SKIP: `` prefix and has always lived in the per-gate skip bucket — a
#: non-gate line sitting inside the per-gate grammar, one shape away from the
#: collision that made the #492 disclosure readable as 37 failing gates. No
#: shipped consumer mis-read it, for one reason only: every consumer of that
#: bucket is reached through a FAIL-guarded path, and a project with no RTL
#: reports SKIPPED-CONDITION.
#:
#: THE DECISION, made deliberately rather than inherited: in the record-driven
#: world this is an UMBRELLA-LEVEL NOTE, not a gate outcome. It is keyed off the
#: umbrella's own tri-state (``executed is None`` = nothing dispatched), it
#: never becomes a record, and `gate_records` stays exactly "one entry per
#: registered gate". Its RENDERING is unchanged, prefix included, because the
#: operator-facing listing is a contract this migration does not get to alter
#: on the way past — and once the parsers are gone (step 4) the prefix
#: collision is inert: it exists only in text nothing reads.
_P0_NO_RTL_NOTE = ("no RTL directory found — structural gates skipped "
                   "(analog track / pre-RTL)")


def _p0_gate_record(name: str,
                    verdict: str,
                    message: str = "",
                    evidence: Optional[Dict[str, Any]] = None,
                    reason_class: Optional[str] = None,
                    ) -> Dict[str, Any]:
    """One registered structural gate's outcome, stated once.

    Built at the point where the outcome is DECIDED — beside the exit-code
    branch, the class-skip branch, the waiver branch — so no later reader has
    to recover it from the sentence some earlier branch wrote. That recovery is
    the whole subject of #497.

    ``message`` is the callee's own first line where the callee produced one
    (a FAIL's first output line, the classifier's account of why an rc-2 was an
    invocation defect), and the umbrella's own reason where the gate never ran
    (class-not-applicable, analog deferred, no backing program). ``evidence``
    is the machine-readable remainder: exit code, skip kind, waiver ticket.
    """
    assert verdict in P0_GATE_VERDICTS, verdict  # closed enum, not free text
    ev = dict(evidence or {})
    if verdict in _P0_NONDECISIVE_VERDICTS:
        reason_class = _reason_taxonomy.infer_nonverdict_reason(
            verdict=verdict, message=message, evidence=ev,
            explicit=reason_class)
        assert reason_class in _reason_taxonomy.REASON_CLASS_SET
        if verdict != "NOT_INVOCABLE":
            # Enforce the class/verdict pairing at the record boundary.  A
            # caller cannot label an execution error SKIP and rely on the
            # roll-up to notice the contradiction later.
            verdict = _reason_taxonomy.record_verdict(reason_class)
    else:
        reason_class = _reason_taxonomy.normalise(reason_class)
    return {
        "name": name,
        "verdict": verdict,
        "reason_class": reason_class,
        "message": message,
        "evidence": ev,
    }


@functools.lru_cache(maxsize=1)
def _two_source_advisory_gates() -> frozenset:
    """Structural gates that BOTH their own module AND the flow call advisory.

    Membership needs TWO independent declarations to agree:

      1. the gate module's own docstring carries ``ENFORCEMENT: advisory``
      2. the canonical flow wires it under ``advisory_program_exit_zero``
         (and never under the blocking ``program_exit_zero``)

    Neither is this function's opinion; it reads what the gate and the flow
    already say. A gate that declares blocking, or that the flow wires
    blocking, is untouched no matter what the other source says -- the
    conservative direction, because a disagreement should be resolved by an
    author, not silently downgraded.

    MEASURED, and the reason this exists: `_STRUCTURAL_RTL_GATES` is a
    hand-maintained tuple whose comment still asserts its L4/L5/L6 members
    "All three BLOCK (see their docstrings)". That stopped being true for the
    L6 member when vibe-ic#1035 reconciled it to `ENFORCEMENT: advisory` --
    the gate's docstring and the flow row were both updated and this tuple was
    not. Its own blast-radius measurement records 41 of 107 published roots red
    from ONE broken producer (the L6 prose-walker emits `transitions: []` every
    time), which is precisely why it is advisory; enforcing it here failed a
    design whose input documents legitimately delegate microarchitecture.
    """
    return frozenset(g for g in _STRUCTURAL_RTL_GATES
                     if _gate_is_two_source_advisory(g))


@functools.lru_cache(maxsize=512)
def _gate_is_two_source_advisory(gate: str) -> bool:
    """True when the gate module AND the flow row BOTH declare it advisory."""
    if not gate or not re.fullmatch(r"[A-Za-z0-9_]+", gate):
        return False
    mod = Path(__file__).resolve().parent / f"{gate}.py"
    try:
        text = mod.read_text(errors="replace")
    except OSError:
        return False
    # The declaration must be the MODULE'S OWN docstring, not any occurrence
    # in the file: prose that merely DISCUSSES the convention (this module
    # does, a few hundred lines up) must not be mistaken for a module
    # declaring itself advisory. Parsed, never grepped.
    try:
        doc = ast.get_docstring(ast.parse(text)) or ""
    except (SyntaxError, ValueError):
        return False
    if not re.search(r"(?m)^ *ENFORCEMENT: *advis", doc):
        return False
    try:
        flow_text = _canonical_flow_text()
    except Exception:
        return False
    adv = re.search(r'advisory_program_exit_zero:\s*\n\s*command: "'
                    + re.escape(gate) + r'\b', flow_text)
    blocking = re.search(r'(?<!advisory_)program_exit_zero:\s*\n\s*command: "'
                         + re.escape(gate) + r'\b', flow_text)
    return bool(adv and not blocking)


def _canonical_flow_text() -> str:
    """The canonical flow YAML as text (path only, never parsed here)."""
    here = Path(__file__).resolve().parent
    return (here.parent / "flow" / "phase1_phase2_phase3.yaml").read_text(
        errors="replace")


def _p0_waiver_record(waiver: Dict[str, Any]) -> Dict[str, Any]:
    """The record for a gate whose FAIL was converted to a deferred waiver.

    Takes the waiver entry the umbrella already builds, so the record cannot
    name a different gate, ticket or first line than the waiver it stands for.
    """
    return _p0_gate_record(
        waiver["gate"], "WAIVED", waiver.get("first_line", ""),
        {"ticket": waiver.get("ticket"),
         "review_required": bool(waiver.get("review_required")),
         "reason": waiver.get("reason", ""),
         "detail": waiver.get("evidence", "")})


# ── #497 step 2: the projections that replace the four prose scrapers ────────
#
# Each function below answers, from the records alone, a question that used to
# be answered by re-deriving the umbrella's prose grammar from line prefixes.
# They are DERIVATIONS, not parsers: none of them looks at a character the
# umbrella wrote for a human, so a seventh line shape cannot change what any of
# them returns.
#
# MEASURED EQUIVALENT before the cut-over, on 27 real runs of the real CLI at
# one fixed project path and one fixed program path — 4 real benchmark projects
# plus 3 synthetic ones, 27 flag/registry combinations, covering P0 = FAIL /
# PASS / SKIPPED-CONDITION and all six reason shapes. Every field the four
# consumers PUBLISH (audit `gates`, `failed_gates`, `failed_gate_count`,
# `passed_gate_count`, `structural_fail_lines`, and both `all(...)` predicates)
# came out identical.
#
# ONE RAW DIFFERENCE, and it is a fifth instance of the defect class rather
# than a regression: on the clean-sweep line
# ``every registered structural-RTL gate that dispatched PASSED (...)`` the
# scraper matches no prefix it knows, falls through to "take the first
# whitespace-delimited token", and returns the failing gate name ``every``.
# It is unobservable because every consumer of that list is guarded on
# ``status == "FAIL"`` and a clean sweep is a PASS — and a non-FAIL P0 can
# reach neither `failing`, `missing`, `oss_blocked_skipped` (P0 is not in
# _OPEN_SOURCE_CONTAINER_BLOCKED_STEPS) nor `informational_only_failing`
# (itself FAIL-guarded). The projection returns []. Recorded here because
# "the sixth line shape is parsed as a gate called `every`" is exactly the
# report this issue exists to stop having to write.
def _p0_gate_records(step: Any) -> List[Dict[str, Any]]:
    """The structured per-gate payload of a step, or ``[]`` when it has none.

    ``[]`` for a step that published nothing is the right answer for every
    caller here: each of them asks "which gates did this step report X for",
    and a step that reported on no gate reported X for none of them. The
    THREE-STATE distinction (`None` = not published, `[]` = published and
    empty) is preserved where it is meaningful — in the serialised artefact —
    and collapsed here, where it is not.
    """
    return list(getattr(step, "gate_records", None) or [])


def _p0_failing_gate_names(records: List[Dict[str, Any]]) -> List[str]:
    """The gates that FAILed, in canonical registry order.

    Replaces ``_parse_p0_failing_subgates``. Both ``all(...)`` predicates that
    decide a verdict read this: ``_step_failure_is_informational_only`` and the
    PASS_WITH_OPEN_SOURCE_CONSTRAINTS ``p0_is_deferrable`` test. Under the
    prose contract an unrecognised LINE became an unrecognised NAME and flipped
    both of them; here a name can only come from a record whose verdict field
    says FAIL.
    """
    return [r["name"] for r in records if r["verdict"] == "FAIL"]


def _p0_fail_line_body(record: Dict[str, Any]) -> str:
    """The body of a FAIL line: what follows ``FAIL: `` / ``  - ``.

    ONE renderer for the two places this text is observable — the reasons list
    the operator reads, and ``structural_fail_lines``, which is what sets
    ``forced_fail`` under ``--phase 2 --strict-structural``. They used to be
    written by the umbrella and re-derived by a scrape; now they are the same
    string from the same function.

    The killed-gate branch is the one FAIL whose prose is a whole sentence the
    umbrella wrote itself rather than the callee's first output line after an
    em-dash, and a kill key in the evidence is the machine-readable fact that
    says so. There are two, and BOTH are honoured: ``stall_grace_s`` is what
    the umbrella writes today (it bounds NO PROGRESS), ``timeout_s`` is what it
    wrote when the bound was a fixed wall clock. The old key is kept because a
    record is a PUBLISHED artefact — a report emitted before that change still
    has to render, and dropping the key would silently re-render those FAILs
    with an em-dash they never had.
    """
    if "timeout_s" in record["evidence"]:
        return f"{record['name']} timed out"
    if "stall_grace_s" in record["evidence"]:
        return f"{record['name']} {record['message']}"
    return f"{record['name']} — {record['message']}"


def _p0_structural_fail_lines(records: List[Dict[str, Any]]) -> List[str]:
    """The ``--strict-structural`` gate listing: one line per blocking FAIL.

    Replaces the ``structural_fail_lines`` scrape, the highest-stakes of the
    four consumers — it is what sets ``forced_fail`` under the flags
    ``design_one_shot_runner.step_final_audit`` actually ships, so a mis-parse
    here does not mis-report a run, it fails one.

    INFORMATIONAL_GATES are filtered exactly as before — by substring over the
    WHOLE rendered line, not over the gate name. That is deliberately kept: the
    line is byte-identical to the one the scrape used to see, so the filter
    cannot select differently, and narrowing it to the name would be a
    behaviour change smuggled into a refactor.
    """
    out: List[str] = []
    for r in records:
        if r["verdict"] != "FAIL":
            continue
        line = _p0_fail_line_body(r)
        if any(g in line for g in INFORMATIONAL_GATES):
            continue
        out.append(line)
    return out


def _p0_audit_gate_records(records: List[Dict[str, Any]]
                           ) -> List[Dict[str, Any]]:
    """The audit artifact's ``gates`` array.

    Replaces ``_normalise_p0_reason_line`` / ``_per_gate_from_p0_reasons``.
    Deliberately still FAIL-ONLY and still truncated at 240 characters: this
    step is a change of DERIVATION, not of schema, and the artifact is
    consumed by the mcp-eda pre-burn guard. Publishing the PASS / SKIP /
    NOT_INVOCABLE population here is a schema change with its own consumers to
    survey, and mixing it into a byte-identity migration would destroy the one
    piece of evidence that says the migration was faithful.
    """
    return [{"name": r["name"], "verdict": "FAIL",
             "message": r["message"][:240]}
            for r in records if r["verdict"] == "FAIL"]


# The gate's own account of WHY it had nothing to check. `[SKIP] ` and a
# repetition of the gate's own name are the house prefix on these lines; they
# carry no information beside a record that already has a `name` and a verdict,
# and repeating them makes the operator line unreadable. Strip only those two,
# never the reason itself, and fall back to the raw line if stripping would
# leave nothing — an empty message is how a genuinely silent gate is recorded,
# and a normalising step must not manufacture one.
_P0_SKIP_MARKER = re.compile(r"^\[(?:skip|n/?a|vacuous|info)\]\s*", re.I)


def _p0_skip_reason_from_output(gate_name: str, stdout: str,
                                stderr: str) -> str:
    """First informative line, minus the marker and the gate's own name.

    A banner such as ``=== waiver_staleness_check (...) ===`` says nothing
    about why the gate stopped.  Taking it unconditionally discarded the next
    line, including ``NONE could be aged`` — the zero denominator issue #1978
    needs to classify.  Skip banner-only lines, but never synthesize prose when
    the gate emitted none.
    """
    lines = (stdout.strip() or stderr.strip()).splitlines()
    informative = [ln.strip() for ln in lines if ln.strip()
                   and not re.match(r"^=+.*=+$", ln.strip())]
    raw = informative[0] if informative else ""
    if not raw:
        return ""
    line = _P0_SKIP_MARKER.sub("", raw, count=1).strip()
    if line.lower().startswith(gate_name.lower()):
        line = line[len(gate_name):].lstrip(" :\u2014-").strip()
    return (line or raw)[:200]


def _p0_skip_entry(record: Dict[str, Any]) -> str:
    """The legacy non-pass bucket payload for one non-decisive record.

    Three shapes, all of them the umbrella's own words about a gate that
    produced no verdict:

      * NOT_INVOCABLE -> the #492 disclosure entry, whose text and every
        downstream recogniser live together in `_gate_invocation`;
      * an input-missing SKIP -> ``<gate> (SKIP: <why>)`` where the gate
        stated a reason, and the bare gate name where it exited 2 in silence.
        The reason is the gate's OWN first line: this projection never invents
        one, so a silent gate still reads exactly as it did before;
      * every other SKIP -> ``<gate> (SKIP: <why>)`` — class-not-applicable,
        analog-track-deferred, no-backing-program.

    The `skip_kind` field is what selects among them, so the choice is made on
    a machine-readable fact rather than on which branch happened to build the
    string.
    """
    if record["verdict"] == "NOT_INVOCABLE":
        return _gate_invocation.format_not_invocable_entry(
            record["name"], record["message"])
    if record["verdict"] in ("BLOCKED", "INCOMPLETE"):
        return (f"{record['name']} ({record['verdict']}: reason_class="
                f"{record['reason_class']}: {record['message']})")
    if (record["evidence"].get("skip_kind") == "input-missing"
            and not record["message"].strip()):
        return record["name"]
    return f"{record['name']} (SKIP: {record['message']})"


def _p0_waiver_entry(record: Dict[str, Any]) -> Dict[str, Any]:
    """The waiver-bucket entry for a WAIVED record: the exact inverse of
    ``_p0_waiver_record``.

    The pair is two hand-written mirrors, which is a drift risk, and it is
    pinned by a round-trip test over the real waiver shapes plus the
    end-to-end byte-identity of `thin_input_waivers` in the `--json` report
    (whose key ORDER this reproduces deliberately).
    """
    ev = record["evidence"]
    return {
        "gate": record["name"],
        "review_required": ev["review_required"],
        "ticket": ev["ticket"],
        "evidence": ev["detail"],
        "reason": ev["reason"],
        "first_line": record["message"],
    }


def _p0_buckets_from_records(
    records: List[Dict[str, Any]],
) -> tuple[List[str], List[str], List[Dict[str, Any]]]:
    """The umbrella's three legacy outcome buckets, PROJECTED from the records.

    #497 step 3 — this is the inversion the whole issue turns on. The buckets
    used to be authored in the branch that decided each gate's outcome, and the
    records were built beside them; now the RECORD is the only thing authored
    and the buckets are derived from it. There is exactly one statement per
    gate, so the prose and the payload cannot disagree — not because a test
    checks that they agree, but because there is nothing left to disagree with.

    A PASS contributes to no bucket, which is why `passed_gate_count` was never
    recoverable from any of them.
    """
    fails: List[str] = []
    skips: List[str] = []
    waivers: List[Dict[str, Any]] = []
    for r in records:
        v = r["verdict"]
        if v == "FAIL":
            fails.append(f"FAIL: {_p0_fail_line_body(r)}")
        elif v in ("SKIP", "NOT_INVOCABLE", "BLOCKED", "INCOMPLETE"):
            skips.append(_p0_skip_entry(r))
        elif v == "WAIVED":
            waivers.append(_p0_waiver_entry(r))
    return fails, skips, waivers


def _p0_verdict_count(records: List[Dict[str, Any]]) -> int:
    """How many registered gates actually RETURNED a verdict (vibe-ic#559).

    `NOT_INVOCABLE` is not a verdict about the design — it says the gate never
    ran, because argparse rejected the argv the umbrella built. Every other
    outcome in `P0_GATE_VERDICTS` is a statement about what was audited, including
    `SKIP` (the input was absent) and `WAIVED`.

    Counted off the RECORDS rather than `registry - fails - skips - waivers`,
    which is what made the old passed-count unrecoverable: a bucket a passing gate
    contributes nothing to cannot be counted backwards from.
    """
    return sum(1 for r in records if r.get("verdict") != "NOT_INVOCABLE")


def _p0_not_invocable_count(records: List[Dict[str, Any]]) -> int:
    """How many registered gates were NEVER VALIDLY INVOKED.

    The complement of `_p0_verdict_count` over the same records, written as its
    own function rather than as `len(records) - verdict_count` at each caller:
    the subtraction is only equal to this while every registered gate has
    exactly one record, which is an invariant of the dispatch loop and not of
    any caller that holds a records list.

    THE SECOND OF THE TWO NUMBERS. `_p0_verdict_count` said how many gates
    answered; nothing said how many did not, so the gap between the umbrella's
    headline numerator and its denominator had no name and no field. A reader
    could subtract, and a reader who did not subtract read the numerator as the
    whole population — which is the reading the headline was reworded to stop.
    """
    return sum(1 for r in records if r.get("verdict") == "NOT_INVOCABLE")


STRUCTURAL_MEASUREMENT_PREFIX = "STRUCTURAL MEASUREMENT:"


def structural_measurement_line(registered: Optional[int],
                                invoked: Optional[int]) -> str:
    """The POPULATION this run's structural verdict was computed over.

    THE DEFECT THIS CLOSES. The `Overall:` line is the only thing
    `design_one_shot_runner.step_final_audit` reads out of this program: it
    greps stdout for `Overall: PASS_WITH_WAIVERS` / `Overall: PASS` and calls
    everything else FAIL. `Overall` is computed from `structural_fail_lines`,
    which `_p0_structural_fail_lines` builds from records whose verdict is
    exactly ``FAIL``. A registered gate that returned NO verdict at all —
    ``NOT_INVOCABLE``, the caller's own argv defect (#492) — contributes to that
    list exactly what a PASS contributes: nothing. So a run over the whole
    registered population and a run over a fraction of it print the SAME WORD
    and exit the SAME CODE.

    MEASURED, not argued. A 20-problem VerilogEval-Human run through
    `benchmark_dispatch.py --solve`, re-audited from a clean checkout of this
    file at origin/main 40d0e14c0:

      * 19 of 20 projects: ``registered_gate_count 246 / invoked_gate_count
        210 / not_invocable_gate_count 36``. The un-invocable 36 are a property
        of the CALL, not of any project (see ``_gate_invocation``), so EVERY
        one of those verdicts is over 210 gates and says 246.
      * 5 of them printed ``Overall: PASS_WITH_WAIVERS`` and exited 0. A
        project whose 246 gates ALL answered clean prints the same two things.
      * 1 of them (``Prob019``) dispatched the umbrella not at all —
        ``0 of 246 checkers returned a verdict`` — and still printed
        ``Overall: PASS_WITH_WAIVERS``, rc 0, which `step_final_audit` records
        as WAIVED. Not one structural gate looked at that design.

    The honest numbers already existed: `_p0_umbrella_status` returns
    ``INCOMPLETE``, and `phase23_completion_audit.json` carries all three
    counts. Neither reaches the verdict line or the exit code, and
    `_build_final_audit_cmd` does not even pass ``--json``, so on the runner's
    own path the honest number has NO consumer. This line is that consumer's
    input, printed where the runner's captured tail can see it.

    WHY A LINE AND NOT A NEW ``Overall:`` WORD. A verdict word is a claim about
    the DESIGN; this is a claim about the MEASUREMENT. Folding "36 gates never
    ran" into `Overall` would either green a real FAIL or red a clean run for
    something the design did not do — both are the false claim in one of its
    two directions. The verdict, the exit code and every existing consumer are
    untouched; the population is stated beside them, in its own units, so a
    reader and a program can tell the two cases apart.

    FOUR STATES, FOUR DIFFERENT SENTENCES — a disclosure that says the same
    thing about every input is not a disclosure:

      * ``registered`` or ``invoked`` is ``None`` -> NOT ASKED. A stage-3/4
        invocation never dispatches the umbrella. ``None`` is not zero and is
        never rendered as zero: "no measurement was requested" and "a
        measurement was requested and nothing answered" are the two states this
        whole finding is about, so they may not share a rendering.
      * ``invoked == 0 < registered``          -> NONE ANSWERED.
      * ``0 < invoked < registered``           -> PARTIAL.
      * ``invoked == registered``              -> WHOLE.

    chip-AGNOSTIC and benchmark-agnostic by construction: it reads two integers
    and names no design, no dataset and no flow. Machine-readable head
    (``registered=`` / ``invoked=`` / ``no_verdict=``) so a consumer parses
    rather than scrapes prose; ``null`` for the not-asked state.
    """
    if registered is None or invoked is None:
        return (f"{STRUCTURAL_MEASUREMENT_PREFIX} registered=null invoked=null "
                f"no_verdict=null — the structural-RTL umbrella was NOT ASKED "
                f"to run in this invocation, so this report makes no claim "
                f"about structural gate coverage. Not asked is not zero.")
    no_verdict = registered - invoked
    head = (f"{STRUCTURAL_MEASUREMENT_PREFIX} registered={registered} "
            f"invoked={invoked} no_verdict={no_verdict}")
    if registered and invoked == 0:
        return (f"{head} — NONE of the {registered} registered structural "
                f"sub-gate(s) returned a verdict. The verdict above was "
                f"computed over an EMPTY structural population: nothing "
                f"structural was measured about this design, and the verdict "
                f"word says nothing about that on its own.")
    if no_verdict > 0:
        return (f"{head} — PARTIAL: {no_verdict} of {registered} registered "
                f"structural sub-gate(s) returned NO verdict, so the verdict "
                f"above is over {invoked} gates, not {registered}, and what "
                f"those {no_verdict} audit is UNCHECKED — not clean.")
    return (f"{head} — WHOLE: every registered structural sub-gate returned a "
            f"verdict, so the verdict above is over the full registered "
            f"population.")


def _p0_umbrella_status(executed: Optional[bool],
                        records: List[Dict[str, Any]]) -> str:
    """THE ONE OWNER of the P0 umbrella's step verdict.

    The four outcomes, and why the third one is not a PASS:

      * ``executed is None``  -> ``SKIPPED-CONDITION``. #447: the umbrella
        dispatched nothing (no RTL), and 0-of-N executed checkers is not a PASS.
      * a gate FAILed          -> ``FAIL``. Unchanged; ``executed`` IS the
        umbrella's own ``len(fails) == 0`` flag, so this branch re-derives
        nothing and cannot disagree with the bucket it came from.
      * no FAIL, but at least one registered gate returned NO VERDICT
                               -> ``INCOMPLETE``.
      * no FAIL, and NO gate returned any verdict at all (an empty ``records``)
                               -> ``INCOMPLETE``. See THE EMPTY DENOMINATOR
        below.
      * no FAIL, every registered gate answered -> ``PASS``.

    WHY THE THIRD BRANCH EXISTS.  The verdict was ``len(fails) == 0``, computed
    over the gates that RETURNED a verdict, and published as a verdict over the
    registered population. MEASURED at v1.9.78 by running this CLI end to end
    over 49 tracked benchmark projects (every project root under
    ``benchmark-data`` / ``benchmark_external`` carrying RTL, minus the
    58-project ``run_v1333_knowledge_converge`` cvdp sub-corpus of
    near-duplicates): 246 registered, 210 answering and 36 ``NOT_INVOCABLE`` on
    ALL 49 — the un-invocable set is a property of the CALL, not of any
    project's content. On a project whose 210
    all came back clean, the umbrella printed PASS — a statement about 246
    checkers, 36 of which had never been validly invoked, so what those 36
    audit was UNAUDITED and the word `PASS` said otherwise. #492 made the
    silence VISIBLE (`NOT_INVOCABLE` is a first-class verdict, disclosed by name
    under its own heading); #559 put both numbers in the headline. Neither
    reached the VERDICT, and the verdict is the field a consumer reads.

    WHY ``INCOMPLETE`` AND NOT ``FAIL``.  A gate that never ran said nothing
    about the design, so calling the run a failure is a second false claim in
    the opposite direction — the same reason `_eval_gate_worker` does not
    convert a `NOT_INVOCABLE` gate into a FAIL. `INCOMPLETE` (#599) is the tier
    this repo already built for exactly this sentence: "the input WAS applicable
    and was NOT examined... a vacuous step is one nobody needs to come back to;
    this is one somebody does." It is a registered producer status
    (`_flow_verdict_tiers.PRODUCER_STATUSES`), a DONE-CLAIM that is not a full
    pass (`is_qualified_done`), and it is in none of `failing` / `missing` /
    `setup_required_skipped` / `oss_blocked_skipped` — so it cannot make a run
    non-green on its own, and it leaves the executed-PASS numerator, which is
    the number a reviewer actually reads.

    WHY NOT ``invoked < registered``.  That predicate is true of any records
    list shorter than the registry, including a test stub that publishes none,
    and it would fire on an umbrella that simply had nothing to dispatch. The
    defect is a gate that WAS dispatched and rejected the argv, which is
    `NOT_INVOCABLE` and nothing else. Narrow on purpose: a rule that fires on
    every shape of missing record is a rule that gets read as noise.

    THE EMPTY DENOMINATOR.  ``executed is True`` with an EMPTY ``records`` is
    `len(fails) == 0` over a population of zero — the exact sentence this
    function exists to stop, in its purest form: a clean sweep of nothing,
    certifying nothing, published as PASS. It is not reachable from the one
    production call site TODAY, because ``_run_structural_rtl_gates`` appends
    one record per registered gate before it returns, so ``executed is not
    None`` implies ``len(records) == len(_STRUCTURAL_RTL_GATES)``. That
    reachability is an invariant of the CALLER, and this function is the ONE
    OWNER of the verdict for EVERY caller — including the next one. A verdict
    that is only correct because of a property held somewhere else is a verdict
    waiting for a refactor, and a PASS pinned by a test outlives the invariant
    that made it unreachable: the pin is what the refactor will trust. So the
    guard is stated here, where the verdict is, and costs one comparison. Note
    the deliberate redundancy of ``executed and``: the branch above already
    proves ``executed`` is truthy, and the condition is written self-contained
    anyway so that moving or reordering these branches cannot silently turn the
    empty population back into a PASS.

    ``INCOMPLETE`` rather than ``FAIL`` for the same reason as above — zero
    gates answering said nothing about the design, so calling it a failure is
    the opposite false claim.
    """
    if executed is None:
        return "SKIPPED-CONDITION"
    if not executed:
        return "FAIL"
    if executed and not records:
        return "INCOMPLETE"
    nonverdict_classes = [
        str(r.get("reason_class") or "") for r in records
        if r.get("verdict") in _P0_NONDECISIVE_VERDICTS
    ]
    if (_reason_taxonomy.p0_tier_for_reason_classes(nonverdict_classes)
            == "INCOMPLETE"):
        return "INCOMPLETE"
    return "PASS"


def _p0_passed_count(records: List[Dict[str, Any]]) -> int:
    """How many registered gates ran and PASSED.

    Replaces ``_p0_passed_gate_count``, which computed the same number as
    ``registry - fails - skips - waivers`` because a passing gate contributes
    no reason line and the number was therefore unrecoverable from the prose
    (it read 0 for the artifact's entire history). Counting PASS verdicts is
    the direct statement of the same fact; the subtraction was the closest a
    bucket-only world could get.
    """
    return sum(1 for r in records if r["verdict"] == "PASS")


def _run_structural_rtl_gates(project: Path,
                              strict_timing: bool = False,
                              allow_thin_input: bool = False,
                              skip_analog: bool = False,
                              records_out: Optional[List[Dict[str, Any]]] = None
                              ) -> tuple[bool, List[str], List[str], List[Dict[str, Any]]]:
    """v0.104: run all structural-RTL gates on the project's RTL directory.

    Each gate is invoked through its declared contract; legacy-uniform gates
    retain the project-positional convention.
    Exit 0 = PASS, exit 1 = FAIL, exit 2 = input-missing (skip).
    Returns (all_passed, fail_reasons, skip_reasons, waiver_entries).

    #497 step 1 — ``records_out``, when a list is supplied, is EXTENDED with
    one ``_p0_gate_record`` per registered gate, in canonical
    ``_STRUCTURAL_RTL_GATES`` order, including the gates that PASS (which
    contribute no entry to any of the three returned buckets, and so have been
    unnameable by every consumer since the umbrella was written). The four
    returned values are untouched, byte for byte.

    WHY AN OUT-PARAMETER RATHER THAN A FIFTH RETURN VALUE.  This is a knowingly
    unlovely shape, chosen because the alternative is not additive. The 4-tuple
    is unpacked positionally at ~20 call sites across the test suite, and two of
    those tests replace THIS FUNCTION with a stub returning a 4-tuple in order
    to drive ``main()``; a fifth element breaks the first group and a separate
    5-tuple entry point breaks the second. An optional keyword that existing
    callers do not pass, and stubs absorb into ``**kwargs``, changes nothing for
    either. The step that cuts the consumers over to the records inverts this —
    the records become the return value and the three prose buckets become a
    projection of them — at which point the out-parameter goes away with the
    scrapers it exists to outlive.

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
            #
            # #497 — `records_out` is left EMPTY here, and that is the
            # statement: no gate was considered, so there is no gate to
            # record. The single skip line names no gate; it is the umbrella
            # explaining ITSELF, and step 3 makes that structural — the
            # composer emits it from `executed is None`, not from this bucket.
            # The bucket keeps it for the legacy 4-tuple, from the SAME
            # constant, so the two cannot be worded apart.
            return None, [], [_P0_NO_RTL_NOTE], []

    # Compute thin-input eligibility once. Only matters when the flag
    # is set. v1.6.98: shifted from doc-count to COVERAGE-shape — see
    # _is_thin_input_eligible docstring (issue #30 Bug 2).
    thin_input_eligible = (
        allow_thin_input
        and _is_thin_input_eligible(project)
    )

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
    # Issue #1968 — exceptional gate CLIs may need output paths.  Give every
    # invocation a private, non-project scratch tree so a compliance run stays
    # read-only with respect to the design and parallel gates cannot collide.
    _contract_scratch = tempfile.TemporaryDirectory(prefix="vibe-ic-p0-")
    gate_scratch_dir = Path(_contract_scratch.name)
    # ── #NNN: parallel structural-gate evaluation ─────────────────────────
    # Each structural gate is an INDEPENDENT read-only validator run as its own
    # subprocess with `cwd=project` (no `os.chdir`); the only per-gate output is
    # a (skip|waiver|fail|pass) classification of its result. So the gates can
    # run CONCURRENTLY — this is the dominant cost on structural-heavy chips
    # (a ~200-gate P0 umbrella) — as long as the fails/skips/waivers
    # lists stay in canonical `_STRUCTURAL_RTL_GATES` order (they feed the JSON
    # report + verdict). The worker below is EXACTLY the former loop body,
    # returning the outcome instead of appending in place; the ordered dispatch
    # loop then appends in gate order, so the report is byte-identical to the
    # sequential path (env `VIBE_IC_COMPLIANCE_WORKERS=1` forces serial).
    #
    # #497 step 3 — the worker returns ONE thing: the gate's RECORD. It used to
    # return the record AND the prose payload for whichever bucket the outcome
    # belonged to, which meant every outcome was stated twice, in two
    # vocabularies, and the two could be edited apart. The buckets are now
    # projected from the records by `_p0_buckets_from_records` after the
    # dispatch, so there is exactly one authoring site per gate.
    def _eval_gate_worker(gate_name: str) -> Dict[str, Any]:
        # #492 — the argv comes from the named builder, not an inline literal,
        # so the regression tests exercise the real construction path. Each
        # gate uses project.rglob for RTL discovery, so giving them the project
        # root finds RTL AND project files. The rtl_dir check above only gates
        # the entire runner ("if no RTL at all, skip the lot").
        argv = _structural_gate_argv(gate_name, project, rtl_dir=rtl_dir,
                                     strict_timing=strict_timing,
                                     scratch_dir=gate_scratch_dir)
        # TIMEOUT-AS-VERDICT (census row plugin/programs/flow_compliance_check.py
        # :7368, class A — "handler records a FAILING verdict"). The fixed 60 s
        # was a RUNTIME guess, and when it fired the umbrella wrote FAIL against
        # the gate: a loaded host or a large design manufactured a substantive
        # verdict about the DESIGN. `run_host_supervised` bounds NO-PROGRESS
        # instead — a gate whose process tree keeps moving runs to completion
        # however long it legitimately takes, and the caller's 60 s is re-read as
        # what it should always have been: how long this gate may show no
        # progress at all before it is called hung.
        res = _watchdog.run_host_supervised(
            argv, cwd=str(project), stall_grace_s=_P0_GATE_STALL_GRACE_S)
        if res.outcome in ("stalled", "ceiling"):
            # Still a FAIL — an unevaluated gate cannot pass — but the reason
            # now states what was actually observed. "made no forward progress"
            # is a claim about the GATE; "timed out" was a claim about the clock.
            return _p0_gate_record(
                gate_name, "FAIL",
                "made no forward progress: output, CPU and I/O were all flat, "
                "so it was killed as hung. This is NOT a statement that the "
                "gate was too slow",
                {"stall_grace_s": _P0_GATE_STALL_GRACE_S,
                 "elapsed_s": round(res.elapsed_s, 1)},
                reason_class=_reason_taxonomy.EXECUTION_ERROR)
        r = _watchdog.completed_process(argv, res)
        if r.returncode == 2:
            # #492 — rc 2 carried two unrelated meanings: "there was no input
            # to check" (a benign verdict FROM the gate) and "you called me
            # wrongly" (a defect IN THIS CALLER). Recording the second as a
            # skip is what let 39 registered gates be permanently silent while
            # the umbrella advertised that all of them ran. Separate them, and
            # say which one happened.
            #
            # A not-invocable gate is NOT converted to a FAIL: the gate
            # returned no verdict at all, so calling it a failure would be a
            # second false claim in the opposite direction. It is disclosed by
            # name, with the callee's own error text as the evidence.
            _why = _gate_invocation.classify_not_invocable(
                r.stdout, r.stderr,
                supplied_flags=[a for a in argv if a.startswith("--")])
            if _why:
                # The line's TEXT comes from _gate_invocation, which also owns
                # every predicate that recognises it downstream. Inlining the
                # f-string here is what let the reasons-list consumers drift
                # from the producer and scrape this disclosure as a failing
                # gate name (#492 follow-up).
                #
                # #497 — in the record the same fact needs no recogniser at
                # all: the verdict field says NOT_INVOCABLE.
                return _p0_gate_record(gate_name, "NOT_INVOCABLE", _why,
                                       {"exit_code": 2},
                                       reason_class=(
                                           _reason_taxonomy.EXECUTION_ERROR))
            # The gate has ALREADY said why it had nothing to check, on its
            # own stdout ("no opcode override doc found", "no ADDR-limit
            # conflict", "single-clock topology"). Recording an empty message
            # here threw that away, and `_p0_skip_entry` then rendered the
            # skip as the bare gate name. Measured on the spm run at
            # v1.11.93: 39 of 246 registered gates reached the report as a
            # name and nothing else.
            #
            # A bare name cannot be triaged. "This design legitimately has no
            # such layer" and "a producer never emitted the document this gate
            # reads" are OPPOSITE findings — one is a property of the design,
            # the other a program defect owed a fix — and both rendered
            # identically. Carry the callee's own first line, exactly as the
            # rc-1 and NOT_INVOCABLE arms already do; the VERDICT is
            # unchanged, only what the record is able to say about it.
            _skip_line = _p0_skip_reason_from_output(
                gate_name, r.stdout, r.stderr)
            _evidence = {"exit_code": 2, "skip_kind": "input-missing"}
            _reason_class = _reason_taxonomy.infer_nonverdict_reason(
                verdict="SKIP", message=_skip_line, evidence=_evidence)
            return _p0_gate_record(
                gate_name, _reason_taxonomy.record_verdict(_reason_class),
                _skip_line, _evidence, reason_class=_reason_class)
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
                _w = {
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
                }
                return _p0_waiver_record(_w)
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
                _w = {
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
                }
                return _p0_waiver_record(_w)
            elif gate_name in _two_source_advisory_gates():
                # DEGRADE LOUDLY: the finding is kept, named, and reported --
                # it just does not flip the umbrella verdict, because the gate
                # itself and the canonical flow BOTH declare it advisory. The
                # denominator is unchanged: the gate ran and returned.
                return _p0_waiver_record({
                    "gate": gate_name,
                    "ticket": "ENFORCEMENT:advisory",
                    "review_required": True,
                    "reason": (
                        "gate declares `ENFORCEMENT: advisory` in its own "
                        "docstring AND the canonical flow wires it under "
                        "`advisory_program_exit_zero`; recorded as a finding, "
                        "not as a blocking structural FAIL"),
                    "first_line": first_line,
                    "evidence": f"{gate_name}.py + flow/phase1_phase2_phase3.yaml",
                })
            else:
                return _p0_gate_record(gate_name, "FAIL", first_line,
                                       {"exit_code": 1})
        # A PASS contributes no line to any bucket — which is exactly why
        # `passed_gate_count` could never be recovered by reading the reasons
        # list, and was 0 for the artifact's entire history. It contributes a
        # RECORD.
        return _p0_gate_record(gate_name, "PASS", "", {"exit_code": 0})

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
                # A registry entry with no shipped program used to be dropped
                # here with `continue` — no fail, no skip, no waiver, no line
                # anywhere in the report — while the umbrella kept advertising
                # `len(_STRUCTURAL_RTL_GATES)` checkers. That is the umbrella
                # certifying a checker it never ran. Record a NAMED skip
                # instead: the count still comes from the registry, but every
                # registered gate that did not dispatch now says so by name.
                # This does not change the umbrella verdict (skips never fail
                # it) and on a correctly-packaged tree it never fires, because
                # every registered gate has its program.
                _msg = (f"registered structural gate has no backing program "
                        f"{prog.name} in {PROGRAMS_DIR.name}/ — checker did "
                        f"not run")
                _pending.append(
                    ("imm", _p0_gate_record(
                        gate_name, "INCOMPLETE", _msg,
                        {"skip_kind": "no-backing-program"},
                        reason_class=_reason_taxonomy.EXECUTION_ERROR)))
                continue
            if gate_name in class_skips:
                _pending.append(
                    ("imm", _p0_gate_record(
                        gate_name, "SKIP", class_skips[gate_name],
                        {"skip_kind": "class-not-applicable",
                         "invocation_contract":
                         _STRUCTURAL_GATE_INVOCATION_CONTRACTS.get(gate_name)},
                        reason_class=_reason_taxonomy.DESIGN_DECLARED_NA)))
                continue
            _contract_na = _p0_contract_na_reason(
                gate_name, project, rtl_dir)
            if _contract_na is not None:
                _pending.append(
                    ("imm", _p0_gate_record(
                        gate_name, "SKIP", _contract_na,
                        {"skip_kind": "declaration-not-present",
                         "applicability_source": "generated L-doc roster",
                         "invocation_contract":
                         _STRUCTURAL_GATE_INVOCATION_CONTRACTS.get(gate_name)},
                        reason_class=_reason_taxonomy.DESIGN_DECLARED_NA)))
                continue
            if gate_name in analog_skip_gates:
                _msg = ("analog track deferred via --skip-analog "
                        "(review_required at analog / foundry sign-off)")
                _pending.append(
                    ("imm", _p0_gate_record(
                        gate_name, "SKIP", _msg,
                        {"skip_kind": "analog-track-deferred"},
                        reason_class=_reason_taxonomy.EXTERNAL)))
                continue
            if _ex is not None:
                _pending.append(("fut", _ex.submit(_eval_gate_worker, gate_name)))
            else:
                _pending.append(("imm", _eval_gate_worker(gate_name)))
        # #497 step 3 — collect the RECORDS in canonical registry order, then
        # project them once. The three buckets are no longer accumulated
        # alongside the records; they are a VIEW of them, so they cannot be
        # populated with anything the records do not say.
        records = [_item if _tag == "imm" else _item.result()
                   for _tag, _item in _pending]
    finally:
        if _ex is not None:
            _ex.shutdown(wait=True)
        _contract_scratch.cleanup()

    # Publish the dispatch contract beside every affected real gate verdict.
    # This is evidence of HOW the gate was invoked, not a later inference from
    # argv text.  Immediate N/A records already carry the same field above.
    for record in records:
        contract = _STRUCTURAL_GATE_INVOCATION_CONTRACTS.get(record["name"])
        if contract:
            record["evidence"].setdefault("invocation_contract", contract)
            if record["evidence"].get("skip_kind") not in {
                    "class-not-applicable", "declaration-not-present",
                    "analog-track-deferred", "no-backing-program"}:
                record["evidence"].setdefault("gate_started", True)

    if records_out is not None:
        records_out.extend(records)
    fails, skips, waivers = _p0_buckets_from_records(records)
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
        _hres = _watchdog.run_host_supervised(
            [sys.executable, str(prog_path), "--help"], stall_grace_s=30)
        help_text = (_hres.out or "") + (_hres.err or "")
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


_PROGRAM_GATE_KEYS = (
    "program_exit_zero",
    "optional_program_exit_zero",
    "advisory_program_exit_zero",
)


def _declared_gate_commands(gate: Any) -> List[str]:
    """Names of the gate PROGRAMS a step declares, walking the gate spec.

    Structural walk of the same nested shapes `_evaluate_gate` executes
    (all_of / any_of lists of sub-gates; a program key holding either a bare
    command string or a {"command": ...} dict) — NOT a text scan, so it cannot
    be fooled by, or trip over, a program name mentioned in a yaml comment
    (comments are gone by the time PyYAML hands us this dict) or by a path
    argument that happens to contain a program's name.

    Returns first tokens (program names), de-duplicated, in declaration order.
    Empty list when the step declares no program gate at all.
    """
    out: List[str] = []

    def _walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                _walk(item)
            return
        if not isinstance(node, dict):
            return
        for key in ("all_of", "any_of"):
            sub = node.get(key)
            # `any_of: true` is a MODIFIER flag on a files_exist block, not a
            # nested gate list — only recurse into real containers.
            if isinstance(sub, (list, dict)):
                _walk(sub)
        for key in _PROGRAM_GATE_KEYS:
            spec = node.get(key)
            if isinstance(spec, dict):
                spec = spec.get("command")
            if not isinstance(spec, str) or not spec.strip():
                continue
            try:
                name = shlex.split(spec)[0]
            except ValueError:
                name = spec.split()[0]
            if name not in out:
                out.append(name)

    _walk(gate)
    return out


_ADVISORY_SKIP_VERDICTS = frozenset({
    "SKIP", "SKIPPED", "SKIPPED-CONDITION", "NOT-APPLICABLE",
    "NOT-RUN", "NO-BUILD", "VACUOUS", "VACUOUS-PASS",
})
_ADVISORY_INCOMPLETE_VERDICTS = frozenset({
    "INCOMPLETE", "NOT CHECKED", "NOT-CHECKED",
})
_ADVISORY_REFUSAL_VERDICTS = frozenset({
    "FAIL", "FAILED", "ERROR", "REFUSED", "BLOCKED", "INVALID",
    "VIOLATION",
})
_ADVISORY_PASS_VERDICTS = frozenset({"PASS", "CLEAN", "OK"})
_ADVISORY_NONBLOCKING_VERDICTS = frozenset({
    *_ADVISORY_PASS_VERDICTS, "PASS-WITH-ADVISORIES", "PASS-WITH-WAIVERS",
    "WARN", "WARNING", "ADVISORY",
})


def _advisory_execution_record(cmd: str, ledger_start: int,
                               ok: bool, out: str,
                               project: Path,
                               execution: Any = None) -> Dict[str, Any]:
    """Build one lossless record for the advisory invocation just completed."""
    row: Dict[str, Any] = {}
    if len(_GATE_LEDGER) > ledger_start:
        candidate = _GATE_LEDGER[-1]
        if candidate.get("cmd") == cmd:
            row = candidate
    report = _command_json_report(project, cmd)
    structured = (execution.structured_verdict
                  if isinstance(execution, _ProgramCheckResult) else
                  row.get("structured_verdict"))
    if not isinstance(structured, str) or not structured:
        structured = _report_verdict(report)
    reason_class = (execution.reason_class
                    if isinstance(execution, _ProgramCheckResult) else
                    row.get("reason_class"))
    reason_class = (_reason_taxonomy.normalise(reason_class)
                    or _reason_taxonomy.report_reason_class(report))
    actual_rc = (execution.exit_code
                 if isinstance(execution, _ProgramCheckResult) else
                 row.get("exit_code") if row else None)
    if actual_rc is None:
        if out.startswith(_VACUOUS_HINT_PREFIX):
            actual_rc = 2
        elif out.startswith(_WAIVER_HINT_PREFIX):
            actual_rc = _WAIVER_EXIT_CODE
        else:
            actual_rc = 0 if ok else 1
    if structured:
        verdict = structured
    elif isinstance(execution, _ProgramCheckResult):
        verdict = execution.verdict
    elif row.get("verdict"):
        verdict = row["verdict"]
    elif out.startswith(_VACUOUS_HINT_PREFIX):
        verdict = "VACUOUS_PASS"
    elif out.startswith(_WAIVER_HINT_PREFIX):
        verdict = "PASS_WITH_WAIVERS"
    else:
        verdict = "PASS" if ok else "FAIL"
    norm = str(verdict).strip().upper().replace("_", "-")
    if (reason_class is None
            and (norm in _ADVISORY_SKIP_VERDICTS
                 or norm in _ADVISORY_INCOMPLETE_VERDICTS
                 or norm == "BLOCKED"
                 or _stdout_signals_token(out, _INCOMPLETE_STDOUT_TOKEN))):
        reason_class = _reason_taxonomy.infer_nonverdict_reason(
            verdict=str(verdict),
            message=_report_reason_text(report) or out)
    true_refusals = _ADVISORY_REFUSAL_VERDICTS - {"BLOCKED"}
    if norm in true_refusals:
        enforcement = "BLOCKING"
    elif reason_class in _reason_taxonomy.INCOMPLETE:
        enforcement = "DISCLOSED_INCOMPLETE"
    elif norm in _ADVISORY_SKIP_VERDICTS:
        enforcement = ("DISCLOSED_SKIP"
                       if reason_class in _reason_taxonomy.SKIP_ELIGIBLE
                       else "DISCLOSED_INCOMPLETE")
    elif norm in _ADVISORY_INCOMPLETE_VERDICTS or norm == "BLOCKED":
        enforcement = "DISCLOSED_INCOMPLETE"
    elif norm == "PASS-WITH-WAIVERS":
        enforcement = "APPROVED_WAIVER"
    elif (norm in _ADVISORY_NONBLOCKING_VERDICTS
          or (actual_rc == 0 and norm not in _ADVISORY_REFUSAL_VERDICTS)):
        enforcement = ("PASSED" if norm in _ADVISORY_PASS_VERDICTS
                       else "NON_BLOCKING_ADVISORY")
    else:
        # No program-authored nonblocking verdict bought this non-zero exit.
        enforcement = "BLOCKING"
    return {
        "gate": _gate_name(cmd),
        "command": cmd,
        "exit_code": actual_rc,
        "verdict": str(verdict).strip().upper(),
        "structured_verdict": structured,
        "reason_class": reason_class,
        "enforcement": enforcement,
    }


# Gate predicate keys that are NOT program invocations. A step whose gate is
# built only out of these declares a real, evaluated gate — it just has no
# program name to print.
_PREDICATE_GATE_KEYS = ("files_exist", "json_field_true")


def _declared_gate_summary(gate: Any) -> str:
    """Short human description of the gate a step DECLARES — for disclosing a
    gate that did not run. Empty string ⇒ the step really declares no gate.

    `_declared_gate_commands` answers a NARROWER question (which gate PROGRAMS
    are declared) and correctly returns [] for a gate assembled only out of
    `files_exist` / `json_field_true` predicates. Reading that emptiness as
    "this step has no gate" is what made the #675-strict disclosure fire
    nowhere: over the whole corpus the strict self-skip resolves 3 times, all
    on the same step, and that step's gate is `files_exist: [...]` — so the
    ADVISORY was gained 0 of 3 times, on exactly the population it was written
    for. A gate is a gate whether or not it shells out.

    Program gates are named by program (that is the useful identifier); the
    predicate gates are named by kind and subject.
    """
    parts: List[str] = []

    def _add(s: str) -> None:
        if s and s not in parts:
            parts.append(s)

    def _walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                _walk(item)
            return
        if not isinstance(node, dict):
            return
        for key in ("all_of", "any_of"):
            sub = node.get(key)
            # `any_of: true` is a MODIFIER on a files_exist block, not a
            # nested gate list — only recurse into real containers.
            if isinstance(sub, (list, dict)):
                _walk(sub)
        for name in _declared_gate_commands(
                {k: v for k, v in node.items()
                 if k in _PROGRAM_GATE_KEYS}):
            _add(name)
        files = node.get("files_exist")
        if isinstance(files, (list, tuple)) and files:
            _add(f"files_exist[{', '.join(str(f) for f in files)}]")
        jft = node.get("json_field_true")
        if isinstance(jft, dict):
            _add(f"json_field_true[{jft.get('file', '?')}:"
                 f"{jft.get('field', '?')}]")

    _walk(gate)
    return ", ".join(parts)


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
        # W4 — `len(rules) == 0` IS THE FAILURE CASE, and it was the pass case.
        # MEASURED on origin/main (397b3f25f) against an empty project tree:
        #
        #     _evaluate_gate(p, {"files_exist": []})  -> (True, [])
        #     _evaluate_gate(p, {"all_of": []})       -> (True, [])
        #     _evaluate_gate(p, {"any_of": []})       -> (False, ['no sub-gate
        #                                                 passed in any_of'])
        #
        # Two of the three empty predicates certified a tree they had not
        # looked at, and `any_of` — the one that got it right — shows the
        # convention was already available. This is the same sentence
        # `util/checkMetadata.py` writes as `if len(rules) == 0: exit(1)`.
        #
        # LANDING WITH NO DEBT: the shipped `flow/phase1_phase2_phase3.yaml`
        # declares ZERO empty `files_exist` / `all_of` / `any_of` lists
        # (measured over every step gate, step condition and the final gate),
        # so the ratchet costs nothing today and refuses the first author who
        # writes one tomorrow.
        if not gate["files_exist"]:
            reasons.append(
                "files_exist: the required-file list is EMPTY, so this "
                "predicate examined nothing and concluded nothing. An empty "
                "corpus is a FAIL, not a pass — name the files this gate is "
                "about, or delete the predicate.")
            return False, reasons
        any_of = gate.get("any_of", False)
        all_of = gate.get("all_of", True) and not any_of
        passed, found, missing = _check_files_exist(
            project, gate["files_exist"], any_of=any_of
        )
        if not passed:
            incomplete_hint = _sibling_authoring_incomplete_for_missing(
                project, missing)
            if incomplete_hint is not None:
                reasons.append(
                    f"{_INCOMPLETE_HINT_PREFIX}{incomplete_hint}")
                return True, reasons
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
        # vibe-ic#901 - this clause DISPATCHED A PROGRAM. Recorded before
        # anything is decided about it, so the denominator cannot depend on the
        # outcome.
        reasons.append(f"{_RAN_HINT_PREFIX}{_cmd}")
        if passed and _json_report_signals_vacuous(project, _cmd):
            # vibe-ic#901 - the gate exited 0 and declared, in the `--json`
            # report THIS clause named, that it examined nothing. That is a
            # disclosure and it was reaching no consumer. Read from the FILE,
            # not from stdout: #887 established that a channel a project-path
            # length can truncate is not a disclosure channel. Recorded
            # unconditionally alongside whatever the legacy channels say, and
            # counted - never tiered - below.
            reasons.append(f"{_JSON_VACUOUS_HINT_PREFIX}{_cmd}")
        # Read BEFORE the pass/fail split and on the FULL snippet: the
        # 200-char truncation below would drop the sentinel, and the
        # disclosure is about what the gate certified, not about whether it
        # was satisfied.
        if _stdout_signals_structure_only(out):
            reasons.append(f"{_STRUCTURE_ONLY_HINT_PREFIX}"
                           f"{_structure_only_note(out) or _cmd}")
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
        elif _stdout_signals_vacuous(out):
            # A gate program may disclose the vacuous tier by PRINTING
            # `VACUOUS_PASS:` while still exiting 0 — which is exactly what the
            # shared analog helper `_analog_a_check_common.vacuous_pass()` does
            # for every A-track gate. The OPTIONAL branch below has always had
            # this stdout fallback; the REQUIRED branch did not, so the same
            # program disclosed its skip through an optional slot and was read
            # as a bare PASS through a required one. A disclosure only counts if
            # the consumer reads it in both.
            reasons.append(f"{_VACUOUS_HINT_PREFIX}{_cmd}")
        if passed and _stdout_signals_token(out, _SUBSTANTIVE_STDOUT_TOKEN):
            reasons.append(f"{_SUBSTANTIVE_HINT_PREFIX}{_cmd}")
        if passed and _stdout_signals_token(out, _INCOMPLETE_STDOUT_TOKEN):
            reasons.append(f"{_INCOMPLETE_HINT_PREFIX}{_cmd}")
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
    # the human report exists). Skipping no longer returns a bare True: since
    # W4 it returns True only for a clause that DECLARED why an absent input
    # is a genuine not-applicable, and it says so in the record. See
    # `_NOT_APPLICABLE_HINT_PREFIX` for what that costs and why.
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
            # NOTHING TO CHECK IS NOT A PASS. The condition matched no path,
            # so `cmd` did not run and this clause concluded nothing about its
            # subject. That is a legitimate state — and it has to be BOUGHT at
            # the wiring site, not assumed, or it is indistinguishable from a
            # gate that quietly stopped covering anything.
            why = spec.get("absent_condition_reason")
            why = why.strip() if isinstance(why, str) else ""
            if len(why) < _MIN_ABSENT_CONDITION_REASON:
                reasons.append(
                    f"optional_program_exit_zero: condition_files_exist "
                    f"{cond_files} matched 0 path(s) under {project}, so "
                    f"`{cmd}` did NOT run and this clause examined nothing — "
                    f"and the clause declares no usable "
                    f"`absent_condition_reason` "
                    f"({'absent' if not why else f'only {len(why)} char(s)'}; "
                    f"{_MIN_ABSENT_CONDITION_REASON} required). Nothing to "
                    f"check is a FAIL, not a pass; declare at the clause why "
                    f"an absent input is a genuine not-applicable here.")
                return False, reasons
            reasons.append(
                f"{_NOT_APPLICABLE_HINT_PREFIX}{cmd} — condition_files_exist "
                f"{cond_files} matched 0 path(s), so the program did not run "
                f"and nothing was checked. Declared not-applicable: {why}")
            return True, reasons
        # GAP-B (#789) — forward --skip-analog (+ reviewable --analog-anchor)
        # when the run defers the analog track AND this optional gate's program
        # declares the flag (e.g. l10/l12 tb-conformance, #773). Verbatim
        # otherwise. The gate program itself scopes the relaxation to ANALOG-only
        # intents, so a digital intent with no evidence STILL FAILs; this only
        # hands over the flag the gate already knows how to honour.
        cmd = _maybe_forward_skip_analog(project, cmd, skip_analog)
        passed, out = _check_program_exit_zero(project, cmd)
        # vibe-ic#901 - the clause's condition files existed, so it dispatched
        # a program. An optional clause whose condition is UNMET returns above
        # without reaching here and is deliberately NOT counted: it examined
        # nothing AND declared nothing, which is a different hole.
        reasons.append(f"{_RAN_HINT_PREFIX}{cmd}")
        if passed and _json_report_signals_vacuous(project, cmd):
            # vibe-ic#901 - the same structured disclosure, read in the OPTIONAL
            # slot too. A disclosure only counts if the consumer reads it in
            # BOTH slots; the same programs are wired through each.
            reasons.append(f"{_JSON_VACUOUS_HINT_PREFIX}{cmd}")
        if _stdout_signals_structure_only(out):
            reasons.append(f"{_STRUCTURE_ONLY_HINT_PREFIX}"
                           f"{_structure_only_note(out) or cmd}")
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
        if passed and _stdout_signals_token(out, _SUBSTANTIVE_STDOUT_TOKEN):
            reasons.append(f"{_SUBSTANTIVE_HINT_PREFIX}{cmd}")
        if passed and _stdout_signals_token(out, _INCOMPLETE_STDOUT_TOKEN):
            reasons.append(f"{_INCOMPLETE_HINT_PREFIX}{cmd}")
        return passed, reasons

    # `advisory_program_exit_zero` (#306/#1980) — RUNS the program and records
    # both its exit code and structured verdict. A genuine warning remains
    # nonblocking; a live refusal blocks. The slot describes the producer's
    # declared policy, it does not erase the verdict the producer returned.
    if "advisory_program_exit_zero" in gate:
        spec = gate["advisory_program_exit_zero"]
        # Accepts the same two shapes as the blocking slots: a bare command
        # STRING (the common case, and the form the enforcement audit reads),
        # or a dict when `condition_files_exist` is needed.
        if isinstance(spec, str):
            spec = {"command": spec}
        if not isinstance(spec, dict) or not spec.get("command"):
            # A MALFORMED advisory spec is a real gate-authoring FAIL, not an
            # advisory one: an unrunnable gate records nothing, and "recorded
            # nothing" must never be indistinguishable from "found nothing".
            reasons.append("advisory_program_exit_zero: spec must be a command "
                           "string, or a dict with a `command`")
            return False, reasons
        cmd = spec.get("command")
        cond_files = spec.get("condition_files_exist")
        if cond_files is not None:
            if not isinstance(cond_files, list) or not cond_files:
                reasons.append("advisory_program_exit_zero: "
                               "`condition_files_exist` must be a non-empty "
                               "list of glob patterns when present")
                return False, reasons
            present = []
            for pat in cond_files:
                present.extend(project.glob(pat))
            if not present:
                # W4 — SILENT was the word, and it was the defect. Three lines
                # below, this same branch refuses to let an rc-2 disclosed skip
                # read as a clean result because "recorded nothing must never
                # be indistinguishable from found nothing"; an unmet condition
                # records nothing AT ALL, which is the same substitution with
                # the program not even started. `fpga_led_probe_lint`'s own
                # SKILL.md states the exposure in the shipped flow: "over the
                # 28 published run roots it executes on 1 and is silent on 27".
                #
                # A MISSING DECLARATION IS A FAIL HERE TOO, advisory tier
                # notwithstanding — this branch already treats a malformed
                # advisory spec as "a real gate-authoring FAIL, not an advisory
                # one", and an undeclared not-applicable is the same class of
                # authoring defect. What the tier protects is the gate's
                # FINDINGS, not its wiring.
                why = spec.get("absent_condition_reason")
                why = why.strip() if isinstance(why, str) else ""
                if len(why) < _MIN_ABSENT_CONDITION_REASON:
                    reasons.append(
                        f"advisory_program_exit_zero: condition_files_exist "
                        f"{cond_files} matched 0 path(s) under {project}, so "
                        f"`{cmd}` did NOT run and recorded nothing — and the "
                        f"clause declares no usable `absent_condition_reason` "
                        f"({'absent' if not why else f'only {len(why)} char(s)'}"
                        f"; {_MIN_ABSENT_CONDITION_REASON} required). An "
                        f"an advisory declaration does not get to be silent "
                        f"about not having looked.")
                    return False, reasons
                # Recorded on the slot's OWN channel, which the `all_of`
                # whitelist already carries, so the disclosure cannot be
                # dropped one level up.
                declared_reason_class = spec.get(
                    "absent_condition_reason_class")
                reason_class = (_reason_taxonomy.normalise(
                    declared_reason_class)
                    if declared_reason_class is not None
                    else _reason_taxonomy.DESIGN_DECLARED_NA)
                if (declared_reason_class is not None
                        and reason_class not in
                        _reason_taxonomy.SKIP_ELIGIBLE):
                    reasons.append(
                        "advisory_program_exit_zero: invalid "
                        "`absent_condition_reason_class` "
                        f"{declared_reason_class!r} for `{cmd}`; expected one "
                        "of DESIGN_DECLARED_NA, CAPABILITY_ABSENT, EXTERNAL")
                    return False, reasons
                reasons.append(
                    f"{_ADVISORY_HINT_PREFIX}n/a (declared; condition "
                    f"{cond_files} matched 0 path(s), so it did not run): "
                    f"{cmd} — {why}")
                reasons.append(
                    f"{_ADVISORY_RECORD_HINT_PREFIX}"
                    + json.dumps({
                        "gate": _gate_name(cmd), "command": cmd,
                        "exit_code": None, "verdict": "NOT_APPLICABLE",
                        "structured_verdict": None,
                        "reason_class": reason_class,
                        "enforcement": "NOT_RUN_DECLARED",
                    }, sort_keys=True))
                return True, reasons
        cmd = _maybe_forward_skip_analog(project, cmd, skip_analog)
        _ledger_start = len(_GATE_LEDGER)
        _execution = _check_program_exit_zero(project, cmd)
        ok, out = _execution
        record = _advisory_execution_record(
            cmd, _ledger_start, ok, out, project, _execution)
        reasons.append(f"{_RAN_HINT_PREFIX}{cmd}")
        reasons.append(
            f"{_ADVISORY_RECORD_HINT_PREFIX}"
            + json.dumps(record, sort_keys=True))
        enforcement = record["enforcement"]
        if enforcement == "BLOCKING":
            reasons.append(
                f"advisory gate refusal: {cmd} "
                f"[rc={record['exit_code']}, verdict={record['verdict']}, "
                f"reason_class={record['reason_class']}]")
            if out:
                reasons.append(f"output: {out[:200]}")
            # An `advisory_program_exit_zero` row that FAILS its step on a
            # refusal is indistinguishable from the blocking
            # `program_exit_zero` row, which makes the two slot names a
            # distinction without a difference.
            #
            # Honour the refusal as advisory ONLY on two-source agreement:
            # the gate's own module says `ENFORCEMENT: advisory` AND the
            # canonical flow wires it advisory and never blocking. A gate
            # that still declares itself blocking while wired advisory is a
            # real disagreement between two authors and keeps blocking here
            # -- it is not this function's place to resolve that silently.
            #
            # The refusal is already appended above and carried in the
            # structured record, so it is REPORTED either way; what changes
            # is only whether it flips the step verdict.
            if _gate_is_two_source_advisory(_gate_name(cmd)):
                return True, reasons
            return False, reasons
        if enforcement == "DISCLOSED_SKIP":
            _structured_norm = str(
                record.get("structured_verdict") or "").upper().replace(
                    "_", "-")
            if _structured_norm in _SELF_SKIP_VERDICTS:
                reasons.append(f"{_SKIP_HINT_PREFIX}{cmd} "
                               f"[verdict={record['verdict']}, "
                               f"reason_class={record['reason_class']}]")
            elif out.startswith(_VACUOUS_HINT_PREFIX):
                reasons.append(out)
            else:
                reasons.append(f"{_VACUOUS_HINT_PREFIX}{cmd}")
        elif enforcement == "DISCLOSED_INCOMPLETE":
            reasons.append(f"{_INCOMPLETE_HINT_PREFIX}{cmd} "
                           f"[verdict={record['verdict']}, "
                           f"reason_class={record['reason_class']}]")
        elif enforcement == "APPROVED_WAIVER":
            reasons.append(f"{_WAIVER_HINT_PREFIX}{cmd}")
        elif out.startswith(_VACUOUS_HINT_PREFIX):
            reasons.append(out)
        elif enforcement == "NON_BLOCKING_ADVISORY":
            reasons.append(
                f"{_ADVISORY_HINT_PREFIX}verdict={record['verdict']} "
                f"rc={record['exit_code']}: {cmd}"
                + (f" :: {out[:200]}" if out else ""))
        return True, reasons

    # `all_of` - list of sub-gates, all must pass
    if "all_of" in gate and isinstance(gate["all_of"], list):
        # W4 — an empty conjunction is vacuously true in logic and vacuously
        # CERTIFYING here, which is the difference that matters: `all_of: []`
        # is a step declaring a gate and running none of it. Refused for the
        # same reason as the empty `files_exist` list above, and with the same
        # measured zero debt on the shipped flow.
        if not gate["all_of"]:
            reasons.append(
                "all_of: the sub-gate list is EMPTY, so this gate dispatched "
                "nothing and concluded nothing. A gate that ran no sub-gate "
                "is a FAIL, not a pass.")
            return False, reasons
        # Wave 93 — preserve VACUOUS_HINT reasons from passing sub-gates so
        # the step-level handler can promote a step whose every executed
        # sub-gate was vacuously satisfied.
        for _i, sub in enumerate(gate["all_of"]):
            if not isinstance(sub, dict):
                continue
            p, r = _evaluate_gate(project, sub, skip_analog=skip_analog)
            if not p:
                reasons.extend(r)
                # #306/#297 — the step has already failed, but the ADVISORY
                # sub-gates still have something to say and this is the run
                # where it matters most. Short-circuiting past them meant the
                # routability-for-clock-quality disclosure was skipped on
                # EVERY failing route — measured end-to-end on a real cell:
                # Step 21 FAILed on an earlier sibling and not one advisory
                # line appeared. The parent is already false, so later
                # executions cannot rescue it; they can only add their exact
                # disposition and evidence.
                # Only the ones AFTER the failure: the earlier ones already
                # ran in this loop and appended their hints.
                for later in gate["all_of"][_i + 1:]:
                    if (isinstance(later, dict)
                            and "advisory_program_exit_zero" in later):
                        _p2, r2 = _evaluate_gate(project, later,
                                                 skip_analog=skip_analog)
                        reasons.extend(
                            h for h in r2
                            if h.startswith((
                                _ADVISORY_HINT_PREFIX,
                                _ADVISORY_RECORD_HINT_PREFIX,
                                _RAN_HINT_PREFIX,
                                _SKIP_HINT_PREFIX,
                                _WAIVER_HINT_PREFIX,
                                _INCOMPLETE_HINT_PREFIX,
                            )))
                return False, reasons
            for hint in r:
                if hint.startswith(_RAN_HINT_PREFIX):
                    # vibe-ic#901 - the DENOMINATOR travels with the numerator.
                    # This loop is a whitelist, so a `__RAN_HINT__` dropped here
                    # would leave the step-level count comparing vacuous clauses
                    # against a denominator of zero - i.e. straight back to
                    # "silence means substance".
                    reasons.append(hint)
                elif hint.startswith(_JSON_VACUOUS_HINT_PREFIX):
                    reasons.append(hint)
                elif hint.startswith(_VACUOUS_HINT_PREFIX):
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
                elif hint.startswith(_ADVISORY_HINT_PREFIX):
                    # #306 — carry the advisory verdict up. Dropping it here
                    # would give an advisory sub-gate that RAN and FOUND
                    # something no way to be seen, which is the failure mode
                    # the slot exists to avoid.
                    reasons.append(hint)
                elif hint.startswith(_ADVISORY_RECORD_HINT_PREFIX):
                    # #1980 — the typed record is the authoritative channel;
                    # dropping it here would preserve prose while losing the
                    # exact rc / structured verdict / disposition tuple.
                    reasons.append(hint)
                elif hint.startswith(_STRUCTURE_ONLY_HINT_PREFIX):
                    # Same reason, one tier over. This list is a WHITELIST: a
                    # hint a sub-gate emits and this loop does not name is
                    # dropped here, silently, and the disclosure dies one
                    # level below the line that was supposed to carry it —
                    # which is precisely the shape of defect the tier exists
                    # to make visible.
                    reasons.append(hint)
                elif hint.startswith(_SUBSTANTIVE_HINT_PREFIX):
                    reasons.append(hint)
                elif hint.startswith(_NOT_APPLICABLE_HINT_PREFIX):
                    # W4 — the whitelist's own warning, come true a THIRD time.
                    # MEASURED before this branch existed, on a tree carrying
                    # step 2's required_outputs and an RTL directory but none
                    # of the Phase-1 documents its optional clauses read: five
                    # of the nine clauses did not run, each emitted its
                    # declared not-applicable record, and every one of the five
                    # was dropped at this line. `check_step` then reported
                    # `declared_not_applicable: 0` and a bare PASS — the
                    # disclosure dying one level below the line meant to carry
                    # it, which is the shape the comment above predicts.
                    reasons.append(hint)
                elif hint.startswith(_INCOMPLETE_HINT_PREFIX):
                    # The whitelist's own warning, come true. #599 added these
                    # two tiers to `program_exit_zero` and did NOT add them
                    # here, so a sub-gate that printed `INCOMPLETE:` inside an
                    # `all_of` had its refusal dropped at this line and the
                    # step was reported as a bare PASS — the exact failure the
                    # comment above describes. MEASURED: step 25's and step
                    # 33's new authority clauses print the token, exit 0, and
                    # before this branch existed `check_step` returned PASS
                    # with the hint absent from `reasons` entirely.
                    reasons.append(hint)
        return True, reasons

    # `any_of` - list of sub-gates, any one passes
    if "any_of" in gate and isinstance(gate["any_of"], list):
        for sub in gate["any_of"]:
            if not isinstance(sub, dict):
                continue
            # An any_of cannot safely mix an advisory policy with sign-off
            # alternatives: a warning/pass would satisfy the disjunction and
            # bypass every sibling. Keep policy-bearing checks in all_of.
            if "advisory_program_exit_zero" in sub:
                reasons.append(
                    "any_of contains an `advisory_program_exit_zero`: an "
                    "advisory warning/pass could satisfy the whole any_of "
                    "and its siblings would never be "
                    "consulted. Put the advisory gate in an `all_of` "
                    "alongside them instead (#306).")
                return False, reasons
            p, r = _evaluate_gate(project, sub, skip_analog=skip_analog)
            if p:
                # W4 — an `any_of` satisfied by a branch that DID NOT RUN is
                # the group's whole verdict resting on a non-verdict. The
                # branch still passes (a declared not-applicable is a legal
                # pass), but the record has to say which branch carried the
                # group and that it examined nothing; otherwise this is the
                # dropped-disclosure shape of the `all_of` whitelist above,
                # one branch over.
                reasons.extend(
                    h for h in r
                    if h.startswith(_NOT_APPLICABLE_HINT_PREFIX))
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

#: #524 — ENV_UNAVAILABLE waivers that WERE honoured but whose `evidence` no
#: independent artefact corroborates. Surfaced as report advisories next to the
#: rejections, so a WAIVED step no longer reads identically whether its
#: deferral rested on an independent artefact or on the producing run pointing
#: at its own orchestrator report.
#:
#: A SEPARATE list from `_ENV_WAIVER_REJECTIONS` on purpose: these waivers are
#: APPLIED. Filing them as rejections would say the step lost its exemption
#: when it did not, which is a different lie from the one being fixed.
#: Populated by `_load_waivers`, which clears it on entry.
_ENV_WAIVER_EVIDENCE_NOTES: List[str] = []

#: #529 — `waivers`-dialect entries this module READ but did NOT bind to a flow
#: step, each with the reason. The loop below binds one tier, ENV_UNAVAILABLE;
#: every other entry took a bare `continue` and left no trace, so a report was
#: byte-identical whether the project carried a fully attested waiver or no
#: waivers.json at all. Measured over every tracked waivers.json: 8 of 8
#: `waivers`-dialect entries (7 verdict_tier WAIVED, 1 PASS_STRUCTURAL, 0
#: ENV_UNAVAILABLE) hit that `continue`, so the mechanism #216 built for
#: "a rejected waiver must never vanish" covered none of the corpus.
#:
#: A THIRD list, separate from BOTH of the above, on purpose:
#:   * not `_ENV_WAIVER_REJECTIONS` — nothing here was refused. A WAIVED-tier
#:     entry is not an error; calling it a rejection would say the step lost an
#:     exemption it never asked this module for, which is the opposite lie.
#:   * not `_ENV_WAIVER_EVIDENCE_NOTES` — those waivers were APPLIED and the
#:     note qualifies them. These were not applied at all.
#: Every entry here is INFORMATIONAL: it changes no step verdict, no count and
#: no exit code. It exists so a reader can tell "read and inapplicable" from
#: "nobody read this file".
_WAIVER_NOT_BOUND_DISCLOSURES: List[str] = []


# #519 — the map MOVED to `_waiver_entries`, which is where the waiver
# vocabulary lives now, and is re-exported here under its historical name so
# this module's existing references keep working against ONE definition.
# It had to move rather than be imported the other way: `waivers_schema_check`
# needs it to resolve a `step: "<role-name>"` waiver, and this module already
# imports `waivers_schema_check.validate`, so importing back would cycle.
_ENV_UNAVAILABLE_STEP_NAME_TO_ID: Dict[str, Any] = _we.STEP_NAME_TO_ID


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

# The ANALOG counterpart of _FPGA_BOARD_STEP_IDS: steps whose evidence can only
# come off a lab bench. Kept as STRING ids because the analog track is lettered
# — which is exactly why the --skip-hardware routing missed A9 for so long: that
# routing is guarded by `isinstance(sid, int)`, so a lettered id could never
# match it however the run was launched.
_ANALOG_BENCH_STEP_IDS = frozenset({"A9"})


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


# Moved to fpga_board_capability.py (#446 follow-up) so a P0 sub-gate that
# is NOT one of _FPGA_BOARD_STEP_IDS (rig_topology_disclosure_check runs
# inside the structural-RTL umbrella, never as its own flow step) can
# consult the identical signal. Kept as a thin alias — every existing call
# site in this file is unchanged — so this is a pure relocation, not a
# behavioural edit.
_fpga_skip_disclosed = _fpga_cap.fpga_skip_disclosed


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


def _unbound_tier_disclosure(index: int,
                             entry: Dict[str, Any],
                             raw_tier: Any,
                             tier: str) -> str:
    """#529 — the advisory for a `waivers`-dialect entry whose `verdict_tier`
    is not ENV_UNAVAILABLE, i.e. one this module read and did not bind.

    WHAT IT MUST AND MUST NOT SAY. It must not read as a rejection: the entry
    is typically well-formed, ticketed and reviewable, and refusing it would be
    a second falsehood in the opposite direction from the silence. It must also
    not hand-wave that the entry "is for another consumer", because — measured
    by execution over every tracked waivers.json and every program that reads
    one — NO code anywhere branches on the tier VALUE except on the single
    string ENV_UNAVAILABLE (here, and `waiver_staleness.is_env_unavailable`).
    Substituting a garbage tier changed no consumer's output. So the honest
    statement is narrow and durable: the ENTRY is consumed, tier-blind, by the
    waiver-hygiene gates and rendered for a human by `final_report_generate`;
    the TIER is a human-readable record of the producing step's status, and no
    gate binds it to a verdict.

    chip-AGNOSTIC: renders only the entry's own structural fields."""
    if isinstance(raw_tier, str) and tier:
        tier_phrase = f"verdict_tier {tier!r}"
    elif raw_tier is None or (isinstance(raw_tier, str) and not tier):
        tier_phrase = "no `verdict_tier`"
    else:
        tier_phrase = (f"a `verdict_tier` of type "
                       f"{type(raw_tier).__name__}, not a string")
    raw_step = entry.get("step")
    step_name = raw_step.strip().lower() if isinstance(raw_step, str) else ""
    sid = _we.resolve_step_name(step_name)
    if sid is not None:
        step_phrase = f"step {step_name!r} (flow step {sid})"
        merits = f"flow step {sid} is"
    elif step_name:
        step_phrase = (f"step {step_name!r}, which is not a recognised flow "
                       f"role name")
        merits = "every flow step is"
    else:
        step_phrase = "no readable `step`"
        merits = "every flow step is"
    ticket = entry.get("ticket")
    ticket_phrase = (f", ticket {ticket!r}" if isinstance(ticket, str) and ticket
                     else ", no ticket")
    return (
        f"WAIVER READ, NOT BOUND — waivers.json `waivers` entry {index} names "
        f"{step_phrase} and carries {tier_phrase}{ticket_phrase}. "
        f"flow_compliance_check binds ONLY verdict_tier 'ENV_UNAVAILABLE' "
        f"entries to a flow step, so this entry granted nothing and refused "
        f"nothing: {merits} reported on its own merits, exactly as it would be "
        f"with no waivers.json at all. This is DISCLOSURE, NOT a rejection — "
        f"the entry is still examined, tier-blind, by the waiver-hygiene gates "
        f"(waivers_schema_check, waiver_legitimacy_check, "
        f"waiver_staleness_check) and is listed for review in "
        f"reports/final_summary.md. No gate binds a non-ENV_UNAVAILABLE tier "
        f"to a step verdict; the tier records the producing step's status for "
        f"a human reader, not a machine decision.")


def _load_waivers(project: Path, max_step: int = 40) -> Dict[int, Dict[str, str]]:
    """Load waivers AFTER validating schema. Returns {} if file missing.
    Raises SystemExit(1) if waivers.json exists but is malformed/rubber-stamped."""
    _ENV_WAIVER_REJECTIONS.clear()  # #216 — fresh per call
    _ENV_WAIVER_EVIDENCE_NOTES.clear()  # #524 — fresh per call
    _WAIVER_NOT_BOUND_DISCLOSURES.clear()  # #529 — fresh per call
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
        # #529 — and NO `continue` in this loop is silent. #216 gave the two
        # rejection branches a voice but left three others mute: a non-object
        # entry, an entry whose tier is not ENV_UNAVAILABLE, and an entry
        # superseded by a `waived_steps` entry for the same step. The middle
        # one is the whole corpus. Each now records why it was not bound.
        #
        # The entry list comes from the SHARED reader (#519's `_waiver_entries`)
        # rather than `data.get("waivers")`, so "which key holds the entries" is
        # answered in one place; `entries_by_key` also yields nothing — instead
        # of iterating a dict's keys — when `waivers` holds a non-list.
        for _idx, w in enumerate(_we.entries_by_key(data).get("waivers", [])):
            if not isinstance(w, dict):
                _WAIVER_NOT_BOUND_DISCLOSURES.append(
                    f"WAIVER ENTRY UNREADABLE — waivers.json `waivers` entry "
                    f"{_idx} is a {type(w).__name__}, not an object, so no "
                    f"step, tier, ticket or rationale could be read from it "
                    f"and it was skipped. No step verdict is affected. Fix or "
                    f"remove the entry.")
                continue
            # DEFENSIVE READ, NOT a schema opinion (#519's rule: a schema error
            # must not take the report down). `verdict_tier` holding a non-string
            # used to reach `.strip()` and raise, and the sole handler of this
            # block turns any exception into SystemExit(1) — so ONE mistyped
            # field deleted the entire compliance report, all 40+ steps of it,
            # and printed only "cannot parse". A non-string tier is now simply
            # a tier that does not equal ENV_UNAVAILABLE, disclosed like any
            # other unbound entry.
            _raw_tier = w.get("verdict_tier")
            tier = _raw_tier.strip().upper() if isinstance(_raw_tier, str) else ""
            if tier != "ENV_UNAVAILABLE":
                _WAIVER_NOT_BOUND_DISCLOSURES.append(
                    _unbound_tier_disclosure(_idx, w, _raw_tier, tier))
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
                # explicit waived_steps entry takes precedence. #529 — say so.
                # The step IS waived, by the other entry, so this is neither a
                # rejection nor a lost exemption; what a reader could not see
                # before is WHICH of two entries supplied the rationale and
                # ticket the report is quoting.
                _WAIVER_NOT_BOUND_DISCLOSURES.append(
                    f"WAIVER SUPERSEDED — waivers.json `waivers` entry {_idx} "
                    f"(verdict_tier ENV_UNAVAILABLE, step {step_name!r} → flow "
                    f"step {sid}, ticket {ticket!r}) was NOT applied: a "
                    f"`waived_steps` entry for the same step is already in "
                    f"force and takes precedence. Flow step {sid} IS waived — "
                    f"by that other entry, whose rationale and ticket are the "
                    f"ones this report quotes — so no verdict changes. If this "
                    f"entry's rationale is the accurate one, remove the "
                    f"competing `waived_steps` entry.")
                continue
            # #524 — the attestation quartet stands in for a human signature
            # (#519), so `evidence` carries the signature's weight. But the
            # test above is `evidence[] non-empty`, a LENGTH test, and a list
            # holding one pointer back at the producing run's own orchestrator
            # report satisfies it exactly as well as a pointer to an
            # independent artefact. Measured on the real producer:
            # `phase3_one_shot_runner._autogen_waivers_json` appends that
            # self-reference UNCONDITIONALLY, and harvests the step's `extras`
            # values as though every one were a path — so an ENV_UNAVAILABLE
            # waiver's evidence is typically `["<tool name>", "<self-ref>"]`
            # and, when extras are empty, the self-reference ALONE.
            #
            # The waiver is still HONOURED. Refusing it would be the wrong
            # repair: this tier's claim is that a tool was ABSENT, and no
            # independent artefact can corroborate a non-execution — the run's
            # own probe record is the only witness that can exist. Since every
            # ENV_UNAVAILABLE waiver the producer can emit is uncorroborated,
            # refusing them would make an honest, correctly disclosed,
            # tool-less-host deferral impossible to honour, i.e. would break
            # "disclosure buys deferral" for precisely the population the tier
            # was built for.
            #
            # So the repair is to stop the report reading IDENTICALLY in the
            # two cases. The assessment rides on the waiver record and, when
            # nothing independent corroborates it, is surfaced as a named
            # advisory. Classification only — never raises, never rejects,
            # never changes a step verdict. chip-AGNOSTIC (structural path
            # tests only).
            _assess = _ev_ind.assess(evidence, project)
            if not _assess.corroborated:
                _ENV_WAIVER_EVIDENCE_NOTES.append(
                    "HONOURED but UNCORROBORATED — " +
                    _ev_ind.disclosure(step_name, _assess) +
                    f" The step (flow step {sid}) remains WAIVED-DEFERRED on "
                    f"ticket {ticket}; review_required stays true.")
            out[sid] = {
                "id": sid,
                "reason": (
                    f"ENV_UNAVAILABLE: {rationale[:200]} "
                    f"[ticket={ticket}, review_required={reviewer_required}, "
                    f"evidence={_assess.describe()}"
                    + ("" if _assess.corroborated
                       else ", NO independent corroboration") + "]"
                ),
                "approver": w.get("approver",
                                  "field-agent-attest (ENV_UNAVAILABLE tier)"),
                "ticket": ticket,
                "verdict_tier": tier,
                "review_required": reviewer_required,
                "evidence": evidence,
                "evidence_assessment": _assess.as_dict(),
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
        if not any(_condition_pattern_satisfied(project, pat)
                   for pat in files):
            return False
        return True
    if files:
        for pat in files:
            if not _condition_pattern_satisfied(project, pat):
                return False
    return True


def _condition_na_declaration(
        project: Path, policy: Any) -> Optional[Tuple[str, str]]:
    """Return the cited design declaration that makes a condition N/A.

    ``condition_not_applicable`` is flow metadata, not a step-id table in this
    program.  The flow names the L-document and the explicit applicability
    values that stand the step down.  Missing, unparseable and un-extracted
    documents return ``None``: absence of a declaration is not a declaration
    of absence.
    """
    if not isinstance(policy, dict):
        return None
    doc_id = str(policy.get("l_doc") or "").strip()
    allowed = {
        str(v).strip().upper().replace("-", "_")
        for v in (policy.get("applicability") or [])
        if str(v).strip()
    }
    if not doc_id or not allowed:
        return None
    try:
        path, doc = _ldoc.load_l_doc(project, doc_id)
    except Exception:
        return None
    if path is None or not isinstance(doc, dict):
        return None
    raw = str(_ldoc.applicability_of(doc) or "").strip()
    normal = raw.upper().replace("-", "_")
    if normal not in allowed:
        return None
    try:
        cited = str(path.relative_to(project))
    except (ValueError, OSError):
        cited = str(path)
    return cited, raw


def _declared_output_branches(spec: Any) -> List[str]:
    """The exact artefact branches of one ``required_outputs`` entry."""
    if not isinstance(spec, str):
        return []
    return [part.strip() for part in spec.split(" OR ") if part.strip()]


def _condition_dependency_producer(
        step: Dict[str, Any], pattern: str,
        step_specs: Mapping[str, Dict[str, Any]]) -> Optional[str]:
    """Nearest ``blocks_on`` ancestor that declares ``pattern`` as output.

    The relation is derived from the flow's existing dependency graph and
    output declarations.  A parallel hand-maintained pattern-to-step table
    would drift the first time either side of the flow changes.
    """
    queue = [str(s) for s in (step.get("blocks_on") or [])]
    seen: Set[str] = set()
    while queue:
        sid = queue.pop(0)
        if sid in seen:
            continue
        seen.add(sid)
        spec = step_specs.get(sid) or {}
        branches = {
            branch
            for output in (spec.get("required_outputs") or [])
            for branch in _declared_output_branches(output)
        }
        if pattern in branches:
            return sid
        queue.extend(str(p) for p in (spec.get("blocks_on") or []))
    direct = [str(s) for s in (step.get("blocks_on") or [])]
    return direct[0] if len(direct) == 1 else None


def _resolve_dependency_condition_results(
        project: Path, results: Sequence[StepResult],
        flow_steps: Sequence[Dict[str, Any]]) -> None:
    """Classify unmet dependency conditions after upstream verdicts exist.

    A plain ``condition_files_exist`` answers only whether a step should be
    dispatched.  It cannot distinguish a design-declared inapplicable track
    from a required upstream artefact that is absent because its producer
    failed.  Steps opting into ``condition_kind: dependency_required`` make
    that distinction here, after all independent step checks have completed:

    * a cited ``condition_not_applicable`` declaration keeps the honest
      ``SKIPPED-CONDITION`` tier;
    * otherwise the step becomes the flow's established dependency state —
      ``MISSING`` plus ``blocked-by-upstream(<producer>)`` — and names every
      absent artefact and the producer that declares it.

    Mutates ``results`` in place before the ordinary cascade-attribution pass.
    It never promotes a verdict and never changes a satisfied condition.
    """
    specs = {
        str(step.get("id")): step
        for step in flow_steps
        if isinstance(step, dict) and step.get("id") is not None
    }
    by_id = {str(result.id): result for result in results}

    for result in results:
        step = specs.get(str(result.id))
        if not step or step.get("condition_kind") != "dependency_required":
            continue
        condition = step.get("condition") or {}
        if _check_condition(project, condition):
            continue
        # Only the condition-generated skip is eligible. A run-mode or
        # class-level skip has a different owner and must not be rewritten.
        if result.status != "SKIPPED-CONDITION" or not any(
                str(reason).startswith("condition not met:")
                for reason in result.reasons):
            continue

        missing = [
            str(pattern)
            for pattern in (condition.get("files_exist") or [])
            if not _condition_pattern_satisfied(project, str(pattern))
        ]
        declaration = _condition_na_declaration(
            project, step.get("condition_not_applicable"))
        result.reasons = [
            reason for reason in result.reasons
            if not str(reason).startswith("condition not met:")
        ]
        if declaration is not None:
            path, value = declaration
            result.reasons.insert(0, (
                f"design-declared NOT_APPLICABLE: {path} records "
                f"applicability={value!r}; condition remains "
                f"SKIPPED-CONDITION. Missing dependency artefact(s): "
                + (", ".join(missing) if missing else "none")
            ))
            continue

        blocked: List[Tuple[str, str, str]] = []
        for pattern in missing:
            producer = _condition_dependency_producer(step, pattern, specs)
            producer_label = producer or "UNDECLARED"
            upstream = by_id.get(producer_label)
            upstream_status = (upstream.status if upstream is not None
                               else "NOT_EVALUATED")
            blocked.append((producer_label, pattern, upstream_status))

        result.status = "MISSING"
        if blocked and blocked[0][0] != "UNDECLARED":
            result.cascade_note = f"blocked-by-upstream({blocked[0][0]})"
        if blocked:
            for producer, pattern, upstream_status in blocked:
                result.reasons.append(
                    f"blocked-by-upstream(step {producer}): required dependency "
                    f"artefact {pattern!r} is missing; upstream status="
                    f"{upstream_status}. No explicit design not-applicable "
                    f"declaration matched {step.get('condition_not_applicable')!r}, "
                    f"so dependency absence is not N/A/SKIP."
                )
        else:
            result.reasons.append(
                "dependency-required condition was unmet, but no missing "
                "files_exist branch was identified; refusing N/A/SKIP"
            )


def _condition_pattern_satisfied(project: Path, pat: str) -> bool:
    """True when ONE `files_exist` condition pattern is satisfied.

    For an ordinary pattern this is existence, unchanged.

    THE ANALOG BLOCK LIST IS DECIDED ON CONTENT, NOT EXISTENCE.
    The A1..A9 + M1..M4 stages are all triggered by
    `files_exist: [<...>/analog_block_list.json]`. That trigger used to be
    satisfied by the file merely BEING THERE, which asks "did anything write a
    block list" — a question ADJACENT to the one the condition exists to answer,
    "does this design have analog blocks to process". The two diverge on the
    exact input the flow most wants to reward: a Phase-1 extraction that looked
    for analog content, found none, and SAID SO by emitting

        {"blocks": [], "no_analog": true}

    Existence-only read that as "analog track applies", so all thirteen analog /
    mixed-signal steps were expected, none could ever produce an artefact for a
    design that has no analog block, and each landed as MISSING — i.e. as work
    that should have happened and did not. A digital project whose Phase 1 wrote
    NOTHING got SKIPPED-CONDITION for the same steps. The honest disclosure was
    scored strictly worse than silence, which inverts the incentive the
    disclosure exists to create.

    Note this function does not introduce the content test; the same module
    ALREADY has one (`_has_canonical_analog_blocks` requires a non-empty
    `blocks`/`analog_blocks` and honours `no_analog`). It was sitting two lines
    below as a FALLBACK, so it was only ever consulted when the file was absent
    — never in the case it was written for. This makes the primary path agree
    with the fallback that was already there.

    Direction of the change: this NARROWS the trigger (existence -> existence
    AND declares >=1 block). It cannot open an analog step that used to run:
    a block list naming real blocks still triggers the whole track, at the
    literal declared path or the canonical one, and an L9 `analog_modules`
    array still triggers it with no block list at all.

    Fail-LOUD on doubt: a block list that cannot be read or parsed is treated as
    TRIGGERING, exactly as before. Only a list that positively and parseably
    declares zero blocks stands the track down, so a corrupt or truncated list
    can never silently delete the analog track.

    chip-AGNOSTIC: JSON structure only — no chip, vendor, PDK or SKU literal.
    """
    hits = _glob_first(project, pat)
    if "analog_block_list" not in pat:
        return bool(hits)

    # PRE-FIX semantics, computed FIRST and held as a ONE-WAY CEILING. This
    # function is only ever allowed to NARROW: a project the existence-only
    # read stood the track DOWN on must still stand it down, whatever the
    # undecidable probe below finds. Without this the probe would WIDEN — a
    # project whose only block list is a dangling symlink resolves to no hit
    # (so pre-fix: SKIPPED-CONDITION) yet is present to `lexists` and
    # unreadable, so an unscoped probe would newly OPEN thirteen steps on it.
    # Restoring fail-loud must not become a licence to trigger.
    pre_fix_satisfied = (bool(hits)
                         or _l9_has_analog_modules(project)
                         or _has_canonical_analog_blocks(project))
    if not pre_fix_satisfied:
        return False

    for rel in hits:
        decl = _analog_block_list_declares_blocks(project / rel)
        if decl is not False:      # True (has blocks) or None (unreadable)
            return True
    # No resolved list declares blocks. The two historical fallbacks still
    # apply, and both are already content-aware.
    if _l9_has_analog_modules(project):
        return True
    # v0.2.55 — canonical-path tolerance. The analog runner writes the block
    # list to the canonical analog dir (`_pl.analog_dir` = phase3/analog/), but
    # the flow-def condition historically pins `phase1/analog/`. Accept the
    # canonical location too, and fall back to L5_ADI_SPEC's `analog_blocks`
    # array (Phase-1 doc-extraction emits it). chip-AGNOSTIC.
    if _has_canonical_analog_blocks(project):
        return True
    # Every list `_glob_first` RESOLVED parses cleanly and declares zero
    # blocks — but `_glob_first` short-circuits at the FIRST root that has a
    # file, so a list at the sibling reachable root was never even opened.
    # Before standing thirteen steps down, look there too.
    if _analog_trigger_undecidable(project, pat):
        return True
    return False


# ── Where an analog-block-list condition can actually SEE a list ────────────
# `_glob_first` resolves such a pattern at exactly TWO roots: the literal root
# the flow-def pins (`phase1/analog/`), and the canonical analog root
# `_pl.analog_dir()` (`phase3/analog/`) it re-probes when the pinned path
# misses. `phase2/analog/` and a bare `analog/` are remap SOURCES, never remap
# TARGETS, so a block list written at either is invisible to this condition at
# EVERY payload — measured False across the full payload grid.
#
# That deferral is deliberate and safe (it can only leave the track running,
# never stand it down), and widening `_glob_first`'s remap to cover those roots
# would touch every `phase{1,2,3}/analog/*` condition in the flow, so it is not
# this change's business. But a deferral is only honest while it is PINNED:
# this tuple, plus its characterization test, is that pin. If a future
# `_glob_first` change opens or re-closes a root, the pin fails loudly instead
# of the reachability silently drifting under the undecidable probe below.
#
# Only the DEFERRED set is a literal. The reachable set is pattern-relative and
# is therefore computed, by `_analog_block_list_probe_paths` below — a second
# hand-maintained list of it would be an unasserted constant free to drift from
# the behaviour it claims to describe, which is the very failure being fixed.
_ANALOG_BLOCK_LIST_ROOTS_DEFERRED = ("phase2/analog", "analog")


def _analog_block_list_probe_paths(project: Path, pat: str) -> List[Path]:
    """The block-list paths this pattern can reach.

    See the reachability note above for why the set is exactly these two.
    """
    if any(c in pat for c in "*?["):
        # A glob pattern has no single literal path to probe; `_glob_first`'s
        # own resolution is the whole answer for it. No analog condition in the
        # flow-def is a glob today; this is the honest degradation if one ever
        # is, and it degrades to pre-fix behaviour, not past it.
        return []
    paths = [project / pat]
    try:
        paths.append(_pl.analog_dir(project) / Path(pat).name)
    except Exception:
        pass
    out: List[Path] = []
    for p in paths:                       # de-dupe, order-preserving
        if p not in out:
            out.append(p)
    return out


def _analog_trigger_undecidable(project: Path, pat: str) -> bool:
    """Is some REACHABLE analog block list present but impossible to judge?

    `_glob_first` answers "which list did the pattern resolve to", and it
    short-circuits: the pinned root winning means the canonical root is never
    looked at. So a tree carrying BOTH a clean `{"blocks": []}` at the pinned
    root AND a corrupt or dangling list at the canonical root reads, through
    the resolved hit alone, as a positive declaration of no analog — and
    thirteen steps stand down on the strength of a file nobody could read.

    `lexists`, not `is_file`: a dangling symlink IS a list somebody put there
    and IS unreadable, which is the definition of undecidable. `is_file()` on
    it says False, i.e. "absent", which is precisely the wrong answer.

    Returning True here only ever KEEPS the track running (the caller has
    already established the pre-fix read was True), so this can add work to
    look at, never remove any. chip-AGNOSTIC: paths and JSON shape only.
    """
    for probe in _analog_block_list_probe_paths(project, pat):
        if not os.path.lexists(probe):
            continue
        if _analog_block_list_declares_blocks(probe) is None:
            return True
    return False


def _analog_block_list_declares_blocks(path: Path) -> Optional[bool]:
    """Does this analog block list declare at least one block?

    True  — a non-empty `blocks` / `analog_blocks` array.
    False — parsed cleanly and positively declares none: an empty
            `blocks` / `analog_blocks` array, OR a bare `no_analog: true`
            with no block array at all.
    None  — could not be read or parsed; the caller must NOT read that as
            "no analog". Unreadable is not evidence of absence.
    """
    try:
        d = json.loads(path.read_text())
    except Exception:
        return None
    if not isinstance(d, dict):
        return None
    blocks = d.get("blocks")
    if blocks is None:
        blocks = d.get("analog_blocks")
    if not isinstance(blocks, list):
        # No usable block array. A bare `no_analog: true` is nonetheless a
        # PARSEABLE, AFFIRMATIVE declaration of none — the strongest one the
        # schema has — so it is decidable, not undecidable. Reading it as
        # "unknown shape" re-creates for the flag-only form the exact defect
        # this whole guard exists to fix: the emitters' A-step gates already
        # stand down on it (`_analog_a_check_common.load_block_list` yields
        # [] -> VACUOUS_PASS "no analog blocks declared"), so the flow would
        # hold thirteen steps applicable that every gate certifies as
        # inapplicable, and each would land MISSING on a design with no
        # analog work TO do.
        #
        # Scoped as narrowly as the evidence allows, to keep the fail-LOUD
        # property intact: the flag decides ONLY when NEITHER block key is
        # present (`blocks is None` after both lookups). A block array that
        # is present but MALFORMED (`"blocks": "oops"`) contradicts the flag,
        # and a self-contradictory list stays undecidable so somebody has to
        # look at it — the same polarity as the named-block-beats-the-flag
        # rule below.
        if blocks is None and d.get("no_analog") is True:
            return False
        return None
    # A named block WINS over a `no_analog` flag that contradicts it. The two
    # disagreeing is a Phase-1 defect, and the non-suppressive reading of a
    # self-contradictory list is the one that keeps the analog track running so
    # somebody has to look at it.
    if len(blocks) > 0:
        return True
    return False


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


#: A declared output whose own machine-readable ``verdict`` field says the
#: producing run FAILED. Same #433c verdict-self-report contract the
#: SKIPPED-CONDITION branch below already honours, read off the same field of
#: the same already-parsed document — only the value differs.
#:
#: MEASURED, and this is why it exists (63x9 matrix, dimension 8, 2026-08-19):
#: over the 16 steps whose REAL gate reaches a PASS tier on a synthesized tree,
#: rewriting every declared JSON output to self-report SKIPPED-CONDITION moved
#: the verdict on 3 of the 3 that reach a plain PASS — the channel works — while
#: rewriting the SAME files, at the SAME field, to self-report FAIL moved
#: 0 of 16. `check_step` opened the artefact, parsed it, read `verdict`,
#: compared it against exactly one value and reported the step green on an
#: output whose own content says the run failed.
#:
#: BLOCKING. A step whose declared output self-reports FAIL resolves to FAIL,
#: which stops a strict flow. It is a DEMOTION rule and can only ever move a
#: plain PASS downwards: it never creates, promotes or waives a verdict.
#:
#: Deliberately NARROW: only the ``verdict`` field (the one this scan already
#: reads), only on a plain PASS (the tier this scan already guards), only these
#: three values. `status`, `summary.*` and the wider SELF_SKIP vocabulary that
#: `test_matrix_d6_skip_discipline.SELF_SKIP_VERDICTS` recognises are NOT read
#: here, and that limit is stated rather than left to be discovered.
_SELF_FAIL_VERDICTS = frozenset({"FAIL", "FAILED", "FAILURE"})


def _evidence_integrity_scan(project: Path,
                             result: "StepResult") -> "StepResult":
    if result.status != "PASS" or not result.evidence:
        return result
    stub_hits: List[str] = []
    broken: List[str] = []
    self_skipped: List[str] = []
    self_failed: List[str] = []
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
                _verdict = str(d.get("verdict", "")).upper().replace("_", "-")
                if _verdict in _SELF_FAIL_VERDICTS:
                    self_failed.append(f"{rel}: verdict={d.get('verdict')!r}")
                    continue
                if _verdict == "SKIPPED-CONDITION":
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
    # Both buckets resolve to FAIL, so they are reported TOGETHER rather than
    # through an elif: a step can carry a 0-byte artefact AND another whose
    # verdict says FAIL, and an elif would silently drop one of the two
    # reasons while the status stayed the same. Nothing about the pre-existing
    # EVIDENCE_MISSING branch changes when `self_failed` is empty.
    if self_failed or broken:
        result.status = "FAIL"
        if self_failed:
            result.reasons.append(
                "VERDICT_SELF_REPORTS_FAIL (#433c): declared output(s) carry a "
                "machine-readable verdict saying the run FAILED — a PASS "
                "contradicted by its own evidence is not a PASS: "
                + "; ".join(self_failed[:4]))
        if broken:
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


def _gate_json_targets(step: Dict[str, Any]) -> Set[str]:
    """Project-relative paths THIS step's own gate writes via ``--json``.

    Walks the whole gate tree, so `all_of` / `any_of` nesting and both the
    string and the mapping (`optional_program_exit_zero: {command: ...}`)
    spellings are covered. Returned paths are compared verbatim against
    `required_outputs` entries — an entry is only re-probed after the gate when
    the step itself declares that exact string as a gate output, never on a
    fuzzy match.
    """
    targets: Set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, val in node.items():
                if key.endswith("program_exit_zero"):
                    cmd = val if isinstance(val, str) else str(
                        (val or {}).get("command", ""))
                    toks = cmd.split()
                    for i, tok in enumerate(toks[:-1]):
                        if tok == "--json":
                            targets.add(toks[i + 1])
                else:
                    walk(val)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(step.get("gate") or {})
    return targets


def _outputs_read_by_in_scope_steps(sid, my_outputs, manifest):
    """Which of `my_outputs` does an IN-SCOPE step declare it READS?

    In-scope = not itself declared upstream of the run's entry. Those are the
    only consumers whose starvation this run could actually cause, and they are
    the ones the anti-laundering rule protects: an output nobody in scope reads
    cannot starve anything, an output someone in scope reads must be present.

    Loads the flow itself — `check_step` receives one step, not the flow — and
    fails CLOSED: if the flow cannot be read, every output is treated as
    consumed, so an unreadable flow refuses to excuse rather than excusing
    everything.
    """
    try:
        import yaml as _y                          # noqa: PLC0415
        flow = _y.safe_load(DEFAULT_FLOW_DEF.read_text(errors="replace"))
        steps = (flow or {}).get("steps") or []
        if not steps:
            return list(my_outputs)
    except Exception:
        return list(my_outputs)
    upstream = {str(u.get("id")) for u in (manifest.get("upstream_steps") or [])
                if isinstance(u, dict)}
    wanted = set()
    for st in steps:
        if not isinstance(st, dict):
            continue
        if str(st.get("id")) in upstream:
            continue                       # also out of scope — not a consumer
        for ri in (st.get("required_inputs") or []):
            if not isinstance(ri, dict):
                continue
            if str(ri.get("from")) != str(sid):
                continue
            pth = ri.get("path")
            if pth:
                wanted.add(str(pth))
            elif str(ri.get("outputs")) == "all":
                wanted.update(str(o) for o in my_outputs)
    return [o for o in my_outputs if o in wanted]


def _json_path_values(value: Any, dotted_path: str) -> List[Any]:
    """Read a dotted JSON path; ``*`` expands every list/dict child."""
    values = [value]
    for part in str(dotted_path).split("."):
        next_values: List[Any] = []
        for current in values:
            if part == "*":
                if isinstance(current, dict):
                    next_values.extend(current.values())
                elif isinstance(current, list):
                    next_values.extend(current)
            elif isinstance(current, dict) and part in current:
                next_values.append(current[part])
        values = next_values
    return values


def _collect_program_output_records(project: Path,
                                    step: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Read declared producer/classifier outputs without executing a gate."""
    records: List[Dict[str, Any]] = []
    for spec in step.get("program_outputs", []) or []:
        if not isinstance(spec, dict):
            continue
        program = str(spec.get("program") or "").strip()
        rel = str(spec.get("path") or "").strip()
        if not program or not rel:
            continue
        path = Path(rel)
        if path.is_absolute():
            produced = False
            data = None
        else:
            path = project / path
            try:
                produced = path.is_file() and path.stat().st_size > 0
                data = (json.loads(path.read_text(errors="replace"))
                        if produced else None)
            except Exception:
                produced = False
                data = None
        verdict: Any = "NOT_PRODUCED"
        if produced:
            verdict = "PRODUCED"
            field_name = spec.get("verdict_field")
            if field_name:
                found = _json_path_values(data, str(field_name))
                if found:
                    verdict = found[0]
        verdict_token = (verdict.strip().upper().replace("_", "-")
                         if isinstance(verdict, str) else "")
        reason_class = _reason_taxonomy.report_reason_class(data)
        if (reason_class is None
                and (verdict_token in _ADVISORY_SKIP_VERDICTS
                     or verdict_token in _ADVISORY_INCOMPLETE_VERDICTS
                     or verdict_token == "BLOCKED")):
            reason_class = _reason_taxonomy.infer_nonverdict_reason(
                verdict=verdict_token,
                message=_report_reason_text(data))
        record: Dict[str, Any] = {
            "program": program,
            "path": rel,
            "produced": produced,
            "verdict": (verdict.strip().upper()
                        if isinstance(verdict, str) else verdict),
            "reason_class": reason_class,
            "role": "PRODUCER_OUTPUT",
            "enforcement": "NOT_A_GATE",
        }
        finding_values: List[Any] = []
        for finding_path in spec.get("finding_fields", []) or []:
            finding_values.extend(_json_path_values(data, str(finding_path)))
        if finding_values:
            record["findings"] = sorted({
                json.dumps(v, sort_keys=True) if isinstance(v, (dict, list))
                else str(v)
                for v in finding_values
            })
        records.append(record)
    return records


def check_step(project: Path, step: Dict[str, Any], waivers: Dict,
               skip_analog: bool = False, skip_hardware: bool = False,
               strict_audit_evidence: bool = True) -> StepResult:
    # Kept as an API-compatibility argument for callers that adopted the
    # 2026-07-28 opt-in.  There is deliberately no lenient branch any more:
    # an audit-created artefact is never run evidence, even when a legacy
    # caller explicitly passes False.
    _ = strict_audit_evidence
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
    result.program_output_records = _collect_program_output_records(
        project, step)

    # Ownership, not resemblance: the flow's declared `stage`, not the first
    # letter of the id. Byte-identical on the shipped flow (A1..A9 all declare
    # `stage: stage_analog`); tightening only — a step that merely SPELLS like
    # an analog one keeps gating. See `_step_owned_by_analog_track`.
    if skip_analog and _step_owned_by_analog_track(step):
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

    # A9 is the ANALOG bench-hardware step, and the allowlist entry that exempts
    # its hw-correlation sub-gate calls it "the analog analogue of
    # --skip-hardware" in as many words. That analogy was never implemented: the
    # routing above is guarded by `isinstance(sid, int)`, and A9's id is the
    # STRING "A9", so --skip-hardware silently did nothing for it. Step 6 landed
    # in the report as WAIVED with review_required while A9 — the step that
    # needs a lab bench — disclosed nothing at all. Same run mode, same absent
    # hardware, two different stories. This states A9's, using the same tier.
    if skip_hardware and str(sid) in _ANALOG_BENCH_STEP_IDS:
        result.status = "WAIVED"
        result.reasons.append(
            "analog bench-hardware step waived via --skip-hardware: no lab "
            "measurement for a headless doc→GDS run (review_required before "
            "silicon sign-off; cosim/SPICE, GDS/DRC/LVS unaffected)")
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
    #
    # EACH declared entry must be satisfied — the list is ALL-of-N, exactly as
    # this module's own docstring has always said ("verifies every step has:
    # (a) all required_outputs present"). Only the " OR " *inside* one entry is
    # any-of, because that spelling is how the flow yaml declares one artefact
    # that legitimately has two accepted names/locations.
    #
    # It used to be any-of-N: evidence was accumulated across entries and
    # MISSING fired only when the COMBINED evidence list was empty, so a step
    # declaring five outputs passed this check on the strength of one. Measured
    # on the real spm x ihp-sg13g2 converge run: Step 21's declared drc.rpt did
    # not exist and the step reported PASS because routed.def did; Step 9's
    # area.rpt AND stats.json were both absent and it reported PASS because
    # netlist.v was there. A declared output nobody verifies is not a
    # requirement, and a step that never produced it has not been measured.
    #
    # RESOLVED PER STEP (see `_resolve_required_output`). The question asked
    # of each entry is no longer "does a file matching this glob exist
    # somewhere under the project" but "does THIS step's own folder record
    # this artefact as written, and is it still one". A run with no `steps/`
    # tree — every published cell, every phase-driven run — falls back to the
    # project-wide glob UNCHANGED and the fallback is recorded in
    # `output_binding`, never taken silently.
    outputs = step.get("required_outputs", [])
    missing_entries: List[str] = []
    _binding = _load_step_binding(project) if outputs else None
    _bind_notes: List[str] = []
    _bind_modes: Dict[str, str] = {}
    _bind_specs: List[Dict[str, Any]] = []
    _n_attr = 0
    _n_glob = 0
    for pat in outputs:
        _sat, _ev, _mode, _note, _detail = _resolve_required_output(
            project, sid, pat, _binding or {})
        _bind_modes[pat] = _mode
        if _mode == "step_attributed":
            _n_attr += 1
        else:
            _n_glob += 1
        # TYPED, per spec — the half of `mixed` a machine can branch on.
        # `mode` alone conflated "this run predates the record" with "the
        # green rests on a file this step never recorded writing", and the
        # only place the difference lived was a sentence in `notes`.
        _bind_specs.append(dict(_detail, spec=pat, mode=_mode,
                                satisfied=bool(_sat)))
        if _note:
            _bind_notes.append(f"{pat}: {_note}")
        if _sat:
            result.evidence.extend(_ev)
        else:
            missing_entries.append(pat)
    if outputs:
        _src = None
        if _binding and _binding.get("available"):
            _src = (_binding.get("sources") or {}).get(str(sid))
        elif _binding:
            # RUN-LEVEL degradation (no steps/ tree at all, unreadable index).
            # One note, not one per spec: the reason is a property of the run,
            # and repeating it 14 times for step D1 would bury the per-spec
            # notes that ARE per-spec under a wall of the same sentence.
            _bind_notes = [f"whole run: {_binding.get('reason')}"]
        result.output_binding = {
            "mode": ("step_attributed" if _n_glob == 0 else
                     "project_glob" if _n_attr == 0 else "mixed"),
            "n_specs": len(outputs), "n_step_attributed": _n_attr,
            "n_project_glob": _n_glob, "source": _src,
            # `codes` is the machine handle: a closed vocabulary (see
            # `_bind_detail`) that says WHICH degradation `mixed` is made of.
            # A consumer asks `"wildcard_unbound" in codes`, not "does the
            # note contain the word credited".
            "codes": sorted({str(d.get("code")) for d in _bind_specs}),
            "specs": _bind_specs[:16],
            "notes": _bind_notes[:12],
        }

    # PARTIAL evidence keeps the gate in play. Two different promotions live
    # downstream of here and both must survive: the gate's own per-file
    # disclosed-skip (#675 loose form, which turns an honestly-declared
    # capability gap into SKIPPED-CONDITION) and its ordinary FAIL. Returning
    # MISSING right here would pre-empt both — an honest skip would read as a
    # silent absence, and a step whose gate detects a real defect would stop
    # reporting that defect. So when SOME declared outputs are present, fall
    # through, and only downgrade a PASS-tier gate verdict afterwards (see
    # `_missing_entries` handling below the gate): a gate may explain an absent
    # output, it may not certify the step as done without one.
    # ── WITHDRAWN 2026-07-28: the "gate is the sole producer" exemption ────
    # A previous change suppressed this early return whenever EVERY missing
    # entry was one of the step's own gate `--json` targets, so the gate would
    # run and the re-probe below could see what it wrote. That is
    # self-certification: `check_step` ran the gate, the gate created the
    # declared output, and the post-gate probe accepted the file THE AUDIT HAD
    # JUST CREATED as the evidence that the step is done. MEASURED on a copy of
    # a published run root (benchmark-data/ic/ibex): step 8 went from MISSING
    # to PASS with `evidence=['reports/phase2/sdc_check.json']` and that same
    # path in the audit's own created-file list — a step whose declared output
    # 12 other tracked roots really do carry, certified on a file the auditor
    # wrote. Same flip on benchmark-data/ic/opentitan_aes and on
    # benchmark-data/evaluation/cvdp/run_v0153_runner/fixed_priority_arbiter.
    # The exemption was justified as reaching one step and reached four
    # (2, 8, 36, FS1) — every step of that SHAPE, not the one it was written
    # for. An auditor may never accept, as evidence, an artefact it caused to
    # exist during its own run, so the early return stands UNCONDITIONALLY: a
    # step ALL of whose declared outputs only its own gate writes stays MISSING
    # until something other than the audit produces one. That is a flow-WIRING
    # statement about the step, and answering it by letting the auditor write
    # the file is answering it with the auditor. The narrower PARTIAL case
    # (some declared outputs already present, one more written by the gate
    # during the audit) is tagged audit_created and refused by default below;
    # the legacy flag cannot weaken that rule.
    if outputs and missing_entries and not result.evidence:
        result.status = "MISSING"
        result.reasons.append(
            f"no required_outputs found (expected: {outputs})")
        _own_audit_targets = _gate_json_targets(step)
        _own_audit_missing = sorted(
            pat for pat in missing_entries if pat in _own_audit_targets)
        if _own_audit_missing:
            result.reasons.append(
                f"PRODUCER GAP: declared output(s) {_own_audit_missing} were "
                f"absent at audit start and are also this step's own audit "
                f"gate output target(s). The auditor will not run that gate "
                f"to manufacture completion evidence; wire a pre-audit "
                f"producer into the owning runner.")
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
            # absent output (self-skip verdict + a capability_flag REGISTERED in
            # `_DECLARED_CAPABILITY_GAP_FLAGS` + a `skips_required_output`
            # matching one of THIS step's missing patterns), so a step-12 marker
            # can never mask a step-9 synth FAIL and no marker can mask a
            # DRC/LVS sign-off. A marker lacking the ownership claim, naming a
            # different output, or claiming a gap the platform does not declare
            # open, stays MISSING.
            # Only the entries that ACTUALLY missed — under ALL-of-N some of
            # `outputs` may be present, and a sibling marker can only excuse the
            # artefact it names as absent.
            missing_pats = [sp for pat in missing_entries
                            for sp in (p.strip() for p in pat.split(" OR "))]
            skip_hint = _declared_sibling_self_skip_for_missing(
                project, missing_pats)
            if skip_hint:
                result.status = "SKIPPED-CONDITION"
                result.self_skip_disclosed = True   # DFT_FCC / 11-d7
                result.reasons.append(
                    "SKIPPED-CONDITION: canonical output absent but a co-located "
                    "sibling that OWNS it honestly self-reports a disclosed "
                    f"capability-gap skip (#675 strict): {skip_hint}")
                # ── The step's DECLARED gate is not the thing that produced
                # this verdict, and until now the report never said so.
                # Measured on the real spm x ihp-sg13g2 converge run: steps 29
                # and 30 reported SKIPPED-CONDITION with reasons that never
                # named post_layout_sim_check / spice_correlation_check, while
                # running either program directly on the same project returned
                # rc=1 — i.e. the declared gate was dead code on this path, and
                # a reader had no way to tell whether it had run and agreed.
                #
                # The gate is NOT re-run to decide the verdict here, and the
                # status is NOT changed: this early-return fires only when ALL
                # of the step's declared outputs are absent AND a sibling
                # marker unambiguously OWNS them with a named capability flag,
                # which is precisely the disclosed capability-gap skip #675
                # exists to record. Its declared gate reads those same absent
                # outputs, so it can only restate the absence — running it to
                # produce a FAIL would replace an honest, named disclosure with
                # a defect claim that is really the same fact counted twice.
                # What was missing was the DISCLOSURE, so name the gate that
                # did not run and let a reviewer see the omission instead of
                # inferring agreement. ADVISORY: never blocks (#306).
                #
                # The summary — not `_declared_gate_commands` — decides
                # whether there is anything to disclose. A gate assembled only
                # out of `files_exist` / `json_field_true` has no program name,
                # and keying the disclosure off the program list meant the
                # ADVISORY fired on none of the steps this path actually
                # resolves. Empty summary ⇒ the step genuinely declares no gate
                # and there is nothing that failed to run.
                _dead_gate = _declared_gate_summary(step.get("gate"))
                if _dead_gate:
                    result.reasons.append(
                        f"ADVISORY (non-blocking, #306): declared gate "
                        f"{_dead_gate} was NOT evaluated for this step — the "
                        f"disclosed capability-gap skip above resolved it. The "
                        f"gate audits the same absent output(s) the sibling "
                        f"marker owns, so its verdict would restate that "
                        f"absence, not add a finding.")
        return _apply_capability_gap(
            _evidence_integrity_scan(project, _disclose_output_binding(result)),
            sid)

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
        "optional_program_exit_zero", "advisory_program_exit_zero",
        "files_exist", "json_field_true",
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

    # ── 2026-07-28: name the evidence this audit authored itself ──────────
    # A `required_outputs` entry that is ALSO one of this step's own gate
    # `--json` targets is the one shape where evaluating the step CREATES the
    # artefact whose presence then decides it. Which entries were absent when
    # the audit began is recorded HERE, before the gate runs, because that is
    # the only moment at which the question "did the RUN produce this?" can
    # still be answered — after the gate it is unanswerable, and the post-gate
    # probe below has always been answering it with the auditor's own output.
    # `_audit_produced` (computed after the gate) is that answer, kept.
    _declared_self_written = sorted(set(outputs) & _gate_json_targets(step))
    _absent_before_gate = [rel for rel in _declared_self_written
                           if not (project / rel).exists()]
    _audit_produced: List[str] = []
    if gate:
        # GAP-B (#789) — thread the run's skip_analog into the gate evaluation
        # so an analog-aware optional/required gate (#773) is invoked WITH
        # --skip-analog when the analog track is explicitly deferred. The P0
        # umbrella (#632) + final_audit (#609) already honour the flag; this
        # closes the per-step optional/required gate wiring gap. No-op when
        # skip_analog is False.
        passed, reasons = _evaluate_gate(project, gate, skip_analog=skip_analog)
        _audit_produced = [rel for rel in _absent_before_gate
                           if (project / rel).exists()]
        if _audit_produced:
            # IDEMPOTENCE. Refusing the audit's own output is only a
            # measurement if the NEXT audit gets the same answer. Left on
            # disk, the file the gate just wrote is indistinguishable from run
            # evidence on the second pass, so the audit would report MISSING
            # once and PASS forever after — a verdict that depends on how many
            # times the auditor has run. Remove exactly what this invocation
            # created (never a file that was already there, which is why
            # `_absent_before_gate` is captured BEFORE the gate) and leave the
            # tree as the run left it.
            for _rel in list(_audit_produced):
                try:
                    (project / _rel).unlink()
                except OSError as _exc:
                    # Unmeasured is not zero: say so rather than let a stale
                    # file quietly become next run's evidence.
                    result.reasons.append(
                        f"WARNING: could not remove audit-created output "
                        f"{_rel} ({_exc}); this invocation still excludes it, "
                        f"but a later audit cannot distinguish the leftover "
                        f"from pre-existing run evidence")
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
        # Human prose for a structured nonblocking warning. Refusals are plain
        # failure reasons and therefore never reach this held-out bucket.
        advisory_hints = [r for r in reasons
                          if r.startswith(_ADVISORY_HINT_PREFIX)]
        advisory_record_hints = [
            r for r in reasons
            if r.startswith(_ADVISORY_RECORD_HINT_PREFIX)]
        for h in advisory_record_hints:
            try:
                rec = json.loads(h[len(_ADVISORY_RECORD_HINT_PREFIX):])
            except (TypeError, ValueError):
                rec = None
            if isinstance(rec, dict):
                result.advisory_gate_records.append(rec)
        # W4 — a clause whose `condition_files_exist` matched nothing, which
        # therefore ran no program and concluded nothing, and which DECLARED
        # why that is a genuine not-applicable. Held out here and re-appended
        # visibly below, exactly like `advisory_hints`: it must not become a
        # reason a step failed, and it must not silently vanish either. It
        # deliberately does not move the tier — see `_NOT_APPLICABLE_HINT_PREFIX`.
        na_hints = [r for r in reasons
                    if r.startswith(_NOT_APPLICABLE_HINT_PREFIX)]
        # The structure-only disclosure is NOT a reason the step failed and
        # NOT a reason it passed; it says what the step produced. It is read
        # on both paths and never suppresses another verdict.
        structure_only_hints = [r for r in reasons
                                if r.startswith(_STRUCTURE_ONLY_HINT_PREFIX)]
        if structure_only_hints:
            result.structure_only_disclosed = True
            for h in structure_only_hints:
                result.reasons.append(
                    f"STRUCTURE-ONLY: a declared artefact of this step was "
                    f"produced from a library default, not from a bound "
                    f"input — {h[len(_STRUCTURE_ONLY_HINT_PREFIX):]}")
        # #599 — the two words the roll-up did not have.
        substantive_hints = [r for r in reasons
                             if r.startswith(_SUBSTANTIVE_HINT_PREFIX)]
        incomplete_hints = [r for r in reasons
                            if r.startswith(_INCOMPLETE_HINT_PREFIX)]
        # vibe-ic#901 - the DENOMINATOR: clauses that dispatched a gate program.
        # Predicate-only clauses (`files_exist`, `json_field_true`) are
        # deliberately NOT counted: they cannot populate the numerator, so
        # counting them would let a step leave the vacuous tier without any
        # clause having said it examined anything.
        ran_hints = [r for r in reasons
                     if r.startswith(_RAN_HINT_PREFIX)]
        # vibe-ic#901 - the NUMERATOR contributed by the structured channel,
        # kept apart from the legacy bucket above so it cannot alter any tier
        # the legacy bucket already decides.
        json_vacuous_hints = [r for r in reasons
                              if r.startswith(_JSON_VACUOUS_HINT_PREFIX)]
        # Every clause that disclosed emptiness, by whichever channel, without
        # double-counting a clause that used both.
        all_vacuous_cmds = {r[len(_VACUOUS_HINT_PREFIX):] for r in vacuous_hints}
        all_vacuous_cmds |= {r[len(_JSON_VACUOUS_HINT_PREFIX):]
                             for r in json_vacuous_hints}
        non_hint_reasons = [r for r in reasons
                            if not r.startswith(_RAN_HINT_PREFIX)
                            and not r.startswith(_JSON_VACUOUS_HINT_PREFIX)
                            and not r.startswith(_VACUOUS_HINT_PREFIX)
                            and not r.startswith(_SKIP_HINT_PREFIX)
                            and not r.startswith(_WAIVER_HINT_PREFIX)
                            and not r.startswith(_STRUCTURE_ONLY_HINT_PREFIX)
                            and not r.startswith(_ADVISORY_HINT_PREFIX)
                            and not r.startswith(_ADVISORY_RECORD_HINT_PREFIX)
                            and not r.startswith(_SUBSTANTIVE_HINT_PREFIX)
                            and not r.startswith(_INCOMPLETE_HINT_PREFIX)
                            and not r.startswith(_NOT_APPLICABLE_HINT_PREFIX)]
        if passed and incomplete_hints and not non_hint_reasons:
            # An applicable question that was not examined outranks every
            # benign non-pass tier beside it.  In particular, a declared N/A
            # sibling or a waiver must not launder the incomplete clause into
            # SKIPPED-CONDITION / WAIVED.
            result.status = "INCOMPLETE"
            for h in incomplete_hints:
                result.reasons.append(
                    f"INCOMPLETE: the gate reports its input was applicable "
                    f"and was NOT examined: "
                    f"{h[len(_INCOMPLETE_HINT_PREFIX):]}")
        elif (passed and waiver_hints and not non_hint_reasons
                and not skip_hints):
            # WAIVED here means "DEFERRED via waiver": it leaves the required
            # denominator the same way an explicit waivers.json entry does and
            # drives Overall → PASS_WITH_WAIVERS. The gate DID pass its
            # threshold; the WITH_WAIVERS distinction is the whole point (#651).
            #
            # `not vacuous_hints` REMOVED — the same masking #675 removed from
            # the `skip_hints` branch immediately below, two branches apart in
            # this same chain, left in place here.
            #
            # A WAIVER IS MORE SPECIFIC THAN A VACUOUS PASS, for the reason
            # this file states in its own words: "a vacuous step is one nobody
            # needs to come back to". A step credited via a waiver is one
            # somebody MUST come back to -- production tapeout review has to
            # close it. When an `all_of` step carried both hints the waiver
            # branch was skipped and the step fell through to VACUOUS_PASS,
            # which erased the review_required obligation AND removed the step
            # from the WAIVED-DEFERRED tally a reviewer reads.
            #
            # MEASURED on the #460 oracle replica (Step 4, no verilator):
            #   verilator_coverage_measure  rc=3  PASS_WITH_WAIVERS   <- waiver
            #   vacuous_testbench_check     rc=2  VACUOUS_PASS        <- vacuous
            #   professional_tb_check       rc=0  VACUOUS_PASS
            # and the step rendered `○ [VACUOUS-PASS]`, tallying
            # WAIVED-DEFERRED=0 for a run that had one. Both hints are true;
            # the label can carry one, and it must be the one that says
            # somebody owes an answer.
            #
            # Aggregation is unchanged for every step that has no waiver hint,
            # and this can only ever move a step OUT of VACUOUS_PASS and INTO
            # WAIVED -- both sit outside the executed-PASS numerator and inside
            # `total_required`, so no numerator moves and nothing turns green
            # that was not already passing.
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
            result.self_skip_disclosed = True   # DFT_FCC / 11-d7
            for h in skip_hints:
                result.reasons.append(
                    f"SKIPPED-CONDITION: gate evidence self-reports a skip "
                    f"(#608/#675): {h[len(_SKIP_HINT_PREFIX):]}")
        elif (passed and vacuous_hints and substantive_hints
                and not non_hint_reasons and not skip_hints):
            # #599 step 14. The gate printed `VACUOUS_PASS:` because the
            # artefact it normally audits was absent, and in the same breath
            # reported that it verified the equivalent by another route — for
            # `yosys_hilomap_required_check`, the runner's inline `yosys -p`
            # command instead of a `.ys` script. Its docstring keeps the vacuous
            # word deliberately, so the gate is not what is wrong; the roll-up
            # simply never read the second half. A substantive verification is a
            # PASS.
            result.status = "PASS"
            for h in substantive_hints:
                result.reasons.append(
                    f"substantive: the audited artefact was absent, and the "
                    f"gate verified the equivalent by another route: "
                    f"{h[len(_SUBSTANTIVE_HINT_PREFIX):]}")
        elif passed and vacuous_hints and not non_hint_reasons and not skip_hints:
            # vibe-ic#901, 2026-08-22 — THE THIRD WORD. WHY IT EXISTS AND WHY
            # IT IS SAFE.
            #
            # This branch used to grant one word, `VACUOUS_PASS`, whose meaning
            # is "every executed sub-gate was vacuously satisfied". #901 built
            # the count that decides whether that sentence is TRUE and wired it
            # to the structured channel only, so the legacy channel kept saying
            # it unconditionally. On the shipped step 4 over a tree whose
            # simulation ran — real results.xml, testbenches that drive the
            # unit, coverage measured at line=97.37% — the sentence was FALSE:
            # 4 clauses ran, 3 read real content, 1 examined nothing.
            #
            # TWO LANDED REQUIREMENTS SAT ON OPPOSITE SIDES OF THAT, and the
            # collision is real, not a misunderstanding:
            #   step 4  must not be called "every sub-gate was vacuous"
            #           (test_GUARD_the_shipped_step_is_not_vacuous_...)
            #   step A9 an analog step that closed in simulation with no bench
            #           measurement must NOT rejoin the executed-PASS numerator
            #           (test_a9_...::test_simulation_only_close_is_not_a_bare_pass)
            # Both are true statements about what a reader must not be told.
            # ONE word cannot carry both, which is why the answer is a word.
            #
            # THE ALTERNATIVE, MEASURED AND REJECTED. Splitting the channel by
            # exit code — rc=2 keeps the unconditional tier, rc=0 + printed
            # `VACUOUS_PASS:` joins the counted bucket — turns all 20 tests in
            # the #901 file green, guards included. It was still wrong: A9's
            # emitter is an rc=0 printer too, so A9 came out
            #     status=PASS, partial_vacuity_disclosed=True
            # i.e. disclosed on its own line and COUNTED IN `pass_count`
            # anyway, because `pass_count = counts["PASS"]` reads the word and
            # not the disclosure. A step held out of the numerator for cause
            # was handed back to it. Reverted.
            #
            # WHY THE THIRD WORD CANNOT DO THAT. The only status this branch
            # can now produce in place of `VACUOUS_PASS` is `PARTIALLY-VACUOUS`,
            # and neither is the string `"PASS"`. `pass_count` is
            # `counts["PASS"]` and nothing else, so this change CANNOT move any
            # step into or out of the executed-PASS numerator — not step 4, not
            # A9, not any of the five steps whose word can move at all. It
            # splits an existing bucket in two and leaves the numerator
            # identical to origin/main, which is exactly the property the
            # guards were written to protect and is asserted directly in them
            # now, instead of being approximated by pinning a label.
            unanimous = len(all_vacuous_cmds) >= len(ran_hints)
            # SPELLED AS TWO STATEMENTS, NOT A TERNARY, ON PURPOSE.
            # `test_issue634_flow_verdict_tiers::test_the_producers_vocabulary_
            # is_pinned` discovers this file's vocabulary by scanning its SOURCE
            # for status assignments to a quoted upper-case literal, which is
            # the anti-drift device that makes
            # a new tier a test failure instead of a silent escape. A ternary
            # puts the second word out of that regex's reach: the pin would then
            # report the word as "pinned, not in the producer" and, worse, the
            # NEXT tier added the same way would never be noticed at all. Two
            # plain assignments keep both words visible to the scanner.
            if unanimous:
                result.status = "VACUOUS_PASS"
            else:
                result.status = "PARTIALLY-VACUOUS"
            for h in vacuous_hints:
                # Strip the internal prefix; surface a human-friendly
                # diagnostic so reviewers see *why* it was vacuous.
                cmd = h[len(_VACUOUS_HINT_PREFIX):]
                if unanimous:
                    result.reasons.append(
                        f"vacuous: gate program signalled VACUOUS_PASS "
                        f"(input not applicable), and it is "
                        f"{len(all_vacuous_cmds)} of {len(ran_hints)} gate "
                        f"clause(s) that ran here: {cmd}"
                    )
                else:
                    # The same sentence the structured channel already prints
                    # below, from the same numerator and denominator, so a
                    # reader cannot tell which channel disclosed — nor should
                    # they have to.
                    result.partial_vacuity_disclosed = True
                    result.reasons.append(
                        f"PARTIALLY-VACUOUS ({len(all_vacuous_cmds)} of "
                        f"{max(len(ran_hints), len(all_vacuous_cmds))} gate "
                        f"clause(s) examined nothing): {cmd}"
                    )
        elif passed and structure_only_hints and not non_hint_reasons:
            # The step ran and produced its declared artefact — from a library
            # default. PASS would say the artefact is design-bound; it is not.
            result.status = "STRUCTURE-ONLY"
        elif (passed and json_vacuous_hints and not non_hint_reasons
                and not skip_hints
                and len(all_vacuous_cmds) >= len(ran_hints)):
            # vibe-ic#901 - the structured channel, COUNTED.
            #
            # Placed LAST on purpose: every other tier is resolved before this
            # branch is reached, so the only verdict this can ever displace is a
            # BARE PASS. It cannot take a step out of WAIVED, SKIPPED-CONDITION,
            # INCOMPLETE, STRUCTURE-ONLY or the legacy VACUOUS_PASS, and `passed`
            # being false falls through to the FAIL arm below - a FAIL can never
            # be silenced by a vacuous sibling.
            #
            # The count is what the first attempt lacked. `>=` and not `==`
            # because a vacuous clause may be reached by a path that emits no
            # RAN marker; the comparison may only ever WITHHOLD this tier from a
            # step some clause substantively examined, never grant it to one no
            # clause did.
            result.status = "VACUOUS_PASS"
            result.json_vacuity_promoted = True
            for c in sorted(all_vacuous_cmds):
                result.reasons.append(
                    f"vacuous: the gate's own --json report declares it "
                    f"examined nothing, and it is {len(all_vacuous_cmds)} of "
                    f"{len(ran_hints)} gate clause(s) that ran here: {c}")
        else:
            result.status = "PASS" if passed else "FAIL"
            result.reasons.extend(non_hint_reasons)
        # vibe-ic#901 - the tier is a per-STEP word and a partially vacuous step
        # has no such word: some of its clauses examined the design and some
        # examined nothing. Both facts are true and one label can carry only
        # one. Whichever tier resolved above, the clauses that disclosed
        # emptiness through the structured channel are named HERE - on the step
        # line, in `reasons`, in a typed field and in the tally - rather than
        # being dropped for failing to be unanimous.
        if result.status != "VACUOUS_PASS" and json_vacuous_hints:
            result.partial_vacuity_disclosed = True
            for h in json_vacuous_hints:
                result.reasons.append(
                    f"PARTIALLY-VACUOUS ({len(all_vacuous_cmds)} of "
                    f"{max(len(ran_hints), len(all_vacuous_cmds))} gate "
                    f"clause(s) examined nothing): "
                    f"{h[len(_JSON_VACUOUS_HINT_PREFIX):]}")
        # W4 — whatever tier was chosen, every clause that did NOT run because
        # its condition matched nothing is named on the step line and carried
        # into the JSON report, with the reason its wiring site declared. A
        # step whose gate list is half unexecuted must not read as a step whose
        # gate list was executed; the count is stated so a reader can see how
        # much of the declared gate actually spoke.
        if na_hints:
            result.declared_not_applicable = [
                h[len(_NOT_APPLICABLE_HINT_PREFIX):] for h in na_hints]
            for h in na_hints:
                result.reasons.append(
                    f"NOT-APPLICABLE (declared, {len(na_hints)} of "
                    f"{len(na_hints) + len(ran_hints)} gate clause(s) here "
                    f"examined nothing): {h[len(_NOT_APPLICABLE_HINT_PREFIX):]}")
        # #306 — whatever tier was chosen, the advisory verdicts are printed
        # on the step line and carried into the JSON report. An advisory gate
        # that ran and said nothing would make the run LOOK audited while
        # having reported no finding, which is the shape this repo removes
        # everywhere else.
        for h in advisory_hints:
            result.reasons.append(
                f"ADVISORY (non-blocking, #306): "
                f"{h[len(_ADVISORY_HINT_PREFIX):]}")
        for rec in result.advisory_gate_records:
            result.reasons.append(
                "GATE EVIDENCE: "
                f"{rec.get('gate')} rc={rec.get('exit_code')} "
                f"verdict={rec.get('verdict')} "
                f"reason_class={rec.get('reason_class')} "
                f"enforcement={rec.get('enforcement')}")
    else:
        # No gate — just presence of outputs counts
        result.status = "PASS" if result.evidence else "MISSING"

    # ── GATE-PRODUCED declared outputs: probed after the gate, and SAID ────
    # `missing_entries` above is computed BEFORE the gate runs, which is right
    # for every artefact an upstream step produced. It is wrong for the one
    # class of artefact the step's OWN GATE writes: the audit-trail file a gate
    # command names with `--json`. Such an entry would report MISSING on the
    # first evaluation of a project and PASS on the second, purely because the
    # first evaluation created it — a verdict that changes with how many times
    # it has been run is not a measurement.
    #
    # Scope is deliberately narrow: ONLY entries that appear verbatim as a
    # `--json <path>` argument in one of THIS step's own gate commands are
    # re-probed, and only after the gate has had its chance to write. An
    # artefact produced by any other step is untouched, so this cannot excuse a
    # genuinely absent upstream output. When the gate did not run at all (no
    # gate, or an early return above), nothing was written and the re-probe
    # simply finds nothing.
    #
    # 2026-07-28 — WHAT THIS CREDIT REALLY IS, now said out loud. An entry that
    # reaches here was absent before the gate; the only thing that ran in
    # between is the gate; so every hit the re-probe can get is an artefact
    # THIS AUDIT CREATED. Crediting it is self-certification, whether or not
    # the flow currently has an independent producer wired for other runs.
    # A population count cannot turn verifier output into pre-audit evidence:
    # missing producers are flow-WIRING gaps and stay MISSING until the runner
    # writes the declared artefacts before this auditor starts.
    #
    # The legacy `strict_audit_evidence` argument remains accepted so older
    # callers do not break, but it cannot weaken this invariant. Every
    # audit-created target is tagged below, excluded from evidence, and left
    # in `missing_entries` so a PASS-tier gate verdict becomes MISSING.
    if _audit_produced and result.output_binding:
        _ob = result.output_binding
        for _sp in _bind_specs:
            if _sp.get("spec") in _audit_produced:
                _sp["code"] = "audit_created"
                _sp["satisfied"] = False
                _sp["audit_created"] = _sp.get("spec")
                _sp.pop("credited", None)
        _ob["codes"] = sorted({str(d.get("code")) for d in _bind_specs})
        _ob["notes"] = (_ob["notes"] + [
            f"{rel}: audit_created; excluded from run evidence because it "
            f"was absent at audit start and this step's own gate wrote it"
            for rel in _audit_produced
        ])[:12]
    if missing_entries:
        _gate_written = _gate_json_targets(step)
        _still_missing: List[str] = []
        for pat in missing_entries:
            if pat in _gate_written and pat not in _audit_produced:
                hits = [h for sp in (p.strip() for p in pat.split(" OR "))
                        for h in _glob_first(project, sp)]
                if hits:
                    result.evidence.append(hits[0])
                    # This credit is PROJECT-WIDE by construction and can be
                    # nothing else: the artefact was absent when the audit
                    # began, so no write record made before the audit can name
                    # it. Counted as such so `output_binding` never reports a
                    # step-attributed total that includes an artefact this
                    # program itself caused to exist.
                    if result.output_binding:
                        _ob = result.output_binding
                        if _bind_modes.get(pat) == "step_attributed":
                            _bind_modes[pat] = "project_glob"
                            _ob["n_step_attributed"] -= 1
                            _ob["n_project_glob"] += 1
                        _ob["mode"] = ("step_attributed"
                                       if _ob["n_project_glob"] == 0 else
                                       "project_glob"
                                       if _ob["n_step_attributed"] == 0
                                       else "mixed")
                        # Retyped on `_bind_specs`, the UNTRUNCATED list —
                        # `_ob["specs"]` is a 16-entry slice of the same dicts
                        # and recomputing `codes` from the slice would drop
                        # the code of any spec past the cut.
                        for _sp in _bind_specs:
                            if _sp.get("spec") == pat:
                                _sp["code"] = "audit_created"
                                _sp["mode"] = "project_glob"
                                _sp["satisfied"] = True
                                _sp["credited"] = hits[0]
                        _ob["codes"] = sorted(
                            {str(d.get("code")) for d in _bind_specs})
                        _ob["notes"] = (_ob["notes"] + [
                            f"{pat}: credited to an artefact this audit's own "
                            f"gate created during this run"])[:12]
                    continue
            _still_missing.append(pat)
        missing_entries = _still_missing
    if _audit_produced:
        result.reasons.append(
            f"SELF-CERTIFIED EVIDENCE EXCLUDED (audit_created) "
            f"{_audit_produced} — this step's own gate created these declared "
            f"output(s) during THIS audit; they were absent when it began, so "
            f"they are evidence the auditor authored, not evidence the run "
            f"produced. PRODUCER GAP: no pre-audit producer supplied these "
            f"paths; wire them into the owning runner before claiming this "
            f"step complete. Refused by default and excluded from credited "
            f"run evidence.")

    # v1.6.269 (#126) — ENV_UNAVAILABLE fallback promotion. If the
    # ── required_outputs is ALL-of-N: a gate may not certify a step done
    # while one of its own declared outputs was never produced ────────────
    # Applied only to a PASS-tier verdict, and only when SOME evidence existed
    # (the all-absent case already returned MISSING above). Every other verdict
    # is left exactly as the gate produced it: SKIPPED-CONDITION is the #675
    # honest capability-gap disclosure, FAIL is a real defect the gate detected,
    # WAIVED is an approved deferral — replacing any of those with MISSING would
    # destroy information, not add rigour.
    #
    # Before this, evidence was pooled across the whole list and MISSING fired
    # only when NOTHING matched, so one present artefact carried the rest.
    # MEASURED on the real spm x ihp-sg13g2 run: Step 21 declared drc.rpt
    # (absent) + routed.def (present) and reported PASS; Step 9 declared
    # netlist.v (present) + "area.rpt OR stats.json" (both absent), PASS.
    # STRUCTURE-ONLY is a PASS-TIER verdict and is demoted here exactly like
    # the other two: the tier says the artefact's CONTENT came from a default,
    # which presupposes the artefact exists. A declared output that is absent
    # is MISSING whatever the gate said about the ones that are present.
    # DERIVED (vibe-ic#634). This used to enumerate the pass tiers and had
    # already fallen a tier behind: `INCOMPLETE` (#599) is a done-claim by the
    # same arithmetic and was not demoted, so a step that declared an output,
    # did not produce it, and reported INCOMPLETE kept its tier.
    # ── OUT-OF-SCOPE-BY-ENTRY (2026-08-25) ────────────────────────────────
    # Placed HERE — after the waiver branch, immediately before the all-absent
    # MISSING demotion — so it can excuse an un-run upstream step and can never
    # override a real FAIL, which is decided above and never reaches this line.
    #
    # A run may declare via --entry-step, BEFORE dispatching anything, that it
    # entered the flow partway through. Without a word for that, the upstream
    # steps report MISSING and the report reads exactly like a Phase 1 that ran
    # and broke — measured on a tree holding only phase2/stage1/sim/:
    #   D1 -> MISSING   (expected 19 files)
    #   1  -> MISSING   (expected phase2/stage1/rtl/*)
    #
    # THE LAUNDERING RISK IS THE WHOLE DESIGN PROBLEM. The manifest is written
    # by the run being judged, so unconstrained this flag turns MISSING into
    # PASS on demand — the run grading its own scope. `run_entry_manifest
    # .excusable` grants it only when ALL of:
    #   1. the step is upstream of the DECLARED entry,
    #   2. every output of it that an IN-SCOPE step declares it reads is
    #      PRESENT on disk (the anti-laundering rule: the artefacts must still
    #      BE there; the claim is only that this run did not produce them), and
    #   3. it declares no hard sign-off output — DRC/LVS/ERC/STA can never be
    #      excused by "we started late".
    if _T.is_done_claim(result.status) and missing_entries:
        try:
            import run_entry_manifest as _rem      # noqa: PLC0415
            _man = _rem.read(project)
        except ImportError:
            _man = None
        if _man is not None:
            _my_outputs = [str(o) for o in (step.get("required_outputs") or [])
                           if isinstance(o, (str, bytes))]
            _consumed = _outputs_read_by_in_scope_steps(sid, _my_outputs, _man)
            _verdict = _rem.excusable(_man, sid, _my_outputs,
                                      _consumed, project)
            if _verdict.get("excusable"):
                result.status = "OUT-OF-SCOPE-BY-ENTRY"
                result.reasons.append(
                    f"out of scope by declared entry: {_verdict['reason']}")
                return result
            result.reasons.append(
                "entry manifest present but does NOT excuse this step: "
                + str(_verdict.get("reason")))

    if _T.is_done_claim(result.status) and missing_entries:
        result.status = "MISSING"
        _by_record = [p for p in missing_entries
                      if _bind_modes.get(p) == "step_attributed"]
        result.reasons.append(
            f"required_outputs missing: {missing_entries} "
            f"(satisfied: {len(outputs) - len(missing_entries)}/{len(outputs)}"
            f" — the gate passed, but every declared output must be produced, "
            f"not just one)"
            + (f" — {len(_by_record)} of them on this step's OWN write record: "
               f"{_by_record}" if _by_record else ""))

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
    result = _evidence_integrity_scan(project, _disclose_output_binding(result))
    return _apply_capability_gap(result, sid)


def _attribute_condition_owner_blocks(
        project: Path,
        results: List["StepResult"],
        steps: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Refuse design-derived N/A until the condition's owner has resolved it.

    A condition normally answers a local yes/no question: when it is false,
    the step is ``SKIPPED-CONDITION``.  That is only sound when the fact the
    condition selects has already been established.  A route predicate is the
    counterexample: neither the chip marker nor the IP marker existing can
    mean either "the other path was selected" or "the route owner failed and
    selected nothing".  The file predicate alone cannot distinguish them.

    The flow declares that missing discriminator in two places:

    * the owner defines a named ``condition_declarations`` record containing
      the complete set of declaration alternatives; and
    * each dependent condition names it through ``condition_owner``.

    Only an owner ``PASS`` plus a valid declaration lets the dependent keep
    its natural verdict.  Every other state is a hard ``MISSING`` annotated
    ``blocked-by-upstream(<owner>)``.  ``MISSING`` is deliberate: it is the
    existing non-green upstream-blocked representation (#503), so this change
    cannot create a new, accidentally-unclassified verdict tier or subtract
    the row from the required denominator.

    BLOCKING, not advisory.  The original downstream verdict and evidence are
    retained in ``reasons`` so a real finding is not erased by attribution.
    Chip/PDK/vendor agnostic: every id, declaration name and path comes from
    the supplied flow definition.
    """
    by_id = {str(r.id): r for r in results}
    step_by_id = {str(st.get("id")): st for st in steps
                  if isinstance(st, dict) and st.get("id") is not None}
    blocked: List[Dict[str, Any]] = []
    counts: Dict[str, int] = {}

    for step in steps:
        if not isinstance(step, dict):
            continue
        owner_spec = step.get("condition_owner")
        if not isinstance(owner_spec, dict):
            continue
        sid = str(step.get("id"))
        row = by_id.get(sid)
        owner_id = str(owner_spec.get("step", "")).strip()
        declaration_name = str(owner_spec.get("declaration", "")).strip()
        owner_row = by_id.get(owner_id)

        # A scoped run may intentionally exclude the owner's stage.  Such a
        # report makes no verdict about that owner, so do not invent one.  The
        # full-flow report — the acceptance surface this relation protects —
        # always carries both rows.  Malformed in-scope metadata fails loudly
        # below rather than being treated as an absent owner.
        if row is None or owner_row is None:
            continue

        owner_step = step_by_id.get(owner_id)
        declarations = ((owner_step or {}).get("condition_declarations")
                        if isinstance(owner_step, dict) else None)
        declaration = (declarations.get(declaration_name)
                       if isinstance(declarations, dict) else None)
        patterns = (declaration.get("files_exist")
                    if isinstance(declaration, dict) else None)
        patterns = ([str(p) for p in patterns if isinstance(p, str) and p]
                    if isinstance(patterns, list) else [])
        exact_one = bool((declaration or {}).get("exactly_one")) \
            if isinstance(declaration, dict) else False
        matched = [p for p in patterns
                   if _condition_pattern_satisfied(project, p)]

        config_ok = bool(owner_id and declaration_name and patterns)
        declaration_ok = (len(matched) == 1 if exact_one else bool(matched))
        if (config_ok and owner_row.status == "PASS" and declaration_ok):
            continue

        if not config_ok:
            declaration_evidence = (
                f"condition-owner configuration is INVALID: Step {owner_id or '?'} "
                f"does not define non-empty declaration {declaration_name!r}")
        elif not matched:
            declaration_evidence = (
                f"{declaration_name} declaration is MISSING: none of "
                f"{patterns} exists")
        elif exact_one and len(matched) != 1:
            declaration_evidence = (
                f"{declaration_name} declaration is CONFLICTING: matched "
                f"{len(matched)} mutually exclusive alternatives {matched}")
        else:
            declaration_evidence = (
                f"{declaration_name} declaration is present as {matched[0]} "
                f"but the owner result is not authoritative")

        prior_status = row.status
        prior_reasons = list(row.reasons)
        primary = (
            f"blocked-by-upstream(step {owner_id}): condition owner Step "
            f"{owner_id} verdict {owner_row.status}; {declaration_evidence}. "
            f"Until the owner passes with an authoritative declaration, this "
            f"row's unmet predicate cannot be interpreted as design-derived "
            f"N/A.")
        row.status = "MISSING"
        row.cascade_note = f"blocked-by-upstream({owner_id})"
        row.reasons = [primary]
        if prior_reasons:
            row.reasons.append(
                f"downstream verdict before owner attribution was "
                f"{prior_status}: {prior_reasons[0]}")
            row.reasons.extend(prior_reasons[1:])
        row.evidence.append(
            f"condition-owner:{owner_id}/{declaration_name}; "
            f"owner_verdict={owner_row.status}; matched={matched}")
        blocked.append({"step": sid, "owner": owner_id,
                        "owner_verdict": owner_row.status,
                        "declaration": declaration_name,
                        "matched": matched,
                        "prior_status": prior_status})
        counts[owner_id] = counts.get(owner_id, 0) + 1

    return {"records": blocked, "blocked_by_upstream": counts}


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


# ── vibe-ic#776 — the declared-dependency relation ──────────────────────────
# `blocks_on` is an ORDERING edge and nothing more. The flow does have a way to
# say "this step reads that artefact", and it is used: a step DECLARES what it
# must produce (`required_outputs`) and its gate DECLARES what it reads
# (`condition_files_exist` / `files_exist` / `json_field_true.file`). A waiver
# may only be inherited across an edge where those two declarations MEET.
#
# MEASURED on the canonical 63-step flow (`flow/phase1_phase2_phase3.yaml`):
# 1221 (step, transitive-blocks_on-ancestor) pairs exist; exactly 6 carry a
# declared dependency —
#   2, 4, 8 <- D1   named L*.json docs, via `condition_files_exist`
#   2       <- 1    `phase2/stage1/rtl/*.sv` / `*.v`, via the lint gate's argv
#   14      <- 9    `phase2/stage2/synth/netlist.v`
#   34      <- 18   `phase3/stage3/pnr/spare_cells.json`
# Replaying every single-waiver scenario over an otherwise-all-MISSING run:
# the pre-#776 code converted 1153 (step, ancestor) pairs to
# DEFERRED-BY-UPSTREAM; this code converts the 6 above. (1153 rather than 1215
# because #600's known-gap stop was already refusing some of them.)
_FLOW_GATE_INPUT_KEYS = ("condition_files_exist", "files_exist", "file")
_FLOW_GATE_COMMAND_KEYS = ("program_exit_zero", "advisory_program_exit_zero",
                           "optional_program_exit_zero", "command")


def _flow_command_input_atoms(command: str) -> List[str]:
    """Path-shaped POSITIONAL arguments of a gate command — files the gate
    declares it reads.

    Conservative by construction: a token is taken only when it contains `/`,
    does not start with `-`, and is not the value of a `--option` (which is
    where this flow puts gate OUTPUTS, `--json` / `--out` / `--report`).

    MEASURED against the alternative of ignoring commands entirely: on the
    canonical flow this rule adds exactly ONE (step, ancestor) relation,
    `2 <- 1` on `phase2/stage1/rtl/*.sv` and `*.v` — the lint gate is literally
    spelled `rtl_hygiene_lint phase2/stage1/rtl/*.sv phase2/stage1/rtl/*.v` and
    step 1 declares producing exactly those two patterns. It adds no other
    pair, so on today's flow the heuristic admits no relation that is not an
    exact string match. A future flow edit that makes it admit a loose one is
    visible as a new pair in `test_declared_dependency_relation_is_small`.
    """
    tokens = command.split()
    out: List[str] = []
    for idx, tok in enumerate(tokens):
        if tok.startswith("-"):
            continue
        if idx > 0 and tokens[idx - 1].startswith("--"):
            continue
        if "/" in tok:
            out.append(tok)
    return out


def _flow_path_atoms(value: Any) -> List[str]:
    """Split the flow's own ` OR ` alternation notation into path atoms.

    Same reading `_check_files_exist` gives these patterns, so the relation is
    derived from the strings the checker itself resolves.
    """
    out: List[str] = []
    items = value if isinstance(value, (list, tuple)) else [value]
    for item in items:
        if not isinstance(item, str):
            continue
        for atom in item.split(" OR "):
            atom = atom.strip()
            if atom and atom != ".":
                out.append(atom)
    return out


@functools.lru_cache(maxsize=None)
def _flow_glob_re(pattern: str) -> "re.Pattern[str]":
    """`**` crosses `/`, `*` and `?` do not — `pathlib.Path.glob` semantics,
    which is what `_glob_first` actually runs."""
    parts: List[str] = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            parts.append(".*")
            i += 2
        elif pattern[i] == "*":
            parts.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            parts.append("[^/]")
            i += 1
        else:
            parts.append(re.escape(pattern[i]))
            i += 1
    return re.compile("^" + "".join(parts) + "$")


def _flow_paths_meet(a: str, b: str) -> bool:
    """True when two declared path patterns can name the same artefact."""
    if a == b:
        return True
    return bool(_flow_glob_re(a).match(b) or _flow_glob_re(b).match(a))


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

    #502 (waiver chain must propagate), as narrowed by #776: a MISSING
    step whose `blocks_on` ancestry (transitive) reaches a
    WAIVED-DEFERRED step **and which the flow DECLARES reads what that
    step must write** is the inevitable consequence of that SAME waiver.
    Verdict becomes DEFERRED-BY-UPSTREAM(parent, ticket): counted
    separately, excluded from strict MISSING (one waiver = one deduction,
    not two). A FAIL never converts — real counter-evidence survives.

    #776: `blocks_on` alone is NOT enough and never was. It is an
    ORDERING edge; on the canonical flow it makes 1221 transitive
    (step, ancestor) pairs of which exactly 6 carry a declared
    dependency. Waiving step 13 (LEC, whose declared outputs
    `reports/lec.{rpt,json}` no other step reads or produces) discounted
    37 downstream steps — the entire tail of the flow — on ordering
    alone. A waived ancestor with no declared relation is now recorded
    as `waived-ancestor-undeclared(<id>)` and the verdict stays MISSING.

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

    # vibe-ic#600 — a step (or an ancestor) that DECLARES a known gap is never
    # softened by this cascade. M2 carried "KNOWN GAP, deliberately left
    # declared and RED" in a COMMENT for four releases, so the cascade could not
    # see it: M2's ancestry reaches step 13's LEC waiver and M2/M3/M4 were
    # reported DEFERRED-BY-UPSTREAM(13). Closing 13 would have moved none of
    # them — M3 and M4 FAIL on their own declared inputs — and the real blocker
    # was hidden behind an unrelated waiver under a verdict that reads softer
    # than MISSING and carries an implicit roadmap.
    known_gap_of: Dict[Any, str] = {}
    for st in steps:
        sid = st.get("id")
        kg = st.get("known_gap")
        if sid is not None and isinstance(kg, str) and kg.strip():
            known_gap_of[sid] = " ".join(kg.split())

    # vibe-ic#776 — the DECLARED-DEPENDENCY relation, built from the flow.
    # `produces[s]` = what step s must write; `consumes[s]` = what step s's own
    # gate reads, PLUS its own required_outputs (a step required to deliver the
    # very artefact an ancestor is required to write cannot deliver without it —
    # that is the (14 <- 9) netlist.v shape).
    produces: Dict[Any, List[str]] = {}
    consumes: Dict[Any, List[str]] = {}
    for st in steps:
        sid = st.get("id")
        if sid is None or str(sid) == "P0":
            continue
        own_out = _flow_path_atoms(st.get("required_outputs") or [])
        produces[sid] = own_out
        reads: List[str] = list(own_out)

        def _harvest(node: Any) -> None:
            if isinstance(node, dict):
                for key, val in node.items():
                    if key in _FLOW_GATE_INPUT_KEYS:
                        reads.extend(_flow_path_atoms(val))
                    elif (key in _FLOW_GATE_COMMAND_KEYS
                          and isinstance(val, str)):
                        reads.extend(_flow_command_input_atoms(val))
                    else:
                        _harvest(val)
            elif isinstance(node, list):
                for item in node:
                    _harvest(item)

        _harvest(st.get("gate"))
        consumes[sid] = reads

    def _declares_dependency(child: Any, ancestor: Any) -> bool:
        """Does the FLOW say `child` reads something `ancestor` writes?"""
        anc_out = produces.get(ancestor) or []
        if not anc_out:
            return False
        for want in consumes.get(child) or []:
            for made in anc_out:
                if _flow_paths_meet(want, made):
                    return True
        return False

    _ord_anc_cache: Dict[Any, List[Any]] = {}

    def _ordering_ancestors(sid: Any) -> List[Any]:
        """Transitive blocks_on ancestors, nearest first (BFS order)."""
        cached = _ord_anc_cache.get(sid)
        if cached is not None:
            return cached
        out: List[Any] = []
        queue = list(parents_of.get(sid, []))
        seen: set = set()
        while queue:
            pid = queue.pop(0)
            if pid in seen:
                continue
            seen.add(pid)
            out.append(pid)
            queue.extend(parents_of.get(pid, []))
        _ord_anc_cache[sid] = out
        return out

    _dep_parent_cache: Dict[Any, List[Any]] = {}

    def _dependency_parents(sid: Any) -> List[Any]:
        """Ancestors this step DECLARES a dependency on, nearest first.

        The relation is checked against every transitive ordering ancestor, not
        only direct `blocks_on` parents: the flow routinely orders a consumer
        several hops behind its producer (step 2's gate reads the L*.json docs
        step D1 writes, but reaches D1 through step 1). Chaining edge-by-edge
        would drop exactly those real relations.
        """
        cached = _dep_parent_cache.get(sid)
        if cached is not None:
            return cached
        out = [a for a in _ordering_ancestors(sid)
               if _declares_dependency(sid, a)]
        _dep_parent_cache[sid] = out
        return out

    def _first_blocking_ancestor(sid: Any, declared_only: bool):
        """Walk ancestry; return ("gap"|"waiver", id) or (None, None).

        A declared known gap is nearer to the truth than any waiver behind it,
        so whichever is reached FIRST wins and a known gap stops the walk.
        With `declared_only` the walk follows the DECLARED-DEPENDENCY relation
        instead of the raw ordering edges.
        """
        step_of = _dependency_parents if declared_only else (
            lambda x: parents_of.get(x, []))
        queue: List[Any] = list(step_of(sid))
        seen: set = set()
        while queue:
            pid = queue.pop(0)
            if pid in seen:
                continue
            seen.add(pid)
            if pid in known_gap_of:
                return "gap", pid
            if pid in deferred_ids:
                return "waiver", pid
            queue.extend(step_of(pid))
        return None, None

    for r in results:
        if r.status != "MISSING":
            continue
        own_gap = known_gap_of.get(r.id)
        if own_gap:
            r.cascade_note = f"known-gap({r.id})"
            r.reasons.insert(0, (
                f"known-gap({r.id}): this step DECLARES its own gap, so no "
                f"upstream waiver explains it and the verdict stays MISSING — "
                f"{own_gap}"))
            info.setdefault("known_gap", []).append((r.id, own_gap))
            continue
        # BFS over blocks_on ancestry, for ATTRIBUTION.
        kind, near = _first_blocking_ancestor(r.id, declared_only=False)
        hit = near if kind == "waiver" else None
        gap_hit = near if kind == "gap" else None
        if gap_hit is not None:
            # Attribution WITHOUT softening: the status stays MISSING, because
            # the ancestor's gap is not a waiver and nothing is deferred.
            r.cascade_note = f"blocked-by-known-gap({gap_hit})"
            r.reasons.insert(0, (
                f"blocked-by-known-gap({gap_hit}): the nearest blocking "
                f"ancestor DECLARES a gap rather than carrying a waiver, so "
                f"this is not deferred work — {known_gap_of[gap_hit]}"))
            info.setdefault("blocked_by_known_gap", []).append((r.id, gap_hit))
            continue
        if hit is None:
            continue
        # vibe-ic#776 — SOFTENING NEEDS MORE THAN ORDER. The reason below used
        # to be printed with the softer status attached, and it contains its own
        # refutation: it says the flow does not establish that this step's
        # artefacts depend on the waived ancestor's, and then discounts the step
        # as though it had. Re-walk the SAME ancestry admitting only edges the
        # flow DECLARES — the near end's gate reads, or its own
        # required_outputs are, something the far end must write. Only a waiver
        # reached that way may soften; otherwise the ordering fact is recorded
        # and the verdict stays MISSING.
        dep_kind, dep_hit = _first_blocking_ancestor(r.id, declared_only=True)
        if dep_kind != "waiver":
            r.cascade_note = f"waived-ancestor-undeclared({hit})"
            r.reasons.insert(0, (
                f"waived-ancestor-undeclared({hit}): step {hit} is a waived "
                f"ancestor of this step in the declared blocks_on ORDER, but "
                f"neither this step's gate nor its required_outputs declares "
                f"reading anything {hit} is required to write — blocks_on is "
                f"an ORDERING edge, so nothing establishes that {hit}'s waiver "
                f"explains this gap. The phase that writes this step's "
                f"evidence never completed; the verdict stays MISSING. If the "
                f"dependency is real, DECLARE it: give this step's gate a "
                f"`condition_files_exist` naming the artefact {hit} produces."))
            info.setdefault("waived_ancestor_undeclared", []).append(
                (r.id, hit))
            continue
        hit = dep_hit
        ticket = _ticket_for(hit)
        r.status = "DEFERRED-BY-UPSTREAM"
        r.cascade_note = f"deferred-by-upstream({hit}, ticket={ticket})"
        r.reasons.insert(0, (
            f"deferred-by-upstream({hit}, ticket={ticket}): step {hit} is a "
            f"waived ancestor of this step in the declared blocks_on ORDER, "
            f"AND the flow declares this step reads what {hit} is required to "
            f"write, so the waiver that stopped {hit} is what stopped this "
            f"step — one waiver, one deduction"
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


def _published_tree_advisory(project: Path) -> Optional[str]:
    """Warn when `project` looks like a PUBLISHED benchmark-data evidence
    folder rather than a live run directory (informational only — changes
    no verdict, no count, no exit code).

    caravel_user_project/v1.9.43_sky130A shipped a RESULT.md claiming
    Overall PASS_WITH_WAIVERS side by side with a committed
    reports/audit/phase23_completion_audit.json recording Overall FAIL from
    the SAME run. Root cause, confirmed by re-running THIS program against
    the committed tree: `benchmark-data/PUBLISHING.md` deliberately excludes
    `phase3/stage3/*` (PnR + extraction working files) and `*.log` from what
    gets committed ("Excluded by construction" / `NOT_PUBLISHED` routing).
    Steps whose `files_exist` target lives under `phase3/stage3/*` — pre-
    and post-route STA, routing, spare-cell insertion, metal fill, SPEF-
    dependent SI/DRC, foundry handoff — therefore read FAIL or MISSING when
    THIS checker is re-run against a published tree, independent of whether
    the run that produced the evidence actually converged. Measured
    identically against `spm/v1.9.94_sky130A` and `spm/v1.9.96_gf180mcuD`
    (both independently converged reference cells whose OWN committed
    `phase23_completion_audit.json` records PASS_WITH_WAIVERS): a fresh
    re-run of THIS checker against either published tree also reports
    Overall FAIL on the identical `phase3/stage3/sta/pre_pnr_timing.rpt`
    absence. A published tree's authoritative verdict is therefore the
    audit captured at ORIGINAL RUN TIME (already committed at
    `reports/audit/phase23_completion_audit.json`) — never a re-run of this
    checker against the published copy, which structurally cannot reproduce
    a stage3-dependent PASS.

    Detection is chip-AGNOSTIC and purely structural: the GDS_MANIFEST that
    `benchmark_evidence_publish.py` writes for every published cell is
    present, and the `phase3/stage3/` subtree that publishing excludes is
    absent. A live run directory has stage3 present and no manifest, so it
    never matches.
    """
    manifest = project / "phase3" / "stage4" / "gds" / "GDS_MANIFEST.txt"
    stage3 = project / "phase3" / "stage3"
    if manifest.is_file() and not stage3.is_dir():
        return (
            "PUBLISHED-TREE DETECTED: phase3/stage4/gds/GDS_MANIFEST.txt is "
            "present and phase3/stage3/ is absent — this project_dir looks "
            "like a committed benchmark-data evidence folder, not a live "
            "run directory. Per benchmark-data/PUBLISHING.md, "
            "phase3/stage3/* (PnR + extraction working files) and *.log "
            "are intentionally excluded from publish. Any step here whose "
            "files_exist target lives under phase3/stage3/* (pre/post-route "
            "STA, routing, spare-cell insertion, metal fill, SPEF-dependent "
            "SI/DRC, foundry handoff) will read FAIL or MISSING even for a "
            "genuinely converged run — that is a property of the published "
            "layout, not evidence of a live regression. The authoritative "
            "verdict for a published cell is the audit captured at "
            "original-run time and already committed at "
            "reports/audit/phase23_completion_audit.json; do not overwrite "
            "it by re-running this checker against the published tree."
        )
    return None


def completion_audit_verdict(
    overall: str,
    invoked_gate_count: Optional[int],
    step_counts: Dict[str, int],
    structural_fail_lines: List[str],
    step_artifact_fail_lines: List[str],
    registered_gate_count: Optional[int] = None,
) -> Tuple[str, Optional[str]]:
    """The `verdict` this run is ENTITLED to write into the completion audit.

    vibe-ic#1001 — A VERDICT ABOUT A DESIGN THIS AUDIT NEVER READ.

    `verdict` in `phase23_completion_audit.json` is the ONE field every
    content-reading consumer keys on: `step_internal_fail_bubble_up_check`
    walks `reports/**/*.json` for exactly this key and reads a `FAIL` in it as
    "a step-internal gate found a defect in this design".

    MEASURED — point `flow_compliance_check.py` at a directory holding no
    design at all (`mkdir empty && flow_compliance_check.py . --phase all`) and
    it writes:

        verdict              FAIL
        invoked_gate_count   0        (of 246 registered)
        step_counts          PASS 0 / FAIL 0 / MISSING 40 / SKIPPED-COND 23
        structural_fail_lines      []
        step_artifact_fail_lines   []

    while its own stdout says, in this file's words, ``GATE EXECUTION LEDGER:
    no program gate was invoked in this run`` and tags the run
    ``[whole run: no_steps_tree]``. Not one gate ran. Not one step was decided
    in either direction. There is no finding — and the artefact asserts one
    anyway, to every consumer that reads the key.

    That is not hypothetical: one PUBLISHED run carries this artefact
    byte-comparably (same `step_counts`, `invoked_gate_count: 0`), because the
    audit was invoked from inside the run's own `reports/` directory, so its
    project root resolved to a tree with no design in it. The SAME plugin
    version re-audited the real root 3.5 seconds later and recorded PASS. The
    stale wrong-root copy is one of the reds the Step-36 gate raises.

    So: a run that measured NOTHING REFUSES. It says `INSUFFICIENT_DATA` —
    this repo's existing token for "the tool did not run / the data is
    missing", already in `step_internal_fail_bubble_up_check._NEUTRAL_VERDICTS`
    — and DISCLOSES the denominator that made it refuse, per the house rule
    that a verdict must say how much it looked at.

    WHAT THIS DELIBERATELY DOES NOT DO — it does not touch `overall`. The exit
    code, the stdout verdict line, the step table and every other consumer keep
    the FAIL, so the run stays red and nothing can route around it. Refusing is
    not passing; the only thing that changes is that a report stops CLAIMING a
    step-internal finding it never made.

    §4.05 NO-LEAK — this is a guard-RELAXING change, so the predicate is
    conjunctive and every conjunct removes a way it could wave through a real
    finding. ONE gate invoked, ONE step decided in EITHER direction, or ONE
    structural / step-artifact failure line, and the FAIL stands unchanged. It
    fires only when the numerator is empty on all four axes at once.

    `invoked_gate_count is None` (a stage-3/4 invocation where the umbrella did
    not run) is NOT zero-proof and deliberately keeps the FAIL: `None` means
    "not asked", and only a measured 0 is evidence that nothing answered.

    Returns (verdict, refusal_reason); refusal_reason is None whenever the
    verdict is `overall` unchanged. chip-AGNOSTIC — reads counts, not designs.
    """
    if overall != "FAIL":
        return overall, None
    if invoked_gate_count != 0:
        return overall, None
    if (step_counts or {}).get("PASS", 0) or (step_counts or {}).get("FAIL", 0):
        return overall, None
    if structural_fail_lines or step_artifact_fail_lines:
        return overall, None
    denom = ("of an unresolved registered-gate population"
             if registered_gate_count is None
             else f"of {registered_gate_count} registered")
    return "INSUFFICIENT_DATA", (
        f"REFUSED, not FAILED: 0 gate(s) {denom} were invoked and 0 step(s) "
        f"were decided (PASS 0 / FAIL 0), with no structural and no "
        f"step-artifact failure line. Nothing about this design was measured, "
        f"so this audit has no step-internal finding to report and does not "
        f"claim one. The run's own status is UNCHANGED and still {overall} — "
        f"refusing is not passing.")


#: Colon-separated stack of the stage scopes an outer `flow_compliance_check`
#: is currently evaluating. Inherited by every gate program this run spawns, so
#: a nested pass can see that its own scope is already open. See the
#: re-entrancy block in `main`.
_SCOPE_STACK_ENV = "VIBEIC_FCC_ACTIVE_SCOPES"

#: The value `_child_env()` hands to every gate program this run spawns: the
#: stack we were given, plus our own scope. Set by `main`, read only while
#: spawning. NOT written to `os.environ` — see the comment at the assignment.
_CHILD_SCOPE_STACK = ""


def _child_env():
    """The environment for a spawned gate program, carrying the scope stack."""
    if not _CHILD_SCOPE_STACK:
        return None          # nothing to add; let the child inherit as before
    return dict(os.environ, **{_SCOPE_STACK_ENV: _CHILD_SCOPE_STACK})

#: Scopes that contain no synthesis step, so the pre-PnR Yosys gate has nothing
#: to read. `stage1` is spelt as an int one line below for historical reasons;
#: these are the stages `--stage` could never name.
_NO_SYNTH_SCOPES = ("stage1", "stage_phase1", "stage_analog")

#: Scopes that contain no digital-RTL step, so the P0 structural umbrella has no
#: subject. The existing `args.stage not in (3, 4)` says the same thing for the
#: numbered stages; this is that sentence for the named ones.
_NO_RTL_UMBRELLA_SCOPES = ("stage3", "stage4", "stage_phase1", "stage_analog",
                           "stage_mixed_signal", "stage5_manufacturing")


def main(argv: Optional[List[str]] = None) -> int:
    # One invocation owns one denominator.  Orchestrators and tests call this
    # entry point repeatedly in-process, so retaining prior rows would publish
    # gates that did not run in the current audit.
    _GATE_LEDGER.clear()
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
    # `--stage` CANNOT NAME EVERY STAGE THIS FLOW HAS, and until now nothing
    # said so. It is `type=int, choices=[1,2,3,4]`, while `stages:` also carries
    # `stage_phase1`, `stage_analog`, `stage_mixed_signal` and
    # `stage5_manufacturing`. A caller that wants an interim verdict for one of
    # those has no way to ask for it, which is why the on-pass reviews for
    # stage_phase1 and stage_analog had no producible verdict source at all.
    # This takes the stage's OWN id, verbatim, so the set of askable scopes is
    # the set of stages the flow declares rather than a hand-typed subset.
    # STRUCTURAL TERMINATION FOR A SELF-SCOPING PRODUCER, and the reason it is a
    # flag rather than a convention. Stage 4's on-pass review has to be hosted on
    # a stage-4 step -- every step after 39 is conditioned on an artefact a
    # doc-to-GDS run does not produce -- so the `stage4_compliance` clause that
    # produces its verdict sits INSIDE the scope it measures and would evaluate
    # its own host, whose gate spawns it again. Naming the host here removes the
    # cycle from the graph instead of catching it at run time, so termination
    # does not depend on the environment surviving the trip. It is also the
    # honest scope: read from step 39, "did stage 4 pass" cannot include step 39,
    # which is still being evaluated.
    p.add_argument("--exclude-step", dest="exclude_step", action="append",
                   default=[],
                   help=("Skip the step with this id (repeatable). For a "
                         "compliance pass spawned BY a step inside the scope it "
                         "measures: naming that step breaks the cycle."))
    p.add_argument("--stage-id", dest="stage_id",
                   help=("Only check steps belonging to this stage, named by "
                         "the stage's own `id` (e.g. stage_phase1, "
                         "stage_analog, stage3). Mutually exclusive with "
                         "--stage, which can only name stages 1-4."))
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
        "--strict-audit-evidence", action="store_true",
        help=("Compatibility no-op: audit-created `required_outputs` are "
              "always tagged audit_created and excluded from run evidence. "
              "Strict audit-evidence behavior is unconditional; this legacy "
              "flag cannot weaken or strengthen it."),
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
        "--read-only", action="store_true",
        help=("2026-08-04: audit a run tree WITHOUT modifying it. This "
              "program is a producer as well as a judge — it runs each "
              "step's gates, and those gates write their own reports "
              "into the project. MEASURED over a published run tree: 25 "
              "files added and 17 tracked files rewritten by one "
              "invocation, and a controlled A/B left 77 tracked files "
              "rewritten plus 64 untracked and 22 IGNORED artefacts. The "
              "ignored ones are invisible to `git status`, so the next "
              "gate reads them without anyone seeing they arrived — the "
              "shape that failed two gatekeeper_review runs on leftovers "
              "rather than on the change under review. With this flag the "
              "audit is performed against a disposable COPY and the "
              "original is left byte-for-byte identical; any --json "
              "report still lands where it was asked for. Use it whenever "
              "the tree is EVIDENCE (a published corpus, another agent's "
              "run) rather than the run in progress."),
    )
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

    # ── --read-only: audit a COPY, never the tree the caller handed us ──────
    #
    # Redirecting the writes one at a time was considered and rejected. This
    # program does not write once: it invokes ~250 sub-gates, each of which
    # chooses its own `--json` destination inside the project, and a
    # per-call-site redirect would be complete only for as long as nobody adds
    # the 251st. Auditing a copy is complete BY CONSTRUCTION — the original
    # path is never handed to any sub-gate, so there is no write site to miss.
    #
    # The copy is made where the caller's TMPDIR points, not beside the
    # project: a sibling directory would itself be a corpus write.
    _ro_scratch = None
    if args.read_only:
        import shutil as _shutil
        import tempfile as _tempfile
        # A --json destination INSIDE the tree would make the flag a lie: the
        # one write left would be the audit's own report, landing in the
        # evidence the caller asked us not to touch. Refused rather than
        # silently redirected — the caller named that path and has to be told
        # it cannot have it.
        if args.json:
            _rep = Path(args.json).resolve()
            if _rep == project or project in _rep.parents:
                print(f"flow_compliance_check: --read-only refuses to write "
                      f"its --json report inside the tree it is auditing "
                      f"({_rep}); choose a destination outside {project}",
                      file=sys.stderr)
                return 2
        _ro_scratch = Path(_tempfile.mkdtemp(prefix="fcc-readonly-"))
        _ro_copy = _ro_scratch / project.name
        try:
            _shutil.copytree(project, _ro_copy, symlinks=True)
        # `shutil.Error` too, and not only `OSError`: copytree COLLECTS the
        # per-file failures and raises its own aggregate type at the end, so an
        # unreadable subdirectory — the ordinary way a copy of somebody else's
        # run tree fails — would otherwise escape as a traceback.
        except (OSError, _shutil.Error) as _exc:
            _shutil.rmtree(_ro_scratch, ignore_errors=True)
            print(f"flow_compliance_check: --read-only could not copy "
                  f"{project}: {_exc}", file=sys.stderr)
            # NOT a fallback to writing. A caller that asked for read-only
            # got no audit rather than an audit that mutated its evidence.
            return 2
        project = _ro_copy
        # `atexit` and not a `try/finally`: `main` returns from ~20 places
        # below, and a finally wrapping all of them would be a 400-line
        # re-indent whose only content is this one line. Leaking a temp dir if
        # the process is killed is the harmless direction — the file this flag
        # exists to protect is already untouched by then.
        import atexit as _atexit
        _atexit.register(_shutil.rmtree, str(_ro_scratch), True)

    # ── the design this verdict is about, measured BEFORE anything judges it ──
    #
    # The tally this program publishes carried no record of its own
    # population: the same run directory, byte-identical, scored PASS=22 under
    # 1.9.76 and PASS=6 under a newer plugin, and nothing in the artefact let a
    # reader tell "the design got worse" from "the ruler got better". Sixteen
    # of the twenty-two were never real.
    #
    # Taken HERE because this is the last moment before any sub-gate writes:
    # ~250 of them emit `--json` reports into the tree, so a digest taken later
    # would be a digest of this program's own opinion. The auditor's footprint
    # is then subtracted by MEASUREMENT (pre/post stat), not by a path
    # allowlist — `reports/phase3/` holds the DRC and LVS sign-off reports as
    # well as the checkers' JSON, and excluding it by prefix would blind the
    # digest to arriving sign-off evidence and make the artefact assert that a
    # design which really moved had not.
    #
    # Every failure mode here degrades to a null digest with a stated reason.
    # It must never cost the audit or move the verdict: this is a record of
    # what was measured, not a measurement.
    _did_scan = None
    _did_error = None
    try:
        if str(PROGRAMS_DIR) not in sys.path:
            sys.path.insert(0, str(PROGRAMS_DIR))
        import design_input_digest as _did
    except Exception as _exc:            # pragma: no cover - import guard
        _did = None
        _did_error = f"design_input_digest unavailable: {_exc}"
    if _did is not None:
        try:
            _did_scan = _did.scan_inputs(project)
        except Exception as _exc:
            _did_error = f"design-input scan failed: {_exc}"

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

    # Apply --stage / --stage-id filter if requested.
    target_stage: Optional[str] = None
    if args.stage is not None and getattr(args, "stage_id", None):
        print("flow_compliance_check: pass --stage OR --stage-id, not both",
              file=sys.stderr)
        return 2
    if getattr(args, "stage_id", None):
        target_stage = str(args.stage_id)
    elif args.stage is not None:
        target_stage = f"stage{args.stage}"
    if target_stage is not None:
        declared_stage_ids = {str(st.get("id")) for st in (flow.get("stages") or [])
                              if isinstance(st, dict) and st.get("id")}
        if declared_stage_ids and target_stage not in declared_stage_ids:
            # A SCOPE THIS FLOW DOES NOT DECLARE IS A TYPO, NOT AN EMPTY RUN.
            # The branch below already refuses an empty selection, but it
            # cannot tell "this stage exists and has no steps here" from "this
            # stage does not exist"; the second is the one a caller can fix.
            print(f"flow_compliance_check: no stage {target_stage!r} in "
                  f"{flow_path}; declared stages are "
                  f"{', '.join(sorted(declared_stage_ids))}", file=sys.stderr)
            return 2
        steps = [s for s in steps if s.get("stage") == target_stage]
        if not steps:
            print(f"flow_compliance_check: no steps for {target_stage}", file=sys.stderr)
            return 2

    excluded = {str(x) for x in (getattr(args, "exclude_step", None) or [])}
    if excluded:
        known = {str(st.get("id")) for st in steps if isinstance(st, dict)}
        unknown = sorted(excluded - known)
        if unknown:
            # A TYPO EXCLUDES NOTHING AND LOOKS IDENTICAL TO A CLEAN RUN, which
            # is the whole failure mode this change exists to stop. Refused.
            print(f"flow_compliance_check: --exclude-step names "
                  f"{', '.join(repr(u) for u in unknown)}, which no step in "
                  f"scope declares. An exclusion that matches nothing silently "
                  f"changes nothing.", file=sys.stderr)
            return 2
        steps = [st for st in steps if str(st.get("id")) not in excluded]
        if not steps:
            print(f"flow_compliance_check: --exclude-step {sorted(excluded)} "
                  f"left no steps to check", file=sys.stderr)
            return 2

    # ── RE-ENTRANCY: A SCOPED PASS MUST NOT RE-ENTER ITS OWN SCOPE ──────────
    # This program spawns itself: a step's gate may carry `stageN_compliance`,
    # which is `flow_compliance_check --stage N`, and that nested pass
    # evaluates steps whose gates may spawn it again. Today every such chain
    # descends (stage3 -> stage2 -> stage1 -> stage_phase1) and terminates by
    # luck rather than by construction: the moment a stage's own verdict is
    # produced ON a step of that same stage -- which is the only place stage 4's
    # verdict CAN be produced, because every step after 39 is conditioned on an
    # artefact no run has -- the chain is infinite.
    #
    # DISCLOSED, NEVER SILENT. The refusal is rc=2 with the scope stack named,
    # so a reader sees a scope that declined to re-enter itself rather than a
    # pass that quietly measured nothing. rc=2 is this program's existing
    # "the question could not be put" tier and the advisory slot already
    # records it as such.
    # A BACKSTOP, NOT THE MECHANISM, and the distinction is load-bearing: it
    # rides on an environment variable, so a caller that sanitises the child
    # environment does not see it. The SHIPPED wiring therefore terminates
    # structurally, via `--exclude-step` above; this catches a FUTURE self-
    # scoping clause added without one, where the alternative is a flow that
    # never returns.
    _scope = target_stage or "ALL"
    _active = [t for t in (os.environ.get(_SCOPE_STACK_ENV) or "").split(":") if t]
    if _scope in _active:
        print(f"flow_compliance_check: rc=2 NOT CHECKED — scope {_scope!r} is "
              f"already being evaluated by an outer pass "
              f"({' -> '.join(_active)}). A scoped compliance pass does not "
              f"re-enter its own scope; the outer pass is the one whose verdict "
              f"this is.", file=sys.stderr)
        return 2
    # PUSHED HERE, POPPED IN THE `finally` AT THE END OF THIS FUNCTION. A
    # subprocess would not need the pop -- it exits -- but `stageN_compliance`
    # imports `main` and calls it IN PROCESS, so a leaked entry would make the
    # NEXT in-process call for the same scope decline a question it should have
    # answered. Measured as a hazard while writing this, not after.
    # PASSED DOWN EXPLICITLY, NEVER SET ON OUR OWN PROCESS. `os.environ` is
    # process-global and `stageN_compliance` imports `main` and calls it IN
    # PROCESS, so mutating it here would leak this run's scope into the NEXT
    # in-process call and make it decline a question it should have answered.
    # A module-level value that each call overwrites has no such lifetime: it is
    # read only by `_child_env()` while this call is spawning children.
    global _CHILD_SCOPE_STACK
    _CHILD_SCOPE_STACK = ":".join(_active + [_scope])

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
        # THE UPPER BOUND IS DERIVED, NOT TYPED. It was hard-coded at 40 and the
        # flow has since grown to 44, so steps 41-44 (the manufacturing steps)
        # fell into NEITHER scope: `--phase 2` excluded them for being > 6 and
        # `--phase 3` excluded them for being > 40. A step in neither scope can
        # never be reported MISSING by a phase-scoped run -- it is invisible
        # rather than out-of-scope, and nothing said so. Every past raise of
        # this cap (39 -> 40) was a symptom of the constant existing at all.
        _int_ids = [s["id"] for s in steps if isinstance(s.get("id"), int)]
        _max_id = max(_int_ids) if _int_ids else 0
        phase_range = (1, 6) if args.phase == "2" else (7, _max_id)
        kept = []
        _agnostic = []
        for s in steps:
            sid = s.get("id")
            if isinstance(sid, int):
                if phase_range[0] <= sid <= phase_range[1]:
                    kept.append(s)
            else:
                # Non-integer id (A* / DT* / FS* / M* / P0) — phase-agnostic,
                # kept in BOTH scopes. That is a deliberate choice and it means
                # `--phase 2` and `--phase 3` are NOT a partition of the flow:
                # these steps are counted once in each. Assigning each of them
                # to a phase is a judgement about that step, made by whoever
                # knows it; guessing them here would bury the ambiguity instead
                # of showing it. So it is DISCLOSED rather than resolved, and a
                # reader adding the two scopes together is told not to.
                kept.append(s)
                _agnostic.append(str(sid))
        steps = kept
        if _agnostic:
            print(f"flow_compliance_check: NOTE — {len(_agnostic)} "
                  f"phase-agnostic step(s) are in scope for BOTH `--phase 2` "
                  f"and `--phase 3`, so the two scopes are not a partition and "
                  f"their step counts must not be added: "
                  f"{', '.join(sorted(_agnostic))}")
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
    if args.stage == 1 or target_stage in _NO_SYNTH_SCOPES:
        # A scope that contains no synthesis step has no subject for this gate.
        # `stage1` was already spelt here as an int; the named scopes are the
        # same statement for the stages `--stage` could never name.
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
    # None = the P0 umbrella did not run in this invocation (stage 3/4), as
    # distinct from "it ran and nothing passed". The audit JSON's
    # passed_gate_count reads this rather than scraping reasons prose.
    structural_passed_count: Optional[int] = None
    # The umbrella's own coverage, as NUMBERS. `None` — not 0 — until the
    # umbrella runs, for the same reason `structural_gate_records` is `None`
    # below: on a stage-3/4 invocation there is no P0 step, and `0 registered`
    # would read as "the registry is empty" while `246 registered / 0 invoked`
    # would read as "246 checkers were supposed to run and none did". Neither is
    # true, and a three-state field says so without inventing either.
    structural_registered_count: Optional[int] = None
    structural_invoked_count: Optional[int] = None
    structural_not_invocable_count: Optional[int] = None
    # #497 step 1 — the P0 umbrella's structured per-gate payload. `None` until
    # the umbrella runs, so a stage-3/4 invocation (where P0 does not run at
    # all) publishes "no records" rather than an empty list that would read as
    # "every gate was considered and none of them anything".
    structural_gate_records: Optional[List[Dict[str, Any]]] = None
    if args.stage not in (3, 4) and target_stage not in _NO_RTL_UMBRELLA_SCOPES:
        structural_gate_records = []
        # #497 step 3 — `main()` no longer consumes the umbrella's PROSE
        # buckets at all. `s_passed` is the umbrella's own tri-state and
        # `s_waivers` is an already-structured list published verbatim as
        # `thin_input_waivers`; the two prose buckets are a legacy view kept
        # for existing callers of this function and are deliberately unread
        # here.
        s_passed, _s_fails, _s_skips, s_waivers = _run_structural_rtl_gates(
            project,
            strict_timing=getattr(args, "strict_timing", False),
            allow_thin_input=getattr(args, "allow_thin_input", False),
            # ORGANIC-20260614 (#632) — thread --skip-analog into the P0
            # umbrella the same way check_step receives it, so the analog
            # sub-gates obey the flag instead of FAILing the umbrella for
            # an explicitly-deferred analog track.
            skip_analog=getattr(args, "skip_analog", False),
            # The umbrella's structured channel. It stays an out-parameter
            # rather than becoming a fifth return value: ~20 call sites unpack
            # the 4-tuple positionally and two of them replace this function
            # with a stub to drive `main()`, so a fifth element would break the
            # first group and a separate entry point the second — for no gain,
            # because the anti-drift property comes from the record being the
            # only thing AUTHORED (the buckets are now projected from it), not
            # from the calling convention.
            records_out=structural_gate_records,
        )
        structural_waivers = s_waivers
        # The umbrella result is built UNCONDITIONALLY once the gates have
        # run. It used to be built only `if s_fails or s_skips or s_waivers`,
        # so the ONE outcome with nothing to report — every structural gate
        # clean, no skip, no waiver — produced no StepResult at all: P0 was
        # missing from the printed per-step listing, missing from the JSON
        # `steps` array, and absent from `counts`, i.e. the best case was the
        # only case with no audit record. Worse, `--phase 2
        # --strict-structural` scopes its whole verdict to `[r for r in
        # results if r.id == "P0"]`, so with P0 gone that scope was EMPTY and
        # the run reported PASS over zero evidence. A clean sweep now emits an
        # explicit PASS with a positive reason line.
        #
        # #497 step 3 — `reasons` is a DERIVED VIEW of the records, rendered by
        # the one function that owns the operator-facing grammar. It is the
        # last of the umbrella's four published outputs to stop being authored
        # independently, and it is byte-identical in all six line shapes: the
        # per-step listing renders it, and a naive move of the #492 disclosure
        # into a field of its own would have made unrun gates invisible again,
        # which is the whole thing #492 was built to end.
        reasons_combined = _compose_p0_reasons_from_records(
            structural_gate_records, s_passed)
        # #497 step 2 — counted off the records. The number this replaces was
        # itself the fix for a prose scrape (`PASS: <gate>` lines the umbrella
        # has never emitted, so the field read 0 for its whole existence); it
        # recovered the count as `registry - fails - skips - waivers`, which is
        # the closest a bucket-only world could get to asking the gates.
        structural_passed_count = _p0_passed_count(structural_gate_records)
        # #447 — s_passed is None when NO checker executed (no RTL):
        # the umbrella reports SKIPPED-CONDITION, never PASS; a
        # pure-analog project's strict verdict is decided by the
        # A-track gates, not by 0/226 skipped digital checkers.
        # vibe-ic#559 — the headline said `N checkers` where N is the number
        # REGISTERED, which is not the number that produced a verdict. 33 of the
        # 243 reject the argv the umbrella builds (argparse exits 2 before the
        # check runs), so they return NOT_INVOCABLE and what they audit is
        # UNAUDITED. The per-gate disclosure below the headline has always been
        # complete; the headline is the part a reader takes at face value, and it
        # reads as 243 audits where 210 happened.
        #
        # BOTH numbers, ALWAYS — not `N checkers` when they agree and something
        # longer when they do not. A line that only changes shape in the bad case
        # is a line nobody has read in the good case, so nobody recognises the
        # bad one either.
        #
        # Safe to reword: nothing parses this string. Checked before changing it,
        # because this session has repeatedly found consumers that scrape prose —
        # `final_report_generate` writes its own P0 heading, and
        # `checker_execution_wiring_audit`'s `checkers` field is its own JSON.
        _n_registered = len(_STRUCTURAL_RTL_GATES)
        _n_verdict = _p0_verdict_count(structural_gate_records)
        # THE SAME TWO NUMBERS THE HEADLINE STATES, published as numbers.
        # Until here they existed only inside a formatted English sentence, so
        # the one machine-readable artifact — `phase23_completion_audit.json` —
        # carried `passed_gate_count` and `failed_gate_count` over a denominator
        # it never named. A consumer could not compute the coverage of the
        # verdict it was reading, and a fraction whose denominator is not
        # published is not a fraction. Assigned here rather than at the audit
        # site so the artifact and the headline read the same variables.
        structural_registered_count = _n_registered
        structural_invoked_count = _n_verdict
        structural_not_invocable_count = _p0_not_invocable_count(
            structural_gate_records)
        structural_result = StepResult(
            id="P0",
            name=(f"Structural-RTL gates (P0 umbrella, {_n_verdict} of "
                  f"{_n_registered} checkers returned a verdict)"),
            stage="stage1",
            # ONE OWNER. The expression that stood here was
            # `"SKIPPED-CONDITION" if s_passed is None else "PASS" if s_passed
            # else "FAIL"` — a verdict over the gates that ANSWERED, published
            # as a verdict over the gates that are REGISTERED. `_p0_umbrella_status`
            # keeps both existing branches (#447's tri-state included, from the
            # same `s_passed` flag) and adds the one the two numbers above imply:
            # a clean sweep with a never-validly-invoked gate in it is
            # INCOMPLETE, not PASS.
            status=_p0_umbrella_status(s_passed, structural_gate_records),
            reasons=reasons_combined,
            evidence=[],
            # #497 step 1 — published ALONGSIDE `reasons`, which is unchanged.
            # Nothing derives anything from this yet; cutting the four
            # scrapers, the audit-JSON projection and the two all(...)
            # predicates over to it are separate steps with their own
            # measurements.
            gate_records=structural_gate_records,
        )

    results: List[StepResult] = []
    if structural_result is not None:
        results.append(structural_result)
    if pre_pnr_result is not None:
        results.append(pre_pnr_result)
    skip_analog = getattr(args, 'skip_analog', False)
    skip_hardware = getattr(args, 'skip_hardware', False)
    strict_audit_evidence = getattr(args, 'strict_audit_evidence', False)
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
                skip_analog=skip_analog, skip_hardware=skip_hardware,
                strict_audit_evidence=strict_audit_evidence))
    else:
        # Independent read-only gates → evaluate concurrently; collect the
        # futures in SUBMISSION order so `results` stays byte-for-byte the
        # same list the sequential path produced (see `_compliance_workers`).
        with ThreadPoolExecutor(max_workers=_workers) as _ex:
            _futs = [
                _ex.submit(check_step, project, step, waivers,
                           skip_analog=skip_analog,
                           skip_hardware=skip_hardware,
                           strict_audit_evidence=strict_audit_evidence)
                for step in _eval_steps
            ]
            for _fut in _futs:
                results.append(_fut.result())

    # v0.3.5 — ORGANIC #502/#503: cascade attribution AFTER all step
    # verdicts are final (waiver conversions included): waiver chains
    # propagate over blocks_on edges; post-FAIL MISSING runs are
    # attributed to their first-FAIL root cause.
    _resolve_dependency_condition_results(
        project, results, flow.get("steps") or steps)
    cascade_info = _attribute_cascade_verdicts(
        results, steps, waivers, skip_analog=skip_analog)
    # Issue #1983 — condition-based N/A is valid only after the step that owns
    # the declaration has passed.  This runs after the ordinary cascade pass
    # so the more specific declared-owner attribution wins over a generic
    # first-FAIL note, and before any counts/verdict/report projection so all
    # consumers see the same hard non-green rows.
    _condition_owner_info = _attribute_condition_owner_blocks(
        project, results, steps)
    for _owner, _count in (
            _condition_owner_info.get("blocked_by_upstream") or {}).items():
        _existing = cascade_info.setdefault("blocked_by_upstream", {})
        _existing[_owner] = _existing.get(_owner, 0) + _count
    cascade_info["condition_owner_blocks"] = (
        _condition_owner_info.get("records") or [])

    # v0.100 H2: advisory — warn if post-route STA passed single-corner only
    advisories: List[str] = []

    # caravel_user_project/v1.9.43_sky130A self-contradiction (RESULT.md
    # PASS_WITH_WAIVERS beside a committed phase23_completion_audit.json
    # FAIL) — surface the published-tree caveat before anyone reads a
    # re-run's FAIL as a live regression. Informational only.
    _pub_tree_note = _published_tree_advisory(project)
    if _pub_tree_note:
        advisories.append(_pub_tree_note)

    # #216 — a rejected ENV_UNAVAILABLE waiver is reported, never dropped.
    # Without this the step showed a bare MISSING and the reader could not
    # tell that a waiver had been attempted, let alone why it did not apply.
    advisories.extend(_ENV_WAIVER_REJECTIONS)
    # #524 — an APPLIED ENV_UNAVAILABLE waiver whose evidence nothing
    # independent corroborates is disclosed here. The step stays WAIVED; what
    # changes is that the reader can now tell which kind of evidence bought
    # the deferral, instead of the verdict reading identically either way.
    advisories.extend(_ENV_WAIVER_EVIDENCE_NOTES)
    # #529 — a `waivers`-dialect entry this run READ but did not bind is
    # disclosed here. Informational only: it changes no verdict, no count and
    # no exit code. Without it a compliance report was byte-identical whether
    # the project carried a ticketed, evidenced, review_required waiver or no
    # waivers.json at all, so a reader could not tell "considered and
    # inapplicable" from "nobody read this file".
    advisories.extend(_WAIVER_NOT_BOUND_DISCLOSURES)
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
    # Wave 93 — VACUOUS_PASS is a first-class verdict tier, displayed
    # separately so reviewers see how many steps were structurally
    # executed vs. vacuously satisfied (the gate ran but found no input to
    # audit). It is NOT counted into `pass_count`; see the adjudication
    # beside `pass_count` below.
    counts = {"PASS": 0, "FAIL": 0, "MISSING": 0, "WAIVED": 0,
              "DEFERRED-BY-UPSTREAM": 0,
              "SKIPPED-CONDITION": 0, "SKIPPED-SETUP-REQUIRED": 0,
              "VACUOUS_PASS": 0,
              # vibe-ic#901 — the step ran, some clauses examined the design
              # and some examined nothing. Counted and rendered separately
              # from VACUOUS-PASS for the reason INCOMPLETE is: same
              # aggregation (a disclosure tier, never a failure, never part of
              # `pass_count`), a different word, because "every sub-gate was
              # vacuous" is a false sentence about such a step.
              "PARTIALLY-VACUOUS": 0, "STRUCTURE-ONLY": 0,
              # #599 — counted and rendered separately from VACUOUS-PASS.
              # Same aggregation (a disclosure tier, never a failure); a
              # different word, because a vacuous step is one nobody needs to
              # come back to and this is one somebody does.
              "INCOMPLETE": 0}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    # vibe-ic#924 — `counts` IS A TALLY OF STEPS AND NOTHING ELSE.
    #
    # It is built one line above by `for r in results: counts[r.status] += 1`,
    # so every unit in it is one canonical step. What used to stand here added
    # `len(structural_waivers)` — a count of P0 SUB-GATE records, all of them
    # inside the ONE step P0 — into that step tally, and the mixed number then
    # reached four consumers at once:
    #
    #   * `total_required = len(steps) - <excused> + …`, where WAIVED is
    #     EXCUSED (`_flow_verdict_tiers.EXCUSED`), so N waived SUB-GATES
    #     removed N STEPS from a 63-step denominator. Numerator unchanged,
    #     denominator smaller: the published ratio ROSE, and it rose with the
    #     number of things waived.
    #   * the headline `… N DEFERRED via waiver`, which says steps;
    #   * the tally line `WAIVED-DEFERRED=N`, whose parts must sum to the step
    #     total and no longer could;
    #   * `⚠ N step(s) DEFERRED via waiver`, which says "step(s)" in words.
    #
    # MEASURED on the shipped CLI (0..4 sub-gate waivers, identical project,
    # only the P0 records varying): Y went 8, 7, 6, 5, 4 and X/Y went 12.5%,
    # 14.3%, 16.7%, 20.0%, 25.0% while ZERO steps carried a WAIVED status.
    # It is also visible in published data: one committed audit log reads
    # `Steps: 21 total (4/3 executed PASS, 3 DEFERRED via waiver)` — a
    # numerator LARGER than its denominator, over a tally summing 22 of 21.
    #
    # WHY NOT "EXCUSE AT MOST ITS OWN STEP" (contribute `min(1, N)`). That
    # reading assumes a waived sub-gate leaves P0 itself excused. It does not:
    # `_p0_umbrella_status` returns only SKIPPED-CONDITION / FAIL / INCOMPLETE
    # / PASS and CANNOT return WAIVED, and with a WAIVED record present the
    # reachable set is {PASS, FAIL} — neither of which is EXCUSED. So `min(1,
    # N)` would remove from the denominator a step that is simultaneously
    # counted in the numerator. Same unit error, magnitude 1. The committed log
    # above is that case in the wild: its P0 row reads `[PASS]` — the step was
    # in the numerator — while its one sub-gate waiver took a step off the
    # denominator, which is how `4/3` happened.
    #
    # WHAT THE ADDEND WAS FOR is preserved exactly. Its stated purpose (v1.6.97,
    # issue #29) was to keep Overall at PASS_WITH_WAIVERS rather than a bare
    # PASS whenever a --allow-thin-input waiver fired, and its only consumer for
    # that is `elif counts["WAIVED"] > 0` — a BOOLEAN threshold that never
    # needed a magnitude. It is carried below by this same-unit signal, so no
    # run changes its verdict word or its exit code.
    #
    # Each waiver is still review_required=true with a ticket id; they remain
    # published verbatim as `thin_input_waivers` in the --json report, are
    # named per gate in P0's own reasons, and are disclosed on the headline and
    # under the tally IN THEIR OWN UNIT below — so nothing goes silent, which
    # is the failure mode the "ON THE LINE" note further down exists to forbid.
    p0_subgate_waivers = len(structural_waivers)

    # THE VIOLATION MUST BE KNOWN BEFORE THE TABLE IS RENDERED.
    #
    # It used to be computed ~300 lines below the print loop, so demoting a
    # contradicted step there changed nothing a reader ever saw — the first
    # attempt at this fix did exactly that and the table still said PASS.
    # Detection moves up; the verdict logic below is untouched and simply reads
    # the list computed here.
    _ordering_violations: List[Dict[str, Any]] = []
    try:
        import flow_step_execution_coverage_check as _cov0
        _g0 = {str(st.get("id")): [str(e) for e in (st.get("blocks_on") or [])]
               for st in steps if st.get("id") is not None}
        _r0 = {"steps": [{"id": r.id, "name": r.name, "status": r.status,
                          "stage": getattr(r, "stage", "")} for r in results]}
        _ordering_violations = _cov0.analyze(_r0, _g0).get(
            "ordering_violations", []) or []
    except Exception:  # nosec — additive enforcement must never crash the audit
        _ordering_violations = []
    # WRITE THE CONTRADICTION BACK INTO THE STEP.
    #
    # The violation is already detected and already forces the RUN to FAIL.
    # What it never did is touch the step's OWN status, because
    # `compute_cascade` never demotes an already-PASS terminal step — the
    # comment above says so. So the per-step table published
    #
    #     [PASS] Step 37: GDSII output (only if Step 31 PV fully clean)
    #
    # beside its own violation line saying step 31 had FAILED. Both are
    # locally correct and the table showed the weaker one; a reader takes
    # `37 PASS` to mean the GDS is good.
    #
    # A DISTINCT status, not VACUOUS_PASS. The two are SIBLINGS, not
    # opposites: since v1.7.96 both are DISCLOSURE tiers, both sit OUTSIDE
    # the executed-PASS numerator, and both stay INSIDE `total_required`
    # (neither is EXCUSED), so neither can be mistaken for a step nobody
    # owes an answer for. What they disclose is what differs —
    # VACUOUS_PASS: the gate ran and found nothing to audit.
    # PASS_VOIDED_BY_DEPENDENCY: the gate ran, audited, and passed, but
    # rests on a chain that broke, so its PASS certifies nothing.
    # They therefore get their own icon and label (`○ [VACUOUS-PASS]` vs
    # `⊘ [PASS-VOIDED]`), their own counter in the tally line, and their own
    # headline clause. Reusing VACUOUS_PASS would erase a distinction a
    # reader needs: a vacuous step is one nobody has to come back to, and a
    # voided one is a step somebody does.
    for _v in _ordering_violations:
        _tid = str(_v.get("terminal_id"))
        for _r in results:
            if str(_r.id) != _tid:
                continue
            if _r.status == "PASS":
                _r.status = "PASS_VOIDED_BY_DEPENDENCY"
            elif getattr(_r, "json_vacuity_promoted", False):
                # vibe-ic#901 - this step would have been a bare PASS on
                # origin/main and would have been VOIDED here, printing the
                # dependency line below. The structured channel moved it to
                # VACUOUS_PASS, which is the label this program pins as the
                # more specific one (see test_POSITIVE_CONTROL_the_blocking_
                # slot_deletes_the_voided_line) - so the STATUS stays
                # VACUOUS_PASS and the dependency line is appended anyway. A
                # new disclosure must not cost an old one. Every other step
                # reaches the `continue` below and behaves as before.
                pass
            else:
                continue
            # One line per DISTINCT dependency. The violation list carries one
            # entry per (terminal, dependency) pair and a step can reach the same
            # failed dependency by several paths, so appending blindly repeats it.
            _why = (f"PASS voided: dependency [{_v.get('signoff_id')}] "
                    f"{_v.get('signoff')} = {_v.get('signoff_status')}, so this "
                    f"step's PASS certifies nothing about the design")
            _r.reasons = list(getattr(_r, "reasons", []) or [])
            if _why not in _r.reasons:
                _r.reasons.append(_why)
    if _ordering_violations:
        counts = {k: 0 for k in counts}
        for _r in results:
            counts[_r.status] = counts.get(_r.status, 0) + 1
        # vibe-ic#924 — the re-application of the sub-gate addend went with it.
        # This branch RESETS `counts` and re-tallies from `results`, so it
        # reproduces the step tally exactly; re-adding a sub-gate population
        # here would reinstate the unit mismatch on precisely the runs that
        # already have an ordering violation. `p0_subgate_waivers` is unchanged
        # by the reset — it is not a bucket of `counts`, which is the point.
        # NO `pass_count` HERE. The re-tally above is load-bearing (the tally
        # line, `total_required` and the sole numerator assignment all read
        # `counts`), but a `pass_count` store on this branch is dead: the
        # unconditional `pass_count = counts["PASS"]` below overwrites it
        # before the only read, and has done since v1.7.96 — which is BEFORE
        # this branch was written. The store that used to be here folded
        # VACUOUS_PASS back in and never once reached the headline.

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
        # Verdict scope: the structural-RTL `P0` umbrella, PLUS the analog
        # track. Step-level gates (1-40) — including the pre-PnR Yosys Step
        # 14 — are REPORTED for info but not gating, because they need real
        # EDA tool harnesses that aren't expected to be in scope when
        # `--phase 2 --strict-structural` is run.
        #
        # OWNER POLICY (2026-08-02), vibe-ic#634 — THE ANALOG TRACK COUNTS
        # TOWARD `Overall`. Until this change the analog track reached the
        # verdict ONLY through the step-execution ordering guard, and that
        # guard adjudicates DONE-CLAIMS (`_T.is_done_claim`). So a tree that
        # CLAIMED an analog step done over a failed dependency could be
        # marked down, and a tree whose analog steps simply FAILED — or never
        # produced their declared outputs at all — made no claim to
        # adjudicate and audited `Overall: PASS`. MEASURED on four trees
        # differing in one recorded content value, under exactly these flags:
        # the trees that bound or disclosed audited FAIL with 3 failed steps,
        # and the two SILENT trees audited PASS with 4 — no ordering
        # violation between them. Doing nothing outranked doing something
        # badly and saying so, one level above the gates built to price that
        # trade. `_flow_verdict_tiers`' own docstring records this as the
        # flow-POLICY question it deliberately left open; the owner settled
        # it, and this is where the answer lands.
        #
        # ABSENT IS NOT FAILED, and that is the control this scoping turns
        # on. `_T.scoped_into_verdict` is the COMPLEMENT of `EXCUSED` — the
        # states the producer already subtracts from `total_required` — so
        # `SKIPPED-CONDITION`, which a pure-digital design (no analog block
        # list ⇒ every A-step's flow `condition` unmet) and an explicit
        # `--skip-analog` both resolve the whole track to, never reaches the
        # verdict, while FAIL, MISSING, a self-skipped required setup and any
        # status this tree has never seen all do. Keeping the not-run states
        # OUT also keeps the analog track out of `oss_blocked_skipped` below,
        # which converts a DISCLOSED self-skip of a sign-off step into a
        # non-green item and lists A3-A9: a design with no analog content
        # must not acquire a deferral list by not having one.
        #
        # NOT WIDENED to `stage_mixed_signal` (M1-M4). That track has its own
        # producers, its own gates and its own blast radius; this is the
        # analog decision taken on the analog track, and mixed-signal is left
        # exactly where it was — pinned by a test so the boundary reads as a
        # decision rather than an omission.
        scoped = [r for r in results
                  if r.id == "P0"
                  or (_T.in_analog_track(r) and _T.scoped_into_verdict(r))]
    else:
        scoped = results
    failing = [r for r in scoped if r.status == "FAIL"]
    missing = [r for r in scoped if r.status == "MISSING"]
    setup_required_skipped = [r for r in scoped
                              if r.status == "SKIPPED-SETUP-REQUIRED"]

    # DFT_FCC / 11-d7 — the THIRD bucket: a sign-off-bar step that
    # self-skipped.
    #
    # SKIPPED-CONDITION appeared in the verdict path at exactly one place —
    # subtracted from `total_required` below — so it could never make a run
    # non-green. That is right for the 20-odd steps in a typical run that are
    # genuinely inapplicable (analog steps on a digital chip, and so on), and
    # wrong for a step this module ALREADY enumerates as a sign-off bar the
    # open-source container cannot clear.
    #
    # MEASURED on the reference run (spm × ihp-sg13g2): step 11 (DFT
    # insertion / ATPG sign-off coverage) resolves to SKIPPED-CONDITION with
    # all three of its declared outputs absent, and the verdict line does not
    # mention it — with the unrelated P0 structural gate clean, that run lands
    # on PASS_WITH_WAIVERS with the DFT sign-off gap invisible. Meanwhile
    # `_OPEN_SOURCE_CONTAINER_BLOCKED_STEPS` lists step 11 by name, and the
    # PASS_WITH_OPEN_SOURCE_CONSTRAINTS tier built for exactly this scenario
    # (review_required=true + an explicit deferral list) never fires, because
    # it only runs on an already-FAIL verdict and step 11 was in neither the
    # failing nor the missing bucket.
    #
    # So: treat such a skip like `missing` — it enters `ok` in strict mode
    # (lenient mode tolerates MISSING, and tolerates this the same way), which
    # routes the run through the promotion below and out to
    # PASS_WITH_OPEN_SOURCE_CONSTRAINTS when the tier's own preconditions
    # hold.
    #
    # TWO predicates, both required, so no new policy is invented:
    #   * `self_skip_disclosed` — the step SHOULD have run and the runner
    #     DISCLOSED a capability gap in place of its sign-off artefact
    #     (#608/#675). This excludes the genuinely-inapplicable skips, which
    #     are the large majority: on the reference run 22 steps are
    #     SKIPPED-CONDITION, of which A3-A9 read "analog track skipped via
    #     --skip-analog" and M1-M4 read "condition not met" on a pure-digital
    #     chip. Those are not deferred sign-off and must stay cost-free.
    #   * membership of `_OPEN_SOURCE_CONTAINER_BLOCKED_STEPS` — the step is
    #     already enumerated here as a sign-off bar the open-source container
    #     cannot clear.
    oss_blocked_skipped = [
        r for r in scoped
        if r.status == "SKIPPED-CONDITION"
        and r.self_skip_disclosed
        and r.id in _OPEN_SOURCE_CONTAINER_BLOCKED_STEPS
    ]

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
        # DFT_FCC / 11-d7 — oss_blocked_skipped joins failing/missing here.
        # It is treated exactly like `missing` (strict-mode only), because a
        # sign-off step that did not run is not distinguishable from one whose
        # sign-off artefact is absent. The FAIL this produces is normally
        # promoted straight back out to PASS_WITH_OPEN_SOURCE_CONSTRAINTS by
        # the tier below — the point is that the gap has to travel THROUGH
        # the verdict rather than around it.
        ok = (len(failing) == 0 and len(missing) == 0
              and len(setup_required_skipped) == 0
              and len(oss_blocked_skipped) == 0)

    # Output
    # v0.3.5 — #502: DEFERRED-BY-UPSTREAM is deferred work tied to the
    # parent's waiver ticket, so it leaves the required denominator the
    # same way the parent's WAIVED does.
    # DFT_FCC / 11-d7 — …but an OSS-blocked sign-off step that self-skipped
    # stays IN the denominator: it is a requirement that was not met, so
    # discounting it inflated the X/Y executed-PASS metric by making the
    # unmet requirement disappear from Y as well as from X.
    # …and a VACUOUS_PASS stays in the denominator for the SAME reason. It
    # is NOT the "inapplicable to this design" tier — that is
    # SKIPPED-CONDITION, whose step-level `condition` was evaluated and not
    # met, and which is subtracted above. VACUOUS_PASS means the gate RAN
    # and exited 0 having found nothing to audit. That is an unmet
    # requirement, so it must cost the denominator; subtracting it too would
    # make an unmeasured step free, which is the `0/-1` shape #235 measured
    # (a co-located disclosure promoted DT1/DT2/DT3 to SKIPPED-CONDITION and
    # flipped a flow FAIL -> PASS). X/Y therefore reads "of Y required
    # steps, X measured something and passed"; Y - X is not all failure, so
    # the vacuous count is named in the same line rather than left to the
    # tally below.
    #
    # WHAT THAT COSTS, scoped honestly. The answer to "but then a step that is
    # honestly inapplicable is a permanent debit" is "no — an honestly
    # inapplicable step is SKIPPED-CONDITION and leaves Y", and that escape
    # exists only for the steps that DECLARE a step-level `condition`.
    # MEASURED on the canonical flow: 22 of 63 do (all of A1-A9, M1-M4, DT*,
    # FS*); the other 41 — D1, 1-39, P0 — have no way to reach
    # SKIPPED-CONDITION at all, so for them an inapplicable input lands on
    # VACUOUS_PASS and IS a permanent Y-debit. The cost is narrowed, not
    # eliminated. Closing it for a specific step means giving that step a
    # condition, which is a flow change with its own blast radius, not a
    # numerator change.
    # DERIVED from the shared tier table (vibe-ic#634): the words subtracted
    # here ARE the definition of "excused", and the ordering guard reads the
    # same set, so the two cannot drift into different notions of which steps
    # are claimed as done. Byte-identical to the previous three-term
    # subtraction for the current vocabulary — the extra spellings in `EXCUSED`
    # are consumer-side tolerance the producer never emits, so they count 0.
    total_required = (len(steps)
                      - sum(_n for _k, _n in counts.items()
                            if _T.is_excused(_k))
                      + len(oss_blocked_skipped))
    # ADJUDICATED AT MERGE, v1.7.96 (supersedes Wave 93) — this is NOT an
    # owner ruling and must not be read as one; the repo's real ones carry a
    # date (`Owner ruling (2026-07-22)` in
    # test_private_project_codename_sanitize.py). The dimension-6 waiver this
    # replaces reserved the question for the owner on the ground that it had
    # no right answer. The measurement below shows it has one, so the
    # reservation is discharged on evidence rather than by authority — and
    # the published numbers it moves are tabled in the landing commit, so a
    # reader who disagrees can see exactly what to reverse.
    # VACUOUS_PASS LEAVES the
    # executed-PASS numerator. Wave 93 rolled it in "since it represents a
    # step that *did* run cleanly (just on input that didn't apply)", which
    # made the published X say the step was MEASURED. It was not: a vacuous
    # gate is one that found no input to audit. Giving the tier its own
    # label and its own counter while leaving it inside X left the number a
    # reviewer actually reads unchanged by the disclosure — measuring
    # something adjacent to the question and reporting it as the answer.
    # It remains a DISCLOSURE tier, not a failure: it is in none of
    # `failing` / `missing` / `setup_required_skipped` /
    # `oss_blocked_skipped`, so it still cannot make a run non-green.
    pass_count = counts["PASS"]

    # THE HEADLINE MUST NAME THE SCOPE IT MEASURED. `args.stage` is None on a
    # `--stage-id` run, so keying only on it would print a whole-flow headline
    # over a one-stage report — the reader's only clue that the numbers below
    # cover nine steps and not sixty-eight. `target_stage` carries both spellings.
    scope = f"{args.flow}" + (f" {target_stage}" if target_stage else "")
    print(f"\n=== Vibe-IC {scope} compliance ===")
    print(f"Project: {project}")
    print(f"Flow def: {flow_path}")
    # Named INSIDE the headline parenthesis, not only in the tally line, so
    # a reader cannot mistake the Y - X gap for Y - X failures. Appended
    # after the two fields every existing parser keys on
    # (`X/Y executed PASS,` then `W DEFERRED`), and deliberately without an
    # `=` so it can never be mistaken for the per-verdict tally line that
    # `final_report_generate._parse_audit_tally` scans for.
    vacuous_head = (f", {counts['VACUOUS_PASS']} VACUOUS-PASS excluded from "
                    f"executed" if counts.get("VACUOUS_PASS") else "")
    # vibe-ic#901 — ON THE HEADLINE TOO, for the reason spelled out beside
    # `voided_str` below: a bucket this line does not name is a bucket whose
    # steps silently vanish from the reader's arithmetic.
    vacuous_head += (
        f", {counts['PARTIALLY-VACUOUS']} PARTIALLY-VACUOUS excluded from "
        f"executed" if counts.get("PARTIALLY-VACUOUS") else "")
    vacuous_head += (
        f", {counts['STRUCTURE-ONLY']} STRUCTURE-ONLY excluded from executed"
        if counts.get("STRUCTURE-ONLY") else "")
    # vibe-ic#924 — the sub-gate waivers keep their place on the line a
    # reader actually reads, now NAMING THEIR UNIT so the number cannot be
    # read as steps. Appended AFTER the two fields every existing parser keys
    # on (`X/Y executed PASS,` then `W DEFERRED`) and with no `=`, per the
    # note above, so `final_report_generate._parse_audit_tally` still cannot
    # mistake this line for the per-verdict tally.
    subgate_head = (f", {p0_subgate_waivers} P0 sub-gate waiver(s) "
                    f"(not steps)" if p0_subgate_waivers else "")
    print(f"Steps: {len(steps)} total ({pass_count}/{total_required} executed PASS, "
          f"{counts['WAIVED']} DEFERRED via waiver{vacuous_head}{subgate_head})")
    skipped_str = f"  SKIPPED={counts.get('SKIPPED-CONDITION', 0)}" if counts.get("SKIPPED-CONDITION") else ""
    vacuous_str = (f"  VACUOUS-PASS={counts['VACUOUS_PASS']}"
                   if counts.get("VACUOUS_PASS") else "")
    vacuous_str += (f"  PARTIALLY-VACUOUS={counts['PARTIALLY-VACUOUS']}"
                    if counts.get("PARTIALLY-VACUOUS") else "")
    # ON THE LINE, or the parts stop summing to the total. The first cut of the
    # dependency write-back demoted 18 of 63 steps into a bucket this summary
    # does not print, so the line read 4+16+12+1+1+9+2 = 45 out of 63 and the
    # other 18 simply vanished — the silent loss this whole change exists to
    # remove, reintroduced by the change itself.
    voided_str = (f"  PASS-VOIDED={counts['PASS_VOIDED_BY_DEPENDENCY']}"
                  if counts.get("PASS_VOIDED_BY_DEPENDENCY") else "")
    incomplete_str = (f"  INCOMPLETE={counts['INCOMPLETE']}"
                      if counts.get("INCOMPLETE") else "")
    # v0.3.5 — #503: split cascade MISSING from independent gaps in the
    # summary so the actionable root-cause surface is visible at a
    # glance; #502: surface the waiver-chain bucket separately.
    missing_str = f"MISSING={counts['MISSING']}"
    _blocked = cascade_info.get("blocked_by_upstream") or {}
    _clauses = [f"{n} blocked-by-upstream of step {sid}"
                for sid, n in _blocked.items()]
    # vibe-ic#776 — these MISSING steps used to be DEFERRED-BY-UPSTREAM and
    # were subtracted from the denominator on an ORDERING edge alone. They are
    # counted here now, and the reader is told WHY they are all one shape, so
    # the honest MISSING does not read as N independent gaps. This is an
    # ATTRIBUTION over the MISSING bucket, not an additional bucket.
    _undeclared: Dict[Any, int] = {}
    for _sid, _anc in (cascade_info.get("waived_ancestor_undeclared") or []):
        _undeclared[_anc] = _undeclared.get(_anc, 0) + 1
    _clauses += [
        f"{n} ordered behind waived step {sid}, which declares no artefact "
        f"they read — MISSING, not deferred"
        for sid, n in _undeclared.items()]
    if _clauses:
        missing_str += " (" + "; ".join(_clauses) + ")"
    dbu_str = (f"  DEFERRED-BY-UPSTREAM={counts['DEFERRED-BY-UPSTREAM']}"
               if counts.get("DEFERRED-BY-UPSTREAM") else "")
    # THE THIRD DISPOSITION, ON THE LINE. Two shapes, because the fact is true
    # in two situations and a reader needs it in both:
    #   * a step that produced ONLY library-default artefacts and was
    #     otherwise clean lands in its own bucket, out of PASS;
    #   * a step that FAILED for another reason and ALSO produced one keeps
    #     the FAIL and carries the disclosure as a parenthetical, exactly the
    #     shape MISSING already uses for blocked-by-upstream. Nothing is
    #     double-counted: the parenthetical annotates a bucket, it is not one.
    so_failing = sum(1 for r in results
                     if r.status == "FAIL" and r.structure_only_disclosed)
    fail_str = f"FAIL={counts['FAIL']}"
    if so_failing:
        fail_str += (f" ({so_failing} also produced a library-default "
                     f"artefact, see STRUCTURE-ONLY below)")
    so_str = (f"  STRUCTURE-ONLY={counts['STRUCTURE-ONLY']}"
              if counts.get("STRUCTURE-ONLY") else "")
    # vibe-ic#901 - an ANNOTATION over the buckets, never a bucket. These steps
    # are already counted in whatever tier they resolved to (usually PASS);
    # adding them again would stop the parts summing to the total. What it says
    # is the thing the tier word cannot: N steps here contain at least one gate
    # clause that ran and examined nothing.
    partial_vacuous = sum(1 for r in results
                          if getattr(r, "partial_vacuity_disclosed", False))
    pv_str = (f"  ({partial_vacuous} step(s) PARTIALLY-VACUOUS: a gate clause "
              f"ran and examined nothing)" if partial_vacuous else "")
    # W4 — the SAME kind of annotation for the clauses that never ran at all,
    # and kept apart from PARTIALLY-VACUOUS because they are a different fact:
    # that one is a clause that ran and found nothing to look at, this one is a
    # clause that was not dispatched because its input was absent. Both leave
    # the tier alone (an ANNOTATION over the buckets, never a bucket, so the
    # parts still sum to the total); without this line the only trace of an
    # unexecuted clause is the per-step reason, and the number a reviewer reads
    # is the tally.
    na_steps = sum(1 for r in results
                   if getattr(r, "declared_not_applicable", None))
    na_clauses = sum(len(getattr(r, "declared_not_applicable", ()) or ())
                     for r in results)
    na_str = (f"  ({na_clauses} gate clause(s) across {na_steps} step(s) "
              f"NOT-APPLICABLE: the declared input was absent, so the clause "
              f"did not run)" if na_clauses else "")
    print(
        f"  PASS={counts['PASS']}  {fail_str}  "
        f"{missing_str}  WAIVED-DEFERRED={counts['WAIVED']}"
        f"{dbu_str}{skipped_str}{vacuous_str}{voided_str}{so_str}"
        f"{incomplete_str}{pv_str}{na_str}\n"
    )
    if p0_subgate_waivers:
        # vibe-ic#924 — ITS OWN LINE, deliberately not a token on the tally
        # line above. That line's contract is that its parts sum to the step
        # total; a sub-gate count sitting among them is what broke the sum.
        print(
            f"  P0 sub-gate waivers: {p0_subgate_waivers} (deferred structural "
            f"sub-gate(s) INSIDE step P0, review_required — NOT steps, and "
            f"NOT subtracted from the {total_required} required steps above; "
            f"see `thin_input_waivers` in the --json report and P0's own "
            f"reasons for the per-gate detail)\n"
        )
    if counts.get("STRUCTURE-ONLY") or so_failing:
        print(
            "  STRUCTURE-ONLY = the step ran and produced its declared "
            "artefact, and that artefact's content came from a library "
            "default because no bound input determined it. Not missing (the "
            "artefact exists and re-running produces the same one), not a "
            "design-bound pass (every number measured on it is a number "
            "about the default), not a failure (the inputs did not determine "
            "the content and inventing content to fill that gap is the "
            "defect this tier exists to make visible).\n"
        )

    _icon = {"PASS": "✓", "FAIL": "✗", "MISSING": "·", "WAIVED": "~",
             "INCOMPLETE": "…",
             "DEFERRED-BY-UPSTREAM": "~",
             "SKIPPED-CONDITION": "-", "SKIPPED-SETUP-REQUIRED": "!",
             "VACUOUS_PASS": "○", "PARTIALLY-VACUOUS": "◔",
             "STRUCTURE-ONLY": "◐",
             "PASS_VOIDED_BY_DEPENDENCY": "⊘"}
    _label = {"PASS": "PASS", "FAIL": "FAIL", "MISSING": "MISSING", "WAIVED": "WAIVED-DEFERRED",
              "DEFERRED-BY-UPSTREAM": "DEFERRED-BY-UPSTREAM",
              "SKIPPED-CONDITION": "SKIPPED-CONDITION",
              "SKIPPED-SETUP-REQUIRED": "SKIPPED-SETUP-REQUIRED",
              "VACUOUS_PASS": "VACUOUS-PASS",
              "PARTIALLY-VACUOUS": "PARTIALLY-VACUOUS",
              "PASS_VOIDED_BY_DEPENDENCY": "PASS-VOIDED",
              "STRUCTURE-ONLY": "STRUCTURE-ONLY",
              "INCOMPLETE": "INCOMPLETE"}
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
    # agent can RTL-repair/retry. Wave-21 fix: when --strict-structural is set
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
                # #497 step 2 — projected from the umbrella's records. This is
                # the highest-stakes of the four consumers: it is what sets
                # `forced_fail` under `--phase 2 --strict-structural`, the
                # flags `design_one_shot_runner.step_final_audit` ships, so a
                # mis-parse here does not mis-report a run, it FAILS one.
                #
                # The scrape it replaces keyed on `FAIL: ` / `- ` prefixes and
                # had to be taught, after the fact, that the #492 disclosure
                # bullets share the `  - ` prefix with Form 2 — without which
                # every never-invoked gate became a structural FAIL line and
                # gates that never ran forced the verdict. The projection has
                # no prefix to be confused by: it reads verdict == "FAIL".
                #
                # INFORMATIONAL_GATES (v0.1.62) are still excluded, still by
                # substring over the whole rendered line, inside
                # `_p0_structural_fail_lines` — a coverage gap is not a
                # deployment blocker and is already excluded from the
                # step-level verdict.
                structural_fail_lines.extend(
                    _p0_structural_fail_lines(_p0_gate_records(r)))
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
    ordering_gating_lines: List[str] = []
    try:
        import flow_step_execution_coverage_check as _cov
        _cov_graph = {
            str(st.get("id")): [str(e) for e in (st.get("blocks_on") or [])]
            for st in steps if st.get("id") is not None}
        _cov_report = {"steps": [
            {"id": r.id, "name": r.name, "status": r.status,
             "stage": getattr(r, "stage", "")} for r in results]}
        for v in _ordering_violations:
            ordering_fail_lines.append(
                f"[{v['terminal_id']}] {v['terminal']} = "
                f"{v['terminal_status']} marked done while dependency "
                f"[{v['signoff_id']}] {v['signoff']} = {v['signoff_status']}")
        # vibe-ic#1429 — BLOCKING, and it stays BLOCKING. A violation inside
        # the run's verdict scope still sets `forced_fail` before the verdict
        # and before the open-source-constraints promotion, so it still cannot
        # be softened away — the sentence above is unchanged. What changes is
        # WHICH violations are inside the scope, and only in the one mode that
        # narrows the scope at all.
        #
        # THE GUARD READS THE SAME VERDICT SCOPE EVERY OTHER BUCKET READS.
        # `scoped` above IS that scope: it is `results` in every
        # mode except `--phase 2 --strict-structural`, where it narrows to the
        # `P0` umbrella plus the analog track (#634). Filtering on it is
        # therefore a NO-OP in every other mode BY CONSTRUCTION — not a mode
        # branch that can be got wrong, and not a second list of step ids that
        # can drift from the one the verdict actually uses.
        #
        # WHAT IT FIXES. `--phase 2 --strict-structural` declares step-level
        # FAIL/MISSING informational, and says so in THREE places: the `scoped`
        # list above, the `structural_fail_lines` / `step_artifact_fail_lines`
        # split ("With --strict-structural alone they are info-only"), and the
        # report's own "Step-level gates (informational, not gating
        # --strict-structural)" heading. This guard was the ONE place that did
        # not, so a step-level MISSING re-entered the verdict through a side
        # door and the report contradicted itself two lines apart. MEASURED on
        # the fixture in `test_flow_compliance_check_gate.py::
        # test_strict_structural_only_structural_gates` — RTL present, no
        # L-docs, no structural FAIL:
        #
        #   Overall: FAIL  (strict=True)
        #   Step-level gates (informational, not gating --strict-structural): 5
        #   ✗ [1] Spec-to-RTL = PASS marked done while dependency
        #         [D1] Phase 1 Doc Extraction = MISSING      <- the sole cause
        #
        # `D1 = MISSING` IS a step-level MISSING. Left as it was, the flag can
        # only ever return FAIL on the input class it was built for (v0.119.53
        # Wave 21: "a structurally clean Phase-2 project was rejected because
        # lint/CDC/coverage/formal step artefacts were incomplete"), and
        # `--strict-step-artifacts` already exists for the other reading.
        #
        # SCOPED, NOT SUPPRESSED. `ordering_fail_lines` still carries EVERY
        # violation, so the printed block and the JSON `ordering_violations`
        # field are unchanged in every mode; only which of them reach
        # `forced_fail` changes, and the ones that do not are named on their
        # own line below rather than going quiet.
        _scoped_ids = {str(r.id) for r in scoped}
        # vibe-ic#1446 — THE ONE CASE THE DEPENDENCY TEST CANNOT SEE: a terminal
        # in scope that returned NO VERDICT AT ALL.
        #
        # #1429's rule above is right about what it measured. Its worked example
        # is a terminal that RAN, AUDITED and PASSED, and whose PASS is then
        # voided by an out-of-scope dependency — `PASS_VOIDED_BY_DEPENDENCY`.
        # For that step the void is a statement about CERTIFICATION, not about
        # measurement: the gates did look, and what they saw was clean. Calling
        # it informational in the mode that declares step-level state
        # informational is exactly right, and nothing here changes it.
        #
        # `INCOMPLETE` is the other thing entirely. It is the empty-denominator
        # tier (#599/#901/#947) — "the input was applicable and was NOT
        # examined". There is no measurement to hold informational, because
        # none was taken. MEASURED on the bare Phase-2 tree under `--phase 2
        # --strict-structural`, the mode that narrows the verdict scope to P0
        # ALONE:
        #
        #   [INCOMPLETE] Step P0: Structural-RTL gates
        #                (P0 umbrella, 0 of 246 checkers returned a verdict)
        #   ✗ [P0] … = INCOMPLETE marked done while dependency [D1] … = MISSING
        #   Overall: PASS   rc=0
        #
        # Zero of 246 checkers answered, the chain under them never ran, and the
        # only step in scope published a green verdict about it. That is the
        # input `test_strict_structural_does_not_excuse_a_broken_p0_ancestry`
        # (#923/#1078) owns, and it went red when #1429 landed three minutes
        # after it in the same batch, neither PR rebased on the other.
        #
        # A CONJUNCTION, AND BOTH HALVES ARE LOAD-BEARING. Neither condition
        # gates on its own, and the repo has already settled both halves
        # separately — this reads those decisions rather than reopening them:
        #   * INCOMPLETE ALONE STAYS GREEN. "gates that never ran must not force
        #     the verdict" (test_issue497_step2…::test_a_not_invocable_record_
        #     is_never_a_failing_gate) and "INCOMPLETE is a disclosure tier, not
        #     a failure — it must not turn a run red on its own"
        #     (test_p0_umbrella_verdict_coverage). Those fixtures run over a
        #     SATISFIED `blocks_on` chain, so they raise no ordering violation
        #     and never reach this list.
        #   * A BROKEN ANCESTRY ALONE STAYS GREEN, which is #1429 itself: the
        #     PASS_VOIDED terminal above is not INCOMPLETE, so it is not in
        #     `_no_verdict_ids` and does not gate.
        # Together they say the verdict scope holds no evidence: nothing was
        # measured, AND the inputs that would have been measured were never
        # produced. `_no_verdict_ids` is built from `scoped`, so it is a SUBSET
        # of `_scoped_ids` by construction and this stays a no-op in every mode
        # that does not narrow the scope.
        _no_verdict_ids = {str(r.id) for r in scoped
                           if r.status == "INCOMPLETE"}
        ordering_gating_lines = [
            line for line, v in zip(ordering_fail_lines, _ordering_violations)
            if str(v['signoff_id']) in _scoped_ids
            or str(v['terminal_id']) in _no_verdict_ids]
        if ordering_gating_lines:
            forced_fail = True
    except Exception:  # nosec — additive enforcement must never crash the audit
        ordering_fail_lines = []
        ordering_gating_lines = []
        _ordering_violations = []

    if not ok or forced_fail:
        overall = "FAIL"
    elif counts["WAIVED"] > 0 or p0_subgate_waivers > 0:
        # vibe-ic#924 — the second disjunct is what the removed addend was
        # actually for (v1.6.97 / issue #29: "so Overall verdict resolves to
        # PASS_WITH_WAIVERS (not bare PASS) whenever the --allow-thin-input
        # waiver actually fired"). It was expressed as an addend into a step
        # counter, but the consumer is this `> 0` test, so a boolean carries
        # it exactly and no run changes its verdict word.
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
        # #497 step 2 — from the umbrella's records, not from its prose. This
        # feeds the second of the two `all(...)` predicates: a name that is not
        # in _P0_THIN_INPUT_DEFERRABLE_SUBGATES turns a deferrable run into a
        # FAIL, and under the prose contract a disclosure bullet supplied 37
        # such names on a run with 2 real failures.
        p0_subgate_fails = _p0_failing_gate_names(_p0_gate_records(p0_result))
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
        # DFT_FCC / 11-d7 — oss_blocked_skipped members are in the table by
        # construction, so they never add to non_blocked_failing; they are
        # included for the same reason failing/missing are, so a future edit
        # to the table cannot silently drop them from the promotion guard.
        for r in failing + missing + oss_blocked_skipped:
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
        # DFT_FCC / 11-d7 — a self-skipped sign-off step is a deferral the
        # tapeout vendor's must-close list cannot omit either.
        deferral_source = list(failing) + list(missing) + list(oss_blocked_skipped)
        deferral_source += [r for r in informational_only_failing
                            if (r.id in _OPEN_SOURCE_CONTAINER_BLOCKED_STEPS
                                or (r.id == "P0" and p0_is_deferrable))]
        if (not non_blocked_failing
                and not forced_fail_effective
                and (failing or missing or informational_only_failing
                     or oss_blocked_skipped)
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
        # vibe-ic#924 — this sentence says "step(s)", so it gets the STEP
        # count. The sub-gate waivers are a second sentence in their own unit
        # rather than a silent addition to this one; a run waived only at
        # sub-gate level used to print "N step(s) DEFERRED" with N steps
        # deferred being zero.
        if counts["WAIVED"]:
            print(f"  ⚠ {counts['WAIVED']} step(s) DEFERRED via waiver — production tapeout review must close them.")
        if p0_subgate_waivers:
            print(f"  ⚠ {p0_subgate_waivers} P0 sub-gate(s) DEFERRED via "
                  f"waiver (structural sub-gates inside step P0, not steps) — "
                  f"production tapeout review must close them.")
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
    # DFT_FCC / 11-d7 — never let a sign-off-bar self-skip pass unmentioned at
    # the verdict line, whether or not the promotion tier fired.
    if oss_blocked_skipped and overall != "PASS_WITH_OPEN_SOURCE_CONSTRAINTS":
        print(f"  ⚠ {len(oss_blocked_skipped)} SIGN-OFF step(s) SELF-SKIPPED "
              f"(disclosed capability gap on a step this flow lists as an "
              f"open-source-container sign-off bar) — review required:")
        for r in oss_blocked_skipped:
            print(f"    • Step {r.id} ({r.name}) — needs "
                  f"{_OPEN_SOURCE_CONTAINER_BLOCKED_STEPS.get(r.id, '?')}")
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
        # vibe-ic#1429 — DEGRADE LOUDLY. A violation this run's verdict scope
        # does not reach is still printed above; this line says so by name, so
        # "reported but not gating" is a statement the reader can SEE rather
        # than a difference they have to infer from the verdict word. Emitted
        # only when the two lists actually differ, so no existing mode's
        # output gains a line. Counted by LENGTH, not by set difference: two
        # violations can render the same line and a set would report one of
        # them as missing from a list it is in.
        _n_info = len(ordering_fail_lines) - len(ordering_gating_lines)
        if _n_info > 0:
            print(f"  ({_n_info} of {len(ordering_fail_lines)} "
                  f"reported, NOT gating: the dependency named is outside "
                  f"this run's verdict scope. Use --strict-step-artifacts to "
                  f"gate on these too.)")

    if advisories:
        print("\nAdvisories:")
        for adv in advisories:
            print(f"  ⚠ {adv}")

    # ── the classified blocker list, beside the tally ──────────────────────
    #
    # THE TALLY IS NOT A MEASUREMENT OF THE DESIGN and this is the part that
    # is. Measured in one round on one cell: real post-route 3-corner STA —
    # strictly BETTER evidence — scored 17 PASSes LOWER, and disabling a
    # deliberate cross-step check scored 2 PASSes HIGHER with the design
    # untouched. X/Y moved twice, in opposite directions, for reasons that had
    # nothing to do with the design. What describes the design is which steps
    # are not green and WHAT EACH ONE IS — plugin defect, design fact, missing
    # capability — and until this block that classification existed only as
    # prose an agent might write, in a shape no consumer could read.
    #
    # STRICTLY ADDITIVE, and the ordering here is the proof: `overall`,
    # `counts`, every promotion tier and every exit-code decision are already
    # settled above. Nothing below is read by any of them. A classification
    # that could move a verdict would immediately be worth gaming, which is the
    # disease this exists to diagnose.
    #
    # Wrapped, for the same reason the audit emission below is wrapped: a
    # defect in the classifier must not be able to change what this program
    # reports about a chip. It is NOT silent — the failure is printed and, when
    # `--json` is on, recorded in the report, because an empty blocker list
    # that means "the classifier crashed" and an empty one that means "nothing
    # is blocked" must not be the same artifact.
    blocker_list_error = ""
    # ONLY the steps this run ACTUALLY routed into the open-source-constraints
    # deferral — never bare membership of `_OPEN_SOURCE_CONTAINER_BLOCKED_STEPS`.
    # The table says "this step would also need a commercial tool to SIGN OFF",
    # which is true of steps that are on the blocker list for entirely other
    # reasons. Measured before narrowing: table membership classified 10 of 41
    # blockers on the reference run as MISSING_CAPABILITY, four of them
    # PASS_VOIDED_BY_DEPENDENCY and one a step whose own gate program ran and
    # returned a verdict. `oss_blocked_skipped` and `os_constraints_deferrals`
    # are decisions this run made; the table is a lookup that answers a
    # neighbouring question.
    _oss_deferred: Dict[Any, str] = {}
    for _r in oss_blocked_skipped:
        _oss_deferred[_r.id] = _OPEN_SOURCE_CONTAINER_BLOCKED_STEPS.get(
            _r.id, "a commercial tool")
    for _d in os_constraints_deferrals:
        if _d.get("commercial_tool_required"):
            _oss_deferred[_d["step_id"]] = _d["commercial_tool_required"]
    try:
        blockers = _bc.build_blockers(
            results,
            flow_steps=steps,
            oss_blocked=_oss_deferred,
            gate_summary_fn=_declared_gate_summary)
        for _line in _bc.render_lines(blockers):
            print(_line)
    except Exception as _bc_exc:  # pragma: no cover - defence in depth
        blockers = []
        blocker_list_error = f"{type(_bc_exc).__name__}: {_bc_exc}"
        print(f"flow_compliance_check: WARN — blocker classification failed "
              f"({blocker_list_error}); the list below is EMPTY BECAUSE OF "
              f"THAT, not because nothing is blocked", file=sys.stderr)
    blocker_class_counts = _bc.class_counts(blockers)
    blocker_sub_class_counts = _bc.sub_blocker_class_counts(blockers)

    # ── the contract guard on the list above, run BY THE PRODUCER ──────────
    #
    # `blocker_classification_check` is the guard on exactly the artefact this
    # block just built: the list is complete over the non-PASS steps, invents
    # none, names in `basis` the rule that decided each class, and the headline
    # counts sum to the list. It shipped with NOTHING but its own unit test
    # running it — zero coverage of real reports, a fixture the author wrote
    # proving the logic and never the artefacts (vibe-ic#381). Compliance
    # reports are produced HERE, so this is the one place the guard is handed a
    # real one every time one exists.
    #
    # ADVISORY HERE, DELIBERATELY, and it is the same rule the block above
    # states rather than a hedge: nothing in this section may move a verdict
    # about a chip. `overall`, `counts`, every promotion tier and every
    # exit-code decision are settled above and none of them reads this. A
    # contract violation is a defect in the CLASSIFIER, not a fact about the
    # design, and a classifier that could fail a chip would immediately be
    # worth gaming. So it is disclosed by name — on stderr and in the report —
    # and the verdict is left alone.
    #
    # The BLOCKING copy of the same guard is the sweep over committed reports
    # in `tools/ci/repo_hygiene_gates.sh`, which is where a violation that
    # reaches the corpus is refused.
    #
    # Wrapped for the same reason the classifier call is: a defect in the guard
    # must not be able to break a flow run. A guard that could not run is
    # itself recorded, never silently empty.
    blocker_contract_violations: List[str] = []
    try:
        blocker_contract_violations, _bcc_facts = _bcc.check_report({
            "overall": overall,
            "steps": [asdict(r) for r in results],
            "blockers": blockers,
            "blocker_class_counts": blocker_class_counts,
            "blocker_list_error": blocker_list_error,
        })
    except Exception as _bcc_exc:  # pragma: no cover - defence in depth
        blocker_contract_violations = [
            f"the blocker-list contract guard could not run: "
            f"{type(_bcc_exc).__name__}: {_bcc_exc}"]
    if blocker_contract_violations:
        print(f"flow_compliance_check: WARN — the classified blocker list "
              f"breaks its own contract in "
              f"{len(blocker_contract_violations)} place(s). The list is "
              f"published WITH this disclosure beside it; the verdict above is "
              f"about the design and is untouched.", file=sys.stderr)
        for _v in blocker_contract_violations:
            print(f"  - {_v}", file=sys.stderr)

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
            # vibe-ic#1429 — the SUBSET that reached `forced_fail`. The field
            # above is unchanged (every violation, every mode); this one says
            # which of them this run's verdict scope actually reached, so a
            # consumer never has to re-derive the scope to know why a run with
            # a reported violation is nonetheless green.
            "ordering_violations_gating": ordering_gating_lines,
            # THE CLASSIFIED BLOCKER LIST, machine-readable, beside the tally.
            # `counts` says how many; this says what each one IS, with the rule
            # that decided it named in `basis` so a reader can audit the
            # classification instead of trusting it. UNCLASSIFIED is a
            # first-class answer here: an honest hole is workable, a wrong
            # class is not.
            "blocker_schema_version": _bc.SCHEMA_VERSION,
            "blockers": blockers,
            "blocker_class_counts": blocker_class_counts,
            "blocker_sub_class_counts": blocker_sub_class_counts,
            # Empty string on the normal path. Non-empty means the list above
            # is empty because the classifier failed, which is a completely
            # different fact from "nothing is blocked".
            "blocker_list_error": blocker_list_error,
            # Empty list on the normal path. Non-empty means the list above
            # breaks its own contract — a defect in the classifier, disclosed
            # rather than folded into the design's verdict. A reader who trusts
            # `blockers` must read this first.
            "blocker_contract_violations": blocker_contract_violations,
            "gate_execution_ledger": _gate_ledger_payload(),
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
        # Per-gate verdicts from the P0 (structural-RTL) umbrella so the
        # JSON is self-contained.
        # Wave 91 / v1.6.15 — id key was renamed -1 → "P0".
        #
        # #497 step 2 — PROJECTED from the umbrella's records. What this
        # replaces read the two prose shapes (Form 1 `FAIL: gate — msg` and
        # Form 2 `  - gate — msg` under a `Failed gates (N):` header) and
        # originally knew only Form 1 — the shape is chosen by the failure
        # COUNT, so `gates` and `failed_gates` came out EMPTY exactly when two
        # or more gates failed. There is now no shape to know.
        p0_audit_result = next(
            (r for r in results if r.id == "P0"), None)
        per_gate: List[Dict[str, Any]] = _p0_audit_gate_records(
            _p0_gate_records(p0_audit_result))
        # The canonical failed-gate list: one projection, no reconciliation.
        # It used to be assembled from three sources and de-duplicated, which
        # is what an assembly of three sources requires.
        failed_gate_names: List[str] = _p0_failing_gate_names(
            _p0_gate_records(p0_audit_result))
        # #497 step 4 — a BACKSTOP stood here too, reconciling the list above
        # against the promotion logic's own view of which sub-gates failed. It
        # existed because two independent parsers of one prose list had already
        # disagreed once. Both sides are now the same projection of the same
        # records, so it could add nothing — kept through step 2 while the
        # scrapers were still in the tree, removed with them. A reconciliation
        # between a thing and itself is not a safety net; it is a second place
        # to have to keep correct.
        #
        # A fifth scrape stood here as well: a `^([\w.]+_check)\b` match
        # over each `structural_fail_lines` entry, added as a third source of
        # failing-gate names "for cases where reasons are formatted differently
        # between gate implementations". It could never contribute. Whenever
        # `structural_fail_lines` is non-empty the P0 umbrella FAILed, and the
        # pass above it has already added every failing gate the umbrella
        # recorded — and had it ever been the only source, it would have
        # silently dropped the 15 registered gates whose names do not end in
        # `_check`. Measured on 27 real runs before removal: it added nothing on
        # every one.

        # #497 step 2 — the count of PASS records. `structural_passed_count`
        # is None only when the umbrella did not run at all (stage 3/4), where
        # there is no P0 step, no records and 0 is the truth. The historical
        # derivation — `sum(1 for g in per_gate if verdict == "PASS")` over a
        # list built by scanning `reasons` for `PASS: <gate>` lines the
        # umbrella has never emitted — could only ever report 0, and did, on
        # every run in this artifact's history.
        passed_gate_count = (
            structural_passed_count if structural_passed_count is not None
            else 0)

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

        # v1.6.27: route via auto-router so the audit lands at
        # reports/audit/ (canonical), not stray reports/ root. Resolved HERE,
        # ahead of the dict, because the footprint subtraction below has to
        # name it: it is written after the post-scan is taken, so measurement
        # cannot see it, and leaving it in would make the PREVIOUS run's audit
        # an input to THIS run's design hash.
        audit_path = _pl.report_path(project, "phase23_completion_audit.json")

        # ── what this tally was computed OVER ────────────────────────────
        # Two hashes, because "did the design change?" and "did the ruler
        # change?" are independent questions with four answers between them.
        # Both blocks are null-with-a-reason on any failure; neither can move
        # the verdict.
        _digest_block: Any = None
        _measurement_block: Any = None
        _prior_audit: Any = None
        # Asked directly, not read back out of the measurement block: the
        # release that produced an artefact is a fact this file owes its
        # reader even when the digest could not be computed.
        try:
            import plugin_manifest_discovery as _pmd
            _running_version = _pmd.running_plugin_version()
        except Exception:
            _running_version = "UNRESOLVED"
        # The audit being OVERWRITTEN is the other half of the comparison, and
        # it is on disk right now. This is the exact shape the finding came
        # from — the same run directory, re-judged — so the artefact can state
        # which of the two moved without any consumer coordinating. It is also
        # where the previous run's footprint is carried from.
        try:
            if audit_path.exists():
                _loaded = json.loads(audit_path.read_text(encoding="utf-8"))
                if isinstance(_loaded, dict):
                    _prior_audit = _loaded
        except (OSError, ValueError):
            _prior_audit = None
        _carried = []
        try:
            _pb = (_prior_audit or {}).get("design_input_digest") or {}
            _carried = [p for p in (_pb.get("auditor_written_paths") or [])
                        if isinstance(p, str)]
        except Exception:
            _carried = []
        if _did is not None and _did_scan is not None:
            try:
                _also_written = [str(audit_path.relative_to(project))]
                if args.json:
                    _rep = Path(args.json).resolve()
                    if project in _rep.parents:
                        _also_written.append(str(_rep.relative_to(project)))
                _post = _did.scan_inputs(project)
                _digest_block = _did.build_digest(
                    _did_scan,
                    _did.auditor_footprint(_did_scan, _post, _also_written,
                                           _carried))
            except Exception as _exc:
                _digest_block = {"schema_version": _did.SCHEMA_VERSION,
                                 "sha256": None,
                                 "unusable_reason": f"digest failed: {_exc}"}
        elif _did_error:
            _digest_block = {"schema_version": 1, "sha256": None,
                             "unusable_reason": _did_error}
        if _did is not None:
            try:
                _measurement_block = _did.build_measurement(
                    _running_version, flow_path, vars(args))
            except Exception as _exc:
                _measurement_block = {"schema_version": _did.SCHEMA_VERSION,
                                      "id": None,
                                      "unusable_reason": str(_exc)}

        # vibe-ic#1001 — the verdict this audit is ENTITLED to write. Computed
        # here rather than inline in the dict so the decision is one testable
        # function; `overall` itself is untouched, so the exit code and every
        # other consumer keep the FAIL. See `completion_audit_verdict`.
        _audit_verdict, _audit_refusal = completion_audit_verdict(
            overall,
            structural_invoked_count,
            counts,
            structural_fail_lines,
            step_artifact_fail_lines,
            structural_registered_count,
        )

        from datetime import datetime, timezone
        audit = {
            "schema_version": 1,
            # Was the string literal "0.119.62" from the initial public
            # release: all 28 tracked audit artefacts carry it, so an audit
            # written by 1.0.0 and one written by 1.9.79 made byte-identical
            # claims about which ruler produced them. It is READ now, from the
            # one manifest `gatekeeper_assign_version --write` owns. #800 did
            # this for `emitted_by`/`generated_by`/`extracted_by`; the key here
            # is `version`, which is not in that gate's attribution-key list,
            # which is how it survived.
            "version": _running_version,
            "run_at": datetime.now(timezone.utc).isoformat(),
            "phase": args.phase,
            "strict_structural": bool(args.strict_structural),
            "strict_step_artifacts": bool(args.strict_step_artifacts),
            "verdict": _audit_verdict,
            # Non-null ONLY when this audit refused (`INSUFFICIENT_DATA`): the
            # denominator that made it refuse, so the refusal can be read
            # without re-deriving it from the counts below.
            "verdict_refusal_reason": _audit_refusal,
            # The run's own status, ALWAYS — unchanged by the refusal above and
            # identical to the exit code and the stdout verdict line. A refusal
            # narrows what the audit CLAIMS, never what the run IS.
            "run_status": overall,
            "gates": per_gate,
            "failed_gates": failed_gate_names,
            "failed_gate_count": len(failed_gate_names),
            "passed_gate_count": passed_gate_count,
            # THE DENOMINATOR, and the part of it that never answered.
            #
            # Every gate count above is a NUMERATOR. The population they are
            # counted out of appeared in this file only inside the P0 step's
            # `name` string, so a consumer of this artifact — the mcp-eda
            # pre-burn guard, any dashboard — could read `passed_gate_count: 6`
            # and had nothing to divide it by. Worse, the number it would have
            # guessed (the registry size) is the WRONG one: 36 of 246 registered
            # gates reject the argv the umbrella builds, return no verdict at
            # all, and are not in any of the three counts above.
            #
            # THREE FIELDS, not two, and `not_invocable` is not left to
            # subtraction: `registered - invoked` is only equal to it while
            # every registered gate has exactly one record, which is an
            # invariant of the dispatch loop and not of this artifact. A reader
            # who subtracts is re-deriving a fact the producer already knows.
            #
            # `null` on a stage-3/4 invocation, where the umbrella did not run —
            # the same three-state `gate_records` publishes, for the same reason.
            "registered_gate_count": structural_registered_count,
            "invoked_gate_count": structural_invoked_count,
            "not_invocable_gate_count": structural_not_invocable_count,
            "step_counts": counts,
            # vibe-ic#1969 — the tally and the records it counted travel in
            # ONE canonical artifact.  `final_report_generate` consumes
            # `step_counts` for its global roll-up and `steps[].status` for
            # its per-step table; omitting the latter forced the renderer to
            # scrape human stdout and create a second, drifting tally.
            # Both values project the SAME final `results` objects after
            # ordering/cascade re-tiering, immediately before this write.
            "steps": [asdict(r) for r in results],
            "structural_fail_lines": structural_fail_lines,
            "step_artifact_fail_lines": step_artifact_fail_lines,
            "missing_required_artifacts": missing_required,
            # v1.6.210 (#91) — surface OS-constraints deferral list in
            # the audit JSON so downstream tooling can render the
            # tape-out vendor's "must-close" list without re-deriving
            # it. Empty list when the verdict is not
            # PASS_WITH_OPEN_SOURCE_CONSTRAINTS.
            "open_source_constraints_deferrals": os_constraints_deferrals,
            # DFT_FCC / 11-d7 — the sign-off-bar steps that SELF-SKIPPED.
            # These used to appear nowhere in the verdict path (they were
            # only subtracted from total_required), so a DFT / formal /
            # post-DFT-LEC sign-off gap could sit inside a run reported as
            # PASS. Surfaced here by step id so a reviewer and any dashboard
            # can see the gap without re-deriving it from the per-step table.
            "open_source_blocked_self_skipped_steps": [
                {"step_id": r.id, "step_name": r.name,
                 "commercial_tool_required":
                     _OPEN_SOURCE_CONTAINER_BLOCKED_STEPS.get(r.id, "?"),
                 "review_required": True}
                for r in oss_blocked_skipped
            ],
            # The classified blocker list, in the artifact the mcp-eda
            # pre-burn guard and the dashboards already read. `failed_gates`
            # here is a list of NAMES; this is the same population with the
            # one fact a name does not carry — whether closing it is a plugin
            # fix, a design FAIL that must never be greened, or a capability
            # to name.
            "blocker_schema_version": _bc.SCHEMA_VERSION,
            "blockers": blockers,
            "blocker_class_counts": blocker_class_counts,
            "blocker_sub_class_counts": blocker_sub_class_counts,
            "blocker_list_error": blocker_list_error,
            "blocker_contract_violations": blocker_contract_violations,
            "gate_execution_ledger": _gate_ledger_payload(),
            "command_argv": list(sys.argv),
            # THE POPULATION, beside the tally. `design_input_digest` is what
            # the verdict was computed over; `measurement` is what computed
            # it. A consumer holding two of these artefacts can state which of
            # the two moved — which is the one thing no reader of this file
            # could do before, and the reason a day of inflated PASS counts
            # was reported as design progress.
            "design_input_digest": _digest_block,
            "measurement": _measurement_block,
        }
        # And when there IS a prior audit at this path — the re-judge of one
        # run directory, exactly the shape the finding came from — the
        # artefact says it itself rather than waiting for a consumer to.
        if _did is not None:
            try:
                audit["tally_delta"] = _did.classify(_prior_audit, audit)
            except Exception as _exc:
                audit["tally_delta"] = {
                    "classification": "NOT_COMPARABLE",
                    "statement": f"comparison failed: {_exc}"}
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit_path.write_text(
            json.dumps(audit, indent=2, ensure_ascii=False))
        # Printed, not only serialised: the reader who acts on the tally reads
        # the log, and a refusal that only exists in a JSON field is a refusal
        # nobody sees. Advisory — it never moves the verdict or the exit code,
        # because it is a statement ABOUT the measurement, not one of the
        # gates being measured.
        _td = audit.get("tally_delta") or {}
        if _td.get("classification") in ("MEASUREMENT_CHANGE",
                                         "UNEXPLAINED_TALLY_MOVE",
                                         "NOT_ATTRIBUTABLE"):
            print(f"flow_compliance_check: TALLY_DELTA "
                  f"{_td.get('classification')} — {_td.get('statement')}")
    except Exception as e:
        # Never let the audit-emission step fail the gate itself.
        # Surface a stderr warning so a human reviewer can spot it.
        print(f"flow_compliance_check: WARN — could not emit "
              f"phase23_completion_audit.json: {e}", file=sys.stderr)

    # ORGANIC #682 — the attribution block. Printed on EVERY run, before the
    # verdict, so `grep <gate> flow_compliance_check.log` answers the question a
    # reader is actually asking: did this gate run? A block emitted only when
    # something failed would leave the passing case exactly as unreadable as it
    # was, which is the defect.
    for _line in gate_ledger_lines():
        print(_line)

    # THE DENOMINATOR, BESIDE THE VERDICT. Printed on EVERY run and LAST, after
    # the ledger: `step_final_audit` keeps only the final 25 lines of this
    # stdout as the step's detail, so a disclosure emitted next to `Overall:`
    # — 130+ lines earlier — never reaches the one consumer that needs it. It
    # is advisory by construction: it moves no verdict and no exit code, it
    # states what the verdict was computed over. See
    # `structural_measurement_line`.
    print(structural_measurement_line(structural_registered_count,
                                      structural_invoked_count))

    # v1.6.210 (#91) — PASS_WITH_OPEN_SOURCE_CONSTRAINTS exits 0 (it is
    # a recognised verdict tier, not a FAIL). PASS, PASS_WITH_WAIVERS,
    # and PASS_WITH_OPEN_SOURCE_CONSTRAINTS all exit 0; FAIL exits 1.
    if overall in ("PASS", "PASS_WITH_WAIVERS",
                   "PASS_WITH_OPEN_SOURCE_CONSTRAINTS"):
        return 0
    return 1


if __name__ == "__main__":
    # A stall is not a verdict about the subject: it reaches the exit
    # code as rc 2 (UNDETERMINED), announced, never as a finding.
    sys.exit(_pr.exit_undetermined_on_stall(main))
