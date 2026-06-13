"""Unit tests for l10_tb_conformance_check.py (v0.53 gate).

Complements cmd_response_conformance_check (which verifies CRC-residue)
by demanding that the tb harness actually DROVE every L10 vector.
"""
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'l10_tb_conformance_check.py'
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import l10_tb_conformance_check as gate  # noqa: E402


# ---------------------------------------------------------------------------
# load_l10 — accepts multiple container shapes
# ---------------------------------------------------------------------------
def test_load_l10_flat_list(tmp_path):
    p = tmp_path / "L10.json"
    p.write_text(json.dumps([{"id": "C1"}, {"id": "C2"}]))
    assert len(gate.load_l10(str(p))) == 2


def test_load_l10_test_cases_key(tmp_path):
    p = tmp_path / "L10.json"
    p.write_text(json.dumps({"test_cases": [{"id": "TC01"}]}))
    assert gate.load_l10(str(p))[0]["id"] == "TC01"


def test_load_l10_vectors_key(tmp_path):
    p = tmp_path / "L10.json"
    p.write_text(json.dumps({"vectors": [{"id": "V1"}, {"id": "V2"}]}))
    assert len(gate.load_l10(str(p))) == 2


def test_load_l10_unknown_shape_raises(tmp_path):
    p = tmp_path / "L10.json"
    p.write_text(json.dumps({"something_else": []}))
    with pytest.raises(ValueError):
        gate.load_l10(str(p))


# ---------------------------------------------------------------------------
# opcode patterns
# ---------------------------------------------------------------------------
def test_opcode_patterns_hex_form():
    pats = gate.opcode_patterns("70")
    blob = "  localparam CMD_GET_ID = 8'h70;"
    assert any(p.search(blob) for p in pats)


def test_opcode_patterns_lowercase_hex_form():
    pats = gate.opcode_patterns("74")
    blob = "wire [7:0] op = 8'h74;"
    assert any(p.search(blob) for p in pats)


def test_opcode_patterns_invalid_returns_empty():
    assert gate.opcode_patterns("not-hex") == []


# ---------------------------------------------------------------------------
# case_has_opcode_evidence
# ---------------------------------------------------------------------------
def test_case_opcode_found_in_tb_blob():
    case = {"opcode": "70"}
    blob = "cmd_opcode <= 8'h70;"
    assert gate.case_has_opcode_evidence(case, blob) is True


def test_case_opcode_missing_returns_false():
    case = {"opcode": "70"}
    blob = "cmd_opcode <= 8'hAA;"
    assert gate.case_has_opcode_evidence(case, blob) is False


def test_case_opcode_from_host_packet_first_byte():
    case = {"host_packet": ["74", "00", "FF"]}
    blob = "txb[0] <= 8'h74;"
    assert gate.case_has_opcode_evidence(case, blob) is True


def test_case_without_opcode_field_returns_false():
    case = {"id": "X"}  # no opcode-ish fields
    assert gate.case_has_opcode_evidence(case, "any blob") is False


# ---------------------------------------------------------------------------
# case id / summary helpers
# ---------------------------------------------------------------------------
def test_case_id_appears_in_tb(tmp_path):
    blob = "// case CMD_GET_ID_OK: drive …"
    assert gate.case_id_appears("CMD_GET_ID_OK", blob, "") is True


def test_case_id_appears_in_summary(tmp_path):
    summary = "CMD_GET_ID_OK PASS\nTC02 PASS\n"
    assert gate.case_id_appears("TC02", "", summary) is True


def test_case_id_empty_string_returns_false():
    assert gate.case_id_appears("", "anything", "") is False


def test_summary_has_pass_matches():
    assert gate.summary_has_pass("TC01", "tb_foo  TC01 PASS") is True


def test_summary_has_pass_no_match():
    assert gate.summary_has_pass("TC01", "tb_foo  TC01 FAIL") is False


# ---------------------------------------------------------------------------
# evaluate()
# ---------------------------------------------------------------------------
def test_evaluate_cmd_response_covered_by_opcode_and_summary():
    cases = [{"id": "GET_ID", "category": "cmd_response", "opcode": "70"}]
    tb_blob = "cmd_opcode <= 8'h70;"
    summary = "GET_ID PASS"
    results, ok, fail = gate.evaluate(cases, tb_blob, summary)
    assert ok == 1 and fail == 0
    assert "opcode in tb" in results[0]["evidence"]


