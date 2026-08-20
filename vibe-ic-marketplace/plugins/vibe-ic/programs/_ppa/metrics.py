#!/usr/bin/env python3
"""The shape every number in the PPA system travels in — and the one question
this module exists to answer: WHAT SHOULD HAVE BEEN MEASURED AND WAS NOT.

Frozen contract: `docs/PPA_INTERFACES.md` §2. Spec §6, §6.1, §6.2, §7.

NOTHING HERE PARSES A TOOL
==========================
The domain modules (`_ppa/timing.py`, `_ppa/power.py`, `_ppa/area.py`) and the
backends under `_ppa/backends/` turn a tool's output into records. This module
owns the RECORD: how one is constructed, what makes one valid, how a set of them
is indexed, and how a coverage question is answered over that set. Adding a tool
must never change a rule in here, and no rule in here may mention a tool.

THE FOURTH INVARIANT, AND IT IS THE WHOLE REASON THIS FILE IS SEPARATE
=====================================================================
**0, -1 and "" never mean "not measured".**

A number that was never obtained is not a small number. Every one of those three
sentinels reads as a legitimate value to arithmetic that comes later:

    area_um2      0     -> "this block is free"
    power_mw      0     -> "this block draws nothing"
    wns_ns        0     -> "exactly met" — the most expensive lie of the three,
                           because 0 slack is a REAL and common STA answer
    wns_ns       -1     -> a plausible violation somebody will try to fix
    unit         ""     -> compares equal to another empty unit, so two numbers
                           in different units pass a unit check

So a missing number is a RECORD, with `status: NOT_MEASURED` and a `reason`, and
it carries NO `value` key at all. Not `value: null` — absent. `null` survives
`.get("value")` as a present key and re-enters arithmetic as soon as somebody
writes `or 0`.

AND THE OMITTED ROW IS THE SAME DEFECT ONE LEVEL UP
==================================================
A record that says NOT_MEASURED is honest. A record that is simply ABSENT from
the set is the identical lie wearing the reader's own assumption: a report with
eight rows where nine were expected reads as eight facts, not as eight facts and
one hole. That is why `coverage()` takes an EXPECTATION SET and reports
`ABSENT` as a distinct outcome from `NOT_MEASURED`, and why the reporter prints
the ABSENT rows literally instead of rendering only what it has.

An absent row cannot be found by looking at the records. It is only visible
against a declaration of what was owed. A coverage report computed without an
expectation set is therefore not a weaker coverage report — it is not one, and
`coverage()` refuses rather than returning 100%.

COMPARABILITY IS A PROPERTY OF `scope`, NOT OF THE METRIC NAME
==============================================================
Two records naming the same `metric` with different `scope` are DIFFERENT FACTS:

    synthesis area              vs  post-route area
    vectorless power            vs  power off a VCD
    ss/1.62V/125C setup slack   vs  tt/1.8V/25C setup slack

Each pair has the same metric name and neither number bounds the other. The
identity of a measurement is therefore `(metric, scope)`, which is what
`record_key` returns and what the index is keyed on. Anything that compares two
records without comparing their scope has already lost the property.

`scope_digest` is that identity in one string, via `canonical_json` — the only
serializer — so two scopes built in different key orders by two authors are one
scope, and two scopes differing in any single field are never accidentally one.

chip-AGNOSTIC, PDK-AGNOSTIC, vendor-AGNOSTIC: no design, PDK, process, vendor or
part literal appears in this module or can affect a verdict. Scope fields are
carried and compared as opaque values and are never interpreted.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from . import canonical_json as cj

__all__ = [
    "SCHEMA_ID", "STATUSES", "COMPARABLE_STATUSES", "NON_VALUE_STATUSES",
    "MEASURED", "NOT_MEASURED", "NOT_APPLICABLE", "INVALID", "ESTIMATED",
    "DERIVED",
    "MetricError",
    "measured", "not_measured", "not_applicable", "invalid", "estimated",
    "derived",
    "validate", "validate_or_raise", "is_comparable",
    "scope_digest", "record_key", "metric_domain", "unit_suffix_of",
    "MetricIndex", "Coverage", "CoverageRow", "coverage", "format_coverage",
]

#: The one shape. Written as the FIRST key of every instance document; see
#: PPA_INTERFACES §5.
SCHEMA_ID = "vibeic.ppa.metric.v1"

# --------------------------------------------------------------------------
# §6.2 — the status enum.
#
# The enum is closed. An unknown status is not "probably fine": a reader that
# does not recognise a status cannot know whether the row may enter arithmetic,
# and the safe default in that situation is to refuse the record, not to guess.
# --------------------------------------------------------------------------
MEASURED = "MEASURED"
NOT_MEASURED = "NOT_MEASURED"
NOT_APPLICABLE = "NOT_APPLICABLE"
INVALID = "INVALID"
ESTIMATED = "ESTIMATED"
DERIVED = "DERIVED"

STATUSES: Tuple[str, ...] = (
    MEASURED, NOT_MEASURED, NOT_APPLICABLE, INVALID, ESTIMATED, DERIVED,
)

#: May enter a numeric comparison. PPA_INTERFACES §2: MEASURED yes; DERIVED
#: "per metric policy, and it carries its formula"; everything else no.
#: ESTIMATED is deliberately NOT here — "never in final PPA" — and it is kept a
#: separate status rather than being banned outright so that an estimate which
#: leaked into a bundle is VISIBLE as an estimate instead of being deleted or,
#: worse, relabelled MEASURED by whoever wanted the row to count.
COMPARABLE_STATUSES: Tuple[str, ...] = (MEASURED, DERIVED)

#: Statuses that may NOT carry a `value` key at all, and must carry a `reason`.
NON_VALUE_STATUSES: Tuple[str, ...] = (
    NOT_MEASURED, NOT_APPLICABLE, INVALID,
)

#: The three sentinels §6.1 names. Held as a constant because the check for
#: them has to be able to say WHICH one it found: "0 is not a measurement" and
#: "the empty string is not a unit" are different sentences to a reader.
NUMERIC_SENTINELS: Tuple[Any, ...] = (0, 0.0, -1, -1.0, "")

#: A metric name: lowercase dotted segments, at least two of them.
#:
#: DELIBERATELY NOT AN ALLOW-LIST OF METRIC NAMES. A closed list would have to
#: be edited by every domain lane that adds a metric, which makes this module a
#: contention point between twelve authors and guarantees that the list is
#: behind the tree. The grammar is what this module can enforce without knowing
#: the taxonomy; the first segment is exposed as `metric_domain` so a coverage
#: report can group by domain without anyone declaring the domains here.
_METRIC_RE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*"
                        r"(?:\.[a-z][a-z0-9]*(?:_[a-z0-9]+)*)+$")

#: Unit suffixes a metric NAME may carry, mapped to the `unit` they assert.
#:
#: This is the one cross-check available without the taxonomy: the frozen
#: example is `"metric": "timing.setup.wns_ns"` with `"unit": "ns"`, so a name
#: that ends in a unit suffix is making a claim about the unit field and the two
#: must agree. `area.die_um2` recorded with `"unit": "mm2"` is a real and cheap
#: mistake — six orders of magnitude — and nothing else in the system is
#: positioned to catch it, because every consumer downstream trusts `unit`.
#:
#: A name with NO recognised suffix is not an error; it simply makes no claim.
_UNIT_SUFFIXES: Dict[str, str] = {
    "ns": "ns", "ps": "ps", "us": "us", "ms": "ms", "s": "s",
    "mw": "mW", "uw": "uW", "nw": "nW", "w": "W", "kw": "kW",
    "um2": "um^2", "mm2": "mm^2", "nm2": "nm^2",
    "um": "um", "nm": "nm", "mm": "mm",
    "mhz": "MHz", "ghz": "GHz", "khz": "kHz", "hz": "Hz",
    "v": "V", "mv": "mV", "ma": "mA", "ua": "uA", "a": "A",
    "pct": "%", "ratio": "1", "count": "count",
}

#: Scope fields that MUST be declared. `stage` alone: it is the field whose
#: absence produces the comparison this lane exists to refuse (synthesis area
#: against post-route area). Corner/mode/clock fields are required by the DOMAIN
#: that owns the metric — a die-area record has no clock and demanding one would
#: force the domain lane to invent a value, which is how a scope field becomes
#: decorative.
_REQUIRED_SCOPE = ("stage",)


class MetricError(Exception):
    """A record that cannot support the fact printed on it.

    Carries a `code` because a verdict a program prints has to be matchable by
    a test and by a caller without parsing English.
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# --------------------------------------------------------------------------
# Construction
# --------------------------------------------------------------------------

