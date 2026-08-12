"""A count is only comparable over the population it was taken over (vibe-ic#1015).

TWO DEFECTS, BOTH IN THE SAME RATCHET
=====================================
#1015 records that sixteen published runs carry a real unacknowledged
step-internal failure, and calls this gate "the only thing that can see them".
Measured on v1.10.33 (`94754771`), it could not see most of them:

    population selected by NAME (`clean_run_*`)   13 swept,  3 with reports/, 5
    + structural `<design>/<run>` run roots        18 swept,  8 with reports/, 8

The published corpus names run roots BOTH ways — `clean_run_<ver>` and
`<version>_<pdk>` — and only the first was ever swept. Two published run roots
carrying three unacknowledged FAILs had never been looked at, and three others
had never been confirmed clean over 92/67/88 examined reports. #1025 fixed the
DEPTH of this glob and said in its own words that it "does not widen" the name
pattern; this is the rest of that same defect.

The second is worse, because it points a reader the wrong way. The ratchet
compared `findings_total` against a recorded integer and recorded no
denominator. The published corpus SHRINKS when a cell is retired, so the count
falls for a reason that is not repair — and the gate printed

    [PASS] 7 -> 5; lower the baseline so the recorded number stops claiming
                   debt that is paid.

over runs that had been withdrawn, one of which the baseline still names and
which is not on disk at all. #1015 is a question about what to DO with those
runs; being told their debt was "paid" is the opposite of the answer.

Every fixture here is synthesised. No design, PDK or vendor name appears.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import step_internal_fail_bubble_up_check as G  # noqa: E402


def _run(root: Path, name: str, *, verdict: str = "FAIL") -> Path:
    """A published run tree carrying one unacknowledged verdict=FAIL report."""
    r = root / name
    (r / "reports" / "phase3").mkdir(parents=True)
    (r / "reports" / "phase3" / "some_signoff.json").write_text(
        json.dumps({"gate": "some_signoff", "verdict": verdict}) + "\n")
    return r


def _corpus(tmp_path: Path) -> Path:
    """`<corpus>/<design>/<run>` — the shape the published tree actually has."""
    c = tmp_path / "ic"
    (c / "designa").mkdir(parents=True)
    return c


# --------------------------------------------------------------------------
# DEFECT 1 — the population was selected by NAME
# --------------------------------------------------------------------------

def test_a_run_root_not_named_clean_run_is_still_swept(tmp_path):
    """THE CONTROL. Fails against the pre-fix module, which globs `clean_run_*`
    and therefore never sees a run root published as `<version>_<process>`."""
    c = _corpus(tmp_path)
    _run(c / "designa", "clean_run_v1")
    _run(c / "designa", "v9.9.9_procx")

    swept = {p.name for p in G._published_run_trees(c)}
    assert "clean_run_v1" in swept, swept
    assert "v9.9.9_procx" in swept, (
        "a published run root is not swept because of how it is NAMED — "
        f"population was {swept}")


def test_both_naming_shapes_are_counted_in_the_corpus_total(tmp_path):
    c = _corpus(tmp_path)
    _run(c / "designa", "clean_run_v1")
    _run(c / "designa", "v9.9.9_procx")

    rep = G.check_corpus(c)
    assert rep["runs_with_reports"] == 2, rep
    assert rep["findings_total"] == 2, rep
    assert set(rep["per_run"]) == {"designa/clean_run_v1",
                                   "designa/v9.9.9_procx"}, rep


def test_widening_never_drops_a_run_the_old_population_had(tmp_path):
    """The union is a union. A `clean_run_*` tree with no reports/ was swept
    before and must still be swept, or the fix trades one blindness for another."""
    c = _corpus(tmp_path)
    (c / "designa" / "clean_run_bare").mkdir(parents=True)   # no reports/
    _run(c / "designa", "v9.9.9_procx")

    swept = {p.name for p in G._published_run_trees(c)}
    assert "clean_run_bare" in swept, swept


def test_flow_phase_directories_are_not_counted_as_runs(tmp_path):
    """A stage INSIDE a run is not a run. Including them would pad the
    denominator with directories that examine nothing."""
    c = _corpus(tmp_path)
    (c / "designa" / "phase3" / "reports").mkdir(parents=True)
    _run(c / "designa", "v9.9.9_procx")

    swept = {p.name for p in G._published_run_trees(c)}
    assert "phase3" not in swept, swept
    assert "v9.9.9_procx" in swept, swept


# --------------------------------------------------------------------------
# DEFECT 2 — the count carried no denominator
# --------------------------------------------------------------------------

def _baseline(p: Path, *, total: int, swept: int, with_reports: int,
              per_run: dict) -> Path:
    p.write_text(json.dumps({"_comment": "t", "findings_total": total,
                             "runs_swept": swept,
                             "runs_with_reports": with_reports,
                             "per_run": per_run}, indent=1) + "\n")
    return p


def test_a_baselined_run_that_left_the_corpus_is_named(tmp_path):
    """It cannot ever be paid down, and its disappearance reads as progress."""
    c = _corpus(tmp_path)
    _run(c / "designa", "v9.9.9_procx")
    bl = _baseline(tmp_path / "b.json", total=4, swept=2, with_reports=2,
                   per_run={"designa/v9.9.9_procx": 1, "designa/retired": 3})

    gone = G.baselined_runs_missing(c, bl)
    assert gone == ["designa/retired"], gone


def test_a_baseline_with_no_recorded_population_is_not_assumed_equal(tmp_path):
    """"I do not know what it was measured over" must not read as "the same"."""
    bl = tmp_path / "b.json"
    bl.write_text(json.dumps({"findings_total": 5}) + "\n")
    assert G._load_baseline_population(bl) is None
    assert G._load_baseline(bl) == 5


def test_the_population_is_recorded_alongside_the_count(tmp_path):
    bl = _baseline(tmp_path / "b.json", total=8, swept=18, with_reports=8,
                   per_run={})
    assert G._load_baseline_population(bl) == {"runs_swept": 18,
                                               "runs_with_reports": 8}


def test_a_fall_under_a_SHRUNKEN_population_is_not_called_debt_paid(
        tmp_path, capsys):
    """The sentence that pointed a reader the wrong way.

    Two runs baselined at 4 findings; one is retired. The count falls to 1 and
    the gate must NOT say the debt was paid — nothing was acknowledged.
    """
    c = _corpus(tmp_path)
    _run(c / "designa", "v9.9.9_procx")
    bl = _baseline(tmp_path / "b.json", total=4, swept=2, with_reports=2,
                   per_run={"designa/v9.9.9_procx": 1, "designa/retired": 3})

    rc = G.main(["--corpus", str(c), "--baseline", str(bl)])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "POPULATION" in out, out
    assert "designa/retired" in out, out
    assert "NOT as debt paid" in out, out
    assert "stops claiming debt that is paid" not in out, out


def test_a_fall_with_a_STABLE_population_is_still_credited(tmp_path, capsys):
    """PAIRED with the test above, which is the only thing that makes it mean
    anything: the credit must still be given when it is genuinely earned."""
    c = _corpus(tmp_path)
    _run(c / "designa", "v9.9.9_procx")
    bl = _baseline(tmp_path / "b.json", total=5, swept=1, with_reports=1,
                   per_run={"designa/v9.9.9_procx": 5})

    rc = G.main(["--corpus", str(c), "--baseline", str(bl)])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "stops claiming debt that is paid" in out, out
    assert "NOT as debt paid" not in out, out


def test_growth_still_FAILS(tmp_path, capsys):
    """The ratchet must not have been softened by any of the above."""
    c = _corpus(tmp_path)
    _run(c / "designa", "clean_run_v1")
    _run(c / "designa", "v9.9.9_procx")
    bl = _baseline(tmp_path / "b.json", total=1, swept=2, with_reports=2,
                   per_run={"designa/clean_run_v1": 1})

    rc = G.main(["--corpus", str(c), "--baseline", str(bl)])
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "GREW" in out or "GREW" in capsys.readouterr().err, out


# --------------------------------------------------------------------------
# The shipped baseline must describe a population that exists.
# --------------------------------------------------------------------------

def test_the_shipped_baseline_names_only_runs_that_exist():
    """Driven by the REAL in-repo artefact, not a fixture authored alongside
    the fix. Hardcodes no design name — the corpus root comes from _hostpaths.
    """
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
    pop = G._load_baseline_population(bl)
    assert pop is not None, (
        "the shipped baseline records a count with no denominator, so a fall "
        "under a shrinking corpus cannot be told from debt being paid")
