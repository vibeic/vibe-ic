"""test_p0_failed_gate_names_preserved.py — the audit JSON must keep the
NAMES of every failing P0 sub-gate, no matter how many failed.

THE DEFECT THIS PINS DOWN
-------------------------
The P0 umbrella emitted its failing sub-gates in one of two shapes, chosen
purely by HOW MANY gates failed:

    exactly 1 failure   ->  "FAIL: <gate> — <msg>"                  (Form 1)
    2 or more failures  ->  "Failed gates (N):"
                            "  - <gate> — <msg>"                    (Form 2)

`flow_compliance_check.main()` built the machine-readable audit artifact
`reports/audit/phase23_completion_audit.json` by SCRAPING that prose, with
matchers that recognised Form 1 ONLY. So `failed_gates` / `failed_gate_count` /
`gates` came out EMPTY exactly when two or more gates failed — the list went
blank precisely when it had the most to report, while a single-failure run
reported fine.

Measured end-to-end on a real run dir, plugin 1.5.85 and plugin 1.6.4 (the
two files are byte-identical in this region, so this is NOT a version
regression — the variable is the failure COUNT):

    2 failing gates -> "failed_gates": []
    1 failing gate  -> "failed_gates": ["provenance_output_hash_completeness_check"]

This matters because that artifact is, by its own comment at the write site,
"the contract the mcp-eda pre-burn guard now consumes (replacing the brittle
stdout regex parser that produced 0 failed_gates from 14 real FAILs)". The
replacement reintroduced the very failure mode it was written to eliminate.

WHAT #497 CHANGED, AND WHY THIS FILE LOOKS DIFFERENT
----------------------------------------------------
The first fix taught the scraper the second shape — a third grammar rule rather
than one less grammar. #497 removed the mechanism: the audit's `gates` and
`failed_gates` are now PROJECTED from the umbrella's typed `gate_records`
(`_p0_audit_gate_records`, `_p0_failing_gate_names`), and the prose is rendered
from those same records. There is no parser left to test, so the tests below
pin the INVARIANT rather than the parser: the machine-readable name set must
depend on which gates failed and on nothing else — in particular not on the
failure COUNT, which is the variable that emptied it.

Two assertions did not survive, and their absence is deliberate:
`PASS: <gate>` lines and bare `<name>_check — msg` lines. Both were shapes the
scraper accepted and the umbrella has NEVER emitted — a passing gate produces
no reason line at all, which is exactly why `passed_gate_count` read 0 for the
artifact's entire history. Their replacement is
`test_the_passing_population_is_named_by_the_records_alone`: the count now
comes from the records, so it is right without any line existing to parse.

BIDIRECTIONAL
-------------
The count-sweep tests fail if the name set ever depends on the shape; the
end-to-end tests fail if the artifact and the umbrella disagree; and the guard
tests fail if the projection became permissive enough to invent a name.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]


def _load():
    """Import flow_compliance_check by path (programs/ is not a package)."""
    mod_name = "_fcc_under_test"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(
        mod_name, _PROGRAMS / "flow_compliance_check.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


fcc = _load()


# --------------------------------------------------------------------------
# The two real shapes, produced by the real composer from real records.
# --------------------------------------------------------------------------
def _fail(name, msg):
    return fcc._p0_gate_record(name, "FAIL", msg, {"exit_code": 1})


ONE_FAILURE = [
    _fail("provenance_output_hash_completeness_check",
          "FAIL: 1 provenance fault(s):"),
]

TWO_FAILURES = [
    _fail("project_outputs_in_tree_check",
          "[FAIL] project_outputs_in_tree_check: 1 live external-storage "
          "artifact(s)"),
    _fail("provenance_output_hash_completeness_check",
          "FAIL: 1 provenance fault(s):"),
]

FOUR_FAILURES = [
    _fail("l1_pin_bus_width_actionable_check",
          "FAIL: 1/1 bus-confirmed pin(s) carry no width phase2 can emit a "
          "port declaration from."),
    _fail("l22_verification_plan_measurable_check",
          "[FAIL] TARGET_OUTSIDE_CONSUMING_LAYER"),
    _fail("project_outputs_in_tree_check",
          "[FAIL] 7 live external-storage artifact(s)"),
    _fail("provenance_output_hash_completeness_check",
          "FAIL: 1 provenance fault(s):"),
]


def _fail_names(records):
    return [g["name"] for g in fcc._p0_audit_gate_records(records)
            if g["verdict"] == "FAIL"]


def _reasons(records):
    """The operator prose the umbrella really emits for these records."""
    return fcc._compose_p0_reasons_from_records(
        records, not any(r["verdict"] == "FAIL" for r in records))


# --------------------------------------------------------------------------
# DEFECT DIRECTION — these are the assertions that go red without the fix.
# --------------------------------------------------------------------------

def test_form2_two_failures_keeps_both_names():
    """The measured defect: 2 failures -> the list was empty."""
    assert _reasons(TWO_FAILURES)[0] == "Failed gates (2):", (
        "premise: two failures must reach the shape that emptied the list")
    assert _fail_names(TWO_FAILURES) == [
        "project_outputs_in_tree_check",
        "provenance_output_hash_completeness_check",
    ]


def test_form2_four_failures_keeps_all_four_names():
    assert _fail_names(FOUR_FAILURES) == [
        "l1_pin_bus_width_actionable_check",
        "l22_verification_plan_measurable_check",
        "project_outputs_in_tree_check",
        "provenance_output_hash_completeness_check",
    ]


def test_form2_never_yields_an_empty_list_when_gates_failed():
    """The invariant that the whole verification discipline rests on:
    a FAILing P0 must never hand downstream an empty NAME SET."""
    for records in (TWO_FAILURES, FOUR_FAILURES):
        assert _fail_names(records), (
            "empty failed-gate name set for a P0 that reported failures")


def test_form2_header_is_not_mistaken_for_a_gate():
    """`Failed gates (4):` is a header, not a gate. It must not appear as
    a name, and must not be silently counted as a passing gate either."""
    names = [g["name"] for g in fcc._p0_audit_gate_records(FOUR_FAILURES)]
    assert not any("Failed" in n for n in names), names
    assert len(names) == 4, names
    assert _reasons(FOUR_FAILURES)[0] == "Failed gates (4):"


def test_form2_messages_survive_not_just_names():
    per = fcc._p0_audit_gate_records(TWO_FAILURES)
    by_name = {g["name"]: g["message"] for g in per}
    assert "provenance fault" in \
        by_name["provenance_output_hash_completeness_check"]


# --------------------------------------------------------------------------
# NO-REGRESSION DIRECTION — Form 1 already worked and must keep working.
# --------------------------------------------------------------------------

def test_form1_single_failure_still_reported():
    assert _reasons(ONE_FAILURE) == [
        "FAIL: provenance_output_hash_completeness_check — FAIL: 1 "
        "provenance fault(s):"], "premise: one failure reaches Form 1"
    assert _fail_names(ONE_FAILURE) == [
        "provenance_output_hash_completeness_check"]


def test_the_passing_population_is_named_by_the_records_alone():
    """Replaces the old `PASS: <gate>` assertion.

    The scraper accepted a `PASS: <gate>` line; the umbrella has never emitted
    one, because a passing gate contributes no reason at all. The count now
    comes from the records, so it is right with no line to parse — and the
    prose still names nobody.
    """
    records = ONE_FAILURE + [
        fcc._p0_gate_record("testbench_exists_check", "PASS", "",
                            {"exit_code": 0})]
    assert fcc._p0_passed_count(records) == 1
    assert _fail_names(records) == [
        "provenance_output_hash_completeness_check"]
    assert not any("testbench_exists_check" in line
                   for line in _reasons(records))


def test_empty_and_absent_records_are_safe():
    assert fcc._p0_audit_gate_records([]) == []
    assert fcc._p0_gate_records(None) == []
    assert fcc._p0_failing_gate_names([]) == []


# --------------------------------------------------------------------------
# The COUNT is the only variable — this is the factorial, as a test.
# --------------------------------------------------------------------------

def test_same_gate_reported_identically_in_both_shapes():
    """One gate, two shapes, one answer. If the name set depends on which
    shape the umbrella happened to choose, the bug is back."""
    one = _fail_names([_fail("provenance_output_hash_completeness_check",
                             "1 fault")])
    two = _fail_names([_fail("provenance_output_hash_completeness_check",
                             "1 fault"),
                       _fail("project_outputs_in_tree_check",
                             "1 live artifact")])
    assert one[0] in two
    assert set(one).issubset(set(two))


@pytest.mark.parametrize("n", [1, 2, 3, 5, 12])
def test_name_set_size_tracks_failure_count(n):
    """14 real FAILs producing 0 names is the historical incident this
    artifact was created to end. Scale it, and include n=1 so the sweep
    crosses the shape boundary rather than staying on one side of it."""
    records = [_fail(f"gate_{i}_check", "[FAIL] synthetic") for i in range(n)]
    got = _fail_names(records)
    assert len(got) == n, f"expected {n} names, got {len(got)}: {got}"
    # the prose shape really does flip at 2, so the sweep is not vacuous
    assert (_reasons(records)[0].startswith("Failed gates")) == (n >= 2)


# --------------------------------------------------------------------------
# END TO END — the artifact main() actually writes.
# --------------------------------------------------------------------------

def _run_main(tmp_path, monkeypatch, records):
    proj = tmp_path / "proj"
    (proj / "rtl").mkdir(parents=True)
    (proj / "rtl" / "top.v").write_text(
        "module top(input a, output b); assign b = a; endmodule\n")

    def _stub(_project, **kw):
        out = kw.get("records_out")
        if out is not None:
            out.extend(records)
        return (not any(r["verdict"] == "FAIL" for r in records),
                *fcc._p0_buckets_from_records(records))

    monkeypatch.setattr(fcc, "_run_structural_rtl_gates", _stub)
    report = tmp_path / "report.json"
    fcc.main([str(proj), "--json", str(report),
              "--phase", "2", "--strict-structural"])
    return json.loads(
        (proj / "reports" / "audit" /
         "phase23_completion_audit.json").read_text())


@pytest.mark.parametrize("n", [1, 2, 4])
def test_end_to_end_the_artifact_names_every_failing_gate(
        n, tmp_path, monkeypatch, capsys):
    """The measurement that found the defect, as a test: run it, read the
    artifact, count the names — at a failure count on each side of the shape
    boundary."""
    records = [_fail(f"gate_{i}_check", "[FAIL] synthetic") for i in range(n)]
    audit = _run_main(tmp_path, monkeypatch, records)
    capsys.readouterr()
    assert audit["failed_gates"] == [f"gate_{i}_check" for i in range(n)]
    assert audit["failed_gate_count"] == n
    assert [g["name"] for g in audit["gates"]] == audit["failed_gates"]
    assert audit["structural_fail_lines"] == [
        f"gate_{i}_check — [FAIL] synthetic" for i in range(n)]


#: Registered gates whose names do NOT end in `_check`. 15 of the 241 at the
#: time of writing, taken from the live registry so the test stays coupled to
#: shipped policy rather than to a transcription of it.
_NON_CHECK_GATES = [g for g in fcc._STRUCTURAL_RTL_GATES
                    if not g.endswith("_check")]


def test_premise_the_registry_contains_gates_not_named_check():
    """If this ever empties, the test below is vacuous — say so out loud."""
    assert _NON_CHECK_GATES, (
        "every registered gate now ends in `_check`; the name-shape hazard "
        "below is moot and the test guarding it is testing nothing")


@pytest.mark.parametrize("gate", _NON_CHECK_GATES[:3])
def test_end_to_end_a_failing_gate_not_named_check_is_still_reported(
        gate, tmp_path, monkeypatch, capsys):
    """The name-shape hazard, pinned.

    The audit writer used to reconcile `failed_gates` against a
    `^([\\w.]+_check)\\b` match over each `structural_fail_lines` entry. It was
    dead code — the pass above it had already added every failing name — but it
    encoded an assumption the registry does not honour: 15 registered gates are
    named `..._audit`, `..._gate`, `..._warn`, `..._present`, `..._lint`. Had
    that scrape ever been the only source, every one of them would have failed
    silently, unnamed in the artifact the pre-burn guard consumes.

    Nothing derives a gate name from its spelling any more. This is the test
    that says so.
    """
    records = [_fail(gate, "[FAIL] a real defect in a gate not named _check")]
    audit = _run_main(tmp_path, monkeypatch, records)
    capsys.readouterr()
    assert audit["failed_gates"] == [gate]
    assert audit["failed_gate_count"] == 1
    assert [g["name"] for g in audit["gates"]] == [gate]
    assert audit["structural_fail_lines"] == [
        f"{gate} — [FAIL] a real defect in a gate not named _check"]


def test_end_to_end_the_artifact_and_the_umbrella_cannot_disagree(
        tmp_path, monkeypatch, capsys):
    """The old backstop reconciled two independent parsers of one prose list,
    because they had already disagreed once. Both sides are now the same
    projection of the same records, which is the stronger statement."""
    records = FOUR_FAILURES + [
        fcc._p0_gate_record("clean_check", "PASS", "", {"exit_code": 0}),
        fcc._p0_gate_record("quiet_check", "SKIP", "", {"exit_code": 2,
                                                        "skip_kind":
                                                        "input-missing"})]
    audit = _run_main(tmp_path, monkeypatch, records)
    capsys.readouterr()
    assert audit["failed_gates"] == fcc._p0_failing_gate_names(records)
    assert audit["gates"] == fcc._p0_audit_gate_records(records)
    assert audit["passed_gate_count"] == 1
    assert "clean_check" not in json.dumps(audit["failed_gates"])
    assert "quiet_check" not in json.dumps(audit["failed_gates"])
