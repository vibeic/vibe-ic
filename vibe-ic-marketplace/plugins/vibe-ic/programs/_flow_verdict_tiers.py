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
}

#: The step is NOT claimed as done and is not held against the run — the
#: producer subtracts exactly these from `total_required`. The extra spellings
#: are consumer-side tolerance for reports written by older producers.
EXCUSED: Set[str] = {
    "WAIVED", "DEFERRED-BY-UPSTREAM", "SKIPPED-CONDITION",
    "SKIPPED", "WAIVED-DEFERRED", "DEFERRED",
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
    """A done-claim that is not a full pass: VACUOUS-PASS, STRUCTURE-ONLY,
    INCOMPLETE, and any tier added later."""
    return is_done_claim(status) and not is_full_pass(status)


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
