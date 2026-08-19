#!/usr/bin/env python3
"""A stall bound a self-test NAMES is a bound that races the host.

WHAT THIS GUARDS
----------------
`test_matrix_63x8_coverage.py` proves that its two supervisors renew their
stall window on SEMANTIC progress — a completed collection, a completed test —
and on nothing else. Four self-tests do that by driving the supervisor at a
deliberately tiny bound and watching what survives it.

`_watchdog.supervise` starts the stall clock when the child is SPAWNED::

    start = clock()
    last_progress = start

A child cannot emit a lifecycle record before its interpreter has booted,
`pytest` has imported, and collection has run. So the window those four tests
choose has to clear a FLOOR that belongs to the machine, not to the code they
are testing — and that floor is not a constant.

MEASURED on the pinned image (ghcr.io/vibeic/vibeic-eda:0.3.13, 32 cores), one
trivial module through the outcome machinery, three runs each::

    idle              0.402, 0.402, 0.402 s
    48 busy loops     0.821, 0.821, 0.808 s

The four bounds were 0.25, 0.3, 0.45, 0.45. The largest cleared the IDLE floor
by 48 ms and was beaten outright by a busy host, at which point the supervisor
correctly killed a healthy child and reported NORECORD. MEASURED, same image,
same unchanged tree, with 48 busy loops running::

    FAILED ...::test_live_collection_chatty_import_without_events_fails_closed
    FAILED ...::test_nested_outcome_run_outlives_old_fixed_bound_with_semantic_progress

Two reds on a tree nobody touched. This module refuses that shape: it MEASURES
the floor on the host actually running the suite, OBSERVES the bound each of
the four self-tests applies, and requires the second to clear the first.

WHY IT OBSERVES RATHER THAN READS
---------------------------------
It never greps the module for a number. It wraps the three supervised entry
points, records the bound in force at CALL time, and aborts the self-test
immediately afterwards — so what it judges is the value that reached the
supervisor, whatever expression produced it. A bound moved into a helper, a
fixture or a config file is measured exactly the same way.

`matrix_63x8/README.md` rule 3 is the reason: this codebase dispatches
dynamically and "PR #460 shipped a broken change *because* a grep could not see
this".
"""

from __future__ import annotations

