"""v1.6.523 — class-aware Phase-2 verification gating.

Covers the five fixes that close the systematic 21-IC benchmark gap
where Phase-2 verification was hardwired to a half-duplex AID-protocol
peripheral, so generic digital IP (CPUs, crypto, arithmetic primitives,
bit-serial cores) could NEVER pass even with clean synth + passing sim.

All tests run WITHOUT docker.

Honesty invariants asserted alongside the new escape paths:
  * a generic_full_stack class with a REAL DUT compile failure still
    FAILs the reference TB,
  * a multi-bit same-cycle NBA race on a non-bit-serial design still
    FAILs,
  * a genuine positive analog mention still counts.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from _skill_routes import assert_route_ships

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import ic_class_profile as icp  # noqa: E402
import design_one_shot_runner as p2  # noqa: E402
import flow_compliance_check as fcc  # noqa: E402
import analog_content_detected_must_emit_l5_check as acd  # noqa: E402
import _vacuous_exit as _vx  # noqa: E402

NBA_GATE = PROGRAMS / "nba_shift_register_same_cycle_read_check.py"


# ---------------------------------------------------------------------
# Fix 1 — registry verification_track + profile accessor
# ---------------------------------------------------------------------
def test_registry_is_valid_json_and_carries_tracks():
    reg = json.loads((PROGRAMS / "ic_class_registry.json").read_text())
    by_name = {c["name"]: c for c in reg["classes"]}
    # Every class must carry a verification_track.
    for c in reg["classes"]:
        assert c.get("verification_track") in (
            "aid_protocol", "generic_full_stack"), c["name"]
    # digital_arithmetic_primitive → generic_full_stack.
    assert by_name["digital_arithmetic_primitive"]["verification_track"] \
        == "generic_full_stack"
    # processor_cpu / soc class exists with the right flags.
    cpu = by_name["processor_cpu"]
    assert cpu["verification_track"] == "generic_full_stack"
    assert cpu["command_protocol_applicable"] is False
    assert cpu["analog_applicable"] is False
    assert cpu["half_duplex_bus"] is False
    # Existing AID protocol class stays aid_protocol.
    assert by_name["aid_class_half_duplex_single_wire"]["verification_track"] \
        == "aid_protocol"


def test_profile_accessor_flags():
    f = icp.class_verification_flags("processor_cpu")
    assert f["verification_track"] == "generic_full_stack"
    assert f["command_protocol_applicable"] is False
    assert f["analog_applicable"] is False
    assert icp.is_aid_protocol_track("processor_cpu") is False
    # soc synonym resolves.
    assert icp.class_verification_flags("soc")["verification_track"] \
        == "generic_full_stack"
    # AID class stays on the protocol track.
    assert icp.is_aid_protocol_track("aid_class_half_duplex") is True


def test_profile_accessor_fail_closed_for_unknown():
    """Unknown / unregistered class fails closed to aid_protocol so the
    existing AID FAIL logic keeps running."""
    f = icp.class_verification_flags("totally_made_up_class_xyz")
    assert f["verification_track"] == "aid_protocol"
    assert f["registry_matched"] is False
    assert icp.is_aid_protocol_track("totally_made_up_class_xyz") is True


# ---------------------------------------------------------------------
# Fix 2 — phase2 reference TB SKIP/PASS for generic_full_stack classes,
#          honesty: real compile failure still FAILs.
# ---------------------------------------------------------------------
def _make_project_with_l9(tmp_path: Path, rtl: str, top: str = "core_top",
                          ports=None):
    proj = tmp_path
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    ports = ports or [
        {"name": "clk", "direction": "input"},
        {"name": "reset_n", "direction": "input"},
        {"name": "data_in", "direction": "input"},
        {"name": "data_out", "direction": "output"},
    ]
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": top, "top_ports": ports}))
    rtl_dir = proj / "phase2" / "stage1" / "rtl"
    rtl_dir.mkdir(parents=True, exist_ok=True)
    (rtl_dir / f"{top}.v").write_text(rtl)
    return proj


def test_predicate_skips_aid_tb_for_generic_class():
    uses, reason = p2._class_uses_aid_reference_tb("processor_cpu")
    assert uses is False
    assert "aid" in reason.lower() or "half" in reason.lower()
    # Fail-closed for unknown.
    uses2, _ = p2._class_uses_aid_reference_tb(None)
    assert uses2 is True


def test_generic_class_reference_tb_skips_when_no_full_stack_tb(tmp_path):
    """generic_full_stack class with NO generic TB → SKIP (not FAIL),
    with the canonical 'gate-level synth + Phase 3' reason."""
    top = "core_top"
    rtl = (f"module {top}(input clk, input reset_n, input data_in, "
           f"output data_out); assign data_out = data_in; endmodule\n")
    proj = _make_project_with_l9(tmp_path, rtl, top)
    sr = p2.step_reference_tb(proj, top, "processor_cpu")
    assert sr.status == "SKIP"
    assert "Phase 3" in sr.detail
    assert sr.extras.get("verification_track") == "generic_full_stack"


def test_generic_class_reference_tb_runs_full_stack_tb(tmp_path):
    """When the generic full-stack TB was built (via step_full_stack_tb_gen)
    the reference TB step uses it as the functional gate."""
    top = "core_top"
    rtl = (f"module {top}(input clk, input reset_n, input data_in, "
           f"output data_out); assign data_out = data_in; endmodule\n")
    proj = _make_project_with_l9(tmp_path, rtl, top)
    # Emit the generic full-stack TB skeleton like the runner does.
    # ORGANIC-20260528: with no concrete L3 golden, the TB-gen now
    # honestly returns SKIP (connectivity-only, functional UNVERIFIED)
    # rather than a fabricated functional PASS. The TB file is still
    # emitted, which is all step_reference_tb needs.
    gen = p2.step_full_stack_tb_gen(proj, top)
    assert gen.status in ("PASS", "SKIP")
    tb = (proj / "phase2" / "stage1" / "sim_full_stack"
          / f"tb_{top}_full.v")
    assert tb.is_file()
    sr = p2.step_reference_tb(proj, top, "processor_cpu")
    # ORGANIC-20260606 #439: a skeleton TB running to completion is
    # CONNECTIVITY evidence only — never a functional PASS, and never an
    # AID-TB false FAIL. PASS is reserved for a real per-IC oracle TB with
    # golden compares.
    #
    # THE TIER IS INCOMPLETE, NOT WAIVED (#1975, cbe6154a6). WAIVED reads as
    # "disposed of"; this step has work outstanding — the per-IC oracle TB —
    # and Step 4's `cpu_functional_oracle_waiver_check` keeps blocking until
    # it exists. SKIP remains correct for the sibling case where no
    # full-stack TB was built at all, so both words are still asserted in
    # this file and the two states cannot collapse into one another.
    assert sr.status == "INCOMPLETE", sr.detail
    assert sr.extras.get("verification_track") == "generic_full_stack"
    assert "aid" in sr.detail.lower()
    assert sr.extras.get("functional_verified") is False
    assert sr.extras.get("capability_gap") == "cap:cpu_functional_oracle"
    # PROPERTY, not literal: the agent must be handed a route it can
    # actually follow. See _skill_routes.py.
    assert_route_ships(sr.extras.get("fallback_skill"),
                       "step_reference_tb INCOMPLETE extras")


def test_generic_class_real_compile_failure_still_fails(tmp_path):
    """HONESTY: a genuinely broken DUT (syntax error) compiled against
    the generic full-stack TB still FAILs — the escape path does NOT
    auto-pass real defects. Requires iverilog; skip if unavailable."""
    import shutil
    if not shutil.which("iverilog"):
        pytest.skip("iverilog not available")
    top = "core_top"
    # Deliberate syntax error: missing semicolon + bogus token.
    rtl = (f"module {top}(input clk, input reset_n, input data_in, "
           f"output data_out); assign data_out = $$$ data_in endmodule\n")
    proj = _make_project_with_l9(tmp_path, rtl, top)
    gen = p2.step_full_stack_tb_gen(proj, top)
    # ORGANIC-20260528: TB-gen verdict is honest (SKIP without a golden),
    # but the TB file is still emitted so step_reference_tb can compile it.
    assert gen.status in ("PASS", "SKIP")
    sr = p2.step_reference_tb(proj, top, "processor_cpu")
    assert sr.status == "FAIL"
    assert "defect" in sr.detail.lower() or "compile" in sr.detail.lower()


def test_absent_compiler_is_distinguished_from_a_rejected_source():
    """vibe-ic#1394 — the predicate that separates "could not measure" from
    "measured and found a defect". Host-independent: no simulator needed.

    The NEGATIVE direction is the load-bearing half. A genuine compile error
    over a missing `include` also says "No such file or directory", so a
    predicate that matched on that phrase would convert real structural
    defects into skips — the inverse of the bug, and strictly worse than it.
    """
    # Failed to EXECUTE: our own wrappers' marker, and the shell's own rc.
    assert p2._compiler_was_not_found(
        127, "", "COMMAND_NOT_FOUND: [Errno 2] No such file or "
                 "directory: 'iverilog'")
    assert p2._compiler_was_not_found(
        127, "", "bash: line 1: : command not found")
    # RAN and rejected the source -> must NOT read as not-found, even when the
    # message carries the very phrase a missing binary produces.
    assert not p2._compiler_was_not_found(
        1, "", "core_top.v:3: Include file foo.vh not found: "
               "No such file or directory")
    assert not p2._compiler_was_not_found(1, "", "syntax error near '$$$'")
    assert not p2._compiler_was_not_found(0, "", "")


def test_qsf_gen_skips_for_generic_class_without_board_top(tmp_path):
    top = "core_top"
    rtl = f"module {top}(input clk); endmodule\n"
    proj = _make_project_with_l9(tmp_path, rtl, top)
    sr = p2.step_qsf_gen(proj, top, "processor_cpu")
    assert sr.status == "SKIP"
    assert "board-pin" in sr.detail or "board" in sr.detail.lower()


def test_usb_hid_tester_skips_for_generic_class(tmp_path):
    top = "core_top"
    rtl = f"module {top}(input clk); endmodule\n"
    proj = _make_project_with_l9(tmp_path, rtl, top)
    sr = p2.step_usb_hid_tester_verify(proj, ic_class="processor_cpu")
    assert sr.status == "SKIP"
    assert "Phase 3" in sr.detail


def test_board_harness_top_reenables_qsf(tmp_path):
    top = "core_top"
    rtl = f"module {top}(input clk); endmodule\n"
    proj = _make_project_with_l9(tmp_path, rtl, top)
    # Supply a board-harness top → board verification applicable again.
    rtl_dir = proj / "phase2" / "stage1" / "rtl"
    (rtl_dir / "de10lite_top.sv").write_text(
        "module de10lite_top(input MAX10_CLK1_50); endmodule\n")
    assert p2._has_board_harness_top(proj) is True


# ---------------------------------------------------------------------
# Fix 3 — flow_compliance class-aware gate skip-set
# ---------------------------------------------------------------------
def _make_class_project(tmp_path: Path, ic_class_markers: dict) -> Path:
    """Build a project whose L docs make detect_ic_class return a
    generic_full_stack class (digital_arithmetic_primitive)."""
    proj = tmp_path
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L1_OVERVIEW.json").write_text(json.dumps({"name": "mul8"}))
    (gd / "L2_FRS.json").write_text(json.dumps(
        {"protocol_overview": {"half_duplex": False}}))
    # No L3 opcodes, no L5 analog → digital_arithmetic_primitive.
    rtl_dir = proj / "phase2" / "stage1" / "rtl"
    rtl_dir.mkdir(parents=True, exist_ok=True)
    (rtl_dir / "mul8.v").write_text(
        "module mul8(input clk, input [7:0] a, input [7:0] b, "
        "output reg [15:0] p); always @(posedge clk) p <= a*b; endmodule\n")
    return proj


def test_class_skipped_gates_for_arithmetic_primitive(tmp_path):
    proj = _make_class_project(tmp_path, {})
    cls = icp.detect_ic_class(proj)["ic_class"]
    assert cls == "digital_arithmetic_primitive"
    skipped = fcc._class_skipped_gates(proj)
    # The protocol + analog gates the class table OWNS are skipped with N/A
    # reasons.
    for g in ("l3_opcode_argument_constraints_check",
              "l12_behavioral_sequences_steps_typed_check",
              "protocol_ip_simulation_required_check",
              "analog_block_coverage_check",
              "analog_hardmacro_check",
              "mixed_signal_cosim_check",
              "analog_content_detected_must_emit_l5_check",
              "analog_hw_spice_correlation_check"):
        assert g in skipped, g
        assert "N/A for class" in skipped[g]
    # Core functional/structural gates are NOT skipped.
    for g in ("crc_completeness_check", "fsm_error_invariant",
              "bitwidth_consistency_check"):
        assert g not in skipped, g
    # #1978 took four PROTOCOL-INDEPENDENT questions out of this table on the
    # rule that a caller may not suppress them wholesale by name. That is a
    # statement about the MECHANISM; the property those entries protected —
    # no false FAIL on a class the question does not apply to — is still owed,
    # and each of these gates now answers for itself. Asserted here so the
    # removal cannot quietly become a re-opened escape (it did once: see the
    # block comment above `_phase3_complete_no_spice`).
    for g in ("l1_electrical_specs_typed_depth_check",
              "assertion_covers_l3_constraints_check",
              "bit_level_full_stack_tb_oracle_check"):
        assert g not in skipped, (
            f"{g} is a protocol-independent question; the class table must "
            f"not silence it by name (#1978)")
        r = subprocess.run(
            [sys.executable, str(PROGRAMS / f"{g}.py"), str(proj)],
            capture_output=True, text=True)
        assert r.returncode == 2, (
            f"{g} must classify its OWN non-verdict on a class it cannot "
            f"apply to; rc={r.returncode} is a verdict over nothing\n"
            + r.stdout + r.stderr)


def test_class_skipped_gates_fail_closed_for_unknown(tmp_path):
    """A project with no L docs → unknown class → empty skip set, so
    every gate runs (no weakening of existing FAIL logic)."""
    proj = tmp_path
    (proj / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    assert fcc._class_skipped_gates(proj) == {}


def test_structural_gates_skip_protocol_for_generic_class(tmp_path):
    """Integration: _run_structural_rtl_gates records the class-skips as
    SKIP entries, not FAILs, for a generic_full_stack class."""
    proj = _make_class_project(tmp_path, {})
    all_passed, fails, skips, waivers = fcc._run_structural_rtl_gates(proj)
    skip_blob = " ".join(skips)
    assert "l3_opcode_argument_constraints_check" in skip_blob
    assert "analog_content_detected_must_emit_l5_check" in skip_blob
    # None of the class-skipped gates appear in fails.
    fail_blob = " ".join(fails)
    assert "l3_opcode_argument_constraints_check" not in fail_blob
    assert "analog_block_coverage_check" not in fail_blob


# ---------------------------------------------------------------------
# v1.6.553 — post-layout SPICE correlation is an analog-track gate.
# Digital-only protocol ICs (analog_applicable=False) that complete
# Phase 3 emit phase3/stage3/extracted/*.spef + phase3/stage3/sta/*.rpt,
# which previously tripped spice_correlation_check's NO_SPICE_VERIFICATION
# FAIL even though such ICs have no transistor-level SPICE deck and never
# should. Under --skip-analog this surfaced as a spurious phase2 FAIL on
# espi / usb_pd / sgmii while interlaken (no Phase-3 SPEF/STA) "passed".
# HONESTY: a genuinely-analog class still RUNS the gate (so a missing /
# uncorrelated SPICE deck on a real analog IC still FAILs).
#
# WHERE THE EXEMPTION LIVES, AND WHY THESE TESTS MOVED (#1978 -> here).
# It used to be a NAME in `flow_compliance_check._CLASS_SKIPPABLE_ANALOG_GATES`:
# the umbrella silenced this gate by spelling it. #1978 removed that entry on
# the rule that a caller's class table may not suppress a protocol-independent
# question wholesale, and pinned the removal in
# `test_issue1978_reason_taxonomy.py::
# test_real_flow_keeps_protocol_independent_questions_out_of_class_skips`.
# Nothing took over the QUESTION, so the v1.6.553 escape re-opened. MEASURED at
# 2010063c1, pinned image 0.3.6, on a registry-matched
# `digital_arithmetic_primitive` project carrying phase3 SPEF + STA and no
# SPICE deck: `spice_correlation_check` rc 1 NO_SPICE_VERIFICATION.
#
# So the tests below no longer assert MEMBERSHIP of a table. They drive the
# gate and assert the OUTCOME, which is the property v1.6.553 exists for and
# the only form that survives the mechanism moving again. The table assertion
# was also the weaker test in a second way: it went red for
# `l1_electrical_specs_typed_depth_check` too, where there is no escape at all
# (that gate self-skips rc 2 "no electrical entries to validate" on the same
# project) -- one red per table entry, not one per defect.
# ---------------------------------------------------------------------
def _phase3_complete_no_spice(tmp_path, analog: bool):
    """A project that REACHED post-layout (SPEF + STA) and ran no SPICE.

    This is the shape v1.6.553 named: before Step 20/21 the gate self-skips
    for a different reason (`no_spef` / `no_sta`) and the question never
    arises, so a fixture without them proves nothing.
    """
    proj = _make_class_project(tmp_path, {})
    if analog:
        (proj / "phase1" / "generated_docs" / "L5_ADI_SPEC.json").write_text(
            json.dumps({"analog_blocks": [{"name": "ldo", "type": "ldo"}],
                        "supplies": [{"name": "VDD"}]}))
    ext = proj / "phase3" / "stage3" / "extracted"
    ext.mkdir(parents=True, exist_ok=True)
    (ext / "top.spef").write_text('*SPEF "IEEE 1481-1998"\n')
    sta = proj / "phase3" / "stage3" / "sta"
    sta.mkdir(parents=True, exist_ok=True)
    (sta / "sta.rpt").write_text("slack 0.5\n")
    return proj


def _run_spice_gate(proj):
    import subprocess
    return subprocess.run(
        [sys.executable, str(PROGRAMS / "spice_correlation_check.py"),
         str(proj), "--no-spice"], capture_output=True, text=True)


def test_spice_correlation_is_not_a_FAIL_for_a_pure_digital_class(tmp_path):
    """The v1.6.553 property, asked of the gate instead of of a table."""
    proj = _phase3_complete_no_spice(tmp_path, analog=False)
    assert icp.detect_ic_class(proj)["ic_class"] == "digital_arithmetic_primitive"
    r = _run_spice_gate(proj)
    assert r.returncode == 2, (
        "a pure-digital IC that completed Phase 3 has no transistor-level deck "
        "to correlate; a missing deck is a design-declared N/A, not a FAIL\n"
        + r.stdout + r.stderr)
    assert "analog_not_applicable_for_class" in r.stdout, r.stdout
    assert "VACUOUS" in r.stdout, (
        "the N/A must land on the DISCLOSED tier — an rc 2 nobody can see is "
        "the silent pass this gate exists to prevent\n" + r.stdout)


def test_spice_correlation_still_FAILs_an_analog_class(tmp_path):
    """REVERSE, one property changed: the class IS analog-applicable.

    Without this the exemption above could be unconditional and the file
    would still be green."""
    proj = _phase3_complete_no_spice(tmp_path, analog=True)
    flags = icp.class_verification_flags(icp.detect_ic_class(proj)["ic_class"])
    assert flags.get("analog_applicable") is not False
    r = _run_spice_gate(proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "NO_SPICE_VERIFICATION" in r.stdout, r.stdout


def test_the_class_table_does_not_silence_the_spice_gate_by_name(tmp_path):
    """The other half of the same rule, stated rather than left implicit.

    `test_issue1978_reason_taxonomy` owns this from its side; asserted here
    too so that re-adding the name -- the shape this file used to demand --
    cannot be done while this file is green."""
    assert "spice_correlation_check" not in fcc._CLASS_SKIPPABLE_ANALOG_GATES
    assert ("analog_hw_spice_correlation_check"
            in fcc._CLASS_SKIPPABLE_ANALOG_GATES)


def test_spice_gate_skipped_for_each_digital_class():
    """Every registry-matched class with analog_applicable=False marks
    the SPICE-correlation gate N/A (covers digital_cmd_driven /
    serial_peripheral_protocol / digital_arithmetic_primitive — the
    espi / lpc / sgmii classes — plus processor_cpu / bare_fpga /
    bus_interconnect_protocol)."""
    import json as _json
    reg = _json.loads((PROGRAMS / "ic_class_registry.json").read_text())
    digital = [c["name"] for c in reg["classes"]
               if c.get("analog_applicable") is False]
    assert "digital_cmd_driven" in digital            # espi / usb_pd / interlaken
    assert "serial_peripheral_protocol" in digital     # lpc
    assert "digital_arithmetic_primitive" in digital   # sgmii
    for cls in digital:
        flags = icp.class_verification_flags(cls)
        assert flags["registry_matched"] is True, cls
        assert flags["analog_applicable"] is False, cls


def test_spice_gate_NOT_skipped_for_analog_class(tmp_path):
    """HONESTY: an analog-applicable class (pure_analog / mixed_signal_otp)
    does NOT skip the SPICE-correlation gate, so a real analog IC that
    completed Phase 3 without a SPICE deck still FAILs the gate."""
    for analog_cls in ("pure_analog", "mixed_signal_otp"):
        flags = icp.class_verification_flags(analog_cls)
        assert flags["registry_matched"] is True, analog_cls
        # analog_applicable is True (or not-False) → _class_skipped_gates
        # never adds the analog gate set for this class.
        assert flags.get("analog_applicable") is not False, analog_cls


def test_spice_gate_skip_is_class_driven_not_skip_analog_flag(tmp_path):
    """The skip is keyed on the detected IC class, NOT on a --skip-analog
    flag or a benchmark name — so it is general (fires for any digital-only
    class) and honest (never special-cased to espi/usb_pd).

    Asked of the gate, for the reason in the block comment above: the class
    key now lives in `spice_correlation_check._analog_not_applicable_for_class`,
    and a test of the caller's table would go green again the moment the
    exemption moved without the escape ever being closed."""
    proj = _phase3_complete_no_spice(tmp_path, analog=False)
    r = _run_spice_gate(proj)
    assert r.returncode == 2 and "analog_not_applicable_for_class" in r.stdout, \
        r.stdout + r.stderr
    assert "digital_arithmetic_primitive" in r.stdout, (
        "the disclosure must name the class it keyed on; a reason that does "
        "not say which record exempted the design cannot be audited\n"
        + r.stdout)
    # Unknown class (no L docs) → fail-closed → the gate still asks.
    empty = tmp_path / "empty_proj"
    (empty / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    ext = empty / "phase3" / "stage3" / "extracted"
    ext.mkdir(parents=True)
    (ext / "top.spef").write_text('*SPEF "IEEE 1481-1998"\n')
    sta = empty / "phase3" / "stage3" / "sta"
    sta.mkdir(parents=True)
    (sta / "sta.rpt").write_text("slack 0.5\n")
    _unknown = icp.class_verification_flags(
        icp.detect_ic_class(empty).get("ic_class") or "unknown")
    # FAIL-CLOSED, stated as the flag the gate actually keys on. `unknown`
    # answers `registry_matched: True` (measured), so a test written against
    # that flag would pass while proving nothing; the exemption is keyed on
    # `analog_applicable is False` and an unclassified design never says that.
    assert _unknown.get("analog_applicable") is not False
    assert _run_spice_gate(empty).returncode == 1, (
        "an unmatched class must NOT be exempted — fail-closed is the whole "
        "reason the key is the registry flag and not a name")


# ---------------------------------------------------------------------
# Fix 4 — negated analog keyword does not count
# ---------------------------------------------------------------------
def _hit(cid: str, line: str) -> bool:
    pat = acd._KEYWORD_CLASSES[cid][0]
    for m in pat.finditer(line):
        if not acd._keyword_is_negated(line, m.start(), m.end()):
            return True
    return False


@pytest.mark.parametrize("line,cid", [
    ("This design does not need an LDO", "ldo"),
    ("no bandgap reference is used here", "bandgap"),
    ("without analog oscillator", "oscillator"),
    ("does not require an on-chip LDO", "ldo"),
    ("❌ LDO removed in this revision", "ldo"),
    ("~~bandgap~~ deleted in v2", "bandgap"),
])
def test_negated_keyword_not_counted(line, cid):
    assert _hit(cid, line) is False


@pytest.mark.parametrize("line,cid", [
    ("Internal LDO regulator provides 1.8V", "ldo"),
    ("4 MHz oscillator with FREQ_TRIM +/- 6%", "oscillator"),
    ("bandgap voltage reference VBG = 1.2V", "bandgap"),
])
def test_positive_keyword_still_counted(line, cid):
    assert _hit(cid, line) is True


def test_mixed_line_negation_is_per_hit():
    """'no LDO but does have a real bandgap' → LDO suppressed, bandgap
    still counts (per-hit, not per-line)."""
    line = "The chip has no LDO but does have a real bandgap reference"
    assert _hit("ldo", line) is False
    assert _hit("bandgap", line) is True


def test_negated_analog_gate_skips_full_run(tmp_path):
    """End-to-end: docs that ONLY negate analog content → gate SKIPs.

    The SUBJECT of this test — negation suppresses the keyword hit, so no
    analog class is claimed — is unchanged. What changed in #833 is the rc
    that "no analog class was claimed" leaves behind: it used to be 0, which
    the P0 structural umbrella credited as an executed PASS for a gate that
    had compared no doc evidence against any L5 record. It is now
    `_vx.RC_VACUOUS`, so this file no longer pins the vacuous credit.
    """
    proj = tmp_path
    docs = proj / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "ds.txt").write_text(
        "This is a fully digital core.\n"
        "It does not need an LDO.\n"
        "There is no bandgap reference.\n"
        "Designed without analog oscillator blocks.\n")
    gate = PROGRAMS / "analog_content_detected_must_emit_l5_check.py"
    r = subprocess.run([sys.executable, str(gate), str(proj)],
                       capture_output=True, text=True)
    assert r.returncode == _vx.RC_VACUOUS, r.stdout + r.stderr
    assert "SKIP" in r.stdout


def test_positive_analog_gate_still_fails_without_l5(tmp_path):
    """HONESTY: a genuine positive analog mention with no L5 entry still
    FAILs."""
    proj = tmp_path
    docs = proj / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "ds.txt").write_text(
        "Internal LDO regulator provides 1.8V to the core.\n"
        "4 MHz oscillator with FREQ_TRIM.\n")
    gate = PROGRAMS / "analog_content_detected_must_emit_l5_check.py"
    r = subprocess.run([sys.executable, str(gate), str(proj)],
                       capture_output=True, text=True)
    assert r.returncode == 1
    assert "FAIL" in r.stdout


# ---------------------------------------------------------------------
# Fix 5 — bit-serial-family suppression in NBA gate
# ---------------------------------------------------------------------
_BAD_RTL = (
    "module ser(input clk, output reg dout);\n"
    "  reg [7:0] tx_sr;\n"
    "  always @(posedge clk) begin\n"
    "    dout <= tx_sr[1];\n"
    "    tx_sr <= tx_sr >> 1;\n"
    "  end\n"
    "endmodule\n"
)


def _run_nba(proj: Path):
    r = subprocess.run([sys.executable, str(NBA_GATE), str(proj)],
                       capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def _nba_proj(tmp_path: Path) -> Path:
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "ser.v").write_text(_BAD_RTL)
    return tmp_path


def test_multi_bit_nba_race_still_fails(tmp_path):
    """HONESTY: a multi-bit same-cycle NBA race on a non-bit-serial
    design still FAILs."""
    proj = _nba_proj(tmp_path)
    code, out = _run_nba(proj)
    assert code == 1
    assert "FAIL" in out


def test_bit_serial_marker_downgrades_to_warn(tmp_path):
    proj = _nba_proj(tmp_path)
    (proj / "facts.yaml").write_text(
        "ip_class: bit_serial_core\ndatapath_width: 1\n")
    code, out = _run_nba(proj)
    assert code == 0
    assert "WARN" in out
    assert "bit-serial" in out.lower() or "bit_serial" in out.lower()


def test_bit_serial_width1_marker_downgrades(tmp_path):
    """W==1 datapath in an L doc downgrades to WARN."""
    proj = _nba_proj(tmp_path)
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L1_OVERVIEW.json").write_text(json.dumps({"data_width": 1}))
    code, out = _run_nba(proj)
    assert code == 0
    assert "WARN" in out


def test_bit_serial_evidence_waiver_downgrades(tmp_path):
    proj = _nba_proj(tmp_path)
    (proj / "waivers.json").write_text(json.dumps({
        "bit_serial_core_lookahead_intentional":
            "This is a bit-serial multiplier; the look-ahead shift read "
            "is intended per the serial datapath topology."}))
    code, out = _run_nba(proj)
    assert code == 0
    assert "WARN" in out


def test_bit_serial_evidence_helper_fail_closed(tmp_path):
    """No marker / no waiver → not bit-serial (fail-closed)."""
    import nba_shift_register_same_cycle_read_check as nba
    proj = _nba_proj(tmp_path)
    is_bs, ev = nba._bit_serial_evidence(proj)
    assert is_bs is False
    assert ev == ""
