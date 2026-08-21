"""tests/test_ic_class_profile.py — Wave 36 (v0.119.68).

Unit tests for the IC class profile helper.  Five fixture classes
exercised:
  * aid_class_half_duplex (EXAMPLE_CHIP / EXAMPLE_TESTER-style)
  * digital_cmd_driven    (UART / SPI command-driven)
  * mixed_signal_otp      (analog + digital + OTP)
  * pure_analog           (PMIC / LDO with no commands)
  * bare_fpga / unknown   (fail-closed fallback)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ic_class_profile import detect_ic_class, required_layers


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def _write_l_docs(project: Path, docs: dict[str, dict]) -> None:
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    for fname, data in docs.items():
        (gd / fname).write_text(json.dumps(data, indent=2))


# ---------------------------------------------------------------------
# Fixture A — aid_class_half_duplex
# ---------------------------------------------------------------------
def test_aid_class_half_duplex_from_protocol_type(tmp_path: Path) -> None:
    project = tmp_path / "ic_aid"
    project.mkdir(parents=True, exist_ok=True)
    _write_l_docs(project, {
        "L1_DATASHEET.json": {"ic_name": "X", "package": "QFN-20"},
        "L2_FRS.json": {"protocol_type": "EXAMPLE_PROTOCOL single_wire_half_duplex"},
        "L3_CMD_PROTOCOL.json": {
            "commands": [{"name": "GET_ID", "opcode": "0x74"},
                         {"name": "GET_STATE", "opcode": "0x72"}],
            "physical_layer": {
                "interface": "Apple ID Bus (single-wire half-duplex)",
            },
        },
        "L11_CALIBRATION.json": {"calibration_targets": [{"name": "A"}]},
        "L13_LAB_CALIBRATION.json": {"lab_traces_present": True},
    })
    profile = detect_ic_class(project)
    assert profile["ic_class"] == "aid_class_half_duplex"
    assert profile["protocol_class"] == "aid_class"
    assert profile["has_command_protocol"] is True
    # All 13 L1-L13 layers stay mandatory. #157: the opt-in completeness
    # layers L24-L27 are conditional-guarded on flags no detector sets, so
    # they resolve to skip (never false-fail) — the L1-L13 floor is unchanged.
    layers = required_layers(profile)
    assert len(layers["mandatory"]) == 13
    assert set(layers["skip"]) == {"L24", "L25", "L26", "L27"}


def test_aid_class_via_inout_id_bus_alone(tmp_path: Path) -> None:
    project = tmp_path / "ic_aid_inout"
    project.mkdir(parents=True, exist_ok=True)
    (project / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (project / "phase2" / "stage1" / "rtl" / "chip_top.v").write_text(
        "module chip_top(input clk, inout id_bus); endmodule\n"
    )
    _write_l_docs(project, {
        "L1_DATASHEET.json": {"ic_name": "X"},
        "L2_FRS.json": {},  # no protocol_type
    })
    profile = detect_ic_class(project)
    assert profile["has_inout_id_bus"] is True
    assert profile["protocol_class"] == "aid_class"
    assert profile["ic_class"] == "aid_class_half_duplex"


# ---------------------------------------------------------------------
# Fixture B — digital_cmd_driven
# ---------------------------------------------------------------------
def test_digital_cmd_driven_uart(tmp_path: Path) -> None:
    project = tmp_path / "ic_uart"
    project.mkdir(parents=True, exist_ok=True)
    _write_l_docs(project, {
        "L1_DATASHEET.json": {"ic_name": "UART-EEPROM",
                              "package": "SOIC-8"},
        "L2_FRS.json": {"protocol_type": "UART", "baud": 115200},
        "L3_CMD_PROTOCOL.json": {
            "commands": [
                {"name": "READ", "opcode": "0x01"},
                {"name": "WRITE", "opcode": "0x02"},
                {"name": "ERASE", "opcode": "0x03"},
                {"name": "STATUS", "opcode": "0x04"},
            ],
        },
        "L6_CONTROL_LOGIC.json": {
            "fsm_states": [{"name": "IDLE"}, {"name": "RX"},
                          {"name": "TX"}, {"name": "DONE"},
                          {"name": "ERR"}],
        },
    })
    profile = detect_ic_class(project)
    assert profile["protocol_class"] == "uart"
    assert profile["ic_class"] == "digital_cmd_driven"
    assert profile["has_analog"] is False
    layers = required_layers(profile)
    # L5 / L11 / L12 / L13 should drop to skip when no analog / no cal.
    assert "L5" in layers["skip"]
    assert "L11" in layers["skip"]
    assert "L12" in layers["skip"]
    assert "L13" in layers["skip"]
    # Core L1/L2/L3/L4/L6/L7/L8/L9/L10 stay mandatory.
    for must in ("L1", "L2", "L3", "L4", "L6", "L7", "L8", "L9", "L10"):
        assert must in layers["mandatory"]


def test_digital_cmd_driven_spi(tmp_path: Path) -> None:
    project = tmp_path / "ic_spi"
    project.mkdir(parents=True, exist_ok=True)
    _write_l_docs(project, {
        "L1_DATASHEET.json": {"ic_name": "SPI-FLASH"},
        "L2_FRS.json": {"protocol_type": "SPI"},
        "L3_CMD_PROTOCOL.json": {
            "commands": [{"name": "READ_ID"}],
        },
    })
    profile = detect_ic_class(project)
    assert profile["protocol_class"] == "spi"
    assert profile["ic_class"] == "digital_cmd_driven"


# ---------------------------------------------------------------------
# Fixture C — mixed_signal_otp
# ---------------------------------------------------------------------
def test_mixed_signal_otp(tmp_path: Path) -> None:
    project = tmp_path / "ic_mixed"
    project.mkdir(parents=True, exist_ok=True)
    _write_l_docs(project, {
        "L1_DATASHEET.json": {"ic_name": "SENSOR-X"},
        "L2_FRS.json": {"protocol_type": "I2C"},
        "L3_CMD_PROTOCOL.json": {
            "commands": [{"name": "READ_TEMP"}, {"name": "TRIM"}],
        },
        "L4_REGMAP.json": {
            "registers": [{"addr": 0, "name": "CTRL"}],
            "otp_layout": {
                "trim_registers": ["TRIM_A", "TRIM_B"],
                "lockbits": [0, 1, 2],
            },
        },
        "L5_ADI_SPEC.json": {
            "analog_blocks": [
                {"name": "ADC"},
                {"name": "BANDGAP"},
                {"name": "TEMP_SENS"},
            ],
        },
        "L11_CALIBRATION.json": {
            "calibration_tables": [{"name": "TRIM_A"}],
        },
    })
    profile = detect_ic_class(project)
    assert profile["has_analog"] is True
    assert profile["has_otp"] is True
    assert profile["has_command_protocol"] is True
    assert profile["ic_class"] == "mixed_signal_otp"
    layers = required_layers(profile)
    # L5 + L11 forced mandatory.
    assert "L5" in layers["mandatory"]
    assert "L11" in layers["mandatory"]


# ---------------------------------------------------------------------
# Fixture D — pure_analog
# ---------------------------------------------------------------------
def test_pure_analog(tmp_path: Path) -> None:
    project = tmp_path / "ic_pmic"
    project.mkdir(parents=True, exist_ok=True)
    _write_l_docs(project, {
        "L1_DATASHEET.json": {"ic_name": "PMIC-LDO",
                              "package": "DFN-6"},
        "L2_FRS.json": {"protocol_type": "none",
                        "interface": "pure analog"},
        "L5_ADI_SPEC.json": {
            "analog_blocks": [
                {"name": "REF"},
                {"name": "ERR_AMP"},
                {"name": "PASS_FET"},
            ],
        },
    })
    profile = detect_ic_class(project)
    assert profile["has_analog"] is True
    assert profile["has_command_protocol"] is False
    assert profile["has_fsm"] is False
    assert profile["ic_class"] == "pure_analog"
    layers = required_layers(profile)
    # L3 / L6 / L7 / L10 dropped to skip.
    for skipped in ("L3", "L6", "L7", "L10"):
        assert skipped in layers["skip"], (
            f"expected {skipped} in skip; got {layers}")


# ---------------------------------------------------------------------
# Fixture E — bare_fpga / unknown
# ---------------------------------------------------------------------
def test_bare_fpga_with_facts_yaml(tmp_path: Path) -> None:
    project = tmp_path / "fpga_skel"
    project.mkdir(parents=True, exist_ok=True)
    (project / "facts.yaml").write_text("ic_name: skel\n")
    profile = detect_ic_class(project)
    # No L docs at all → bare_fpga via facts.yaml fallback.
    assert profile["ic_class"] == "bare_fpga"


def test_unknown_when_no_l_docs_no_facts(tmp_path: Path) -> None:
    project = tmp_path / "empty"
    project.mkdir(parents=True, exist_ok=True)
    profile = detect_ic_class(project)
    assert profile["ic_class"] == "unknown"
    layers = required_layers(profile)
    # Fail-closed: still all 13.
    assert len(layers["mandatory"]) == 13


# ---------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------
def test_lin_protocol_class(tmp_path: Path) -> None:
    project = tmp_path / "ic_lin"
    project.mkdir(parents=True, exist_ok=True)
    _write_l_docs(project, {
        "L1_DATASHEET.json": {"ic_name": "LIN-XCVR"},
        "L2_FRS.json": {"protocol_type": "LIN"},
        "L3_CMD_PROTOCOL.json": {
            "commands": [{"name": "READ_BY_ID"}],
        },
    })
    profile = detect_ic_class(project)
    assert profile["protocol_class"] == "lin"
    # LIN is single-master — classified as digital_cmd_driven.
    assert profile["ic_class"] == "digital_cmd_driven"


def test_kline_protocol_class(tmp_path: Path) -> None:
    project = tmp_path / "ic_kwp"
    project.mkdir(parents=True, exist_ok=True)
    _write_l_docs(project, {
        "L1_DATASHEET.json": {"ic_name": "KWP2000-XCVR"},
        "L2_FRS.json": {"protocol_type": "KWP2000"},
        "L3_CMD_PROTOCOL.json": {
            "commands": [{"name": "FAST_INIT"}],
        },
    })
    profile = detect_ic_class(project)
    # KWP2000 normalises to its own class label (distinct from k_line).
    assert profile["protocol_class"] in ("kwp2000", "k_line")
    assert profile["ic_class"] == "digital_cmd_driven"


def test_required_layers_contract() -> None:
    profile = {
        "ic_class": "aid_class_half_duplex",
        "has_analog": True,
        "has_otp": True,
        "has_calibration": True,
        "has_lab_calibration": True,
        "has_command_protocol": True,
        "has_fsm": True,
    }
    spec = required_layers(profile)
    assert sorted(spec["mandatory"]) == [
        "L1", "L10", "L11", "L12", "L13", "L2", "L3",
        "L4", "L5", "L6", "L7", "L8", "L9",
    ]
    # #157: L24-L27 are opt-in completeness layers guarded on flags absent
    # from this profile → they resolve to skip; the L1-L13 mandatory set is
    # byte-unchanged (still the 13 above).
    assert set(spec["skip"]) == {"L24", "L25", "L26", "L27"}
