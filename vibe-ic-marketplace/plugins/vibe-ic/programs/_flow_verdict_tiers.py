"""The ONE place a flow-compliance verdict word is classified. vibe-ic#634.

`flow_compliance_check` PRODUCES per-step verdict words; `flow_step_execution_
coverage_check` CONSUMES them to decide whether a step that claims to be done
may sit downstream of one that is not. Both sides used to carry their own list
of which words mean "done", and the lists drifted:

    producer, v1.9.48 (#632)   result.status = "STRUCTURE-ONLY"   <- a new tier
    consumer, same tree        _REAL_DONE = {"PASS"}              <- never told

A step wearing `STRUCTURE-ONLY` was therefore counted as done by the producer's
own arithmetic (it is in no failing bucket and is not subtracted from
`total_required`) and was invisible to the ordering guard. Measured on the
one-edge control `A4 blocks_on A3`, `A3 = FAIL`, only A4's word varying:

    A4 = PASS             -> 1 ordering violation
    A4 = VACUOUS-PASS     -> 1
    A4 = STRUCTURE-ONLY   -> 0        <- and INCOMPLETE (#599) likewise 0

which inverts the incentive the tier was introduced to create: a tree that
DISCLOSES its content came from a library default passed where the design-bound
one failed. Disclosure became cheaper than being bound to the design.

WHY THIS MODULE IS DERIVED AND NOT A THIRD LIST. Adding the two missing words to
the consumer would fix today and reproduce the defect on the next tier — that is
exactly how this one arrived. So the classification here is a FUNCTION, not an
enumeration of done-ness:

    a word is a DONE-CLAIM iff it is neither EXCUSED nor NON-GREEN

Only the two *negative* sets are enumerated, and they are the producer's own:
`EXCUSED` is precisely what `total_required` subtracts, `NON_GREEN` is precisely
what the failing/missing/setup-required buckets collect. A tier invented tomorrow
is, by construction, a done-claim the moment it is neither — so it is adjudicated
without anyone remembering to come here.

`test_issue634_flow_verdict_tiers.py` plants a word registered nowhere and
asserts both properties, and pins the producer's full vocabulary against
`PRODUCER_STATUSES` so a word added there with no home in either set fails a
test rather than escaping a guard.

SCOPE, stated because the issue asks a second question this does not answer.
#634 also observes that DISCLOSED sits below SILENT on the *executed-PASS
numerator* (`pass_count = counts["PASS"]` excludes the disclosure tiers, so
declaring a library default costs X/Y while quietly reporting PASS does not).
That is a flow-POLICY question about what the published X measures, it is
discussed at length in the producer's own `total_required` comment, and it is
the owner's to settle. This module changes only which words the ORDERING guard
adjudicates, where today's answer — "not at all" — has no policy defence.

CALIBRATED BEFORE ADOPTING: 133 step-bearing compliance reports under
`benchmark-data/` were scanned for the two newly-adjudicated words. NONE carries
either, so no published verdict moves; the change is reachable only by runs that
start emitting them.
"""
from __future__ import annotations

from typing import Optional, Set

