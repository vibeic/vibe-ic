"""test_issue546_corpus_gates_enumerate_the_commit.py — a corpus gate's input is
what the COMMIT carries, not what this disk holds.

WHAT WENT WRONG (vibe-ic#546)
=============================
`shipped_path_portability_check` and `dead_plugin_path_check` enumerated with
`rglob`, so their input set included whatever the last local run left behind.
Measured at f7b9c7fa0, the SAME COMMIT on two trees:

    shipped_path_portability   3654 file(s) scanned   vs  3595 in a fresh worktree
    dead_plugin_path           3379 examined          vs  3323

The residue is generated test fixtures under
`programs/tests/fixtures/synthetic_benchmark_phase1/`, ignored by `.gitignore`.
That is why this was invisible for so long: `git status --untracked-files=all`
does NOT list ignored paths, so every "is the tree clean?" check said yes.

The verdicts agreed, which is the trap — a count difference is the OBSERVABLE
evidence that the input sets differ, and waiting for a verdict to flip means
waiting for the damage. A fixture written with an absolute path would have made
the portability gate FAIL on its author's machine and PASS in CI, for a file
that is in neither commit.

`_published_tree` was built for exactly this class and its docstring already
records three earlier instances (v1.6.88, v1.6.90, l4_systemrdl_export). These
two gates are the fourth and fifth; the fix is to adopt it, not to invent
anything.

WHY THESE TESTS DRIVE `main()`
==============================
They assert on the PRINTED verdict line, not on a returned structure. A
disclosure a reader never sees is not a disclosure — the #539 mutation set
proved that exact point, where stripping the disclosure from the printed line
left a test asserting on the struct still green.
"""
from __future__ import annotations

import io
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
PLUGIN = PROGRAMS.parent
sys.path.insert(0, str(PROGRAMS))

import dead_plugin_path_check as dpp          # noqa: E402
import shipped_path_portability_check as spp  # noqa: E402


def _repo_of(residue: Path) -> Path:
    """The private plugin repo the `ignored_residue` fixture built."""
    for parent in residue.parents:
        if (parent / ".git").exists():
            return parent
    raise AssertionError(f"no git repo above {residue}")

#: The residue path, RELATIVE to a plugin root. Under `programs/`, so it is
#: inside a scanned bundle subtree, and matched by `.gitignore`
#: `**/tests/fixtures/synthetic_benchmark_phase1/`. This is not a contrived
#: path: it is the real residue class that produced the 59-file gap.
_IGNORED_FIXTURE_REL = Path(
    "programs/tests/fixtures/synthetic_benchmark_phase1/_i546_probe")


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, timeout=60)


def _git_ignores(repo: Path, path: Path) -> bool:
    """Ask git, so the test cannot drift from `.gitignore`."""
    return _git(repo, "check-ignore", "-q", str(path)).returncode == 0


@pytest.fixture
def ignored_residue(tmp_path):
    """A plugin-shaped GIT REPO carrying one ignored generated file.

    THE RESIDUE USED TO BE WRITTEN INTO THE LIVE TREE — this checkout's own
    `programs/tests/fixtures/synthetic_benchmark_phase1/_i546_probe/`, removed
    in a `finally`. That is the residue class this module is ABOUT, planted in
    the tree every other pytest session is reading: the landing gate's per-file
    recovery path runs many sessions at once over ONE checkout, so for the body
    of these tests a neighbour that enumerates by walking the disk counted a
    `.py` that is in no commit. And because the file is git-IGNORED, neither
    `git status --porcelain` nor `--untracked-files=all` shows it — the same
    invisibility that let #546 survive is what makes the red it manufactures
    untraceable.

    The repo built here carries the SHIPPED `.gitignore`, so the premise test
    below still proves the real ignore rule covers this class; and the A/B is
    over a population this test owns, which is what makes the count assertions
    mean something.
    """
    repo = tmp_path / "plugin"
    (repo / "programs").mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / ".gitignore").write_text(
        (PLUGIN / ".gitignore").read_text(encoding="utf-8", errors="replace")
        if (PLUGIN / ".gitignore").is_file()
        else "**/tests/fixtures/synthetic_benchmark_phase1/\n",
        encoding="utf-8")
    # Two tracked files, so the tracked population is non-empty and a count
    # that moves is attributable.
    (repo / "programs" / "tracked_one.py").write_text("A = 1\n", encoding="utf-8")
    (repo / "programs" / "tracked_two.py").write_text("B = 2\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")

    d = repo / _IGNORED_FIXTURE_REL
    d.mkdir(parents=True, exist_ok=True)
    f = d / "generated.py"
    f.write_text("# generated by a local run\nVALUE = 1\n", encoding="utf-8")
    yield f
    assert not (PLUGIN / _IGNORED_FIXTURE_REL).exists(), (
        "the probe reached the live tree; an IGNORED plant there is invisible "
        "to git status and visible to every disk-walking scanner")


