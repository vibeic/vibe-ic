"""Unit tests for phase1_doc_presence_check.py."""
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "phase1_doc_presence_check.py"
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"
sys.path.insert(0, str(SCRIPT.parent))
import phase1_doc_presence_check as chk  # noqa: E402


def _touch(d: Path, name: str) -> None:
    (d / name).write_text("{}")


def test_all_10_present_passes(tmp_path):
    d = tmp_path / "docs"
    d.mkdir(parents=True, exist_ok=True)
    for n in [
        "L1_DATASHEET.json", "L2_FRS.json", "L3_CMD_PROTOCOL.json",
        "L4_REGMAP.json", "L5_ADI_SPEC.json", "L6_CONTROL_LOGIC.json",
        "L7_TEST_DEBUG.json", "L8_TIMING.json", "L8_RTL_CONSTANTS.json",
        "L9_INTEGRATION_SPEC.json",
    ]:
        _touch(d, n)
    findings = chk.check(d)
    errors = [f for f in findings if f.severity == "error"]
    assert not errors


def test_lowercase_variants_pass(tmp_path):
    d = tmp_path / "docs"
    d.mkdir(parents=True, exist_ok=True)
    for n in [
        "L1_datasheet.json", "L2_frs.json", "L3_cmd_protocol.json",
        "L4_regmap.json", "L5_adi.json", "L6_control_logic.json",
        "L7_test_debug.json", "L8_timing.json", "constants.json",  # L8R variant
        "L9_integration.json",
    ]:
        _touch(d, n)
    findings = chk.check(d)
    # constants.json doesn't match the L8R pattern, so 1 error expected
    errors = [f for f in findings if f.severity == "error"]
    assert len(errors) == 1
    assert errors[0].rule == "missing-L8R"


def test_v043_pattern_fails(tmp_path):
    """Simulate the actual v041-v043 mistake."""
    d = tmp_path / "docs"
    d.mkdir(parents=True, exist_ok=True)
    for n in ["L1_datasheet.json", "L3_cmd_protocol.json",
              "L8_timing_waveform.json", "L9_integration_spec.json"]:
        _touch(d, n)
    findings = chk.check(d)
    errors = [f for f in findings if f.severity == "error"]
    # Missing: L2, L4, L5, L6, L7, L8R
    assert len(errors) == 6
    missing_ids = sorted(f.rule for f in errors)
    assert missing_ids == sorted(
        ["missing-L2", "missing-L4", "missing-L5",
         "missing-L6", "missing-L7", "missing-L8R"]
    )


def test_missing_dir_fails(tmp_path):
    findings = chk.check(tmp_path / "nonexistent")
    errors = [f for f in findings if f.severity == "error"]
    assert errors
    assert errors[0].rule == "docs-dir-missing"


# ---------------------------------------------------------------------------
# v0.57 D2: no-protocol sentinel — L3 / L8R are optional when active
# ---------------------------------------------------------------------------
import json as _json


def _write_sentinel_l3(d):
    (d / "L3_CMD_PROTOCOL.json").write_text(
        _json.dumps({"protocol_present": False,
                     "reason": "register-pointer access only"}))


def _write_sentinel_l1(d):
    (d / "L1_DATASHEET.json").write_text(
        _json.dumps({"class_path": "any-ic > analog-front-end",
                     "protocol_present": False}))


def test_sentinel_active_skips_l3_and_l8r(tmp_path):
    """When L3 declares the sentinel, both L3 and L8R may be omitted."""
    d = tmp_path / "docs"
    d.mkdir(parents=True, exist_ok=True)
    for n in ["L1_DATASHEET.json", "L2_FRS.json",
              "L4_REGMAP.json", "L5_ADI_SPEC.json", "L6_CONTROL_LOGIC.json",
              "L7_TEST_DEBUG.json", "L8_TIMING_WAVEFORM.json",
              "L9_INTEGRATION_SPEC.json"]:
        _touch(d, n)
    _write_sentinel_l3(d)
    findings = chk.check(d)
    errors = [f for f in findings if f.severity == "error"]
    assert errors == []
    skip_rules = sorted(f.rule for f in findings if f.severity == "info")
    # L3 file IS present (the sentinel itself), so only L8R is skipped
    assert "skipped-L8R-no-protocol" in skip_rules


def test_sentinel_active_via_l1_field_alone(tmp_path):
    """L1.protocol_present=false alone is enough to skip L3 + L8R."""
    d = tmp_path / "docs"
    d.mkdir(parents=True, exist_ok=True)
    for n in ["L2_FRS.json", "L4_REGMAP.json", "L5_ADI_SPEC.json",
              "L6_CONTROL_LOGIC.json", "L7_TEST_DEBUG.json",
              "L8_TIMING_WAVEFORM.json", "L9_INTEGRATION_SPEC.json"]:
        _touch(d, n)
    _write_sentinel_l1(d)
    findings = chk.check(d)
    errors = [f for f in findings if f.severity == "error"]
    assert errors == []
    skip_rules = sorted(f.rule for f in findings if f.severity == "info")
    assert "skipped-L3-no-protocol" in skip_rules
    assert "skipped-L8R-no-protocol" in skip_rules


def test_no_sentinel_still_requires_l3_and_l8r(tmp_path):
    """Backwards compat: legacy protocol-IC project still fails."""
    d = tmp_path / "docs"
    d.mkdir(parents=True, exist_ok=True)
    for n in ["L1_DATASHEET.json", "L2_FRS.json",
              "L4_REGMAP.json", "L5_ADI_SPEC.json", "L6_CONTROL_LOGIC.json",
              "L7_TEST_DEBUG.json", "L8_TIMING_WAVEFORM.json",
              "L9_INTEGRATION_SPEC.json"]:
        _touch(d, n)
    findings = chk.check(d)
    rules = sorted(f.rule for f in findings if f.severity == "error")
    assert "missing-L3" in rules
    assert "missing-L8R" in rules


def test_sentinel_does_not_excuse_other_missing_layers(tmp_path):
    """Sentinel only skips L3 and L8R; L1/L2/L4/L5/L6/L7/L8T/L9 still required."""
    d = tmp_path / "docs"
    d.mkdir(parents=True, exist_ok=True)
    _write_sentinel_l3(d)
    findings = chk.check(d)
    error_rules = sorted(f.rule for f in findings if f.severity == "error")
    assert "missing-L3" not in error_rules
    assert "missing-L8R" not in error_rules
    for needed in ("missing-L1", "missing-L2", "missing-L4",
                   "missing-L5", "missing-L6", "missing-L7",
                   "missing-L8T", "missing-L9"):
        assert needed in error_rules