#: Every verdict word `flow_compliance_check` can assign to a step, taken from
#: its own `result.status = "..."` sites. Pinned by test so that a word added
#: there without a home below is a test failure, not a silent escape.
PRODUCER_STATUSES: Set[str] = {
    "PASS", "FAIL", "MISSING", "VACUOUS-PASS", "STRUCTURE-ONLY", "INCOMPLETE",
    "WAIVED", "DEFERRED-BY-UPSTREAM", "SKIPPED-CONDITION",
    "SKIPPED-SETUP-REQUIRED",
    # vibe-ic#695 — added by #671 and left unregistered. This module derives
    # done-claim membership BY SUBTRACTION, so a word in neither EXCUSED nor
    # NON_GREEN IS a done-claim: `PASS_VOIDED_BY_DEPENDENCY` — the word #671
    # introduced precisely to say "this is NOT a pass" — was being read as one.
    #
    # That is the mechanism this module exists for working exactly as designed,
    # and it is why the anti-drift test went red the moment the word appeared
    # rather than at the next landing that happened to notice.
    "PASS-VOIDED-BY-DEPENDENCY",
    # vibe-ic#901, 2026-08-22 — the step ran, some clauses examined the design
    # and some examined nothing. CLASSIFIED HERE DELIBERATELY, at the same
    # commit that introduces it, because this module's whole subject is the
    # word that arrives unregistered: registered in neither EXCUSED nor
    # NON_GREEN, so by the derivation above it is a DONE-CLAIM and a QUALIFIED
    # one — identical adjudication to `VACUOUS-PASS`, which is correct, because
    # it is the same tier split by a count and not a new kind of outcome. It
    # may stand under an ordinary process step and may not stand under one
    # whose job was to certify something.
    #
    # It is NOT in EXCUSED: `total_required` must keep subtracting exactly what
    # it subtracted before, and a partially-vacuous step is still a step that
    # was required. It is NOT in NON_GREEN: the step passed, and this word only
    # ever replaces `VACUOUS-PASS`, which is in neither set either — so no
    # run's greenness moves.
    "PARTIALLY-VACUOUS",
    # 2026-08-25 — a step the run declared OUT OF ITS SCOPE via --entry-step.
    # Registered here as well as in EXCUSED because this module adjudicates a
    # word by SUBTRACTION: a status in neither negative set silently becomes a
    # DONE-CLAIM, which for "we never ran this" would be the exact inversion.
    "OUT-OF-SCOPE-BY-ENTRY",
    # RB2-03 (#2063), 2026-09-06 — the step ran, and NOT ONE of its registered
    # sub-gates returned a verdict. Split out of INCOMPLETE, whose sentence is
    # "the input WAS applicable and was NOT examined" over a PARTIAL
    # population: on a 0-of-N run there is no population at all, and a reader
    # cannot tell "245 of 246 answered" from "none did" when both wear the same
    # word. MEASURED on the subservient cell (lane rbsub2, 8HD-8): a no-RTL run
    # printed INCOMPLETE over "0 of 246 structural sub-gate(s) returned a
    # verdict".
    #
    # CLASSIFIED HERE, at the commit that introduces it, and DELIBERATELY given
    # the SAME adjudication as INCOMPLETE — in neither EXCUSED nor NON_GREEN,
    # therefore a QUALIFIED done-claim. It only ever replaces INCOMPLETE, which
    # sits in neither set either, so no run's greenness moves; what changes is
    # that the word now says which of the two situations happened.
    "NOT-MEASURED",
}

#: The step is NOT claimed as done and is not held against the run — the
#: producer subtracts exactly these from `total_required`. The extra spellings
#: are consumer-side tolerance for reports written by older producers.
EXCUSED: Set[str] = {
    "WAIVED", "DEFERRED-BY-UPSTREAM", "SKIPPED-CONDITION",
    "SKIPPED", "WAIVED-DEFERRED", "DEFERRED",
    # Subtracted from total_required: the run DECLARED, before dispatching
    # anything, that it entered the flow downstream of this step. It is excused
    # only under flow_compliance_check's two conditions — upstream of the
    # declared entry AND every output an in-scope step reads is present on disk
    # — so this is never "we skipped it and the artefacts are gone", it is
    # "these artefacts were supplied rather than produced here".
    "OUT-OF-SCOPE-BY-ENTRY",
}

#: The step is a defect or an absence — the producer's `failing` / `missing` /
#: `setup_required_skipped` buckets, which are what keep a run from being green.
NON_GREEN: Set[str] = {"FAIL", "MISSING", "SKIPPED-SETUP-REQUIRED",
                       # #695 — a PASS its own dependency contradicts is
                       # not a pass. NON_GREEN, not EXCUSED: EXCUSED is
                       # what `total_required` SUBTRACTS, and a step
                       # voided by a violated dependency is still a step
                       # that was required and did not deliver.
                       "PASS-VOIDED-BY-DEPENDENCY"}

#: The one word that satisfies a predecessor outright. Every OTHER done-claim is
#: QUALIFIED: it ran and did not fail, but it measured, certified or produced
#: less than a full pass, so it may stand under an ordinary process step and may
#: not stand under one whose job was to certify something.
FULL_PASS = "PASS"


def normalize(status: Optional[str]) -> str:
    """The word in one spelling. The producer writes `VACUOUS_PASS`; reports and
    the consumer say `VACUOUS-PASS`, and a classifier that saw two words where
    there is one would answer differently about the same step."""
    return (status or "").strip().upper().replace("_", "-")


def is_excused(status: Optional[str]) -> bool:
    return normalize(status) in EXCUSED


def is_non_green(status: Optional[str]) -> bool:
    return normalize(status) in NON_GREEN


def is_done_claim(status: Optional[str]) -> bool:
    """DERIVED. Neither excused nor non-green ⇒ the step is claimed as done and
    must be adjudicated for ordering — whatever the word is."""
    s = normalize(status)
    return bool(s) and s not in EXCUSED and s not in NON_GREEN


