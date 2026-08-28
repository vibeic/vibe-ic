"""programs/tests/test_control_substance_check.py

Every case here drives a REAL `pytest` subprocess and classifies ITS OWN
report. No JUnit XML is hand-typed, so these tests cannot agree with the
classifier by construction — if pytest changes how it renders an assertion,
they go red rather than staying green against a frozen fixture.

The assertions pin OBSERVED COUNTS (`counts["presence_only"] == 2`), not the
presence of a key, because a test that only checks a field exists is the very
thing `control_substance_check` was written to stop crediting. Applying the
rule to its own evidence is the point.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import control_substance_check as CSC  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROGRAM = Path(__file__).resolve().parent.parent / "control_substance_check.py"


# ---------------------------------------------------------------------------
# Real pytest runs
# ---------------------------------------------------------------------------
def run_pytest(tmp_path: Path, name: str, body: str):
    """Write a test module, run pytest over it, return (junit_path, stdout)."""
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    (d / f"test_{name}.py").write_text(body)
    xml = tmp_path / f"{name}.xml"
    txt = tmp_path / f"{name}.txt"
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_ADDOPTS"}
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    proc = _pr.run(
        [sys.executable, "-m", "pytest", str(d), "-q", "-p", "no:cacheprovider",
         f"--junitxml={xml}", f"--basetemp={tmp_path / ('bt_' + name)}"],
        cwd=str(tmp_path), env=env, capture_output=True, text=True,
        # Under the repo's 60 s per-call ceiling (harness bound 180 s // 3):
        # an inner bound above it can outlive the harness and kill the whole
        # session instead of the test. These inner runs measure ~3 s.
        )
    txt.write_text(proc.stdout + proc.stderr)
    assert xml.exists(), f"inner pytest wrote no report: {proc.stdout[-800:]}"
    return xml, txt


def counts_of(xml: Path):
    return CSC.audit(CSC.read_junit(xml))


def cli(*args) -> subprocess.CompletedProcess:
    return _pr.run([sys.executable, str(PROGRAM), *args],
                          capture_output=True, text=True)


# The PR #856 shape: a test file that imports the module the fix introduces.
NEW_MODULE = """
from module_the_fix_introduces import merge
def test_one():
    assert merge({}, {"a": 1}) == {"a": 1}
def test_two():
    assert merge({"a": 1}, {}) == {"a": 1}
def test_three():
    assert merge({"a": 1}, {"a": 2}) == {"a": 2}
"""

# The PR #862 shape: the module is there; only the new FIELD is missing. The
# same defect is reached once through `[]` (KeyError) and three times through
# `.get()` (AssertionError). Substance is identical; the exception class is not.
NEW_FIELD = """
def audit():
    return {"verdict": "FAIL", "version": "0.119.62",
            "steps": [{"name": "a"}, {"name": "b"}]}
def _sha(rec):
    return rec.get("design_sha256")

def test_via_subscript():
    assert audit()["design_sha256"] == "abc"
def test_via_get_is_not_none():
    assert _sha(audit()) is not None
def test_via_get_bare():
    assert _sha(audit()), "the tally was published with no record"
def test_via_membership():
    assert "design_sha256" in {}
def test_the_version_is_read_not_restated():
    assert audit()["version"] == "1.9.79"
def test_the_step_population_is_counted():
    assert len(audit()["steps"]) == 27
"""

# A control that genuinely observed wrong values, and nothing else.
SUBSTANTIVE = """
def rounded(x):
    return int(x)          # the defect: truncates instead of rounding
def verdict(n):
    return "PASS" if n >= 0 else "PASS"   # the defect: never FAIL

def test_rounding():
    assert rounded(2.7) == 3
def test_verdict():
    assert verdict(-1) == "FAIL"
def test_report_text():
    assert "FAIL" in "gate ran: verdict=PASS cases=3"
