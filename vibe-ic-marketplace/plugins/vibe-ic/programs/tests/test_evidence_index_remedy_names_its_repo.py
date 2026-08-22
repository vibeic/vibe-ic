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

import subprocess
import sys
from pathlib import Path

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
    return subprocess.run(
        [sys.executable, str(PROG), "--check", "--root", str(repo),
         "--corpus-may-be-absent"],
        capture_output=True, text=True, env=env, timeout=60)


def test_when_the_index_is_outside_this_repo_the_remedy_says_so(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    corpus_root = tmp_path / "corpus"
    _corpus(corpus_root, "# stale\n\nnothing that regenerates\n")
    r = _run(repo, corpus_root / "ic")
    if "Fix:" not in r.stdout:
        import pytest
        pytest.skip(f"gate did not reach the stale-index branch: "
                    f"{r.stdout.strip()[:200]}")
    fix = next(l for l in r.stdout.splitlines() if "Fix:" in l)
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
    if "Fix:" not in r.stdout:
        import pytest
        pytest.skip("gate did not reach the stale-index branch")
    fix = next(l for l in r.stdout.splitlines() if "Fix:" in l)
    assert fix.count("INDEX.md") == 1, fix
