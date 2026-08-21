"""#634 — a pass tier the ordering guard could not see.

`#632` landed `STRUCTURE-ONLY` in the producer without telling the consumer that
adjudicates dependency ordering. On `origin/main` before this change, the
one-edge control `A4 blocks_on A3` with `A3 = FAIL` and only A4's word varying:

    A4 = PASS             -> 1 ordering violation
    A4 = VACUOUS-PASS     -> 1
    A4 = STRUCTURE-ONLY   -> 0        <- and INCOMPLETE (#599) likewise 0

So a step wearing either word was counted done by the producer's own arithmetic
and escaped the guard — which inverts the incentive the tier exists to create:
the tree that DISCLOSES a library default passed where the design-bound one
failed.

WHY THESE TESTS ARE MOSTLY ABOUT THE DERIVATION. Adding the two words to the
consumer's set would fix today and reproduce the defect on the next tier, which
is precisely how this one arrived. So the fix classifies by FUNCTION — a word is
a done-claim iff it is neither excused nor non-green — and the load-bearing test
below plants a word registered NOWHERE and requires the guard to adjudicate it.

CALIBRATION, before adopting a stricter rule: 133 step-bearing compliance
reports under `benchmark-data/` were scanned; NONE carries `STRUCTURE-ONLY` or
`INCOMPLETE`, so no published verdict moves. And the producer's own headline was
measured byte-identical on two real projects across the change:

    sha256   Steps: 63 total (5/53 executed PASS, 2 DEFERRED via waiver,
                              3 VACUOUS-PASS excluded from executed)
    spm      Steps: 63 total (0/40 executed PASS, 0 DEFERRED via waiver)

NOT IN SCOPE, deliberately. #634 also observes that a DISCLOSED tree sits below
a SILENT one on the executed-PASS numerator, because `pass_count` counts only
`PASS`. That is a flow-policy question about what the published X measures and
it belongs to the owner; this change touches only which words the ordering guard
adjudicates, where the current answer — none of them — has no policy defence.
"""
from __future__ import annotations

import importlib
import pathlib
import re

T = importlib.import_module("_flow_verdict_tiers")
G = importlib.import_module("flow_step_execution_coverage_check")
F = importlib.import_module("flow_compliance_check")

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]


def _violations(a4_status: str) -> int:
    """The one-edge control from the issue: A4 depends on A3, A3 FAILed, and
    only the word on A4 varies."""
    report = {"steps": [{"id": "A3", "name": "a3", "status": "FAIL"},
                        {"id": "A4", "name": "a4", "status": a4_status}]}
    out = G.analyze(report, {"A4": ["A3"]})
    return len(out.get("ordering_violations", []))


# ── the defect, stated as the control that measured it ─────────────────────
def test_STRUCTURE_ONLY_is_adjudicated():
    """THE DEFECT. 0 before this change."""
    assert _violations("STRUCTURE-ONLY") == 1


def test_INCOMPLETE_is_adjudicated():
    """The fourth tier in the same position (#599), found by the derivation
    rather than by being remembered."""
    assert _violations("INCOMPLETE") == 1


def test_a_tier_registered_NOWHERE_is_still_adjudicated():
    """LOAD-BEARING, and the only test here that distinguishes a derivation
    from a longer list. A word invented today is in no set on either side; it
    must still be adjudicated, because the failure this issue records is a word
    added on one side and unknown on the other.

    The fail-SAFE direction matters too: an unregistered word is treated as a
    DONE-CLAIM (checked), never as excused (waved through)."""
    assert _violations("TIER-INVENTED-TODAY") == 1
    assert T.is_done_claim("TIER-INVENTED-TODAY")


def test_the_tiers_that_already_worked_still_do():
    """The accept case — this must not be a rewrite that moves the behaviour."""
    assert _violations("PASS") == 1
    assert _violations("VACUOUS-PASS") == 1


def test_an_EXCUSED_word_is_still_not_a_done_claim():
    """The other half of the derivation. If excusal broke, every waived and
    condition-skipped step in every flow would start reporting violations."""
    assert _violations("WAIVED") == 0
    assert _violations("SKIPPED-CONDITION") == 0
    assert _violations("DEFERRED-BY-UPSTREAM") == 0


def test_a_FAILING_word_is_not_a_done_claim():
    assert _violations("FAIL") == 0
    assert _violations("MISSING") == 0


# ── the classification itself ──────────────────────────────────────────────
def test_the_two_spellings_are_one_word():
    """The producer writes `VACUOUS_PASS`; reports and the consumer say
    `VACUOUS-PASS`. A classifier that saw two words would answer differently
    about the same step."""
    assert T.normalize("VACUOUS_PASS") == T.normalize("VACUOUS-PASS")
    assert _violations("VACUOUS_PASS") == _violations("VACUOUS-PASS") == 1


def test_a_qualified_done_is_not_a_full_pass():
    """The degree distinction the guard needs: a full PASS satisfies a
    predecessor outright; every other done-claim only does so when the
    predecessor's job was not to certify something."""
    assert T.is_full_pass("PASS")
    for w in ("VACUOUS-PASS", "STRUCTURE-ONLY", "INCOMPLETE", "NEW-TIER"):
        assert T.is_qualified_done(w), w
        assert not T.is_full_pass(w), w


