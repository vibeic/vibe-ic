"""`absence_verdict_names_its_search_space_check` — what it refuses, what it
accepts, and the false positives it was measured against.

Every acceptance case below is a REAL shape from this repo, reduced. They are
here because the first version of the checker reported each of them as a silent
refusal, and a checker that fires on correct code is the thing that teaches
people to ignore it.
"""
from __future__ import annotations

import ast
import importlib.util
import sys
import textwrap
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "_avnss", PROGRAMS / "absence_verdict_names_its_search_space_check.py")
AV = importlib.util.module_from_spec(_spec)
sys.modules["_avnss"] = AV
_spec.loader.exec_module(AV)


def _verdicts(source: str):
    """(rule_id, names_search_space) for every absence verdict in `source`."""
    tree = ast.parse(textwrap.dedent(source))
    out = []
    for lineno, rule_id, companions in AV.absence_verdicts(tree):
        fn = AV._enclosing_function(tree, lineno)
        binds = AV._bindings(fn)
        named = AV._has_locus_resolved(companions, binds) if companions else False
        out.append((rule_id, named))
    return out


# ── the RED: this is the shape the rule exists to refuse ────────────────────

def test_a_refusal_with_no_address_of_any_kind_is_refused():
    """"It is not there" and "I did not look" print identically."""
    assert _verdicts('''
        def check(doc):
            if not doc.get("thing"):
                raise Refusal("THING_NOT_FOUND", "the thing is not there")
    ''') == [("THING_NOT_FOUND", False)]


def test_a_count_is_not_an_address():
    """The measured defect: a denominator over ONE view reads as thoroughness.

    `0 of 1` is true, is measured, and does not say WHICH one — so it cannot be
    told apart from a search that never opened the second view. A count alone
    must not satisfy the rule.
    """
    assert _verdicts('''
        def resolve(n, entries):
            if n not in entries:
                return _fail("SITE_NOT_FOUND",
                             f"{n!r} is not declared ({len(entries)} entries)")
    ''') == [("SITE_NOT_FOUND", False)]


# ── acceptance: each of these was a MEASURED false positive ─────────────────

def test_a_filesystem_path_is_an_address():
    assert _verdicts('''
        def check(root):
            if not root.is_file():
                return _finding("REPORT_ABSENT",
                                f"no report at {root} — nothing ran")
    ''') == [("REPORT_ABSENT", True)]


def test_a_document_address_is_an_address():
    """A field missing from a document already opened answers "where" with a
    JSON pointer. `closures[3]` sends a reader to exactly one place."""
    got = _verdicts('''
        def check(plan):
            for i, c in enumerate(plan["closures"]):
                if not c.get("evidence"):
                    findings.append(Finding("ERROR", "CLOSURE_FIELD_MISSING",
                        f"closures[{i}] missing evidence"))
    ''')
    assert got == [("CLOSURE_FIELD_MISSING", True)]


def test_an_address_whose_tail_is_interpolated_is_an_address():
    """`f"foundry_signoff_plan.{k} is required"` — the literal fragment the
    parser sees ends at the dot, and it is still an address."""
    assert _verdicts('''
        def check(plan):
            for k in REQUIRED:
                if not plan.get(k):
                    findings.append(Finding("ERROR", "PLAN_FIELD_MISSING",
                        f"foundry_signoff_plan.{k} is required"))
    ''') == [("PLAN_FIELD_MISSING", True)]


def test_a_locus_bound_one_line_above_the_refusal_counts():
    """The commonest real shape: `reason` is built out of the path, then
    passed. Reading the call alone reports it as silent."""
    assert _verdicts('''
        def check(rep_path):
            if not rep_path.is_file():
                reason = f"no pad-ring report at {rep_path} — nothing ran"
                findings.append(_finding("PADRING_REPORT_ABSENT", reason))
    ''') == [("PADRING_REPORT_ABSENT", True)]


