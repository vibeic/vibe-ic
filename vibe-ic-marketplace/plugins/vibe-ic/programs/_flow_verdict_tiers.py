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
NON_GREEN: Set[str] = {"FAIL", "MISSING", "SKIPPED-SETUP-REQUIRED"}

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