def _base(metric: str, status: str, scope: Mapping[str, Any],
          source: Optional[Mapping[str, Any]] = None,
          **extra: Any) -> Dict[str, Any]:
    rec: Dict[str, Any] = {
        "schema": SCHEMA_ID,
        "metric": metric,
        "status": status,
        "scope": dict(scope or {}),
    }
    if source is not None:
        rec["source"] = dict(source)
    for k, v in extra.items():
        if v is not None:
            rec[k] = v
    return rec


def measured(metric: str, value: float, unit: str, scope: Mapping[str, Any],
             source: Mapping[str, Any], **extra: Any) -> Dict[str, Any]:
    """A number that was READ OUT of an artefact.

    `source` is not optional and that is the point: a MEASURED row without a
    provenance is indistinguishable from one somebody typed, and the whole
    contract is built on being able to go back to the artefact.
    """
    rec = _base(metric, MEASURED, scope, source, **extra)
    rec["value"] = value
    rec["unit"] = unit
    validate_or_raise(rec)
    return rec


def not_measured(metric: str, reason: str, scope: Mapping[str, Any],
                 **extra: Any) -> Dict[str, Any]:
    """The honest absence. NO `value` key — not `value: null`."""
    rec = _base(metric, NOT_MEASURED, scope, None, reason=reason, **extra)
    validate_or_raise(rec)
    return rec


def not_applicable(metric: str, reason: str, scope: Mapping[str, Any],
                   **extra: Any) -> Dict[str, Any]:
    """The metric does not apply here, and the reason has to prove it does not.

    §2: "the contract must prove it does not apply". A NOT_APPLICABLE with a
    reason like "n/a" is how a metric somebody could not obtain gets excused
    permanently, so the reason is required and is carried into the report.
    """
    rec = _base(metric, NOT_APPLICABLE, scope, None, reason=reason, **extra)
    validate_or_raise(rec)
    return rec


