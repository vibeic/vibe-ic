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

    analysed              nets that produced an answer
    analysis_failed       nets the tool refused, from BOTH witnesses
    connectivity          PSM-0038 / PSM-0039 lines — unconnected shapes and
                          instances on nets that DID analyse
    unconnected_instances the PSM-0039 subset, as `<inst>/<pin>` terminals

Two independent witnesses for failure: our own wrapper's `PSM_NONFATAL`, and
OpenROAD's own `PSM-0069 Check connectivity failed on <net>`. A wrapper that
stopped emitting its marker would otherwise silently restore the defect.

THE SECOND DEFECT: A PROPERTY MEASURED, RECORDED, AND DECIDED BY NOTHING
=======================================================================
`connectivity` was reported and folded into no verdict, for a stated reason:
"the grid has unconnected shapes" is a different question from "did the
analysis run", and conflating them would fire on grids that are merely
imperfect. That reasoning holds for PSM-0038 — an unconnected SHAPE is a
floating island of metal, an imperfection, not a starved consumer.

It does NOT hold for PSM-0039. That line names an INSTANCE TERMINAL the grid
solver could not reach: a pin that consumes current with no conductor arriving.
The two were carried in one undifferentiated list, so the reason to not gate
the weaker one silently governed the stronger one too.

This matters because of what the flow gates INSTEAD. The supply question the
flow does decide is net OWNERSHIP — is a terminal's net pointer non-NULL. A
terminal attached to a declared rail that no metal reaches passes that test
perfectly: the pointer is valid, the name is right, and no conductor arrives.
Ownership is a LOGICAL property; being reached is a PHYSICAL one, and a rail
that is declared but not built satisfies the first while failing the second.
So the flow gated the property that cannot detect the defect, and left the
property that can — already computed, already written to the report — deciding
nothing.

Measured on a real run, from the tool's own log beside its own report::

    [WARNING PSM-0039] Unconnected instance <inst>/<pin> at location (...)
    [WARNING PSM-0039] Unconnected instance <inst>/<pin> at location (...)
    ir_drop.json  "unconnected_supply_pins": [ ...both of them... ]
    ir_drop.json  "verdict": PASS

The report named the field `unconnected_supply_pins` and still nothing read it.

So PSM-0039 now DECIDES, and PSM-0038 still does not. `unconnected_instances`
is the separation; `connectivity` keeps both and its meaning is unchanged.

Pure functions over text — no tool, no filesystem, so the rule is testable.
chip-AGNOSTIC: tool message IDs and the design's own instance paths. No design,
process, vendor or rail-name literal appears in any rule here.
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
# The 0039 line as the tool writes it today:
#     [WARNING PSM-0039] Unconnected instance <inst>/<pin> at location (x, y).
# `<inst>` is a hierarchical instance path, so the terminal is not one token.
_PSM0039_TERM_RE = re.compile(
    r"PSM-0039\]\s*Unconnected instance\s+(\S+)\s+at\b")
# Any 0039 line at all, whatever the sentence around the ID says.
_PSM0039_ANY_RE = re.compile(r"PSM-0039\]\s*(.*)")


def unconnected_instances(log: str) -> List[str]:
    """Instance supply terminals the grid solver reported it could not reach.

    UNCAPPED, unlike `connectivity`. That list is a display sample and says so;
    this one is a decision input whose LENGTH is quoted back in
    `verdict_basis`, and a length that silently saturates at a display cap is a
    measurement that reads "20" on a design with 500. Callers that render it
    cap at the point of rendering, where the truncation is visible.

    PSM-0039 ONLY. PSM-0038 — an unconnected SHAPE — is deliberately excluded:
    a floating island of supply metal is an imperfection, while an unreached
    instance terminal is a consumer with no conductor arriving. They were one
    list, and merging them is what let the reason to tolerate the first decide
    the second.

    EVERY 0039 line yields an entry. When the sentence has the shape the tool
    writes today the entry is the parsed `<inst>/<pin>`; otherwise it is the
    whole line after the ID. A witness that returns nothing because the tool
    reworded its sentence is the exact failure mode this module was written for
    — see `_PSM0069_RE` above, which lost every real log to a trailing period.

    Order-preserving and de-duplicated, so a count is a count of terminals.
    """
    seen: List[str] = []
    for line in (log or "").splitlines():
        m = _PSM0039_ANY_RE.search(line)
        if not m:
            continue
        term = _PSM0039_TERM_RE.search(line)
        entry = term.group(1) if term else (m.group(1).strip() or line.strip())
        if entry not in seen:
            seen.append(entry)
    return seen


def analysis_coverage(log: str, power_nets: Sequence[str],
                      conn_cap: int = 20) -> Dict[str, List[str]]:
    """(analysed, analysis_failed, connectivity, unreached terminals)."""
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
        "unconnected_instances": unconnected_instances(log),
    }


def ir_verdict(worst_ir_uv: float, budget_uv: float,
               analysis_failed: Sequence[str],
               unreached_terminals: Sequence[str]) -> str:
    """PASS only when the budget holds, every net produced an answer, AND no
    instance terminal was reported unreached.

    Order matters, and both prior conditions decide before the budget for the
    same reason. An incomplete analysis makes the comparison one over a partial
    set. An unreached terminal makes it one over a grid that does not deliver
    to a consumer the design contains — a smaller number computed on the paths
    that DO exist, which is a number about a different design. Neither is a
    tighter or looser budget; both are a budget applied to the wrong thing.

    `unreached_terminals` is REQUIRED, not defaulted. A caller that forgets it
    is the state this fix removes, and a default would let that state come back
    silently through any new call site.
    """
    if unreached_terminals:
        return "FAIL"
    if analysis_failed:
        return "FAIL"
    return "PASS" if worst_ir_uv <= budget_uv else "FAIL"


def verdict_basis(analysis_failed: Sequence[str],
                  unreached_terminals: Sequence[str]) -> str:
    reasons = []
    if unreached_terminals:
        reasons.append(
            f"the grid analysis reported {len(unreached_terminals)} instance "
            f"supply terminal(s) it could not reach "
            f"({', '.join(unreached_terminals[:6])}"
            f"{' …' if len(unreached_terminals) > 6 else ''}) — those "
            f"terminals are OWNED by a supply net and no conductor of it "
            f"arrives, so the worst-case IR is the worst over the paths that "
            f"do exist and is not a statement about the design")
    if analysis_failed:
        reasons.append(
            f"analyze_power_grid failed on "
            f"{', '.join(sorted(analysis_failed))} — the worst-case IR "
            f"reported is the worst of the nets that SUCCEEDED and is not a "
            f"statement about the design")
    if reasons:
        return "; ".join(reasons)
    return ("worst static IR drop against the budget, all nets analysed, no "
            "unreached instance supply terminal")
