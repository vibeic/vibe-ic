"""End-to-end test of the canonical closed-loop fix-loop pattern.

This is the pattern that the *-fix / *-loop skills (hold-fix, drc-fix, eco-plan,
analog-sizing-loop) are documented to follow in their "Canonical loop
infrastructure" SKILL.md sections:

    IterativeSearch drives a bounded parameter sweep over a typed SearchSpace,
    every proposed iteration is passed through AdmissionGuard.admit() BEFORE the
    (here: toy) expensive evaluation, and the loop terminates via
    ConvergenceChecker (CONVERGED / PLATEAU / REGRESSION / EXHAUSTED).

The objective is a toy stand-in for "WHS toward 0 / yield toward 100%": a
two-knob quadratic whose optimum is reachable inside the bounded space. The test
asserts the loop converges, never spends an EDA round on a duplicate fingerprint,
and respects the iteration budget.

Both primitives are pure-Python and chip-AGNOSTIC, so this runs with no EDA
tools installed.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).parent.parent
assert (PROGRAMS / "iterative_search.py").exists()
assert (PROGRAMS / "loop_admission_guard.py").exists()

sys.path.insert(0, str(PROGRAMS))
import iterative_search as it          # noqa: E402
import loop_admission_guard as g       # noqa: E402


# A toy "score": stand-in for an expensive EDA measurement (WHS ps / yield %).
# Optimum at x=3, y=-1 with score 0.0; everything else is negative.
def _objective(point):
    return -((point["x"] - 3.0) ** 2 + (point["y"] + 1.0) ** 2)


def test_iterative_search_admission_guard_end_to_end():
    """IterativeSearch.run() drives the sweep; its internal AdmissionGuard
    dedups + budget-guards every point. Loop converges on the toy objective."""
    space = it.SearchSpace([
        it.Dimension("x", "continuous", lo=-10.0, hi=10.0),
        it.Dimension("y", "continuous", lo=-10.0, hi=10.0),
    ])
    checker = it.ConvergenceChecker(target=0.0, tolerance=0.5, patience=6)
    search = it.IterativeSearch(space, checker, maximize=True, seed=7,
                                explore_rounds=5, max_rounds=40)

    # The expensive evaluation must run AT MOST once per distinct admitted point.
    eval_calls = []

    def evaluate(point):
        eval_calls.append(g.canonical_fingerprint(point))
        return _objective(point)

    outcome = search.run(evaluate)

    # 1. The loop converged to (near) the optimum.
    assert outcome.status == it.CONVERGED
    assert outcome.best_score >= -0.5            # within tolerance of target 0.0
    assert abs(outcome.best_point["x"] - 3.0) < 1.0
    assert abs(outcome.best_point["y"] + 1.0) < 1.0

    # 2. Budget respected: never more rounds than max_rounds.
    assert 0 < outcome.rounds <= 40
    assert len(outcome.history) == outcome.rounds

    # 3. AdmissionGuard guaranteed no admitted point was a fingerprint duplicate
    #    -> the loop never wasted an (expensive) evaluation on a repeat.
    seen = search.guard.seen_fingerprints()
    assert len(seen) == search.guard.admitted_count == outcome.rounds
    # every evaluated point's fingerprint is unique
    assert len(set(eval_calls)) == len(eval_calls)


def test_manual_loop_guard_rejects_duplicate_and_runaway():
    """The manually-driven variant documented in the skills: each proposed
    iteration is screened by AdmissionGuard.admit() before the EDA run."""
    guard = g.AdmissionGuard(
        bounds={"skew_ps": (-50.0, 50.0)},
        caps={"buffers": 512},
        max_iterations=3,
    )

    # First admission: clamped into bounds, admitted, runs an iteration.
    r1 = guard.admit({"buffers": 8, "skew_ps": 200.0})   # skew out of range
    assert r1.admitted and r1.reason == "ADMITTED"
    assert "skew_ps" in r1.clamped_fields
    assert r1.proposal["skew_ps"] == 50.0                # post-clamp / safe

    # Identical (post-clamp) proposal -> DUPLICATE, no EDA round spent.
    r_dup = guard.admit({"buffers": 8, "skew_ps": 50.0})
    assert not r_dup.admitted and r_dup.reason == "DUPLICATE"
    assert r_dup.fingerprint == r1.fingerprint

    # Runaway buffer count is REJECTED (not clamped) before any expensive run.
    r_cap = guard.admit({"buffers": 9999, "skew_ps": -10.0})
    assert not r_cap.admitted and r_cap.reason == "RUNAWAY_CAP"

    # Fill the iteration budget, then the next admission is RUNAWAY_ITERATION_BUDGET.
    assert guard.admit({"buffers": 16, "skew_ps": -5.0}).admitted   # 2nd
    assert guard.admit({"buffers": 32, "skew_ps": 5.0}).admitted    # 3rd
    r_budget = guard.admit({"buffers": 1, "skew_ps": 0.0})          # 4th -> over budget
    assert not r_budget.admitted
    assert r_budget.reason == "RUNAWAY_ITERATION_BUDGET"


def test_manual_search_admit_loop_converges_minimizing():
    """Glue the two primitives by hand exactly as the drc-fix skill documents:
    IterativeSearch.propose() -> AdmissionGuard already screened it -> evaluate
    -> record, minimizing a residual-count-style objective."""
    space = it.SearchSpace([
        it.Dimension("x", "continuous", lo=-8.0, hi=8.0),
        it.Dimension("y", "continuous", lo=-8.0, hi=8.0),
    ])
    # minimize (x-2)^2 + (y-2)^2 -> optimum 0 at (2,2)
    checker = it.ConvergenceChecker(target=0.0, tolerance=0.5, patience=8)
    search = it.IterativeSearch(space, checker, maximize=False, seed=3,
                                explore_rounds=5, max_rounds=40)

    while len(search.history) < search.max_rounds:
        point = search.propose()      # None => guard exhausted budget / saturated
        if point is None:
            break
        score = (point["x"] - 2.0) ** 2 + (point["y"] - 2.0) ** 2
        search.record(point, score)
        if search.checker.classify(search.scores(), search.maximize) in (
                it.CONVERGED, it.REGRESSION):
            break

    best_point, best_score = search.best()
    assert search.status() == it.CONVERGED
    assert best_score <= 0.5
    # admitted-count tracked by the internal guard equals the rounds recorded
    assert search.guard.admitted_count == len(search.history)
