"""tests/test_fault_injection.py — Wave 42 (v0.119.70 / SF8).

Five fault-injection scenarios from the third-round audit
(`a38d56dfe53d7bd11`).  Each test crafts a fixture that mis-claims
something in facts.yaml or in the L docs and verifies the matching
gate actually CATCHES the attack instead of silently SKIPping.

These tests do NOT live in `test_ic_class_e2e.py` because a passing
fault-injection test fails the implicit attack — i.e. the fault is
caught.  Keeping them in their own module makes the audit story
explicit when scanning the test suite.

Acceptance: every test in this module must PASS — otherwise the
attacker would have escaped.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent


def _write_json(p: Path, body: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(body, indent=2))


def _write_text(p: Path, body: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


def _evidence(name: str) -> dict:
    return {
        "extraction_evidence": {
            "vendor.pdf": [{"literal": f"sentinel-{name}", "label": name}],
        }
    }


def _run(prog: str, project: Path, *extra: str
         ) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROGRAMS / prog), str(project), *extra],
        capture_output=True, text=True,
    )


# ---------------------------------------------------------------------
# Common EXAMPLE_PROTOCOL-class L doc set — used by attacks 1, 3.
# ---------------------------------------------------------------------
def _build_aid_class_skeleton(project: Path) -> None:
    """Realistic EXAMPLE_PROTOCOL-class fixture: inout id_bus RTL + L1/L3/L6 etc."""
    project.mkdir(parents=True, exist_ok=True)
    _write_json(project / "phase1/generated_docs/L1_DATASHEET.json", {
        **_evidence("L1"),
        "ic_name": "EXAMPLE_PROTOCOL-X",
        "package": "SOT-23",
        "vendor": "ExampleCorp",
        "description": "Single-wire half-duplex EXAMPLE_PROTOCOL transceiver",
        "supply_voltage_v": 3.3,
        "current_typ_ma": 1,
        "current_max_ma": 5,
        "operating_temp_c": "-40 to 105",
        "interface": "EXAMPLE_PROTOCOL single-wire",
    })
    _write_json(project / "phase1/generated_docs/L3_CMD_PROTOCOL.json", {
        **_evidence("L3"),
        "ic_name": "EXAMPLE_PROTOCOL-X",
        "command_count": 3,
        "commands": [
            {"opcode": "0x10", "name": "WAKE", "payload_bytes": 0,
             "pre_wake_allowed": True},
            {"opcode": "0x20", "name": "READ_ID", "payload_bytes": 0,
             "pre_wake_allowed": False},
            {"opcode": "0x30", "name": "READ_REG", "payload_bytes": 1,
             "pre_wake_allowed": False,
             "payload_semantics": [{"byte_offset": 0, "name": "addr"}]},
        ],
        "physical_layer": "single_wire_half_duplex open_drain",
    })
    _write_json(project / "phase1/generated_docs/L6_CONTROL_LOGIC.json", {
        **_evidence("L6"),
        "ic_name": "EXAMPLE_PROTOCOL-X",
        "fsm_states": [
            {"name": "PRE_WAKE"}, {"name": "WAKE_LATCH"},
            {"name": "RX_CMD"}, {"name": "TX_RESP"}, {"name": "DONE"},
        ],
        "wake_gating": True,
    })
    _write_json(project / "phase1/generated_docs/L8_TIMING_WAVEFORM.json", {
        **_evidence("L8"),
        "ic_name": "EXAMPLE_PROTOCOL-X",
        "timing_parameters": {
            "br_min_us": 5, "br_max_us": 15,
            "ibt_min_us": 1, "ibt_max_us": 10,
        },
        "rx_classifier_ticks": {"br_min": 5, "br_max": 15,
                                  "ibt_min": 1, "ibt_max": 10},
    })
    _write_json(project / "phase1/generated_docs/L9_INTEGRATION_SPEC.json", {
        **_evidence("L9"),
        "ic_name": "EXAMPLE_PROTOCOL-X",
        "top_module": "aid_top",
        "ports": [
            {"name": "clk", "dir": "input"},
            {"name": "id_bus", "dir": "inout"},
        ],
    })
    rtl_body = """
