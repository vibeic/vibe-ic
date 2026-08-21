"""Unit tests for iterative_search.py.

Covers Dimension/SearchSpace mechanics, the ConvergenceChecker verdicts, and
the deterministic explore-then-exploit IterativeSearch driver.
"""
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'iterative_search.py'
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import iterative_search as it  # noqa: E402


# ---------------------------------------------------------------------------
# Dimension
# ---------------------------------------------------------------------------
def test_dimension_validation():
    with pytest.raises(ValueError):
        it.Dimension("bad", "continuous")            # missing lo/hi
    with pytest.raises(ValueError):
        it.Dimension("bad", "enumerate")             # missing choices
    with pytest.raises(ValueError):
        it.Dimension("bad", "weird")                 # unknown kind
    with pytest.raises(ValueError):
        it.Dimension("bad", "integer", lo=5, hi=1)   # lo>hi


def test_dimension_clamp():
    d = it.Dimension("x", "continuous", lo=0.0, hi=1.0)
    assert d.clamp(2.0) == 1.0
    assert d.clamp(-1.0) == 0.0
    di = it.Dimension("n", "integer", lo=0, hi=10)
    assert di.clamp(3.6) == 4
    de = it.Dimension("s", "enumerate", choices=["a", "b"])
    assert de.clamp("z") == "a"
    db = it.Dimension("f", "boolean")
    assert db.clamp(1) is True


def test_dimension_sample_in_range_deterministic():
    import random
    d = it.Dimension("n", "integer", lo=0, hi=10)
    rng = random.Random(0)
    vals = [d.sample(rng) for _ in range(50)]
    assert all(0 <= v <= 10 for v in vals)


# ---------------------------------------------------------------------------
# SearchSpace
# ---------------------------------------------------------------------------
def test_searchspace_bounds_only_numeric():
    space = it.SearchSpace([
        it.Dimension("x", "continuous", lo=-1.0, hi=1.0),
        it.Dimension("n", "integer", lo=0, hi=8),
        it.Dimension("s", "enumerate", choices=["a", "b"]),
        it.Dimension("f", "boolean"),
    ])
    b = space.bounds()
    assert set(b) == {"x", "n"}
    assert b["x"] == (-1.0, 1.0)


def test_searchspace_random_point_deterministic():
    import random
    space = it.SearchSpace([it.Dimension("x", "continuous", lo=0.0, hi=1.0)])
    p1 = space.random_point(random.Random(42))
    p2 = space.random_point(random.Random(42))
    assert p1 == p2


# ---------------------------------------------------------------------------
# ConvergenceChecker
# ---------------------------------------------------------------------------
def test_converge_on_target_maximize():
    c = it.ConvergenceChecker(target=0.0, tolerance=0.5)
    assert c.classify([-5.0, -2.0, -0.2], maximize=True) == it.CONVERGED


def test_continue_when_far():
    c = it.ConvergenceChecker(target=0.0, tolerance=0.5, patience=10)
    assert c.classify([-5.0, -4.0, -3.0], maximize=True) == it.CONTINUE


def test_regression_detected():
    c = it.ConvergenceChecker(regression_drop=1.0)
    assert c.classify([5.0, 1.0], maximize=True) == it.REGRESSION


def test_plateau_detected():
    c = it.ConvergenceChecker(patience=3)
    # no improvement across the last 4 rounds
    assert c.classify([1.0, 1.0, 1.0, 1.0, 1.0], maximize=True) == it.PLATEAU


def test_empty_history_continue():
    assert it.ConvergenceChecker().classify([]) == it.CONTINUE


# ---------------------------------------------------------------------------
# IterativeSearch
# ---------------------------------------------------------------------------
def _quadratic_search(seed=7):
    space = it.SearchSpace([
        it.Dimension("x", "continuous", lo=-10.0, hi=10.0),
        it.Dimension("y", "continuous", lo=-10.0, hi=10.0),
    ])
    checker = it.ConvergenceChecker(target=0.0, tolerance=0.5, patience=6)
    search = it.IterativeSearch(space, checker, maximize=True, seed=seed,
                                explore_rounds=5, max_rounds=60)

    def evaluate(p):
        return -((p["x"] - 3.0) ** 2 + (p["y"] + 1.0) ** 2)
    return search.run(evaluate)


def test_search_converges():
    outcome = _quadratic_search()
    assert outcome.status == it.CONVERGED
    assert outcome.best_score >= -0.5            # within tolerance of 0
    assert abs(outcome.best_point["x"] - 3.0) < 1.5
    assert abs(outcome.best_point["y"] + 1.0) < 1.5


def test_search_deterministic():
    a = _quadratic_search(seed=11)
    b = _quadratic_search(seed=11)
    assert a.history == b.history
    assert a.best_point == b.best_point


def test_no_duplicate_points_recorded():
    outcome = _quadratic_search()
    fps = [tuple(sorted(h["point"].items())) for h in outcome.history]
    assert len(fps) == len(set(fps)), "admission guard should prevent dup points"


def test_demo_cli():
    outcome = it._demo()
    assert outcome.status == it.CONVERGED
