"""A count is only comparable over the population it was taken over (vibe-ic#1015/#1025).

THE DEFECT
==========
`step_internal_fail_bubble_up_check --corpus` ratchets `findings_total` against
a recorded integer and recorded NO DENOMINATOR. Its population is the published
corpus, which SHRINKS whenever a cell is retired, so the count falls for a
reason that is not acknowledgement. Measured on v1.10.33, the gate printed

    [PASS] 7 -> 5; lower the baseline so the recorded number stops claiming
                   debt that is paid.

while one of the four runs the baseline named — `u_hawaii_adc/clean_run_v1427_20260715` —
was not on disk at all. #1015 asks what to DO about the runs that carry a real
unacknowledged failure; being told their debt was "paid" is the opposite of the
answer, and #1025 records the same baseline naming runs that no longer exist.

WHAT THIS DOES NOT DO
=====================
It does not widen the population. A widening to the corpus's own admissibility
rule ("carries provenance.jsonl or reports/orchestrator/") was implemented,
measured and WITHDRAWN before landing: it takes findings 5 -> 21 under
`benchmark-data/ic` and 5 -> 37 under `benchmark-data`, and it makes BOTH
`ic/<design>` and `ic/<design>/<version>` admissible, so a nested run root
double-counts the same artefacts. Replacing one wrong population with another
silently is not a repair; that question is filed separately.

Every fixture here is synthesised. No design, PDK or vendor name appears.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import step_internal_fail_bubble_up_check as G  # noqa: E402


def _run(root: Path, name: str) -> Path:
    """A swept run tree carrying one unacknowledged verdict=FAIL report.

    Named `clean_run_*` because that is the population the gate sweeps; these
    tests are about the DENOMINATOR, not about widening the population.
    """
    r = root / name
    (r / "reports" / "phase3").mkdir(parents=True)
    (r / "reports" / "phase3" / "some_signoff.json").write_text(
        json.dumps({"gate": "some_signoff", "verdict": "FAIL"}) + "\n")
    return r


def _corpus(tmp_path: Path) -> Path:
    c = tmp_path / "ic"
    (c / "designa").mkdir(parents=True)
    return c


def _baseline(p: Path, *, total: int, swept: int, with_reports: int,
              per_run: dict) -> Path:
    p.write_text(json.dumps({"_comment": "t", "findings_total": total,
                             "runs_swept": swept,
                             "runs_with_reports": with_reports,
                             "per_run": per_run}, indent=1) + "\n")
    return p


# --------------------------------------------------------------------------
# The denominator travels with the number
# --------------------------------------------------------------------------

def test_a_baselined_run_that_left_the_corpus_is_named(tmp_path):
    """It can never be paid down, and its disappearance reads as progress."""
    c = _corpus(tmp_path)
    _run(c / "designa", "clean_run_v1")
    bl = _baseline(tmp_path / "b.json", total=4, swept=2, with_reports=2,
                   per_run={"designa/clean_run_v1": 1, "designa/retired": 3})

    assert G.baselined_runs_missing(c, bl) == ["designa/retired"]


def test_a_baseline_with_no_recorded_population_is_not_assumed_equal(tmp_path):
    """"I do not know what it was measured over" must not read as "the same"."""
    bl = tmp_path / "b.json"
    bl.write_text(json.dumps({"findings_total": 5}) + "\n")
    assert G._load_baseline_population(bl) is None
    assert G._load_baseline(bl) == 5


def test_the_population_is_recorded_alongside_the_count(tmp_path):
    bl = _baseline(tmp_path / "b.json", total=5, swept=13, with_reports=3,
                   per_run={})
    assert G._load_baseline_population(bl) == {"runs_swept": 13,
                                               "runs_with_reports": 3}


def test_a_fall_under_a_SHRUNKEN_population_is_not_called_debt_paid(
        tmp_path, capsys):
    """THE SENTENCE THAT POINTED A READER THE WRONG WAY.

    Two runs baselined at 4 findings; one is retired. The count falls to 1 and
    the gate must NOT say the debt was paid — nothing was acknowledged.
    """
    c = _corpus(tmp_path)
    _run(c / "designa", "clean_run_v1")
    bl = _baseline(tmp_path / "b.json", total=4, swept=2, with_reports=2,
                   per_run={"designa/clean_run_v1": 1, "designa/retired": 3})

    rc = G.main(["--corpus", str(c), "--baseline", str(bl)])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "POPULATION" in out, out
    assert "designa/retired" in out, out
    assert "NOT as debt paid" in out, out
    assert "stops claiming debt that is paid" not in out, out


def test_a_fall_with_a_STABLE_population_is_still_credited(tmp_path, capsys):
    """PAIRED with the test above, and the only thing that makes it mean
    anything: the credit must still be given when it is genuinely earned."""
    c = _corpus(tmp_path)
    _run(c / "designa", "clean_run_v1")
    bl = _baseline(tmp_path / "b.json", total=5, swept=1, with_reports=1,
                   per_run={"designa/clean_run_v1": 5})

    rc = G.main(["--corpus", str(c), "--baseline", str(bl)])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "stops claiming debt that is paid" in out, out
    assert "NOT as debt paid" not in out, out


def test_growth_still_FAILS(tmp_path, capsys):
    """The ratchet must not have been softened by any of the above."""
    c = _corpus(tmp_path)
    _run(c / "designa", "clean_run_v1")
    _run(c / "designa", "clean_run_v2")
    bl = _baseline(tmp_path / "b.json", total=1, swept=2, with_reports=2,
                   per_run={"designa/clean_run_v1": 1})

    rc = G.main(["--corpus", str(c), "--baseline", str(bl)])
    assert rc == 1, capsys.readouterr().out


# --------------------------------------------------------------------------
# The population must not depend on how the caller spelled the path (#1025)
# --------------------------------------------------------------------------

def test_the_swept_population_is_the_same_at_either_depth(tmp_path):
    """#1025's own words: the answer must not depend on how many path
    components the caller happened to type.

    This is the property a first version of the widening BROKE — `glob("*/*")`
    matched `<design>/<run>` from one root and `<tree>/<design>` from its
    parent, so the same repository answered 8 findings or 19 depending on the
    argument. Asserted here so the next widening cannot reintroduce it.
    """
    top = tmp_path / "corpus"
    c = top / "ic"
    (c / "designa").mkdir(parents=True)
    _run(c / "designa", "clean_run_v1")

    from_parent = {p.resolve() for p in G._published_run_trees(top)}
    from_child = {p.resolve() for p in G._published_run_trees(c)}
    assert from_child, "the child root swept nothing — fixture is wrong"
    assert from_child <= from_parent, (
        f"sweeping the parent lost run trees the child found: "
        f"{sorted(from_child - from_parent)}")
    assert from_parent == from_child, (
        f"the population depends on the caller's path depth: parent-only "
        f"{sorted(from_parent - from_child)}")


# --------------------------------------------------------------------------
# The shipped baseline, driven by the REAL in-repo artefact
# --------------------------------------------------------------------------

def test_the_shipped_baseline_names_only_runs_that_exist():
    from _hostpaths import repo_path
    corpus = repo_path("benchmark-data", "ic")
    if not corpus.is_dir():
        pytest.skip(f"no published corpus at {corpus}")
    bl = _PROGRAMS / "step_internal_fail_bubble_up_baseline.json"
    if not bl.is_file():
        pytest.skip("no shipped baseline")

    gone = G.baselined_runs_missing(corpus, bl)
    assert gone == [], (
        "the shipped baseline names run(s) that are not on disk; their findings "
        f"can never be paid down and their loss reads as progress: {gone}")


def test_the_shipped_baseline_records_its_population():
    bl = _PROGRAMS / "step_internal_fail_bubble_up_baseline.json"
    if not bl.is_file():
        pytest.skip("no shipped baseline")
    assert G._load_baseline_population(bl) is not None, (
        "the shipped baseline records a count with no denominator, so a fall "
        "under a shrinking corpus cannot be told from debt being paid")
