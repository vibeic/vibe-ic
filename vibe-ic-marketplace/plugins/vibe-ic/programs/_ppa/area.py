#!/usr/bin/env python3
"""Area: the taxonomy that keeps a PROXY and a PHYSICAL number apart.

WHY THIS MODULE EXISTS, AS A MEASUREMENT AND NOT AS AN OPINION
--------------------------------------------------------------
On one real completed run (`spm`, gf180mcuD, phase 3 complete) the three numbers
that all get called "the area" are:

    synthesis chip area   4703.5296   library area units, PRE-placement
    post-route core area  12294       um^2   (OpenROAD, post metal fill)
    die area              20164.00    um^2   (DEF DIEAREA 142.0 x 142.0 um)

The synthesis figure is 2.61x smaller than the core and 4.29x smaller than the
die, and it is not even in the same unit — the emitting artefact literally
declares `chip_area_unit: "cell-library area unit (as declared by the library
the synthesis script loaded)"`. So substituting one for the other is not an
approximation with an error bar. It is a different quantity, reported under the
same word.

The taxonomy therefore has three classes, and only one of them may ever answer
"how big is this chip":

    RTL_PROXY     cell count, wire count, and the reductions computed from them.
                  Counts, not extents. A count says nothing about the area of
                  what is fabricated: two netlists with the same cell count can
                  differ by any factor once drive strengths differ.
    SYNTH_PROXY   an AREA-shaped number produced before placement — yosys
                  `Chip area for module`, its sequential share. It has an area
                  unit, which is exactly what makes it dangerous: it looks
                  physical. It excludes placement density, filler, routing-driven
                  upsizing, the seal, and the die envelope.
    PHYSICAL      core area, die area, occupied standard-cell area, macro area,
                  utilisation — post-route, from the artefacts that exist.

`eligible_for_physical_ppa` is true for PHYSICAL and false for both proxies.
There is no metric for which it is conditionally true, because a conditional
would be the substitution this module exists to prevent.

THE RULE THAT IS THE POINT OF THE WHOLE FILE
--------------------------------------------
    A proxy comparison can never produce a SMALLER verdict.

Not "is down-weighted", not "is a tie-breaker": it cannot produce it at all. A
candidate that wins on cell count and loses on post-route core area is NOT
smaller, and a candidate that wins on cell count with no post-route evidence at
all is UNDETERMINED. `area_verdict` implements exactly that and its negative
fixture is that first sentence.

One more line runs alongside it, and it is not the same line: EXTENT vs RATIO.
`area.physical.utilization_pct` is PHYSICAL, post-route and measured, and it
still must not vote — a candidate at 40% where the baseline achieved 59.2% is
not a smaller chip, it is the same core with more empty space in it. So only
metrics that measure HOW BIG enter the verdict; the ones that measure WHAT
FRACTION are reported beside it and counted by nobody.

EXIT CODES (PPA_INTERFACES.md §1)
---------------------------------
    0 the physical evidence supports the smaller-area claim
    1 REFUSED — a finding about the design: it is not physically smaller
    2 UNDETERMINED — no physical evidence, mismatched scope, or absent input
    3 bad invocation

rc=1 is a claim about silicon. "I could not look" is 2 and prints a marker.

Source: `VIBE_IC_PPA_ENHANCEMENT_SPEC_v1.2_FINAL` §7.3; `docs/PPA_INTERFACES.md`
§1-§5. Issue PPA-009.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import _path_layout as _pl


def applied_area_metrics_tcl() -> str:
    """Measure logical standard-cell and core area on the shipped route DB.

    The runner places this tail after final DEF writes, including a resumed
    tail. Spacers, well taps and pads are excluded from the numerator. Missing
    DB data leaves the advisory unmeasured without killing routing.
    """
    return r'''
if {[catch {
  set _vic_block [ord::get_db_block]
  set _vic_rect [$_vic_block getCoreArea]
  set _vic_dbu [$_vic_block getDbUnitsPerMicron]
  if {$_vic_dbu <= 0} { error "invalid DB units" }
  set _vic_cell_area 0.0
  foreach _vic_inst [$_vic_block getInsts] {
    set _vic_master [$_vic_inst getMaster]
    if {[$_vic_master getType] in {CORE CORE_TIEHIGH CORE_TIELOW}} {
      set _vic_cell_area [expr {$_vic_cell_area +
          double([$_vic_master getWidth]) * [$_vic_master getHeight]}]
    }
  }
  set _vic_core_area [expr {double([$_vic_rect xMax] - [$_vic_rect xMin]) *
      ([$_vic_rect yMax] - [$_vic_rect yMin]) / ($_vic_dbu * $_vic_dbu)}]
  set _vic_cell_area [expr {$_vic_cell_area / ($_vic_dbu * $_vic_dbu)}]
  if {$_vic_core_area <= 0 || $_vic_cell_area <= 0} { error "empty area" }
  utl::metric_float vibeic__pnr__applied__cell_area_um2 $_vic_cell_area
  utl::metric_float vibeic__pnr__applied__core_area_um2 $_vic_core_area
} _vic_area_error]} {
  puts "PNR_APPLIED_AREA_NOT_MEASURED: $_vic_area_error"
}
'''

if __package__ in (None, ""):  # executed as a script, not imported
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from _ppa import canonical_json as _cj  # type: ignore  # noqa: E402
else:
    from . import canonical_json as _cj

__all__ = [
    "SCHEMA", "SCHEMA_VERDICT",
    "RTL_PROXY", "SYNTH_PROXY", "PHYSICAL", "AREA_CLASSES", "PROXY_CLASSES",
    "MEASURED", "NOT_MEASURED", "NOT_APPLICABLE", "INVALID", "ESTIMATED",
    "DERIVED", "STATUSES", "COMPARABLE_STATUSES", "VALUE_BEARING_STATUSES",
    "AreaMetricSpec", "AREA_METRICS",
    "UnknownAreaMetric", "AreaRecordError", "IneligibleForPhysicalPPA",
    "classify", "unit_of", "is_physical", "is_extent",
    "eligible_for_physical_ppa",
    "metrics_of_class", "area_record", "proxy_record", "physical_record",
    "digest_of_record", "assert_eligible_for_physical_ppa", "filter_physical",
    "scope_matches", "compare", "area_verdict", "main",
    "_step25_native_density_due",
]

SCHEMA = "vibeic.ppa.metric.v1"
SCHEMA_VERDICT = "vibeic.ppa.area_verdict.v1"

# ── the taxonomy ─────────────────────────────────────────────────────────────
RTL_PROXY = "RTL_PROXY"
SYNTH_PROXY = "SYNTH_PROXY"
PHYSICAL = "PHYSICAL"
AREA_CLASSES = (RTL_PROXY, SYNTH_PROXY, PHYSICAL)
PROXY_CLASSES = (RTL_PROXY, SYNTH_PROXY)

# ── statuses (PPA_INTERFACES.md §2) ──────────────────────────────────────────
MEASURED = "MEASURED"
NOT_MEASURED = "NOT_MEASURED"
NOT_APPLICABLE = "NOT_APPLICABLE"
INVALID = "INVALID"
ESTIMATED = "ESTIMATED"
DERIVED = "DERIVED"
STATUSES = (MEASURED, NOT_MEASURED, NOT_APPLICABLE, INVALID, ESTIMATED, DERIVED)
#: the only statuses whose value may enter a numeric comparison.
COMPARABLE_STATUSES = (MEASURED, DERIVED)
#: statuses that carry a number at all. ESTIMATED is one of them — an estimate
#: HAS a value, it just may never be compared against a measurement (§2). That
#: distinction is the whole reason a pre-synthesis estimator can publish its
#: figure without that figure being adoptable as a result.
VALUE_BEARING_STATUSES = (MEASURED, DERIVED, ESTIMATED)

# ── verdict / reason codes — a verdict never travels as bare prose ───────────
V_SMALLER = "SMALLER"
V_LARGER = "LARGER"
V_EQUAL = "EQUAL"
V_UNDETERMINED = "UNDETERMINED"

C_OK = "AREA_OK"
C_NOT_SMALLER = "AREA_NOT_SMALLER"
C_NO_PHYSICAL_EVIDENCE = "AREA_NO_PHYSICAL_EVIDENCE"
C_PROXY_ONLY = "AREA_PROXY_ONLY_NOT_A_VERDICT"
C_SCOPE_MISMATCH = "AREA_SCOPE_MISMATCH"
C_METRIC_MISMATCH = "AREA_METRIC_MISMATCH"
C_STATUS_NOT_COMPARABLE = "AREA_STATUS_NOT_COMPARABLE"
C_UNIT_MISMATCH = "AREA_UNIT_MISMATCH"
C_DISAGREEING_PHYSICAL = "AREA_PHYSICAL_METRICS_DISAGREE"
C_ZERO_BASELINE = "AREA_BASELINE_NOT_POSITIVE"
C_ABSENT_INPUT = "AREA_INPUT_ABSENT"


class AreaMetricSpec:
    """One area metric: its class, its unit, and whether it is an EXTENT.

    `is_extent` is the difference between "how big" and "what fraction".
    `area.physical.utilization_pct` is PHYSICAL, post-route and measured — and
    a candidate with a LOWER utilisation is not a smaller chip, it is the same
    chip with more empty space in it. Letting a ratio vote in a smaller-than
    verdict would reward exactly the wrong direction, so only extents vote.
    """

    __slots__ = ("name", "metric_class", "unit", "what", "is_extent")

    def __init__(self, name: str, metric_class: str, unit: str, what: str,
                 is_extent: bool = True):
        self.name = name
        self.metric_class = metric_class
        self.unit = unit
        self.what = what
        self.is_extent = is_extent

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"AreaMetricSpec({self.name!r}, {self.metric_class!r})"


def _spec(name: str, cls: str, unit: str, what: str, is_extent: bool = True
          ) -> Tuple[str, AreaMetricSpec]:
    return name, AreaMetricSpec(name, cls, unit, what, is_extent)


#: The registry. A metric that is not in here has no class, and a number with no
#: class is refused rather than guessed — an unknown name is the exact shape of
#: a new proxy quietly arriving on the physical side.
AREA_METRICS: Dict[str, AreaMetricSpec] = dict([
    # --- RTL_PROXY: counts and the reductions computed from counts ------------
    #
    # THE UNIT OF A COUNT IS `count`, NOT THE NAME OF THE THING COUNTED.
    # These three read "cells", "wires" and "wire_bits" until v1.11.33, and
    # every record built from them was refused by the canonical index:
    # `_ppa/metrics.unit_suffix_of` reads the `_count` suffix on the metric
    # NAME as a claim about the `unit` field, and "cells" is not "count".
    # Six records per run, from a producer and a consumer in the same lane.
    #
    # The name is what moved, not the rule. WHAT is counted is already stated
    # twice -- in the metric name and in the `what` string below -- so putting
    # it in `unit` bought nothing and cost the one cross-check that catches an
    # order-of-magnitude unit error. See PPA_INTERFACES.md §2, "a name that
    # ends in a unit suffix is a claim about the unit field".
    _spec("area.proxy.cell_count", RTL_PROXY, "count",
          "cells in a yosys netlist (generic or technology-mapped)"),
    _spec("area.proxy.wire_count", RTL_PROXY, "count",
          "wires in a yosys netlist"),
    _spec("area.proxy.wire_bit_count", RTL_PROXY, "count",
          "wire bits in a yosys netlist"),
    _spec("area.proxy.cell_count_reduction_pct", RTL_PROXY, "%",
          "100*(orig-opt)/orig over cell counts", is_extent=False),
    _spec("area.proxy.wire_count_reduction_pct", RTL_PROXY, "%",
          "100*(orig-opt)/orig over wire counts", is_extent=False),
    # --- SYNTH_PROXY: area-shaped, but pre-placement --------------------------
    _spec("area.synth.cell_area", SYNTH_PROXY, "lib_area_unit",
          "yosys `Chip area for module` — the liberty area of the mapped cells, "
          "before placement, filler, routing-driven upsizing or any envelope"),
    _spec("area.synth.sequential_area", SYNTH_PROXY, "lib_area_unit",
          "the sequential share of the above"),
    _spec("area.estimate.pre_synthesis_um2", RTL_PROXY, "um^2",
          "cell-count x a per-PDK area table, BEFORE synthesis has run. Its "
          "unit is um^2, which is exactly what makes it dangerous: it is an "
          "RTL_PROXY wearing a physical unit, and it is only ever ESTIMATED"),
    _spec("area.estimate.pre_synthesis_mm2", RTL_PROXY, "mm^2",
          "the above divided by 1e6"),
    # --- PHYSICAL: post-route, from artefacts that exist ----------------------
    _spec("area.physical.die_um2", PHYSICAL, "um^2",
          "DEF DIEAREA scaled by its own UNITS DISTANCE MICRONS"),
    _spec("area.physical.core_um2", PHYSICAL, "um^2",
          "the core (placeable) area, post-route"),
    _spec("area.physical.stdcell_um2", PHYSICAL, "um^2",
          "occupied standard-cell area, post-route"),
    _spec("area.physical.macro_um2", PHYSICAL, "um^2",
          "area occupied by hard macros, post-route"),
    _spec("area.physical.utilization_pct", PHYSICAL, "%",
          "achieved placement utilisation, post-route (the LAST reported value, "
          "never the first — the placer reprints it as it iterates). A RATIO, "
          "so it is reported but never voted: a lower utilisation is not a "
          "smaller chip", is_extent=False),
])


class UnknownAreaMetric(KeyError):
    """A metric name with no entry in AREA_METRICS. Refused, never guessed."""


class AreaRecordError(ValueError):
    """A record that does not satisfy the canonical metric contract."""


class IneligibleForPhysicalPPA(AreaRecordError):
    """A proxy or estimated number was offered where a physical one is required."""


# ── classification ───────────────────────────────────────────────────────────
def _spec_for(metric: str) -> AreaMetricSpec:
    try:
        return AREA_METRICS[metric]
    except KeyError:
        raise UnknownAreaMetric(
            f"unknown area metric {metric!r}; known: "
            f"{', '.join(sorted(AREA_METRICS))}") from None


def classify(metric: str) -> str:
    """RTL_PROXY / SYNTH_PROXY / PHYSICAL. Raises on an unregistered name."""
    return _spec_for(metric).metric_class


def unit_of(metric: str) -> str:
    return _spec_for(metric).unit


def is_extent(metric: str) -> bool:
    """Whether the metric measures HOW BIG rather than WHAT FRACTION."""
    return _spec_for(metric).is_extent


def is_physical(metric: str) -> bool:
    return classify(metric) == PHYSICAL


def eligible_for_physical_ppa(metric: str) -> bool:
    """Whether this metric may answer a question about the area of silicon.

    True for PHYSICAL only. Note this is the METRIC's eligibility; a record also
    has to carry a comparable STATUS — see `assert_eligible_for_physical_ppa`.
    """
    return is_physical(metric)


def metrics_of_class(metric_class: str) -> List[str]:
    if metric_class not in AREA_CLASSES:
        raise ValueError(f"unknown area class {metric_class!r}")
    return sorted(m for m, s in AREA_METRICS.items()
                  if s.metric_class == metric_class)


# ── record construction ──────────────────────────────────────────────────────
def area_record(
    metric: str,
    status: str,
    *,
    value: Optional[float] = None,
    scope: Optional[Mapping[str, Any]] = None,
    source: Optional[Mapping[str, Any]] = None,
    reason: Optional[str] = None,
    formula: Optional[str] = None,
    unit: Optional[str] = None,
    assumptions: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build one `vibeic.ppa.metric.v1` record, class-labelled.

    Validates the things that are cheap to get wrong and expensive to notice:

    * the metric is registered, so it HAS a class;
    * the unit is the registry's unit — passing a different one is refused
      rather than recorded, because a unit disagreement is the failure that made
      `chip_area` look like um^2;
    * MEASURED / DERIVED carry a value, a scope and a source; DERIVED also
      carries its formula (PPA_INTERFACES.md §3);
    * ESTIMATED carries a value AND an `assumptions` mapping with one entry per
      number: an estimate whose assumptions are not written down is
      indistinguishable from a measurement at the point somebody quotes it;
    * every remaining status carries a `reason` and NO value. There are no
      numeric sentinels: 0, -1 and "" never mean "not measured" (§2);
    * ESTIMATED is refused outright for a PHYSICAL metric. §2 says ESTIMATED is
      "never in final PPA", so the way to make a pre-synthesis estimate
      unadoptable as a physical measurement is to make the record un-buildable,
      not to label it and hope the reader checks.
    """
    spec = _spec_for(metric)
    if status not in STATUSES:
        raise AreaRecordError(
            f"status {status!r} is not one of {', '.join(STATUSES)}")
    if unit is not None and unit != spec.unit:
        raise AreaRecordError(
            f"{metric}: unit {unit!r} is not the registered unit {spec.unit!r}; "
            f"a unit disagreement is a different quantity, not a formatting "
            f"choice")
    if status == ESTIMATED and spec.metric_class == PHYSICAL:
        raise IneligibleForPhysicalPPA(
            f"{metric} is PHYSICAL and ESTIMATED is never final PPA "
            f"(PPA_INTERFACES.md §2); record the estimate under its own "
            f"pre-synthesis schema instead of under a physical metric name")

    rec: Dict[str, Any] = {
        "schema": SCHEMA,
        "metric": metric,
        "metric_class": spec.metric_class,
        "eligible_for_physical_ppa": (spec.metric_class == PHYSICAL
                                      and status in COMPARABLE_STATUSES),
        "status": status,
    }

    if status in VALUE_BEARING_STATUSES:
        if value is None:
            raise AreaRecordError(
                f"{metric}: status {status} requires a value; a missing number "
                f"is NOT_MEASURED with a reason, never a sentinel")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise AreaRecordError(f"{metric}: value must be a number")
        if value != value or value in (float("inf"), float("-inf")):
            raise AreaRecordError(
                f"{metric}: NaN/Infinity is NOT_MEASURED with a reason, not a "
                f"value (canonical_json refuses to serialize it anyway)")
        if not scope:
            raise AreaRecordError(
                f"{metric}: a number without a scope cannot be compared to "
                f"anything (PPA_INTERFACES.md §2)")
        if status in COMPARABLE_STATUSES and not source:
            raise AreaRecordError(
                f"{metric}: a measured number without a source cannot be "
                f"audited; numbers never travel alone")
        if status == DERIVED and not formula:
            raise AreaRecordError(
                f"{metric}: DERIVED requires the formula that produced it")
        if status == ESTIMATED and not assumptions:
            raise AreaRecordError(
                f"{metric}: ESTIMATED requires `assumptions` — every number in "
                f"an estimate states what it assumed, or the reader cannot "
                f"tell it from a measurement")
        rec["value"] = value
        rec["unit"] = spec.unit
        rec["scope"] = dict(scope)
        if source:
            rec["source"] = dict(source)
        if formula:
            rec["formula"] = formula
        if assumptions:
            rec["assumptions"] = dict(assumptions)
    else:
        if value is not None:
            raise AreaRecordError(
                f"{metric}: status {status} must not carry a value "
                f"(got {value!r}); it carries a reason")
        if not reason:
            raise AreaRecordError(
                f"{metric}: status {status} requires a reason — "
                f'"I could not read it" and "I read it and it was empty" must '
                f"never produce the same record")
        rec["reason"] = reason
        if scope:
            rec["scope"] = dict(scope)
        if source:
            rec["source"] = dict(source)
    return rec