"""


# ---------------------------------------------------------------------------
# (a) a control that collected nothing
# ---------------------------------------------------------------------------
def test_a_collection_error_is_never_credited_as_a_failing_test(tmp_path):
    xml, _ = run_pytest(tmp_path, "newmod", NEW_MODULE)
    rep = counts_of(xml)
    assert rep["counts"][CSC.NOT_COLLECTED] == 1
    assert rep["substantive"] == 0
    assert rep["tautological"] is True
    # Three test functions were written; none of them ran.
    assert rep["counts"][CSC.OBSERVED_VALUE] == 0
    assert rep["counts"][CSC.PRESENCE_ONLY] == 0


def test_the_junit_test_count_that_makes_this_look_like_a_run(tmp_path):
    """The trap, pinned: pytest reports the collection error as tests="1".

    A reviewer (or a program) that reads `tests` sees a run of size 1 for a
    file with three test functions that executed nothing. This is why the
    checker reads the testcase's <error>, not the suite's counters.
    """
    import xml.etree.ElementTree as ET
    xml, _ = run_pytest(tmp_path, "newmod2", NEW_MODULE)
    suite = ET.parse(str(xml)).getroot().find("testsuite") or \
        ET.parse(str(xml)).getroot()
    assert suite.attrib["tests"] == "1"
    assert suite.attrib["errors"] == "1"
    assert suite.attrib["failures"] == "0"
    assert counts_of(xml)["substantive"] == 0


def test_the_cli_fails_on_a_control_that_collected_nothing(tmp_path):
    xml, _ = run_pytest(tmp_path, "newmod3", NEW_MODULE)
    proc = cli("--junit", str(xml))
    assert proc.returncode == 1
    assert "TAUTOLOGICAL CONTROL" in proc.stdout
    assert "0 of 1 reported failures observed a VALUE" in proc.stdout


# ---------------------------------------------------------------------------
# (b) substance is not the exception class — the PR #862 finding
# ---------------------------------------------------------------------------
def test_wrapping_a_keyerror_in_get_does_not_make_it_behavioural(tmp_path):
    xml, _ = run_pytest(tmp_path, "newfield", NEW_FIELD)
    rep = counts_of(xml)
    by_test = {c["test"].split("::")[-1]: c["bucket"] for c in rep["cases"]}

    # Four different exception classes / assertion shapes, one substance.
    assert by_test["test_via_subscript"] == CSC.PRESENCE_ONLY      # KeyError
    assert by_test["test_via_get_is_not_none"] == CSC.PRESENCE_ONLY
    assert by_test["test_via_get_bare"] == CSC.PRESENCE_ONLY
    assert by_test["test_via_membership"] == CSC.PRESENCE_ONLY

    # ... and the two that really did observe a value.
    assert by_test["test_the_version_is_read_not_restated"] == \
        CSC.OBSERVED_VALUE
    assert by_test["test_the_step_population_is_counted"] == \
        CSC.OBSERVED_VALUE

    assert rep["counts"][CSC.PRESENCE_ONLY] == 4
    assert rep["substantive"] == 2
    assert rep["failures_reported"] == 6


def test_the_reported_split_is_the_number_a_reviewer_was_missing(tmp_path):
    """`2 of 6`, not `6 of 6 behavioural`."""
    xml, _ = run_pytest(tmp_path, "newfield2", NEW_FIELD)
    proc = cli("--junit", str(xml))
    assert proc.returncode == 0
    assert "2 of 6 reported failures observed a VALUE" in proc.stdout


# ---------------------------------------------------------------------------
# (c) REVERSE CASE — a real control must still pass
# ---------------------------------------------------------------------------
def test_a_substantive_control_is_not_flagged(tmp_path):
    xml, _ = run_pytest(tmp_path, "subst", SUBSTANTIVE)
    rep = counts_of(xml)
    assert rep["substantive"] == 3
    assert rep["counts"][CSC.PRESENCE_ONLY] == 0
    assert rep["counts"][CSC.NOT_COLLECTED] == 0
    assert rep["counts"][CSC.UNDECIDED] == 0
    assert rep["tautological"] is False
    assert cli("--junit", str(xml)).returncode == 0


def test_membership_against_real_content_is_substantive(tmp_path):
    """`'FAIL' in 'verdict=PASS...'` observed the text and it was wrong.

    Only membership in an EMPTY container is presence-only. Collapsing all
    `in` assertions to presence-only would have made the checker call a real
    output-text control vacuous.
    """
    xml, _ = run_pytest(tmp_path, "subst2", SUBSTANTIVE)
    by_test = {c["test"].split("::")[-1]: c["bucket"]
               for c in counts_of(xml)["cases"]}
    assert by_test["test_report_text"] == CSC.OBSERVED_VALUE


# ---------------------------------------------------------------------------
# Honest boundary: the input it will not guess on
# ---------------------------------------------------------------------------
AMBIGUOUS = """
def absent():
    return {}.get("design_sha256")      # the field is missing
