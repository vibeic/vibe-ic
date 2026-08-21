#!/usr/bin/env python3
"""`_ppa/backends/orfs.py` — read ORFS AutoTuner output, and refuse its sentinels.

This parser exists because the ORFS AutoTuner result row is ALMOST the record
the search layer wants, and every place it is not is invisible: it typechecks,
it plots, and it is wrong in the direction that flatters the run.

Everything below was MEASURED against the AutoTuner source, not assumed:
`tools/AutoTuner/src/autotuner/{utils.py,distributed.py}` at ORFS
`3476215b9`. Line numbers are from that revision and are quoted so a reader can
re-check them rather than trust this docstring.

TRAP 1 — `step` IS NOT PROGRESS
===============================
`step` is a Ray Tune training ITERATION. `distributed.py:163` is
`self.step_ += 1`, and `distributed.py:253` feeds it straight into the
objective as `(self.step_ / 100) ** (-1)`. It counts how many times the trial
reported back to the tuner and has no relationship to how far through the flow
the trial got: a trial that died in floorplan and one that finished detailed
routing can carry the same value.

The wrong implementation is one line -- `completed_stage = row["step"]` -- and
once it is in a manifest, every fidelity comparison downstream is comparing
things that were never at the same point in the flow. `completed_stage_of()`
NEVER derives a stage from `step`; it reads an explicit stage field or returns
None WITH A REASON, and `_ppa/search.Candidate.set_completed_stage` rejects an
integer by type as the second line of defence.

TRAP 2 — `num_drc` IS NOT SIGN-OFF DRC
======================================
`utils.py:427-428` reads it from `stage_name == "detailedroute"`,
`route__drc_errors`: it is the DETAILED-ROUTE violation count the router
reports about its own result. It is not a sign-off deck run, and it carries no
information about LVS, antenna, IR, EM or logical equivalence.

Used as the anti-cheating term -- which is exactly what ORFS does with it,
`distributed.py:253`, `score = ppa * ... + (gamma * metrics["num_drc"])` -- it
lets a candidate that never ran sign-off appear feasible, and `num_drc: 0`
reads as "this design is clean". So one `num_drc` becomes TWO records: the
detailed-route count it genuinely is, and an explicit NOT_MEASURED
`drc.signoff.violations` carrying the reason it is not. Contract §2: a report
prints the literal NOT_MEASURED row, it does not omit it.

FOUR NUMERIC SENTINELS, ALL MEASURED IN THE SAME FILE
=====================================================
Contract §2 forbids numeric sentinels -- `0`, `-1` and `""` never mean "not
measured". The AutoTuner uses four of them, and each one survives an
is-it-a-number check:

  S1  ERROR_METRIC = 9e99                                    utils.py:73
      An invalid config returns `{METRIC: 9e99, effective_clk_period: 9e99,
      num_drc: 9e99, die_area: 9e99}` (distributed.py:151-154), and a failed
      run returns four of them (distributed.py:250, utils.py:82). A naive
      parser publishes `MEASURED 9e99` -- a FAILED TRIAL AS A MEASUREMENT.

  S2  num_drc = wirelength = 0 when the flow stopped early   utils.py:418-419
          if stop_stage != "finish":
              num_drc = wirelength = 0
      A trial that stopped at floorplan reports zero violations and zero
      wirelength. This is the worst of the four, because `num_drc` is the
      penalty term in the score: a trial that never routed takes a ZERO DRC
      PENALTY and therefore scores BETTER than one that routed honestly and
      found violations. The objective function rewards early termination.

      This parser therefore treats `num_drc == 0` as MEASURED only when the
      resolved stage is `detailed_route` or above. Below it, or when the stage
      is unknown, a 0 is indistinguishable from the sentinel and the record is
      NOT_MEASURED -- "I could not tell" is not "clean".

  S3  clk_period = 9999999                                   utils.py:410
      "no clock constraint was found", published as a 9999999 ns period.

  S4  "ERR" string initialisers                              utils.py:411-417
      Un-produced metrics carry the literal string. Handled as INVALID: the
      artefact exists but cannot support the metric.

`worst_slack` IS SETUP, AND HOLD IS NEVER READ
==============================================
`utils.py:431-432` reads `timing__setup__ws`. So `worst_slack` is the SETUP
worst slack, definitively -- and the AutoTuner never reads a hold number at
all. Recording it as an unqualified "worst slack" would understate what is
known; recording it without saying hold is missing would overstate it. Both
records are emitted: `timing.setup.wns_ns` scoped `check: setup`, and
`timing.hold.wns_ns` as NOT_MEASURED. A tuner optimising this number is
optimising setup only, and hold is invisible to it -- the same shape as
`num_drc`, one term standing in for a vector.

A NUMBER WITHOUT A SCOPE IS NOT A MEASUREMENT
=============================================
Contract §2: two numbers are comparable only if their `scope` matches. An ORFS
row does not state which flow stage it describes, so the caller must supply it.
When it cannot, every record from that row comes back NOT_MEASURED -- not
MEASURED-with-a-blank-scope, which would silently join a comparison it does not
belong to.

WHAT THIS MODULE DOES NOT DO
============================
No thresholds. No verdicts. No eligibility. It never says "clean", "PASS",
"good" or "better". `_ppa/feasibility.py` decides what a violation count means
and `_ppa/search.py` decides what may be compared with what. Refusing a
sentinel is not a threshold: it is the parser declining to claim the tool said
something it did not say.

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

# `utils.py:73`. Any metric at or above this magnitude is the tuner's failure
# marker, not a number the flow produced.
ERROR_METRIC = 9e99

# `utils.py:410`. The initialiser for "no clock constraint was found".
NO_CLOCK_SENTINEL = 9999999

# The Ray Tune bookkeeping keys. They describe the TUNER, not the design. They
# are listed so `unmapped_keys` does not fill with noise -- an ignored key and
# an unrecognised key are different facts and the caller acts on only one.
TUNER_KEYS: Tuple[str, ...] = (
    "step", "training_iteration", "trial_id", "experiment_id", "iterations",
    "time_this_iter_s", "time_total_s", "timestamp", "pid", "hostname",
    "node_ip", "done", "should_checkpoint", "config", "date",
    "experiment_tag", "iterations_since_restore", "time_since_restore",
    "timesteps_since_restore", "timesteps_total", "episodes_total",
    "warmup_time", "perf", "minimum",
)

# The stage an ORFS row might state explicitly. `step` is deliberately NOT here.
STAGE_KEYS: Tuple[str, ...] = ("completed_stage", "flow_stage", "stage")

# tool key -> (metric name, unit). MEASURED against `utils.py:443-454`, which
# is the complete return of `read_metrics`. Scope is supplied by the caller,
# never guessed: the row does not carry one.
NUMERIC_METRICS: Dict[str, Tuple[str, Optional[str]]] = {
    "clk_period": ("timing.clock_period_ns", "ns"),
    "worst_slack": ("timing.setup.wns_ns", "ns"),
    "total_power": ("power.total_w", "W"),
    "core_util": ("area.core_utilisation_percent", "%"),
    "final_util": ("area.utilisation_percent", "%"),
    "design_area": ("area.design_um2", "um^2"),
    "core_area": ("area.core_um2", "um^2"),
    "die_area": ("area.die_um2", "um^2"),
    "wirelength": ("route.wirelength_um", "um"),
}

# The two keys this module exists for, kept OUT of the table above so that a
# future editor adding a metric cannot give either the ordinary treatment by
# adding one line.
DRC_KEY = "num_drc"
DERIVED_KEY = "effective_clk_period"

DETAILED_ROUTE_STAGE = "detailed_route"
SIGNOFF_STAGE = "signoff"

# Stages at or above which a detailed-route DRC count is a real number rather
# than `utils.py:418`'s early-stop zero.
_ROUTED_STAGES: Tuple[str, ...] = ("detailed_route", "post_route_extracted")

NUM_DRC_LIMIT_REASON = (
    "ORFS `num_drc` is the DETAILED-ROUTE violation count the router reports "
    "about its own result (utils.py:427-428, route__drc_errors from the "
    "detailedroute stage). It is not a sign-off rule-deck run, and it carries "
    "no information about LVS, antenna, IR, EM or logical equivalence. A "
    "sign-off DRC count was NOT measured by this artefact."
)

EARLY_STOP_ZERO_REASON = (
    "ORFS sets `num_drc = wirelength = 0` when the flow stopped before "
    "`finish` (utils.py:418-419), so a 0 here is indistinguishable from "
    "'the router never ran'. It is NOT reported as zero violations: `num_drc` "
    "is the penalty term in the AutoTuner objective (distributed.py:253), so "
    "reading the sentinel as a real zero rewards a trial for terminating "
    "early. Supply a completed stage of detailed_route or above to record it."
)

ERROR_METRIC_REASON = (
    "the value is ORFS's ERROR_METRIC sentinel 9e99 (utils.py:73), which the "
    "AutoTuner returns for an invalid config or a failed run "
    "(distributed.py:151-154, 250). It is a failure marker, not a measurement."
)

NO_CLOCK_REASON = (
    "`clk_period` is 9999999, the initialiser ORFS leaves in place when no "
    "clock constraint was found (utils.py:410). It is a sentinel, not a "
    "9999999 ns clock."
)

NO_SCOPE_REASON = (
    "the ORFS row states no flow stage, and the caller supplied none. A number "
    "without a scope cannot enter a comparison (PPA_INTERFACES §2), and "
    "deriving the stage from the tuner's `step` would be false progress."
)

HOLD_NOT_READ_REASON = (
    "the ORFS AutoTuner reads `timing__setup__ws` only (utils.py:431-432); it "
    "never reads a hold number. A search that optimises `worst_slack` is "
    "optimising setup alone, and hold is invisible to it."
)

EFFECTIVE_CLK_FORMULA = "clk_period - worst_slack"

EFFECTIVE_CLK_NOTE = (
    "COMPUTED by the tuner, not parsed from a flow report "
    f"(distributed.py:254, `{EFFECTIVE_CLK_FORMULA}`). Contract §3: hash the "
    "value you PARSED, never one you recomputed, so this is DERIVED and "
    "carries its formula."
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


def is_error_metric(value: Any) -> bool:
    """True for ORFS's 9e99 failure marker. Compared by magnitude, not
    equality, because the tuner also propagates it through arithmetic."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and abs(value) >= ERROR_METRIC


