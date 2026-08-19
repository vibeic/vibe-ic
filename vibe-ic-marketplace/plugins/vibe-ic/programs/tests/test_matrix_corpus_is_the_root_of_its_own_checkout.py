#!/usr/bin/env python3
"""The corpus must be the ROOT of its own checkout, not a directory inside one.

WHAT WENT WRONG
---------------
`test_matrix_d3_outputs_produced.run_roots` states the invariant this module
enforces, in its own docstring::

    trackedness is still decided by `git ls-tree -r HEAD` in the tree that
    holds the root (:func:`tracked_under`), so it is the CORPUS COMMIT that
    answers, `git clean -xdf` still cannot move a verdict, and two clones of
    one corpus commit still agree

`_refuse_an_unanswerable_corpus` was the only thing standing behind it, and it
asked `_claims_to_be_a_checkout`, which walks UP the parent directories looking
for a `.git`. A corpus that is a SUBDIRECTORY of some other repository's work
tree satisfies that, and `tracked_under` then runs `git ls-tree -r HEAD` there
and is answered by THAT repository's HEAD. Not the corpus commit. Some commit,
of some repository, that happens to own the directory.

It is not a hypothetical spelling. v1.10.56 (#1723) moved the published cells
out to `vibeic/benchmark-data`; a checkout of THIS repository on any branch
from before that move still carries `benchmark-data/` tracked, and pointing
`$VIBE_IC_BENCHMARK_DATA` at one is a single plausible keystroke.

MEASURED on this host, same commit of this repository, same image, same
command, only the pointer changed::

    corpus                                   tracked at HEAD   d3 verdict
    vibeic/benchmark-data @146d665 (clone)             8,309   23 failed
    <a vibe-ic checkout>/benchmark-data                17,479    8 failed

The local tree is the richer one, and that is the danger, not the comfort: it
credits as evidence artefacts the PUBLISHED corpus does not carry. `ic/sha256`
is 810 files in that working tree and 9 — an `input/` directory and nothing
else — in the corpus that was actually published. Fifteen d3 cells read as
answered because somebody's unpublished working tree answered them.

WHAT THIS GUARD MEASURES
------------------------
Two synthetic corpora, built here, one of each shape, put through the real
`_refuse_an_unanswerable_corpus`. No pointer is set and no real corpus is
touched, so this module states the same verdict on a host that has one and on
a host that does not.

It also records the NON-DEGENERACY: the predicate that used to be the whole
rule still says "yes, a checkout" about the bad shape. The new rule is
therefore doing work the old one did not, rather than restating it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
for _p in (str(_TESTS_DIR), str(_TESTS_DIR.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import test_matrix_d3_outputs_produced as D3      # noqa: E402


def _git(cwd: Path, *args: str) -> None:
    """Run git in *cwd*, with an identity, refusing to inherit the operator's.

    `-c` rather than `git config`: the repositories built here are scratch and
    must not depend on, or acquire, any global git state.
    """
    proc = subprocess.run(
        ["git", "-c", "user.email=matrix@example.invalid",
         "-c", "user.name=matrix", "-c", "commit.gpgsign=false",
         "-C", str(cwd), *args],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, (
        f"git {' '.join(args)} failed in {cwd}: {proc.stderr.strip()}")


def _make_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q", "-b", "main")


def _commit_all(root: Path, message: str) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", message)


@pytest.fixture()
def corpus_inside_another_repo(tmp_path) -> Path:
    """`<outer checkout>/benchmark-data` — the shape that must be refused."""
    outer = tmp_path / "outer_repo"
    _make_repo(outer)
    corpus = outer / "benchmark-data"
    (corpus / "ic" / "demo").mkdir(parents=True)
    (corpus / "ic" / "demo" / "artefact.txt").write_text(
        "carried by the OUTER repository's commit\n", encoding="utf-8")
    _commit_all(outer, "outer repo carries a benchmark-data tree")
    return corpus


@pytest.fixture()
def corpus_that_is_its_own_repo(tmp_path) -> Path:
    """A clone-shaped corpus: its ROOT is the checkout."""
    corpus = tmp_path / "benchmark-data"
    _make_repo(corpus)
    (corpus / "ic" / "demo").mkdir(parents=True)
    (corpus / "ic" / "demo" / "artefact.txt").write_text(
        "carried by the CORPUS commit\n", encoding="utf-8")
    _commit_all(corpus, "published cells")
    return corpus


def test_a_corpus_that_is_its_own_checkout_is_admitted(
        corpus_that_is_its_own_repo):
    """The legitimate shape must keep working, or the rule is just a wall."""
    D3._refuse_an_unanswerable_corpus(corpus_that_is_its_own_repo)


def test_a_corpus_inside_another_checkout_is_refused(
        corpus_inside_another_repo):
    """The commit that answers must be the corpus's own."""
    with pytest.raises(AssertionError) as caught:
        D3._refuse_an_unanswerable_corpus(corpus_inside_another_repo)

    message = str(caught.value)
    assert "not the root of its own checkout" in message, message
    assert str(corpus_inside_another_repo.parent.resolve()) in message, (
        f"the refusal does not name the work tree that would have answered, "
        f"so an operator cannot tell which repository's HEAD was about to be "
        f"read as the corpus commit:\n{message}")


def test_the_old_predicate_still_accepts_the_refused_shape(
        corpus_inside_another_repo):
    """NON-DEGENERACY. The new rule is not a restatement of the old one.

    If `_claims_to_be_a_checkout` had ever refused this shape, the rule above
    would be dead code and its guard would be measuring nothing.
    """
    assert D3._claims_to_be_a_checkout(corpus_inside_another_repo), (
        "the filesystem predicate now refuses the nested shape by itself, so "
        "the work-tree-root rule beside it is no longer the thing under test "
        "— re-derive what this module guards before deleting either")


def test_the_outer_commit_is_what_would_have_answered(
        corpus_inside_another_repo):
    """The CONSEQUENCE, measured rather than argued.

    A file no corpus repository ever published reads as `tracked at HEAD` —
    which is this module's word for "evidence" — purely because the enclosing
    repository committed it.
    """
    assert D3.is_tracked(corpus_inside_another_repo, "ic/demo/artefact.txt"), (
        "the fixture did not reproduce the condition: nothing under the nested "
        "corpus reads as tracked, so this cell proves nothing about whose "
        "commit answers")