def genuinely_none(_s):
    return None                          # the function really returns None

def test_absent_field():
    assert absent() == "abc123"
def test_genuine_none():
    assert genuinely_none("x") == 7
"""


def test_the_none_sentinel_is_refused_not_guessed(tmp_path):
    """Two different substances, one identical input, one honest refusal.

    Both produce `assert None == <literal>`. The checker declines both rather
    than guessing, and neither is counted as substantive.
    """
    xml, _ = run_pytest(tmp_path, "ambig", AMBIGUOUS)
    rep = counts_of(xml)
    assert rep["counts"][CSC.UNDECIDED] == 2
    assert rep["substantive"] == 0
    reasons = {c["reason"] for c in rep["cases"]}
    assert len(reasons) == 1, "the two cases must be indistinguishable here"
    assert "None sentinel" in reasons.pop()


LENGTHS = """
def steps():
    return []
def test_something_was_produced():
    assert len(steps()) > 0
def test_the_population_is_27():
    assert len(steps()) == 27
"""


def test_a_length_threshold_and_a_length_equality_are_not_the_same_claim(
        tmp_path):
    """`len(x) > 0` pins no value; `len(x) == 27` pins one but observed 0.

    Collapsing both to presence-only was the first thing this file caught in
    the checker: it silently demoted a real count control.
    """
    xml, _ = run_pytest(tmp_path, "lens", LENGTHS)
    by_test = {c["test"].split("::")[-1]: c["bucket"]
               for c in counts_of(xml)["cases"]}
    assert by_test["test_something_was_produced"] == CSC.PRESENCE_ONLY
    assert by_test["test_the_population_is_27"] == CSC.UNDECIDED


def test_undecided_is_not_laundered_into_substantive(tmp_path):
    xml, _ = run_pytest(tmp_path, "ambig2", AMBIGUOUS)
    proc = cli("--junit", str(xml))
    assert proc.returncode == 1              # 0 substantive => tautological
    assert "undecided (never credited)    : 2" in proc.stdout


# ---------------------------------------------------------------------------
# Tests that were already green are not controls
# ---------------------------------------------------------------------------
def test_a_test_that_passed_pre_fix_is_not_counted_as_a_control(tmp_path):
    xml, _ = run_pytest(tmp_path, "mixed", SUBSTANTIVE + """
def test_already_true():
    assert 1 == 1
