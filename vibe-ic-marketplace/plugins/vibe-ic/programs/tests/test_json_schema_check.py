"""Unit tests for json_schema_check.py.

Tests verify correct detection of missing keys, empty values, null values,
invalid JSON, missing files, nested key dot notation, and extra keys OK.
"""
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'json_schema_check.py'
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import json_schema_check as jsc  # noqa: E402


# ---------------------------------------------------------------------------
# Test 1: All keys present and non-empty
# ---------------------------------------------------------------------------
def test_all_keys_present(tmp_path):
    data = {"part_number": "IC-001", "pins": [{"name": "VDD"}], "electrical_specs": {"vdd": 3.3}}
    f = tmp_path / "L1.json"
    f.write_text(json.dumps(data))

    findings, parsed = jsc.audit_json_keys(f, ["part_number", "pins", "electrical_specs"])
    assert len(findings) == 0
    assert parsed["part_number"] == "IC-001"


# ---------------------------------------------------------------------------
# Test 2: Missing key
# ---------------------------------------------------------------------------
def test_missing_key(tmp_path):
    data = {"part_number": "IC-001"}
    f = tmp_path / "L1.json"
    f.write_text(json.dumps(data))

    findings, _ = jsc.audit_json_keys(f, ["part_number", "pins"])
    assert len(findings) == 1
    assert findings[0].category == "MISSING_KEY"
    assert "pins" in findings[0].message


# ---------------------------------------------------------------------------
# Test 3: Empty string value
# ---------------------------------------------------------------------------
def test_empty_value(tmp_path):
    data = {"part_number": "", "pins": [{"name": "VDD"}]}
    f = tmp_path / "L1.json"
    f.write_text(json.dumps(data))

    findings, _ = jsc.audit_json_keys(f, ["part_number", "pins"])
    assert len(findings) == 1
    assert findings[0].category == "EMPTY_VALUE"
    assert "part_number" in findings[0].key


# ---------------------------------------------------------------------------
# Test 4: Null value
# ---------------------------------------------------------------------------
def test_null_value(tmp_path):
    data = {"part_number": None, "pins": [{"name": "VDD"}]}
    f = tmp_path / "L1.json"
    f.write_text(json.dumps(data))

    findings, _ = jsc.audit_json_keys(f, ["part_number", "pins"])
    assert len(findings) == 1
    assert findings[0].category == "EMPTY_VALUE"


# ---------------------------------------------------------------------------
# Test 5: Not valid JSON
# ---------------------------------------------------------------------------
def test_invalid_json(tmp_path):
    f = tmp_path / "bad.json"
    f.write_text("{ this is not json }")

    findings, _ = jsc.audit_json_keys(f, ["part_number"])
    assert len(findings) == 1
    assert findings[0].category == "INVALID_JSON"


# ---------------------------------------------------------------------------
# Test 6: File missing
# ---------------------------------------------------------------------------
def test_file_missing(tmp_path):
    missing = tmp_path / "nonexistent.json"
    findings, _ = jsc.audit_json_keys(missing, ["part_number"])
    assert len(findings) == 1
    assert findings[0].category == "FILE_MISSING"


# ---------------------------------------------------------------------------
# Test 7: Nested key check with dot notation
# ---------------------------------------------------------------------------
def test_nested_key_dot_notation(tmp_path):
    data = {
        "clock": {"frequency": "100MHz", "duty_cycle": 0.5},
        "part_number": "IC-002",
    }
    f = tmp_path / "L5.json"
    f.write_text(json.dumps(data))

    # Should pass: nested key exists and non-empty
    findings, _ = jsc.audit_json_keys(f, ["clock.frequency"])
    assert len(findings) == 0

    # Should fail: nested key missing
    findings2, _ = jsc.audit_json_keys(f, ["clock.missing_field"])
    assert len(findings2) == 1
    assert findings2[0].category == "MISSING_KEY"


# ---------------------------------------------------------------------------
# Test 8: Extra keys OK (only required keys matter)
# ---------------------------------------------------------------------------
def test_extra_keys_ok(tmp_path):
    data = {
        "part_number": "IC-003",
        "pins": [{"name": "A"}],
        "extra_field_1": "hello",
        "extra_field_2": 42,
        "unrelated": {"nested": True},
    }
    f = tmp_path / "L1.json"
    f.write_text(json.dumps(data))

    findings, _ = jsc.audit_json_keys(f, ["part_number", "pins"])
    assert len(findings) == 0


# ---------------------------------------------------------------------------
# Test: CLI exit codes
# ---------------------------------------------------------------------------
def test_cli_exit_code_pass(tmp_path):
    data = {"part_number": "IC-001", "pins": [{"name": "VDD"}]}
    f = tmp_path / "L1.json"
    f.write_text(json.dumps(data))

    rc = jsc.main([
        '--json-file', str(f),
        '--required-keys', 'part_number,pins',
    ])
    assert rc == 0


def test_cli_exit_code_fail(tmp_path):
    data = {"part_number": "IC-001"}
    f = tmp_path / "L1.json"
    f.write_text(json.dumps(data))

    rc = jsc.main([
        '--json-file', str(f),
        '--required-keys', 'part_number,missing_key',
    ])
    assert rc == 1