def test_the_stimulus_is_real_and_invisible_to_the_usual_clean_check(ignored_residue):
    """THE PREMISE, PROVEN FIRST. If git did not ignore this file, or if
    `--untracked-files=all` did show it, the rest of this module would be
    testing something that cannot happen."""
    assert ignored_residue.is_file()
    repo = _repo_of(ignored_residue)
    assert _git_ignores(repo, ignored_residue), (
        "the probe file is not ignored, so it is not the residue class #546 is "
        "about — this test would prove nothing")
    r = _git(repo, "status", "--porcelain", "--untracked-files=all", "--",
             str(repo / _IGNORED_FIXTURE_REL))
    assert r.stdout.strip() == "", (
        "an ignored path showed up in --untracked-files=all; the whole reason "
        "#546 stayed hidden was that it does not")


def test_portability_scan_ignores_generated_residue(ignored_residue):
    """The count must not move when a generated file appears."""
    repo = _repo_of(ignored_residue)
    spp.scan_tree(repo)
    with_residue = spp.SCAN_CENSUS["files_read"]
    assert spp.SCAN_CENSUS["enumeration"] == "git-tracked"
    ignored_residue.unlink()
    spp.scan_tree(repo)
    assert spp.SCAN_CENSUS["files_read"] == with_residue, (
        "the scanned population changed when an IGNORED file appeared or "
        "vanished — the gate is reading the disk, not the commit")


def test_dead_plugin_scan_ignores_generated_residue(ignored_residue):
    repo = _repo_of(ignored_residue)
    _, with_residue = dpp.scan(str(repo))
    assert with_residue["enumeration"] == "git-tracked"
    ignored_residue.unlink()
    _, without = dpp.scan(str(repo))
    assert without["files_considered"] == with_residue["files_considered"], (
        "the considered population changed with an IGNORED file — same defect")


def test_both_gates_name_their_enumeration_in_the_printed_verdict():
    """A fallback nobody can see is how this survived. The tracked set and the
    walk print the same sentence, so the sentence must say which one ran."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        spp.main([str(PLUGIN)])
    assert "git-tracked" in buf.getvalue(), (
        "shipped_path_portability_check's verdict does not name its "
        "enumeration; a silent fallback would be indistinguishable from this")

    buf = io.StringIO()
    with redirect_stdout(buf):
        dpp.main([str(PLUGIN)])
    assert "git-tracked" in buf.getvalue(), (
        "dead_plugin_path_check's verdict does not name its enumeration")


def test_outside_a_published_tree_the_walk_still_runs_and_says_so(tmp_path):
    """`None` from `_published_tree` means NOT A PUBLISHED TREE — never
    "published and empty". A user's own project publishes nothing, so the walk
    is the honest answer there, and refusing would turn a working gate into a
    silent one. It must still find a real defect, and still disclose the mode."""
    # Assembled rather than written literally, following the convention in
    # test_shipped_path_portability_check.py: this file is itself shipped
    # source, and a literal personal path here would make the guard's own
    # regression lock FAIL on the test that proves the guard works.
    leak = "/" + "home" + "/" + ("some" + "body") + "/project"
    (tmp_path / "programs").mkdir()
    (tmp_path / "programs" / "leaky.py").write_text(
        f'HOME = "{leak}"\n', encoding="utf-8")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = spp.main([str(tmp_path)])
    out = buf.getvalue()
    assert rc == 1, "the walk fallback stopped finding a real personal path"
    assert "filesystem-walk" in out, (
        "the fallback did not name itself — a silent fallback reintroduces "
        "#546 on exactly the paths that are not ours")