def proxy_record(metric: str, status: str, **kw: Any) -> Dict[str, Any]:
    """`area_record` restricted to the proxy classes.

    A backend that parses a pre-placement tool calls THIS, so that a parser can
    never emit a physical claim no matter what it was handed.
    """
    if classify(metric) == PHYSICAL:
        raise IneligibleForPhysicalPPA(
            f"{metric} is PHYSICAL; a proxy producer may not emit it")
    return area_record(metric, status, **kw)


def physical_record(metric: str, status: str, **kw: Any) -> Dict[str, Any]:
    """`area_record` restricted to PHYSICAL metrics."""
    if classify(metric) != PHYSICAL:
        raise IneligibleForPhysicalPPA(
            f"{metric} is {classify(metric)}, not PHYSICAL; it may not be "
            f"promoted into a physical-area measurement")
    return area_record(metric, status, **kw)


def digest_of_record(rec: Mapping[str, Any]) -> str:
    """`sha256:<hex>` of the record, through the ONE serializer."""
    return _cj.digest_of(rec)


def assert_eligible_for_physical_ppa(rec: Mapping[str, Any]) -> None:
    """Raise unless `rec` may enter a physical-area measurement.

    This is the promotion guard. It refuses three separate ways of arriving at
    the same mistake: a proxy metric name, a comparable-looking status that is
    actually ESTIMATED, and a record that never carried a class at all.
    """
    if not isinstance(rec, Mapping):
        raise IneligibleForPhysicalPPA("not a metric record")
    metric = rec.get("metric")
    if not isinstance(metric, str):
        raise IneligibleForPhysicalPPA("record carries no metric name")
    cls = classify(metric)  # raises UnknownAreaMetric for an unregistered name
    if cls != PHYSICAL:
        raise IneligibleForPhysicalPPA(
            f"{metric} is {cls}; a proxy may not stand in for physical area")
    status = rec.get("status")
    if status not in COMPARABLE_STATUSES:
        raise IneligibleForPhysicalPPA(
            f"{metric} has status {status!r}; only "
            f"{'/'.join(COMPARABLE_STATUSES)} may enter a comparison")
    if rec.get("eligible_for_physical_ppa") is not True:
        raise IneligibleForPhysicalPPA(
            f"{metric} record is not flagged eligible_for_physical_ppa")


