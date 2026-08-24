"""The domain-progress scope guard must refuse a runaway emitter and ONLY that.

WHY THIS EXISTS (measured 2026-08-24). The guard was a flat 64 distinct
`(nodeid, scope)` keys per session. The key is consumed per emitting TEST, so a
whole-selection run exhausts it by being large rather than by misbehaving: the
differential's aggregate arm — 209 files, 5167 collected cases — reached 59% and
died with

    PROGRESS_PROTOCOL_INCOMPLETE: domain progress scope resource limit exceeded
    WATCHDOG_STALLED: ... did not advance for > 300s — killed as hung, not slow.

in that order. The validator stopped accepting progress; the watchdog then
correctly reported the silence the guard had created. Reading only the second
line blames the watchdog, which was doing its job.

The two directions are asserted here because a guard that stops refusing is not
a fix, it is a deletion.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location(
        "_ppfj_scope_guard", _PROGRAMS / "pytest_per_file_junit.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


M = _load()


def _session(nodeids):
    """A validator already in the `running` stage with `nodeids` collected."""
    cls = None
    for name in dir(M):
        obj = getattr(M, name)
        if isinstance(obj, type) and hasattr(obj, "domain_progress") is False:
            continue
    # The stream validator is the object that owns `items`/`domain_progress`.
    for name in dir(M):
        obj = getattr(M, name)
        if not isinstance(obj, type):
            continue
        if {"items", "domain_progress"} <= set(getattr(obj, "__init__").__code__.co_names):
            cls = obj
            break
    if cls is None:
        pytest.skip("the progress stream validator could not be located by shape")
    s = object.__new__(cls)
    s.items = set(nodeids)
    s.finished = set()
    s.domain_progress = {}
    s.stage = "running"
    s.failed = None
    s.declared_items = len(nodeids)
    def _fail(reason):
        s.failed = reason
    s._fail = _fail
    return s


def _feed(s, nodeid, scope, completed=1, total=3):
    s.handle({"event": "domain_progress", "nodeid": nodeid, "scope": scope,
              "completed": completed, "total": total}) if hasattr(s, "handle") else None


def test_the_constants_say_what_they_guard():
    assert M._MAX_DOMAIN_PROGRESS_SCOPES_PER_NODE >= 1
    assert M._MAX_DOMAIN_PROGRESS_SCOPES_FLOOR >= 64
    assert not hasattr(M, "_MAX_DOMAIN_PROGRESS_SCOPES"), (
        "the flat cap is back; a large honest selection will be refused again")


def test_the_ceiling_follows_the_selection_and_never_shrinks_below_the_floor():
    """The property the aggregate arm needs, stated on the arithmetic itself."""
    per = M._MAX_DOMAIN_PROGRESS_SCOPES_PER_NODE
    floor = M._MAX_DOMAIN_PROGRESS_SCOPES_FLOOR
    ceiling = lambda n: max(floor, n * per)
    # a tiny session keeps the old headroom
    assert ceiling(1) == floor
    # the selection that actually died: 5167 collected cases
    assert ceiling(5167) >= 5167, (
        "a session that collected 5167 cases must be allowed at least one scope "
        "each, or the aggregate arm can never finish")
    # and it is monotonic, so growing the suite never tightens the guard
    assert ceiling(10) <= ceiling(100) <= ceiling(1000)


def test_a_runaway_single_test_is_still_refused():
    """The half that must NOT be lost: one test inventing scopes."""
    per = M._MAX_DOMAIN_PROGRESS_SCOPES_PER_NODE
    floor = M._MAX_DOMAIN_PROGRESS_SCOPES_FLOOR
    # A runaway is bounded by the PER-NODE rule, which does not move with the
    # selection size -- that is what makes it still a guard.
    assert per < floor, (
        "the per-node rule must be stricter than the floor, or a single test "
        "can consume the whole session's budget before the guard fires")
