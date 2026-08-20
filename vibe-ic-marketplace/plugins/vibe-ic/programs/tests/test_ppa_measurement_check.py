#!/usr/bin/env python3
"""The gate's four fixtures, measured as REAL PROCESS EXIT CODES.

Every exit code here is taken from `subprocess.run(...).returncode` and not from
`main()`'s return value. The two are not the same measurement: a program whose
`main` returns 2 but whose `__main__` block calls `sys.exit()` with nothing, or
raises before it, exits 0 or 1, and the in-process test would still be green.
This repository has shipped a gate that refused with a bare `SystemExit("...")`
-- which exits 1 -- inside a program where 1 means a hard finding about
silicon, and no in-process test could have seen it.

    positive   the coverage is complete -> rc 0
    negative   an expected row is ABSENT from the set -> rc 1
    vacuous    the bundle is not there -> rc 2 WITH A MARKER, never 0, never 1
    mutation   see test_ppa_metrics_mutation.py
"""
import json
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from _ppa import metrics as M  # noqa: E402

PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
GATE = PROGRAMS / "ppa_measurement_check.py"

SCOPE_SYNTH = {"stage": "synthesis"}
SCOPE_ROUTE = {"stage": "post_route_extracted", "process": "ss",
               "voltage_v": 1.62, "temperature_c": 125}
SRC = {"path": "sta.rpt", "tool": "opensta"}

EXPECT_THREE = [
    {"metric": "area.die_um2", "scope": SCOPE_SYNTH},
    {"metric": "power.total_mw", "scope": SCOPE_ROUTE},
    {"metric": "timing.setup.wns_ns", "scope": SCOPE_ROUTE},
]


def run(*args):
    return subprocess.run([sys.executable, str(GATE), *args],
                          capture_output=True, text=True)


def write(path, obj):
    path.write_text(json.dumps(obj), encoding="utf-8")
    return str(path)


def bundle_of(tmp_path, records, expected=EXPECT_THREE, name="bundle.json"):
    idx = M.MetricIndex()
    for rec in records:
        idx.add(rec)
    return write(tmp_path / name, M.bundle(idx, expected=expected))


ALL_THREE = [
    M.measured("area.die_um2", 12000.0, "um^2", SCOPE_SYNTH, SRC),
    M.measured("power.total_mw", 3.0, "mW", SCOPE_ROUTE, SRC),
    M.measured("timing.setup.wns_ns", -0.124, "ns", SCOPE_ROUTE, SRC),
]


# ------------------------------------------------------------- 1. POSITIVE

def test_positive_a_complete_record_set_exits_zero(tmp_path):
    p = run("--coverage", bundle_of(tmp_path, ALL_THREE))
    assert p.returncode == 0, p.stderr
    assert "3 expected" in p.stdout
    assert "3 covered" in p.stdout


def test_positive_prints_every_row_including_the_ones_it_passed(tmp_path):
    p = run("--coverage", bundle_of(tmp_path, ALL_THREE))
    for row in EXPECT_THREE:
        assert row["metric"] in p.stdout


# ------------------------------------------------------------- 2. NEGATIVE

def test_negative_an_OMITTED_ROW_is_caught_and_exits_one(tmp_path):
    """THE FIXTURE THIS LANE EXISTS FOR.

    Nothing in this bundle is wrong. Two valid, sourced, in-scope measurements.
    `timing.setup.wns_ns` was owed and is simply not there, and a report of the
    two rows present would read as two facts and say nothing at all about the
    third -- which is how a coverage gap becomes an implied zero.
    """
    p = run("--coverage", bundle_of(tmp_path, ALL_THREE[:2]))
    assert p.returncode == 1, (p.returncode, p.stdout, p.stderr)
    assert "timing.setup.wns_ns" in p.stderr
    assert "NO RECORD AT ALL" in p.stdout
    assert "[REFUSE]" in p.stderr


def test_negative_the_absent_row_is_printed_not_omitted(tmp_path):
    p = run("--coverage", bundle_of(tmp_path, ALL_THREE[:2]))
    assert "[ABSENT" in p.stdout
    assert "3 expected" in p.stdout


