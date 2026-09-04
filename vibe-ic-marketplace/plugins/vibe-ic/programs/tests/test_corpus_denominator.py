#!/usr/bin/env python3
"""A statistic over the corpus must carry its own denominator. vibe-ic#1200.

The historical corpus had 73 of 75 published run trees without a per-step
verdict.  The frozen benchmark-data 8c4b608 population is exactly 2 of 12
countable, with ten uncountable.  `0 of 2 countable` is the honest answer and
`0` is the lie. These tests hold the mechanism that makes the second spelling
unavailable, and the ratchet that stops this exact population becoming less
answerable than it already is.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[2]
REPO = PLUGIN.parents[2]
import sys  # noqa: E402
sys.path.insert(0, str(PLUGIN / "programs"))
import _corpus_denominator as CD  # noqa: E402
from _published_corpus import corpus_root, needs_corpus  # noqa: E402


def _ic() -> Path:
    """The `ic/` tree of whichever published corpus is readable here.

    NOT `REPO / "benchmark-data" / "ic"` unconditionally, and the difference is
    the whole reason the two tests below were failing. That directory still
    exists in this repository — it holds the design INPUTS, 542 files — while
    the RESULT cells moved to `vibeic/benchmark-data`. So the old
    `skipif(not IC.is_dir())` guard could never fire, and the two corpus tests
    ran over a population of input directories and reported, in the words of one
    of them, "the corpus shrank unexpectedly: (0, 12)". Nothing had shrunk: they
    were measuring a different tree than the one they name.
    """
    root = corpus_root()
    return (root if root is not None else REPO / "benchmark-data") / "ic"


def _tree(root: Path, ic: str, run: str, step_index=None) -> Path:
    t = root / ic / run
    t.mkdir(parents=True, exist_ok=True)
    if step_index is not None:
        p = t / CD.STEP_INDEX_REL
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(step_index if isinstance(step_index, str)
                     else json.dumps(step_index))
    return t


# ===========================================================================
# THE MECHANISM: the numerator is not available without the denominator
# ===========================================================================
def test_the_denominator_exposes_no_bare_rate():
    """Every one of these is a way to quote 2 without quoting 75.

    The defect is not that somebody computed the wrong number — it is that the
    right number can be printed alone. So the type refuses to produce one.
    """
    d = CD.Denominator(n_countable=2, n_total=75)
    for attr in ("percent", "pct", "rate", "ratio", "fraction_value", "value"):
        assert not hasattr(d, attr), (
            f"Denominator.{attr} exists, which is a way to quote the numerator "
            f"alone — the exact shape #1200 is about")
    for dunder in ("__int__", "__float__", "__index__"):
        assert not hasattr(d, dunder), (
            f"Denominator.{dunder} lets the pair collapse to one number")


def test_fraction_returns_BOTH_and_render_says_both():
    d = CD.Denominator(n_countable=2, n_total=75, uncountable=("a", "b"))
    assert d.fraction() == (2, 75)
    s = d.render()
    assert "2 of 75" in s and "could not" in s, s


def test_a_corpus_where_NOTHING_can_answer_is_vacuous_not_zero():
    """`0 of 75 countable` reads like a result and is not one.

    Distinct from an empty corpus, and more dangerous, because 75 in the
    denominator makes it look like something was examined.
    """
    d = CD.Denominator(n_countable=0, n_total=75, uncountable=tuple("x" * 75))
    assert d.is_vacuous is True
    assert CD.Denominator(n_countable=1, n_total=75).is_vacuous is False


def test_an_empty_population_renders_as_no_population():
    d = CD.Denominator(n_countable=0, n_total=0)
    assert "no population" in d.render(), d.render()
    assert d.is_vacuous is True


# ===========================================================================
# COUNTABILITY
# ===========================================================================
def test_a_tree_with_a_readable_record_is_countable(tmp_path):
    _tree(tmp_path, "ic", "v1", {"1": "pass"})
    d = CD.step_verdict_denominator(tmp_path)
    assert d.fraction() == (1, 1) and not d.uncountable


def test_PAIRED_a_tree_with_no_record_is_not(tmp_path):
    _tree(tmp_path, "ic", "v1", None)
    d = CD.step_verdict_denominator(tmp_path)
    assert d.fraction() == (0, 1)
    assert d.uncountable == ("ic/v1",), d.uncountable


def test_a_record_that_does_not_PARSE_is_not_countable(tmp_path):
    """Present-but-unreadable answers nothing. Counting it would put an
    unanswerable tree in the numerator, which is the defect wearing a file."""
    _tree(tmp_path, "ic", "v1", "{not json")
    d = CD.step_verdict_denominator(tmp_path)
    assert d.fraction() == (0, 1), d.as_dict()


def test_an_EMPTY_record_is_not_countable(tmp_path):
    """`{}` parses and answers nothing."""
    _tree(tmp_path, "ic", "v1", {})
    assert CD.step_verdict_denominator(tmp_path).fraction() == (0, 1)


def test_the_walk_counts_RUN_TREES_and_not_their_subdirectories(tmp_path):
    """A deeper walk would count `steps/` and `reports/` as run trees and
    inflate the denominator — the same lie upside down."""
    t = _tree(tmp_path, "ic", "v1", {"1": "pass"})
    (t / "reports" / "phase3").mkdir(parents=True)
    (t / "steps" / "s1").mkdir(parents=True)
    d = CD.step_verdict_denominator(tmp_path)
    assert d.n_total == 1, f"the walk counted subdirectories: {d.as_dict()}"


# ===========================================================================
# THE RATCHET, both directions
# ===========================================================================
def test_the_ratchet_REFUSES_a_corpus_that_became_less_answerable():
    d = CD.Denominator(0, 76, uncountable=tuple(f"t{i}" for i in range(74)))
    ok, why = CD.ratchet_verdict(d, ceiling=73)
    assert ok is False
    assert "less answerable" in why and "74" in why, why


def test_PAIRED_the_ratchet_ACCEPTS_unchanged_and_asks_to_hold_a_gain():
    same = CD.Denominator(2, 75, uncountable=tuple(f"t{i}" for i in range(73)))
    ok, why = CD.ratchet_verdict(same, ceiling=73)
    assert ok is True and "unchanged" in why

    better = CD.Denominator(5, 75, uncountable=tuple(f"t{i}" for i in range(70)))
    ok, why = CD.ratchet_verdict(better, ceiling=73)
    assert ok is True, why
    assert "lower UNCOUNTABLE_CEILING to 70" in why, (
        "a gain that nobody is asked to hold is a gain that will be given back")


def test_default_ratchet_is_bound_to_the_frozen_ten_uncountable():
    same = CD.Denominator(2, 12, uncountable=tuple(f"u{i}" for i in range(10)))
    ok, why = CD.ratchet_verdict(same)
    assert ok is True and "unchanged" in why, why

    regressed = CD.Denominator(
        2, 13, uncountable=tuple(f"u{i}" for i in range(11)))
    ok, why = CD.ratchet_verdict(regressed)
    assert ok is False and "up from 10" in why, why


# ===========================================================================
# THE REAL CORPUS
# ===========================================================================
def test_the_published_corpus_has_not_become_less_answerable():
    d = CD.step_verdict_denominator(_ic())
    ok, why = CD.ratchet_verdict(d)
    assert ok, why


@needs_corpus
def test_the_measured_state_is_what_the_docstring_claims():
    """#1200's number, re-derived rather than quoted.

    If this fails the corpus moved, and the module's opening measurement — the
    thing a reader trusts — must move with it.
    """
    root = _ic()
    d = CD.step_verdict_denominator(root)
    assert d.fraction() == (2, 12), (
        f"the frozen 8c4b608 denominator moved: {d.fraction()}")
    uncountable = set(d.uncountable)
    countable = {
        str(p.relative_to(root)) for p in CD.run_trees(root)
        if str(p.relative_to(root)) not in uncountable
    }
    assert countable == {
        "spm/v1.10.18_sky130A",
        "spm/v1.14.88_gf180mcuD",
    }, countable
    assert len(uncountable) == CD.UNCOUNTABLE_CEILING == 10
    assert d.is_vacuous is False, "not a single tree can answer"
    # ...and the disclosure a caller would print names both numbers.
    s = d.render()
    assert f"of {d.n_total}" in s and str(d.n_countable) in s, s


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
