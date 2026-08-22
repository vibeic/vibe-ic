"""Unit tests for lec_equivalence_check.py (Step 13 LEC substance gate).

Covers the exact anti-fabrication failure the gate must guard:
  - PASS  : equivalent==true WITH real compared-point evidence + 0 failures
  - FAIL  : vacuous claim (equivalent:true, 0 points compared)
  - FAIL  : equivalent==true but non-equivalent / unproven points present
  - FAIL  : equivalent==false
  - FAIL  : missing report (REQUIRED check -> honest FAIL, never vacuous PASS)
"""
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "lec_equivalence_check.py"
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import lec_equivalence_check as lec  # noqa: E402


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _write_json(project: Path, obj: dict) -> Path:
    p = project / "reports" / "lec.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj))
    return p


def _write_rpt(project: Path, text: str) -> Path:
    p = project / "reports" / "lec.rpt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def _run(project: Path) -> int:
    return lec.main([str(project)])


# ---------------------------------------------------------------------------
# PASS — substance good
# ---------------------------------------------------------------------------
def test_pass_with_real_point_counts(tmp_path):
    _write_json(tmp_path, {
        "equivalent": True,
        "compared_points": 128,
        "non_equivalent_points": 0,
        "unproven_points": 0,
    })
    res = lec.audit(tmp_path)
    assert res.passed is True
    assert res.equivalent is True
    assert res.compared_points == 128
    assert res.findings == []
    assert _run(tmp_path) == 0


def test_pass_with_alias_field_names(tmp_path):
    # Conformal/Formality-style aliases must still verify.
    _write_json(tmp_path, {
        "is_equivalent": True,
        "points_compared": 57,
        "non_equiv_points": 0,
        "aborted": 0,
    })
    res = lec.audit(tmp_path)
    assert res.passed is True
    assert res.compared_points == 57


def test_pass_via_yosys_rpt_success_line_when_json_has_no_counts(tmp_path):
    # JSON has only the boolean; .rpt carries the canonical Yosys proof.
    _write_json(tmp_path, {"equivalent": True})
    _write_rpt(
        tmp_path,
        "Executing EQUIV_STATUS pass.\n"
        "Proved 64 $equiv cells.\n"
        "Equivalence successfully proven!\n",
    )
    res = lec.audit(tmp_path)
    assert res.passed is True
    assert res.compared_points == 64
    assert res.evidence_source in ("rpt", "json+rpt")
    assert _run(tmp_path) == 0


# ---------------------------------------------------------------------------
# FAIL — vacuous claim (the headline anti-fabrication hole)
# ---------------------------------------------------------------------------
def test_fail_vacuous_zero_points_compared(tmp_path):
    _write_json(tmp_path, {
        "equivalent": True,
        "compared_points": 0,
        "non_equivalent_points": 0,
    })
    res = lec.audit(tmp_path)
    assert res.passed is False
    rules = {f.rule for f in res.findings}
    assert "LEC_VACUOUS_CLAIM" in rules
    assert _run(tmp_path) == 1


def test_fail_equivalent_true_but_no_evidence_anywhere(tmp_path):
    # bare {"equivalent": true} — exactly what the old json_field_true trusted.
    _write_json(tmp_path, {"equivalent": True})
    res = lec.audit(tmp_path)
    assert res.passed is False
    rules = {f.rule for f in res.findings}
    assert "LEC_NO_POINT_EVIDENCE" in rules
    assert _run(tmp_path) == 1


# ---------------------------------------------------------------------------
# FAIL — real non-equivalence / unproven points
# ---------------------------------------------------------------------------
def test_fail_nonequivalent_points_present(tmp_path):
    _write_json(tmp_path, {
        "equivalent": True,           # self-asserted true ...
        "compared_points": 100,
        "non_equivalent_points": 3,   # ... but body contradicts it
    })
    res = lec.audit(tmp_path)
    assert res.passed is False
    assert "LEC_NONEQUIV_POINTS" in {f.rule for f in res.findings}
    assert _run(tmp_path) == 1


def test_fail_unproven_points_present(tmp_path):
    _write_json(tmp_path, {
        "equivalent": True,
        "compared_points": 100,
        "non_equivalent_points": 0,
        "unproven_points": 2,
    })
    res = lec.audit(tmp_path)
    assert res.passed is False
    assert "LEC_UNPROVEN_POINTS" in {f.rule for f in res.findings}
    assert _run(tmp_path) == 1


def test_fail_unproven_from_rpt_only(tmp_path):
    _write_json(tmp_path, {"equivalent": True, "compared_points": 40})
    _write_rpt(tmp_path, "Found 5 unproven $equiv cells in 'top'.\n")
    res = lec.audit(tmp_path)
    assert res.passed is False
    assert res.unproven_points == 5
    assert "LEC_UNPROVEN_POINTS" in {f.rule for f in res.findings}


def test_fail_equivalent_false(tmp_path):
    _write_json(tmp_path, {
        "equivalent": False,
        "compared_points": 100,
        "non_equivalent_points": 4,
    })
    res = lec.audit(tmp_path)
    assert res.passed is False
    assert "LEC_NOT_EQUIVALENT" in {f.rule for f in res.findings}
    assert _run(tmp_path) == 1


# ---------------------------------------------------------------------------
# FAIL — missing / unparseable data (REQUIRED check: never vacuous PASS)
# ---------------------------------------------------------------------------
def test_fail_missing_report(tmp_path):
    # no reports/lec.json at all
    res = lec.audit(tmp_path)
    assert res.passed is False
    assert "LEC_REPORT_MISSING" in {f.rule for f in res.findings}
    assert _run(tmp_path) == 1


def test_fail_unparseable_json(tmp_path):
    p = tmp_path / "reports" / "lec.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{ this is not json ]")
    res = lec.audit(tmp_path)
    assert res.passed is False
    assert "LEC_REPORT_UNPARSEABLE" in {f.rule for f in res.findings}
    assert _run(tmp_path) == 1


def test_fail_json_not_object(tmp_path):
    p = tmp_path / "reports" / "lec.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("[1, 2, 3]")
    res = lec.audit(tmp_path)
    assert res.passed is False
    assert "LEC_REPORT_UNPARSEABLE" in {f.rule for f in res.findings}


# ---------------------------------------------------------------------------
# misc — list-valued count fields, CLI --json emission, bad dir
# ---------------------------------------------------------------------------
def test_list_valued_nonequiv_points_count_as_length(tmp_path):
    _write_json(tmp_path, {
        "equivalent": True,
        "compared_points": 10,
        "non_equivalent_points": [{"point": "reg_a"}, {"point": "reg_b"}],
    })
    res = lec.audit(tmp_path)
    assert res.non_equivalent_points == 2
    assert res.passed is False
    assert "LEC_NONEQUIV_POINTS" in {f.rule for f in res.findings}


def test_json_output_written_and_shape(tmp_path):
    _write_json(tmp_path, {
        "equivalent": True, "compared_points": 8,
        "non_equivalent_points": 0, "unproven_points": 0,
    })
    out = tmp_path / "out" / "report.json"
    rc = lec.main([str(tmp_path), "--json", str(out)])
    assert rc == 0
    assert out.is_file()
    rep = json.loads(out.read_text())
    assert rep["program"] == "lec_equivalence_check"
    assert rep["passed"] is True
    assert rep["compared_points"] == 8
    assert "findings" in rep and "summary" in rep


def test_bad_project_dir_returns_2(tmp_path):
    missing = tmp_path / "nope"
    assert lec.main([str(missing)]) == 2