def test_a_DECLARED_absence_is_two_and_an_OMISSION_is_one(tmp_path):
    """Same hole. One is visible to a reader and one is not, and the exit codes
    are the difference. rc 2 is not a pass either -- a run that measured two of
    three things it owed has not passed -- but it is not a finding."""
    declared = bundle_of(
        tmp_path,
        ALL_THREE[:2] + [M.not_measured("timing.setup.wns_ns",
                                        "STA did not run", SCOPE_ROUTE)],
        name="declared.json")
    omitted = bundle_of(tmp_path, ALL_THREE[:2], name="omitted.json")
    assert run("--coverage", declared).returncode == 2
    assert run("--coverage", omitted).returncode == 1


def test_a_declared_absence_says_in_words_that_it_is_not_a_pass(tmp_path):
    b = bundle_of(tmp_path,
                  ALL_THREE[:2] + [M.not_measured("timing.setup.wns_ns",
                                                  "STA did not run",
                                                  SCOPE_ROUTE)])
    p = run("--coverage", b)
    assert p.returncode == 2
    assert "not a pass" in p.stderr.lower()
    assert "STA did not run" in p.stdout


def test_negative_an_estimate_standing_in_for_a_measurement_exits_one(tmp_path):
    b = bundle_of(tmp_path,
                  ALL_THREE[:2] + [M.estimated("timing.setup.wns_ns", 0.5,
                                               "ns", SCOPE_ROUTE,
                                               basis="regression")])
    p = run("--coverage", b)
    assert p.returncode == 1
    assert "ESTIMATE" in p.stderr


def test_negative_a_measurement_at_the_wrong_scope_does_not_cover(tmp_path):
    """A post-route area is a real number and it does not answer an expectation
    of a synthesis area."""
    wrong = M.measured("area.die_um2", 15400.0, "um^2", SCOPE_ROUTE, SRC)
    b = bundle_of(tmp_path, [wrong] + ALL_THREE[1:])
    p = run("--coverage", b)
    assert p.returncode == 1
    assert "area.die_um2" in p.stderr


def test_negative_a_record_carrying_a_sentinel_is_refused(tmp_path):
    bad = M.not_measured("timing.setup.wns_ns", "STA did not run", SCOPE_ROUTE)
    bad["value"] = 0
    doc = {"schema": M.BUNDLE_SCHEMA_ID,
           "records": ALL_THREE[:2] + [bad], "expected": EXPECT_THREE}
    p = run("--coverage", write(tmp_path / "sentinel.json", doc))
    assert p.returncode == 1
    assert "VALUE_ON_A_NON_MEASUREMENT" in p.stderr


# -------------------------------------------------------------- 3. VACUOUS

def test_vacuous_a_bundle_that_is_not_there_exits_two_with_a_marker(tmp_path):
    """NOT rc 0 (nothing was checked) and NOT rc 1 (rc 1 is a claim about
    silicon, and nothing here looked at any)."""
    p = run("--coverage", str(tmp_path / "does_not_exist.json"))
    assert p.returncode == 2, (p.returncode, p.stdout, p.stderr)
    assert "[CANNOT CHECK]" in p.stderr