module aid_top (
    input  wire clk,
    input  wire rst_n,
    inout  wire id_bus
);
    reg [7:0] cmd_buf [0:7];
    reg [3:0] bit_idx;
    reg       byte_valid;
    reg       reject_9bit;
    reg [3:0] state;
    localparam S_CMD_IDLE = 4'd0;
    localparam S_CMD_DECODE = 4'd1;
    always @(posedge clk) begin
        case (state)
            S_CMD_IDLE: state <= S_CMD_DECODE;
            default:    state <= S_CMD_IDLE;
        endcase
    end
endmodule
""".strip()
    _write_text(project / "phase2/stage1/rtl/aid_top.v", rtl_body)


# ---------------------------------------------------------------------
# Attack 1 — fake `unknown` class by removing L2 protocol_type.
# ---------------------------------------------------------------------
def test_attack_unknown_class_fall_through_fails(tmp_path: Path) -> None:
    """MF1 — Wave 37 three gates must FAIL (not SKIP) on unknown
    class when RTL/L docs carry full evidence.

    Attack: scrub every protocol-class anchor (L2.protocol_type +
    L3.physical_layer + RTL inout id_bus) so detect_ic_class lands
    on `unknown`, but keep L3 opcodes + L6 wake_gating + L8 br/ibt
    anchors. Pre-Wave-42 the three gates would auto-SKIP on
    `unknown`; post-Wave-42 they must run their inspection logic.
    """
    project = tmp_path / "ic_attack1"
    _build_aid_class_skeleton(project)
    # Scrub L2 protocol_type / interface.
    _write_json(project / "phase1/generated_docs/L2_FRS.json", {
        **_evidence("L2"), "ic_name": "EXAMPLE_PROTOCOL-X",
        "supply_voltage_min_v": 3.0, "supply_voltage_max_v": 3.6,
    })
    # Scrub L3.physical_layer + L1.interface (anything that could
    # name the EXAMPLE_PROTOCOL class indirectly).
    l1 = json.loads(
        (project / "phase1/generated_docs/L1_DATASHEET.json").read_text())
    l1.pop("interface", None)
    l1.pop("description", None)
    (project / "phase1/generated_docs/L1_DATASHEET.json").write_text(
        json.dumps(l1, indent=2))
    l3 = json.loads(
        (project / "phase1/generated_docs/L3_CMD_PROTOCOL.json").read_text())
    l3.pop("physical_layer", None)
    for cmd in l3["commands"]:
        cmd.pop("pre_wake_allowed", None)
    (project / "phase1/generated_docs/L3_CMD_PROTOCOL.json").write_text(
        json.dumps(l3, indent=2))
    # Replace RTL with a stub that has NO inout id_bus so the
    # detection truly lands on `unknown` (instead of `aid_class`).
    rtl_path = project / "phase2/stage1/rtl/aid_top.v"
    rtl_path.write_text("""
module aid_top (input wire clk, input wire rst_n);
    // Cmd-buf evidence is still present below — does not affect
    // protocol_class detection.
    reg [7:0] cmd_buf [0:7];
    reg [7:0] opcode;
    always @(posedge clk) begin
        case (opcode) 8'h10: cmd_buf[0] <= 1; default: ; endcase
    end