def filter_physical(records: Iterable[Mapping[str, Any]]
                    ) -> List[Dict[str, Any]]:
    """The records that may answer a physical-area question, and only those."""
    out: List[Dict[str, Any]] = []
    for r in records:
        try:
            assert_eligible_for_physical_ppa(r)
        except (IneligibleForPhysicalPPA, UnknownAreaMetric):
            continue
        out.append(dict(r))
    return out


# ── comparison ───────────────────────────────────────────────────────────────
def scope_matches(a: Optional[Mapping[str, Any]],
                  b: Optional[Mapping[str, Any]]) -> bool:
    """§2: two numbers are comparable only if their scope matches.

    Exact equality on the whole scope object, deliberately. A subset rule would
    let post-route be compared to synthesis whenever one side simply omitted the
    stage — and an omitted key is exactly how that would arrive.
    """
    if not isinstance(a, Mapping) or not isinstance(b, Mapping):
        # A scope read off disk can be a list, a string, or null. None of those
        # is a scope, so nothing is comparable to it — and that is a
        # not-comparable answer, not an exception two frames up.
        return False
    if not a or not b:
        return False
    try:
        return _cj.dumps(dict(a)) == _cj.dumps(dict(b))
    except (TypeError, ValueError):
        # a scope holding something JSON cannot represent (a set, NaN) is a
        # scope this comparison cannot establish equality for.
        return False