# ---------------------------------------------------------------------------
# v0.61 Bug #2 — fact-graph profiles (Path A)
# ---------------------------------------------------------------------------
def test_fact_graph_profile_l1_passes_on_renderer_output(tmp_path):
    """L1 profile checks `ic_name`, which fact-graph render always emits."""
    data = {
        "ic_name": "MY_WDT", "class_path": "apb-peripheral",
        "overview": {"package": "QFN16"}, "pinout": {},
        "electrical_characteristics": {},
    }
    f = tmp_path / "L1_DATASHEET.json"
    f.write_text(json.dumps(data))
    rc = jsc.main(['--json-file', str(f), '--skill-profile', 'L1'])
    assert rc == 0


def test_fact_graph_profile_l1_fails_when_ic_name_missing(tmp_path):
    data = {"class_path": "apb-peripheral", "overview": {}}
    f = tmp_path / "L1.json"
    f.write_text(json.dumps(data))
    rc = jsc.main(['--json-file', str(f), '--skill-profile', 'L1'])
    assert rc == 1


def test_fact_graph_profile_l8r_requires_clock_frequency(tmp_path):
    """L8R must declare clock_frequency_hz for downstream SDC generation."""
    f = tmp_path / "L8_RTL_CONSTANTS.json"
    f.write_text(json.dumps({"clock_frequency_hz": 50_000_000}))
    rc = jsc.main(['--json-file', str(f), '--skill-profile', 'L8R'])
    assert rc == 0
    # Without it: FAIL
    f.write_text(json.dumps({"reset_polarity": "low"}))
    rc = jsc.main(['--json-file', str(f), '--skill-profile', 'L8R'])
    assert rc == 1


def test_fact_graph_profile_l9_requires_dtop_and_submodules(tmp_path):
    f = tmp_path / "L9.json"
    f.write_text(json.dumps({
        "dtop_top_level": {"name": "wdt_top"},
        "submodules": [{"name": "wdt_core"}],
    }))
    rc = jsc.main(['--json-file', str(f), '--skill-profile', 'L9'])
    assert rc == 0


def test_fact_graph_profile_l13_requires_criterion_and_tester(tmp_path):
    f = tmp_path / "L13.json"
    f.write_text(json.dumps({
        "criterion": "register_write_read_roundtrip",
        "tester": "Cocotb APB BFM",
    }))
    rc = jsc.main(['--json-file', str(f), '--skill-profile', 'L13'])
    assert rc == 0


def test_fact_graph_profile_l2_empty_keys_passes_on_valid_json(tmp_path):
    """L2/L3/L4/L5/L6/L7/L8 have empty profile lists — class-specific
    structure is enforced by phase1_consistency_check, not here. Empty
    profile + valid JSON should PASS, not error 2."""
    f = tmp_path / "L2.json"
    f.write_text(json.dumps({"requirements": ["watchdog reset"], "modes": ["NORMAL"]}))
    rc = jsc.main(['--json-file', str(f), '--skill-profile', 'L2'])
    assert rc == 0


def test_fact_graph_profile_l2_empty_keys_still_catches_invalid_json(tmp_path):
    """Even with empty profile, the gate must still reject malformed JSON."""
    f = tmp_path / "L2.json"
    f.write_text("not a valid json {{")
    rc = jsc.main(['--json-file', str(f), '--skill-profile', 'L2'])
    assert rc == 1


def test_fact_graph_profile_l10_requires_test_cases(tmp_path):
    f = tmp_path / "L10.json"
    f.write_text(json.dumps({"test_cases": [{"id": "TC01"}]}))
    rc = jsc.main(['--json-file', str(f), '--skill-profile', 'L10'])
    assert rc == 0


# ---------------------------------------------------------------------------
# v0.61 — Path B (legacy v0.51) profiles still work (regression guard)
# ---------------------------------------------------------------------------
def test_path_b_legacy_datasheet_gen_profile_unchanged(tmp_path):
    """Path B's `datasheet-gen` profile still requires v0.51 keys."""
    data = {
        "part_number": "X", "description": "y",
        "pin_count": 8, "package": "SOIC",
    }
    f = tmp_path / "L1.json"
    f.write_text(json.dumps(data))
    rc = jsc.main(['--json-file', str(f), '--skill-profile', 'datasheet-gen'])
    assert rc == 0


def test_path_b_legacy_regmap_gen_profile_unchanged(tmp_path):
    f = tmp_path / "L4.json"
    f.write_text(json.dumps({"registers": [], "base_address": "0x1000_0000"}))
    rc = jsc.main(['--json-file', str(f), '--skill-profile', 'regmap-gen'])
    # Empty list counts as empty value → FAIL (preserves v0.51 behavior)
    assert rc == 1
    f.write_text(json.dumps({
        "registers": [{"name": "CTRL"}], "base_address": "0x1000_0000",
    }))
    rc = jsc.main(['--json-file', str(f), '--skill-profile', 'regmap-gen'])
    assert rc == 0
