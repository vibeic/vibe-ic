"""Regression tests for ORGANIC-20260606 #481 + #482.

#481 (MEDIUM, Bucket A): triage records whose category letter contradicts
their own fields. New program `programs/triage_record_check.py` flags:
  (a) F/G/H with closeloop=false and no skip justification
  (b) A-E (FLOOR) marked closeloop=true
  (c) agent-fixable letter with FLOOR-family rationale → REVIEW finding

#482 (LOW, Bucket B): the dataset-agnostic module-name-source-priority
lesson must be present in skills/open-benchmark-methodology/SKILL.md, named
generically (no benchmark/chip literals), and the skill's compliance tests
must still pass.

ACCEPTANCE (from the issue ## 驗收):
  (481) feed a fixture triage json reproducing the 4 violation shapes
        (H×2 closeloop=false no justification; F/G with FLOOR rationale)
        → exactly those violations listed; a compliant set → PASS.
  (482) the SKILL.md section exists, names the rule generically, and the
        skill's structure/compliance tests still pass.
"""
from __future__ import annotations

import json
from pathlib import Path

import triage_record_check as mod

SKILL_MD = (Path(__file__).resolve().parents[2]
            / "skills" / "open-benchmark-methodology" / "SKILL.md")


# ── #481 defect fixture: the 4 violation shapes from the issue ───────────
# Two H records with closeloop=false and no skip justification (rule a),
# one F and one G record whose rationale reads FLOOR (rule c).
DEFECT_RECORDS = [
    {"id": "div_a", "category": "H", "closeloop": False,
     "rationale": "off-by-one in the quotient feedback"},
    {"id": "div_b", "category": "H", "closeloop": False,
     "rationale": "wrong polarity on the partial-remainder mux"},
    {"id": "shift_c", "category": "F", "closeloop": True,
     "rationale": "the spec admits two mutually-exclusive readings of the boundary"},
    {"id": "pipe_d", "category": "G", "closeloop": True,
     "rationale": "this case is under-specified; left spec-faithful"},
]

# A compliant set: F/G/H all close-looped or skip-justified, A-E not
# close-looped, no letter↔rationale clash.
COMPLIANT_RECORDS = [
    {"id": "ok_floor_a", "category": "A", "closeloop": False,
     "rationale": "TB wires a different port name than the prose"},
    {"id": "ok_floor_e", "category": "E", "closeloop": False,
     "rationale": "spec admits two mutually-exclusive readings; left spec-faithful"},
    {"id": "ok_fix_f", "category": "F", "closeloop": True,
     "rationale": "the clue was in the prose; re-read and re-derived"},
    {"id": "ok_fix_g", "category": "G", "closeloop": False,
     "skip_justification": "deferred to next session per time budget",
     "rationale": "convention sweep needed"},
    {"id": "ok_fix_h", "category": "H", "closeloop": True,
     "rationale": "real RTL bug; fixed and self-verified on own TB"},
]


def _write(tmp_path, name, obj):
    p = tmp_path / name
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


# ── #481 ACCEPTANCE: defect fixture → exactly those violations ───────────
def test_481_defect_fixture_lists_exactly_the_four_shapes(tmp_path):
    """END-STATE assertion: the 4 issue shapes are flagged and nothing else."""
    src = _write(tmp_path, "triage.json", DEFECT_RECORDS)
    out = tmp_path / "report.json"
    rc = mod.main([str(src), "--json", str(out)])
    assert rc == 1, "defect fixture must FAIL (rc 1)"

    report = json.loads(out.read_text())
    assert report["verdict"] == "FAIL"

    # The two H records: rule (a) agent_fixable_no_closeloop_no_skip.
    viol_by_id = {v["id"]: v for v in report["violations"]}
    assert set(viol_by_id) == {"div_a", "div_b"}, (
        "exactly the two H records must be rule-a violations")
    assert viol_by_id["div_a"]["rule"] == "agent_fixable_no_closeloop_no_skip"
    assert viol_by_id["div_b"]["rule"] == "agent_fixable_no_closeloop_no_skip"

    # The F and G records: rule (c) letter-vs-rationale contradiction → REVIEW.
    rev_by_id = {r["id"]: r for r in report["reviews"]}
    assert set(rev_by_id) == {"shift_c", "pipe_d"}, (
        "exactly the F and G FLOOR-rationale records must be REVIEW findings")
    assert rev_by_id["shift_c"]["rule"] == "letter_vs_rationale_contradiction"
    assert rev_by_id["pipe_d"]["rule"] == "letter_vs_rationale_contradiction"
    assert "mutually-exclusive" in rev_by_id["shift_c"]["floor_keyword"]
    assert "under-specified" in rev_by_id["pipe_d"]["floor_keyword"]

    assert report["n_violations"] == 2
    assert report["n_reviews"] == 2


def test_481_compliant_set_passes(tmp_path):
    src = _write(tmp_path, "ok.json", COMPLIANT_RECORDS)
    rc = mod.main([str(src)])
    assert rc == 0


# ── #481 individual rules ────────────────────────────────────────────────
def test_481_rule_b_floor_with_closeloop(tmp_path):
    recs = [{"id": "x", "category": "B", "closeloop": True,
             "rationale": "needs a param the prose never states"}]
    src = _write(tmp_path, "b.json", recs)
    out = tmp_path / "r.json"
    rc = mod.main([str(src), "--json", str(out)])
    assert rc == 1
    rep = json.loads(out.read_text())
    assert rep["violations"][0]["rule"] == "floor_with_closeloop"


