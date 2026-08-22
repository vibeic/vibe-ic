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
# ORGANIC #808 — verification_checklist (DV-milestone) kind-scoping.
#
# NEW gap, surfaced after #799 unblocked Step-4: phase1 emits a project's DV
# verification checklist table (e.g. OpenTitan-style) as L10
# kind=verification_checklist rows (status Done/N/A/Waived/None) — DV PROCESS
# MILESTONES, not TB-traceable functional vectors. The TB-evidence demand
# counted EVERY checklist row as "lack evidence" -> hard-FAIL Step-4. These
# tests pin the kind-scope: satisfied/deferred checklist rows are credited,
# blank/None/FAIL rows surface as a (non-fatal) checklist gap, and
# functional_vector / cmd_response cases STILL require TB evidence (§4.05).
# ---------------------------------------------------------------------------
def test_checklist_classify_helpers():
    assert gate.is_verification_checklist({"kind": "verification_checklist"})
    assert gate.is_verification_checklist({"kind": "dv_checklist"})
    assert not gate.is_verification_checklist({"kind": "functional_vector"})
    assert gate.classify_checklist({"status": "Done"}) == "satisfied"
    assert gate.classify_checklist({"status": "N/A"}) == "satisfied"
    assert gate.classify_checklist({"status": "Waived"}) == "satisfied"
    assert gate.classify_checklist({"status": None}) == "checklist_gap"
    assert gate.classify_checklist({"status": ""}) == "checklist_gap"
    assert gate.classify_checklist({"status": "Fail"}) == "checklist_gap"


def test_evaluate_checklist_done_credited_not_failed():
    """POS — a Done/N/A/Waived checklist row is credited (ok), NOT a TB miss."""
    cases = [
        {"name": "spec_complete", "kind": "verification_checklist", "status": "Done"},
        {"name": "csr_defined", "kind": "verification_checklist", "status": "N/A"},
        {"name": "sec_cm", "kind": "verification_checklist", "status": "Waived"},
    ]
    results, ok, fail = gate.evaluate(cases, "// empty tb", "")
    assert ok == 3 and fail == 0
    assert gate.count_checklist_gaps(results) == 0
    assert all(r["status"] == "pass" for r in results)


def test_evaluate_checklist_none_is_gap_not_tb_fail():
    """NEG-3 — a blank/None checklist row surfaces as a checklist gap
    (review_required), NOT folded into fail_count, NOT blanket-passed."""
    cases = [
        {"name": "sim_smoke", "kind": "verification_checklist", "status": None},
        {"name": "fpv_main", "kind": "verification_checklist"},  # no status field
    ]
    results, ok, fail = gate.evaluate(cases, "// empty tb", "")
    assert ok == 0 and fail == 0          # not a TB-evidence failure
    assert gate.count_checklist_gaps(results) == 2
    assert all(r["status"] == "checklist_gap" for r in results)
    assert all(r["review_required"] is True for r in results)


def test_evaluate_checklist_explicit_fail_is_gap_not_blanket_pass():
    """NEG-3 (explicit) — a checklist row with status=Fail is a checklist gap,
    NOT a blanket pass; it stays review_required."""
    cases = [{"name": "x", "kind": "verification_checklist", "status": "Fail"}]
    results, ok, fail = gate.evaluate(cases, "// empty tb", "")
    assert ok == 0 and fail == 0
    assert gate.count_checklist_gaps(results) == 1
    assert results[0]["status"] == "checklist_gap"
    assert results[0]["review_required"] is True


def test_evaluate_functional_vector_still_requires_tb_evidence():
    """NEG-1 — a kind=functional_vector case with NO TB evidence STILL FAILs;
    the checklist relaxation must never leak to genuine functional vectors."""
    cases = [{"id": "VEC_GHOST", "kind": "functional_vector", "opcode": "FF"}]
    results, ok, fail = gate.evaluate(cases, "// unrelated content", "")
    assert fail == 1 and ok == 0
    assert gate.count_checklist_gaps(results) == 0
    assert results[0]["status"] == "fail"


def test_evaluate_mixed_l10_functional_strict_checklist_scoped():
    """MIXED — functional_vector (covered) + checklist Done (credited) +
    checklist None (gap). The functional case keeps its strict TB demand."""
    cases = [
        {"id": "VEC_OK", "kind": "functional_vector"},
        {"name": "spec_complete", "kind": "verification_checklist", "status": "Done"},
        {"name": "sim_smoke", "kind": "verification_checklist", "status": None},
    ]
    tb_blob = "// task drives VEC_OK trace"
    results, ok, fail = gate.evaluate(cases, tb_blob, "")
    assert fail == 0
    assert ok == 2  # functional_vector traced + 1 checklist Done
    assert gate.count_checklist_gaps(results) == 1


def test_evaluate_mixed_functional_miss_still_hard_fails():
    """NO-LEAK — a functional_vector with NO trace STILL hard-FAILs even when
    a sibling checklist row is Done (the checklist credit cannot mask it)."""
    cases = [
        {"id": "VEC_GHOST", "kind": "functional_vector"},
        {"name": "spec_complete", "kind": "verification_checklist", "status": "Done"},
    ]
    results, ok, fail = gate.evaluate(cases, "// unrelated xyz", "")
    assert fail == 1          # the functional miss dominates
    assert ok == 1            # the checklist Done credited
    assert gate.count_checklist_gaps(results) == 0


def test_cli_checklist_only_l10_returns_pass_with_waivers(tmp_path):
    """CLI/consumer-contract — an all-checklist L10 (mix Done + None), with an
    empty TB, returns rc=3 PASS_WITH_WAIVERS (NOT rc=1 hard-FAIL): the
    OpenTitan-style 103/103 false hard-FAIL is the defect this fixes."""
    tb_dir, summary = _make_tree(
        tmp_path,
        [
            {"name": "spec_complete", "kind": "verification_checklist", "status": "Done"},
            {"name": "csr_defined", "kind": "verification_checklist", "status": "N/A"},
            {"name": "sim_smoke", "kind": "verification_checklist", "status": None},
        ],
        {"tb_dummy.v": "// no functional vectors here"},
        "")
    out = tmp_path / "out.json"
    rc = gate.main([
        "--l10", str(tmp_path / "phase1" / "generated_docs" / "L10.json"),
        "--tb-dir", str(tb_dir),
        "--summary", str(summary),
        "--out", str(out),
    ])
    assert rc == 3
    data = json.loads(out.read_text())
    assert data["total"] == 3
    assert data["ok"] == 2          # Done + N/A credited
    assert data["fail"] == 0        # NOT a hard-FAIL
    assert data["checklist_gaps"] == 1


def test_cli_checklist_plus_functional_miss_still_hard_fails(tmp_path):
    """CLI NO-LEAK — a functional_vector with no TB trace alongside checklist
    rows STILL hard-FAILs (rc=1); the checklist scoping never relaxes it."""
    tb_dir, summary = _make_tree(
        tmp_path,
        [
            {"id": "VEC_GHOST", "kind": "functional_vector"},
            {"name": "spec_complete", "kind": "verification_checklist", "status": "Done"},
        ],
        {"tb_dummy.v": "// unrelated content xyz"},
        "")
    out = tmp_path / "out.json"
    rc = gate.main([
        "--l10", str(tmp_path / "phase1" / "generated_docs" / "L10.json"),
        "--tb-dir", str(tb_dir),
        "--summary", str(summary),
        "--out", str(out),
    ])
    assert rc == 1


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