def test_vacuous_an_unparseable_bundle_exits_two_not_zero(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{ this is not json", encoding="utf-8")
    p = run("--coverage", str(path))
    assert p.returncode == 2
    assert "[CANNOT CHECK]" in p.stderr


def test_vacuous_a_bundle_with_no_denominator_exits_two(tmp_path):
    """A coverage report over no expectation set is not a weaker report, it is
    not one -- computed from the records alone it is 100% by construction."""
    b = bundle_of(tmp_path, ALL_THREE, expected=None)
    p = run("--coverage", b)
    assert p.returncode == 2
    assert "[CANNOT CHECK]" in p.stderr
    assert "100%" in p.stderr


def test_vacuous_an_expect_file_that_is_not_there_exits_two(tmp_path):
    """A named denominator that cannot be read is never quietly dropped back to
    the bundle's own -- that turns a coverage claim into a claim about whatever
    happened to be measured."""
    b = bundle_of(tmp_path, ALL_THREE)
    p = run("--coverage", b, "--expect", str(tmp_path / "nope.json"))
    assert p.returncode == 2
    assert "[CANNOT CHECK]" in p.stderr


def test_vacuous_an_empty_records_list_is_not_a_pass(tmp_path):
    """An empty set against a stated denominator is three ABSENT rows, which is
    the strongest finding this gate has -- not a clean run."""
    b = bundle_of(tmp_path, [])
    p = run("--coverage", b)
    assert p.returncode == 1
    assert "3" in p.stdout


def test_no_arguments_is_a_bad_invocation_not_a_pass():
    p = run()
    assert p.returncode != 0
    assert p.returncode != 1, "argparse's usage error must not read as a finding"


def test_both_modes_at_once_is_refused():
    p = run("--coverage", "x.json", "--compare", "a.json", "b.json")
    assert p.returncode != 0


# ------------------------------------------------- the comparison refusal

def _rec(tmp_path, name, rec):
    return write(tmp_path / name, rec)


def test_compare_across_differing_scope_is_UNDETERMINED_not_a_winner(tmp_path):
    """THE REFUSAL THIS LANE EXISTS FOR, at the CLI.

    Both numbers are real, both correctly recorded, and the smaller one is the
    one somebody would rather quote. Both rows say `area.die_um2`, so nothing
    downstream can see which stage produced which.
    """
    a = _rec(tmp_path, "a.json",
             M.measured("area.die_um2", 12000.0, "um^2", SCOPE_SYNTH, SRC))
    b = _rec(tmp_path, "b.json",
             M.measured("area.die_um2", 15400.0, "um^2", SCOPE_ROUTE, SRC))
    p = run("--compare", a, b, "--better", "lower")
    assert p.returncode == 2, (p.returncode, p.stdout, p.stderr)
    assert "DIFFERENT_SCOPE" in p.stdout
    assert "stage" in p.stdout
    assert "winner" not in p.stdout.lower()


def test_compare_at_the_same_scope_exits_zero(tmp_path):
    a = _rec(tmp_path, "a.json",
             M.measured("area.die_um2", 12000.0, "um^2", SCOPE_SYNTH, SRC))
    b = _rec(tmp_path, "b.json",
             M.measured("area.die_um2", 11000.0, "um^2", SCOPE_SYNTH,
                        {"path": "b.rpt", "tool": "yosys"}))
    p = run("--compare", a, b, "--better", "lower")
    assert p.returncode == 0, p.stderr
    assert "COMPARABLE" in p.stdout


def test_compare_against_a_non_measurement_is_undetermined(tmp_path):
    """Missing is not winning, and it is not losing either."""
    a = _rec(tmp_path, "a.json",
             M.measured("power.total_mw", 3.0, "mW", SCOPE_ROUTE, SRC))
    b = _rec(tmp_path, "b.json",
             M.not_measured("power.total_mw", "no VCD", SCOPE_ROUTE))
    p = run("--compare", a, b, "--better", "lower")
    assert p.returncode == 2
    assert "NOT_MEASURED" in p.stdout


def test_compare_names_no_winner_without_a_direction(tmp_path):
    a = _rec(tmp_path, "a.json",
             M.measured("timing.setup.wns_ns", -0.1, "ns", SCOPE_ROUTE, SRC))
    b = _rec(tmp_path, "b.json",
             M.measured("timing.setup.wns_ns", 0.2, "ns", SCOPE_ROUTE,
                        {"path": "b.rpt", "tool": "opensta"}))
    p = run("--compare", a, b, "--json", str(tmp_path / "r.json"))
    assert p.returncode == 0
    report = json.loads((tmp_path / "r.json").read_text())
    assert report["comparison"]["winner"] is None


def test_compare_two_different_quantities_is_a_bad_invocation(tmp_path):
    """rc 3, never a design FAIL: the caller asked a question with no answer."""
    a = _rec(tmp_path, "a.json",
             M.measured("power.total_mw", 3.0, "mW", SCOPE_ROUTE, SRC))
    b = _rec(tmp_path, "b.json",
             M.measured("area.die_um2", 12000.0, "um^2", SCOPE_ROUTE, SRC))
    p = run("--compare", a, b)
    assert p.returncode == 3
    assert "DIFFERENT_METRIC" in p.stdout


def test_compare_refuses_a_set_on_either_side(tmp_path):
    a = _rec(tmp_path, "a.json",
             M.measured("power.total_mw", 3.0, "mW", SCOPE_ROUTE, SRC))
    b = write(tmp_path / "b.json", ALL_THREE)
    p = run("--compare", a, b)
    assert p.returncode == 2
    assert "[CANNOT CHECK]" in p.stderr


# ------------------------------------------------------------ the --json arm

def test_the_json_report_is_written_even_when_the_gate_refuses(tmp_path):
    out = tmp_path / "report.json"
    p = run("--coverage", bundle_of(tmp_path, ALL_THREE[:2]),
            "--json", str(out))
    assert p.returncode == 1
    report = json.loads(out.read_text())
    assert report["rc"] == 1
    absent = [r for r in report["coverage"]["rows"] if r["outcome"] == "ABSENT"]
    assert [r["metric"] for r in absent] == ["timing.setup.wns_ns"]


def test_the_json_report_is_written_for_the_vacuous_arm_too(tmp_path):
    """A run that could not look must leave the same kind of evidence as one
    that did, or 'no report' becomes indistinguishable from 'no problem'."""
    out = tmp_path / "report.json"
    p = run("--coverage", str(tmp_path / "nope.json"), "--json", str(out))
    assert p.returncode == 2
    report = json.loads(out.read_text())
    assert report["rc"] == 2
    assert report["cannot_check"]


# --------------------------------------- PPA_INTERFACES §1: a code on every verdict

@pytest.mark.parametrize("what,expect_rc,expect_code", [
    ("complete", 0, "COVERAGE_COMPLETE"),
    ("omitted", 1, "COVERAGE_ABSENT"),
    ("declared", 2, "COVERAGE_INCOMPLETE"),
])
def test_every_coverage_verdict_carries_a_machine_readable_code(
        tmp_path, what, expect_rc, expect_code):
    """A caller must be able to tell two rc=2s apart without parsing English:
    'the bundle is not there' and 'the bundle is there and two rows are
    declared absent' are the same exit code and different problems."""
    records = {
        "complete": ALL_THREE,
        "omitted": ALL_THREE[:2],
        "declared": ALL_THREE[:2] + [M.not_measured(
            "timing.setup.wns_ns", "STA did not run", SCOPE_ROUTE)],
    }[what]
    out = tmp_path / "r.json"
    p = run("--coverage", bundle_of(tmp_path, records), "--json", str(out))
    assert p.returncode == expect_rc, (p.stdout, p.stderr)
    assert json.loads(out.read_text())["code"] == expect_code


def test_the_vacuous_arm_distinguishes_its_two_reasons(tmp_path):
    absent = tmp_path / "a.json"
    p = run("--coverage", str(tmp_path / "nope.json"), "--json", str(absent))
    assert p.returncode == 2
    assert json.loads(absent.read_text())["code"] == "INPUT_ABSENT"

    nodenom = tmp_path / "b.json"
    p = run("--coverage", bundle_of(tmp_path, ALL_THREE, expected=None),
            "--json", str(nodenom))
    assert p.returncode == 2
    assert json.loads(nodenom.read_text())["code"] == "NO_EXPECTATION_SET"


def test_the_compare_verdict_code_is_on_the_report(tmp_path):
    a = _rec(tmp_path, "a.json",
             M.measured("area.die_um2", 12000.0, "um^2", SCOPE_SYNTH, SRC))
    b = _rec(tmp_path, "b.json",
             M.measured("area.die_um2", 15400.0, "um^2", SCOPE_ROUTE, SRC))
    out = tmp_path / "r.json"
    p = run("--compare", a, b, "--json", str(out))
    assert p.returncode == 2
    assert json.loads(out.read_text())["code"] == "DIFFERENT_SCOPE"
