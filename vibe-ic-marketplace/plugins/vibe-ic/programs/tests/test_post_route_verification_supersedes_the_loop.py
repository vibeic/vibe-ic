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