def _record(metric: str, status: str, *, value: Any = None,
            unit: Optional[str] = None, scope: Optional[Dict[str, Any]] = None,
            source: Optional[Dict[str, Any]] = None,
            reason: Optional[str] = None, formula: Optional[str] = None,
            note: Optional[str] = None) -> Dict[str, Any]:
    """One canonical metric record (PPA_INTERFACES §2).

    A non-MEASURED record carries a `reason` and NO `value` key at all -- not a
    null, not a zero. Contract §2: no numeric sentinels, and an absent value
    must be ABSENT rather than falsy, so no consumer can average it by
    accident.
    """
    rec: Dict[str, Any] = {"schema": METRIC_SCHEMA, "metric": metric,
                           "status": status}
    if status in ("MEASURED", "DERIVED"):
        rec["value"] = value
        if unit is not None:
            rec["unit"] = unit
        if status == "DERIVED":
            rec["formula"] = formula or "unstated"
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
            records.extend(_drc_records(row[key], base_scope, source,
                                        resolved))
            continue
        if key == DERIVED_KEY:
            records.append(_derived_record(row[key], base_scope, source,
                                           resolved))
            continue
        spec = NUMERIC_METRICS.get(key)
        if spec is None:
            unmapped.append(key)
            continue
        records.extend(_numeric_records(key, spec, row[key], base_scope,
                                        source, resolved))

    return {"records": records, "completed_stage": resolved,
            "completed_stage_reason": why, "unmapped_keys": unmapped,
            "tuner_keys": tuner}