def test_an_empty_status_is_not_a_done_claim():
    """`""`/None reach here from a malformed report. Treating an absent word as
    a done-claim would make an unparseable step assert it finished."""
    for bad in (None, "", "   "):
        assert not T.is_done_claim(bad), repr(bad)


# ── the anti-drift device ──────────────────────────────────────────────────
def test_the_producers_vocabulary_is_pinned():
    """WHY THIS TEST EXISTS. The derivation makes an unregistered word land on
    the safe side, but "safe" is not "classified" — a new word that ought to be
    EXCUSED would start blocking runs. So the producer's vocabulary is read out
    of its own source and pinned: adding a word there fails this test, and a
    human decides which set it joins instead of finding out from a verdict.
    """
    src = pathlib.Path(F.__file__).read_text(encoding="utf-8")
    found = {T.normalize(m) for m in
             re.findall(r'\.status = "([A-Z][A-Z_-]+)"', src)}
    assert found == T.PRODUCER_STATUSES, (
        "flow_compliance_check's verdict vocabulary changed. Add the new word "
        "to EXCUSED or NON_GREEN in _flow_verdict_tiers.py, or confirm it is a "
        "done-claim, then update PRODUCER_STATUSES.\n"
        f"  in the producer, not pinned: {sorted(found - T.PRODUCER_STATUSES)}\n"
        f"  pinned, not in the producer: {sorted(T.PRODUCER_STATUSES - found)}")


def test_every_pinned_word_lands_in_exactly_one_place():
    """No word may be both excused and failing, and every one must be
    classifiable — the property the guard's `_REAL_DONE` quietly lacked."""
    for w in T.PRODUCER_STATUSES:
        n = sum((T.is_excused(w), T.is_non_green(w), T.is_done_claim(w)))
        assert n == 1, (w, T.is_excused(w), T.is_non_green(w),
                        T.is_done_claim(w))


def test_both_sides_read_the_same_table():
    """The single-source claim, asserted rather than described."""
    assert F._T is T
    assert G._T is T
    assert G._NOT_APPLICABLE is T.EXCUSED
    assert G._REAL_DONE == {T.FULL_PASS}


def test_the_excused_set_still_holds_exactly_what_it_held_before():
    """`is T.EXCUSED` proves the two sides share an object, NOT that the object
    kept its contents — a rewrite that silently dropped a word would satisfy
    the identity check and start reporting violations on every waived step in
    every flow. So the set is pinned to the literal contents the consumer
    carried before the move."""
    assert T.EXCUSED == {"SKIPPED-CONDITION", "SKIPPED", "WAIVED",
                         "WAIVED-DEFERRED", "DEFERRED-BY-UPSTREAM",
                         "DEFERRED"}


def test_the_done_claim_set_of_a_report_is_derived():
    got = T.done_claims_in(["PASS", "WAIVED", "STRUCTURE-ONLY", "FAIL",
                            "INCOMPLETE", "SKIPPED-CONDITION", "WHATEVER"])
    assert got == {"PASS", "STRUCTURE-ONLY", "INCOMPLETE", "WHATEVER"}


# ── the producer's own second enumeration, one tier behind ─────────────────
def test_the_missing_output_demotion_now_covers_every_done_claim():
    """The same defect one layer over: the demotion that turns a done-claim
    with an absent declared output into MISSING enumerated three tiers and had
    already fallen behind `INCOMPLETE`, so such a step kept its tier.

    Read from the source because the demotion sits mid-function in a
    thousand-line evaluator with no seam to drive; an enumeration reappearing
    there is what this asserts against."""
    src = pathlib.Path(F.__file__).read_text(encoding="utf-8")
    body = "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith("#"))
    assert "_T.is_done_claim(result.status) and missing_entries" in body
    assert 'result.status in ("PASS", "VACUOUS_PASS", "STRUCTURE-ONLY")' \
        not in body


def test_the_total_required_subtraction_is_derived_not_enumerated():
    src = pathlib.Path(F.__file__).read_text(encoding="utf-8")
    body = "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith("#"))
    seg = body[body.index("total_required = "):]
    seg = seg[:seg.index("\n\n")]
    assert "_T.is_excused" in seg, seg
    assert 'counts["WAIVED"]' not in seg, seg

def test_pass_voided_by_dependency_is_not_a_done_claim():
    """vibe-ic#695. #671 introduced this word precisely to say "this is NOT a
    pass", and left it unregistered — so the subtraction rule read it as a
    done-claim, which is the exact inversion this module exists to prevent.

    The anti-drift test above caught it the moment the word appeared. This one
    pins the ANSWER, so registering it in the wrong set later is also caught:
    putting it in EXCUSED would make `total_required` subtract it, and a step
    voided by a violated dependency is still a step that was required and did
    not deliver."""
    w = "PASS_VOIDED_BY_DEPENDENCY"
    assert T.normalize(w) in T.PRODUCER_STATUSES
    assert T.is_done_claim(w) is False
    assert T.normalize(w) in T.NON_GREEN
    assert T.normalize(w) not in T.EXCUSED
