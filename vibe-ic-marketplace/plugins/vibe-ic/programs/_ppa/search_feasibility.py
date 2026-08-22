#!/usr/bin/env python3
"""`_ppa/search_feasibility.py` — the bridge from the SEARCH lane to the HARD
gate, and the one place the two vocabularies are translated.

WHY THIS IS A THIRD MODULE AND NOT A LINE IN EITHER OF THE OTHER TWO
====================================================================
`_ppa/search.py` says, in its own docstring, that it does NOT decide whether a
candidate is feasible -- `_ppa/feasibility.py` owns that. That separation is
worth keeping: the search lane's job is which points ran and which may be
compared, and a search module that could reach into the promotion gate is a
search module that could be made to grade its own homework.

So the dependency lives HERE. This module imports both; neither imports this.
`ppa_search_run.py` is the only caller, and it is a CLI shell.

WHAT IT FIXES (F-12)
====================
`ppa_search_run.py` hard-wired `Ledger.evaluate_feasibility(None)` -- the stub
-- so every manifest a downloaded plugin could produce marked every candidate
UNDETERMINED and published an empty Pareto frontier. `_ppa/feasibility.py` had
landed three commits earlier and the CLI had no way to reach it.

THE TRANSLATION, AND THE ONE PLACE IT COULD HAVE BEEN DISHONEST
===============================================================
The hard gate answers FEASIBLE / INFEASIBLE / UNDETERMINED per candidate. The
search lane speaks ELIGIBLE / INELIGIBLE / UNDETERMINED. The mapping is the
obvious one and it is TOTAL -- there is no fourth verdict and no default arm
that could turn an unrecognised answer into eligibility:

    FEASIBLE      -> ELIGIBLE
    INFEASIBLE    -> INELIGIBLE
    UNDETERMINED  -> UNDETERMINED       (and anything else, defensively)

Per AXIS the search manifest publishes a term vector, and `audit_manifest`
refuses an ELIGIBLE candidate whose nine terms do not all PASS or state
NOT_APPLICABLE. So the axis translation has to be exact in the same direction:

    SATISFIED     -> PASS
    VIOLATED      -> FAIL
    UNDETERMINED  -> NOT_CHECKED
    WAIVED        -> WAIVED             (see below -- unreachable from here)

NO WAIVER TRAVELS THIS BRIDGE, ON PURPOSE
=========================================
A waiver is a named owner accepting one KNOWN violation on one run. A point in
a search space is not a run; it is a configuration that a run visited. Handing
the gate a waiver list here would let one accepted violation silently authorise
every candidate that shares the axis, so the candidate document this module
builds carries `metrics` and nothing else, and `promotion_verdict` therefore
never reaches its waiver path. `AXIS_WAIVED` is mapped above only so that the
translation table is total; on this path it does not occur.

A POLICY THAT COULD NOT BE READ IS NOT AN EMPTY POLICY
======================================================
`policy_from_path` returns a REASON rather than a permissive default when the
document is absent, unreadable or not an object. Falling back to the stub there
would publish a stub verdict for a run whose caller explicitly asked for
adjudication, which is the same class of defect as the one this module exists
to fix -- a record whose stated basis is not the basis that was used.

chip-AGNOSTIC: no IC, vendor, SKU, process or PDK appears in this file.
"""
from __future__ import annotations

import json
import pathlib
from typing import Any, Dict, Optional, Tuple

from . import canonical_json as cj
from . import feasibility as F
from . import search as S

#: What `toolchain.feasibility_source` says when this bridge did the work. It
#: names the FUNCTION, not a lane, because "which code adjudicated this" is the
#: question a reader of a published manifest is actually asking.
SOURCE_SHIPPED = "_ppa.feasibility.promotion_verdict"

#: Total by construction: every member of the gate's verdict vocabulary has a
#: row, and `.get(..., UNDETERMINED)` covers anything a future gate adds. There
#: is deliberately no arm that produces ELIGIBLE from an unrecognised verdict.
VERDICT_MAP: Dict[str, str] = {
    F.FEASIBLE: S.FEAS_ELIGIBLE,
    F.INFEASIBLE: S.FEAS_INELIGIBLE,
    F.UNDETERMINED: S.FEAS_UNDETERMINED,
}

#: Axis status -> the term vocabulary `audit_manifest` reads. Same rule: the
#: unknown arm goes to NOT_CHECKED, never to PASS.
TERM_MAP: Dict[str, str] = {
    F.AXIS_SATISFIED: "PASS",
    F.AXIS_VIOLATED: "FAIL",
    F.AXIS_UNDETERMINED: "NOT_CHECKED",
    F.AXIS_WAIVED: "WAIVED",
}


