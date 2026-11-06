"""CZD-17 (ordrv5 ruling) — the route verdict is the FINAL count.

`drt_reconciliation` demanded that two readings agree which are taken at
DIFFERENT POINTS IN TIME:

  metric  `route__drc_errors`   OpenROAD emits it in FlexDR::end, BEFORE the
                                repair passes and before verifyRoute
                                (FlexDR.cpp:1714) — the state mid-loop.
  prose   `[INFO DRT-0702] Post-route verification: N violation(s).`
                                the whole-design verifyRoute — the FINAL
                                state, the geometry that ships.

So a difference is STRUCTURAL, not evidence of a broken tool, and refusing on
it records a converged route as UNKNOWN. RULING: the final count decides; the
in-loop count is diagnostic, recorded beside it; absence of ANY final reading
is still refused, because an unmeasured route must not read as a clean one.

The DRT excerpts below are copied verbatim from this lane's own RUN A
(subservient x gf180mcuD, image 0.3.46) — tool grammar only, chip-AGNOSTIC.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]


def _sdf():
    if str(PROGRAMS) not in sys.path:
        sys.path.insert(0, str(PROGRAMS))
    spec = importlib.util.spec_from_file_location(
        "_signoff_drc_format", PROGRAMS / "_signoff_drc_format.py")
    return _exec_registered("_signoff_drc_format", spec)


def _exec_registered(name, spec):
    """Execute a fresh copy under its real name, then restore the previous
    `sys.modules` entry. Left registered, the copy replaced the runner for
    every later test on the same xdist worker, whose monkeypatches then sat on
    a module their code under test no longer imported (d3 live measurement,
    pdn_em identity, r34 pad drop: red in the sweep, green alone)."""
    m = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(name)
    sys.modules[name] = m
    try:
        spec.loader.exec_module(m)
    finally:
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous
    return m


# RUN A: thirteen in-loop lines at 1, then the repair cleared the junction.
RUNA_TAIL = "\n".join(
    ["[INFO DRT-0199]   Number of violations = 1."] * 13
    + ["[INFO DRT-0703] Post-route verification: 5 violation(s) repaired.",
       "[INFO DRT-0702] Post-route verification: 0 violation(s)."])

# The shape the ruling names for rbsub2: the loop reported clean, the FINAL
# whole-design verify found five. A REAL non-convergence.
# NOTE: rbsub2's own log is not present on this host; this is a fixture of the
# stated shape, not a copy of that run.
RBSUB2_SHAPE = "\n".join(
    ["[INFO DRT-0199]   Number of violations = 0.",
     "[INFO DRT-0702] Post-route verification: 5 violation(s)."])


# The in-loop number that produced the historical refusal did NOT come from the
# log: `router_iter_last_count` already appends the post-route VERIFIED count,
# so the log side reads 0. It came from the metrics JSON, measured on RUN A:
#     detailedroute__route__drc_errors = 1        (FlexDR::end, mid-loop)
#     [INFO DRT-0702] ... 0 violation(s)          (verifyRoute, final)
RUNA_IN_LOOP_METRIC = 1


def test_runa_final_is_zero_though_the_metric_said_one():
    m = _sdf()
    assert m.router_post_route_final_count(RUNA_TAIL) == 0
    # the log side already resolves to the verified count ...
    assert m.router_iter_last_count(RUNA_TAIL) == 0
    # ... so the disagreement was metric(1) vs prose(0): two points in time.
    assert RUNA_IN_LOOP_METRIC != m.router_post_route_final_count(RUNA_TAIL)


def test_a_real_non_convergence_is_still_caught():
    """The ruling must not turn into 'trust the loop'. Final 5 is a failure."""
    m = _sdf()
    assert m.router_post_route_final_count(RBSUB2_SHAPE) == 5


def test_silence_is_not_zero():
    """No final line at all -> None, never 0. An unmeasured route must not read
    as a clean one; the step refuses on this."""
    m = _sdf()
    assert m.router_post_route_final_count(
        "[INFO DRT-0199]   Number of violations = 1.") is None
    assert m.router_post_route_final_count("") is None
