"""#576 — a guard refused before the rung that does not need what it guards.

`analog_one_shot_runner._try_native_a6_pv` abandoned native per-block PV before
naming a tool when the L19 `pdk_target` was null. The issue read that as "the
rung-1 resolver does not consume the field", which is half right, and the false
half is the load-bearing one: `resolve_pdk` DID read it, and refused on it —
BEFORE rung 1 was reached.

    tnorm = (target or "").strip()
    if not tnorm:
        return {"available": False, ..., "reason": "no target"}

    # ── rung 1: project-staged custom PDK (checked first, local-FS, cheap) ──

The comment says "checked first". The guard above it made that impossible.

WHAT RUNG 1 ACTUALLY NEEDS, measured by calling `_resolve_project_custom_pdk`
directly on a fixture staging exactly the canonical globs
(`pdk_analog_completeness_check._AXES`):

    target=None           -> available=True  rung=1
    target="custom_node"  -> available=True  rung=1

Identical. The target string is carried into the RESULT for the record; it is
not an input to the detection, which is a glob over `input/pdk/`. So a project
whose assets are all on disk was refused by a guard protecting a decision its
own subject does not participate in.

FOUR CALLERS DUPLICATED THE GUARD, which is why fixing the resolver alone would
have changed nothing observable. Two of them (`_try_native_a6_pv`,
`analog_mc_yield_run`) returned None before calling at all — and None reads to
their callers as "the native path does not apply", so the design's own staged
sign-off decks were never run and no tool was ever named.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import tempfile

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, _PROGRAMS / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


M = _load("analog_pdk_availability_probe", "analog_pdk_availability.py")


@pytest.fixture()
def staged_project():
    """A project staging a custom PDK at the canonical globs.

    Built from `pdk_analog_completeness_check._AXES` rather than from
    hand-written paths, so the fixture cannot drift from what the detector
    actually looks for — a guessed filename yields an empty detection and every
    assertion below would pass vacuously.
    """
    import pdk_analog_completeness_check as _pac
    root = pathlib.Path(tempfile.mkdtemp())
    for axis in ("spice_models", "drc_deck", "lvs_deck"):
        rel = _pac._AXES[axis][0].replace("**/", "").replace("*", "x")
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x\n", encoding="utf-8")
    return root


# ── the defect ───────────────────────────────────────────────────────────────
def test_a_staged_pdk_resolves_without_a_declared_target(staged_project):
    """The case the guard blocked."""
    res = M.resolve_pdk(None, project=str(staged_project))
    assert res["available"] is True, res
    assert res["rung"] == 1, res


def test_the_detection_does_not_depend_on_the_target_string(staged_project):
    """Declared or not, rung 1 answers the same — which is why guarding on the
    declaration was guarding the wrong thing."""
    a = M.resolve_pdk(None, project=str(staged_project))
    b = M.resolve_pdk("custom_node", project=str(staged_project))
    assert (a["available"], a["rung"]) == (b["available"], b["rung"])


# ── the accept cases: the guard still does its job for the other rungs ───────
def test_no_target_and_nothing_staged_is_still_unavailable():
    """Rungs 2 and 3 genuinely need a family name to match an installed
    directory against. Removing the guard entirely would have made this
    probe the container for a nameless family."""
    bare = pathlib.Path(tempfile.mkdtemp())
    res = M.resolve_pdk(None, project=str(bare))
    assert res["available"] is False
    assert res["rung"] is None


def test_the_dead_end_reason_distinguishes_itself():
    """`no target` could not tell "nothing declared" from "nothing declared AND
    nothing staged", and only the second is a real dead end. A reason that
    cannot distinguish them sends the reader to the wrong fix."""
    bare = pathlib.Path(tempfile.mkdtemp())
    reason = M.resolve_pdk(None, project=str(bare))["reason"]
    assert "no project-staged PDK" in reason, reason


def test_a_declared_target_with_nothing_staged_falls_through_to_rung_2():
    """Unchanged behaviour for the ordinary open-PDK case."""
    bare = pathlib.Path(tempfile.mkdtemp())
    res = M.resolve_pdk("sky130A", project=str(bare))
    assert res["available"] is False
    assert "rung 2" in str(res.get("reason", "")), res


# ── the callers must not re-close the door ───────────────────────────────────
@pytest.mark.parametrize("filename,func", [
    ("analog_one_shot_runner.py", "_try_native_a6_pv"),
    ("analog_mc_yield_run.py", None),
])
def test_no_caller_returns_early_on_a_missing_declaration(filename, func):
    """Four callers duplicated the guard. Fixing only the resolver would have
    changed nothing observable, so this asserts the callers as source.

    COMMENTS STRIPPED: each site's comment must name the removed guard in order
    to explain why it is gone, and a scan that cannot tell documentation from
    code has to be weakened the first time someone documents something.
    """
    src = (_PROGRAMS / filename).read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "if not declared:\n        return None" not in code, (
        f"{filename} still refuses before the resolver, so the resolver's "
        f"rung-1-first ordering cannot be reached")
    assert "#576" in src, (
        f"{filename} no longer records why the guard was removed; the next "
        f"reader restores it as an obvious missing check")


def test_the_native_pv_entry_point_reaches_the_resolver(staged_project):
    """End to end: the function that abandoned PV on its fourth line now gets
    far enough to produce a status dict.

    It returns `ran: False` here because no container exists in this harness —
    that is the honest answer, and it is a different answer from None, which
    its caller reads as "the native path does not apply".
    """
    A = _load("analog_one_shot_runner_probe", "analog_one_shot_runner.py")
    out = A._try_native_a6_pv(staged_project, "blk", "no-such-container")
    assert out is not None, (
        "still abandoning before the resolver — the caller cannot tell that "
        "from a project with no staged PDK at all")
    assert out.get("ran") is False
