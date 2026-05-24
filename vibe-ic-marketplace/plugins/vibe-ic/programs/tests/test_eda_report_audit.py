"""Unit tests for eda_report_audit.py.

Tests verify correct detection of EDA reports across all modes:
DRC, LVS, power, EM, IR-drop, and STA.

Updated 2026-04-22: reports must now include a tool signature AND meet a
minimum size (MIN_REPORT_BYTES per mode) to pass. Hand-typed stubs are
rejected. See `TOOL_SIGNATURES` / `MIN_REPORT_BYTES` in eda_report_audit.py.
"""
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'eda_report_audit.py'
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import eda_report_audit as era  # noqa: E402

# Padding to satisfy MIN_REPORT_BYTES thresholds
_PAD = "# " + ("=" * 78 + "\n") * 40  # ~3.2 KB


# ---------------------------------------------------------------------------
# DRC mode
# ---------------------------------------------------------------------------
def test_drc_report_pass(tmp_path):
    rpt = tmp_path / "run_drc.rpt"
    rpt.write_text(
        "[INFO drt-0012] OpenROAD detailed_route\n"
        "spacing violation at M1\n"
        "via enclosure error at M2\n"
        "3 violations total\n" + _PAD
    )
    result = era._check_drc(tmp_path)
    assert result.passed is True
    assert "spacing" in result.summary["categories_found"]
    assert result.summary["has_count"] is True
    assert result.summary["tool_authentic"] is True


def test_drc_stub_rejected(tmp_path):
    """Anti-fabrication: hand-typed tiny report without tool sig must FAIL."""
    rpt = tmp_path / "drc.rpt"
    rpt.write_text("spacing: 0\nwidth: 0\ntotal: 0 violations\n")  # 40 B
    result = era._check_drc(tmp_path)
    assert result.passed is False
    assert result.summary.get("tool_authentic") is False


def test_drc_no_report_fail(tmp_path):
    result = era._check_drc(tmp_path)
    assert result.passed is False
    assert result.summary["files_found"] == 0


# ---------------------------------------------------------------------------
# LVS mode
# ---------------------------------------------------------------------------
def test_lvs_report_pass(tmp_path):
    rpt = tmp_path / "chip_lvs.rpt"
    rpt.write_text(
        "Netgen LVS comparison\n"
        "NET count: 1234\ndevice count: 567\n"
        "unmatched instance: U1\nnet mismatch: VDD\n"
        "Number of topologically valid matches: 567\n"
        "Circuits match.\n" + _PAD
    )
    result = era._check_lvs(tmp_path)
    assert result.passed is True
    cats = result.summary["categories_found"]
    assert "instance" in cats
    assert "net" in cats
    assert result.summary["tool_authentic"] is True


def test_lvs_stub_rejected(tmp_path):
    rpt = tmp_path / "lvs.rpt"
    rpt.write_text("net: OK\ndevice: OK\n")
    result = era._check_lvs(tmp_path)
    assert result.passed is False


def test_lvs_no_report_fail(tmp_path):
    result = era._check_lvs(tmp_path)
    assert result.passed is False
    assert result.summary["files_found"] == 0


# ---------------------------------------------------------------------------
# Power mode
# ---------------------------------------------------------------------------
def test_power_report_pass(tmp_path):
    rpt = tmp_path / "power_analysis.rpt"
    rpt.write_text(
        "OpenROAD Power Report\n"
        "Group: sequential   Internal Power: 0.12 mW\n"
        "Group: combinational\n"
        "leakage power: 0.05 mW static\n"
        "dynamic power: 3.5 mW switching\n"
        "Total Power: 3.67 mW\n" + _PAD
    )
    result = era._check_power(tmp_path)
    assert result.passed is True
    assert result.summary["has_leakage"] is True
    assert result.summary["has_dynamic"] is True


def test_power_stub_rejected(tmp_path):
    rpt = tmp_path / "power.rpt"
    rpt.write_text("leakage: 1 mW\ndynamic: 3 mW\n")
    result = era._check_power(tmp_path)
    assert result.passed is False


