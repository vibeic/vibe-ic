#!/usr/bin/env python3
"""The frontier over the raw triple. Never over a number somebody collapsed.

WHY A SINGLE SCORE IS FORBIDDEN IN PUBLIC OUTPUT (spec 11.3)
============================================================
Area, power and timing trade against each other. Any weighting that turns them
into one number encodes a preference -- and the preference is the ARGUMENT, not
a measurement. Once the collapsed number exists it is the number that gets
quoted, compared across runs whose weights differed, and eventually optimised
against directly, at which point the flow is tuning a proxy and not the design.

So `assert_no_collapsed_scalar()` refuses a public document that carries one,
and it refuses by KEY NAME against an exact normalised list rather than by
guessing from values, because a rule that guesses is a rule that both misses and
false-positives.

WHY A NON-COMPARABLE CANDIDATE IS EXCLUDED RATHER THAN ADMITTED
================================================================
Pareto domination is defined only between comparable points. The tempting
implementation says "if we cannot compare them, neither dominates the other, so
both stay on the frontier" -- and that is exactly how a candidate with no
measured power, or with power measured against a different activity basis, ends
up published as a winner. Nobody could show it was worse, so it stayed.

This module inverts that. A candidate enters the frontier only if, for EVERY
declared objective, it has a `MEASURED` record whose `scope` matches the
objective's declared reference scope. Anything else lands in `undetermined`
with a reason and is never described as better than anything.

The two shapes this catches are named in the spec and are the same defect wearing
different clothes:

    power better, but a different activity basis   ->  PARETO_SCOPE_MISMATCH
    area better, but a different stage             ->  PARETO_SCOPE_MISMATCH

Synthesis area and post-route area are not the same metric with a bit of noise
between them; vectorless power and vector-driven power are not either. Comparing
them produces a winner that does not exist.

WHY THE FRONTIER MUST BE RECOMPUTABLE BY A THIRD PARTY
=======================================================
`build_frontier()` emits, for every candidate it considered, the raw objective
values with their unit, scope and source -- and the objective senses it used.
That is everything needed to redo the domination relation independently, which
is what `verify_frontier()` does: it recomputes from the raw triple and refuses
if the published frontier disagrees. A frontier nobody can recompute is a claim,
not a result.

chip-AGNOSTIC: no IC, vendor, SKU or process is named here, and the objective
metric names are supplied by the contract rather than invented in this file.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import feasibility as feas

__all__ = [
    "PARETO_SCHEMA",
    "SENSE_MIN", "SENSE_MAX",
    "Objective", "DEFAULT_OBJECTIVES",
    "objectives_from_document",
    "objective_values", "dominates", "build_frontier", "verify_frontier",
    "assert_no_collapsed_scalar", "COLLAPSED_SCALAR_KEYS",
    "frontier_exit_code", "empty_frontier_finding",
]

PARETO_SCHEMA = "vibeic.ppa.pareto_frontier.v1"

SENSE_MIN = "min"
SENSE_MAX = "max"

# --- codes ------------------------------------------------------------------
P_OK = "PARETO_OK"
P_INFEASIBLE_EXCLUDED = "PARETO_INFEASIBLE_EXCLUDED"
P_FEASIBILITY_UNDETERMINED = "PARETO_FEASIBILITY_UNDETERMINED"
P_EMPTY_FRONTIER = "PARETO_EMPTY_FRONTIER"
P_INFEASIBLE_IN_FRONTIER = "PARETO_INFEASIBLE_IN_FRONTIER"
P_NOT_MEASURED = "PARETO_NOT_MEASURED"
P_METRIC_ABSENT = "PARETO_METRIC_ABSENT"
P_SCOPE_MISMATCH = "PARETO_SCOPE_MISMATCH"
P_SCOPE_NOT_DECLARED = "PARETO_SCOPE_NOT_DECLARED"
P_SCOPE_DIVERGENT = "PARETO_SCOPE_DIVERGENT"
P_UNIT_DIVERGENT = "PARETO_UNIT_DIVERGENT"
P_NO_PROVENANCE = "PARETO_NO_PROVENANCE"
P_NON_NUMERIC = "PARETO_NON_NUMERIC"
P_COLLAPSED_SCALAR = "PARETO_COLLAPSED_SCALAR"
P_FRONTIER_DISAGREES = "PARETO_FRONTIER_DISAGREES"
P_NO_OBJECTIVES = "PARETO_NO_OBJECTIVES"
P_UNDETERMINED_JUDGED_BETTER = "PARETO_UNDETERMINED_JUDGED_BETTER"

#: Keys a PUBLIC Pareto document may never carry, normalised (lowercased, with
#: `-` and ` ` folded to `_`). Matched EXACTLY, never as a substring: `scope`
#: contains no forbidden word and must not be caught, and a substring rule that
#: fires on `score` inside `scorecard` teaches authors to rename rather than to
#: stop collapsing.
COLLAPSED_SCALAR_KEYS = frozenset({
    "score", "scores", "total_score", "overall_score", "composite",
    "composite_score", "weighted_score", "weighted_sum", "weight", "weights",
    "fom", "figure_of_merit", "merit", "cost", "cost_function",
    "objective_value", "utility", "fitness", "rank", "ranking", "rank_score",
    "ppa_score", "qor_score", "goodness", "penalty",
})


def _norm_key(k: str) -> str:
    return str(k).strip().lower().replace("-", "_").replace(" ", "_")


@dataclass(frozen=True)
class Objective:
    """One axis of the trade-off, and the exact scope its numbers must carry.

    `scope` is the reference every candidate's record must match. It is not
    optional-with-a-default because the default would have to be "whatever the
    first candidate happened to carry", which makes the answer depend on input
    order and silently admits the mismatched candidate that the order favoured.
    """
    key: str
    metric: str
    sense: str
    scope: Mapping[str, Any] = field(default_factory=dict)


#: The canonical triple. The metric NAMES are the ones the interface freeze uses
#: in its own example plus the obvious siblings; a contract may override all of
#: them, and must supply the scope in every case.
DEFAULT_OBJECTIVES: Tuple[Objective, ...] = (
    Objective("area", "area.total_um2", SENSE_MIN),
    Objective("power", "power.total_w", SENSE_MIN),
    Objective("timing", "timing.setup.wns_ns", SENSE_MAX),
)


def objectives_from_document(doc: Mapping[str, Any]) -> Tuple[Objective, ...]:
    raw = doc.get("objectives")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return ()
    out: List[Objective] = []
    for o in raw:
        if not isinstance(o, Mapping):
            continue
        sense = str(o.get("sense") or "").lower()
        if sense not in (SENSE_MIN, SENSE_MAX):
            continue
        key = str(o.get("key") or o.get("metric") or "").strip()
        metric = str(o.get("metric") or "").strip()
        if not key or not metric:
            continue
        scope = o.get("scope")
        out.append(Objective(key, metric, sense,
                             dict(scope) if isinstance(scope, Mapping) else {}))
    return tuple(out)


# ---------------------------------------------------------------------------
# reading the raw triple out of a candidate
# ---------------------------------------------------------------------------
def _pick(records: Sequence[Any], obj: Objective) -> Tuple[Optional[Mapping[str, Any]],
                                                           List[str],
                                                           List[Mapping[str, Any]]]:
    """The one record that may represent `obj`, or None with the reasons why not."""
    named = [r for r in records
             if isinstance(r, Mapping) and r.get("metric") == obj.metric]
    if not named:
        return None, [P_METRIC_ABSENT], []

    codes: List[str] = []
    rejected: List[Mapping[str, Any]] = []
    usable: List[Mapping[str, Any]] = []
    for r in named:
        if r.get("schema") != feas.METRIC_SCHEMA:
            codes.append(P_METRIC_ABSENT)
            rejected.append({"reason": P_METRIC_ABSENT})
            continue
        if r.get("status") not in feas.COMPARABLE_STATUSES:
            # NOT_MEASURED / INVALID / ESTIMATED / DERIVED-without-policy are
            # not comparable. This is the "never judged better" rule: the
            # candidate does not become unbeatable by being unreadable.
            codes.append(P_NOT_MEASURED)
            rejected.append({"reason": P_NOT_MEASURED,
                             "status": r.get("status")})
            continue
        src = r.get("source")
        digest = str((src or {}).get("sha256") or "") if isinstance(src, Mapping) else ""
        if not isinstance(src, Mapping) or not digest.startswith("sha256:"):
            codes.append(P_NO_PROVENANCE)
            rejected.append({"reason": P_NO_PROVENANCE})
            continue
        if not feas._is_number(r.get("value")):
            codes.append(P_NON_NUMERIC)
            rejected.append({"reason": P_NON_NUMERIC})
            continue
        usable.append(r)

    if not usable:
        return None, codes or [P_METRIC_ABSENT], rejected

    if not obj.scope:
        # Without a declared reference scope nothing here can say whether two
        # candidates' numbers describe the same thing. Refusing is the honest
        # answer; picking one candidate's scope as the reference would make the
        # verdict depend on input order.
        return None, codes + [P_SCOPE_NOT_DECLARED], rejected

    matched = [r for r in usable
               if feas._covers(r.get("scope") or {}, obj.scope)]
    if not matched:
        codes.append(P_SCOPE_MISMATCH)
        rejected.extend({"reason": P_SCOPE_MISMATCH,
                         "scope": dict(r.get("scope") or {}),
                         "required_scope": dict(obj.scope)} for r in usable)
        return None, codes, rejected

    units = {str(r.get("unit", "")) for r in matched}
    if len(units) > 1:
        codes.append(P_UNIT_DIVERGENT)
        return None, codes, rejected
    scopes = {feas_scope_key(r.get("scope") or {}) for r in matched}
    if len(scopes) > 1:
        # Two records both satisfy the required subset but differ elsewhere in
        # scope, so they are two different measurements and there is no single
        # number for this objective.
        codes.append(P_SCOPE_DIVERGENT)
        return None, codes, rejected
    return matched[0], codes, rejected


def feas_scope_key(scope: Mapping[str, Any]) -> Tuple[Tuple[str, Any], ...]:
    return tuple(sorted((str(k), scope[k]) for k in scope))


def objective_values(candidate: Mapping[str, Any],
                     objectives: Sequence[Objective]) -> Dict[str, Any]:
    """The raw triple for one candidate, with every reason it is not usable."""
    records = candidate.get("metrics")
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        records = []
    values: Dict[str, Any] = {}
    codes: List[str] = []
    comparable = True
    for obj in objectives:
        rec, cs, rejected = _pick(records, obj)
        codes.extend(cs)
        if rec is None:
            comparable = False
            values[obj.key] = {"objective": obj.key, "metric": obj.metric,
                               "sense": obj.sense, "status": "NOT_COMPARABLE",
                               "codes": sorted(set(cs)),
                               "rejected": [dict(x) for x in rejected]}
            continue
        values[obj.key] = {
            "objective": obj.key, "metric": obj.metric, "sense": obj.sense,
            "status": feas.STATUS_MEASURED, "value": rec.get("value"),
            "unit": rec.get("unit"), "scope": dict(rec.get("scope") or {}),
            "source": dict(rec.get("source") or {}),
        }
    return {"values": values, "comparable": comparable,
            "codes": sorted(set(c for c in codes if c != P_OK))}


def _better(a: Any, b: Any, sense: str) -> bool:
    return a < b if sense == SENSE_MIN else a > b


def dominates(a: Mapping[str, Any], b: Mapping[str, Any],
              objectives: Sequence[Objective]) -> bool:
    """Classic Pareto domination over the raw triple. No weights anywhere.

    Both operands must be fully comparable; callers guarantee that by admitting
    only comparable candidates. Domination is: no worse on every objective, and
    strictly better on at least one.
    """
    strictly = False
    for obj in objectives:
        va = a["values"][obj.key]["value"]
        vb = b["values"][obj.key]["value"]
        if _better(vb, va, obj.sense):
            return False
        if _better(va, vb, obj.sense):
            strictly = True
    return strictly


# ---------------------------------------------------------------------------
# building and verifying
# ---------------------------------------------------------------------------
def build_frontier(candidates: Sequence[Mapping[str, Any]],
                   results: Sequence[feas.FeasibilityResult],
                   objectives: Sequence[Objective]) -> Dict[str, Any]:
    """Emit the public frontier document. Infeasible candidates never enter it.

    The ordering of the two filters is the point of the lane: FEASIBILITY IS
    APPLIED FIRST and is not a term in anything afterwards. A candidate that
    fails the hard gate is not merely penalised in the comparison, it is not in
    the comparison.
    """
    verdict_by_id = {r.candidate_id: r.verdict for r in results}
    considered: List[Dict[str, Any]] = []
    admitted: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []
    undetermined: List[Dict[str, Any]] = []

    for cand in candidates:
        cid = str(cand.get("candidate_id") or "")
        row = objective_values(cand, objectives)
        row["candidate_id"] = cid
        row["feasibility"] = verdict_by_id.get(cid, feas.UNDETERMINED)
        considered.append(row)

        if row["feasibility"] != feas.FEASIBLE:
            code = (P_INFEASIBLE_EXCLUDED
                    if row["feasibility"] == feas.INFEASIBLE
                    else P_FEASIBILITY_UNDETERMINED)
            excluded.append({"candidate_id": cid,
                             "feasibility": row["feasibility"], "code": code})
            continue
        if not row["comparable"]:
            undetermined.append({"candidate_id": cid, "codes": row["codes"]})
            continue
        admitted.append(row)

    frontier: List[str] = []
    dominated: List[Dict[str, Any]] = []
    for a in admitted:
        by = [b["candidate_id"] for b in admitted
              if b["candidate_id"] != a["candidate_id"]
              and dominates(b, a, objectives)]
        if by:
            dominated.append({"candidate_id": a["candidate_id"],
                              "dominated_by": sorted(by)})
        else:
            frontier.append(a["candidate_id"])

    doc = {
        "schema": PARETO_SCHEMA,
        "objectives": [{"key": o.key, "metric": o.metric, "sense": o.sense,
                        "scope": dict(o.scope)} for o in objectives],
        "relation": ("a dominates b iff a is no worse on every objective and "
                     "strictly better on at least one; comparison requires a "
                     "MEASURED record whose scope matches the objective scope"),
        "considered": sorted(considered, key=lambda r: r["candidate_id"]),
        "frontier": sorted(frontier),
        "dominated": sorted(dominated, key=lambda r: r["candidate_id"]),
        "excluded_infeasible": sorted(excluded, key=lambda r: r["candidate_id"]),
        "undetermined": sorted(undetermined, key=lambda r: r["candidate_id"]),
    }
    return doc


def assert_no_collapsed_scalar(doc: Any) -> List[str]:
    """Every path in `doc` whose key collapses the triple into one number.

    Returns paths, not a bool, because "there is a forbidden key somewhere" is
    not actionable and a reviewer needs to be told which one.
    """
    found: List[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, Mapping):
            for k, v in node.items():
                p = f"{path}.{k}" if path else str(k)
                if _norm_key(k) in COLLAPSED_SCALAR_KEYS:
                    found.append(p)
                walk(v, p)
        elif isinstance(node, Sequence) and not isinstance(node, (str, bytes)):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(doc, "")
    return sorted(found)


def verify_frontier(doc: Mapping[str, Any],
                    candidates: Sequence[Mapping[str, Any]],
                    results: Sequence[feas.FeasibilityResult],
                    objectives: Sequence[Objective]) -> Dict[str, Any]:
    """Recompute the frontier independently and refuse if the document differs.

    This is the third-party check made executable. It reads only the RAW triple
    out of the candidates plus the declared objectives -- never the published
    `frontier` list -- and then compares.
    """
    findings: List[Dict[str, Any]] = []
    if not objectives:
        findings.append({"code": P_NO_OBJECTIVES,
                         "detail": "no objective declared, nothing to compare"})
        return {"findings": findings, "recomputed": None}

    recomputed = build_frontier(candidates, results, objectives)

    published = list(doc.get("frontier") or [])
    verdict_by_id = {r.candidate_id: r.verdict for r in results}
    for cid in published:
        v = verdict_by_id.get(cid, feas.UNDETERMINED)
        if v == feas.INFEASIBLE:
            findings.append({"code": P_INFEASIBLE_IN_FRONTIER,
                             "candidate_id": cid, "feasibility": v})
        elif v != feas.FEASIBLE:
            findings.append({"code": P_UNDETERMINED_JUDGED_BETTER,
                             "candidate_id": cid, "feasibility": v})

    for row in recomputed["undetermined"]:
        if row["candidate_id"] in published:
            findings.append({"code": P_UNDETERMINED_JUDGED_BETTER,
                             "candidate_id": row["candidate_id"],
                             "codes": row["codes"]})

    if sorted(published) != sorted(recomputed["frontier"]):
        findings.append({"code": P_FRONTIER_DISAGREES,
                         "published": sorted(published),
                         "recomputed": sorted(recomputed["frontier"])})

    for path in assert_no_collapsed_scalar(doc):
        findings.append({"code": P_COLLAPSED_SCALAR, "path": path})

    # dedupe on the canonical text of each finding, preserving order
    seen = set()
    unique: List[Dict[str, Any]] = []
    for f in findings:
        key = tuple(sorted((k, str(v)) for k, v in f.items()))
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return {"findings": unique, "recomputed": recomputed}


def empty_frontier_finding(doc: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """THE single owner of "this run named no promotable design".

    Both the exit code and the printed finding come from here, and that is
    deliberate. The first version implemented the rule twice -- once as a branch
    in `frontier_exit_code` and once as a finding appended by the CLI -- and the
    mutation probe caught it immediately: reverting the branch left the rc
    unchanged at 1, because the other copy still fired. Two implementations of
    one rule mean neither can be shown to be the one doing the work, so
    reverting either proves nothing about either.

    An exit code nobody can explain is an exit code somebody overrides, so the
    finding is not optional decoration -- it is the same fact, printed.
    """
    if doc.get("considered") and not doc.get("frontier"):
        return {"code": P_EMPTY_FRONTIER,
                "considered": len(doc.get("considered") or []),
                "excluded": len(doc.get("excluded_infeasible") or []),
                "undetermined": len(doc.get("undetermined") or []),
                "detail": "no candidate is both feasible and comparable, so "
                          "this run names no promotable design"}
    return None


def frontier_exit_code(doc: Mapping[str, Any],
                       findings: Sequence[Mapping[str, Any]]) -> int:
    """Same precedence as the feasibility CLI, and for the same reason.

    UNDETERMINED outranks REFUSED: a run that could not establish every
    comparison must not publish a complete claim about which design won. Both
    block, and every finding is printed whichever code is returned.

    AN EMPTY FRONTIER IS NEVER A PASS, and this is the one that got past the
    first implementation of this function. If every candidate was excluded, the
    document is internally consistent and every invariant holds -- and it names
    no promotable design at all. Returning 0 there is the empty-tree lie at the
    frontier level: a promoter reading only the exit code would proceed with
    nothing. Measured while writing `test_M6_an_incomplete_view_set_keeps_a
    _candidate_off_the_frontier`: rc was 0 with `frontier: <empty>`.
    """
    # P_EMPTY_FRONTIER is excluded from the generic route so that emptiness has
    # exactly ONE path to a non-zero rc; see `empty_frontier_finding`.
    codes = {f.get("code") for f in findings} - {P_EMPTY_FRONTIER}
    undetermined_codes = {
        P_NO_OBJECTIVES, P_SCOPE_NOT_DECLARED, P_SCOPE_MISMATCH,
        P_SCOPE_DIVERGENT, P_UNIT_DIVERGENT, P_NOT_MEASURED,
        P_METRIC_ABSENT, P_NO_PROVENANCE, P_NON_NUMERIC,
    }
    if doc.get("undetermined"):
        return feas.RC_UNDETERMINED
    if any(r.get("code") == P_FEASIBILITY_UNDETERMINED
           for r in (doc.get("excluded_infeasible") or [])):
        return feas.RC_UNDETERMINED
    if codes & undetermined_codes:
        return feas.RC_UNDETERMINED
    if codes:
        return feas.RC_FAIL
    if empty_frontier_finding(doc) is not None:
        return feas.RC_FAIL
    return feas.RC_PASS
