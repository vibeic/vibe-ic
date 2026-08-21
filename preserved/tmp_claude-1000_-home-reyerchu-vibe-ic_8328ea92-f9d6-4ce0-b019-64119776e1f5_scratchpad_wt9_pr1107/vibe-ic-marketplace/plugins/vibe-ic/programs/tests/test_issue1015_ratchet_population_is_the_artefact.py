"""vibe-ic#1015 — the ratchet held a line over 3 of 117 published run trees.

`step_internal_fail_bubble_up_check --corpus` is the instrument that stops the
#1015 population growing while the owner decides what happens to the published
runs that are not clean. It recognised a run tree by its directory being NAMED
`clean_run_*`. A run's name is not what makes it published evidence — the
tracked `reports/` tree under it is.

MEASURED on 4b22e36e over `benchmark-data`:

    tracked run dirs carrying reports/**/*.json : 117
      matching clean_run_*  (the old population):   3
      NOT matching          (invisible to it)   : 114

    PROJECT mode over all 117, the same audit one dir at a time:
      RED (rc 1)            : 24 run dirs, 45 findings
        inside  clean_run_* :  2 run dirs,  5 findings   <- all the ratchet saw
        outside clean_run_* : 22 run dirs, 40 findings   <- ratcheted by nothing

TWO-ARM CONTROL, run on the real corpus before this file was written. A new
unacknowledged FAIL was added to `ic/spm/v1.10.18_sky130A` (a published tree not
named `clean_run_*`) and the SAME stimulus was put to both checkers:

    green (this branch) -> rc 1   "GREW 22 -> 23"
    red   (origin/main) -> rc 0   "[PASS] 7 -> 5"

The red arm does not merely miss it: it reports the number SHRINKING, so the run
that introduced a real failure reads as one that paid debt off.

The fixtures below build throwaway git repositories rather than leaning on the
shipped corpus, so they keep discriminating when the corpus changes. Two tests
at the end DO read the shipped baseline, because a baseline that has drifted
from the tree is the one thing a fixture can never notice.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_REPO = _PROGRAMS.parents[3]
_CHECK = _PROGRAMS / "step_internal_fail_bubble_up_check.py"
_BASELINE = _PROGRAMS / "step_internal_fail_bubble_up_baseline.json"


def _load():
    spec = importlib.util.spec_from_file_location("sifbu", _CHECK)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["sifbu"] = mod
    spec.loader.exec_module(mod)
    return mod


M = _load()


# --------------------------------------------------------------------------
# fixture: a throwaway repository whose published run trees are REAL git
# objects, because the population predicate is "what git tracks".
# --------------------------------------------------------------------------
def _repo(tmp_path: Path, runs) -> Path:
    """`runs` = {run_rel_dir: {report_rel_path: verdict_or_None}}."""
    root = tmp_path / "repo"
    (root / "benchmark-data").mkdir(parents=True)
    for run, reports in runs.items():
        for rel, verdict in reports.items():
            p = root / run / "reports" / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            body = {"verdict": verdict} if verdict else {"note": "no verdict"}
            p.write_text(json.dumps(body) + "\n")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "corpus"], cwd=root, check=True)
    return root


def _sweep(root: Path, sub: str = "benchmark-data", *extra: str):
    proc = subprocess.run(
        [sys.executable, str(_CHECK), "--corpus", str(root / sub), *extra],
        capture_output=True, text=True, cwd=str(root), timeout=60)
    return proc.returncode, proc.stdout + proc.stderr


# ==========================================================================
# 1. THE POPULATION IS THE ARTEFACT, NOT THE NAME
# ==========================================================================
_NAMED = "benchmark-data/ic/sha256/clean_run_v1_20260101"
_UNNAMED = "benchmark-data/ic/spm/v1.10.18_sky130A"


def test_a_published_run_tree_not_named_clean_run_is_in_the_population(tmp_path):
    """The whole of #1015's gap, at its smallest.

    Both trees are tracked, both carry `reports/`, and only one is named
    `clean_run_*`. Before this change the other was not in the population at
    all — 114 of 117 published run dirs were in that state.
    """
    root = _repo(tmp_path, {
        _NAMED:   {"phase3/a.json": "PASS"},
        _UNNAMED: {"phase3/b.json": "PASS"},
    })
    found = {p.relative_to(root).as_posix()
             for p in M._published_run_trees(root / "benchmark-data")}
    assert _NAMED in found and _UNNAMED in found, (
        "a published run tree carrying a tracked reports/ was excluded from "
        f"the ratchet's population because of its NAME: {sorted(found)}")


def test_the_old_name_pattern_is_what_this_replaces(tmp_path):
    """PAIRED GUARD — an always-fires mutant must kill the test above.

    Restoring the old `clean_run_*` predicate must make the assertion fail. A
    test that passes under both predicates would be measuring nothing, which is
    exactly how the gap survived #1025: that commit touched this function and
    said in its own comment that it "does not widen" the name.
    """
    root = _repo(tmp_path, {
        _NAMED:   {"phase3/a.json": "PASS"},
        _UNNAMED: {"phase3/b.json": "PASS"},
    })
    corpus = root / "benchmark-data"
    old = sorted(p.relative_to(root).as_posix()
                 for p in corpus.rglob("clean_run_*") if p.is_dir())
    new = sorted(p.relative_to(root).as_posix()
                 for p in M._published_run_trees(corpus))
    assert _UNNAMED not in old, (
        "the mutant does not fire — the old predicate already saw the unnamed "
        "tree, so the test above proves nothing")
    assert _UNNAMED in new and set(old) < set(new), (
        f"the new predicate is not strictly wider than the old one: "
        f"old={old} new={new}")


def test_a_tree_with_no_tracked_reports_is_not_in_the_population(tmp_path):
    """The other side: the predicate is `reports/`, not "any directory".

    Without this, "widen the population" could be satisfied by returning
    everything, and the sweep would spend its time on trees there is nothing
    to read in.
    """
    root = _repo(tmp_path, {_UNNAMED: {"phase3/b.json": "PASS"}})
    (root / "benchmark-data" / "ic" / "notes").mkdir(parents=True)
    (root / "benchmark-data" / "ic" / "notes" / "README.md").write_text("x\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "notes"], cwd=root, check=True)
    found = {p.relative_to(root).as_posix()
             for p in M._published_run_trees(root / "benchmark-data")}
    assert found == {_UNNAMED}, found


def test_an_untracked_run_tree_is_still_excluded(tmp_path):
    """#1025's property, which this change must not break.

    The population is what git TRACKS, so a baseline is not a function of what
    this particular machine happens to hold.
    """
    root = _repo(tmp_path, {_UNNAMED: {"phase3/b.json": "PASS"}})
    scratch = root / "benchmark-data" / "ic" / "scratch_local" / "reports"
    scratch.mkdir(parents=True)
    (scratch / "c.json").write_text('{"verdict": "FAIL"}\n')   # NOT committed
    found = {p.relative_to(root).as_posix()
             for p in M._published_run_trees(root / "benchmark-data")}
    assert found == {_UNNAMED}, (
        f"an UNTRACKED run tree entered the population: {found}")


# ==========================================================================
# 2. THE RATCHET NOW HOLDS THE LINE IT CLAIMS TO
# ==========================================================================
def test_a_new_unacknowledged_fail_outside_clean_run_is_red(tmp_path):
    """The two-arm control, as a test.

    ARM A: baseline recorded with the tree clean. ARM B: one new unacknowledged
    FAIL in a published tree NOT named `clean_run_*` — the shape all 8 of
    #1015's growth took. It must be rc 1.
    """
    root = _repo(tmp_path, {_UNNAMED: {"phase3/b.json": "PASS"}})
    bl = tmp_path / "bl.json"
    rc, _ = _sweep(root, "benchmark-data", "--baseline", str(bl),
                   "--write-baseline")
    assert rc == 0
    assert json.loads(bl.read_text())["findings_total"] == 0

    rc, out = _sweep(root, "benchmark-data", "--baseline", str(bl))
    assert rc == 0, out                       # control: still clean

    bad = root / _UNNAMED / "reports" / "phase3" / "new_fail.json"
    bad.write_text('{"verdict": "FAIL"}\n')
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "a new unacknowledged FAIL"],
                   cwd=root, check=True)

    rc, out = _sweep(root, "benchmark-data", "--baseline", str(bl))
    assert rc == 1, (
        "a NEW unacknowledged step-internal FAIL in a published run tree not "
        f"named clean_run_* did not redden the ratchet:\n{out}")
    assert "GREW" in out and _UNNAMED.split("/")[-1] in out, out


def test_an_acknowledged_fail_is_still_not_a_finding(tmp_path):
    """The control for the test above: widening the population must not make
    a WAIVED or BUBBLED failure start counting. If it did, the new number would
    be larger for a reason that is not a defect."""
    root = _repo(tmp_path, {_UNNAMED: {
        "phase3/b.json": "FAIL",
        "orchestrator/summary.json": None,
    }})
    orch = root / _UNNAMED / "reports" / "orchestrator" / "summary.json"
    orch.write_text(json.dumps(
        {"verdict": "FAIL", "failed": ["reports/phase3/b.json"]}) + "\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "bubbled"], cwd=root, check=True)
    bl = tmp_path / "bl.json"
    _sweep(root, "benchmark-data", "--baseline", str(bl), "--write-baseline")
    assert json.loads(bl.read_text())["findings_total"] == 0, (
        "a FAIL that IS bubbled up was counted as unacknowledged")


# ==========================================================================
# 3. A COUNT IS NOT A LINE WITHOUT THE SET IT COUNTED
# ==========================================================================
def test_a_baseline_from_a_different_population_is_NOT_CHECKED(tmp_path):
    """Measured on the real tree: the same file at the same commit answers 22
    over `benchmark-data/ic` and 45 over `benchmark-data`. Comparing one
    against the other is a verdict over a population never examined, so it is
    rc 2 — not a PASS, and not a FAIL either."""
    root = _repo(tmp_path, {_UNNAMED: {"phase3/b.json": "FAIL"}})
    bl = tmp_path / "bl.json"
    rc, _ = _sweep(root, "benchmark-data/ic", "--baseline", str(bl),
                   "--write-baseline")
    assert rc == 0
    assert json.loads(bl.read_text())["corpus_population"] == "benchmark-data/ic"

    rc, out = _sweep(root, "benchmark-data", "--baseline", str(bl))
    assert rc == 2, (
        "a baseline measured over one corpus root was silently compared "
        f"against another:\n{out}")
    assert "NOT CHECKED" in out and "benchmark-data/ic" in out, out


def test_the_same_population_still_ratchets_normally(tmp_path):
    """Control for the guard above — it must refuse a DIFFERENT population, not
    become unable to compare at all."""
    root = _repo(tmp_path, {_UNNAMED: {"phase3/b.json": "FAIL"}})
    bl = tmp_path / "bl.json"
    _sweep(root, "benchmark-data/ic", "--baseline", str(bl), "--write-baseline")
    rc, out = _sweep(root, "benchmark-data/ic", "--baseline", str(bl))
    assert rc == 0 and "NOT CHECKED" not in out, out


# ==========================================================================
# 4. THE SHIPPED BASELINE, WHICH NO FIXTURE CAN SPEAK FOR
# ==========================================================================
def test_the_shipped_baseline_records_which_population_it_counted():
    doc = json.loads(_BASELINE.read_text())
    assert doc.get("corpus_population"), (
        "the shipped baseline is a bare integer with no record of the corpus "
        "root it was measured over, so it is comparable to anything")
    assert isinstance(doc.get("findings_total"), int)


@pytest.mark.skipif(not (_REPO / "benchmark-data").is_dir(),
                    reason="no benchmark-data in this tree")
def test_the_shipped_baseline_still_matches_a_fresh_sweep():
    """A baseline that has drifted below the tree makes the gate permanently
    red; one that has drifted above it silently absorbs new findings. Either
    way the recorded number has stopped describing the corpus, and a fixture
    can never see that."""
    doc = json.loads(_BASELINE.read_text())
    corpus = _REPO / doc["corpus_population"]
    rep = M.check_corpus(corpus)
    assert rep["findings_total"] <= doc["findings_total"], (
        f"the corpus carries {rep['findings_total']} unacknowledged "
        f"step-internal FAIL(s) and the baseline records "
        f"{doc['findings_total']} — the ratchet is red")
    assert rep["runs_with_reports"] > 0, "the sweep reached nothing"