def invalid(metric: str, reason: str, scope: Mapping[str, Any],
            source: Optional[Mapping[str, Any]] = None,
            **extra: Any) -> Dict[str, Any]:
    """The artefact exists and cannot support the metric.

    Distinct from NOT_MEASURED on purpose: NOT_MEASURED says nobody looked,
    INVALID says somebody looked and what was there could not answer. Collapsing
    them loses the only signal that a parser or a tool is broken.
    """
    rec = _base(metric, INVALID, scope, source, reason=reason, **extra)
    validate_or_raise(rec)
    return rec


def estimated(metric: str, value: float, unit: str, scope: Mapping[str, Any],
              basis: str, **extra: Any) -> Dict[str, Any]:
    """A prediction. Never in a final PPA claim; see COMPARABLE_STATUSES."""
    rec = _base(metric, ESTIMATED, scope, None, basis=basis, **extra)
    rec["value"] = value
    rec["unit"] = unit
    validate_or_raise(rec)
    return rec


def derived(metric: str, value: float, unit: str, scope: Mapping[str, Any],
            formula: str, inputs: Optional[Sequence[str]] = None,
            **extra: Any) -> Dict[str, Any]:
    """A number this system COMPUTED, carrying the formula that produced it.

    §3: "Hash the value you PARSED, never one you recomputed. A number you
    computed is DERIVED and states its formula." The formula is required so a
    reader can recompute it; `inputs` names the record keys it came from.
    """
    rec = _base(metric, DERIVED, scope, None, formula=formula,
                inputs=list(inputs) if inputs is not None else None, **extra)
    rec["value"] = value
    rec["unit"] = unit
    validate_or_raise(rec)
    return rec


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

def validate(rec: Any) -> List[Tuple[str, str]]:
    """Every problem with `rec`, as `(code, message)` pairs. `[]` means valid.

    Returns ALL problems rather than raising on the first, because a producer
    fixing a record wants the list and a gate reporting one wants to print the
    list. `validate_or_raise` is the single-problem front door.
    """
    problems: List[Tuple[str, str]] = []

    def bad(code: str, msg: str) -> None:
        problems.append((code, msg))

    if not isinstance(rec, dict):
        return [("NOT_AN_OBJECT",
                 f"a metric record is a JSON object, got {type(rec).__name__}")]

    if rec.get("schema") != SCHEMA_ID:
        bad("WRONG_SCHEMA",
            f"`schema` must be {SCHEMA_ID!r}, got {rec.get('schema')!r}")

    metric = rec.get("metric")
    if not isinstance(metric, str) or not metric:
        bad("NO_METRIC", "`metric` must be a non-empty string")
    elif not _METRIC_RE.match(metric):
        bad("BAD_METRIC_NAME",
            f"{metric!r} is not a dotted lowercase metric name with at least "
            "two segments (e.g. 'timing.setup.wns_ns')")

    status = rec.get("status")
    if status not in STATUSES:
        bad("BAD_STATUS",
            f"`status` must be one of {', '.join(STATUSES)}; got "
            f"{status!r}. An unrecognised status cannot be known to be safe "
            "for arithmetic, so it is refused rather than assumed.")

    scope = rec.get("scope")
    if not isinstance(scope, dict) or not scope:
        bad("NO_SCOPE",
            "`scope` must be a non-empty object: comparability is a property "
            "of scope, and a record without one can be compared to anything")
    else:
        for field in _REQUIRED_SCOPE:
            if not scope.get(field):
                bad("SCOPE_INCOMPLETE",
                    f"`scope.{field}` is required; without it a synthesis "
                    "number and a post-route number are the same fact")
        for key, val in sorted(scope.items()):
            if not isinstance(key, str):
                bad("BAD_SCOPE_KEY", f"scope key {key!r} is not a string")
            elif val is None or val == "":
                # An empty scope field is §6.1's third sentinel one level in:
                # "" == "" so two records with an unknown corner compare as the
                # same corner.
                bad("SCOPE_SENTINEL",
                    f"`scope.{key}` is {val!r}. An empty scope field is not an "
                    "unknown scope field — two of them compare EQUAL, which "
                    "silently makes two different facts comparable. Omit the "
                    "key, or state it.")

    has_value = "value" in rec
    numeric_status = status in COMPARABLE_STATUSES or status == ESTIMATED

    if numeric_status:
        if not has_value:
            bad("NO_VALUE", f"status {status} requires a `value`")
        else:
            value = rec["value"]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                # bool is an int in Python and True would pass a naive check.
                bad("VALUE_NOT_A_NUMBER",
                    f"`value` must be a number, got {value!r}")
            elif value != value or value in (float("inf"), float("-inf")):
                bad("VALUE_NOT_FINITE",
                    f"`value` is {value!r}; NaN and Infinity are not JSON and "
                    "a metric that is NaN is NOT_MEASURED with a reason")
        unit = rec.get("unit")
        if not isinstance(unit, str) or not unit:
            bad("NO_UNIT",
                f"status {status} requires a non-empty `unit`. The empty "
                "string is not a unit — it compares equal to another empty "
                "unit, so two numbers in different units pass a unit check.")
        elif isinstance(metric, str):
            suffix_unit = unit_suffix_of(metric)
            if suffix_unit is not None and suffix_unit.lower() != unit.lower():
                bad("UNIT_CONTRADICTS_NAME",
                    f"metric {metric!r} names unit {suffix_unit!r} but the "
                    f"record says {unit!r}. Every consumer downstream trusts "
                    "`unit`, so this is a silent order-of-magnitude error.")
    else:
        if has_value:
            found = rec["value"]
            # Name the sentinel when it IS one of the three §6.1 names. "0 is
            # not a measurement" and "the empty string is not a unit" are
            # different sentences to whoever has to fix the producer, and a
            # generic "must not carry a value" makes them one.
            named = ("" if not any(found is s or (type(found) is type(s)
                                                  and found == s)
                                   for s in NUMERIC_SENTINELS)
                     else f" {found!r} is one of the three sentinels §6.1 names,"
                          " and every one of them reads as a legitimate value"
                          " to arithmetic downstream.")
            bad("VALUE_ON_A_NON_MEASUREMENT",
                f"status {status} must not carry a `value` (got "
                f"{found!r}).{named} 0, -1 and \"\" never mean 'not measured'; "
                "the absence is the `reason`, and `value: null` is not an "
                "absence either — the key survives .get() and re-enters "
                "arithmetic as `or 0`.")
        reason = rec.get("reason")
        if status in NON_VALUE_STATUSES and (
                not isinstance(reason, str) or not reason.strip()):
            bad("NO_REASON",
                f"status {status} requires a `reason` saying why. Without one "
                "the row is indistinguishable from a row nobody thought about.")

    if status == MEASURED:
        src = rec.get("source")
        if not isinstance(src, dict) or not src:
            bad("NO_SOURCE",
                "a MEASURED record must name its `source`; a number with no "
                "provenance cannot be checked against the artefact it came "
                "from, which is the entire contract")
        else:
            if not src.get("path"):
                bad("SOURCE_UNPATHED", "`source.path` is required")
            if not src.get("tool"):
                bad("SOURCE_UNTOOLED", "`source.tool` is required")

    if status == DERIVED and not str(rec.get("formula") or "").strip():
        bad("NO_FORMULA",
            "a DERIVED record must state the `formula` that produced it, so a "
            "reader can recompute it instead of trusting it")

    if status == ESTIMATED and not str(rec.get("basis") or "").strip():
        bad("NO_BASIS",
            "an ESTIMATED record must state the `basis` of the estimate")

    return problems