def test_power_missing_dynamic_fail(tmp_path):
    rpt = tmp_path / "power_analysis.rpt"
    rpt.write_text(
        "OpenROAD Power Report\nleakage power: 1.2 uW static\ntotal: 1.2 uW\n" + _PAD
    )
    result = era._check_power(tmp_path)
    assert result.passed is False
    assert result.summary["has_leakage"] is True
    assert result.summary["has_dynamic"] is False


# ---------------------------------------------------------------------------
# EM mode
# ---------------------------------------------------------------------------
def test_em_report_pass(tmp_path):
    rpt = tmp_path / "em_check.rpt"
    rpt.write_text(
        "OpenROAD Electromigration analysis\n"
        "EM lifetime: 10 years\n"
        "Wire M3: Javg 2.5 mA, current density limit 5.0 mA/um\n"
        "Jpeak 8.1 mA/um, RMS current 3.2 mA/um\n" + _PAD
    )
    result = era._check_em(tmp_path)
    assert result.passed is True
    assert result.summary["has_density"] is True


def test_em_stub_rejected(tmp_path):
    rpt = tmp_path / "em.rpt"
    rpt.write_text("Javg=1 OK\n")
    result = era._check_em(tmp_path)
    assert result.passed is False


# ---------------------------------------------------------------------------
# STA mode
# ---------------------------------------------------------------------------
def test_sta_report_pass(tmp_path):
    rpt = tmp_path / "sta_final.rpt"
    rpt.write_text(
        "OpenSTA timing report\n"
        "Startpoint: clk_i\nEndpoint: out_q\n"
        "WNS = -0.05 ns\nTNS = -1.2 ns\n"
        "setup slack: 0.1 ns\nhold slack: 0.02 ns\n"
        "data arrival time: 2.34 ns\n" + _PAD
    )
    result = era._check_sta(tmp_path)
    assert result.passed is True
    assert result.summary["has_wns_tns"] is True
    assert result.summary["has_setup_hold"] is True


def test_sta_stub_rejected(tmp_path):
    rpt = tmp_path / "sta.rpt"
    rpt.write_text("WNS=0 setup: OK hold: OK\n")
    result = era._check_sta(tmp_path)
    assert result.passed is False


def test_sta_missing_setup_hold_fail(tmp_path):
    rpt = tmp_path / "sta_final.rpt"
    rpt.write_text(
        "OpenSTA\nStartpoint: clk\nEndpoint: out\n"
        "WNS = -0.05 ns\nTNS = -1.2 ns\nslack summary\n" + _PAD
    )
    result = era._check_sta(tmp_path)
    assert result.passed is False
    assert result.summary["has_wns_tns"] is True
    assert result.summary["has_setup_hold"] is False


# ---------------------------------------------------------------------------
# IR-drop mode
# ---------------------------------------------------------------------------
def test_ir_drop_pass(tmp_path):
    rpt = tmp_path / "ir_drop.rpt"
    rpt.write_text(
        "OpenROAD PSM IR-drop analysis\n"
        "power grid mesh nodes: 12458\n"
        "max IR drop: 15 mV drop on VDD rail\n"
        "worst voltage drop 0.5% Vdd\nstatic IR: 12 mV\ndynamic IR: 15 mV\n" + _PAD
    )
    result = era._check_ir_drop(tmp_path)
    assert result.passed is True
    assert result.summary["has_drop_value"] is True


def test_ir_drop_stub_rejected(tmp_path):
    rpt = tmp_path / "ir.rpt"
    rpt.write_text("IR: 6 mV OK\n")
    result = era._check_ir_drop(tmp_path)
    assert result.passed is False


# ---------------------------------------------------------------------------
# CLI: --mode is required
# ---------------------------------------------------------------------------
def test_cli_mode_required():
    with pytest.raises(SystemExit) as exc_info:
        era.main(["some_dir"])
    assert exc_info.value.code == 2  # argparse error
