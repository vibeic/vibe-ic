#!/usr/bin/env python3
"""analog_loop_liveness_check.py — a NULL over a DEAD LOOP certifies nothing.

WHY THIS PROGRAM EXISTS
-----------------------
MEASURED (u_hawaii_adc / ihp-sg13g2, rounds 18-20). A closed-loop analog block
was probed for two different defects over a conversion window, and both probes
returned a clean null:

    "the auto-zero node does not walk"   — vaz drift +0.0003 V/clock, flat
    "range is refuted"                   — code span 0.00 of 176.6 ideal

Both nulls were CORRECT ARITHMETIC ON A DEAD CIRCUIT. Over those same windows
the block's conversion counter never counted, so the reset was asserted 255/256
of the time; the quantiser never resolved (0 of 40 decisions); and the feedback
DAC was pinned at one reference for the entire window (0 edges). A comparator
that never resolves cannot kick, and coefficients cannot be exercised by a loop
that is held in reset. Two mechanisms were closed on that evidence and both had
to be reopened rounds later, when the same probes on a LIVE loop returned
+0.0037 V/clock (12x) and a de-saturating loop filter.

Nothing in the harness said the loop was dead. That is the defect this program
fixes: a null result is only evidence if the thing that would have produced a
non-null result was RUNNING. Reporting "no trend" over a window in which the
loop never closed is the analog shape of a vacuous pass.

WHAT LIVENESS IS, MEASURED — all three, over the reported window:

  1. RESET RELEASED     the reset node goes inactive, so the window has a
                        conversion phase at all
  2. FEEDBACK SWITCHING the DAC node takes both states after release. A DAC
                        pinned at one reference is an OPEN loop wearing a
                        closed loop's schematic
  3. DECISION RESOLVING the quantiser output resolves at least once. A latch
                        that never leaves precharge injects nothing and
                        decides nothing

Fail any one and the verdict is NOT_MEASURED (loop dead) with the failing
condition named — never "no trend", never a number.

CHIP-AGNOSTIC. Every node is an ARGUMENT. No design, block, net or vendor name
appears here; the program does not know what a conversion window is called in
any particular design, only that one was declared to it.

    analog_loop_liveness_check.py --samples-json S.json
        [--reset-node N --dac-node N --decision-node N --measure-node N]
        [--active-high/--active-low] [--vdd V] [--json out.json]

exit 0 → LIVE; any trend reported is evidence
exit 2 → NOT_MEASURED (loop dead): the window certifies nothing
exit 1 → the inputs themselves are unusable (missing node, empty window)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _atomic_artefact as _aa  # noqa: E402 — vibe-ic#1082

#: fraction of vdd above/below which a node counts as resolved to a rail
RAIL_FRACTION = 0.5
#: a DAC/decision excursion smaller than this fraction of vdd is not a state
#: change; it is settling.
EDGE_FRACTION = 0.4


def _edges(v: Sequence[float], thresh: float) -> int:
    """Number of times the signal crosses `thresh` in either direction."""
    n, above = 0, v[0] > thresh
    for x in v[1:]:
        if (x > thresh) != above:
            n += 1
            above = not above
    return n


def _released(v: Sequence[float], thresh: float, active_high: bool) -> bool:
    return any((x <= thresh) if active_high else (x > thresh) for x in v)


def _span(v: Sequence[float]) -> float:
    return max(v) - min(v)


def drift_per_step(t: Sequence[float], v: Sequence[float],
                   groups: int = 4) -> Optional[Dict[str, float]]:
    """Net drift of `v`, as the change between its first and last quarter.

    Deliberately a first-vs-last comparison, not a fit: the quantity this was
    written for oscillates within each group, and a fit over an oscillation
    reports a slope with a confidence it has not earned.
    """
    if len(v) < 2 * groups:
        return None
    k = max(1, len(v) // groups)
    a = sum(v[:k]) / k
    b = sum(v[-k:]) / k
    dt = t[-1] - t[0]
    return {"first_mean": a, "last_mean": b, "net_drift": b - a,
            "span_s": dt,
            "drift_per_second": (b - a) / dt if dt else 0.0}


def assess(samples: Dict[str, List[float]], *, time_key: str = "t",
           reset: Optional[str] = None, dac: Optional[str] = None,
           decision: Optional[str] = None, measure: Optional[str] = None,
           vdd: float = 1.2, reset_active_high: bool = True) -> Dict:
    """The whole judgement. Pure, so a caller can feed it any source."""
    out: Dict[str, object] = {"vdd": vdd}
    t = samples.get(time_key)
    if not t:
        return {"result": "UNUSABLE",
                "reason": f"no time vector under key {time_key!r}"}
    mid = vdd * RAIL_FRACTION
    edge_thresh = vdd * EDGE_FRACTION

    conditions: List[Dict[str, object]] = []

    def need(node: Optional[str], name: str, test, detail):
        if node is None:
            conditions.append({"condition": name, "state": "NOT_DECLARED",
                               "why": ("no node was named for this condition, "
                                       "so liveness cannot be established")})
            return
        v = samples.get(node)
        if not v:
            conditions.append({"condition": name, "state": "ABSENT",
                               "node": node,
                               "why": "named but not present in the samples"})
            return
        ok, extra = test(v)
        conditions.append({"condition": name, "node": node,
                           "state": "LIVE" if ok else "DEAD", **extra,
                           "why": detail})

    need(reset, "reset_released",
         lambda v: (_released(v, mid, reset_active_high),
                    {"fraction_asserted": round(
                        sum(1 for x in v if (x > mid) == reset_active_high)
                        / len(v), 6)}),
         "a window whose reset is never released has no conversion phase")
    need(dac, "feedback_switching",
         lambda v: (_edges(v, mid) > 0 and _span(v) >= edge_thresh,
                    {"edges": _edges(v, mid), "span_v": round(_span(v), 6),
                     # OCCUPANCY, reported and deliberately NOT a threshold.
                     # MEASURED: a window whose feedback sits at one
                     # reference 98.6% of the time passes this condition on
                     # edges and span alone, and it is barely more informative
                     # than a pinned one. But a converter legitimately near
                     # full scale ALSO has an occupancy near 0 or 1, so a
                     # floor here would refuse correct data. Liveness is a
                     # per-window question; only a SWEEP separates "near full
                     # scale" from "stuck", by asking whether the occupancy
                     # TRACKS the input. Reported so a reader sees it.
                     "low_state_fraction": round(
                         sum(1 for x in v if x <= mid) / len(v), 6)}),
         "a DAC pinned at one reference is an OPEN loop; nothing it does "
         "depends on the loop's state")
    need(decision, "decision_resolving",
         lambda v: (_span(v) >= edge_thresh,
                    {"edges": _edges(v, mid), "span_v": round(_span(v), 6)}),
         "a quantiser that never leaves precharge decides nothing and "
         "injects nothing")

    out["conditions"] = conditions
    dead = [c for c in conditions if c["state"] != "LIVE"]
    if dead:
        out["result"] = "NOT_MEASURED"
        out["reason"] = (
            "the loop was NOT LIVE over this window, so a null result here "
            "certifies nothing: " +
            "; ".join(f"{c['condition']}={c['state']}" for c in dead))
        out["measurement_withheld"] = (
            "a trend (or the absence of one) is reported ONLY over a live "
            "window. Reporting it here would be a vacuous pass.")
        return out

    out["result"] = "LIVE"
    if measure:
        v = samples.get(measure)
        if not v:
            out["result"] = "UNUSABLE"
            out["reason"] = f"measure node {measure!r} absent"
            return out
        d = drift_per_step(t, v)
        out["measure"] = {"node": measure, **(d or {}),
                          "note": None if d else "too few samples for a trend"}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples-json", required=True,
                    help="{node: [values...]} including a time vector")
    ap.add_argument("--time-key", default="t")
    ap.add_argument("--reset-node")
    ap.add_argument("--dac-node")
    ap.add_argument("--decision-node")
    ap.add_argument("--measure-node")
    ap.add_argument("--vdd", type=float, default=1.2)
    ap.add_argument("--reset-active-low", action="store_true")
    ap.add_argument("--json")
    a = ap.parse_args(argv)

    with open(a.samples_json) as fh:
        samples = json.load(fh)
    out = assess(samples, time_key=a.time_key, reset=a.reset_node,
                 dac=a.dac_node, decision=a.decision_node,
                 measure=a.measure_node, vdd=a.vdd,
                 reset_active_high=not a.reset_active_low)
    print(json.dumps(out, indent=2))
    if a.json:
        _aa.write_text(a.json, json.dumps(out, indent=2) + "\n")
    return {"LIVE": 0, "NOT_MEASURED": 2}.get(str(out["result"]), 1)


if __name__ == "__main__":
    sys.exit(main())