def validate_or_raise(rec: Any) -> Dict[str, Any]:
    """`rec` if it is valid; otherwise `MetricError` carrying the FIRST code."""
    problems = validate(rec)
    if problems:
        code, msg = problems[0]
        if len(problems) > 1:
            msg += f" (+{len(problems) - 1} more: " \
                   + ", ".join(c for c, _ in problems[1:]) + ")"
        raise MetricError(code, msg)
    return rec


def is_comparable(rec: Mapping[str, Any]) -> bool:
    """True only if this record may enter a numeric comparison.

    Validity is part of the question. An invalid record with status MEASURED is
    not comparable, because nothing checked the number it carries.
    """
    return (rec.get("status") in COMPARABLE_STATUSES
            and not validate(rec))


# --------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------

def metric_domain(metric: str) -> str:
    """The first dotted segment — `timing`, `power`, `area`, ...

    Grouping key for a coverage report. Derived from the name rather than
    declared here, so a new domain needs no edit to this module.
    """
    return metric.split(".", 1)[0] if isinstance(metric, str) else ""


def unit_suffix_of(metric: str) -> Optional[str]:
    """The unit a metric NAME claims, or None if it claims nothing."""
    if not isinstance(metric, str) or "." not in metric:
        return None
    last = metric.rsplit(".", 1)[1]
    if "_" not in last:
        return None
    return _UNIT_SUFFIXES.get(last.rsplit("_", 1)[1])


def scope_digest(scope: Mapping[str, Any]) -> str:
    """`sha256:<hex>` identity of a scope, via the one serializer.

    Two scopes assembled in different key orders are one scope; two scopes
    differing in any single field are never one. Hand-rolling `json.dumps` here
    would reintroduce exactly the disagreement `canonical_json` exists to
    remove.
    """
    return cj.digest_of(dict(scope or {}))


def record_key(rec: Mapping[str, Any]) -> Tuple[str, str]:
    """The identity of a MEASUREMENT: `(metric, scope_digest)`.

    NOT the metric name. Two records naming the same metric under different
    scope are different facts and must both be able to live in one index.
    """
    return (str(rec.get("metric", "")), scope_digest(rec.get("scope") or {}))


# --------------------------------------------------------------------------
# Index
# --------------------------------------------------------------------------

