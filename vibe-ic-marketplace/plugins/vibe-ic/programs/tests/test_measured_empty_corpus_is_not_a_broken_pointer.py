#!/usr/bin/env python3
"""A correct pointer at the published corpus must not be diagnosed as a broken one.

THE DEFECT THIS PINS, AS IT WAS MEASURED
========================================
`_published_corpus.corpus_root` named THREE causes for "the pointer is set and there
are no cells" — the name is wrong, the clone failed, the fetch step did nothing — and
refused. On 2026-08-20 a fourth appeared that is none of them: the pointer is right,
the clone succeeded, and `vibeic/benchmark-data` genuinely publishes zero cells
because the publisher withdrew all four of them.

The refusal then closed by advising the reader to *point it at a clone of
vibeic/benchmark-data*. **The remedy it printed is the action that produced it.**

Measured on a clean `a4caccefe` worktree, pointer bound at a real `git clone` of
`vibeic/benchmark-data` @ `3b58ccd42` (6929 blobs, 9 designs under `ic/`, 0 cell
directories, 0 `.def` blobs at any path):

    pointer at a corpus carrying one cell  ->  1345 tests collected, 0 errors
    pointer at the real published corpus   ->    52 tests collected, 52 errors

52 of the 55 importing modules died AT IMPORT — `needs_corpus` is built at module
scope, so the exception escapes collection rather than any test — and 1293 tests went
dark, most of them with no published cell as their subject.

This is the defect `tools/ci/routed_def_corpus.py` separates into rc 0 (an index was
read and holds none) and rc 3 (nothing was opened), surviving one layer down in the
test helper.

WHAT THIS FILE MAY NOT BE MISTAKEN FOR
======================================
It is NOT a relaxation, and the tests below are written so that a relaxation cannot
pass them. The refusal is still a refusal for every accident it was built for — an
empty directory, a path that does not exist, a tree that is not the corpus — and
those three are asserted here as well as in `test_published_corpus_helper.py`,
deliberately duplicated, because a future edit that widens the new row would show up
first as one of them going green.

A measured-empty corpus SKIPS. A skip is not a pass: nothing is verified about any
cell, and the reason says so in its own words rather than borrowing the
"could not look" sentence that belongs to a corpus nobody offered.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import _published_corpus as C  # noqa: E402


#: SPELLED AS A LITERAL, NOT AS `C.CORPUS_CONTRACT`, AND THAT IS THE POINT.
#: A fixture built from the module under test cannot go red for the reason the
#: module is wrong — it goes red with `AttributeError` the moment the constant is
#: new, and an AttributeError proves only that a name was added. The constant is
#: asserted to equal this literal in `test_the_contract_marker_is_the_publishing_
#: contract`, so drift is still caught, but the RED below is the real refusal.
_CONTRACT = "PUBLISHING.md"


def _corpus_tree(root: Path, *, cells: bool) -> Path:
    """The minimum tree that IS the published corpus, with or without a cell."""
    (root / "ic" / "somedesign").mkdir(parents=True, exist_ok=True)
    (root / _CONTRACT).write_text(
        "# Publishing converged benchmark evidence\n"
        "A cell is `ic/<IC>/v<version>_<PDK>/`.\n", encoding="utf-8")
    if cells:
        cell = root / "ic" / "somedesign" / "v1.0.0_pdk"
        cell.mkdir(parents=True, exist_ok=True)
        (cell / "RESULT.md").write_text("PASS\n", encoding="utf-8")
    return root


def _pointed_at(path) -> None:
    os.environ[C.CORPUS_ENV] = str(path)


def _unpointed() -> None:
    os.environ.pop(C.CORPUS_ENV, None)


# ══════════════════════════════════════════════════════════════════════
# THE new row. This is what goes red without the fix.
# ══════════════════════════════════════════════════════════════════════

def test_the_real_corpus_with_zero_cells_does_not_raise(tmp_path):
    """The whole finding, in one assertion.

    Before the fourth state existed this raised `CorpusPointerBroken`, which is a
    claim about the READER'S CONFIGURATION and the configuration is correct.
    """
    _corpus_tree(tmp_path, cells=False)
    _pointed_at(tmp_path)
    try:
        # `corpus_root` DELIBERATELY, not `corpus_state`: it exists both before and
        # after this repair, so the red below is the defect raising and not a name
        # that does not exist yet.
        root = C.corpus_root()
    except C.CorpusPointerBroken as exc:
        pytest.fail(
            "a correct pointer at the published corpus was diagnosed as a broken "
            f"pointer — the remedy it prints is the action that produced it: {exc}")
    finally:
        _unpointed()
    assert root is None, "a corpus with no cell must not hand back a cell root"


def test_the_contract_marker_is_the_publishing_contract():
    """`_CONTRACT` above is hand-spelled so the fixtures do not depend on the module
    under test. This is the one place the two spellings are tied together."""
    assert C.CORPUS_CONTRACT == _CONTRACT


def test_measured_empty_is_a_different_state_from_never_offered(tmp_path,
                                                                monkeypatch):
    """Two non-running states, and they must not be the same fact.

    Both give `corpus_root() is None`, which is why the STATE exists: the reason a
    reader is shown is chosen from it, not from the return value.
    """
    _corpus_tree(tmp_path, cells=False)
    _pointed_at(tmp_path)
    try:
        measured, _ = C.corpus_state()
    finally:
        _unpointed()
    monkeypatch.delenv(C.CORPUS_ENV, raising=False)
    monkeypatch.setattr(C, "_REPO", tmp_path / "nothing-here")
    offered, _ = C.corpus_state()
    assert measured == C.MEASURED_EMPTY
    assert offered == C.NOT_OFFERED
    assert measured != offered, (
        "a counted zero and an absent corpus collapsed into one state — the exact "
        "shape vibe-ic#1764 separated at the producer")


def test_the_two_reasons_are_different_sentences_and_neither_claims_a_pass():
    """`SKIP_REASON` says the check could not look. Over a corpus that WAS read and
    counted, that sentence is false, so it must not be the one shown."""
    assert C.MEASURED_EMPTY_REASON != C.SKIP_REASON
    assert "could not look" in C.SKIP_REASON
    assert "could not look" not in C.MEASURED_EMPTY_REASON.replace(
        "not 'I could not look'", "")
    # It must state the measurement, and state that it is not a pass.
    assert "0 cells" in C.MEASURED_EMPTY_REASON
    assert "not a pass" in C.MEASURED_EMPTY_REASON
    assert C.CORPUS_ENV in C.MEASURED_EMPTY_REASON


def test_skip_reason_follows_the_state(tmp_path, monkeypatch):
    _corpus_tree(tmp_path, cells=False)
    _pointed_at(tmp_path)
    try:
        assert C.skip_reason() == C.MEASURED_EMPTY_REASON
    finally:
        _unpointed()
    monkeypatch.setattr(C, "_REPO", tmp_path / "nothing-here")
    assert C.skip_reason() == C.SKIP_REASON


def test_a_correct_pointer_no_longer_kills_collection(tmp_path):
    """The cost the defect actually had: 52 of 55 modules died at IMPORT.

    Driven through a real interpreter, because the failure being guarded is that
    the exception escapes module scope and pytest never gets to a test.
    """
    _corpus_tree(tmp_path, cells=False)
    prog = (f"import sys; sys.path.insert(0, {str(_HERE)!r})\n"
            "import _published_corpus as C\n"
            "print(C.corpus_state()[0])\n")
    env = dict(os.environ)
    env[C.CORPUS_ENV] = str(tmp_path)
    r = subprocess.run([sys.executable, "-c", prog], capture_output=True,
                       text=True, timeout=60, env=env)
    assert r.returncode == 0, (
        "importing the helper with a correct pointer at an empty published corpus "
        f"still fails, so every module that imports it stays dark: {r.stderr[-600:]}")
    assert r.stdout.strip() == C.MEASURED_EMPTY, r.stdout


# ══════════════════════════════════════════════════════════════════════
# The three refusals the new row must NOT have widened. Duplicated from
# test_published_corpus_helper.py on purpose: an edit that loosens the new
# row shows up here first.
# ══════════════════════════════════════════════════════════════════════

def test_an_empty_directory_is_still_a_broken_pointer(tmp_path):
    """The measured `29 passed, 2 skipped` exploit. Still impossible."""
    empty = tmp_path / "empty"
    empty.mkdir()
    _pointed_at(empty)
    try:
        with pytest.raises(C.CorpusPointerBroken):
            C.corpus_root()
    finally:
        _unpointed()


def test_a_path_that_does_not_exist_is_still_a_broken_pointer(tmp_path):
    _pointed_at(tmp_path / "nope")
    try:
        with pytest.raises(C.CorpusPointerBroken) as e:
            C.corpus_root()
    finally:
        _unpointed()
    assert "does not exist" in str(e.value)


def test_a_tree_that_is_not_the_corpus_is_still_a_broken_pointer(tmp_path):
    """A real directory with real content that is simply not the publisher.

    This is the mistyped-path case with substance in it, which is the one a
    presence check on the directory alone would wave through.
    """
    other = tmp_path / "some-other-repo"
    (other / "datasets").mkdir(parents=True)
    (other / "runs").mkdir()
    (other / "README.md").write_text("not the corpus\n", encoding="utf-8")
    _pointed_at(other)
    try:
        with pytest.raises(C.CorpusPointerBroken):
            C.corpus_root()
    finally:
        _unpointed()


def test_the_contract_alone_is_not_enough_without_the_ic_root(tmp_path):
    """A tree with no `ic/` cannot be MEASURED for cells, so it is refused.

    Calling it measured-empty would claim a count over a shape that is not there,
    which is the same manufactured measurement in the opposite direction.
    """
    half = tmp_path / "half"
    half.mkdir()
    (half / _CONTRACT).write_text("# contract\n", encoding="utf-8")
    _pointed_at(half)
    try:
        with pytest.raises(C.CorpusPointerBroken):
            C.corpus_root()
    finally:
        _unpointed()


def test_an_ic_root_alone_is_not_enough_without_the_contract(tmp_path):
    """`ic/` is a two-letter directory name. It identifies nothing on its own."""
    half = tmp_path / "half"
    (half / "ic").mkdir(parents=True)
    _pointed_at(half)
    try:
        with pytest.raises(C.CorpusPointerBroken):
            C.corpus_root()
    finally:
        _unpointed()


def test_a_corpus_that_carries_cells_is_unchanged(tmp_path):
    """The row that must not move: cells present, the path comes back, nothing skips."""
    _corpus_tree(tmp_path, cells=True)
    _pointed_at(tmp_path)
    try:
        state, root = C.corpus_state()
        # Asked WHILE the pointer is still set, because `cell_dirs` re-reads it.
        # Comparing to [] after unsetting would be an assertion that cannot fail.
        names = [p.name for p in C.cell_dirs()]
    finally:
        _unpointed()
    assert state == C.PRESENT
    assert root == tmp_path
    assert names == ["v1.0.0_pdk"], names
