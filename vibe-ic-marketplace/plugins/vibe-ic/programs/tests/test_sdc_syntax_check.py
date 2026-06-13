"""Unit tests for sdc_syntax_check.py.

Tests verify correct detection of valid SDC files, missing SDC files,
missing create_clock, missing timing constraints, unreasonable clock
periods, and empty directories.
"""
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'sdc_syntax_check.py'
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import sdc_syntax_check as ssc  # noqa: E402


# ---------------------------------------------------------------------------
# Test 1: Valid SDC → PASS
# ---------------------------------------------------------------------------
def test_valid_sdc_pass(tmp_path):
    sdc = """\
# Clock definition
create_clock -period 10 -name sys_clk [get_ports clk]

# Input/output delays
set_input_delay -clock sys_clk -max 2.0 [get_ports data_in]
set_output_delay -clock sys_clk -max 3.0 [get_ports data_out]
"""
    (tmp_path / "timing.sdc").write_text(sdc)

    result = ssc.audit(str(tmp_path))
    assert result.passed is True
    assert result.summary["valid_files"] >= 1
    assert result.summary["errors"] == 0


# ---------------------------------------------------------------------------
# Test 2: No .sdc files → FAIL
# ---------------------------------------------------------------------------
def test_no_sdc_fail(tmp_path):
    (tmp_path / "design.v").write_text("module top(); endmodule")

    result = ssc.audit(str(tmp_path))
    assert result.passed is False
    errors = [f for f in result.findings if f.severity == "ERROR"]
    assert any(f.rule == "NO_SDC_FILE" for f in errors)


# ---------------------------------------------------------------------------
# Test 3: SDC without create_clock → FAIL
# ---------------------------------------------------------------------------
def test_no_create_clock_fail(tmp_path):
    sdc = """\
# Timing constraints only, no clock definition
set_input_delay -clock sys_clk -max 2.0 [get_ports data_in]
set_output_delay -clock sys_clk -max 3.0 [get_ports data_out]
"""
    (tmp_path / "timing.sdc").write_text(sdc)

    result = ssc.audit(str(tmp_path))
    assert result.passed is False
    errors = [f for f in result.findings if f.severity == "ERROR"]
    assert any(f.rule == "NO_CREATE_CLOCK" for f in errors)


# ---------------------------------------------------------------------------
# Test 4: SDC with create_clock but no delay constraints → FAIL
# ---------------------------------------------------------------------------
def test_no_timing_constraint_fail(tmp_path):
    sdc = """\
# Clock only, no timing constraints
create_clock -period 10 -name sys_clk [get_ports clk]
"""
    (tmp_path / "timing.sdc").write_text(sdc)

    result = ssc.audit(str(tmp_path))
    assert result.passed is False
    errors = [f for f in result.findings if f.severity == "ERROR"]
    assert any(f.rule == "NO_TIMING_CONSTRAINT" for f in errors)


# ---------------------------------------------------------------------------
# Test 5: Unreasonable clock period (too small) → FAIL
# ---------------------------------------------------------------------------
def test_unreasonable_period_fail(tmp_path):
    sdc = """\
# Unreasonably small period (0.001 ns = 1 THz)
create_clock -period 0.001 -name fast_clk [get_ports clk]
set_input_delay -clock fast_clk -max 0.0001 [get_ports data_in]
"""
    (tmp_path / "timing.sdc").write_text(sdc)

    result = ssc.audit(str(tmp_path))
    assert result.passed is False
    errors = [f for f in result.findings if f.severity == "ERROR"]
    assert any(f.rule == "BAD_CLOCK_PERIOD" for f in errors)


# ---------------------------------------------------------------------------
# Test 6: Empty directory → FAIL
# ---------------------------------------------------------------------------
def test_empty_dir_fail(tmp_path):
    result = ssc.audit(str(tmp_path))
    assert result.passed is False
    errors = [f for f in result.findings if f.severity == "ERROR"]
    assert any(f.rule == "NO_SDC_FILE" for f in errors)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