def test_evaluate_error_path_covered_by_id_reference():
    cases = [{"id": "TC_ERR_01", "category": "error_path"}]
    tb_blob = "// testing TC_ERR_01 corner"
    results, ok, fail = gate.evaluate(cases, tb_blob, "")
    assert ok == 1 and fail == 0
    assert "id substring in tb/summary" in results[0]["evidence"]


def test_evaluate_uncovered_case():
    cases = [{"id": "GHOST", "category": "cmd_response", "opcode": "FF"}]
    results, ok, fail = gate.evaluate(cases, "// nothing", "")
    assert fail == 1 and ok == 0
    assert results[0]["evidence"] == []
    assert results[0]["pass"] is False


# ---------------------------------------------------------------------------
# main() CLI
# ---------------------------------------------------------------------------
def _make_tree(tmp_path, l10_cases, tb_files, summary_text=""):
    (tmp_path / "phase1" / "generated_docs").mkdir(parents=True)
    (tmp_path / "phase1" / "generated_docs" / "L10.json").write_text(
        json.dumps({"test_cases": l10_cases}))
    tb_dir = tmp_path / "phase2" / "stage1" / "sim" / "tb"
    tb_dir.mkdir(parents=True)
    for name, text in tb_files.items():
        (tb_dir / name).write_text(text)
    summary_path = tmp_path / "phase2" / "stage1" / "sim" / "work" / "summary.txt"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(summary_text)
    return tb_dir, summary_path


def test_cli_pass_when_every_case_covered(tmp_path):
    tb_dir, summary = _make_tree(
        tmp_path,
        [{"id": "GET_ID", "category": "cmd_response", "opcode": "70"}],
        {"tb_cmd.v": "cmd <= 8'h70;"},
        "GET_ID PASS\n")
    out = tmp_path / "out.json"
    rc = gate.main([
        "--l10", str(tmp_path / "phase1" / "generated_docs" / "L10.json"),
        "--tb-dir", str(tb_dir),
        "--summary", str(summary),
        "--out", str(out),
    ])
    assert rc == 0
    data = json.loads(out.read_text())
    assert data["ok"] == 1
    assert data["fail"] == 0


def test_cli_fail_when_case_lacks_evidence(tmp_path):
    tb_dir, summary = _make_tree(
        tmp_path,
        [{"id": "GHOST", "category": "cmd_response", "opcode": "FF"}],
        {"tb_other.v": "wire x;"},
        "")
    out = tmp_path / "out.json"
    rc = gate.main([
        "--l10", str(tmp_path / "phase1" / "generated_docs" / "L10.json"),
        "--tb-dir", str(tb_dir),
        "--summary", str(summary),
        "--out", str(out),
    ])
    assert rc == 1


def test_cli_warn_only_flag_returns_0_on_failures(tmp_path):
    tb_dir, summary = _make_tree(
        tmp_path,
        [{"id": "GHOST", "category": "cmd_response", "opcode": "FF"}],
        {"tb_other.v": ""},
        "")
    out = tmp_path / "out.json"
    rc = gate.main([
        "--l10", str(tmp_path / "phase1" / "generated_docs" / "L10.json"),
        "--tb-dir", str(tb_dir),
        "--summary", str(summary),
        "--out", str(out),
        "--warn-only",
    ])
    assert rc == 0


def test_cli_missing_l10_returns_2(tmp_path):
    tb_dir = tmp_path / "phase2" / "stage1" / "sim" / "tb"
    tb_dir.mkdir(parents=True)
    rc = gate.main([
        "--l10", str(tmp_path / "no.json"),
        "--tb-dir", str(tb_dir),
        "--out", str(tmp_path / "out.json"),
    ])
    assert rc == 2


def test_cli_missing_tb_dir_returns_2(tmp_path):
    (tmp_path / "L10.json").write_text(json.dumps([{"id": "X"}]))
    rc = gate.main([
        "--l10", str(tmp_path / "L10.json"),
        "--tb-dir", str(tmp_path / "no_tb"),
        "--out", str(tmp_path / "out.json"),
    ])
    assert rc == 2
