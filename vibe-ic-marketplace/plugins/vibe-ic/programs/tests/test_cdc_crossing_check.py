"""Unit tests for cdc_crossing_check.py.

Tests verify correct detection of CDC reports and crossing analysis content.
"""
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'cdc_crossing_check.py'
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import cdc_crossing_check as ccc  # noqa: E402


# ---------------------------------------------------------------------------
# PASS: CDC report with clock domain and crossing keywords
# ---------------------------------------------------------------------------
def test_cdc_report_pass(tmp_path):
    rpt = tmp_path / "cdc.rpt"
    rpt.write_text(
        "Clock domain: clk_sys -> clk_peri\n"
        "Crossing detected at signal data_sync\n"
        "Synchronizer: 2-FF found\n"
    )

    result = ccc.audit_cdc(tmp_path)
    assert result.passed is True
    assert result.summary["has_clock_ref"] is True
    assert result.summary["has_crossing"] is True
    assert result.summary["files_found"] == 1


# ---------------------------------------------------------------------------
# FAIL: No CDC report files
# ---------------------------------------------------------------------------
def test_no_report_fail(tmp_path):
    (tmp_path / "readme.txt").write_text("not a cdc file")

    result = ccc.audit_cdc(tmp_path)
    assert result.passed is False
    assert result.summary["files_found"] == 0


# ---------------------------------------------------------------------------
# FAIL: CDC file with clock ref but no crossing keywords
# ---------------------------------------------------------------------------
def test_no_crossing_fail(tmp_path):
    rpt = tmp_path / "cdc.rpt"
    rpt.write_text("Clock domain analysis:\nclk_sys frequency = 100 MHz\n")

    result = ccc.audit_cdc(tmp_path)
    assert result.passed is False
    assert result.summary["has_clock_ref"] is True
    assert result.summary["has_crossing"] is False


# ---------------------------------------------------------------------------
# FAIL: Empty directory (non-existent path)
# ---------------------------------------------------------------------------
def test_empty_dir_fail(tmp_path):
    nonexistent = tmp_path / "does_not_exist"

    result = ccc.audit_cdc(nonexistent)
    assert result.passed is False
    assert result.summary["files_found"] == 0


# ---------------------------------------------------------------------------
# CLI exit codes
# ---------------------------------------------------------------------------
def test_cli_pass(tmp_path):
    rpt = tmp_path / "cdc.rpt"
    rpt.write_text("clock domain crossing: synchronizer at sig_a\n")
    rc = ccc.main([str(tmp_path)])
    assert rc == 0


def test_cli_fail(tmp_path):
    rc = ccc.main([str(tmp_path)])
    assert rc == 1