def is_full_pass(status: Optional[str]) -> bool:
    return normalize(status) == FULL_PASS


def is_qualified_done(status: Optional[str]) -> bool:
    """A done-claim that is not a full pass: VACUOUS-PASS, PARTIALLY-VACUOUS,
    STRUCTURE-ONLY, INCOMPLETE, NOT-MEASURED, and any tier added later."""
    return is_done_claim(status) and not is_full_pass(status)


#: The done-claims that state, in the word itself, that the step measured
#: NOTHING about the design in its own scope. RB2-03 (#2063).
#:
#: WHY THIS SET IS HERE AND NOT IN THE CONSUMER. `flow_compliance_check`'s #1446
#: ordering guard built its "no verdict" population as
#: `{r.id for r in scoped if r.status == "INCOMPLETE"}` — a literal, in a
#: reader, of exactly the kind this module exists to delete. Introducing
#: `NOT-MEASURED` beside `INCOMPLETE` walked straight through it: MEASURED on
#: this tree, the P0 violation line was PRINTED and the gating list came back
#: empty. It is stated once, here, next to the classification it belongs to.
NO_VERDICT_IN_SCOPE: Set[str] = {"INCOMPLETE", "NOT-MEASURED"}


def says_nothing_was_measured(status: Optional[str]) -> bool:
    """The step claimed done and measured nothing in its own scope."""
    return normalize(status) in NO_VERDICT_IN_SCOPE


def done_claims_in(statuses) -> Set[str]:
    """Which words in a report are done-claims. Derived like everything else —
    listing the expected ones here would be the enumeration this module exists
    to delete.

    The anti-drift device is NOT a list of unknown words (by the derivation
    above there are none: an unregistered word is a done-claim, which is the
    fail-SAFE side). It is the `PRODUCER_STATUSES` pin, which fails a test when
    the producer's vocabulary grows so a human classifies the new word instead
    of discovering later which side it silently landed on."""
    return {normalize(s) for s in statuses if is_done_claim(s)}


# ── which TRACK a step is on, and whether it reaches the verdict ──────────
#
# The module above answers "what does this WORD mean". The two predicates
# below answer the two questions the verdict SCOPE asks of a step — which
# track it is on, and whether it counts — and they are here rather than in
# the consumer for the same reason everything else is: a scope kept as a list
# in a reader drifts from the thing it is a list of.
#
#: The flow yaml's own stage word for the analog track. Read from the STEP,
#: never from a step-id allow-list: ids get renumbered and tracks grow steps,
#: and an allow-list goes quiet on exactly the step it did not know about —
#: the same failure mode as the enumerated done-set this module deleted.
ANALOG_STAGE = "stage_analog"


def _field(step, name: str) -> str:
    """One field off a step record in either shape. `flow_compliance_check`
    holds its steps as `StepResult` objects and writes them to the JSON report
    as dicts, and a predicate that saw only one of those would answer
    correctly in the producer and silently `False` in every reader."""
    raw = (step.get(name) if isinstance(step, dict)
           else getattr(step, name, ""))
    return str(raw or "")


def in_analog_track(step) -> bool:
    """Is this canonical step part of the ANALOG track?

    Chip-AGNOSTIC and renumber-proof: the answer comes from the flow yaml's
    own `stage` vocabulary, which is where the track is defined, not from a
    list of step ids kept in a consumer.

    `stage_mixed_signal` (M1-M4) is a DIFFERENT track and is deliberately NOT
    included — see the scoping note in `flow_compliance_check.main`.
    """
    return _field(step, "stage").strip().lower() == ANALOG_STAGE


def scoped_into_verdict(step) -> bool:
    """ABSENT IS NOT FAILED — the discrimination the analog scoping turns on.

    Answers "does this step reach `Overall`?", and it is the COMPLEMENT of the
    registered not-run states — `is_excused`, which is precisely what the
    producer subtracts from `total_required` — never a list of the states that
    cost. On the analog track `SKIPPED-CONDITION` is exactly what "this design
    has no analog content" looks like: every A-step's flow `condition` keys on
    an analog block list, so a pure-digital design — and an explicit
    `--skip-analog` — resolve the whole track to it.

    Everything else is scoped in, INCLUDING a word this tree has never seen.
    Same fail-safe direction as `is_done_claim`: absent is a claim the
    vocabulary has to make, not a default an unregistered word inherits. A
    track that ran and failed, a declared output that was never produced, and
    a step wearing an unregistered status all reach the verdict.
    """
    return not is_excused(_field(step, "status"))