endmodule
""".strip())
    sys.path.insert(0, str(PROGRAMS))
    try:
        from ic_class_profile import detect_ic_class  # type: ignore
    finally:
        sys.path.pop(0)
    profile = detect_ic_class(project)
    detected = profile["ic_class"]
    # Detection here can land on either `unknown` (if all anchors
    # gone) or `digital_cmd_driven` (since L3 commands persist).
    # Both must run the gate's full inspection logic.  The bug we
    # are guarding against is: the pre-Wave-42 gate would have
    # silently SKIPped `unknown`.  In any case the gate must NOT
    # print the auto-SKIP and MUST fall through to the FAIL path.
    assert detected != "pure_analog" and detected != "bare_fpga", (
        f"fault setup landed on auto-skipped class: {profile}")
    proc = _run("l3_opcode_pre_wake_allowed_typed_check.py", project)
    out = proc.stdout + proc.stderr
    assert "SKIP — ic_class=unknown not in applicable set" not in out, (
        f"MF1 broken: unknown class auto-SKIPped\n{out}")
    # The L3 commands lack pre_wake_allowed and L6 has wake_gating
    # → gate must FAIL.
    assert proc.returncode == 1, (
        f"unknown/digital fall-through should FAIL: "
        f"exit={proc.returncode}\n{out}")
    assert "missing typed field" in out, (
        f"FAIL message wrong: {out}")


# ---------------------------------------------------------------------
# Attack 2 — fake `pure_analog` on a cmd-driven IC.
# ---------------------------------------------------------------------
def test_attack_pure_analog_with_cmd_rtl_downgrades_to_unknown(
        tmp_path: Path) -> None:
    """SF5 — a project that LOOKS pure_analog (only L1/L5/L8/L13) but
    whose RTL has cmd-driven constructs must be downgraded to
    `unknown` so cmd-related gates fail-closed."""
    project = tmp_path / "ic_attack2"
    project.mkdir(parents=True, exist_ok=True)
    # Pure-analog L docs only — would normally classify pure_analog.
    _write_json(project / "phase1/generated_docs/L1_DATASHEET.json", {
        **_evidence("L1"),
        "ic_name": "FAKE-PMIC",
        "description": "Looks like an LDO but has cmd_buf in RTL",
        "vout_v": 3.3,
    })
    _write_json(project / "phase1/generated_docs/L2_FRS.json", {
        **_evidence("L2"),
        "interface": "pure analog",
    })
    _write_json(project / "phase1/generated_docs/L5_ADI_SPEC.json", {
        **_evidence("L5"),
        "analog_blocks": [{"name": "BANDGAP_REF"}],
    })
    # The injected RTL gives away the lie.
    _write_text(project / "phase2/stage1/rtl/sneaky.v", """
module sneaky (input clk, input [7:0] opcode);
    reg [7:0] cmd_buf [0:7];
    always @(posedge clk) begin
        case (opcode)
            8'h10: cmd_buf[0] <= 8'h01;
            default: cmd_buf[0] <= 8'h00;
        endcase
    end