class MetricIndex:
    """A set of records keyed by `(metric, scope_digest)`.

    Refuses a second record for the same key. That is not tidiness: two MEASURED
    rows for one identity mean two numbers claim to be the same fact, and any
    index that silently keeps the last one has picked a winner on insertion
    order. If they genuinely are different facts, their scope differs and they
    do not collide.
    """

    def __init__(self) -> None:
        self._by_key: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self._order: List[Tuple[str, str]] = []

    def __len__(self) -> int:
        return len(self._by_key)

    def __iter__(self):
        for key in self._order:
            yield self._by_key[key]

    def add(self, rec: Mapping[str, Any]) -> Tuple[str, str]:
        validate_or_raise(rec)
        key = record_key(rec)
        if key in self._by_key:
            prior = self._by_key[key]
            if cj.sha256(dict(prior)) == cj.sha256(dict(rec)):
                raise MetricError(
                    "DUPLICATE_RECORD",
                    f"{key[0]!r} under this scope was recorded twice, "
                    "identically. Deduplicating silently would make a record "
                    "set's size depend on how many times a producer ran.")
            raise MetricError(
                "CONFLICTING_RECORD",
                f"{key[0]!r} under this scope already carries "
                f"{prior.get('status')}/{prior.get('value', '-')!r}; the new "
                f"record carries {rec.get('status')}/"
                f"{rec.get('value', '-')!r}. Two numbers claiming to be the "
                "same fact is a conflict, and keeping the last one picks a "
                "winner on insertion order.")
        self._by_key[key] = dict(rec)
        self._order.append(key)
        return key

    def extend(self, recs: Iterable[Mapping[str, Any]]) -> None:
        for rec in recs:
            self.add(rec)

    def get(self, metric: str,
            scope: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        return self._by_key.get((metric, scope_digest(scope)))

    def by_metric(self, metric: str) -> List[Dict[str, Any]]:
        """Every record for `metric`, ACROSS scopes.

        Returns a list and never a single record, because "the area" is not a
        thing this index can answer — there is a synthesis one and a post-route
        one and the caller has to say which.
        """
        return [self._by_key[k] for k in self._order if k[0] == metric]

    def keys(self) -> List[Tuple[str, str]]:
        return list(self._order)

    def records(self) -> List[Dict[str, Any]]:
        return [self._by_key[k] for k in self._order]

    def digest(self) -> str:
        """Identity of the whole set, order-independent.

        Keys are sorted before hashing so a bundle assembled from files read in
        a different directory order is the same set.
        """
        return cj.digest_of(sorted(
            (dict(self._by_key[k]) for k in self._order),
            key=lambda r: cj.dumps(r)))


# --------------------------------------------------------------------------
# Coverage — "what should have been measured and was not"
# --------------------------------------------------------------------------

#: A coverage outcome per expected row. ABSENT is the one this lane exists for.
COVERED = "COVERED"          #: MEASURED (or DERIVED) and valid
DECLARED_ABSENT = "DECLARED_ABSENT"   #: present, NOT_MEASURED/NOT_APPLICABLE, with a reason
UNUSABLE = "UNUSABLE"        #: present but INVALID or ESTIMATED
ABSENT = "ABSENT"            #: no record at all — the omitted row

#: Severity order for the report's single verdict. ABSENT outranks everything:
#: an omitted row is the only outcome that is invisible to a reader of the
#: report, so it is the one that must decide the verdict when it is present
#: alongside anything else. (`max()` over the raw strings would order these
#: alphabetically, which puts ABSENT first by luck and not by rule; this repo
#: has already shipped one aggregator where adding a row SUBTRACTED a refusal.)
_COVERAGE_SEVERITY = {COVERED: 0, DECLARED_ABSENT: 1, UNUSABLE: 2, ABSENT: 3}


class CoverageRow:
    """One expected measurement and what became of it."""

    __slots__ = ("metric", "scope", "outcome", "status", "reason")

    def __init__(self, metric: str, scope: Mapping[str, Any], outcome: str,
                 status: Optional[str], reason: Optional[str]) -> None:
        self.metric = metric
        self.scope = dict(scope)
        self.outcome = outcome
        self.status = status
        self.reason = reason

    def as_dict(self) -> Dict[str, Any]:
        return {"metric": self.metric, "scope": self.scope,
                "outcome": self.outcome, "status": self.status,
                "reason": self.reason}


class Coverage:
    """The answer, and the denominator it was computed over.

    `expected` is stated on the report itself. A coverage figure with no
    denominator is the shape this repository keeps paying for: "0 gaps found"
    over a population nobody enumerated reads exactly like "everything was
    measured".
    """

    def __init__(self, rows: Sequence[CoverageRow],
                 unexpected: Sequence[Dict[str, Any]]) -> None:
        self.rows = list(rows)
        #: Records present in the index that no expectation asked for. Not an
        #: error — a domain may legitimately measure more than it was asked to
        #: — but they are DISCLOSED, because otherwise a producer could satisfy
        #: a coverage gate by measuring something adjacent.
        self.unexpected = list(unexpected)

    @property
    def expected(self) -> int:
        return len(self.rows)

    def count(self, outcome: str) -> int:
        return sum(1 for r in self.rows if r.outcome == outcome)

    @property
    def absent(self) -> List[CoverageRow]:
        return [r for r in self.rows if r.outcome == ABSENT]

    @property
    def worst(self) -> str:
        """The most severe outcome present, or COVERED over an empty set...

        ...which never happens, because `coverage()` refuses an empty
        expectation set rather than returning a vacuous 100%.
        """
        worst = COVERED
        for row in self.rows:
            if _COVERAGE_SEVERITY[row.outcome] > _COVERAGE_SEVERITY[worst]:
                worst = row.outcome
        return worst

    @property
    def complete(self) -> bool:
        return self.worst == COVERED

    def as_dict(self) -> Dict[str, Any]:
        return {
            "expected": self.expected,
            "outcomes": {o: self.count(o) for o in
                         (COVERED, DECLARED_ABSENT, UNUSABLE, ABSENT)},
            "worst": self.worst,
            "rows": [r.as_dict() for r in self.rows],
            "unexpected": [{"metric": r.get("metric"),
                            "scope": r.get("scope"),
                            "status": r.get("status")}
                           for r in self.unexpected],
        }


def coverage(index: MetricIndex,
             expected: Sequence[Mapping[str, Any]]) -> Coverage:
    """What was owed, against what is there.

    `expected` is a sequence of `{"metric": ..., "scope": {...}}`. It is the
    DECLARATION of what this run was supposed to measure, and it is required:
    without it an omitted row cannot be seen at all, so a coverage report
    computed from the records alone is not a weaker report, it is not one.
    Hence the refusal below rather than an empty-set 100%.
    """
    if not expected:
        raise MetricError(
            "NO_EXPECTATION_SET",
            "coverage needs a declaration of what should have been measured. "
            "Computed from the records alone it can only ever report 100%, "
            "because the rows it would have to report missing are exactly the "
            "rows that are not there to iterate over.")

    rows: List[CoverageRow] = []
    claimed: set = set()
    for i, want in enumerate(expected):
        if not isinstance(want, Mapping):
            raise MetricError(
                "BAD_EXPECTATION",
                f"expectation #{i} is {type(want).__name__}, not an object "
                "with `metric` and `scope`")
        metric = want.get("metric")
        scope = want.get("scope")
        if not isinstance(metric, str) or not metric:
            raise MetricError("BAD_EXPECTATION",
                              f"expectation #{i} does not name a `metric`")
        if not isinstance(scope, Mapping) or not scope:
            raise MetricError(
                "BAD_EXPECTATION",
                f"expectation #{i} ({metric}) does not name a `scope`. An "
                "expectation without a scope is satisfied by a measurement at "
                "any stage or corner, which is the comparison this lane "
                "refuses, moved into the denominator.")
        key = (metric, scope_digest(scope))
        rec = index.get(metric, scope)
        if rec is None:
            rows.append(CoverageRow(metric, scope, ABSENT, None, None))
            continue
        claimed.add(key)
        status = rec.get("status")
        if status in COMPARABLE_STATUSES and not validate(rec):
            outcome = COVERED
        elif status in (NOT_MEASURED, NOT_APPLICABLE):
            outcome = DECLARED_ABSENT
        else:
            outcome = UNUSABLE
        rows.append(CoverageRow(metric, scope, outcome, status,
                                rec.get("reason")))

    unexpected = [r for r in index.records() if record_key(r) not in claimed]
    return Coverage(rows, unexpected)


def format_coverage(cov: Coverage) -> str:
    """The report. EVERY row is printed, including the ones with no number.

    §2: "A report prints the literal NOT_MEASURED row; it does not omit it."
    Rendering only the rows that have values is how a coverage gap becomes an
    implied zero in the reader's head, so the formatter has no filter and takes
    no argument that could add one.
    """
    lines = [
        f"metric coverage: {cov.expected} expected, "
        f"{cov.count(COVERED)} covered, "
        f"{cov.count(DECLARED_ABSENT)} declared-absent, "
        f"{cov.count(UNUSABLE)} unusable, "
        f"{cov.count(ABSENT)} ABSENT -> {cov.worst}",
    ]
    for row in cov.rows:
        scope = ", ".join(f"{k}={row.scope[k]!r}" for k in sorted(row.scope))
        detail = ""
        if row.outcome == ABSENT:
            detail = ("  <- NO RECORD AT ALL. Not a zero: nothing in the "
                      "bundle answers this, and nothing in the bundle says so.")
        elif row.reason:
            detail = f"  ({row.status}: {row.reason})"
        elif row.status:
            detail = f"  ({row.status})"
        lines.append(f"  [{row.outcome:14s}] {row.metric}  {{{scope}}}{detail}")
    if cov.unexpected:
        lines.append(f"  {len(cov.unexpected)} record(s) present that no "
                     f"expectation asked for (disclosed, not an error):")
        for rec in cov.unexpected:
            lines.append(f"    - {rec.get('metric')} [{rec.get('status')}]")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# The bundle envelope, and reading records out of whatever a producer wrote
# --------------------------------------------------------------------------

#: A set of records travelling as ONE document.
#:
#: NOTE FOR THE LANDER: PPA_INTERFACES §5 says every instance document has a
#: schema file under `schemas/ppa/`. This envelope's would be
#: `schemas/ppa/metric_bundle.v1.schema.json`, which is NOT in this lane's
#: declared file list, so it is not created here and is raised as a request
#: instead. The envelope is not therefore unchecked: `validate_bundle` below is
#: its enforcer and `test_ppa_metrics_bundle.py` is its fixture set.
BUNDLE_SCHEMA_ID = "vibeic.ppa.metric_bundle.v1"


def bundle(index: "MetricIndex",
           expected: Optional[Sequence[Mapping[str, Any]]] = None,
           **extra: Any) -> Dict[str, Any]:
    """One document carrying a record set, its declared denominator, and its
    identity.

    `expected` travels WITH the records on purpose. A bundle that carries only
    what was measured cannot be audited for what was not: the reader would have
    to supply the denominator from somewhere else, and in practice supplies it
    from the record set itself, which always agrees with itself.
    """
    # RECORDS ARE EMITTED IN CANONICAL ORDER, and this is the one place in the
    # PPA contract where a list is sorted. §3 is explicit that list order IS
    # part of a fact -- a corner list, a path, a sequence of stages -- and that
    # is why `canonical_json` sorts keys and stops there.
    #
    # This list is the exception because it is a SET, not a sequence: the index
    # refuses two records claiming one identity, so no two entries here are the
    # same fact and their order carries no information. Emitting them in
    # producer order would make the DOCUMENT's identity depend on the order the
    # assembler happened to read files in, while `records_digest` -- which is
    # already order-independent -- said it did not. Two artefacts describing one
    # set, disagreeing about whether order matters, is the kind of drift this
    # contract exists to remove, so the two are made to agree here rather than
    # left for a reader to discover.
    doc: Dict[str, Any] = {
        "schema": BUNDLE_SCHEMA_ID,
        "records": sorted(index.records(), key=cj.dumps),
        "records_digest": index.digest(),
    }
    if expected is not None:
        doc["expected"] = [dict(e) for e in expected]
    for key, val in extra.items():
        if val is not None:
            doc[key] = val
    return doc


def validate_bundle(doc: Any) -> List[Tuple[str, str]]:
    """Every problem with a bundle ENVELOPE. Does not re-validate the records —
    that is `MetricIndex.add`, which also catches the conflicts a per-record
    check cannot see.
    """
    problems: List[Tuple[str, str]] = []
    if not isinstance(doc, dict):
        return [("NOT_AN_OBJECT",
                 f"a bundle is a JSON object, got {type(doc).__name__}")]
    if doc.get("schema") != BUNDLE_SCHEMA_ID:
        problems.append(("WRONG_SCHEMA",
                         f"`schema` must be {BUNDLE_SCHEMA_ID!r}, got "
                         f"{doc.get('schema')!r}"))
    if not isinstance(doc.get("records"), list):
        problems.append(("NO_RECORDS",
                         "`records` must be a list (an empty list is a set of "
                         "zero records, which is different from no list at "
                         "all — the first is a claim, the second is a "
                         "malformed document)"))
    if "expected" in doc and not isinstance(doc["expected"], list):
        problems.append(("BAD_EXPECTED", "`expected` must be a list"))
    return problems


def records_from_document(doc: Any) -> List[Dict[str, Any]]:
    """The records in `doc`, whichever of the three shapes a producer wrote.

    Accepted: one record; a bare list of records; a bundle envelope. Anything
    else raises rather than yielding `[]` — rule 9 of this repository, and the
    one that keeps biting: "I could not read it" and "I read it and it was
    empty" must never produce the same answer, and returning an empty list for
    an unrecognised document makes them identical to every caller.
    """
    if isinstance(doc, list):
        return [d for d in doc]
    if isinstance(doc, dict):
        if doc.get("schema") == BUNDLE_SCHEMA_ID:
            recs = doc.get("records")
            if not isinstance(recs, list):
                raise MetricError(
                    "NO_RECORDS",
                    "bundle has no `records` list; that is a malformed "
                    "document, not a bundle of zero records")
            return list(recs)
        if doc.get("schema") == SCHEMA_ID:
            return [doc]
    raise MetricError(
        "UNRECOGNISED_DOCUMENT",
        "not a metric record, a list of records, or a "
        f"{BUNDLE_SCHEMA_ID} bundle. Refused rather than read as empty: an "
        "unreadable document and an empty one must not reach a caller as the "
        "same answer.")


# --------------------------------------------------------------------------
# Comparison — the refusal this lane exists for
# --------------------------------------------------------------------------

#: Verdict codes from `compare`. Each is a different sentence to a reader and
#: they are deliberately not collapsed into a boolean.
CMP_OK = "COMPARABLE"
CMP_DIFFERENT_SCOPE = "DIFFERENT_SCOPE"
CMP_NOT_MEASURED = "NOT_MEASURED"
CMP_UNIT_MISMATCH = "UNIT_MISMATCH"
CMP_INVALID = "INVALID_RECORD"
CMP_DIFFERENT_METRIC = "DIFFERENT_METRIC"


def compare(a: Mapping[str, Any], b: Mapping[str, Any],
            better: Optional[str] = None) -> Dict[str, Any]:
    """Whether two records may be compared, and — only then — the delta.

    THE REFUSAL IS THE POINT. Two records with the same `metric` and different
    `scope` are different facts. Synthesis area is not post-route area;
    vectorless power is not VCD power; ss/125C setup slack is not tt/25C setup
    slack. A comparison across differing scope is UNDETERMINED, and this
    function will not pick one — picking one is how a favourable stage gets
    quoted against an unfavourable one and nobody downstream can see it
    happened, because both rows say `area_um2`.

    IT ALSO WILL NOT NAME A WINNER BY ITSELF. Which direction is "better" is
    domain policy (smaller area, more positive slack, less power) and belongs to
    the domain module that owns the metric, not to the module that owns the
    shape. Without an explicit `better`, the report states which value is
    larger and says the direction was not declared — it never silently assumes
    that lower is better, which is wrong for slack and for frequency.
    """
    if better not in (None, "lower", "higher"):
        raise MetricError("BAD_DIRECTION",
                          f"`better` is 'lower', 'higher' or unset; got "
                          f"{better!r}")
    out: Dict[str, Any] = {
        "a": {"metric": a.get("metric"), "status": a.get("status"),
              "scope": dict(a.get("scope") or {})},
        "b": {"metric": b.get("metric"), "status": b.get("status"),
              "scope": dict(b.get("scope") or {})},
        "better": better,
    }
    for name, rec in (("a", a), ("b", b)):
        problems = validate(rec)
        if problems:
            out["verdict"] = CMP_INVALID
            out["detail"] = (f"record {name} is not a valid metric record: "
                             f"{problems[0][0]}: {problems[0][1]}")
            return out

    if a.get("metric") != b.get("metric"):
        out["verdict"] = CMP_DIFFERENT_METRIC
        out["detail"] = (f"{a.get('metric')!r} and {b.get('metric')!r} are not "
                         "the same quantity; there is no comparison to make")
        return out

    da, db = scope_digest(a.get("scope") or {}), scope_digest(b.get("scope") or {})
    if da != db:
        sa, sb = dict(a.get("scope") or {}), dict(b.get("scope") or {})
        keys = sorted(set(sa) | set(sb))
        # A FIELD ONE SIDE DOES NOT DECLARE IS NOT A FIELD WHOSE VALUE IS null,
        # and the report must not render them the same way -- that is this whole
        # module's subject, applied to its own output. `a_declared` carries the
        # distinction machine-readably; the sentence says `<not declared>`.
        diff = [{"field": k,
                 "a": sa.get(k), "a_declared": k in sa,
                 "b": sb.get(k), "b_declared": k in sb}
                for k in keys if sa.get(k) != sb.get(k) or (k in sa) != (k in sb)]
        out["verdict"] = CMP_DIFFERENT_SCOPE
        out["scope_diff"] = diff

        def _shown(d: Dict[str, Any], side: str) -> str:
            return repr(d[side]) if d[side + "_declared"] else "<not declared>"

        out["detail"] = (
            "same metric, different scope, so these are two different facts "
            "and neither bounds the other: "
            + "; ".join(f"{d['field']}: {_shown(d, 'a')} vs {_shown(d, 'b')}"
                        for d in diff))
        return out

    if not (a.get("status") in COMPARABLE_STATUSES
            and b.get("status") in COMPARABLE_STATUSES):
        out["verdict"] = CMP_NOT_MEASURED
        out["detail"] = (
            f"status a={a.get('status')} b={b.get('status')}: a record that "
            "is not a measurement cannot lose and cannot win. Missing is not "
            "winning, and it is not losing either.")
        return out

    if a.get("unit") != b.get("unit"):
        out["verdict"] = CMP_UNIT_MISMATCH
        out["detail"] = (f"same metric and same scope, but unit {a.get('unit')!r} "
                         f"vs {b.get('unit')!r}. One of these two records is "
                         "wrong; comparing the numbers would hide which.")
        return out

    va, vb = float(a["value"]), float(b["value"])
    out["verdict"] = CMP_OK
    out["unit"] = a.get("unit")
    out["a"]["value"] = va
    out["b"]["value"] = vb
    out["delta_b_minus_a"] = vb - va
    if better is None:
        out["winner"] = None
        out["detail"] = (
            f"comparable. b - a = {vb - va} {a.get('unit')}. No direction was "
            "declared, so no winner is named: which way is better is domain "
            "policy (smaller area, MORE POSITIVE slack, less power) and "
            "assuming 'lower is better' is wrong for slack and for frequency.")
    else:
        if va == vb:
            out["winner"] = None
        elif (va < vb) == (better == "lower"):
            out["winner"] = "a"
        else:
            out["winner"] = "b"
        out["detail"] = (f"comparable; better={better}; b - a = {vb - va} "
                         f"{a.get('unit')}")
    return out


# --------------------------------------------------------------------------
# Coverage -> exit code
# --------------------------------------------------------------------------

#: Coverage outcome -> exit code, and this table is written out rather than
#: derived from `_COVERAGE_SEVERITY` because THE TWO ORDERS ARE NOT THE SAME.
#: Severity runs COVERED < DECLARED_ABSENT < UNUSABLE < ABSENT, but the exit
#: codes run 0 (pass), 2 (undetermined), 1 (refused) — 1 is the HARDER verdict
#: and the SMALLER integer. Any aggregation that uses max() over rc mixes the
#: two orders and promotes a refusal to an undetermined; this repository shipped
#: exactly that in `ppa_head_to_head_check` and it took a landing to notice.
_COVERAGE_RC = {
    COVERED: 0,
    DECLARED_ABSENT: 2,   # honestly declared, still not measured -> NOT CHECKED
    UNUSABLE: 2,          # INVALID: somebody looked and the artefact could not answer
    ABSENT: 1,            # the omitted row: the report would imply a zero
}


def coverage_rc(cov: Coverage) -> int:
    """The gate verdict for a coverage report.

    ABSENT is rc=1 and everything else short of complete is rc=2, and the
    difference is exactly the difference this lane exists to keep:

      * a row present and saying NOT_MEASURED is HONEST. The run did not
        measure it, the report prints that, a reader can see the hole. That is
        UNDETERMINED — never a pass, but not a finding.
      * a row that is simply not there is the SAME hole with nothing marking it.
        The report renders n-1 rows and reads as n-1 facts. That is a finding
        about the record set, and it is rc=1.
      * an ESTIMATED row standing where a measurement was owed is also rc=1:
        §2 says an estimate is never in a final PPA, and letting it satisfy a
        coverage slot at rc=2 is how it would get there.
    """
    rc = 0
    for row in cov.rows:
        if row.outcome == UNUSABLE and row.status == ESTIMATED:
            this = 1
        else:
            this = _COVERAGE_RC[row.outcome]
        # 1 outranks 2 outranks 0. Written as an explicit ladder, not max().
        if this == 1:
            return 1
        if this == 2:
            rc = 2
    return rc