import inspect
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Tuple

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
for _p in (str(_TESTS_DIR), str(_TESTS_DIR.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import test_matrix_63x8_coverage as CV       # noqa: E402

#: Generous enough that measuring the floor can never be killed by a bound.
_PROBE_STALL_S = 120
_PROBE_RUNS = 3

#: The production default both constants carry. Anything at or above it is a
#: real run or this module's own probe, never one of the four self-tests, so
#: this is what separates "the bound under test" from "the bound in service"
#: without naming a single test.
_PRODUCTION_STALL_S = 60

#: The bound must sit CLEAR of the floor. Deliberately weaker than the margin
#: the subject applies: this module states the invariant, and would still be
#: doing its job if the subject chose a different multiple.
_MIN_CLEARANCE = 2.0

#: kind -> (module attribute holding the bound, entry points to wrap)
_MACHINERY: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "collection": ("_COLLECTION_PROGRESS_STALL_S",
                   ("_collect_items_from_paths",)),
    "outcome": ("_OUTCOME_PROGRESS_STALL_S",
                ("_run_outcome_reports", "_run_one_module_outcome")),
}

#: The four self-tests that drive a supervisor at a bound of their own choosing.
_SELF_TESTS: Tuple[str, ...] = (
    "test_live_collection_relays_finite_semantic_progress_past_old_bound",
    "test_live_collection_chatty_import_without_events_fails_closed",
    "test_nested_outcome_run_outlives_old_fixed_bound_with_semantic_progress",
    "test_nested_outcome_chatty_import_without_pytest_events_fails_closed",
)


class _BoundRecorded(BaseException):
    """Abort the self-test the instant its bound is known.

    A `BaseException`, not an `Exception`: the subjects catch `AssertionError`
    and run inside `pytest.raises`, and a sentinel those can swallow would let
    a self-test keep running and report a bound this module never judged.
    """


def _measure_floor_s(kind: str) -> float:
    """Spawn-to-first-lifecycle-record latency this host imposes, in seconds.

    Uses the SAME machinery the bound applies to, over a module with one
    trivial test, so the number carries interpreter start, `pytest` import,
    collection and teardown. The WORST of `_PROBE_RUNS` is taken: a floor read
    off the best sample is a floor that only holds when the host is quiet.
    """
    attr, _entries = _MACHINERY[kind]
    previous = getattr(CV, attr)
    scratch = Path(tempfile.mkdtemp(prefix=f"guard_floor_{kind}_"))
    try:
        setattr(CV, attr, _PROBE_STALL_S)
        probe = scratch / "test_floor_probe.py"
        probe.write_text("def test_probe():\n    assert True\n",
                         encoding="utf-8")
        worst = 0.0
        for _ in range(_PROBE_RUNS):
            started = time.monotonic()
            if kind == "collection":
                CV._collect_items_from_paths((probe,), scratch)
            else:
                CV._run_outcome_reports((probe,), cwd=scratch)
            worst = max(worst, time.monotonic() - started)
        return worst
    finally:
        setattr(CV, attr, previous)


def _bounds_applied_by(name: str, tmp_path: Path) -> List[Tuple[str, float]]:
    """Every sub-production bound *name* hands to a supervisor.

    The wrapper reads the module attribute at CALL time, so a bound computed
    from a measurement, a fixture or a file is recorded exactly like a literal.
    Bounds at or above `_PRODUCTION_STALL_S` pass straight through untouched:
    those are real runs and this module's own floor probe, and stopping them
    would stop the subject from being able to measure anything.
    """
    recorded: List[Tuple[str, float]] = []
    func = getattr(CV, name)

    with pytest.MonkeyPatch().context() as patcher:
        for kind, (attr, entries) in _MACHINERY.items():
            for entry in entries:
                original = getattr(CV, entry)

                def _wrapped(*args, _kind=kind, _attr=attr,
                             _original=original, **kwargs):
                    bound = float(getattr(CV, _attr))
                    if bound >= _PRODUCTION_STALL_S:
                        return _original(*args, **kwargs)
                    recorded.append((_kind, bound))
                    raise _BoundRecorded(f"{_kind}={bound}")

                patcher.setattr(CV, entry, _wrapped)

        params = inspect.signature(func).parameters
        kwargs = {}
        inner = None
        if "monkeypatch" in params:
            inner = pytest.MonkeyPatch()
            kwargs["monkeypatch"] = inner
        if "tmp_path" in params:
            target = tmp_path / name
            target.mkdir(parents=True, exist_ok=True)
            kwargs["tmp_path"] = target
        try:
            func(**kwargs)
        except _BoundRecorded:
            pass
        finally:
            if inner is not None:
                inner.undo()

    return recorded


def test_the_floor_probe_measures_a_real_child(tmp_path):
    """CONTROL. A floor of zero would make every clearance below vacuous."""
    floors = {kind: _measure_floor_s(kind) for kind in sorted(_MACHINERY)}
    for kind, floor in floors.items():
        assert floor > 0.01, (
            f"the {kind} floor probe measured {floor:.4f}s, which no real "
            f"interpreter start takes. The probe is not running a child, so "
            f"every clearance this module reports would be measured against "
            f"nothing. Floors: {floors!r}")


@pytest.mark.parametrize("name", _SELF_TESTS)
def test_the_self_test_bound_clears_the_measured_host_floor(name, tmp_path):
    """No self-test may bound a supervisor inside its own start-up latency."""
    applied = _bounds_applied_by(name, tmp_path)
    assert applied, (
        f"{name} handed no sub-{_PRODUCTION_STALL_S}s bound to any supervised "
        f"entry point, so this cell measured nothing. Either it stopped "
        f"driving the supervisor — in which case it is no longer the thing "
        f"this module guards and belongs out of _SELF_TESTS — or it reaches "
        f"the supervisor by a path not wrapped here.")

    for kind, bound in applied:
        floor = _measure_floor_s(kind)
        assert bound >= floor * _MIN_CLEARANCE, (
            f"{name} bounds the {kind} supervisor at {bound:.3f}s while this "
            f"host needs {floor:.3f}s to get a child as far as its first "
            f"lifecycle record — a clearance of {bound / floor:.2f}x, below "
            f"the {_MIN_CLEARANCE}x this module requires. The stall clock "
            f"starts at SPAWN (`_watchdog.supervise`: `last_progress = "
            f"start`), so a bound this close is not measuring the mechanism "
            f"under test; it is measuring how busy the machine is, and it "
            f"reddens an unchanged tree whenever the machine is busy. "
            f"MEASURED on this image: the 0.45s constant cleared an idle "
            f"floor of 0.402s by 48ms and lost outright at 0.808s under 48 "
            f"busy loops. Derive the bound from a measurement of THIS host "
            f"and keep the old constant only as a floor.")
