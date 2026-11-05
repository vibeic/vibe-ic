"""v1.13.71 — DRT-0701 supersedes a stale `detailedroute__route__drc_errors`.

MEASURED CASE (the reason this exists), subservient x gf180mcuD, plugin
v1.13.70, image sha256:fad41245fbff, 2026-08-31:

    openroad.metrics.json  detailedroute__route__drc_errors = 1
    openroad.log           last [INFO DRT-0199] Number of violations = 1
                           [WARNING DRT-0701] Post-route verification found 2
                           violation(s) ... (1 in-loop). The published result
                           is the verified one.
    routed_router.drc.rpt  2 `violation type` records  <- the ground truth

`router_iter_counts` already appended the verified 2, so the prose read 2 while
the metric read 1; `reconcile` refused to issue any route verdict and pnr died
in ROUTE_DRC_METRIC_DISAGREEMENT. Route convergence was therefore recorded as
UNKNOWN for an IC whose route had demonstrably not converged.

NEGATIVE CONTROL is the load-bearing half: a disagreement that DRT-0701 does
NOT explain must still FAIL. The supersede fires only where the metric equals
the number OpenROAD itself labels "in-loop" — that equality is the proof, and
without it nothing is substituted.
"""
import sys
from pathlib import Path


_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import _signoff_drc_format as _sdf  # noqa: E402


_0701 = ("[WARNING DRT-0701] Post-route verification found {v} violation(s) "
         "that the routing loop did not report ({il} in-loop). "
         "The published result is the verified one.")


def _log(iter_counts, verified=None, in_loop=None):
    lines = ["[INFO DRT-0199]   Number of violations = %d." % c
             for c in iter_counts]
    if verified is not None:
        lines.append(_0701.format(v=verified, il=in_loop))
    return "\n".join(lines) + "\n"




# --- the pair reader -------------------------------------------------------

def test_pair_reads_both_numbers():
    assert _sdf.router_post_route_verified_pair(
        _0701.format(v=2, il=1)) == (2, 1)


def test_pair_is_none_without_the_in_loop_parenthetical():
    """A 0701 line naming only the verified count proves nothing about a
    metric, so it is not a pair and cannot license a substitution."""
    assert _sdf.router_post_route_verified_pair(
        "[WARNING DRT-0701] Post-route verification found 3 violation(s).") is None


def test_pair_is_none_on_a_silent_log():
    assert _sdf.router_post_route_verified_pair(_log([5, 2, 0])) is None


def test_pair_takes_the_last_0701():
    """A route that re-verifies more than once publishes the LAST word.
    MEASURED: the subservient log carries 0701 twice (lines 890 and 6521)."""
    text = _0701.format(v=3, il=0) + "\n" + _0701.format(v=2, il=1)
    assert _sdf.router_post_route_verified_pair(text) == (2, 1)


# --- the measured case -----------------------------------------------------





# --- NEGATIVE CONTROLS: these must still FAIL ------------------------------