def _axis_names_match_terms() -> bool:
    """Do the gate's default axes name exactly the search lane's nine terms?

    Asserted by MEASUREMENT at import-check time rather than by comment,
    because the two tuples live in two files and the failure mode of them
    drifting apart is silent: a term the search lane publishes that no axis
    fills reads as NOT_CHECKED forever, and an axis with no term is dropped
    from the published vector without anything saying so.
    """
    return tuple(a.name for a in F.DEFAULT_AXES) == S.FEASIBILITY_TERMS


def policy_from_path(path: pathlib.Path,
                     ) -> Tuple[Optional[F.FeasibilityPolicy], Optional[str],
                                Optional[Dict[str, Any]]]:
    """(policy, reason-it-could-not-be-built, the document read).

    Exactly one of the first two is None. The document is returned as well so
    the caller can record WHAT it adjudicated against, by digest, in the
    manifest -- a policy named by path alone is not reproducible.
    """
    if not path.exists():
        return None, f"{path} does not exist", None
    if path.is_dir():
        return None, f"{path} is a directory, not a policy document", None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"{path} could not be read: {exc}", None
    if not raw.strip():
        return None, (f"{path} is empty: it declares no required view, and an "
                      "empty policy is not the same as a permissive one"), None
    try:
        doc = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        return None, f"{path} is not valid JSON: {exc}", None
    if not isinstance(doc, dict):
        return None, f"{path} does not hold a policy object", None
    return F.policy_from_document(doc), None, doc


def feasibility_fn(policy: F.FeasibilityPolicy) -> S.FeasibilityFn:
    """A `FeasibilityFn` the ledger can call, backed by the shipped hard gate.

    The candidate document handed to `promotion_verdict` carries the trial's
    own canonical metric records and NOTHING else -- no summary field, no
    waiver list, no knob values. The gate reads records or it reads nothing,
    and this keeps that true across the bridge.
    """
    def _fn(candidate: "S.Candidate") -> S.FeasibilityVerdict:
        result = F.promotion_verdict(
            {"candidate_id": candidate.identity,
             "metrics": list(candidate.metrics)},
            policy)
        terms = {a.name: TERM_MAP.get(a.status, "NOT_CHECKED")
                 for a in result.axes}
        # Any term the axis table did not fill stays explicitly NOT_CHECKED
        # rather than absent: a reader must be able to see there are nine.
        for t in S.FEASIBILITY_TERMS:
            terms.setdefault(t, "NOT_CHECKED")
        return S.FeasibilityVerdict(
            verdict=VERDICT_MAP.get(result.verdict, S.FEAS_UNDETERMINED),
            reason=_reason(result),
            terms=terms)
    return _fn


def _reason(result: "F.FeasibilityResult") -> str:
    """One sentence naming the gate, the verdict and the axes that carried it.

    It never says "clean". A FEASIBLE verdict names the axes that were proved,
    so a nine-axis pass and a pass that happened to have nothing to look at do
    not read the same -- and the second cannot occur, because an axis with no
    evidence is UNDETERMINED and UNDETERMINED is not FEASIBLE.
    """
    by_status: Dict[str, list] = {}
    for a in result.axes:
        by_status.setdefault(a.status, []).append(a.name)
    parts = [f"{status.lower()}: {', '.join(sorted(names))}"
             for status, names in sorted(by_status.items())]
    return (f"{SOURCE_SHIPPED} adjudicated this candidate from its own "
            f"canonical metric records: {result.verdict} — "
            + "; ".join(parts))


def toolchain_record(path: pathlib.Path, doc: Dict[str, Any],
                     policy: F.FeasibilityPolicy) -> Dict[str, Any]:
    """What the manifest publishes about HOW feasibility was decided.

    The policy is recorded by DIGEST as well as by path, because a path is not
    a fact: two runs citing `policy.json` may have adjudicated against two
    different documents, and a reader comparing them has no way to tell.
    """
    return {
        "feasibility_source": SOURCE_SHIPPED,
        "feasibility_policy_path": str(path),
        "feasibility_policy_digest": cj.digest_of(doc),
        "feasibility_required_views": len(policy.required_views),
        "feasibility_limits_declared": sorted(policy.limits),
        "feasibility_axes": [a.name for a in policy.axes],
        "feasibility_waivers_supplied": False,
        "feasibility_note": (
            f"every trial that RAN was adjudicated by {SOURCE_SHIPPED} "
            f"against {len(policy.required_views)} declared required view(s) "
            f"from {path}; no waiver was supplied, so each verdict rests on "
            "the trial's own measured records alone"),
    }


def stub_toolchain_record() -> Dict[str, Any]:
    """What the manifest publishes when NO feasibility function was supplied.

    The note is `stub_feasibility`'s own live-computed reason, so the manifest
    cannot state a basis different from the one the candidates carry, and it
    cannot state a condition the tree contradicts -- the two halves of F-12.
    """
    return {
        "feasibility_source": "STUB",
        "feasibility_note": S.stub_feasibility(S.Candidate({})).reason,
    }