def _numeric_records(key: str, spec: Tuple[str, Optional[str]], val: Any,
                     base_scope: Dict[str, Any],
                     source: Optional[Dict[str, Any]],
                     resolved: Optional[str]) -> List[Dict[str, Any]]:
    name, unit = spec
    sc = dict(base_scope)
    note = None
    extra: List[Dict[str, Any]] = []

    if key == "worst_slack":
        # MEASURED at utils.py:431-432 -- it is timing__setup__ws. Saying so is
        # more honest than a blank `check`, and the hold companion below is
        # what stops the setup number from standing in for a timing verdict.
        sc["check"] = "setup"
        note = "ORFS reads `timing__setup__ws` (utils.py:431-432)"
        extra.append(_record(
            "timing.hold.wns_ns", "NOT_MEASURED",
            scope=dict(base_scope, check="hold"), source=source,
            reason=HOLD_NOT_READ_REASON))

    if not isinstance(val, (int, float)) or isinstance(val, bool):
        return [_record(name, "INVALID", scope=sc, source=source, note=note,
                        reason=(f"the artefact carries {key!r}={val!r}, which "
                                "is not a number; the artefact exists but "
                                "cannot support this metric"))] + extra
    if is_error_metric(val):
        return [_record(name, "NOT_MEASURED", scope=sc, source=source,
                        note=note, reason=ERROR_METRIC_REASON)] + extra
    if key == "clk_period" and val == NO_CLOCK_SENTINEL:
        return [_record(name, "NOT_MEASURED", scope=sc, source=source,
                        note=note, reason=NO_CLOCK_REASON)] + extra
    if key == "wirelength" and val == 0 and resolved not in _ROUTED_STAGES:
        return [_record(name, "NOT_MEASURED", scope=sc, source=source,
                        note=note, reason=EARLY_STOP_ZERO_REASON)] + extra
    if resolved is None:
        return [_record(name, "NOT_MEASURED", scope=sc, source=source,
                        note=note, reason=NO_SCOPE_REASON)] + extra
    return [_record(name, "MEASURED", value=val, unit=unit, scope=sc,
                    source=source, note=note)] + extra


