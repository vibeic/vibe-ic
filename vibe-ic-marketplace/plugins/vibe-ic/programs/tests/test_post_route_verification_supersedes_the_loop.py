"""OpenROAD publishes TWO route-DRC numbers and says which one ships.

After the detailed router's repair loop ends, OpenROAD runs a POST-ROUTE
VERIFICATION. When it disagrees with the loop it says so in its own words:

    [WARNING DRT-0701] Post-route verification found 1 violation(s) that the
    routing loop did not report (0 in-loop). The published result is the verified one.

"The published result is the verified one" — the tool is telling the reader which
of its two numbers describes the geometry that ships. Nothing parsed that line:
grepped across the whole repository, `DRT-0701` appeared only in a test fixture
and two comments, so `router_iter_last_count` returned the loop's SUPERSEDED
count.

MEASURED on a real gf180mcuD run of `spm` (2026-08-29, plugin 1.12.51):

    trajectory (DRT-0199)                     [251, 50, 50, 0]
    DRT-0701 post-route verification          1
    detailedroute__route__drc_errors (metrics) 1
    _drt_reading verdict                      DISAGREE — "METRIC=1 but LOG=0"

`_drt_reading` requires the metric and the prose to AGREE and fails the pnr step
when they do not — correctly, and deliberately: letting either side win silently
is the defect it exists to remove. So one unparsed line failed pnr, NO GDS was
ever streamed, and steps 31/36/38 failed with 37 MISSING. Four reds, one line.

WORSE THAN THE FALSE NUMBER: `_route_feedback_loosen_ex` decides whether to grow
the die from the trajectory, so a trailing 0 read as "still converging" and the
automatic rescue DECLINED to fire on a design that had not converged.

chip-AGNOSTIC: OpenROAD/TritonRoute log grammar only, no design specifics.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import _signoff_drc_format as sdf  # noqa: E402

_LOOP = (
    "[INFO DRT-0199]   Number of violations = 251\n"
    "[INFO DRT-0199]   Number of violations = 50\n"
    "[INFO DRT-0199]   Number of violations = 50\n"
    "[INFO DRT-0199]   Number of violations = 0\n")

_VERIFIED_DISAGREES = _LOOP + (
    "[WARNING DRT-0701] Post-route verification found 1 violation(s) that the "
    "routing loop did not report (0 in-loop). The published result is the "
    "verified one.\n")

_VERIFIED_AGREES = _LOOP + (
    "[WARNING DRT-0701] Post-route verification found 0 violation(s) that the "
    "routing loop did not report (0 in-loop). The published result is the "
    "verified one.\n")


def test_the_published_count_is_the_verified_one_not_the_loops():
    """The regression itself, stated as the property."""
    assert sdf.router_iter_last_count(_VERIFIED_DISAGREES) == 1, (
        "the reader returned the loop's superseded count while the router had "
        "already published a different verified one")


def test_the_loops_trajectory_is_still_readable():
    """The verified count is APPENDED, not substituted — `_drt_violation_trajectory`
    readers still need the loop's real history to judge convergence."""
    counts = sdf.router_iter_counts(_VERIFIED_DISAGREES)
    assert counts[:4] == [251, 50, 50, 0], counts
    assert counts[-1] == 1, counts


def test_a_log_without_the_verification_line_is_unchanged():
    """The control that matters most: without this, the fix is satisfied by code
    that rewrites every log's answer."""
    assert sdf.router_iter_counts(_LOOP) == [251, 50, 50, 0]
    assert sdf.router_iter_last_count(_LOOP) == 0


def test_a_verification_that_agrees_does_not_duplicate_the_count():
    assert sdf.router_iter_counts(_VERIFIED_AGREES) == [251, 50, 50, 0]
    assert sdf.router_iter_last_count(_VERIFIED_AGREES) == 0


def test_the_verifier_saying_nothing_is_not_the_verifier_finding_nothing():
    """None, never 0 — the same rule `router_iter_last_count` already holds for a
    log with no trajectory. Collapsing them would turn "this reader could not
    read the log" into "this design is DRC-clean"."""
    assert sdf.router_post_route_verified_count(_LOOP) is None
    assert sdf.router_post_route_verified_count("") is None
    assert sdf.router_post_route_verified_count(_VERIFIED_DISAGREES) == 1


def test_no_trajectory_at_all_is_still_undetermined():
    assert sdf.router_iter_last_count("nothing routed here") is None


# ---------------------------------------------------------------------------
# THE CONSUMER, NOT ONLY THE DONOR.
#
# Everything above asserts on `_signoff_drc_format`. That is the helper the fix
# was written into — but it is not the reader the rescue ladder calls. The
# runner keeps its OWN `_drt_violation_trajectory`, and it re-implemented the
# parse inline from the two shared regex aliases:
#
#     counts = _RE_DRT_0199.findall(log_text) or _RE_DRT_COMPLETING.findall(...)
#
# The DRT-0701 count is appended inside `router_iter_counts`, NOT by either
# pattern, so borrowing the patterns did not borrow the fix. MEASURED on the
# installed plugin cache at 1.12.58 (byte-identical to main 5fe1c183), against
# the very log this module's docstring is written about:
#
#     _drt_violation_trajectory(_VERIFIED_DISAGREES)  ->  [251, 50, 50, 0]
#     _drt_final_violations(_VERIFIED_DISAGREES)      ->  1
#     _drt_is_non_converging([251, 50, 50, 0])        ->  False
#     _route_feedback_loosen_ex(...)                  ->  (None, 'route_still_converging')
#
# which is, word for word, the consequence this module's docstring says the fix
# removed: "a trailing 0 read as 'still converging' and the automatic rescue
# DECLINED to fire on a design that had not converged."
#
# chip-AGNOSTIC: OpenROAD/TritonRoute log grammar only, no design specifics.
# ---------------------------------------------------------------------------

