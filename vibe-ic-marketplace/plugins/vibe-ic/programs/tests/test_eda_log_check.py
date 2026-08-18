"""Unit tests for eda_log_check.py.

Tests verify correct detection of valid logs, missing logs, error patterns,
missing expected patterns, empty logs, and multiple patterns.
"""
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'eda_log_check.py'
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import eda_log_check as elc  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture: sample EDA log content
# ---------------------------------------------------------------------------
GOOD_LOG = """\
=== Yosys Synthesis Report ===
Reading design...
Mapping cells to technology library...
Number of cells: 1234
Chip area: 0.045 mm2
Total wire length: 12345 um
=== Synthesis Complete ===
"""

ERROR_LOG = """\
=== Yosys Synthesis Report ===
Reading design...
Error: Cannot find module 'missing_module'
FATAL: Synthesis aborted
"""

NO_MATCH_LOG = """\
=== Some other tool ===
Processing data...
Step 1 complete.
Step 2 complete.
Done.
"""


# ---------------------------------------------------------------------------
# Test 1: Valid log with expected pattern found
# ---------------------------------------------------------------------------
def test_valid_log_with_expected(tmp_path):
    f = tmp_path / "synth.log"
    f.write_text(GOOD_LOG)

    findings, info = elc.audit_log(
        f,
        expect_patterns=["Number of cells", "Chip area"],
        reject_patterns=["Error", "FATAL"],
    )
    assert len(findings) == 0
    assert len(info["expect_matched"]) >= 1
    assert len(info["reject_matched"]) == 0


# ---------------------------------------------------------------------------
# Test 2: Missing log file
# ---------------------------------------------------------------------------
def test_missing_log(tmp_path):
    missing = tmp_path / "nonexistent.log"

    findings, info = elc.audit_log(
        missing,
        expect_patterns=["Number of cells"],
        reject_patterns=[],
    )
    assert len(findings) == 1
    assert findings[0].category == "LOG_MISSING"


# ---------------------------------------------------------------------------
# Test 3: Log with error pattern (reject pattern found)
# ---------------------------------------------------------------------------
def test_log_with_error_pattern(tmp_path):
    f = tmp_path / "synth.log"
    f.write_text(ERROR_LOG)

    findings, info = elc.audit_log(
        f,
        expect_patterns=[],
        reject_patterns=["Error", "FATAL"],
    )
    # Should find at least one REJECTED_FOUND
    rejected = [f for f in findings if f.category == "REJECTED_FOUND"]
    assert len(rejected) >= 1
    assert len(info["reject_matched"]) >= 1


# ---------------------------------------------------------------------------
# Test 4: No expected pattern found
# ---------------------------------------------------------------------------
def test_no_expected_pattern_found(tmp_path):
    f = tmp_path / "other.log"
    f.write_text(NO_MATCH_LOG)

    findings, info = elc.audit_log(
        f,
        expect_patterns=["Number of cells", "Chip area"],
        reject_patterns=[],
    )
    assert len(findings) == 1
    assert findings[0].category == "EXPECTED_NOT_FOUND"
    assert len(info["expect_matched"]) == 0


# ---------------------------------------------------------------------------
# Test 5: Empty log file
# ---------------------------------------------------------------------------
def test_empty_log(tmp_path):
    f = tmp_path / "empty.log"
    f.write_text("")

    findings, info = elc.audit_log(
        f,
        expect_patterns=["Number of cells"],
        reject_patterns=[],
    )
    assert len(findings) == 1
    assert findings[0].category == "EMPTY_LOG"


# ---------------------------------------------------------------------------
# Test 6: Multiple patterns — some match, some don't (but at least one matches)
# ---------------------------------------------------------------------------
def test_multiple_patterns(tmp_path):
    f = tmp_path / "synth.log"
    f.write_text(GOOD_LOG)

    findings, info = elc.audit_log(
        f,
        expect_patterns=["Number of cells", "NONEXISTENT_PATTERN"],
        reject_patterns=["FATAL", "CRITICAL"],
    )
    # At least one expect matched, so no EXPECTED_NOT_FOUND
    assert all(f.category != "EXPECTED_NOT_FOUND" for f in findings)
    assert "Number of cells" in info["expect_matched"]
    # No reject pattern matched in good log
    assert len(info["reject_matched"]) == 0
    assert len(findings) == 0


# ---------------------------------------------------------------------------
# Test: CLI exit codes
# ---------------------------------------------------------------------------
def test_cli_exit_code_pass(tmp_path):
    f = tmp_path / "synth.log"
    f.write_text(GOOD_LOG)

    rc = elc.main([
        '--log-file', str(f),
        '--expect-pattern', 'Number of cells|Chip area',
        '--reject-pattern', 'Error|FATAL',
    ])
    assert rc == 0


def test_cli_exit_code_fail(tmp_path):
    rc = elc.main([
        '--log-file', str(tmp_path / 'missing.log'),
        '--expect-pattern', 'Number of cells',
    ])
    assert rc == 1