def test_a_refusal_nested_in_a_report_that_carries_the_paths_counts():
    """`_report(..., inputs={...}, findings=[_finding(ID, ...)])` — the
    disclosure is on the ENCLOSING call, and it is still a disclosure."""
    assert _verdicts('''
        def run(project):
            rep = _report("SKIP", reason,
                          inputs={"floorplan_def": FLOORPLAN_DEF_REL},
                          findings=[_finding("INFO", "REQUIRED_INPUT_ABSENT",
                                             "; ".join(parts))])
    ''') == [("REQUIRED_INPUT_ABSENT", True)]


def test_a_keyword_name_is_disclosure():
    """`note(ID, path=str(mj))` says where it looked in the keyword."""
    assert _verdicts('''
        def parse(mj):
            o.note("METRICS_JSON_NOT_PRESENT", path=str(mj))
    ''') == [("METRICS_JSON_NOT_PRESENT", True)]


# ── population: what is NOT a refusal at all ────────────────────────────────

def test_an_environment_read_is_not_a_refusal():
    """`os.environ.get("VIBEIC_KLAYOUT_FORCE_ABSENT")` is a TEST HOOK whose
    whole job is to force the honest-degrade path. Reporting it as a silent
    refusal is the false positive this restriction removed."""
    assert _verdicts('''
        def runner():
            if os.environ.get("VIBEIC_KLAYOUT_FORCE_ABSENT"):
                return None
    ''') == []


def test_a_rule_id_in_a_comparison_is_not_a_refusal():
    assert _verdicts('''
        def triage(f):
            if f["code"] == "REPORT_ABSENT":
                return "skip"
    ''') == []


def test_tests_are_excluded_from_the_population(tmp_path):
    """A test constructs refusals as FIXTURES, deliberately minimal. Requiring
    a fixture to disclose a search space would flag the tests that prove the
    rule — this file among them."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text(
        'def t():\n    _fail("THING_NOT_FOUND", "nope")\n')
    # NOTE the variable is called `path`, not `p`: the rule asks for a NAMED
    # locus, and a single-letter name discloses nothing to a reader. That is
    # deliberate, and this fixture failed the first time it was written with
    # `p` — which is the property working, not a gap.
    (tmp_path / "shipped.py").write_text(
        'def r(path):\n    _fail("THING_NOT_FOUND", f"nothing at {path}")\n')
    res = AV.scan(tmp_path)
    assert res["files_skipped_tests"] == 1
    assert res["absence_verdicts"] == 1
    assert res["silent"] == []
    res_incl = AV.scan(tmp_path, include_tests=True)
    assert res_incl["absence_verdicts"] == 2
    assert len(res_incl["silent"]) == 1


# ── the exit contract: a gate that could not look has not passed ────────────

def test_an_absent_directory_is_not_checked_not_clean(tmp_path):
    rc = AV.main(["--programs-dir", str(tmp_path / "nope")])
    assert rc == 2


def test_an_empty_population_is_not_checked_not_clean(tmp_path):
    """Zero absence verdicts is not "every absence verdict is well-formed"."""
    (tmp_path / "a.py").write_text("x = 1\n")
    rc = AV.main(["--programs-dir", str(tmp_path)])
    assert rc == 2


def test_a_silent_refusal_makes_the_gate_fail(tmp_path):
    (tmp_path / "a.py").write_text(
        'def r():\n    _fail("THING_NOT_FOUND", "the thing is not there")\n')
    assert AV.main(["--programs-dir", str(tmp_path)]) == 1


def test_a_disclosed_refusal_makes_the_gate_pass(tmp_path):
    (tmp_path / "a.py").write_text(
        'def r(p):\n    _fail("THING_NOT_FOUND", f"nothing at {p} — looked once")\n')
    assert AV.main(["--programs-dir", str(tmp_path)]) == 0


# ── the corpus sweep, in the suite, so it cannot rot unnoticed ──────────────

def test_the_shipped_tree_is_clean():
    """A guard that fires on the tree it ships with is a bug, not a guard."""
    res = AV.scan(PROGRAMS)
    assert res["absence_verdicts"] > 0, "empty population — this proves nothing"
    assert res["silent"] == [], (
        "absence verdicts naming no search space: "
        + ", ".join(f"{v['file']}:{v['line']} {v['rule_id']}"
                    for v in res["silent"]))
