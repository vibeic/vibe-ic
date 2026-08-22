#!/usr/bin/env python3
"""Arms, fairness conditions, and the independent scorer for a PPA head-to-head.

CHIP_AGNOSTIC: strict-logic — no process, vendor or PDK name in the LOGIC of this
file. `test_ppa_benchmark_fairness::test_the_library_is_chip_and_pdk_and_vendor_agnostic` strips the module docstring before it looks, so the docstring MAY name
one; the code below may not. This is STRICTER than the repo-wide
`source_chip_agnostic_check`, whose PASS is not this file's verdict.

WHAT THIS MODULE IS FOR, IN ONE SENTENCE
========================================

    SAME RTL, SAME PDK, LOWER POWER, HIGHER PERFORMANCE, SMALLER AREA -- THAT IS
    BETTER.

That sentence is the whole product claim, and this module exists to make it
UNARGUABLE. It does not compute any number about any design. It reads a record
somebody else produced and decides whether the numbers in it are ALLOWED to be
compared at all -- and when they are not, it says UNDETERMINED rather than
picking a winner.

THE FOUR WAYS THAT SENTENCE BECOMES ARGUABLE, AND ALL FOUR ARE CHECKABLE
=======================================================================

  the same STAGE            synthesis area is not post-route area
  the same corner/mode      an arm at tt/25C is not an arm at ss/125C
  the same activity basis   vectorless power is not VCD power
  both arms FEASIBLE        smaller area with DRC violations is not smaller

Every one of those is a SCOPE question, and the frozen interface
(`docs/PPA_INTERFACES.md` section 2) already gives the answer in the general
case: "Two numbers are comparable only if their `scope` matches. [...] A
comparison across differing scope is UNDETERMINED, not a winner." This module is
that rule applied to the one document where the stakes are a published claim.

The v1 record carried each axis as a BARE FLOAT. A bare float has no scope, so a
v1 record cannot answer any of the four questions above -- not "it answered them
badly", but "there is nothing in the document that could answer them". That is
why v2 exists and why a v1-shaped record is UNDETERMINED here rather than
refused: the checker could not look.

AND A FIFTH, WHICH IS THE ONE THAT WOULD DESTROY THE RESULT FASTEST
==================================================================

A TUNED ARM MUST BE ALLOWED TO TUNE.

Publishing a win over a deliberately weakened opponent is the same defect as a
gate that cannot fail: the outcome was decided by the setup and not by the
thing being measured. If the opponent's flow ships a tuner -- ORFS AutoTuner is
the case in front of us -- then the opponent gets its tuner, its OFFICIAL search
space, and a budget no smaller than ours, or the comparison is not a comparison.

This is NOT already covered by the v1 `tuned_by_this_project: false` refusal, and
the gap is the interesting part. That flag asks "did we hand-tune their config?"
and a campaign can answer `false` truthfully while having handed the opponent a
search space we wrote and a budget of five trials against our five hundred. The
flag catches the crude rigging; the budget and the search-space provenance catch
the polite kind.

WHY THE SCORER TAKES ONLY THE ARMS
==================================

`score()` is given `arms` and nothing else. It CANNOT see the record's asserted
verdict, because the parameter that would carry it does not exist. That is a
structural guarantee rather than a promise: a future author who wants the scorer
to agree with the record has to change the signature to do it, and changing the
signature is visible in a diff in a way that reading one extra dict key is not.
The comparison of derived-vs-asserted happens OUTSIDE the scorer, in the caller.

WHAT IS NOT HERE
================

No thresholds about any tool's output, and no parsing of any tool's output --
that is `_ppa/backends/*.py`, one module per tool, by the module map in
`docs/PPA_INTERFACES.md` section 4. No feasibility THRESHOLDS either:
`_ppa/feasibility.py` owns the question "is this implementation feasible". This
module owns the strictly narrower question "were the two arms asked the same
feasibility question, and did both of them pass it" -- which is a fairness
property of a COMPARISON and belongs nowhere else.

chip-AGNOSTIC, PDK-AGNOSTIC, vendor-AGNOSTIC: no design, PDK, process, vendor or
part literal appears in the logic or can affect it. Every domain value here
(stage names, activity bases, tool-agnostic check names) is compared to the
OTHER arm's value and is never interpreted as naming a particular technology.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from . import canonical_json

__all__ = [
    "RC_OK", "RC_REFUSED", "RC_UNDETERMINED",
    "SCHEMA_V1", "SCHEMA_V2", "AXES",
    "Refusal",
    "record_schema", "axis_scope", "axis_value",
    "PROBLEM_FIELDS",
    "check_contract_identity", "check_scope_parity", "check_stage_basis_agreement",
    "check_feasibility", "check_tuning_parity",
    "derive_feasibility", "pareto_relation", "score",
    "VERDICT_CLEAN", "CHECK_CLEAN", "CHECK_VIOLATIONS",
    "CHECK_NOT_CHECKED",
]

RC_OK = 0
RC_REFUSED = 1
RC_UNDETERMINED = 2

SCHEMA_V1 = "vibeic.ppa.comparison.v1"
SCHEMA_V2 = "vibeic.ppa.comparison.v2"

#: The three axes, and which direction is better. This is the whole of the
#: module's PPA knowledge and it is a physical fact, not a tuning choice.
AXES: Dict[str, str] = {
    "area_um2": "lower",
    "timing_wns_ns": "higher",
    "power_mw": "lower",
}

#: WHICH AXES A PERCENTAGE IS MEANINGFUL FOR, and this is measurement theory
#: rather than a formatting preference.
#:
#: Area and power are RATIO-scale: they have a true zero and cannot be negative,
#: so "16% smaller" is a statement about the quantity. Worst negative slack is
#: INTERVAL-scale: it crosses zero, its zero is a threshold and not an absence,
#: and a ratio built on it is not a fact about timing.
#:
#: THIS IS NOT PEDANTRY, AND THE FIRST v2 REPORT SHOWED WHY. Rendering an arm
#: that improved WNS from -0.30 ns to -0.10 ns, the inherited formula
#: (s - o) / o printed
#:
#:     timing_wns_ns  subject=-0.1  baseline=-0.3  (higher better) -66.67%
#:                                                          -> SUBJECT_BETTER
#:
#: A MINUS SIXTY-SIX PERCENT beside the word BETTER. The number is arithmetically
#: correct and it is unquotable: its sign is decided by the SIGN OF THE BASELINE,
#: so the same 0.2 ns improvement prints positive against a positive baseline and
#: negative against a negative one. Negative slack is the normal case for an arm
#: that has not closed, which is exactly when a comparison gets published, so
#: this would have been the common rendering and not the rare one. It is the
#: kind of figure an opponent quotes back.
#:
#: The absolute delta is emitted for every axis, carries a sign that means one
#: thing, and is the honest answer for an interval-scale quantity.
AXIS_SCALE: Dict[str, str] = {
    "area_um2": "ratio",
    "timing_wns_ns": "interval",
    "power_mw": "ratio",
}


class Refusal(Exception):
    """A record that cannot support the claim printed on it.

    `rc` follows `docs/PPA_INTERFACES.md` section 1 exactly, and the split is
    load-bearing:

        1  the record is DEFECTIVE and the defect is demonstrable from the
           record itself -- a claim about the comparison, and through it about
           silicon
        2  the record is INCOMPLETE -- the checker could not look, and
           "I could not look" must never reach a reader as "I looked"
    """

    def __init__(self, code: str, message: str, rc: int = RC_REFUSED):
        super().__init__(message)
        self.code = code
        self.message = message
        self.rc = rc


# ---------------------------------------------------------------------------
# Scope vocabulary
# ---------------------------------------------------------------------------

#: Stages at which a number is a PROXY for the property and not the property.
#: `_ppa/area.py` owns the full area taxonomy; this is the comparison's own,
#: narrower use of it -- which stages a PHYSICAL claim may cite.
PROXY_STAGES = ("rtl", "elaborated", "synthesis", "post_synth")

#: Stages at which a number is a physical measurement of a placed-and-routed
#: implementation.
PHYSICAL_STAGES = ("post_place", "post_cts", "post_route",
                   "post_route_extracted", "signed_off_gds", "silicon")

#: Which stages each declared measurement basis is allowed to cite. An arm
#: whose basis and whose stage disagree is contradicting itself INSIDE ONE
#: RECORD, which is the cheapest kind of dishonesty to close.
BASIS_STAGES: Dict[str, Tuple[str, ...]] = {
    "post_route_sta": ("post_route", "post_route_extracted"),
    "signed_off_gds": ("post_route", "post_route_extracted", "signed_off_gds"),
    # A silicon arm measures POWER on a wafer and still takes its AREA from the
    # geometry that was manufactured, so a silicon basis may cite either.
    "silicon": ("post_route", "post_route_extracted", "signed_off_gds",
                "silicon"),
}

#: Scope keys that MUST be present on each axis before parity can even be
#: asked. Declaring an empty scope on both arms must not buy a pass: two
#: numbers that say nothing about themselves are not thereby comparable.
REQUIRED_SCOPE: Dict[str, Tuple[str, ...]] = {
    "area_um2": ("stage",),
    "timing_wns_ns": ("stage", "mode", "process", "voltage_v",
                      "temperature_c", "rc_corner", "check"),
    "power_mw": ("stage", "mode", "process", "voltage_v", "temperature_c",
                 "activity_basis"),
}

#: The identity of the PROBLEM as the v1 refusal names it. Compared as opaque
#: values and never interpreted, which is what keeps this PDK-agnostic.
PROBLEM_FIELDS = ("spec_sha256", "pdk", "clock_target_ns", "corners")

#: A number may enter a numeric comparison only from this status.
#: `docs/PPA_INTERFACES.md` section 2 lists the other five and why each is out.
COMPARABLE_STATUS = "MEASURED"


def record_schema(doc: Mapping[str, Any]) -> str:
    """The schema a record DECLARES. A record that declares nothing is v1.

    Declaring nothing is treated as v1 and not as an error because every record
    written before the fairness conditions existed declares nothing, and the
    honest verdict for those is UNDETERMINED (they carry no scope), which is
    what the v1 path produces. A record cannot buy a PASS by declaring v1
    either: the parity conditions below need a scope, a v1 axis has none, and
    the absence is reported as UNDETERMINED rather than skipped.
    """
    got = doc.get("schema")
    return got if isinstance(got, str) and got else SCHEMA_V1


def axis_value(arm: Mapping[str, Any], axis: str) -> Optional[float]:
    """The number on `axis`, whichever shape the record uses.

    v1 wrote a bare float. v2 writes the canonical metric record. Both are read
    here so that the two shapes differ in what they can be CHECKED for, never in
    what the arithmetic does -- a scorer that computed a v1 delta differently
    from a v2 delta would make the migration itself a source of disagreement.
    """
    ppa = arm.get("ppa")
    if not isinstance(ppa, Mapping):
        return None
    raw = ppa.get(axis)
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, Mapping):
        v = raw.get("value")
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        return float(v)
    return None


def axis_status(arm: Mapping[str, Any], axis: str) -> Optional[str]:
    """The declared status of `axis`, or None when the record does not say."""
    ppa = arm.get("ppa")
    if not isinstance(ppa, Mapping):
        return None
    raw = ppa.get(axis)
    if isinstance(raw, Mapping):
        s = raw.get("status")
        return s if isinstance(s, str) else None
    return None


def axis_scope(arm: Mapping[str, Any], axis: str) -> Optional[Mapping[str, Any]]:
    """The scope of `axis`, or None when the record carries none.

    None and `{}` are deliberately DIFFERENT here, and hard rule 9 is why: an
    axis that declares no scope at all ("I could not look") must not produce the
    same verdict as an axis that declares an empty one ("I looked and there is
    nothing to say"). The first is `None` and yields SCOPE_UNDECLARED; the
    second is `{}` and fails the REQUIRED_SCOPE check by name.
    """
    ppa = arm.get("ppa")
    if not isinstance(ppa, Mapping):
        return None
    raw = ppa.get(axis)
    if not isinstance(raw, Mapping):
        return None
    sc = raw.get("scope")
    return sc if isinstance(sc, Mapping) else None


# ---------------------------------------------------------------------------
# F1 -- contract identity
# ---------------------------------------------------------------------------

def check_contract_identity(arms: Sequence[Mapping[str, Any]]) -> str:
    """Every arm ran the SAME contract, proven by hash and not by heading.

    Returns the shared contract digest.

    WHY THE HASH AND NOT THE FIELDS. The v1 refusal compares four declared
    fields -- spec digest, PDK, clock target, corner set -- and refuses when
    they diverge. That is a good check and it stays. It is also a check over the
    fields somebody chose to put in the record, so a contract that differs in a
    fifth thing (a floorplan constraint, an IO timing budget, a permitted cell
    set) passes it. The contract HASH covers the whole document, so it cannot be
    passed by omission.

    WHY A DIVERGENCE IS rc=2 AND NOT rc=1. A hash mismatch tells you the two
    contracts are not the same document. It does not tell you HOW they differ,
    or which one the campaign meant, and the checker is not entitled to pick.
    UNDETERMINED is the honest verdict and it is also the useful one: the fix is
    to publish the two contracts, not to argue about the number.

    WHY A HASH THAT DISAGREES WITH ITS OWN INLINE CONTRACT IS rc=1. That one IS
    demonstrable from the record alone -- the object is right there, and
    `canonical_json.digest_of` recomputes its identity deterministically. A
    document whose stated identity is not its identity is defective, full stop.
    """
    digests: List[Tuple[str, Optional[str]]] = []
    for a in arms:
        contract = a.get("contract")
        if not isinstance(contract, Mapping):
            raise Refusal(
                "CONTRACT_UNDECLARED",
                f"arm {a.get('flow')!r} declares no `contract` object, so there "
                "is no identity to compare against the other arms'. Two flows "
                "that cannot be shown to have solved the same problem have not "
                "been compared.",
                RC_UNDETERMINED)
        declared = contract.get("sha256")
        if not isinstance(declared, str) or not declared:
            raise Refusal(
                "CONTRACT_UNDECLARED",
                f"arm {a.get('flow')!r} carries a `contract` with no `sha256`.",
                RC_UNDETERMINED)
        body = contract.get("body")
        if isinstance(body, Mapping):
            if not body:
                # The same argument REQUIRED_SCOPE makes one layer down: both
                # arms declaring NOTHING must not satisfy an equality check.
                # Two empty contracts hash identically and say nothing, and an
                # identity that carries no content identifies no problem.
                raise Refusal(
                    "CONTRACT_VACUOUS",
                    f"arm {a.get('flow')!r} carries an EMPTY contract body. "
                    "Two empty contracts hash identically, so this would "
                    "satisfy the identity check while identifying no problem.",
                    RC_UNDETERMINED)
            recomputed = canonical_json.digest_of(body)
            if recomputed != declared:
                raise Refusal(
                    "CONTRACT_HASH_WRONG",
                    f"arm {a.get('flow')!r} states contract identity "
                    f"{declared!r}, but the contract body carried in the SAME "
                    f"record canonicalises to {recomputed!r}. A document whose "
                    "stated identity is not its identity cannot anchor a "
                    "comparison to anything.")
            # ONE ANSWER PER QUESTION. `design` and the contract body both name
            # the PDK, the clock target, the spec digest and the corner set, and
            # this repository has paid before for a fact with two homes and two
            # values -- the reader believes whichever they opened. Where both
            # declare a field it must be the same field, and the check is over
            # the INTERSECTION so that a contract legitimately richer than
            # `design` is not penalised for being richer.
            design = a.get("design") or {}
            clashing = {}
            for field in PROBLEM_FIELDS:
                if field not in design or field not in body:
                    continue
                d, c = design[field], body[field]
                same = (sorted(d) == sorted(c)
                        if field == "corners" and isinstance(d, list)
                        and isinstance(c, list) else d == c)
                if not same:
                    clashing[field] = (d, c)
            if clashing:
                raise Refusal(
                    "CONTRACT_CONTRADICTS_DESIGN",
                    f"arm {a.get('flow')!r} states one problem twice and "
                    "differently: "
                    + "; ".join(f"design.{f}={d!r} vs contract.body.{f}={c!r}"
                                for f, (d, c) in sorted(clashing.items()))
                    + ". A fact with two homes and two values is believed "
                      "according to which one the reader opened.")
        digests.append((str(a.get("flow")), declared))
    distinct = sorted({d for _, d in digests})
    if len(distinct) > 1:
        detail = "; ".join(f"{flow}={d}" for flow, d in digests)
        raise Refusal(
            "CONTRACT_DIVERGED",
            "the arms do not share one contract identity, so they answered "
            f"different questions and there is no winner to report: {detail}",
            RC_UNDETERMINED)
    return distinct[0]


# ---------------------------------------------------------------------------
# F2/F3/F4 -- scope parity: stage, corner/mode, activity basis
# ---------------------------------------------------------------------------

def check_scope_parity(arms: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Per axis: every arm's number was taken under the same conditions.

    This is the single condition that covers three of the lane's four
    arguabilities, because all three are the same defect at different keys:

        stage            `scope.stage`      synthesis area vs post-route area
        corner / mode    `scope.process`, `voltage_v`, `temperature_c`,
                         `rc_corner`, `mode`, `check`
        activity basis   `scope.activity_basis`   vectorless vs VCD

    Treating them as one condition rather than three is not a shortcut -- it is
    the point. A checker with three hand-written comparisons acquires a fourth
    blind spot the day somebody adds a fifth scope key, whereas requiring the
    scope dicts to be EQUAL has no blind spot by construction: a key that exists
    is compared, and a key that does not exist yet is compared the moment it
    does.

    The REQUIRED_SCOPE list stops the degenerate way to satisfy equality, which
    is for both arms to declare nothing.
    """
    out: Dict[str, Any] = {}
    for axis in AXES:
        scopes: List[Tuple[str, Optional[Mapping[str, Any]]]] = [
            (str(a.get("flow")), axis_scope(a, axis)) for a in arms]
        for flow, sc in scopes:
            if sc is None:
                raise Refusal(
                    "SCOPE_UNDECLARED",
                    f"arm {flow!r} carries `{axis}` with no `scope`. A bare "
                    "number cannot say which stage, corner, mode or activity "
                    "basis produced it, so it cannot be shown comparable to "
                    "the other arm's -- and an unshowable comparison is "
                    "UNDETERMINED, never a win.",
                    RC_UNDETERMINED)
            missing = [k for k in REQUIRED_SCOPE[axis] if k not in sc]
            if missing:
                raise Refusal(
                    "SCOPE_INCOMPLETE",
                    f"arm {flow!r}'s `{axis}` scope does not declare "
                    f"{missing}. Both arms declaring nothing would otherwise "
                    "satisfy equality, and two numbers that say nothing about "
                    "themselves are not thereby comparable.",
                    RC_UNDETERMINED)
            # PRESENT-BUT-NULL is the same hole one step in. `k not in sc` is
            # satisfied by `{"process": None}`, and two arms that both declare
            # `process: None` then compare EQUAL and buy the parity they were
            # meant to be refused. Producers reach for null exactly when they
            # could not read the field -- which is when the refusal matters
            # most -- so a required key must carry a stated value or be absent.
            blank = [k for k in REQUIRED_SCOPE[axis]
                     if sc.get(k) is None or sc.get(k) == ""]
            if blank:
                raise Refusal(
                    "SCOPE_SENTINEL",
                    f"arm {flow!r}'s `{axis}` scope declares {blank} with no "
                    "value. `null` and \"\" are not unknown-corner markers: two "
                    "of them compare EQUAL, so two numbers measured under "
                    "conditions nobody recorded would pass as measured under "
                    "the SAME conditions. State the field or omit the key.",
                    RC_UNDETERMINED)
        for flow, sc in scopes[1:]:
            ref_flow, ref_sc = scopes[0]
            if dict(sc) != dict(ref_sc):
                diff = sorted(
                    set(dict(sc).items()) ^ set(dict(ref_sc).items()),
                    key=lambda kv: str(kv[0]))
                keys = sorted({k for k, _ in diff})
                raise Refusal(
                    "SCOPE_DIVERGED",
                    f"`{axis}` was not measured under the same conditions in "
                    f"every arm: {ref_flow} and {flow} differ on {keys} "
                    f"({ref_flow}={ {k: dict(ref_sc).get(k) for k in keys} }, "
                    f"{flow}={ {k: dict(sc).get(k) for k in keys} }). Two "
                    "numbers taken under different conditions are different "
                    "metrics, so this comparison is UNDETERMINED and not a "
                    "result.",
                    RC_UNDETERMINED)
        for a in arms:
            st = axis_status(a, axis)
            if st is not None and st != COMPARABLE_STATUS:
                raise Refusal(
                    "AXIS_NOT_COMPARABLE",
                    f"arm {a.get('flow')!r} declares `{axis}` with "
                    f"status={st!r}. Only {COMPARABLE_STATUS} may enter a "
                    "numeric comparison; everything else carries a reason "
                    "instead of a result.",
                    RC_UNDETERMINED)
        out[axis] = dict(scopes[0][1])
    return out


def check_stage_basis_agreement(arms: Sequence[Mapping[str, Any]]) -> None:
    """An arm may not cite a synthesis number under a sign-off basis.

    The negative fixture the area lane names -- "a candidate that wins on cell
    count and loses on post-route area must not be reported as smaller" -- is
    this check plus `check_scope_parity`: the proxy number cannot masquerade as
    the physical one, in either arm, because the record says which stage it came
    from and the basis says which stages it is entitled to cite.
    """
    for a in arms:
        basis = a.get("measurement_basis")
        allowed = BASIS_STAGES.get(basis)
        if allowed is None:
            continue          # C4 in the caller owns an unknown basis
        for axis in AXES:
            sc = axis_scope(a, axis)
            if sc is None:
                continue      # SCOPE_UNDECLARED in check_scope_parity owns it
            stage = sc.get("stage")
            # A STAGE THAT WAS NEVER STATED CANNOT CONTRADICT ANYTHING.
            # `check_scope_parity` owns completeness and says so precisely
            # ("scope does not declare ['stage', ...]", SCOPE_INCOMPLETE, rc 2);
            # this check owns the case where a stage IS stated and is wrong for
            # the declared basis. The distinction became load-bearing when this
            # check moved AHEAD of parity in `ppa_head_to_head_check.evaluate`:
            # without it, an arm whose `area_um2` scope is `{}` was reported as
            # "taken at stage=None -- a stage this basis does not cover", which
            # names a contradiction that does not exist and buries the real
            # defect, which is that the scope is empty. MEASURED by
            # tests/test_ppa_benchmark_fairness.py::test_VACUOUS_both_arms_
            # declaring_an_EMPTY_scope_does_not_buy_equality, which went red on
            # exactly that substitution.
            if stage is None:
                continue      # SCOPE_INCOMPLETE in check_scope_parity owns it
            if stage in allowed:
                continue
            kind = ("a PROXY stage" if stage in PROXY_STAGES
                    else "a stage this basis does not cover")
            raise Refusal(
                "STAGE_CONTRADICTS_BASIS",
                f"arm {a.get('flow')!r} declares measurement_basis="
                f"{basis!r}, which may cite {list(allowed)}, but its `{axis}` "
                f"was taken at stage={stage!r} -- {kind}. A record that cites "
                "a pre-physical number under a sign-off basis is claiming a "
                "measurement it did not take.")


# ---------------------------------------------------------------------------
# F5 -- feasibility
# ---------------------------------------------------------------------------

#: The floor of checks a comparison needs before "smaller" means anything.
#: `_ppa/feasibility.py` owns the FULL list (it adds IR, EM and equivalence);
#: this is the subset without which the word "better" is not defined, and the
#: parity rule below means a campaign that runs more is held to more.
FEASIBILITY_FLOOR = ("drc", "lvs", "antenna", "setup", "hold", "drv")


#: The three shapes a check may state its result in, and what each means.
#:
#: `violations`  a non-negative integer count.        0 is clean.
#: `status`      CLEAN / VIOLATIONS / NOT_CHECKED.    a stated classification.
#: `verdict`     a literal, for a check that has no count.
#:
#: WHY THERE ARE THREE. Requiring a count on every check is a TYPE ERROR on the
#: checks that do not produce one. LVS answers "do these two circuits match, and
#: which circuit was compared" -- a verdict about a named top-level cell, not a
#: population. The only way to express an LVS-clean arm used to be
#: `violations: 0`, which is a slightly odd thing to write about a verdict and
#: which invites arithmetic on it downstream. And `status` was documented by the
#: `comparison.v2` schema as a first-class alternative for years while this
#: function ignored it, so a record that VALIDATED against the shipped schema
#: and declared `status: CLEAN` on every axis derived as NOT_CHECKED and the
#: whole arm was refused. Measured: with `status: CLEAN` alone the head-to-head
#: refused naming ['antenna','drc','drv','hold','lvs','setup']; with
#: `violations: 0` added for the three physical checks it refused naming only
#: ['drv','hold','setup'], which was the accurate answer.
CHECK_CLEAN = "CLEAN"
CHECK_VIOLATIONS = "VIOLATIONS"
CHECK_NOT_CHECKED = "NOT_CHECKED"

#: Verdict literals that mean a verdict-shaped check is clean, per check name.
#: Sourced from the accept sets `_ppa/feasibility.py` declares on the matching
#: axis, so there is ONE statement in this repository of what an LVS pass looks
#: like. A check name absent from this map has no verdict spelling and must
#: state a count or a status.
VERDICT_CLEAN: Dict[str, Tuple[str, ...]] = {
    "lvs": ("CLEAN", "MATCH"),
    "equivalence": ("PROVEN", "EQUIVALENT"),
}


def _check_result(name: str, c: Mapping[str, Any]) -> Tuple[str, Any, str]:
    """One check -> (CLEAN | VIOLATIONS | NOT_CHECKED, evidence, why).

    A check may state its result more than one way. When it does, the statements
    must AGREE, and when they do not the COUNT wins: `violations: 3` is a
    measurement and `status: CLEAN` beside it is an assertion, and this module's
    whole stance is that an assertion beside its own evidence is where a record
    has room to be dishonest cheaply. The disagreement is reported either way.
    """
    n = c.get("violations")
    has_count = isinstance(n, int) and not isinstance(n, bool) and n >= 0
    status = c.get("status") if c.get("status") in (
        CHECK_CLEAN, CHECK_VIOLATIONS, CHECK_NOT_CHECKED) else None
    verdict = c.get("verdict")
    accept = VERDICT_CLEAN.get(name, ())
    has_verdict = isinstance(verdict, str) and bool(verdict.strip()) and accept

    if status == CHECK_NOT_CHECKED:
        # An explicit "I did not check this" outranks everything else on the
        # record: a count left over from an earlier run must not resurrect it.
        return CHECK_NOT_CHECKED, None, "the check declares status NOT_CHECKED"

    stated: List[str] = []
    if has_count:
        stated.append(CHECK_VIOLATIONS if n > 0 else CHECK_CLEAN)
    if status in (CHECK_CLEAN, CHECK_VIOLATIONS):
        stated.append(status)
    if has_verdict:
        stated.append(CHECK_CLEAN if verdict.strip().upper() in
                      {a.upper() for a in accept} else CHECK_VIOLATIONS)

    if not stated:
        if verdict is not None and not accept:
            return (CHECK_NOT_CHECKED, None,
                    f"the check states verdict {verdict!r}, but {name!r} has no "
                    "verdict spelling; state `violations` or `status`")
        return (CHECK_NOT_CHECKED, None,
                "the check states no `violations` count, no `status` and no "
                "`verdict` this check name accepts")

    if len(set(stated)) > 1:
        # Contradiction. The count is the measurement, so it decides; the
        # disagreement is named so nobody has to diff the record to find it.
        decided = (CHECK_VIOLATIONS if has_count and n > 0
                   else CHECK_CLEAN if has_count
                   else CHECK_VIOLATIONS)
        return decided, n if has_count else None, (
            f"the check contradicts itself: violations={n!r}, status="
            f"{c.get('status')!r}, verdict={verdict!r}. The measured count "
            "decides; an assertion beside its own evidence does not.")
    return stated[0], (n if has_count else verdict if has_verdict else None), ""


def derive_feasibility(arm: Mapping[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """FEASIBLE / INFEASIBLE / NOT_CHECKED, derived from the arm's own evidence.

    Derived and never read off a `verdict` key ON THE ARM, for the same reason
    the PPA verdict is derived: an assertion beside its own evidence is the one
    place a record has room to be dishonest cheaply. A `verdict` on an
    individual CHECK is a different thing -- it is that check's result, the only
    form some checks have, and `_check_result` adjudicates it against the accept
    set the feasibility axis declares.
    """
    checks = (arm.get("feasibility") or {}).get("checks")
    if not isinstance(checks, Mapping) or not checks:
        return "NOT_CHECKED", {"reason": "no `feasibility.checks`"}
    violating: Dict[str, Any] = {}
    unchecked: List[str] = []
    reasons: Dict[str, str] = {}
    contradicting: List[str] = []
    for name in sorted(set(FEASIBILITY_FLOOR) | set(checks)):
        c = checks.get(name)
        if not isinstance(c, Mapping):
            unchecked.append(name)
            reasons[name] = ("the arm declares no object for this check"
                             if c is None else
                             f"`checks.{name}` is {type(c).__name__}, not an object")
            continue
        result, evidence, why = _check_result(name, c)
        if why:
            reasons[name] = why
            if "contradicts itself" in why:
                contradicting.append(name)
        if result == CHECK_NOT_CHECKED:
            unchecked.append(name)
        elif result == CHECK_VIOLATIONS:
            violating[name] = evidence if evidence is not None else \
                c.get("status") or c.get("verdict")
    detail: Dict[str, Any] = {}
    if reasons:
        detail["reasons"] = reasons
    if contradicting:
        detail["contradicting"] = sorted(contradicting)
    if violating:
        return "INFEASIBLE", {"violating": violating,
                              "not_checked": unchecked, **detail}
    if unchecked:
        return "NOT_CHECKED", {"not_checked": unchecked, **detail}
    return "FEASIBLE", {"checked": sorted(checks), **detail}


def check_feasibility(arms: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Both arms were asked the same feasibility question, and both passed it.

    SMALLER AREA WITH DRC VIOLATIONS IS NOT SMALLER. An implementation that does
    not close is not an implementation, so a number taken off it is not a PPA
    result -- it is the cost of a design that does not exist. This is the
    condition that stops the cheapest possible win: relax until it fits, then
    publish the area.

    THE ASYMMETRY CLAUSE IS THE SUBTLE HALF. Running DRC+LVS+antenna on the
    subject and DRC alone on the baseline produces two arms both reporting
    "clean" over different questions, and the arm that was asked less looks
    exactly as good as the arm that was asked more. Requiring the same check SET
    is what makes "both feasible" mean one thing.
    """
    per_arm: Dict[str, Any] = {}
    sets: List[Tuple[str, frozenset]] = []
    for a in arms:
        flow = str(a.get("flow"))
        verdict, detail = derive_feasibility(a)
        per_arm[flow] = {"verdict": verdict, **detail}
        checks = (a.get("feasibility") or {}).get("checks")
        sets.append((flow, frozenset(checks) if isinstance(checks, Mapping)
                     else frozenset()))
        asserted = (a.get("feasibility") or {}).get("verdict")
        if isinstance(asserted, str) and asserted != verdict:
            raise Refusal(
                "FEASIBILITY_CONTRADICTED",
                f"arm {flow!r} asserts feasibility {asserted!r}; the checks "
                f"carried in the same record derive {verdict!r} "
                f"({detail}).")
    not_checked = [f for f, v in per_arm.items()
                   if v["verdict"] == "NOT_CHECKED"]
    if not_checked:
        raise Refusal(
            "FEASIBILITY_NOT_CHECKED",
            f"feasibility is not established for {sorted(not_checked)}: "
            + "; ".join(f"{f}: {per_arm[f].get('not_checked') or per_arm[f]}"
                        for f in sorted(not_checked))
            + ". An unclosed or unverified implementation cannot be the "
              "cheaper one, and a comparison that did not look is "
              "UNDETERMINED.",
            RC_UNDETERMINED)
    ref_flow, ref_set = sets[0]
    for flow, s in sets[1:]:
        if s != ref_set:
            raise Refusal(
                "FEASIBILITY_ASYMMETRIC",
                f"the arms were not asked the same feasibility question: "
                f"{ref_flow} was checked for {sorted(ref_set)}, {flow} for "
                f"{sorted(s)}. Both then report 'clean' over different "
                "questions, and the arm that was asked less looks exactly as "
                "good as the arm that was asked more.")
    infeasible = [f for f, v in per_arm.items() if v["verdict"] == "INFEASIBLE"]
    if infeasible:
        raise Refusal(
            "ARM_INFEASIBLE",
            "an arm does not close, so its numbers are the cost of a design "
            "that does not exist: "
            + "; ".join(f"{f} {per_arm[f]['violating']}"
                        for f in sorted(infeasible))
            + ". Smaller area with violations is not smaller.")
    return per_arm


# ---------------------------------------------------------------------------
# F6 -- the opponent gets to tune
# ---------------------------------------------------------------------------

#: A baseline's search space has to come from the opponent, not from us.
OFFICIAL_SEARCH_SPACE_SOURCES = ("official", "upstream_default")


def _budget(arm: Mapping[str, Any]) -> Dict[str, float]:
    b = (arm.get("tuning") or {}).get("budget")
    if not isinstance(b, Mapping):
        return {}
    return {k: float(v) for k, v in b.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)}


def check_tuning_parity(subject: Mapping[str, Any],
                        baselines: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """The opponent gets its tuner, its official search space, and our budget.

    A WIN OVER A DELIBERATELY WEAKENED OPPONENT IS THE SAME DEFECT AS A GATE
    THAT CANNOT FAIL. Both are outcomes decided by the setup rather than by the
    thing being measured, and this one is worse in one respect: a gate that
    cannot fail merely fails to find defects, whereas a rigged benchmark
    actively publishes a false one.

    THREE DISTINCT WAYS TO WEAKEN AN OPPONENT, AND THE v1 CHECKER SEES NONE:

      (a) do not run their tuner at all while running ours
      (b) run their tuner on a budget smaller than ours
      (c) run their tuner over a search space WE wrote

    (c) is the one that hides behind `tuned_by_this_project: false`. That flag
    is about their CONFIG, and it can be honestly false while the SEARCH SPACE
    -- which decides what the tuner is even able to find -- came from us. So an
    arm that declares `tuned_by_this_project: false` and
    `tuning.search_space.authored_by_this_project: true` is not merely suspect,
    it is self-contradictory, and it is refused as such.

    A flow with no tuner is not weakened by not being tuned. `supported: false`
    is a complete and honest declaration and passes. What is refused is the
    ABSENCE of a declaration, because "we do not know whether the opponent was
    allowed to tune" is exactly the state this condition exists to end.
    """
    out: Dict[str, Any] = {}
    for arm in [subject, *baselines]:
        t = arm.get("tuning")
        if not isinstance(t, Mapping) or "supported" not in t:
            raise Refusal(
                "TUNING_UNDECLARED",
                f"arm {arm.get('flow')!r} declares no `tuning.supported`. "
                "Whether the opponent was allowed to tune is the difference "
                "between a comparison and a demonstration, and it is not "
                "inferable from the numbers.",
                RC_UNDETERMINED)
        if t.get("supported") and t.get("performed") and not isinstance(
                t.get("search_space"), Mapping):
            raise Refusal(
                "TUNING_UNDECLARED",
                f"arm {arm.get('flow')!r} tuned but declares no "
                "`tuning.search_space`. What a tuner was allowed to search "
                "decides what it was able to find.",
                RC_UNDETERMINED)

    s_t = subject.get("tuning") or {}
    s_budget = _budget(subject)
    for b in baselines:
        flow = str(b.get("flow"))
        b_t = b.get("tuning") or {}
        space = b_t.get("search_space") if isinstance(
            b_t.get("search_space"), Mapping) else {}

        if space.get("authored_by_this_project") is True and \
                b.get("tuned_by_this_project") is False:
            raise Refusal(
                "BASELINE_TUNING_CONTRADICTS_ROLE",
                f"baseline {flow!r} declares `tuned_by_this_project: false` "
                "while its tuner searched a space this project authored. The "
                "flag is about their configuration; the search space decides "
                "what their tuner was able to find at all, so the record "
                "contradicts itself.")

        if b_t.get("supported") and s_t.get("performed") and not b_t.get("performed"):
            raise Refusal(
                "OPPONENT_NOT_TUNED",
                f"baseline {flow!r} ships a tuner and was not tuned, while "
                "the subject was. A tuned arm must be allowed to tune, and a "
                "win over an opponent held at its defaults measures the setup "
                "and not the flow.")

        if b_t.get("performed"):
            if space.get("source") not in OFFICIAL_SEARCH_SPACE_SOURCES:
                raise Refusal(
                    "OPPONENT_SEARCH_SPACE_NOT_OFFICIAL",
                    f"baseline {flow!r} was tuned over a search space whose "
                    f"source is {space.get('source')!r}; it must be one of "
                    f"{list(OFFICIAL_SEARCH_SPACE_SOURCES)}. A tuner can only "
                    "find what its search space contains, so a space we chose "
                    "is a result we chose.")
            b_budget = _budget(b)
            shared = sorted(set(s_budget) & set(b_budget))
            if s_t.get("performed") and not shared:
                raise Refusal(
                    "BUDGET_INCOMPARABLE",
                    f"the subject's tuning budget {sorted(s_budget)} and "
                    f"{flow}'s {sorted(b_budget)} share no dimension, so "
                    "whether the opponent got an equal budget cannot be "
                    "decided from this record.",
                    RC_UNDETERMINED)
            short = {k: (s_budget[k], b_budget[k]) for k in shared
                     if b_budget[k] < s_budget[k]}
            if short:
                raise Refusal(
                    "OPPONENT_UNDERBUDGETED",
                    f"baseline {flow!r} was given a smaller tuning budget than "
                    "the subject on "
                    + "; ".join(f"{k}: subject={sv}, {flow}={bv}"
                                for k, (sv, bv) in sorted(short.items()))
                    + ". Search budget buys PPA directly, so a smaller budget "
                      "is a handicap applied to the opponent and the "
                      "difference it bought is not ours.")
        out[flow] = {
            "supported": bool(b_t.get("supported")),
            "performed": bool(b_t.get("performed")),
            "budget": _budget(b),
            "search_space_source": space.get("source"),
        }
    out["_subject"] = {
        "supported": bool(s_t.get("supported")),
        "performed": bool(s_t.get("performed")),
        "budget": s_budget,
    }
    return out


# ---------------------------------------------------------------------------
# Pareto and the scorer
# ---------------------------------------------------------------------------

def pareto_relation(subject: Mapping[str, float],
                    baseline: Mapping[str, float]) -> str:
    """The relation between two triples, over the triple and never a scalar.

    SUBJECT_DOMINATES / BASELINE_DOMINATES / EQUAL / INCOMPARABLE.

    INCOMPARABLE IS A RESULT AND IT IS THE COMMON ONE. Area, timing and power
    trade against each other by construction, so most honest comparisons come
    out mixed, and a mixed result is a TRADE-OFF -- reporting one as a win is
    exactly the collapsed-scalar defect the record already refuses to CARRY,
    arriving instead through the verdict. Nothing here reduces the triple to a
    number, not even to order two candidates: the frontier is over the triple
    (`docs/PPA_INTERFACES.md` section 4, `_ppa/pareto.py`).
    """
    better = worse = 0
    for axis, direction in AXES.items():
        s, o = float(subject[axis]), float(baseline[axis])
        if s == o:
            continue
        if (s < o) == (direction == "lower"):
            better += 1
        else:
            worse += 1
    if better and worse:
        return "INCOMPARABLE"
    if better:
        return "SUBJECT_DOMINATES"
    if worse:
        return "BASELINE_DOMINATES"
    return "EQUAL"


def score(arms: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """The independent scorer: arms in, per-axis verdict + Pareto relation out.

    IT TAKES `arms` AND NOTHING ELSE, ON PURPOSE. There is no parameter through
    which the record's own asserted verdict could reach this function, so it
    cannot agree with an assertion -- it can only compute. Whether the assertion
    matches is a separate question asked by the caller, over this function's
    output. A future author who wants the scorer to see the assertion has to
    widen the signature, and that is visible in a diff in a way that reading one
    more key off a dict is not.

    LOSS IS DERIVED BY THE SAME CODE PATH AS WIN. There is no branch here that
    only a win takes.
    """
    subject = next(a for a in arms if a.get("role") == "subject")
    out: Dict[str, Any] = {"subject": subject["flow"], "per_baseline": {}}
    s_triple = {ax: axis_value(subject, ax) for ax in AXES}
    for b in [a for a in arms if a.get("role") == "baseline"]:
        o_triple = {ax: axis_value(b, ax) for ax in AXES}
        axes: Dict[str, Any] = {}
        for ax, direction in AXES.items():
            s, o = s_triple[ax], o_triple[ax]
            if s == o:
                verdict = "TIE"
            elif (s < o) == (direction == "lower"):
                verdict = "SUBJECT_BETTER"
            else:
                verdict = "BASELINE_BETTER"
            row: Dict[str, Any] = {
                "subject": s, "baseline": o, "better_is": direction,
                "scale": AXIS_SCALE[ax], "verdict": verdict,
                "delta": round(s - o, 6),
                "delta_pct": None,
            }
            # NO NUMERIC SENTINEL: a percentage that is not meaningful is None
            # WITH A STATED REASON, never a 0 and never a silently omitted key.
            if AXIS_SCALE[ax] != "ratio":
                row["delta_pct_reason"] = (
                    f"{ax} is an interval-scale quantity: it crosses zero and "
                    "its zero is a threshold, not an absence, so a ratio built "
                    "on it would take its SIGN from the baseline's sign rather "
                    "than from the direction of the change. The absolute delta "
                    "is the honest figure here.")
            elif o <= 0:
                row["delta_pct_reason"] = (
                    f"the baseline's {ax} is {o}, so a relative change has no "
                    "denominator to be relative to.")
            else:
                row["delta_pct"] = round((s - o) / o * 100.0, 4)
            axes[ax] = row
        axes["pareto"] = pareto_relation(s_triple, o_triple)
        out["per_baseline"][b["flow"]] = axes
    return out