def _derived_record(val: Any, base_scope: Dict[str, Any],
                    source: Optional[Dict[str, Any]],
                    resolved: Optional[str]) -> Dict[str, Any]:
    """`effective_clk_period` is COMPUTED by the tuner, never parsed."""
    name = "timing.effective_clock_period_ns"
    if not isinstance(val, (int, float)) or isinstance(val, bool):
        return _record(name, "INVALID", scope=base_scope, source=source,
                       reason=f"effective_clk_period={val!r} is not a number")
    if is_error_metric(val):
        return _record(name, "NOT_MEASURED", scope=base_scope, source=source,
                       reason=ERROR_METRIC_REASON)
    if resolved is None:
        return _record(name, "NOT_MEASURED", scope=base_scope, source=source,
                       reason=NO_SCOPE_REASON)
    return _record(name, "DERIVED", value=val, unit="ns", scope=base_scope,
                   source=source, formula=EFFECTIVE_CLK_FORMULA,
                   note=EFFECTIVE_CLK_NOTE)


def _drc_records(raw: Any, base_scope: Dict[str, Any],
                 source: Optional[Dict[str, Any]],
                 resolved: Optional[str]) -> List[Dict[str, Any]]:
    """`num_drc` becomes TWO records: what it is, and what it is not.

    The second record is the one that stops the cheat. Without it a manifest
    holds a single row saying `drc: 0` and every reader -- human and program --
    takes it for a sign-off result.
    """
    signoff = _record("drc.signoff.violations", "NOT_MEASURED",
                      scope=dict(base_scope, stage=SIGNOFF_STAGE),
                      source=source, reason=NUM_DRC_LIMIT_REASON)
    dr_scope = dict(base_scope, stage=DETAILED_ROUTE_STAGE)
    name = "drc.detailed_route.violations"

    if not isinstance(raw, (int, float)) or isinstance(raw, bool):
        return [_record(name, "INVALID", scope=dr_scope, source=source,
                        reason=f"num_drc={raw!r} is not a number"), signoff]
    if is_error_metric(raw):
        return [_record(name, "NOT_MEASURED", scope=dr_scope, source=source,
                        reason=ERROR_METRIC_REASON), signoff]
    if raw == 0 and resolved not in _ROUTED_STAGES:
        # The measured trap. `utils.py:418` writes this zero when the flow
        # stopped early, and the score subtracts `gamma * num_drc`, so reading
        # it as a real zero pays a trial for not routing.
        return [_record(name, "NOT_MEASURED", scope=dr_scope, source=source,
                        reason=EARLY_STOP_ZERO_REASON), signoff]
    return [_record(name, "MEASURED", value=raw, scope=dr_scope, source=source,
                    note=("this is the router's own count of its own result; "
                          "it is not a sign-off verdict and must not be used "
                          "as the eligibility term")),
            signoff]


def parse_rows(rows: Any, **kw: Any) -> List[Dict[str, Any]]:
    """`parse_row` over a list. A non-list gives an empty list, never a guess."""
    if not isinstance(rows, list):
        return []
    return [parse_row(r, **kw) for r in rows]


#: WHY THIS BACKEND IS NOT DRIVEN FROM A PATH (`_ppa/backends/__init__.py`).
#: `parse_row`/`parse_rows` take AutoTuner result ROWS that the search layer
#: already holds in memory; there is no single artefact on disk that this
#: module is the reader of. Inventing a file format here would make this
#: parser the author of a document nobody writes.
NO_DRIVER_REASON = (
    "orfs parses AutoTuner result rows supplied by the search layer, not an "
    "artefact on disk: it has no path to be driven from. Call "
    "`_ppa.backends.orfs.parse_rows(rows)` from the code that holds the rows.")
