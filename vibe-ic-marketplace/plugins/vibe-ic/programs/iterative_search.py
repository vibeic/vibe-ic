#!/usr/bin/env python3
"""
iterative_search.py -- Generic bounded iterative-search primitive.

Unifies the explore-then-exploit loops that Vibe-IC currently re-implements
per skill (hold-fix slack search, analog-sizing W/L sweep, drc-fix spacing
search, timing-closure SDC-strategy search). One typed SearchSpace + a
ConvergenceChecker + an explore-then-exploit proposer, deterministic under a
fixed seed, wrapped by loop_admission_guard for dedup / runaway protection.

The idea of a single reusable bounded SearchSpace with explore-then-exploit
and a convergence/regression/plateau classifier is borrowed from
samirliu/chipagent's IterativeSearch engine; this implementation is
independent, chip-AGNOSTIC, and integrates the local AdmissionGuard.

Core objects:
    Dimension       one tunable knob (continuous / integer / enumerate / boolean)
    SearchSpace     a set of Dimensions; samples / clamps / perturbs points
    ConvergenceChecker  classifies a score history (CONVERGED / PLATEAU /
                    REGRESSION / EXHAUSTED / CONTINUE)
    IterativeSearch propose -> (caller evaluates) -> record, until done

Usage (library):
    space = SearchSpace([
        Dimension("buffers", "integer", lo=0, hi=64),
        Dimension("skew_ps", "continuous", lo=-50.0, hi=50.0),
        Dimension("strategy", "enumerate", choices=["mc", "false_path"]),
    ])
    checker = ConvergenceChecker(target=0.0, tolerance=1.0, patience=4)
    search = IterativeSearch(space, checker, maximize=True, seed=7)

    def evaluate(point):           # caller runs the real EDA tool here
        return -abs(point["skew_ps"])

    result = search.run(evaluate)
    print(result.status, result.best_point, result.best_score)

Usage (CLI -- runs a deterministic self-demo that converges a quadratic):
    python3 iterative_search.py --demo
    python3 iterative_search.py --demo --json out.json

No external tool dependencies -- pure Python.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable, Dict, List, Optional

import loop_admission_guard as _guard


# Convergence verdicts ------------------------------------------------------
CONVERGED = "CONVERGED"
PLATEAU = "PLATEAU"
REGRESSION = "REGRESSION"
EXHAUSTED = "EXHAUSTED"
CONTINUE = "CONTINUE"


# ---------------------------------------------------------------------------
# Search space
# ---------------------------------------------------------------------------
@dataclass
class Dimension:
    """One tunable knob.

    kind == "continuous" -> float in [lo, hi]
    kind == "integer"    -> int in [lo, hi]
    kind == "enumerate"  -> one of choices
    kind == "boolean"    -> True / False
    """
    name: str
    kind: str
    lo: Optional[float] = None
    hi: Optional[float] = None
    choices: Optional[List] = None

    def __post_init__(self):
        if self.kind in ("continuous", "integer"):
            if self.lo is None or self.hi is None:
                raise ValueError(f"dimension {self.name!r} needs lo/hi")
            if self.lo > self.hi:
                raise ValueError(f"dimension {self.name!r} lo>hi")
        elif self.kind == "enumerate":
            if not self.choices:
                raise ValueError(f"dimension {self.name!r} needs choices")
        elif self.kind == "boolean":
            pass
        else:
            raise ValueError(f"unknown dimension kind {self.kind!r}")

    def clamp(self, value):
        if self.kind == "continuous":
            return float(min(max(value, self.lo), self.hi))
        if self.kind == "integer":
            return int(round(min(max(value, self.lo), self.hi)))
        if self.kind == "enumerate":
            return value if value in self.choices else self.choices[0]
        if self.kind == "boolean":
            return bool(value)
        return value

    def sample(self, rng: random.Random):
        if self.kind == "continuous":
            return rng.uniform(self.lo, self.hi)
        if self.kind == "integer":
            return rng.randint(int(self.lo), int(self.hi))
        if self.kind == "enumerate":
            return rng.choice(self.choices)
        if self.kind == "boolean":
            return rng.random() < 0.5
        return None

    def perturb(self, value, rng: random.Random):
        """A small neighbour of `value` for the exploit phase."""
        if self.kind == "continuous":
            span = (self.hi - self.lo) or 1.0
            return self.clamp(value + rng.uniform(-0.1, 0.1) * span)
        if self.kind == "integer":
            span = max(1, int(round((self.hi - self.lo) * 0.1)))
            return self.clamp(value + rng.randint(-span, span))
        if self.kind == "enumerate":
            # mostly keep, occasionally jump to another choice
            if len(self.choices) > 1 and rng.random() < 0.34:
                others = [c for c in self.choices if c != value]
                return rng.choice(others) if others else value
            return value
        if self.kind == "boolean":
            return (not value) if rng.random() < 0.34 else value
        return value


@dataclass
class SearchSpace:
    dims: List[Dimension]

    def names(self) -> List[str]:
        return [d.name for d in self.dims]

    def bounds(self) -> Dict[str, tuple]:
        """Numeric (lo, hi) bounds, for handing to AdmissionGuard."""
        out = {}
        for d in self.dims:
            if d.kind in ("continuous", "integer"):
                out[d.name] = (d.lo, d.hi)
        return out

    def clamp(self, point: Dict) -> Dict:
        return {d.name: d.clamp(point.get(d.name)) for d in self.dims}

    def random_point(self, rng: random.Random) -> Dict:
        return {d.name: d.sample(rng) for d in self.dims}

    def neighbour(self, base: Dict, rng: random.Random) -> Dict:
        return {d.name: d.perturb(base.get(d.name), rng) for d in self.dims}


# ---------------------------------------------------------------------------
# Convergence
# ---------------------------------------------------------------------------
@dataclass
class ConvergenceChecker:
    """Classify a score history.

    target:         a score that, once reached (by best), means CONVERGED.
    tolerance:      |best - target| <= tolerance counts as reaching target.
    patience:       rounds of no improvement (> min_delta) before PLATEAU.
    min_delta:      smallest score change that counts as an improvement.
    regression_drop: a drop larger than this between the two latest rounds
                     is flagged as REGRESSION.
    """
    target: Optional[float] = None
    tolerance: float = 0.0
    patience: int = 4
    min_delta: float = 1e-9
    regression_drop: float = 0.0

    def _better(self, a: float, b: float, maximize: bool) -> bool:
        return (a > b + self.min_delta) if maximize else (a < b - self.min_delta)

    def classify(self, scores: List[float], maximize: bool = True) -> str:
        if not scores:
            return CONTINUE

        best = max(scores) if maximize else min(scores)

        # CONVERGED -- best meets target
        if self.target is not None and abs(best - self.target) <= self.tolerance:
            return CONVERGED
        if self.target is not None:
            reached = best >= self.target if maximize else best <= self.target
            if reached:
                return CONVERGED

        # REGRESSION -- latest round dropped sharply vs the one before
        if self.regression_drop > 0 and len(scores) >= 2:
            prev, last = scores[-2], scores[-1]
            drop = (prev - last) if maximize else (last - prev)
            if drop > self.regression_drop:
                return REGRESSION

        # PLATEAU -- no improvement for `patience` rounds
        if len(scores) > self.patience:
            recent = scores[-(self.patience + 1):]
            window_best = max(recent) if maximize else min(recent)
            improved = self._better(window_best, recent[0], maximize)
            if not improved:
                return PLATEAU

        return CONTINUE


# ---------------------------------------------------------------------------
# Iterative search
# ---------------------------------------------------------------------------
@dataclass
class SearchOutcome:
    status: str
    best_point: Dict
    best_score: float
    rounds: int
    history: List[dict] = field(default_factory=list)


class IterativeSearch:
    def __init__(self, space: SearchSpace, checker: ConvergenceChecker,
                 maximize: bool = True, seed: int = 0,
                 explore_rounds: int = 3, max_rounds: int = 20):
        self.space = space
        self.checker = checker
        self.maximize = maximize
        self.explore_rounds = explore_rounds
        self.max_rounds = max_rounds
        self._rng = random.Random(seed)
        self.guard = _guard.AdmissionGuard(
            bounds=space.bounds(), max_iterations=max_rounds)
        self.history: List[dict] = []   # [{"point":..., "score":...}]

    # -- helpers ------------------------------------------------------------
    def scores(self) -> List[float]:
        return [h["score"] for h in self.history]

    def best(self):
        if not self.history:
            return None, None
        key = (lambda h: h["score"]) if self.maximize else (lambda h: -h["score"])
        b = max(self.history, key=key)
        return b["point"], b["score"]

    # -- propose / record ---------------------------------------------------
    def propose(self) -> Optional[Dict]:
        """Return the next point to evaluate, or None if no admissible point
        could be found (budget exhausted / search space saturated)."""
        for _ in range(32):  # bounded retry to dodge duplicates
            if len(self.history) < self.explore_rounds or not self.history:
                cand = self.space.random_point(self._rng)
            else:
                base, _score = self.best()
                cand = self.space.neighbour(base, self._rng)
            res = self.guard.admit(cand)
            if res.admitted:
                return res.proposal
            if res.reason == "RUNAWAY_ITERATION_BUDGET":
                return None
        return None

    def record(self, point: Dict, score: float) -> None:
        self.history.append({"point": point, "score": score})

    def status(self) -> str:
        if len(self.history) >= self.max_rounds:
            base = self.checker.classify(self.scores(), self.maximize)
            return base if base in (CONVERGED, REGRESSION) else EXHAUSTED
        return self.checker.classify(self.scores(), self.maximize)

    # -- convenience driver -------------------------------------------------
    def run(self, evaluate: Callable[[Dict], float]) -> SearchOutcome:
        """Loop propose -> evaluate -> record until a terminal status."""
        while len(self.history) < self.max_rounds:
            point = self.propose()
            if point is None:
                break
            score = float(evaluate(point))
            self.record(point, score)
            st = self.checker.classify(self.scores(), self.maximize)
            if st in (CONVERGED, REGRESSION):
                break
        best_point, best_score = self.best()
        return SearchOutcome(
            status=self.status(),
            best_point=best_point or {},
            best_score=best_score if best_score is not None else float("nan"),
            rounds=len(self.history),
            history=list(self.history))


# ---------------------------------------------------------------------------
# CLI -- deterministic self-demo
# ---------------------------------------------------------------------------
def _demo() -> SearchOutcome:
    """Maximize -(x-3)^2 -(y+1)^2 over a bounded space; should converge near
    the optimum (x=3, y=-1, score=0) deterministically under seed=7."""
    space = SearchSpace([
        Dimension("x", "continuous", lo=-10.0, hi=10.0),
        Dimension("y", "continuous", lo=-10.0, hi=10.0),
    ])
    checker = ConvergenceChecker(target=0.0, tolerance=0.5, patience=6)
    search = IterativeSearch(space, checker, maximize=True, seed=7,
                             explore_rounds=5, max_rounds=40)

    def evaluate(p):
        return -((p["x"] - 3.0) ** 2 + (p["y"] + 1.0) ** 2)

    return search.run(evaluate)


def main(argv: list = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generic bounded iterative-search primitive (self-demo).")
    parser.add_argument("--demo", action="store_true",
                        help="Run the deterministic convergence demo")
    parser.add_argument("--json", default=None, help="Output JSON report path")
    args = parser.parse_args(argv)

    if not args.demo:
        parser.print_help()
        return 0

    outcome = _demo()
    report = asdict(outcome)
    report_json = json.dumps(report, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(report_json)
    print(report_json)
    # Demo is considered healthy if it converged.
    return 0 if outcome.status == CONVERGED else 1


if __name__ == "__main__":
    sys.exit(main())