""")
    rep = counts_of(xml)
    assert rep["counts"][CSC.PASSED] == 1
    assert rep["failures_reported"] == 3
    assert rep["substantive"] == 3


# ---------------------------------------------------------------------------
# Text mode: weaker, and the program measures by how much
# ---------------------------------------------------------------------------
def test_text_mode_loses_verdicts_the_same_runs_xml_keeps(tmp_path):
    xml, txt = run_pytest(tmp_path, "modes", NEW_FIELD)
    x = CSC.audit(CSC.read_junit(xml))
    t = CSC.audit(CSC.read_text(txt), "text")
    assert x["substantive"] == 2
    # The custom-message assertion loses its assert line in the console log.
    assert t["counts"][CSC.UNDECIDED] > x["counts"][CSC.UNDECIDED]
    assert t["substantive"] <= x["substantive"]


def test_text_mode_still_detects_a_control_that_did_not_collect(tmp_path):
    _, txt = run_pytest(tmp_path, "newmod_txt", NEW_MODULE)
    rep = CSC.audit(CSC.read_text(txt), "text")
    assert rep["counts"][CSC.NOT_COLLECTED] >= 1
    assert rep["substantive"] == 0
    assert rep["tautological"] is True


def test_compare_modes_reports_the_gap(tmp_path):
    xml, txt = run_pytest(tmp_path, "modes2", NEW_FIELD)
    out = tmp_path / "r.json"
    proc = cli("--junit", str(xml), "--text", str(txt), "--compare-modes",
               "--json", str(out))
    assert "mode comparison (measured, not assumed)" in proc.stdout
    doc = json.loads(out.read_text())
    assert doc["primary"]["substantive"] == 2
    assert doc["text"]["source"] == "text"


# ---------------------------------------------------------------------------
# A checker that returns clean on no input is the failure it is auditing
# ---------------------------------------------------------------------------
def test_no_evidence_is_an_error_not_a_clean_bill(tmp_path):
    empty = tmp_path / "empty.xml"
    empty.write_text('<?xml version="1.0"?><testsuites></testsuites>\n')
    proc = cli("--junit", str(empty))
    assert proc.returncode == 2
    assert "no testcase found" in proc.stderr


def test_an_unreadable_report_is_named_not_swallowed(tmp_path):
    bad = tmp_path / "bad.xml"
    bad.write_text("this is not xml <<<")
    proc = cli("--junit", str(bad))
    assert proc.returncode == 2
    assert "unreadable" in proc.stdout


def test_advisory_mode_still_reports_the_count(tmp_path):
    xml, _ = run_pytest(tmp_path, "adv", NEW_MODULE)
    proc = cli("--junit", str(xml), "--advisory")
    assert proc.returncode == 0
    assert "TAUTOLOGICAL CONTROL" in proc.stdout


# ---------------------------------------------------------------------------
# Parser units, over strings pytest really emitted (captured above)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("expr,want", [
    ("None is not None", ("None", "is not", "None")),
    ("'0.119.62' == '1.9.79'", ("'0.119.62'", "==", "'1.9.79'")),
    ("2 == 5", ("2", "==", "5")),
    ("0 > 0", ("0", ">", "0")),
    ("'verdict=PASS' in 'gate ran: verdict=FAIL cases=3'",
     ("'verdict=PASS'", "in", "'gate ran: verdict=FAIL cases=3'")),
    ("{'a'} == {'a', 'b'}", ("{'a'}", "==", "{'a', 'b'}")),
    ("None", None),
    ("False", None),
])
def test_split_comparison(expr, want):
    assert CSC.split_comparison(expr) == want


def test_a_comparison_operator_inside_an_object_repr_is_not_split():
    """`<X object at 0x1> == <Y object at 0x2>` has three `<`/`>` that are
    not operators. Splitting on the first one would report nonsense."""
    got = CSC.split_comparison("<A object at 0x1> == <B object at 0x2>")
    assert got == ("<A object at 0x1>", "==", "<B object at 0x2>")


def test_an_operator_inside_a_string_literal_is_not_split():
    assert CSC.split_comparison("'a == b' == 'c'") == ("'a == b'", "==", "'c'")


def test_pytest_raises_that_did_not_raise_is_named_not_generic():
    got = CSC.classify_failure("Failed: DID NOT RAISE <class 'ValueError'>")
    assert got["bucket"] == CSC.UNDECIDED
    assert "pytest.raises did not raise" in got["reason"]


def test_the_exception_name_that_is_only_its_own_suffix_parses():
    """`Failed` is a class name that IS the suffix. An earlier regex required
    at least one character before it and dropped every such crash."""
    assert CSC.split_exception("Failed: x") == ("Failed", "x")
    assert CSC.split_exception("AssertionError: y") == ("AssertionError", "y")
    assert CSC.split_exception("assert 0 > 0") == (None, "assert 0 > 0")


def test_error_block_takes_the_last_E_block_and_survives_indentation():
    text = ("    def t():\n"
            ">       assert f() is not None\n"
            "E       assert None is not None\n"
            "E        +  where None = f()\n"
            "\n"
            "x.py:4: AssertionError\n")
    assert CSC.classify_failure(
        CSC.error_block(text))["bucket"] == CSC.PRESENCE_ONLY
