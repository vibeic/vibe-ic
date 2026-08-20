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
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

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
    "classify", "unit_of", "is_physical", "eligible_for_physical_ppa",
    "metrics_of_class", "area_record", "proxy_record", "physical_record",
    "digest_of_record", "assert_eligible_for_physical_ppa", "filter_physical",
    "scope_matches", "compare", "area_verdict", "main",
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
    """One area metric: what class it belongs to and what unit it is in."""

    __slots__ = ("name", "metric_class", "unit", "what")

    def __init__(self, name: str, metric_class: str, unit: str, what: str):
        self.name = name
        self.metric_class = metric_class
        self.unit = unit
        self.what = what

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"AreaMetricSpec({self.name!r}, {self.metric_class!r})"


def _spec(name: str, cls: str, unit: str, what: str) -> Tuple[str, AreaMetricSpec]:
    return name, AreaMetricSpec(name, cls, unit, what)


#: The registry. A metric that is not in here has no class, and a number with no
#: class is refused rather than guessed — an unknown name is the exact shape of
#: a new proxy quietly arriving on the physical side.
AREA_METRICS: Dict[str, AreaMetricSpec] = dict([
    # --- RTL_PROXY: counts and the reductions computed from counts ------------
    _spec("area.proxy.cell_count", RTL_PROXY, "cells",
          "cells in a yosys netlist (generic or technology-mapped)"),
    _spec("area.proxy.wire_count", RTL_PROXY, "wires",
          "wires in a yosys netlist"),
    _spec("area.proxy.wire_bit_count", RTL_PROXY, "wire_bits",
          "wire bits in a yosys netlist"),
    _spec("area.proxy.cell_count_reduction_pct", RTL_PROXY, "%",
          "100*(orig-opt)/orig over cell counts"),
    _spec("area.proxy.wire_count_reduction_pct", RTL_PROXY, "%",
          "100*(orig-opt)/orig over wire counts"),
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
          "never the first — the placer reprints it as it iterates)"),
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
    if not a or not b:
        return False
    return _cj.dumps(dict(a)) == _cj.dumps(dict(b))


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
                      baseline_scope=dict(baseline.get("scope") or {}),
                      candidate_scope=dict(candidate.get("scope") or {}))
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

      * every PHYSICAL comparison that can be formed is formed, and they must
        AGREE. One physical metric saying LARGER outranks any number of proxies
        saying SMALLER — that is the negative fixture: a candidate that wins on
        cell count and loses on post-route core area is NOT smaller.
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
    proxy_cmps: List[Dict[str, Any]] = []
    refused: List[Dict[str, Any]] = []
    for m in shared:
        try:
            cls = classify(m)
        except UnknownAreaMetric as ex:
            refused.append({"metric": m, "code": C_METRIC_MISMATCH,
                            "reason": str(ex)})
            continue
        cmp_ = compare(b_idx[m], c_idx[m])
        if cmp_["relation"] == V_UNDETERMINED:
            refused.append(cmp_)
            continue
        (physical_cmps if cls == PHYSICAL else proxy_cmps).append(cmp_)

    doc: Dict[str, Any] = {
        "schema": SCHEMA_VERDICT,
        "physical_comparisons": physical_cmps,
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
                "no PHYSICAL area metric could be compared, so there is no "
                "area verdict. "
                + (f"{len(wins)} proxy metric(s) ({', '.join(wins)}) are "
                   f"smaller; a proxy is a count or a pre-placement estimate "
                   f"and may not stand in for post-route area."
                   if wins else
                   "The proxy comparisons that were formed are advisory only."))
        else:
            doc["code"] = C_NO_PHYSICAL_EVIDENCE
            doc["reason"] = (
                "no area metric could be compared at all: "
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
    doc["verdict"] = V_SMALLER
    doc["code"] = C_OK
    doc["reason"] = ("smaller on every comparable physical area metric: "
                     + ", ".join(f"{c['metric']} {c['delta_pct']:+.4f}%"
                                 for c in physical_cmps))
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