def _echo_scope(scope: Any) -> Any:
    """Echo a scope back into a refusal WITHOUT assuming it is a scope.

    The refusal is often "that is not a scope", so coercing it to a dict here
    raises inside the very branch that exists to report it.
    """
    return dict(scope) if isinstance(scope, Mapping) else scope


def _undet(code: str, why: str, **extra: Any) -> Dict[str, Any]:
    out = {"relation": V_UNDETERMINED, "code": code, "reason": why}
    out.update(extra)
    return out


def compare(baseline: Mapping[str, Any], candidate: Mapping[str, Any]
            ) -> Dict[str, Any]:
    """Compare two area records. Smaller value wins; ties are EQUAL.

    Returns a dict with `relation` in SMALLER/LARGER/EQUAL/UNDETERMINED and a
    machine-readable `code`. UNDETERMINED is a real answer here, not an error:
    it is what "these two numbers were never the same quantity" looks like.
    """
    bm, cm = baseline.get("metric"), candidate.get("metric")
    if bm != cm:
        return _undet(C_METRIC_MISMATCH,
                      f"{bm!r} and {cm!r} are different metrics; a comparison "
                      f"across metrics has no winner", metric=None)
    try:
        cls = classify(str(bm))
    except UnknownAreaMetric as ex:
        return _undet(C_METRIC_MISMATCH, str(ex), metric=bm)
    common = {"metric": bm, "metric_class": cls}
    for side, rec in (("baseline", baseline), ("candidate", candidate)):
        if rec.get("status") not in COMPARABLE_STATUSES:
            return _undet(C_STATUS_NOT_COMPARABLE,
                          f"{side} {bm} has status {rec.get('status')!r} — "
                          f"its value may not enter a numeric comparison",
                          **common)
    for side, rec in (("baseline", baseline), ("candidate", candidate)):
        v = rec.get("value")
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            # Reachable from the CLI: the record sets are read off disk and a
            # hand-written one can claim MEASURED and carry no number. That is
            # an UNDETERMINED comparison, never a crash and never a finding.
            return _undet(C_STATUS_NOT_COMPARABLE,
                          f"{side} {bm} claims status "
                          f"{rec.get('status')!r} but carries no numeric value "
                          f"(got {v!r})", **common)
        if v != v or v in (float("inf"), float("-inf")):
            return _undet(C_STATUS_NOT_COMPARABLE,
                          f"{side} {bm} carries {v!r}, which is not a number a "
                          f"comparison can use", **common)
    if baseline.get("unit") != candidate.get("unit"):
        return _undet(C_UNIT_MISMATCH,
                      f"{bm}: units differ "
                      f"({baseline.get('unit')!r} vs {candidate.get('unit')!r})",
                      **common)
    if not scope_matches(baseline.get("scope"), candidate.get("scope")):
        return _undet(C_SCOPE_MISMATCH,
                      f"{bm}: scopes differ, so these are different metrics "
                      f"wearing one name (PPA_INTERFACES.md §2)",
                      **common,
                      baseline_scope=_echo_scope(baseline.get("scope")),
                      candidate_scope=_echo_scope(candidate.get("scope")))
    bv, cv = float(baseline["value"]), float(candidate["value"])
    if bv <= 0:
        return _undet(C_ZERO_BASELINE,
                      f"{bm}: baseline is {bv}, which cannot anchor a relative "
                      f"area claim", **common)
    if cv < bv:
        rel = V_SMALLER
    elif cv > bv:
        rel = V_LARGER
    else:
        rel = V_EQUAL
    return {
        "relation": rel,
        "code": C_OK,
        "metric": bm,
        "metric_class": cls,
        "unit": baseline.get("unit"),
        "baseline_value": bv,
        "candidate_value": cv,
        "delta": round(cv - bv, 10),
        "delta_pct": round(100.0 * (cv - bv) / bv, 6),
        "eligible_for_physical_ppa": cls == PHYSICAL,
    }


