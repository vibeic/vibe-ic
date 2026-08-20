#!/usr/bin/env python3
"""`_ppa/backends/orfs.py` — read ORFS AutoTuner output, and refuse its two lies.

This parser exists because the ORFS AutoTuner result row is ALMOST the record
the search layer wants, and the two places it is not are both invisible: they
typecheck, they plot, and they are wrong in a direction that flatters the run.

TRAP 1 — `step` IS NOT PROGRESS
===============================
`step` is a Ray Tune training ITERATION: how many times the trial reported its
objective back to the tuner. It has no relationship to how far through the
place-and-route flow the trial got. A trial that died in floorplan and a trial
that finished detailed routing can carry the same `step`, and a higher `step`
does not mean a more converged design.

The wrong implementation is one line -- `completed_stage = row["step"]` -- and
once it is in a manifest, every fidelity comparison downstream is comparing
things that were never at the same point in the flow. `completed_stage_of()`
therefore NEVER derives a stage from `step`. It reads an explicit stage field or
it returns None WITH A REASON, and `_ppa/search.Candidate.set_completed_stage`
rejects an integer by type as the second line of defence.

TRAP 2 — `num_drc` IS NOT SIGN-OFF DRC
======================================
`num_drc` counts DETAILED-ROUTE DRC violations, as reported by the router about
its own result. It is not a sign-off deck run, and it says nothing whatever
about LVS, antenna, IR, EM or logical equivalence.

Used as the anti-cheating term -- which is how a tuner naturally reaches for it,
because it is the only violation count in the row -- it lets a candidate that
never ran sign-off appear feasible, and `num_drc: 0` reads as "this design is
clean". So this parser emits TWO records for that one number: the
detailed-route count it genuinely is, MEASURED and scoped to `detailed_route`;
and the sign-off count it is not, explicitly NOT_MEASURED with the reason. The
second record is the important one. Contract §2: a report prints the literal
NOT_MEASURED row, it does not omit it.

A NUMBER WITHOUT A SCOPE IS NOT A MEASUREMENT
=============================================
Contract §2: two numbers are comparable only if their `scope` matches. An ORFS
row does not state which flow stage it describes, so the caller must supply it.
When it cannot, every record from that row comes back NOT_MEASURED -- not
MEASURED-with-a-blank-scope, which would silently join a comparison it does not
belong to. This is the same refusal as trap 1 seen from the other side: the
stage has to come from somewhere real or from nowhere at all.

WHAT THIS MODULE DOES NOT DO
============================
No thresholds. No verdicts. No eligibility. It never says "clean", "PASS",
"good" or "better". `_ppa/feasibility.py` decides what a violation count means
and `_ppa/search.py` decides what may be compared with what.

VERSION HONESTY
===============
`parse_row` reports `unmapped_keys` for every key it did not recognise. An ORFS
release that renames a field then surfaces as a named key nobody read, instead
of as a metric that quietly stopped appearing -- the failure mode where a report
gets shorter and no one notices.

chip-AGNOSTIC: no IC, vendor, SKU, process or PDK appears here.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

METRIC_SCHEMA = "vibeic.ppa.metric.v1"
PARSER = "_ppa/backends/orfs.py"
TOOL = "orfs"

# The Ray Tune bookkeeping keys. They describe the TUNER, not the design, and
# none of them is a design metric. They are listed so that `unmapped_keys` does
# not fill with noise -- an ignored key and an unrecognised key are different
# facts and the caller acts on only one of them.
TUNER_KEYS: Tuple[str, ...] = (
    "step", "training_iteration", "trial_id", "experiment_id", "iterations",
    "time_this_iter_s", "time_total_s", "timestamp", "pid", "hostname",
    "node_ip", "done", "should_checkpoint", "config", "date",
    "experiment_tag", "iterations_since_restore", "time_since_restore",
    "timesteps_since_restore", "timesteps_total", "episodes_total",
    "warmup_time", "perf",
)

# The stage an ORFS row might state explicitly. `step` is deliberately NOT here.
STAGE_KEYS: Tuple[str, ...] = ("completed_stage", "flow_stage", "stage")

# tool key -> (metric name, unit). Scope is supplied by the caller, never
# guessed: the row does not carry one.
NUMERIC_METRICS: Dict[str, Tuple[str, Optional[str]]] = {
    "worst_slack": ("timing.worst_slack_ns", "ns"),
    "clk_period": ("timing.clock_period_ns", "ns"),
    "total_power": ("power.total_w", "W"),
    "design_area": ("area.design_um2", "um^2"),
    "core_area": ("area.core_um2", "um^2"),
    "die_area": ("area.die_um2", "um^2"),
    "final_util": ("area.utilisation_fraction", None),
    "core_util": ("area.core_utilisation_fraction", None),
    "wirelength": ("route.wirelength_um", "um"),
    "num_instances": ("area.instance_count", None),
}

# The key this whole module exists for. Kept out of NUMERIC_METRICS so that a
# future editor adding a metric cannot accidentally give it the plain treatment.
DRC_KEY = "num_drc"

DETAILED_ROUTE_STAGE = "detailed_route"

NUM_DRC_LIMIT_REASON = (
    "ORFS `num_drc` is the DETAILED-ROUTE violation count the router reports "
    "about its own result. It is not a sign-off rule-deck run, and it carries "
    "no information about LVS, antenna, IR, EM or logical equivalence. A "
    "sign-off DRC count was NOT measured by this artefact."
)

NO_SCOPE_REASON = (
    "the ORFS row states no flow stage, and the caller supplied none. A number "
    "without a scope cannot enter a comparison (PPA_INTERFACES §2), and "
    "deriving the stage from the tuner's `step` would be false progress."
)

# `timing.worst_slack_ns` does not say setup or hold. The row does not either.
# Recording it as setup would be the parser asserting a check it never read.
WORST_SLACK_CHECK_NOTE = (
    "the tool key `worst_slack` does not state whether the check is setup or "
    "hold; `scope.check` is therefore null and this number is not comparable "
    "with a setup-scoped or hold-scoped one until the check is stated"
)


def completed_stage_of(row: Dict[str, Any]) -> Tuple[Optional[str], str]:
    """(stage, reason). NEVER derives a stage from `step`.

    Returns the explicitly stated stage, or None with the reason there is not
    one. The caller records the reason; it does not substitute a guess.
    """
    if not isinstance(row, dict):
        return None, "row is not an object"
    for k in STAGE_KEYS:
        v = row.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip(), f"stated explicitly by the row key {k!r}"
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return None, (
                f"row key {k!r} holds a number ({v!r}), not a stage name; a "
                "numeric stage is a tuner iteration counter in disguise and "
                "is refused")
    if "step" in row or "training_iteration" in row:
        return None, (
            "the row carries a Ray Tune iteration counter and no flow stage. "
            "`step` counts objective reports, not flow progress: the same "
            "value can mean 'died in floorplan' and 'finished routing', so it "
            "is NOT used as a stage.")
    return None, "the row states no flow stage"


def _record(metric: str, status: str, *, value: Any = None,
            unit: Optional[str] = None, scope: Optional[Dict[str, Any]] = None,
            source: Optional[Dict[str, Any]] = None,
            reason: Optional[str] = None,
            note: Optional[str] = None) -> Dict[str, Any]:
    """One canonical metric record (PPA_INTERFACES §2).

    NOT_MEASURED carries a `reason` and NO `value` key at all -- not a null, not
    a zero. Contract §2: no numeric sentinels, and an absent value must be
    absent rather than falsy, so no consumer can average it by accident.
    """
    rec: Dict[str, Any] = {"schema": METRIC_SCHEMA, "metric": metric,
                           "status": status}
    if status == "MEASURED":
        rec["value"] = value
        if unit is not None:
            rec["unit"] = unit
    else:
        rec["reason"] = reason or "not stated"
    rec["scope"] = dict(scope or {})
    rec["source"] = dict(source or {})
    rec["source"].setdefault("tool", TOOL)
    rec["source"].setdefault("parser", PARSER)
    if note:
        rec["note"] = note
    return rec


def parse_row(row: Dict[str, Any], *, stage: Optional[str] = None,
              scope: Optional[Dict[str, Any]] = None,
              source: Optional[Dict[str, Any]] = None,
              ) -> Dict[str, Any]:
    """One AutoTuner result row -> canonical records, plus what was NOT read.

    `stage` is the flow stage the caller knows this row describes. Supply it
    only if it is known; when it is absent AND the row does not state one,
    every record comes back NOT_MEASURED, which is the honest result of a
    number nobody can scope.

    Returns `{"records": [...], "completed_stage": str|None,
    "completed_stage_reason": str, "unmapped_keys": [...], "tuner_keys": [...]}`.
    """
    if not isinstance(row, dict):
        return {"records": [], "completed_stage": None,
                "completed_stage_reason": "row is not an object",
                "unmapped_keys": [], "tuner_keys": []}

    stated, why = completed_stage_of(row)
    resolved = stage or stated
    if stage and stated and stage != stated:
        why = (f"caller supplied {stage!r} and the row states {stated!r}; the "
               "caller's value is used and the disagreement is recorded")
    elif stage and not stated:
        why = f"supplied by the caller ({stage!r}); the row states none"

    base_scope = dict(scope or {})
    if resolved:
        base_scope["stage"] = resolved

    records: List[Dict[str, Any]] = []
    unmapped: List[str] = []
    tuner: List[str] = []

    for key in sorted(row):
        if key in TUNER_KEYS:
            tuner.append(key)
            continue
        if key in STAGE_KEYS:
            continue
        if key == DRC_KEY:
            records.extend(_drc_records(row[key], base_scope, source, resolved))
            continue
        spec = NUMERIC_METRICS.get(key)
        if spec is None:
            unmapped.append(key)
            continue
        name, unit = spec
        val = row[key]
        note = WORST_SLACK_CHECK_NOTE if key == "worst_slack" else None
        if not isinstance(val, (int, float)) or isinstance(val, bool):
            records.append(_record(
                name, "INVALID", scope=base_scope, source=source, note=note,
                reason=(f"the artefact carries {key!r}={val!r}, which is not a "
                        "number; the artefact exists but cannot support this "
                        "metric")))
            continue
        if resolved is None:
            records.append(_record(name, "NOT_MEASURED", scope=base_scope,
                                   source=source, reason=NO_SCOPE_REASON,
                                   note=note))
            continue
        # `scope.check` is stated as null rather than omitted, so a consumer
        # matching scopes sees a declared unknown instead of a missing key it
        # might treat as a wildcard.
        sc = dict(base_scope)
        if key == "worst_slack":
            sc["check"] = None
        records.append(_record(name, "MEASURED", value=val, unit=unit,
                               scope=sc, source=source, note=note))

    return {"records": records, "completed_stage": resolved,
            "completed_stage_reason": why, "unmapped_keys": unmapped,
            "tuner_keys": tuner}


def _drc_records(raw: Any, base_scope: Dict[str, Any],
                 source: Optional[Dict[str, Any]],
                 resolved: Optional[str]) -> List[Dict[str, Any]]:
    """`num_drc` becomes TWO records: what it is, and what it is not.

    The second record is the one that stops the cheat. Without it a manifest
    holds a single row saying `drc: 0` and every reader -- human and program --
    takes it for a sign-off result.
    """
    signoff_scope = dict(base_scope)
    signoff_scope["stage"] = "signoff"
    not_signoff = _record(
        "drc.signoff.violations", "NOT_MEASURED", scope=signoff_scope,
        source=source, reason=NUM_DRC_LIMIT_REASON)

    dr_scope = dict(base_scope)
    dr_scope["stage"] = DETAILED_ROUTE_STAGE

    if not isinstance(raw, (int, float)) or isinstance(raw, bool):
        return [_record("drc.detailed_route.violations", "INVALID",
                        scope=dr_scope, source=source,
                        reason=(f"num_drc={raw!r} is not a number")),
                not_signoff]
    if resolved is None:
        # The detailed-route count is self-scoping -- the number IS a
        # detailed-route number whatever stage the row belongs to -- so unlike
        # the other metrics it survives a missing caller stage.
        pass
    return [_record("drc.detailed_route.violations", "MEASURED", value=raw,
                    scope=dr_scope, source=source,
                    note=("this is the router's own count of its own result; "
                          "it is not a sign-off verdict and must not be used "
                          "as the eligibility term")),
            not_signoff]


def parse_rows(rows: Any, **kw: Any) -> List[Dict[str, Any]]:
    """`parse_row` over a list. A non-list gives an empty list, never a guess."""
    if not isinstance(rows, list):
        return []
    return [parse_row(r, **kw) for r in rows]
