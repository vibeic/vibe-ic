"""The printed remedy must name the repository the result lands in.

A printed remedy is EXECUTED, not read. `benchmark_evidence_index` said "re-run
with --write and commit the result", which was written when the index lived in
this repository. It can now live in the corpus clone — the code that formats the
path already knows that — while the gate itself is run from vibe-ic. A reader
following the old remedy commits in the wrong repository, finds nothing to
commit, and is left with a red gate over a tree that is correct.

Same class as a remedy whose command does not run: naming the wrong place and
failing to run are the same defect to whoever tries it.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROGRAMS = Path(__file__).resolve().parents[1]
PROG = PROGRAMS / "benchmark_evidence_index.py"


def _corpus(root: Path, index_body: str) -> Path:
    """A corpus holding one published cell and a deliberately stale INDEX.md."""
    ic = root / "ic"
    (ic / "somecell" / "reports").mkdir(parents=True)
    (ic / "somecell" / "reports" / "note.md").write_text("x", encoding="utf-8")
    (ic / "INDEX.md").write_text(index_body, encoding="utf-8")
    return ic


def _run(repo: Path, corpus: Path | None):
    env = {"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}
    if corpus is not None:
        env["VIBE_IC_BENCHMARK_DATA"] = str(corpus.parent)
    return _pr.run(
        [sys.executable, str(PROG), "--check", "--root", str(repo),
         "--corpus-may-be-absent"],
        capture_output=True, text=True, env=env)


def _fix_line(r, what: str) -> str:
    """The gate's `Fix:` line, or a FAILURE naming what was not reached.

    This was `pytest.skip` at three sites. A skip here is a test that has gone
    dark: the fixture CONSTRUCTS a corpus with a stale index precisely so the
    stale-index branch is reached, so not reaching it is a broken construction,
    not an environment this test should excuse. Skipping reported "passed" for
    a run that checked nothing about the remedy -- which is the same shape as
    the defect this whole module exists to catch.
    """
    if "Fix:" not in r.stdout:
        raise AssertionError(
            f"the {what} construction never reached the stale-index branch, so "
            f"nothing about the remedy was checked. rc={r.returncode}\n"
            f"stdout: {r.stdout.strip()[:400]}\nstderr: {r.stderr.strip()[:200]}")
    return next(l for l in r.stdout.splitlines() if "Fix:" in l)


def test_when_the_index_is_outside_this_repo_the_remedy_says_so(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    corpus_root = tmp_path / "corpus"
    _corpus(corpus_root, "# stale\n\nnothing that regenerates\n")
    r = _run(repo, corpus_root / "ic")
    fix = _fix_line(r, "outside-this-repo")
    assert "NOT this repository" in fix, fix
    assert "corpus clone" in fix, fix
    # and it must name the FILE, so the reader knows what to commit there
    assert "INDEX.md" in fix, fix


def test_the_remedy_never_says_the_path_twice(tmp_path):
    """It did, in the first version of this fix. A remedy that repeats itself
    reads as two instructions and is one."""
    repo = tmp_path / "repo"
    repo.mkdir()
    corpus_root = tmp_path / "corpus"
    _corpus(corpus_root, "# stale\n\nnothing that regenerates\n")
    r = _run(repo, corpus_root / "ic")
    fix = _fix_line(r, "no-repetition")
    assert fix.count("INDEX.md") == 1, fix


def test_a_dotdot_spelling_does_not_make_an_outside_index_look_inside(tmp_path):
    """The predicate must answer about the FILE, not about its spelling.

    `relative_to` is lexical and `ic_root` is built from
    $VIBE_IC_BENCHMARK_DATA without being resolved, so a value carrying `..`
    used to defeat this: an index genuinely OUTSIDE the repository was reported
    as "this repository", printing exactly the wrong-repository remedy this
    module exists to prevent. Measured before the fix; this pins it.

    The two arms differ only in the SPELLING of the same corpus path.
    """
    repo = tmp_path / "repo"
    (repo / "sub").mkdir(parents=True)
    corpus_root = tmp_path / "corpus"
    _corpus(corpus_root, "# stale\n\nnothing that regenerates\n")

    # the same directory, reached by a path that walks INTO the repo first
    spelled = repo / "sub" / ".." / ".." / "corpus" / "ic"
    assert spelled.resolve() == (corpus_root / "ic").resolve()

    r = _run(repo, spelled)
    fix = _fix_line(r, "dotdot-spelling")
    assert "NOT this repository" in fix, fix