def _index(records: Sequence[Mapping[str, Any]]) -> Dict[str, Mapping[str, Any]]:
    out: Dict[str, Mapping[str, Any]] = {}
    for r in records:
        m = r.get("metric")
        if isinstance(m, str):
            out[m] = r
    return out


def area_verdict(baseline: Sequence[Mapping[str, Any]],
                 candidate: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Is the candidate SMALLER than the baseline? Physical evidence only.

    THE RULE, and the whole reason the module exists:

      * every PHYSICAL EXTENT comparison that can be formed is formed, and they
        must AGREE. One physical extent saying LARGER outranks any number of
        proxies saying SMALLER — that is the negative fixture: a candidate that
        wins on cell count and loses on post-route core area is NOT smaller.
      * a physical RATIO (utilisation) is reported and NOT voted. A lower
        utilisation is not a smaller chip; it is the same chip with more empty
        space, and letting it vote would reward the wrong direction.
      * with no physical comparison available the verdict is UNDETERMINED. Not
        "SMALLER on the evidence we have". A proxy result is reported, clearly
        labelled, as advisory — it never becomes the verdict.
      * physical metrics that disagree with each other (die smaller, core
        larger) are UNDETERMINED too. Two answers is not an answer.

    Returns the verdict document; `main` maps it to an exit code.
    """
    b_idx, c_idx = _index(baseline), _index(candidate)
    shared = sorted(set(b_idx) & set(c_idx))

    physical_cmps: List[Dict[str, Any]] = []
    ratio_cmps: List[Dict[str, Any]] = []
    proxy_cmps: List[Dict[str, Any]] = []
    refused: List[Dict[str, Any]] = []
    for m in shared:
        try:
            cls, extent = classify(m), is_extent(m)
        except UnknownAreaMetric as ex:
            refused.append({"metric": m, "code": C_METRIC_MISMATCH,
                            "reason": str(ex)})
            continue
        cmp_ = compare(b_idx[m], c_idx[m])
        if cmp_["relation"] == V_UNDETERMINED:
            refused.append(cmp_)
            continue
        if cls != PHYSICAL:
            proxy_cmps.append(cmp_)
        elif extent:
            physical_cmps.append(cmp_)
        else:
            ratio_cmps.append(cmp_)

    doc: Dict[str, Any] = {
        "schema": SCHEMA_VERDICT,
        "physical_comparisons": physical_cmps,
        "physical_ratios_not_voted": ratio_cmps,
        "proxy_comparisons_advisory": proxy_cmps,
        "not_compared": refused,
        "physical_metrics_available": [c["metric"] for c in physical_cmps],
        "proxy_metrics_available": [c["metric"] for c in proxy_cmps],
    }

    if not physical_cmps:
        doc["verdict"] = V_UNDETERMINED
        if proxy_cmps:
            wins = [c["metric"] for c in proxy_cmps
                    if c["relation"] == V_SMALLER]
            doc["code"] = C_PROXY_ONLY
            doc["reason"] = (
                "no PHYSICAL EXTENT metric could be compared, so there is no "
                "area verdict. "
                + (f"{len(wins)} proxy metric(s) ({', '.join(wins)}) are "
                   f"smaller; a proxy is a count or a pre-placement estimate "
                   f"and may not stand in for post-route area."
                   if wins else
                   "The proxy comparisons that were formed are advisory only."))
        else:
            doc["code"] = C_NO_PHYSICAL_EVIDENCE
            doc["reason"] = (
                (f"{len(ratio_cmps)} physical RATIO comparison(s) were formed "
                 f"but a ratio is never voted; " if ratio_cmps else "")
                + "no area EXTENT metric could be compared: "
                + (f"{len(refused)} pair(s) refused "
                   f"({', '.join(sorted({str(r.get('code')) for r in refused}))})"
                   if refused else
                   "the two record sets share no metric name"))
        return doc

    rels = {c["relation"] for c in physical_cmps}
    if V_LARGER in rels and V_SMALLER in rels:
        doc["verdict"] = V_UNDETERMINED
        doc["code"] = C_DISAGREEING_PHYSICAL
        doc["reason"] = (
            "the physical area metrics disagree ("
            + "; ".join(f"{c['metric']} {c['relation']}" for c in physical_cmps)
            + "); two answers is not an answer")
        return doc
    if V_LARGER in rels or rels == {V_EQUAL}:
        doc["verdict"] = V_LARGER if V_LARGER in rels else V_EQUAL
        doc["code"] = C_NOT_SMALLER
        grew = [f"{c['metric']} {c['delta_pct']:+.4f}%" for c in physical_cmps
                if c["relation"] != V_SMALLER]
        proxy_wins = [c["metric"] for c in proxy_cmps
                      if c["relation"] == V_SMALLER]
        doc["reason"] = (
            "not smaller on physical area: " + ", ".join(grew)
            + (f" — despite {len(proxy_wins)} proxy metric(s) "
               f"({', '.join(proxy_wins)}) being smaller, which is exactly the "
               f"substitution this check refuses" if proxy_wins else ""))
        return doc
    # Everything left is SMALLER, or SMALLER mixed with EQUAL: nothing grew and
    # at least one extent shrank. Say which is which — "smaller on every metric"
    # would be false of the ones that only tied.
    doc["verdict"] = V_SMALLER
    doc["code"] = C_OK
    shrank = [c for c in physical_cmps if c["relation"] == V_SMALLER]
    tied = [c["metric"] for c in physical_cmps if c["relation"] == V_EQUAL]
    doc["reason"] = (
        "smaller on physical area: "
        + ", ".join(f"{c['metric']} {c['delta_pct']:+.4f}%" for c in shrank)
        + (f"; unchanged on {', '.join(tied)}" if tied else "")
        + ("; nothing grew" if not tied else ""))
    return doc


# ── CLI ──────────────────────────────────────────────────────────────────────
_MARK_CANNOT = "[CANNOT CHECK]"
_MARK_REFUSE = "[REFUSE]"


def _load_records(path_s: str, label: str) -> Tuple[Optional[List[Dict]], str]:
    """Read a record list. Returns (records, error) — never a silent empty.

    An absent file and a file holding an empty list must not produce the same
    answer, so the absent case returns an error string and the empty case
    returns `[]`.
    """
    p = Path(path_s)
    if not p.exists():
        return None, f"{label}: no such file: {p}"
    if not p.is_file():
        return None, f"{label}: not a file: {p}"
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as ex:
        return None, f"{label}: unreadable: {ex}"
    if not raw.strip():
        return None, f"{label}: file is empty: {p}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as ex:
        return None, f"{label}: not JSON: {ex}"
    if isinstance(data, dict):
        data = data.get("records", data.get("metrics"))
        if data is None:
            return None, (f"{label}: object has neither a 'records' nor a "
                          f"'metrics' list")
    if not isinstance(data, list):
        return None, f"{label}: expected a list of metric records"
    if not all(isinstance(x, dict) for x in data):
        return None, f"{label}: every entry must be a metric record object"
    return data, ""


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="_ppa.area",
        description=("Area taxonomy gate: refuse an area-improvement claim that "
                     "only a PROXY supports. rc 0 physically smaller, 1 REFUSED "
                     "(not smaller), 2 UNDETERMINED, 3 bad invocation."))
    ap.add_argument("--baseline", required=True,
                    help="JSON list of vibeic.ppa.metric.v1 area records")
    ap.add_argument("--candidate", required=True,
                    help="JSON list of vibeic.ppa.metric.v1 area records")
    ap.add_argument("--json", default=None, help="write the verdict document here")
    try:
        args = ap.parse_args(list(argv) if argv is not None else None)
    except SystemExit as ex:  # argparse exits 2; the contract says 3
        return 3 if (ex.code or 0) != 0 else 0

    base, b_err = _load_records(args.baseline, "--baseline")
    cand, c_err = _load_records(args.candidate, "--candidate")
    if b_err or c_err:
        doc = {
            "schema": SCHEMA_VERDICT,
            "verdict": V_UNDETERMINED,
            "code": C_ABSENT_INPUT,
            "reason": "; ".join(x for x in (b_err, c_err) if x),
        }
        print(f"{_MARK_CANNOT} area: {doc['reason']}", file=sys.stderr)
        _write_json(args.json, doc)
        return 2

    try:
        doc = area_verdict(base, cand)
    except (AreaRecordError, UnknownAreaMetric) as ex:
        doc = {"schema": SCHEMA_VERDICT, "verdict": V_UNDETERMINED,
               "code": C_METRIC_MISMATCH, "reason": str(ex)}
        print(f"{_MARK_CANNOT} area: {ex}", file=sys.stderr)
        _write_json(args.json, doc)
        return 2
    except Exception as ex:  # noqa: BLE001 - deliberate: see below
        # An unhandled exception here would leave Python to exit 1, and 1 in
        # this program means "the design is not smaller". A crash is an
        # INTERNAL ERROR (rc=3), never a claim about silicon.
        doc = {"schema": SCHEMA_VERDICT, "verdict": V_UNDETERMINED,
               "code": "AREA_INTERNAL_ERROR",
               "reason": f"{type(ex).__name__}: {ex}"}
        print(f"{_MARK_CANNOT} area: internal error — {type(ex).__name__}: {ex}",
              file=sys.stderr)
        _write_json(args.json, doc)
        return 3

    _write_json(args.json, doc)
    verdict, reason = doc["verdict"], doc["reason"]
    if verdict == V_SMALLER:
        print(f"area: SMALLER — {reason}")
        return 0
    if verdict == V_UNDETERMINED:
        print(f"{_MARK_CANNOT} area: UNDETERMINED — {reason}", file=sys.stderr)
        return 2
    print(f"{_MARK_REFUSE} area: {verdict} — {reason}", file=sys.stderr)
    return 1


#: R-0915-141. How much room over the THEORETICAL minimum the placer is given
#: when the core is not the one the auto-sizer produced. The natural density
#: (cell area / core area) is the fully-spread solution and the placer cannot
#: do better than it anywhere, so asking for exactly that leaves no slack for
#: row granularity or local clustering; 1.5x is slack without being a pack.
_PLACEMENT_SPREAD_HEADROOM = 1.5
#: The lowest `-density` worth asking OpenROAD's global placer for. Below this
#: the bin-density objective buys nothing and the solver gets numerically
#: unhappy; the value is CLAMPED and the clamp is DISCLOSED, never silent.
_PLACEMENT_DENSITY_FLOOR = 0.05
#: How far the FLOOR may sit above the design's OWN natural density before the
#: derived target stops describing this design at all.
#:
#: MEASURED, spm x gf180mcuD (lane icsub5, 2026-09-23), 273 cells in a
#: 2376x2376 um ring-pinned core — natural density 0.064 %, so the 0.05 floor
#: is 78x the natural. `global_placement -density 0.05` DIVERGED:
#:     | iter | overflow | HPWL         | d(HPWL) | gradient
#:     | 1880 |  0.4321  | 2.666727e+04 | +0.00%  | 3.00e+25
#:     | 2060 |  0.4321  | 2.666727e+04 | +0.00%  | 1.96e+29
#:     | 2080 |  0.3903  | 3.934455e+04 | +20.90% | 5.18e+29
#:     [ERROR GPL-0305] RePlAce diverged during gradient descent calculation,
#:     resulting in an invalid step length (Inf or NaN).
#: Overflow sat at 0.4321 for ~200 iterations with wirelength flat while the
#: density weight grew geometrically: the target was UNREACHABLE. 273 cells
#: cannot be spread to a uniform 5 % across 5.6 mm^2 — the row/bin granularity
#: cannot represent it — so the solver escalated the density force without
#: bound until the step length overflowed. `routed.def` was never written.
#: subservient, by contrast, sits at 2.09x (natural 2.39 %, floor 0.05) and
#: converges to a VERIFIED router_drc=0.
#: So the derived target is used only while the floor stays within this ratio
#: of the design's own density. Past it the design is too sparse for any
#: density target to describe, and today's number stands — DISCLOSED, never
#: silently.
_PLACEMENT_FLOOR_MAX_RATIO = 10.0


def real_core_placement_density(cell_area_um2: float, core_w: int, core_h: int,
                                ceiling: float) -> Tuple[Optional[float], str]:
    """`(density, basis)` for a core the auto-sizer did NOT size.

    R-0915-141. MEASURED, subservient x gf180mcuD as a DIE (lane icsub5, run2
    on main 1f537b5c0): the pad ring pinned the die at 1962x1962 um, R-0915-103
    made the core the 1176x1176 um interior, and `global_placement` was still
    handed `-density 0.30` -- the placement default, whose own help justifies it
    on a "spm 200x200 die". `-density` is an UPPER BOUND on bin occupancy, and
    the wirelength + timing objective packs right up to it, so on a core whose
    natural density is 2.39 % the placer compressed 2510 cells into
    33,057/0.30 = 110,190 um^2. The measured island was 42 tiles of 50x50 um =
    105,000 um^2 -- within 5 % of that prediction -- and ALL 3808 post-repair
    router violations, and all 41 of the shipped route's, fell inside it.

    The rectangle was never the problem: R-0915-103 is right that the core is
    the interior and the auto-sizer's answer is "never a lever on the
    rectangle". What survived the ring adoption was the DENSITY that belonged
    to the die nobody used.

    So when the core is not the auto-sized one, the target is derived from what
    will actually be placed in THAT core. It is CLAMPED ABOVE by the caller's
    own `--util`, which means this can only ever SPREAD a design, never pack
    one: a core that is already dense keeps today's number exactly.

    Returns `(None, why)` when it cannot be computed, and the caller then keeps
    the existing behaviour -- an unmeasurable density is not a licence to guess.
    """
    if cell_area_um2 <= 0:
        return None, "no measured cell area, so no natural density to derive"
    core_area = float(core_w) * float(core_h)
    if core_area <= 0:
        return None, "core area is not positive"
    natural = cell_area_um2 / core_area
    want = natural * _PLACEMENT_SPREAD_HEADROOM
    density = want
    clamped = ""
    if density < _PLACEMENT_DENSITY_FLOOR:
        # REACHABILITY, measured (GPL-0305 on spm — see the constant above).
        # A floor that towers over the design's own density is not a target the
        # placer can reach; asking for it makes RePlAce escalate the density
        # force until the step length overflows.
        if _PLACEMENT_DENSITY_FLOOR > natural * _PLACEMENT_FLOOR_MAX_RATIO:
            return None, (
                f"cell area {cell_area_um2:.0f}um^2 / core {core_w}x{core_h}um "
                f"= natural {100.0 * natural:.3f}%, and the placer floor "
                f"{_PLACEMENT_DENSITY_FLOOR:g} is "
                f"{_PLACEMENT_DENSITY_FLOOR / natural:.0f}x that — beyond the "
                f"{_PLACEMENT_FLOOR_MAX_RATIO:g}x this design's density can "
                f"reach, so no derived target describes it and the caller's "
                f"own value stands (GPL-0305 divergence, measured on spm)")
        density = _PLACEMENT_DENSITY_FLOOR
        clamped = (f"; raised to the placer floor {_PLACEMENT_DENSITY_FLOOR:g}"
                   f" (asked {want:.4f})")
    if density > ceiling:
        density = ceiling
        clamped = (f"; capped at the caller's --util {ceiling:g} — this rule "
                   f"only ever SPREADS, never packs (asked {want:.4f})")
    basis = (f"cell area {cell_area_um2:.0f}um^2 / core {core_w}x{core_h}um "
             f"({core_area:.0f}um^2) = natural {100.0 * natural:.2f}%, "
             f"x{_PLACEMENT_SPREAD_HEADROOM:g} headroom{clamped}")
    return density, basis


# ── N4 — `--die-um auto` sizes the CORE from the cells this netlist HAS ─────
# MEASURED, spm x gf180mcuD as a HARDMACRO (lane cmpb, 2026-09-28, image
# 0.3.83): the auto-sizer took the mean cell to be `site area x 6.0` -- a
# sky130-hd width in sites -- so 2.195 um^2 x 6 = 13.17 um^2, where this
# netlist's own synthesis stat says 8857.632 um^2 / 273 cells = 32.4 um^2.
# It then made that area the DIE and cut a 10 um inset out of it: an 85 um die,
# a 65 um core, OpenROAD `Effective utilization: 2.193`, and a core narrower
# than one period of the PDK's own power straps. No per-PDK constant can be
# right for every library, so there is none here: the area is READ -- from the
# synthesis stat bound to this exact netlist, else from each instance's own LEF
# SIZE -- and when neither can be read the caller is told so.


def lef_site_dims_um(lef_text: str, site_name: str = ""
                     ) -> Optional[Tuple[float, float]]:
    """`(width, height)` in um of a LEF SITE DEFINITION, or None.

    The definition is a bare `SITE <name>` line bounded by its `END <name>`;
    the `SITE <name> ;` inside every MACRO is a reference and is never read.
    Selection: the site literally named `site_name` (the one the floorplan
    builds rows from), else the first `CLASS CORE` site, else the first that
    parses. chip-AGNOSTIC: LEF grammar only.
    """
    if not isinstance(lef_text, str) or not lef_text:
        return None
    named = core = first = None
    want = (site_name or "").strip().lower()
    for m in re.finditer(r"^[ \t]*SITE[ \t]+([^\s;]+)[ \t\r]*$",
                         lef_text, re.MULTILINE | re.IGNORECASE):
        name = m.group(1)
        blk = lef_text[m.end():]
        end = re.search(rf"^[ \t]*END[ \t]+{re.escape(name)}[ \t\r]*$",
                        blk, re.MULTILINE | re.IGNORECASE)
        if end:
            blk = blk[:end.start()]
        sm = re.search(r"\bSIZE\s+([0-9.]+)\s+BY\s+([0-9.]+)\s*;",
                       blk, re.IGNORECASE)
        if not sm:
            continue
        try:
            w, h = float(sm.group(1)), float(sm.group(2))
        except ValueError:
            continue
        if not (w > 0 and h > 0):
            continue
        if want and name.lower() == want and named is None:
            named = (w, h)
        if core is None and re.search(r"\bCLASS\s+CORE\s*;", blk, re.IGNORECASE):
            core = (w, h)
        if first is None:
            first = (w, h)
    if named is not None:
        return named
    return core if core is not None else first


def synth_stat_cell_area_um2(netlist: Path) -> Tuple[Optional[float], str]:
    """The cell area the synthesis stat reports for THIS netlist, in um^2.

    Read from `<netlist dir>/stats.json` (schema `vibe-ic/synth-stats/1`) only
    when all three hold: the record names this netlist, its recorded sha256 is
    this file's, and its unit was ESTABLISHED as um^2 (liberty area checked
    against the cell LEF). A figure for another netlist, or in an unproven
    library unit, is not this design's area. Returns `(None, why)` otherwise.
    """
    try:
        import _yosys_stat as _ys  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        return None, f"_yosys_stat could not be imported: {exc}"
    stats = Path(netlist).parent / _ys.STATS_FILENAME
    try:
        rec = json.loads(stats.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"no readable synthesis stat at {stats.name} ({type(exc).__name__})"
    if not isinstance(rec, dict):
        return None, f"{stats.name} is not a record"
    named = Path(str(rec.get("netlist") or "").replace("\\", "/")).name
    if named != Path(netlist).name:
        return None, f"{stats.name} describes {named or 'no netlist'}, not {Path(netlist).name}"
    recorded = str(rec.get(_ys.NETLIST_DIGEST_FIELD) or "").strip().lower()
    if not recorded or recorded != _ys.netlist_digest(Path(netlist)):
        return None, f"{stats.name} is not bound to this netlist's sha256"
    area = rec.get("chip_area")
    ev = rec.get("chip_area_unit_evidence") or {}
    if not (isinstance(area, (int, float)) and area > 0):
        return None, f"{stats.name} carries no positive chip_area"
    if rec.get("chip_area_unit") != "um^2" or not (isinstance(ev, dict) and ev.get("established")):
        return None, f"{stats.name} chip_area unit is not established as um^2"
    return float(area), (f"synthesis stat {stats.name} (chip_area {float(area):g} um^2, "
                         f"bound to {recorded[:19]}…)")


def instance_cell_area_um2(master_counts: Mapping[str, int],
                           macro_sizes: Mapping[str, Tuple[float, float]]
                           ) -> Tuple[Optional[float], str]:
    """Sum of every instance's own LEF SIZE (w x h), or `(None, why)`.

    Every master must resolve: a sum over the masters that happened to be in
    one LEF is an under-count of unknown size, which is the defect this
    replaces in a different spelling.
    """
    if not master_counts:
        return None, "the netlist instantiates no cells"
    missing = sorted(m for m in master_counts if m not in macro_sizes)
    if missing:
        return None, (f"{len(missing)} master(s) carry no LEF SIZE "
                      f"(e.g. {', '.join(missing[:3])})")
    area = sum(n * macro_sizes[m][0] * macro_sizes[m][1]
               for m, n in master_counts.items())
    n = sum(master_counts.values())
    return float(area), (f"sum of {n} instances' LEF SIZE over "
                         f"{len(master_counts)} master(s)")


def _step25_native_density_due(project: Path, def_file: Path,
                               pdk: Any) -> bool:
    """Return whether the retained Step 25 native density result is stale.

    This is the area/density cache-admission predicate.  The phase-3 runner
    still decides when the producer runs; this module owns the input binding
    comparison and keeps that PPA logic beside the area taxonomy.
    """
    import em_current_density_check as emc

    binding = emc.validate_native_density(project)
    if not binding["valid"]:
        return True
    try:
        doc = json.loads((_pl.reports_phase3_dir(project) /
                          "em_openroad_density.json").read_text())
        return (doc["inputs"]["layout"]["sha256"] != emc._native_sha(def_file)
                or doc["pdk"] != {"name": pdk.name,
                                   "tech_lef": str(pdk.tech_lef)})
    except (OSError, ValueError, KeyError, TypeError):
        return True


def _write_json(path_s: Optional[str], doc: Mapping[str, Any]) -> None:
    if not path_s:
        return
    p = Path(path_s)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(_cj.dumps(doc), encoding="utf-8")
    tmp.replace(p)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
