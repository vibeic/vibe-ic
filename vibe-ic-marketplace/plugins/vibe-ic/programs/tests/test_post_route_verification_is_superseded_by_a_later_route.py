"""A DRT-0701 count was quoted for geometry two routes newer than it.

`router_post_route_verified_count` took the LAST `[WARNING DRT-0701]` anywhere
in the log. A single PnR pass runs `detailed_route` several times — the DRV
repair loop rips up and re-routes, antenna and PG paths can re-route again —
and OpenROAD emits DRT-0701 only when a route's verification DISAGREES with its
own loop. So a log routinely ends with more routes after the last 0701, and
that 0701 then describes geometry those routes replaced.

MEASURED (subservient x gf180mcuD, host 8HD-9, pinned image
...@sha256:66c33ff2..., OpenROAD 26Q3-1472, 2026-09-02):

    run                     last 0701   routes STARTED after it   loop's last
    round 3   (ksubs8)          3                0                     1   valid
    round 4   arm A             1                2                     1   stale
    round 5   pass @491         6                2                     3   STALE

The round-5 row is the one that bites, and it is this module's fixture. The
published count read **6** while the route that shipped measured **3** — and
the router's own DRC report, holding 3 records, was then REFUSED for failing to
reconcile with 6. That refusal silently disabled the residual-class guard that
reads the report, and the ladder grew the die on a number belonging to a route
that no longer existed.

Arm A was stale too and INVISIBLE, because there the stale and the true number
happened to be equal (1 == 1). That is the shape this test exists to stop: a
latent wrong reading that only surfaces when two numbers differ.

WHY DROPPING A STALE 0701 IS SOUND, and is not a widened threshold: a later
route either emits its OWN 0701 — which then becomes the last one and IS used —
or its verification agreed with its loop, in which case the loop's own last
count already is the verified count. Either way the trajectory's last element
ends up being the shipped route's number. Nothing is relaxed; a superseded
measurement simply stops being quoted for a route it does not describe.

DEGRADE LOUDLY: `router_post_route_verified_superseded` reports the dropped
value and how many routes superseded it, so "the verifier said nothing" stays
distinguishable from "the verifier spoke about a route that no longer exists".

THE DISCRIMINATOR IS `DRT-0194`, and it is chosen by measurement: the flow's
no-op re-routes do not emit it. The PG re-route on a design with no PG-dirty
net logged DRT-0178/0036/0179 and no DRT-0194, so a call that did nothing
cannot supersede a real verification.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PROG = Path(__file__).resolve().parent.parent / "_signoff_drc_format.py"
_spec = importlib.util.spec_from_file_location("_sdf_stale", _PROG)
_sdf = importlib.util.module_from_spec(_spec)
sys.modules["_sdf_stale"] = _sdf
_spec.loader.exec_module(_sdf)

_FIX = Path(__file__).resolve().parent / "fixtures" / "drt_residual_types"
_REAL = (_FIX / "openroad_round5_stale_verification.txt").read_text()

_VALID = (
    "[INFO DRT-0194] Start detail routing.\n"
    "[INFO DRT-0199]   Number of violations = 1.\n"
    "[WARNING DRT-0701] Post-route verification found 3 violation(s) that the "
    "routing loop did not report (1 in-loop). The published result is the "
    "verified one.\n")
_SUPERSEDED = _VALID + (
    "[INFO DRT-0194] Start detail routing.\n"
    "[INFO DRT-0199]   Number of violations = 2.\n")
_NOOP_AFTER = _VALID + (
    "[INFO DRT-0178] Init guide query.\n"
    "[INFO DRT-0036] Metal1 guide region query size = 7080.\n"
    "[INFO DRT-0179] Init gr pin query.\n"
    "[INFO DRT-0501] Runtime: 80.81s\n")


def test_a_verification_with_no_route_after_it_is_this_routes():
    assert _sdf.router_post_route_verified_count(_VALID) == 3
    assert _sdf.router_post_route_verified_superseded(_VALID) is None
    assert _sdf.router_iter_counts(_VALID)[-1] == 3


def test_a_verification_a_later_route_superseded_is_not_quoted():
    assert _sdf.router_post_route_verified_count(_SUPERSEDED) is None
    assert _sdf.router_post_route_verified_superseded(_SUPERSEDED) == (3, 1)
    # the trajectory's last element becomes the SHIPPED route's own count
    assert _sdf.router_iter_counts(_SUPERSEDED)[-1] == 2


def test_a_noop_reroute_does_not_supersede_anything():
    """The discriminator is `DRT-0194 Start detail routing`, not "some routing
    command ran". MEASURED: the PG re-route on a design with no PG-dirty net
    emits DRT-0178/0036/0179 and no DRT-0194 — it did nothing, so it cannot
    invalidate the verification before it."""
    assert _sdf.router_post_route_verified_count(_NOOP_AFTER) == 3
    assert _sdf.router_post_route_verified_superseded(_NOOP_AFTER) is None


def test_the_real_round5_pass_quotes_the_shipped_route_not_a_stale_one():
    """THE ARTEFACT THIS FIX EXISTS FOR — one real PnR pass, verbatim markers.

    Two DRT-0701s (3, then 6) and FOUR `Start detail routing` lines, two of
    them after the last 0701. The route that shipped measured 3."""
    assert _REAL.count("[INFO DRT-0194] Start detail routing") == 4
    assert _REAL.count("[WARNING DRT-0701]") == 2
    sup = _sdf.router_post_route_verified_superseded(_REAL)
    assert sup == (6, 2), sup
    assert _sdf.router_post_route_verified_count(_REAL) is None
    assert _sdf.router_iter_counts(_REAL)[-1] == 3, (
        "the published count must be the SHIPPED route's own last iteration, "
        "not the count a verification took two routes earlier")


def test_no_verification_at_all_is_still_None_not_zero():
    """Unchanged behaviour, re-asserted here because this fix adds a second way
    to return None and the two must not be confused with a clean design."""
    plain = ("[INFO DRT-0194] Start detail routing.\n"
             "[INFO DRT-0199]   Number of violations = 0.\n")
    assert _sdf.router_post_route_verified_count(plain) is None
    assert _sdf.router_post_route_verified_superseded(plain) is None
    assert _sdf.router_iter_counts(plain)[-1] == 0