import importlib  # noqa: E402


def _runner():
    """Plain import, the idiom every other phase-3 test in this directory uses
    (`programs/` is on sys.path above). NOT `spec_from_file_location`: loading
    this module under a synthetic name leaves it out of `sys.modules`, and
    `dataclasses` then resolves a field annotation through
    `sys.modules.get(cls.__module__)` and dies on None — which reds every test
    in this block, CONTROLS INCLUDED, for a reason that has nothing to do with
    the property under test."""
    return importlib.import_module("phase3_one_shot_runner")


def test_the_runners_own_trajectory_reader_also_sees_the_verified_count():
    """The regression, stated against the reader the ladder actually calls."""
    mod = _runner()
    traj = mod._drt_violation_trajectory(_VERIFIED_DISAGREES)
    assert traj[:4] == [251, 50, 50, 0], traj
    assert traj[-1] == 1, (
        "the runner's trajectory reader returned the loop's superseded count "
        "while the router had already published a different verified one")


def test_the_docstrings_last_element_invariant_actually_holds():
    """`_drt_violation_trajectory` promises "The LAST element equals
    `_drt_final_violations`". Until this delegated, that sentence was false on
    exactly the logs the promise matters on."""
    mod = _runner()
    for log in (_LOOP, _VERIFIED_AGREES, _VERIFIED_DISAGREES):
        traj = mod._drt_violation_trajectory(log)
        assert traj[-1] == mod._drt_final_violations(log), (log, traj)


def test_the_rescue_engages_on_a_route_the_verifier_says_did_not_converge():
    """The consequence, not the parse: with the verified count in the
    trajectory, `_drt_is_non_converging` sees final=1 after a 0 (a CLIMB at the
    tail) and the die-loosen ladder fires instead of declining."""
    mod = _runner()
    traj = mod._drt_violation_trajectory(_VERIFIED_DISAGREES)
    assert mod._drt_is_non_converging(traj) is True, traj
    dims, reason = mod._route_feedback_loosen_ex(
        285, 285, _VERIFIED_DISAGREES, 0,
        auto_die_requested=True, route_completed=True, residual_history=[])
    assert reason != "route_still_converging", reason
    assert dims is not None, (
        "the rescue still declined on a route the router itself reported as "
        "unconverged")


def test_control_a_log_the_verifier_never_spoke_on_is_untouched():
    """THE CONTROL. Without it the fix is satisfied by code that rewrites every
    log's answer. These four inputs must read EXACTLY as they did before —
    three carry no DRT-0701 line at all, and the fourth carries one that
    AGREES, so none of them may move in either direction."""
    mod = _runner()
    assert mod._drt_violation_trajectory(_LOOP) == [251, 50, 50, 0]
    assert mod._drt_violation_trajectory(_VERIFIED_AGREES) == [251, 50, 50, 0]
    assert mod._drt_violation_trajectory("") == []
    assert mod._drt_violation_trajectory("GPL-0301 utilization 120%") == []


def test_control_the_declines_that_are_not_this_bug_still_decline():
    """The ladder's other refusals are untouched: an explicit die and a route
    that never completed still decline, with their own named reasons, on the
    same log that now engages the loosen path."""
    mod = _runner()
    assert mod._route_feedback_loosen_ex(
        285, 285, _VERIFIED_DISAGREES, 0,
        auto_die_requested=False, route_completed=True,
        residual_history=[]) == (None, "explicit_die_requested")
    assert mod._route_feedback_loosen_ex(
        285, 285, _VERIFIED_DISAGREES, 0,
        auto_die_requested=True, route_completed=False,
        residual_history=[]) == (None, "route_did_not_complete")


def test_control_a_genuinely_still_improving_route_is_still_not_loosened():
    """A trajectory whose tail is strictly DECREASING is a router that ran out
    of iterations, not a congested die — it must still decline. Guards against
    a fix that simply makes the ladder always fire."""
    mod = _runner()
    improving = (
        "[INFO DRT-0199]   Number of violations = 251\n"
        "[INFO DRT-0199]   Number of violations = 50\n"
        "[INFO DRT-0199]   Number of violations = 4\n")
    assert mod._drt_violation_trajectory(improving) == [251, 50, 4]
    assert mod._drt_is_non_converging([251, 50, 4]) is False
    assert mod._route_feedback_loosen_ex(
        285, 285, improving, 0, auto_die_requested=True,
        route_completed=True,
        residual_history=[]) == (None, "route_still_converging")