endmodule
""".strip())
    sys.path.insert(0, str(PROGRAMS))
    try:
        from ic_class_profile import detect_ic_class  # type: ignore
    finally:
        sys.path.pop(0)
    profile = detect_ic_class(project)
    assert profile["ic_class"] == "unknown", (
        f"SF5 attack escaped: profile={profile}")
    assert "class_downgrade_reason" in profile, (
        f"SF5 should record downgrade reason: {profile}")
    assert "pure_analog" in profile["class_downgrade_reason"]


# ---------------------------------------------------------------------
# Attack 3 — fake LIN protocol on EXAMPLE_PROTOCOL-class IC.
# ---------------------------------------------------------------------
def test_attack_lin_protocol_with_aid_inout_fails(tmp_path: Path) -> None:
    """SF4 — slave_tx / rx_byte_valid gates must FAIL on
    L2.protocol_type='lin' when RTL exposes inout id_bus."""
    project = tmp_path / "ic_attack3"
    _build_aid_class_skeleton(project)
    # Add the lying L2 — claim LIN.
    _write_json(project / "phase1/generated_docs/L2_FRS.json", {
        **_evidence("L2"),
        "ic_name": "EXAMPLE_PROTOCOL-X",
        "protocol_type": "lin",
    })
    # Slave TX gate.  We can't directly invoke without an inspect
    # wrapper; use the runner via importlib.
    sys.path.insert(0, str(PROGRAMS))
    try:
        from slave_tx_no_device_break_check import (  # type: ignore
            inspect as slave_tx_inspect,
        )
        from rx_byte_valid_requires_ibt_gate_check import (  # type: ignore
            run_audit as rx_audit,
        )
    finally:
        sys.path.pop(0)
    # slave_tx
    failures, _, summary = slave_tx_inspect(project)
    assert any("inconsistency" in f.lower() for f in failures), (
        f"SF4 (slave_tx) escape: failures={failures} summary={summary}")
    # rx_byte_valid
    result = rx_audit(project)
    verdict = getattr(result, "verdict", None)
    assert verdict == "FAIL", (
        f"SF4 (rx_byte_valid) escape: verdict={verdict}")
    inconsistency = any(
        "inconsistency" in (f.message or "").lower()
        for f in getattr(result, "findings", [])
    )
    assert inconsistency, (
        f"SF4 (rx_byte_valid) wrong message: "
        f"{[f.message for f in result.findings]}")


# ---------------------------------------------------------------------
# Attack 4 — facts.yaml comment-line escape must be ignored.
# ---------------------------------------------------------------------
def test_attack_facts_yaml_comment_escape_ignored(tmp_path: Path) -> None:
    """MF3 — substring grep is gone. A `# no_fsm: true` comment must
    not silence the fsm requirement."""
    project = tmp_path / "ic_attack4"
    project.mkdir(parents=True, exist_ok=True)
    _write_text(project / "facts.yaml",
                "# no_fsm: true   (this is a comment, not a flag)\n"
                "ic_name: dummy\n")
    sys.path.insert(0, str(PROGRAMS))
    try:
        # _facts_yaml_escape_flags is the hardened entrypoint.
        from l_doc_structured_field_count_check import (  # type: ignore
            _facts_yaml_escape_flags,
        )
    finally:
        sys.path.pop(0)
    flags = _facts_yaml_escape_flags(project)
    assert flags == {
        "no_command_protocol": False,
        "no_fsm": False,
        "no_timing_classification": False,
    }, f"MF3 escape leaked: {flags}"
    # Also test nested mapping — must NOT leak.
    _write_text(project / "facts.yaml",
                "metadata:\n  no_fsm: true\nic_name: dummy\n")
    flags2 = _facts_yaml_escape_flags(project)
    assert flags2["no_fsm"] is False, (
        f"MF3 nested-key escape leaked: {flags2}")


# ---------------------------------------------------------------------
# Attack 5 — Path A marker + vendor docs in input/docs/ → FAIL.
# ---------------------------------------------------------------------
def test_attack_path_a_marker_with_vendor_docs_fails(
        tmp_path: Path) -> None:
    """MF2 — if facts.yaml marks `phase1_skipped_path_a: true` but
    input/docs/ holds vendor PDFs, the gate must FAIL."""
    project = tmp_path / "ic_attack5"
    project.mkdir(parents=True, exist_ok=True)
    _write_text(project / "facts.yaml",
                "phase1_skipped_path_a: true\nic_name: dummy\n")
    # Plant a fake vendor PDF.
    (project / "input/docs").mkdir(parents=True)
    (project / "input/docs/vendor_datasheet.pdf").write_text("fake pdf")

    proc = _run("extraction_evidence_schema_check.py", project)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1, (
        f"MF2 (extraction) escape: exit={proc.returncode} out={out}")
    assert "Wave 42 / MF2" in out, (
        f"MF2 (extraction) wrong message: {out}")

    proc2 = _run("phase1_coverage_report_present_check.py", project)
    out2 = proc2.stdout + proc2.stderr
    assert proc2.returncode == 1, (
        f"MF2 (coverage) escape: exit={proc2.returncode} out={out2}")
    assert "Wave 42 / MF2" in out2, (
        f"MF2 (coverage) wrong message: {out2}")