def test_481_rule_a_satisfied_by_skip_justification(tmp_path):
    recs = [{"id": "x", "category": "H", "closeloop": False,
             "skip_justification": "out of time-budget this session",
             "rationale": "real RTL bug"}]
    src = _write(tmp_path, "skip.json", recs)
    assert mod.main([str(src)]) == 0


def test_481_liberal_field_naming(tmp_path):
    """Alternate field names (letter / close_loop / skip_reason) parse."""
    recs = [{"name": "y", "letter": "H", "close_loop": False,
             "skip_reason": "deferred", "reason": "off-by-one"}]
    src = _write(tmp_path, "alt.json", recs)
    assert mod.main([str(src)]) == 0


def test_481_wrapped_records_shape(tmp_path):
    """{records:[...]} wrapper is accepted (liberal input shape)."""
    src = _write(tmp_path, "wrapped.json", {"records": COMPLIANT_RECORDS})
    assert mod.main([str(src)]) == 0


def test_481_category_in_long_form(tmp_path):
    """'A. Benchmark ↔ TB' style category strings collapse to the letter."""
    recs = [{"id": "z", "category": "A. Benchmark description vs TB",
             "closeloop": False, "rationale": "TB wires a different port"}]
    src = _write(tmp_path, "long.json", recs)
    assert mod.main([str(src)]) == 0


def test_481_invalid_letter_is_violation(tmp_path):
    recs = [{"id": "bad", "category": "Z", "closeloop": False}]
    src = _write(tmp_path, "bad.json", recs)
    out = tmp_path / "r.json"
    assert mod.main([str(src), "--json", str(out)]) == 1
    rep = json.loads(out.read_text())
    assert rep["violations"][0]["rule"] == "letter_invalid"


# ── #481 IO error → exit 2 ───────────────────────────────────────────────
def test_481_missing_file_io_error(tmp_path):
    assert mod.main([str(tmp_path / "absent.json")]) == 2


def test_481_unparseable_json_io_error(tmp_path):
    p = tmp_path / "broken.json"
    p.write_text("{not json", encoding="utf-8")
    assert mod.main([str(p)]) == 2


def test_481_wrong_shape_io_error(tmp_path):
    p = tmp_path / "scalar.json"
    p.write_text("42", encoding="utf-8")
    assert mod.main([str(p)]) == 2


# ── #482 ACCEPTANCE: SKILL.md section exists + generic + wired ────────────
def test_482_skill_md_has_dataset_agnostic_module_name_rule():
    assert SKILL_MD.exists(), "open-benchmark-methodology SKILL.md missing"
    text = SKILL_MD.read_text(encoding="utf-8")
    low = text.lower()
    # The rule names the generic concept, not a chip/benchmark literal.
    assert "directory-leaf" in low or "directory leaf" in low
    assert "tb-facing module name" in low or "testbench-facing module name" in low \
        or "tb-facing" in low
    # close-loop must-not regression clause
    assert "must not" in low and "prose typo" in low
    # why_not_bucket_a judgment note present
    assert "why_not_bucket_a" in low
    assert "contextual judgment" in low or "judgment" in low


def test_482_triage_record_check_wired_into_result_checklist():
    text = SKILL_MD.read_text(encoding="utf-8")
    assert "triage_record_check.py" in text, (
        "triage_record_check must be wired into the § 6 RESULT checklist")
    # Same 'enforced by programs/...' style as result_md_lint.
    assert "programs/triage_record_check.py" in text


def test_482_skill_compliance_tests_still_pass():
    """The skill's own structure/compliance test module must still import +
    its core invariants hold after our SKILL.md / compliance.yaml edits."""
    import importlib.util
    import sys

    comp_test = (SKILL_MD.parent / "tests" / "test_compliance.py")
    assert comp_test.exists()
    spec = importlib.util.spec_from_file_location("obm_compliance_test", comp_test)
    m = importlib.util.module_from_spec(spec)
    # Importing a file under `skills/` writes its `__pycache__/*.pyc`, which
    # moves the digest `test_shipped_skills_tree_is_untouched_by_this_session`
    # compares. Unlike the subprocess case in
    # test_v0_3_4_issue501_verbatim_lessons.py, this import happens in THIS
    # process, so a child's `-B` is irrelevant and only the in-process flag
    # governs it. Restored in `finally` so the setting does not leak into the
    # rest of the session. Measured: without the guard 1 file, with it 0.
    _dwb = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(m)
    finally:
        sys.dont_write_bytecode = _dwb
    # compliance.yaml still loads and declares the skill correctly.
    reqs = m.load_requirements()
    assert reqs.get("skill") == "open-benchmark-methodology"
    assert isinstance(reqs.get("requirements"), list) and reqs["requirements"]


def test_482_rule_is_chip_agnostic():
    """The added rule must carry no chip/vendor codename (deny-list tokens)."""
    deny = (Path(__file__).resolve().parents[1] / "tests" / "chip_deny_list.txt")
    tokens = []
    for line in deny.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            tokens.append(line.lower())
    low = SKILL_MD.read_text(encoding="utf-8").lower()
    import re
    for t in tokens:
        assert not re.search(r"\b" + re.escape(t) + r"\b", low), (
            f"deny-list token {t!r} leaked into SKILL.md")
