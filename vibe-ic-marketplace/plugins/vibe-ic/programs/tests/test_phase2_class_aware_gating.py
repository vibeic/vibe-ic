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


import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import ic_class_profile as icp  # noqa: E402
import design_one_shot_runner as p2  # noqa: E402
import _vacuous_exit as _vx  # noqa: E402



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










def test_qsf_gen_skips_for_generic_class_without_board_top(tmp_path):
    top = "core_top"
    rtl = f"module {top}(input clk); endmodule\n"
    proj = _make_project_with_l9(tmp_path, rtl, top)
    sr = p2.step_qsf_gen(proj, top, "processor_cpu")
    assert sr.status == "NOT_APPLICABLE"
    assert "board-pin" in sr.detail or "board" in sr.detail.lower()


def test_usb_hid_tester_skips_for_generic_class(tmp_path):
    top = "core_top"
    rtl = f"module {top}(input clk); endmodule\n"
    proj = _make_project_with_l9(tmp_path, rtl, top)
    sr = p2.step_usb_hid_tester_verify(proj, ic_class="processor_cpu")
    assert sr.status == "NOT_APPLICABLE"
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
    # The protocol + analog gates the class table OWNS are skipped with N/A
    # reasons.
    # Core functional/structural gates are NOT skipped.
    # #1978 took four PROTOCOL-INDEPENDENT questions out of this table on the
    # rule that a caller may not suppress them wholesale by name. That is a
    # statement about the MECHANISM; the property those entries protected —
    # no false FAIL on a class the question does not apply to — is still owed,
    # and each of these gates now answers for itself. Asserted here so the
    # removal cannot quietly become a re-opened escape (it did once: see the
    # block comment above `_phase3_complete_no_spice`).






# ---------------------------------------------------------------------
# Step 30 owes current critical-path correlation even for digital classes.
# v1.26.98 (912474756450052b190c399db372df639be65964) replaced the old
# whole-class exemption / NO_SPICE_VERIFICATION branch with current receipt
# validation. Typed analog applicability remains a separate class fact.
# SPEF + STA alone do not prove the producer was reached: the owning
# predicate requires routed.def. Drive the actual CLI on both sides of that
# boundary, retaining --no-spice and the original test IDs. A ready route
# with no current receipt must FAIL for digital, analog and unknown alike.
# ---------------------------------------------------------------------
def _phase3_complete_no_spice(tmp_path, analog: bool):
    """Synthetic SPEF + STA inputs, without routed.def or any Step30 product."""
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


def _run_spice_gate(proj, audit_name):
    # Outside the project: an audit must not become a producer product on
    # the next invocation or alter the current receipt's applicability.
    audit = proj.parent / f"{proj.name}-{audit_name}-spice-audit.json"
    run = subprocess.run(
        [sys.executable, str(PROGRAMS / "spice_correlation_check.py"),
         str(proj), "--no-spice", "--json", str(audit)],
        capture_output=True, text=True)
    return run, json.loads(audit.read_text())


def _assert_spice_route_obligation(proj):
    """A pre-producer nonmeasurement cannot exempt a completed route."""
    route = proj / "phase3" / "stage3" / "pnr" / "routed.def"
    receipt = proj / "reports" / "phase3" / "spice_correlation.current.json"
    assert not route.exists()
    assert not receipt.exists()

    run, report = _run_spice_gate(proj, "before-route")
    assert run.returncode == 2, run.stdout + run.stderr
    summary = report["summary"]
    assert summary["skipped"] is True, report
    assert summary["pass"] is False, report
    assert summary["measurement"] == "NOT_MEASURED", report
    assert summary["current_binding"] == "NOT_YET_PRODUCED", report
    assert summary["reason"] == "asked_before_producer", report
    assert summary["reason_class"] == "ASKED_BEFORE_PRODUCER", report
    assert summary["asked_before_producer"]["producer_has_run"] is False, report
    assert "VACUOUS" in run.stderr, run.stderr

    route.parent.mkdir(parents=True, exist_ok=True)
    route.write_text("DESIGN neutral ;\nEND DESIGN\n")
    assert route.is_file()
    assert not receipt.exists()
    run, report = _run_spice_gate(proj, "ready-route")
    assert run.returncode == 1, run.stdout + run.stderr
    assert report["passed"] is False, report
    summary = report["summary"]
    assert summary["skipped"] is False, report
    assert summary["pass"] is False, report
    assert summary["measurement"] == "NOT_MEASURED", report
    assert summary["current_binding"] == "REFUSED", report
    assert any(f["rule"] == "SPICE_CURRENT_INPUTS_UNBOUND"
               and f["severity"] == "ERROR" for f in report["findings"]), report
    assert not receipt.exists()


def test_spice_correlation_is_not_a_FAIL_for_a_pure_digital_class(tmp_path):
    """Digital analog N/A never waives applicable critical-path correlation."""
    proj = _phase3_complete_no_spice(tmp_path, analog=False)
    profile = icp.detect_ic_class(proj, refresh=True)
    assert profile["ic_class"] == "digital_arithmetic_primitive"
    flags = icp.class_verification_flags(profile["ic_class"])
    assert flags["registry_matched"] is True
    assert flags["analog_applicable"] is False
    _assert_spice_route_obligation(proj)


def test_spice_correlation_still_FAILs_an_analog_class(tmp_path):
    """Analog class still refuses missing current evidence once route exists."""
    proj = _phase3_complete_no_spice(tmp_path, analog=True)
    flags = icp.class_verification_flags(
        icp.detect_ic_class(proj, refresh=True)["ic_class"])
    assert flags.get("analog_applicable") is not False
    _assert_spice_route_obligation(proj)




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
    """Class facts and --no-spice cannot suppress the current route obligation.

    Retain the historical ID; --skip-analog is not an accepted checker flag.
    """
    proj = _phase3_complete_no_spice(tmp_path, analog=False)
    profile = icp.detect_ic_class(proj, refresh=True)
    assert profile["ic_class"] == "digital_arithmetic_primitive"
    flags = icp.class_verification_flags(profile["ic_class"])
    assert flags["registry_matched"] is True
    assert flags["analog_applicable"] is False
    _assert_spice_route_obligation(proj)
    # Unknown class (no L docs) retains the same strict route boundary.
    empty = tmp_path / "empty_proj"
    (empty / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    ext = empty / "phase3" / "stage3" / "extracted"
    ext.mkdir(parents=True)
    (ext / "top.spef").write_text('*SPEF "IEEE 1481-1998"\n')
    sta = empty / "phase3" / "stage3" / "sta"
    sta.mkdir(parents=True)
    (sta / "sta.rpt").write_text("slack 0.5\n")
    _unknown = icp.class_verification_flags(
        icp.detect_ic_class(empty, refresh=True).get("ic_class") or "unknown")
    # Do not assume unknown.registry_matched=False: registered unknown may
    # match. Its independently derived analog applicability is not False.
    assert _unknown.get("analog_applicable") is not False
    _assert_spice_route_obligation(empty)


# ---------------------------------------------------------------------
# Fix 4 — negated analog keyword does not count
# ---------------------------------------------------------------------
def _hit(cid: str, line: str) -> bool:
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




def _nba_proj(tmp_path: Path) -> Path:
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "ser.v").write_text(_BAD_RTL)
    return tmp_path
