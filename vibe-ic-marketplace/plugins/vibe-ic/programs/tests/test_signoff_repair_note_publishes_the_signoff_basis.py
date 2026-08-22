#!/usr/bin/env python3
"""The sign-off repair's NON-PROMOTED note must publish the number sign-off
judges, not the resizer's pre-reroute wire-load ESTIMATE.

MEASURED (subservient x sky130A): `step_signoff_spef_repair` kept the base
route -- a real SS-corner setup FAIL at -14.39 ns -- and published

    "no-op (base route kept): repair estimate -14.39->0.0003 ns, ..."

The +0.0003 is `SHIP_WNS_AFTER_REPAIR`, which this module's own
`_SHIP_POSTROUTE_CVG_TCL` comment describes as "measured with the set_wire_rc
wire-load model on the buffers/cells the pre-reroute repair just inserted/
resized", and which `_ship_repair_should_promote` deliberately refuses to key
on. The honest `SHIP_WNS_POSTROUTE` sat unpublished in the same parsed dict.
That published pair was then carried into three downstream round briefs as
"0.0003 ns from closing", for a design 14 ns from closing.

The same file already carries the other measured instance of the divergence
(sha256 x sky130A: SS setup +0.05 ns estimate -> -6.66 ns real), so this is a
CLASS, not one chip.

BIDIRECTIONAL NEGATIVE CONTROL: `_note()` below falls back to the VERBATIM
pre-fix literal when the new publisher is absent, so this file exercises the
pre-fix note against the pre-fix tree and FAILS there, and exercises the new
note and PASSES here. A test that could only fail on ImportError would prove
nothing about behaviour.

chip/PDK/vendor-AGNOSTIC: pure text assertions on a parsed dict.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import phase3_one_shot_runner as p3  # noqa: E402


def _note(parsed: dict) -> str:
    """Whatever the module publishes for the NON-PROMOTED repair exit."""
    fn = getattr(p3, "_ship_repair_nonpromotion_note", None)
    if fn is not None:
        return fn(parsed)
    # Pre-fix publisher, copied verbatim from the pre-fix
    # `step_signoff_spef_repair` non-promoted return.
    return (f"no-op (base route kept): repair estimate {parsed['wns_before']}->"
            f"{parsed['wns_after_repair']} ns, reroute violations="
            f"{parsed['route_violations']}; not promoted "
            f"(needs setup>=0 and DRC-clean).")


def _parsed(**kw) -> dict:
    base = {
        "wns_before": -14.39,
        "wns_after_repair": 0.0003,
        "wns_postroute": None,
        "route_violations": 0,
        "reroute_incomplete": 0,
    }
    base.update(kw)
    return base


# --- 1. the measured subservient shape: honest number EXISTS and must lead ---

def test_measured_signoff_slack_is_published_when_it_exists():
    note = _note(_parsed(wns_postroute=-14.39))
    assert "-14.39" in note
    assert "SIGN-OFF" in note.upper()


def test_estimate_is_labelled_an_estimate_not_a_result():
    note = _note(_parsed(wns_postroute=-14.39))
    assert "ESTIMATE" in note.upper()
    # and it must say what basis that estimate is on
    assert "set_wire_rc" in note


def test_divergence_between_estimate_and_signoff_basis_is_stated():
    note = _note(_parsed(wns_postroute=-14.39))
    assert "optimistic" in note.lower()
    # -14.39 real vs +0.0003 estimate == 14.3903 ns of optimism
    assert "14.39" in note


# --- 2. the honest number was NOT measured: no closure pair at all ----------

def test_unmeasured_signoff_slack_says_so():
    note = _note(_parsed(wns_postroute=None))
    assert "UNMEASURED" in note.upper()


def test_estimate_is_not_rendered_as_a_closure_pair_when_basis_unmeasured():
    """The exact shape that produced '0.0003 ns from closing'."""
    note = _note(_parsed(wns_postroute=None))
    assert "-14.39->0.0003" not in note.replace(" ", "")


def test_named_upstream_cause_is_carried_when_the_reroute_aborted():
    note = _note(_parsed(wns_postroute=None, reroute_incomplete=4))
    assert "SHIP_REROUTE_INCOMPLETE" in note


# --- 3. a genuinely-closing repair is NOT slandered by the new wording ------

def test_positive_signoff_slack_is_reported_without_an_optimism_claim():
    note = _note(_parsed(wns_before=-1.2, wns_after_repair=0.4,
                         wns_postroute=0.35))
    assert "0.35" in note
    # estimate 0.4 vs real 0.35 -> still optimistic, but only by 0.05
    assert "0.0500" in note or "0.05" in note


def test_estimate_pessimistic_vs_real_makes_no_optimism_claim():
    note = _note(_parsed(wns_before=-1.2, wns_after_repair=-0.9,
                         wns_postroute=-0.5))
    assert "optimistic" not in note.lower()


# --- 4. the ESTIMATE must never buy a PROMOTION ----------------------------
#
# Pre-fix the ONLY setup-closure criterion was `wns_after_repair` (the
# estimate); `wns_postroute` was consulted only to refuse a route WORSE than
# the base. A route that is merely no-worse-than-base, with an estimate
# reading >= 0, was therefore promoted as the SHIPPED sign-off route while its
# honest real-SPEF slack was deeply negative.


def _promote(**kw) -> bool:
    p = _parsed(route_violations=0, **kw)
    return p3._ship_repair_should_promote(p, True, True)


def test_optimistic_estimate_does_not_promote_a_route_that_gained_nothing():
    """subservient x sky130A: estimate +0.0003, real -14.39, base -14.39.

    Zero honest gain -- the estimate is the only thing carrying it.
    """
    assert _promote(wns_before=-14.39, wns_after_repair=0.0003,
                    wns_postroute=-14.39) is False


def test_an_honest_improvement_short_of_closure_still_promotes():
    """POLICY GUARD (not a negative control -- this passed pre-fix too).

    Closure is NOT the bar for promotion; being genuinely better is. A route
    that honestly moved -9.0 -> -6.66 ns is the better route and must ship,
    even though it has not closed. This test exists so the narrower rule above
    can never be widened into "refuse anything that did not close".
    """
    assert _promote(wns_before=-9.0, wns_after_repair=0.05,
                    wns_postroute=-6.66) is True


def test_a_genuinely_closed_route_is_still_promoted():
    """The fix must not refuse a real closure -- it only ADDS refusals."""
    assert _promote(wns_before=-1.2, wns_after_repair=0.4,
                    wns_postroute=0.35) is True


def test_absent_postroute_marker_leaves_the_old_decision_untouched():
    """Older/stubbed log: no honest number -> pre-existing behaviour stands."""
    assert _promote(wns_before=-1.2, wns_after_repair=0.4,
                    wns_postroute=None) is True


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
