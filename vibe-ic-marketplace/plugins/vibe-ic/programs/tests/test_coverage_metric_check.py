"""Unit tests for coverage_metric_check.py.

Tests verify correct detection of coverage reports and percentage metrics.
"""
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'coverage_metric_check.py'
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import coverage_metric_check as cmc  # noqa: E402


# ---------------------------------------------------------------------------
# PASS: Coverage report with percentage
# ---------------------------------------------------------------------------
def test_coverage_report_pass(tmp_path):
    rpt = tmp_path / "coverage.rpt"
    rpt.write_text("Line coverage: 85.3%\nBranch coverage: 72.1%\n")

    result = cmc.audit_coverage(tmp_path)
    assert result.passed is True
    assert result.summary["files_found"] == 1
    assert result.summary["metric_count"] == 2
    vals = [m["value"] for m in result.summary["metrics"]]
    assert 85.3 in vals
    assert 72.1 in vals


# ---------------------------------------------------------------------------
# FAIL: No coverage report files
# ---------------------------------------------------------------------------
def test_no_report_fail(tmp_path):
    (tmp_path / "readme.txt").write_text("not a coverage file")

    result = cmc.audit_coverage(tmp_path)
    assert result.passed is False
    assert result.summary["files_found"] == 0


# ---------------------------------------------------------------------------
# FAIL: Coverage file without any percentage
# ---------------------------------------------------------------------------
def test_no_percentage_fail(tmp_path):
    rpt = tmp_path / "coverage.rpt"
    rpt.write_text("Coverage analysis complete.\nNo metrics available.\n")

    result = cmc.audit_coverage(tmp_path)
    assert result.passed is False
    assert result.summary["files_found"] == 1
    assert result.summary["metrics"] == []


# ---------------------------------------------------------------------------
# FAIL: Empty directory (non-existent path)
# ---------------------------------------------------------------------------
def test_empty_dir_fail(tmp_path):
    nonexistent = tmp_path / "does_not_exist"

    result = cmc.audit_coverage(nonexistent)
    assert result.passed is False
    assert result.summary["files_found"] == 0


# ---------------------------------------------------------------------------
# CLI exit codes
# ---------------------------------------------------------------------------
def test_cli_pass(tmp_path):
    rpt = tmp_path / "coverage.rpt"
    rpt.write_text("Line coverage: 90.0%\n")
    rc = cmc.main([str(tmp_path)])
    assert rc == 0


def test_cli_fail(tmp_path):
    rc = cmc.main([str(tmp_path)])
    assert rc == 1
