"""Unit tests for no_protocol_consistency_check.py (v0.56 gate)."""
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'no_protocol_consistency_check.py'
assert SCRIPT.exists()

sys.path.insert(0, str(SCRIPT.parent))
import no_protocol_consistency_check as gate  # noqa: E402


def _make_docs(tmp_path, l3_dict=None, l8r_dict=None, class_path=None):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    if l3_dict is not None:
        (docs / "L3_CMD_PROTOCOL.json").write_text(json.dumps(l3_dict))
    if l8r_dict is not None:
        (docs / "L8_RTL_CONSTANTS.json").write_text(json.dumps(l8r_dict))
    if class_path:
        (docs / "L1_DATASHEET.json").write_text(
            json.dumps({"class_path": f"any-ic > digital-ic > {class_path}"}))
    return docs


def _make_class_kb(tmp_path, name, floor_lines):
    kb = tmp_path / "class_kb"
    (kb / "templates").mkdir(parents=True)
    body = f"class: {name}\n\nspec_floor:\n"
    for line in floor_lines:
        body += f"  {line}\n"
    (kb / "templates" / f"{name}.yaml").write_text(body)
    return kb


# ---------------------------------------------------------------------------
# Sentinel absent → gate is N/A → exit 0
# ---------------------------------------------------------------------------
def test_no_l3_file_returns_pass(tmp_path):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    rc, report = gate.check(docs, tmp_path / "no_kb")
    assert rc == 0
    assert report["applies"] is False


def test_l3_with_protocol_present_returns_pass(tmp_path):
    docs = _make_docs(tmp_path, l3_dict={"protocol_present": True})
    rc, report = gate.check(docs, tmp_path / "no_kb")
    assert rc == 0
    assert report["applies"] is False


def test_l3_without_protocol_present_field_returns_pass(tmp_path):
    """Legacy L3 (no field) is treated as protocol_present: true."""
    docs = _make_docs(tmp_path, l3_dict={"commands": [{"opcode": "0x70"}]})
    rc, report = gate.check(docs, tmp_path / "no_kb")
    assert rc == 0
    assert report["applies"] is False


# ---------------------------------------------------------------------------
# Sentinel present → 4 rules
# ---------------------------------------------------------------------------
def test_sentinel_with_reason_passes(tmp_path):
    kb = _make_class_kb(tmp_path, "any-ic",
                        ["L4_regmap_reg_count_min: 1"])
    docs = _make_docs(tmp_path,
                      l3_dict={"protocol_present": False,
                               "reason": "register-pointer access only"},
                      class_path="any-ic")
    rc, report = gate.check(docs, kb)
    assert rc == 0
    assert report["pass"] is True


def test_sentinel_missing_reason_fails(tmp_path):
    docs = _make_docs(tmp_path, l3_dict={"protocol_present": False})
    rc, report = gate.check(docs, tmp_path / "no_kb")
    assert rc == 1
    rules = [f["rule"] for f in report["findings"]]
    assert "no_protocol_reason_required" in rules


def test_sentinel_empty_reason_fails(tmp_path):
    docs = _make_docs(tmp_path,
                      l3_dict={"protocol_present": False, "reason": "  "})
    rc, report = gate.check(docs, tmp_path / "no_kb")
    assert rc == 1
    assert any(f["rule"] == "no_protocol_reason_required"
               for f in report["findings"])


def test_sentinel_with_command_set_contradicts(tmp_path):
    docs = _make_docs(tmp_path, l3_dict={
        "protocol_present": False,
        "reason": "ADC",
        "command_set": [{"opcode": "0x70"}],
    })
    rc, report = gate.check(docs, tmp_path / "no_kb")
    assert rc == 1
    contradictions = [f for f in report["findings"]
                      if f["rule"] == "no_protocol_l3_contradiction"]
    assert any(f["field"] == "command_set" for f in contradictions)


def test_sentinel_with_crc_field_contradicts(tmp_path):
    docs = _make_docs(tmp_path, l3_dict={
        "protocol_present": False, "reason": "ADC",
        "crc": {"poly": "0x31"},
    })
    rc, report = gate.check(docs, tmp_path / "no_kb")
    assert rc == 1
    fields = [f.get("field") for f in report["findings"]]
    assert "crc" in fields


def test_sentinel_with_l8r_crc_const_contradicts(tmp_path):
    docs = _make_docs(tmp_path,
                      l3_dict={"protocol_present": False, "reason": "EEPROM"},
                      l8r_dict={"crc8_polynomial": "0x07",
                                "clock_frequency_hz": 5000000})
    rc, report = gate.check(docs, tmp_path / "no_kb")
    assert rc == 1
    assert any(f["rule"] == "no_protocol_l8r_contradiction"
               for f in report["findings"])


def test_sentinel_class_floor_demands_opcode_count(tmp_path):
    kb = _make_class_kb(tmp_path, "cable-side-id-ic",
                        ["L3_opcode_count_min: 8"])
    docs = _make_docs(tmp_path,
                      l3_dict={"protocol_present": False, "reason": "ADC"},
                      class_path="cable-side-id-ic")
    rc, report = gate.check(docs, kb)
    assert rc == 1
    assert any(f["rule"] == "no_protocol_class_floor_mismatch"
               and f.get("field") == "L3_opcode_count_min"
               for f in report["findings"])


def test_sentinel_class_floor_demands_crc_poly(tmp_path):
    kb = _make_class_kb(tmp_path, "cable-side-id-ic",
                        ["L3_crc_poly_allowed:"])
    docs = _make_docs(tmp_path,
                      l3_dict={"protocol_present": False, "reason": "ADC"},
                      class_path="cable-side-id-ic")
    rc, report = gate.check(docs, kb)
    assert rc == 1
    assert any(f.get("field") == "L3_crc_poly_allowed"
               for f in report["findings"])


# ---------------------------------------------------------------------------
# Path errors + CLI
# ---------------------------------------------------------------------------
def test_missing_docs_dir_returns_2(tmp_path):
    rc, report = gate.check(tmp_path / "absent", tmp_path / "no_kb")
    assert rc == 2
    assert "error" in report


def test_cli_pass(tmp_path):
    docs = _make_docs(tmp_path, l3_dict={"protocol_present": False,
                                          "reason": "EEPROM"})
    rc = gate.main([str(docs), "--class-kb", str(tmp_path / "no_kb")])
    assert rc == 0


def test_cli_fail(tmp_path):
    docs = _make_docs(tmp_path, l3_dict={"protocol_present": False,
                                          "reason": "ADC",
                                          "command_set": [{"opcode": "1"}]})
    rc = gate.main([str(docs), "--class-kb", str(tmp_path / "no_kb")])
    assert rc == 1
