#!/usr/bin/env python3
"""psm_analysis_coverage — which power nets did the grid analysis actually answer?

WHY
===
`analyze_power_grid` is invoked once per power net inside a Tcl `catch`, and a
failure prints `PSM_NONFATAL <net>: <err>` so the step keeps going. Keeping going
is right — one refused net must not abort a run.

But that marker appeared exactly ONCE in the whole programs tree: on the line
that writes it. Nothing read it, and the consequence is not a missing warning,
it is an INVERTED one.

A net whose analysis failed produces no `IR drop` line. The worst-case IR is
therefore the worst of the nets that SUCCEEDED, so the failure makes the number
SMALLER and the verdict likelier to pass. Measured on a real run:

    [ERROR PSM-0069] Check connectivity failed on <net>
    ir_drop.json verdict: PASS

The measurement failing improved the measured value. That is the shape worth
naming: not "a check did not run" but "a check that did not run made the result
look better".

WHAT THIS COMPUTES
==================
From the analysis log and the nets the run asked about:

    analysed          nets that produced an answer
    analysis_failed   nets the tool refused, from BOTH witnesses
    connectivity      PSM-0038 / PSM-0039 lines — unconnected shapes and
                      instances on nets that DID analyse

Two independent witnesses for failure: our own wrapper's `PSM_NONFATAL`, and
OpenROAD's own `PSM-0069 Check connectivity failed on <net>`. A wrapper that
stopped emitting its marker would otherwise silently restore the defect.

Connectivity findings are reported and NOT folded into the verdict: "the grid
has unconnected shapes" is a different question from "did the analysis run", and
conflating them would fire on grids that are merely imperfect.

Pure functions over text — no tool, no filesystem, so the rule is testable.
"""
from __future__ import annotations

import re
from typing import Dict, List, Sequence

_NONFATAL_RE = re.compile(r"PSM_NONFATAL\s+([^\s:]+)\s*:")
# The tool ends the sentence: `... failed on VDD.` — a greedy \S+ swallows the
# period and yields a net name that matches nothing. Caught by the test for the
# second witness, which is exactly the witness that would have gone quiet on
# every real log while looking implemented.
_PSM0069_RE = re.compile(
    r"PSM-0069\]\s*Check connectivity failed on\s+([^\s.,;:]+)")
_CONN_RE = re.compile(r"PSM-003[89]\]")


def analysis_coverage(log: str, power_nets: Sequence[str],
                      conn_cap: int = 20) -> Dict[str, List[str]]:
    """(analysed, analysis_failed, connectivity findings) for one run's log."""
    failed = ({m.group(1) for m in _NONFATAL_RE.finditer(log or "")}
              | {m.group(1) for m in _PSM0069_RE.finditer(log or "")})
    # A net named only by the tool and not by the run's own list is still a
    # failure worth reporting — the list can be wrong, the tool's line cannot be
    # about a net that does not exist.
    return {
        "analysed": sorted(set(power_nets) - failed),
        "analysis_failed": sorted(failed),
        "connectivity": [l.strip() for l in (log or "").splitlines()
                         if _CONN_RE.search(l)][:conn_cap],
    }


def ir_verdict(worst_ir_uv: float, budget_uv: float,
               analysis_failed: Sequence[str]) -> str:
    """PASS only when the budget holds AND every net produced an answer.

    Order matters: the budget comparison is meaningless over a partial set, so
    an incomplete analysis decides first.
    """
    if analysis_failed:
        return "FAIL"
    return "PASS" if worst_ir_uv <= budget_uv else "FAIL"


def verdict_basis(analysis_failed: Sequence[str]) -> str:
    if analysis_failed:
        return (f"analyze_power_grid failed on {', '.join(sorted(analysis_failed))} "
                f"— the worst-case IR reported is the worst of the nets that "
                f"SUCCEEDED and is not a statement about the design")
    return "worst static IR drop against the budget, all nets analysed"
