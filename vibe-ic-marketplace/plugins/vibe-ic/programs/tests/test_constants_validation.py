"""Unit tests for constants_validation.py.

Tests verify correct detection of missing fields, duplicate names, empty
constants, section structure warnings, missing comments, and nested
constants structures.
"""
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'constants_validation.py'
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import constants_validation as cv  # noqa: E402


# ---------------------------------------------------------------------------
# Test 1: Valid constants → PASS
# ---------------------------------------------------------------------------
def test_valid_constants_pass(tmp_path):
    data = [
        {"name": "CLK_DIV", "value": 10, "width": 8, "comment": "Clock divider"},
        {"name": "RESET_VAL", "value": 0, "width": 1, "comment": "Reset value"},
    ]
    (tmp_path / "rtl_constants.json").write_text(json.dumps(data))

    result = cv.audit(str(tmp_path))
    assert result.passed is True
    assert result.summary["constants_total"] == 2
    assert result.summary["errors"] == 0


# ---------------------------------------------------------------------------
# Test 2: Missing name → FAIL
# ---------------------------------------------------------------------------
def test_missing_name_fail(tmp_path):
    data = [
        {"value": 10, "width": 8, "comment": "No name field"},
    ]
    (tmp_path / "rtl_constants.json").write_text(json.dumps(data))

    result = cv.audit(str(tmp_path))
    assert result.passed is False
    errors = [f for f in result.findings if f.severity == "ERROR"]
    assert any(f.rule == "MISSING_FIELD" and "name" in f.message for f in errors)


# ---------------------------------------------------------------------------
# Test 3: Missing value → FAIL
# ---------------------------------------------------------------------------
def test_missing_value_fail(tmp_path):
    data = [
        {"name": "MY_CONST", "width": 4, "comment": "No value field"},
    ]
    (tmp_path / "rtl_constants.json").write_text(json.dumps(data))

    result = cv.audit(str(tmp_path))
    assert result.passed is False
    errors = [f for f in result.findings if f.severity == "ERROR"]
    assert any(f.rule == "MISSING_FIELD" and "value" in f.message for f in errors)


# ---------------------------------------------------------------------------
# Test 4: Missing width/bits → FAIL
# ---------------------------------------------------------------------------
def test_missing_width_fail(tmp_path):
    data = [
        {"name": "MY_CONST", "value": 42, "comment": "No width or bits"},
    ]
    (tmp_path / "rtl_constants.json").write_text(json.dumps(data))

    result = cv.audit(str(tmp_path))
    assert result.passed is False
    errors = [f for f in result.findings if f.severity == "ERROR"]
    assert any(f.rule == "MISSING_FIELD" and "width" in f.message for f in errors)


# ---------------------------------------------------------------------------
# Test 5: Duplicate names → FAIL
# ---------------------------------------------------------------------------
def test_duplicate_names_fail(tmp_path):
    data = [
        {"name": "SAME_NAME", "value": 1, "width": 8, "comment": "First"},
        {"name": "SAME_NAME", "value": 2, "width": 8, "comment": "Duplicate"},
    ]
    (tmp_path / "rtl_constants.json").write_text(json.dumps(data))

    result = cv.audit(str(tmp_path))
    assert result.passed is False
    assert result.summary["duplicates"] >= 1
    errors = [f for f in result.findings if f.rule == "DUPLICATE_NAME"]
    assert len(errors) >= 1


# ---------------------------------------------------------------------------
# Test 6: Empty directory (no JSON files) → FAIL
# ---------------------------------------------------------------------------
def test_empty_dir_fail(tmp_path):
    result = cv.audit(str(tmp_path))
    assert result.passed is False
    errors = [f for f in result.findings if f.severity == "ERROR"]
    assert any(f.rule == "NO_CONSTANTS_FILE" for f in errors)


# ---------------------------------------------------------------------------
# Test 7: Dict JSON without recognized section keys → WARNING but PASS
# ---------------------------------------------------------------------------
def test_section_structure_warning(tmp_path):
    data = {
        "my_custom_section": [
            {"name": "A", "value": 1, "width": 4, "comment": "ok"},
        ]
    }
    (tmp_path / "rtl_constants.json").write_text(json.dumps(data))

    result = cv.audit(str(tmp_path))
    assert result.passed is True
    warnings = [f for f in result.findings if f.severity == "WARNING"]
    assert any(f.rule == "SECTION_STRUCTURE" for f in warnings)


# ---------------------------------------------------------------------------
# Test 8: Constant without comment → WARNING but PASS
# ---------------------------------------------------------------------------
def test_missing_comment_warning(tmp_path):
    data = [
        {"name": "NO_COMMENT", "value": 99, "width": 8},
    ]
    (tmp_path / "rtl_constants.json").write_text(json.dumps(data))

    result = cv.audit(str(tmp_path))
    assert result.passed is True
    warnings = [f for f in result.findings if f.severity == "WARNING"]
    assert any(f.rule == "MISSING_COMMENT" for f in warnings)


# ---------------------------------------------------------------------------
# Test 9: Nested constants key → PASS
# ---------------------------------------------------------------------------
def test_nested_constants_pass(tmp_path):
    data = {
        "constants": [
            {"name": "BAUD_DIV", "value": 26, "width": 16, "comment": "Baud rate"},
            {"name": "PARITY_EN", "value": 1, "width": 1, "comment": "Parity"},
        ]
    }
    (tmp_path / "rtl_constants.json").write_text(json.dumps(data))

    result = cv.audit(str(tmp_path))
    assert result.passed is True
    assert result.summary["constants_total"] == 2
    assert result.summary["errors"] == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
