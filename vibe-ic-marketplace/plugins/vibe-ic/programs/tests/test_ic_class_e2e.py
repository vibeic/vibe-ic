"""tests/test_ic_class_e2e.py — Wave 36 (v0.119.68).

End-to-end fixture tests for three hypothetical IC classes:
  * ic_uart_transceiver  — pure digital UART, 4 commands, no OTP
  * ic_pmic_pure_analog  — pure analog PMIC, no L3 commands
  * ic_mixed_signal_otp  — analog + digital + OTP, 5 commands

Each fixture exercises:
  - phase1_all_l_docs_present_check       (M1)
  - extraction_evidence_schema_check       (M2 — silent-skip path)
  - phase1_coverage_report_present_check  (M2 — silent-skip path)
  - l_doc_structured_field_count_check     (M5 — class-aware skip)

Acceptance: none of the gates may FAIL on a well-formed fixture.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_PROGRAMS = (
    Path(__file__).resolve().parent.parent.parent
)


def _write(project: Path, rel: str, body: dict) -> None:
    # Translate legacy top-level rel paths to new layout
    legacy_map = {"phase1/generated_docs/": "phase1/generated_docs/",
                  "phase1/input_doc/": "phase1/input_doc/"}
    for k, v in legacy_map.items():
        if rel.startswith(k):
            rel = v + rel[len(k):]
            break
    p = project / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(body, indent=2))


def _evidence_for(filename: str) -> dict:
    """Minimal valid extraction_evidence schema."""
    return {
        "extraction_evidence": {
            "vendor_doc.pdf": [
                {"literal": f"sentinel-for-{filename}",
                 "label": filename}
            ],
        }
    }


def _run(prog: str, project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PLUGIN_PROGRAMS / prog), str(project)],
        capture_output=True, text=True,
    )


# ---------------------------------------------------------------------
# Fixture A — ic_uart_transceiver
# ---------------------------------------------------------------------
def _build_uart_transceiver(project: Path) -> None:
    """Pure UART chip — 4 commands, no analog, no OTP, no calibration."""
    project.mkdir(parents=True, exist_ok=True)
    _write(project, "phase1/generated_docs/L1_DATASHEET.json", {
        **_evidence_for("L1"),
        "ic_name": "UART-T",
        "package": "SOIC-8",
        "vendor": "ExampleCorp",
        "description": "8-pin UART command transceiver",
        "supply_voltage_v": 3.3,
        "current_typ_ma": 5,
        "current_max_ma": 12,
        "operating_temp_c": "-40 to 85",
        "interface": "UART",
        "baud_rate": 115200,
        "package_dimensions_mm": {"l": 4.9, "w": 3.9, "h": 1.5},
    })
    _write(project, "phase1/generated_docs/L2_FRS.json", {
        **_evidence_for("L2"),
        "ic_name": "UART-T",
        "protocol_type": "UART",
        "baud_rate": 115200,
        "data_bits": 8,
        "parity": "none",
        "stop_bits": 1,
        "flow_control": "none",
        "supply_voltage_min_v": 3.0,
        "supply_voltage_max_v": 3.6,
        "operating_temp_min_c": -40,
        "operating_temp_max_c": 85,
        "current_active_ma": 5,
        "current_idle_ma": 0.5,
        "rx_buffer_bytes": 64,
        "tx_buffer_bytes": 64,
        "command_count": 4,
        "ack_timeout_ms": 10,
    })
    _write(project, "phase1/generated_docs/L3_CMD_PROTOCOL.json", {
        **_evidence_for("L3"),
        "ic_name": "UART-T",
        "command_count": 4,
        "commands": [
            {"opcode": "0x01", "name": "READ", "payload_bytes": 0},
            {"opcode": "0x02", "name": "WRITE", "payload_bytes": 4},
            {"opcode": "0x03", "name": "STATUS", "payload_bytes": 0},
            {"opcode": "0x04", "name": "RESET", "payload_bytes": 0},
        ],
        "crc_parameters": {
            "polynomial_hex": "0x07",
            "init_hex": "0x00",
            "bit_order": "msb_first",
        },
    })
    _write(project, "phase1/generated_docs/L4_REGMAP.json", {
        **_evidence_for("L4"),
        "ic_name": "UART-T",
        "registers": [
            {"addr": 0, "name": "CTRL", "width": 8},
            {"addr": 1, "name": "STATUS", "width": 8},
            {"addr": 2, "name": "BAUD_HI", "width": 8},
            {"addr": 3, "name": "BAUD_LO", "width": 8},
            {"addr": 4, "name": "DATA", "width": 8},
        ],
    })
    _write(project, "phase1/generated_docs/L6_CONTROL_LOGIC.json", {
        **_evidence_for("L6"),
        "ic_name": "UART-T",
        "fsm_states": [
            {"name": "IDLE"},
            {"name": "RX_START"},
            {"name": "RX_DATA"},
            {"name": "TX_DATA"},
            {"name": "DONE"},
        ],
    })
    _write(project, "phase1/generated_docs/L7_TEST_DEBUG.json", {
        **_evidence_for("L7"),
        "ic_name": "UART-T",
        "test_scenarios": [
            {"name": "READ_TEST"}, {"name": "WRITE_TEST"},
            {"name": "ERR_TEST"},
        ],
    })
    _write(project, "phase1/generated_docs/L8_TIMING_WAVEFORM.json", {
        **_evidence_for("L8"),
        "ic_name": "UART-T",
        "timing_parameters": {
            "tBitNs": 8680,
            "tFrameUs": 87,
            "tStartNs": 8680,
            "tStopNs": 8680,
            "tParityNs": 0,
            "tIdleNs": 100,
            "tSetupNs": 5,
            "tHoldNs": 5,
            "tProcUs": 50,
            "tAckMs": 10,
        },
    })
    _write(project, "phase1/generated_docs/L9_INTEGRATION_SPEC.json", {
        **_evidence_for("L9"),
        "ic_name": "UART-T",
        "top_module": "uart_top",
        "fsm_states": [{"name": "IDLE"}],
        "ports": [
            {"name": "clk", "dir": "input"},
            {"name": "rx", "dir": "input"},
            {"name": "tx", "dir": "output"},
        ],
    })
    _write(project, "phase1/generated_docs/L10_TEST_CASES.json", {
        **_evidence_for("L10"),
        "ic_name": "UART-T",
        "test_cases": [{"id": f"TC{i}", "scenario": f"s{i}"}
                       for i in range(5)],
    })


# ---------------------------------------------------------------------
# Fixture B — ic_pmic_pure_analog
# ---------------------------------------------------------------------
def _build_pmic_pure_analog(project: Path) -> None:
    """Pure-analog PMIC — only L1 / L2 / L5 / L8 / L13 mandatory."""
    project.mkdir(parents=True, exist_ok=True)
    _write(project, "phase1/generated_docs/L1_DATASHEET.json", {
        **_evidence_for("L1"),
        "ic_name": "PMIC-3V3",
        "package": "DFN-6",
        "vendor": "ExampleCorp",
        "description": "3.3V LDO 500mA",
        "vout_v": 3.3,
        "iout_max_ma": 500,
        "vdropout_mv_max": 350,
        "iquiescent_ua": 60,
        "operating_temp_c": "-40 to 125",
        "package_dimensions_mm": {"l": 2, "w": 2, "h": 0.75},
        "psrr_db_typ": 65,
        "noise_uvrms": 50,
    })
    _write(project, "phase1/generated_docs/L2_FRS.json", {
        **_evidence_for("L2"),
        "ic_name": "PMIC-3V3",
        "interface": "pure analog",
        "vin_min_v": 3.6,
        "vin_max_v": 6.0,
        "vout_typ_v": 3.3,
        "vout_tol_pct": 1.5,
        "iload_max_ma": 500,
        "isc_typ_ma": 700,
        "current_limit_threshold_ma": 650,
        "thermal_shutdown_c": 160,
        "thermal_recovery_c": 140,
        "fold_back_pct": 30,
        "psrr_db_at_1khz": 65,
        "psrr_db_at_100khz": 40,
        "noise_uvrms_10hz_100khz": 50,
        "load_regulation_pct": 0.2,
        "line_regulation_pct": 0.1,
    })
    _write(project, "phase1/generated_docs/L5_ADI_SPEC.json", {
        **_evidence_for("L5"),
        "ic_name": "PMIC-3V3",
        "analog_blocks": [
            {"name": "BANDGAP_REF", "vref_v": 1.225},
            {"name": "ERROR_AMP"},
            {"name": "PASS_FET", "rds_on_mohm": 60},
            {"name": "CURRENT_LIMIT"},
            {"name": "THERMAL_SHUTDOWN"},
        ],
    })
    _write(project, "phase1/generated_docs/L8_TIMING_WAVEFORM.json", {
        **_evidence_for("L8"),
        "ic_name": "PMIC-3V3",
        "timing_parameters": {
            "tStartUs": 200,
            "tShutdownUs": 50,
            "tThermalRecoveryMs": 1,
            "tLoadStepUs": 5,
            "tLineStepUs": 10,
            "tPsrrSettlingUs": 100,
            "tSCResponseUs": 1,
            "tCurrentLimitUs": 1,
            "tInrushUs": 50,
            "tDischargeMs": 5,
        },
    })
    _write(project, "phase1/generated_docs/L13_LAB_CALIBRATION.json", {
        **_evidence_for("L13"),
        "ic_name": "PMIC-3V3",
        "lab_traces_present": True,
        "calibration_steps": [
            {"step": "VOUT_TRIM"}, {"step": "ILIM_TRIM"},
            {"step": "PSRR_MEAS"}, {"step": "NOISE_MEAS"},
            {"step": "TSDN_VERIFY"},
        ],
    })


# ---------------------------------------------------------------------
# Fixture C — ic_mixed_signal_otp
# ---------------------------------------------------------------------
def _build_mixed_signal_otp(project: Path) -> None:
    """Mixed-signal sensor with OTP — analog + digital + 5 cmds."""
    project.mkdir(parents=True, exist_ok=True)
    _write(project, "phase1/generated_docs/L1_DATASHEET.json", {
        **_evidence_for("L1"),
        "ic_name": "TEMP-SENS",
        "package": "DFN-8",
        "vendor": "ExampleCorp",
        "description": "I2C temp sensor with OTP trim",
        "interface": "I2C",
        "supply_voltage_v": 3.3,
        "current_active_ua": 200,
        "current_sleep_ua": 1,
        "operating_temp_c": "-40 to 125",
        "accuracy_c": 0.5,
        "resolution_bits": 16,
        "package_dimensions_mm": {"l": 3, "w": 3, "h": 0.9},
    })
    _write(project, "phase1/generated_docs/L2_FRS.json", {
        **_evidence_for("L2"),
        "ic_name": "TEMP-SENS",
        "protocol_type": "I2C",
        "i2c_addr_7bit": "0x48",
        "i2c_max_clock_khz": 400,
        "vdd_min_v": 2.7,
        "vdd_max_v": 3.6,
        "iactive_typ_ua": 200,
        "isleep_typ_ua": 1,
        "tconvert_ms": 50,
        "tsdo_min_ns": 10,
        "tsdo_max_ns": 200,
        "command_count": 5,
        "trim_otp_bits": 64,
        "lock_otp_bits": 8,
        "psrr_db": 50,
        "noise_uvrms": 30,
    })
    _write(project, "phase1/generated_docs/L3_CMD_PROTOCOL.json", {
        **_evidence_for("L3"),
        "ic_name": "TEMP-SENS",
        "command_count": 5,
        "commands": [
            {"opcode": "0x00", "name": "READ_TEMP"},
            {"opcode": "0x01", "name": "READ_CONFIG"},
            {"opcode": "0x02", "name": "WRITE_CONFIG"},
            {"opcode": "0x03", "name": "TRIGGER_OTP_PROG"},
            {"opcode": "0x04", "name": "READ_ID"},
        ],
        "crc_parameters": {
            "polynomial_hex": "0x07", "init_hex": "0x00",
            "bit_order": "msb_first",
        },
    })
    _write(project, "phase1/generated_docs/L4_REGMAP.json", {
        **_evidence_for("L4"),
        "ic_name": "TEMP-SENS",
        "registers": [
            {"addr": 0, "name": "TEMP_HI", "width": 8},
            {"addr": 1, "name": "TEMP_LO", "width": 8},
            {"addr": 2, "name": "CONFIG", "width": 8},
            {"addr": 3, "name": "STATUS", "width": 8},
            {"addr": 4, "name": "ID", "width": 8},
        ],
        "otp_layout": {
            "trim_registers": ["TRIM_GAIN", "TRIM_OFFSET",
                               "TRIM_BANDGAP"],
            "lockbits": [0, 1, 2, 3],
            "read_map": {"start": 0, "end": 7},
            "write_map": {"start": 0, "end": 5},
            "otp_ip_specs": {"vendor": "X", "size_bytes": 16},
            "mask_sources": ["MASK_LOCK", "MASK_TRIM"],
        },
    })
    _write(project, "phase1/generated_docs/L5_ADI_SPEC.json", {
        **_evidence_for("L5"),
        "ic_name": "TEMP-SENS",
        "analog_blocks": [
            {"name": "ADC_16BIT"},
            {"name": "BANDGAP"},
            {"name": "TEMP_DIODE"},
            {"name": "VOLTAGE_REFERENCE"},
        ],
    })
    _write(project, "phase1/generated_docs/L6_CONTROL_LOGIC.json", {
        **_evidence_for("L6"),
        "ic_name": "TEMP-SENS",
        "fsm_states": [
            {"name": "IDLE"}, {"name": "I2C_ADDR"},
            {"name": "I2C_DATA"}, {"name": "ADC_CONVERT"},
            {"name": "OTP_PROG"}, {"name": "DONE"},
        ],
    })
    _write(project, "phase1/generated_docs/L7_TEST_DEBUG.json", {
        **_evidence_for("L7"),
        "ic_name": "TEMP-SENS",
        "test_scenarios": [
            {"name": "TEMP_READ"}, {"name": "OTP_READBACK"},
            {"name": "I2C_ADDR_CHK"},
        ],
    })
    _write(project, "phase1/generated_docs/L8_TIMING_WAVEFORM.json", {
        **_evidence_for("L8"),
        "ic_name": "TEMP-SENS",
        "timing_parameters": {
            "tConvertMs": 50,
            "tSCLPeriodNs": 2500,
            "tSDOnMaxNs": 200,
            "tHoldNs": 50,
            "tSetupNs": 50,
            "tBufNs": 1300,
            "tHdStaNs": 600,
            "tSuStaNs": 600,
            "tHdDatNs": 0,
            "tSuDatNs": 100,
            "tOtpProgUs": 100,
        },
    })
    _write(project, "phase1/generated_docs/L9_INTEGRATION_SPEC.json", {
        **_evidence_for("L9"),
        "ic_name": "TEMP-SENS",
        "top_module": "temp_sens_top",
        "fsm_states": [{"name": "IDLE"}],
        "ports": [
            {"name": "scl", "dir": "input"},
            {"name": "sda", "dir": "inout"},
            {"name": "alert", "dir": "output"},
        ],
    })
    _write(project, "phase1/generated_docs/L10_TEST_CASES.json", {
        **_evidence_for("L10"),
        "ic_name": "TEMP-SENS",
        "test_cases": [{"id": f"TC{i}"} for i in range(5)],
    })
    _write(project, "phase1/generated_docs/L11_CALIBRATION.json", {
        **_evidence_for("L11"),
        "ic_name": "TEMP-SENS",
        "calibration_tables": [
            {"name": "TRIM_GAIN", "step": "0.1%"},
            {"name": "TRIM_OFFSET", "step": "0.05C"},
            {"name": "TRIM_BANDGAP", "step": "1mV"},
        ],
    })
    _write(project, "phase1/generated_docs/L12_BEHAVIORAL.json", {
        **_evidence_for("L12"),
        "ic_name": "TEMP-SENS",
        "calibration_steps": [
            {"step": "I2C_PROBE"},
            {"step": "OTP_TRIM"},
        ],
    })
    _write(project, "phase1/generated_docs/L13_LAB_CALIBRATION.json", {
        **_evidence_for("L13"),
        "ic_name": "TEMP-SENS",
        "lab_traces_present": True,
        "calibration_steps": [{"s": i} for i in range(5)],
    })


# ---------------------------------------------------------------------
# Test entry points
# ---------------------------------------------------------------------
GATES_TO_RUN = [
    "phase1_all_l_docs_present_check.py",
    "extraction_evidence_schema_check.py",
    "phase1_coverage_report_present_check.py",
    "l_doc_structured_field_count_check.py",
]


def _generate_coverage_report(project: Path) -> None:
    """Run phase1_coverage_report_gen so the present-check has a
    report to verify. Stub a tiny input/docs/ so the gen script has
    a vendor-doc denominator (otherwise it no-ops with empty patterns)."""
    in_docs = project / "input" / "docs"
    in_docs.mkdir(parents=True, exist_ok=True)
    # Write a stub vendor doc that contains every extraction_evidence
    # literal we emitted in the L docs (so coverage is 100%).
    stub_lines: list[str] = []
    gd = project / "phase1" / "generated_docs"
    if gd.is_dir():
        for f in sorted(gd.glob("*.json")):
            try:
                j = json.loads(f.read_text())
            except Exception:
                continue
            ev = j.get("extraction_evidence")
            if isinstance(ev, dict):
                for entries in ev.values():
                    if isinstance(entries, list):
                        for e in entries:
                            if isinstance(e, dict):
                                lit = e.get("literal")
                                if isinstance(lit, str):
                                    stub_lines.append(lit)
                            elif isinstance(e, str):
                                stub_lines.append(e)
    (in_docs / "vendor_doc.txt").write_text("\n".join(stub_lines) + "\n")
    subprocess.run(
        [sys.executable,
         str(PLUGIN_PROGRAMS / "phase1_coverage_report_gen.py"),
         str(project)],
        capture_output=True, text=True,
    )


def _check_gates(project: Path) -> list[str]:
    _generate_coverage_report(project)
    fails: list[str] = []
    for prog in GATES_TO_RUN:
        r = _run(prog, project)
        # FAIL exit code is 1.  We tolerate 0 (PASS / SKIP) and 2
        # (input error — reported per-gate where applicable). A
        # well-formed fixture should never hit FAIL.
        if r.returncode == 1:
            fails.append(
                f"{prog}: rc=1\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
            )
    return fails


def test_uart_transceiver_passes_all_gates(tmp_path: Path) -> None:
    project = tmp_path / "ic_uart_transceiver"
    _build_uart_transceiver(project)
    fails = _check_gates(project)
    assert not fails, "\n\n".join(fails)


def test_pmic_pure_analog_passes_all_gates(tmp_path: Path) -> None:
    project = tmp_path / "ic_pmic_pure_analog"
    _build_pmic_pure_analog(project)
    fails = _check_gates(project)
    assert not fails, "\n\n".join(fails)


def test_mixed_signal_otp_passes_all_gates(tmp_path: Path) -> None:
    project = tmp_path / "ic_mixed_signal_otp"
    _build_mixed_signal_otp(project)
    fails = _check_gates(project)
    assert not fails, "\n\n".join(fails)
