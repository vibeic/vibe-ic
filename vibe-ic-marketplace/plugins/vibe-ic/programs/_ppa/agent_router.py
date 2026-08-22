#!/usr/bin/env python3
"""Program-First diagnosis. The agent is reached only by an explicit waive.

INVARIANT 12: THE PROGRAM HAS THE FIRST RIGHT TO DECIDE
=======================================================
The valuable property of this router is not that it can reach a model. It is
that it usually does NOT. A handoff that happens when the deterministic rules
could have answered is a DEFECT, not a convenience: it replaces a verdict
anyone can reproduce from the bytes with one that depends on which model
answered, and it does so invisibly, because a handoff looks like the system
working.

So the control flow here is one-directional and there is no other path to the
agent: run the rules; if a rule decides, return that decision and stop; only
when the rules explicitly waive is a handoff built at all. `diagnose()` returns
`handoff=None` for every outcome except HANDOFF, and a test asserts that over a
battery of situations the rules can settle.

"THE RULES DID NOT MATCH" IS NOT A WAIVE
========================================
The distinction that does the work here. There are three ways a deterministic
pass can end and they are three different verdicts:

  a rule decided            -> PROGRAM_DECIDED. Nothing is handed over.
  a rule waived, by name    -> HANDOFF, with a reason from the closed set.
  the evidence was not there-> UNDETERMINED. Nothing is handed over.

The third is the one systems get wrong. When a domain cannot be SEEN, the
honest answer is that it was not checked -- not "clean" (which is a false
green) and not "ask the agent" (which promotes a hole in the evidence into a
question about the design). Missing evidence is fixed by producing the
evidence, and a router that routes around it hides the only signal that it is
missing. This is the same rule as: "I could not read it" and "I read it and it
was empty" must never produce the same verdict.

AND THE DISTINCTION INSIDE THAT DISTINCTION
===========================================
A domain can be unmeasurable for two different reasons and they route
differently, which is the subtlest thing in this file:

  the artefact is ABSENT               -> UNDETERMINED (rc=2). Go produce it.
  the tool RAN and failed unrecognisably -> NOVEL_TOOL_FAILURE, a legal waive.

In the second case the evidence about the failure exists and is exactly what a
diagnostic agent is for; in the first there is nothing to diagnose. Collapsing
them would either bury real tool failures as "missing evidence" or turn every
un-run step into an agent call.

WHAT NEVER REACHES THE AGENT, WHATEVER THE REASON SAYS
======================================================
`agent_policy.may_delegate` is called on the QUESTION at the point the handoff
is built, not on the reason. No reason in the closed set makes a
never-delegated question delegable, so the guard must not be reachable through
a reason the caller picked. If the question is `threshold_comparison` and the
rules cannot settle it, the answer is UNDETERMINED and the fix is a new rule.

chip-AGNOSTIC: nothing here reasons about any IC, vendor, SKU or process.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from . import agent_policy, canonical_json

__all__ = [
    "SCHEMA",
    "HANDOFF_SCHEMA",
    "DOMAINS",
    "DOMAIN_LAYER",
    "CONFLICTING_PAIRS",
    "KNOWN_REMEDY",
    "Diagnosis",
    "diagnose",
    "domain_status",
]

SCHEMA = "vibeic.ppa.situation.v1"
HANDOFF_SCHEMA = "vibeic.ppa.agent_handoff.v1"

RC_OK = 0
RC_REFUSED = 1
RC_UNDETERMINED = 2

# The domains a PPA situation can be violated in. Closed, so that an
# unrecognised domain is refused rather than silently ignored -- an ignored
# domain is a violation the router reports clean.
DOMAINS: Tuple[str, ...] = (
    "timing_setup", "timing_hold", "area", "power",
    "drc", "lvs", "antenna", "ir_drop", "em", "equivalence",
)

# Which layer a domain's remedy lives in. Used only to detect that a situation
# spans layers, which is a legal waive reason: a fix in one layer that is
# evaluated in another cannot be chosen by a rule that sees only one of them.
DOMAIN_LAYER: Dict[str, str] = {
    "timing_setup": "physical",
    "timing_hold": "physical",
    "area": "physical",
    "power": "physical",
    "drc": "physical",
    "lvs": "physical",
    "antenna": "physical",
    "ir_drop": "physical",
    "em": "physical",
    "equivalence": "logic",
}

# Pairs whose known remedies push in opposite directions, so applying both
# rules mechanically would undo one with the other. These are the situations a
# single-domain rule table genuinely cannot settle, and they are the honest
# case for MULTI_DOMAIN_CONFLICT.
CONFLICTING_PAIRS: FrozenSet[FrozenSet[str]] = frozenset({
    frozenset({"timing_setup", "area"}),
    frozenset({"timing_setup", "power"}),
    frozenset({"timing_setup", "timing_hold"}),
    frozenset({"timing_setup", "ir_drop"}),
    frozenset({"area", "ir_drop"}),
    frozenset({"power", "timing_hold"}),
})

# The deterministic remedy for a domain violated on its own. Program-First
# means this table is where a case gets ADDED when an agent turns out to have
# been asked something a rule could have answered -- the router improving is
# this dict growing, not the model getting better.
KNOWN_REMEDY: Dict[str, str] = {
    "timing_hold": "insert hold-fixing delay on the violating paths, then "
                   "re-run STA at the same corner set",
    "area": "reduce utilisation target or relax the area-driven effort, then "
            "re-run placement",
    "drc": "re-run the router with the violated rule's spacing honoured; a "
           "geometry edit is never the remedy",
    "antenna": "insert diodes or raise the routing layer on the violating "
               "nets, then re-extract",
    "equivalence": "re-run equivalence with the same key-point mapping; a "
                   "mismatch here is a logic defect, not a tuning knob",
    "em": "widen or split the violating segment, then re-extract",
}

_GATE_VERDICTS: Tuple[str, ...] = ("PASS", "FAIL", "UNDETERMINED", "TOOL_ERROR")

# Tool failure signatures this system already understands. A TOOL_ERROR whose
# signature is in here is NOT novel and does not reach the agent.
KNOWN_TOOL_SIGNATURES: FrozenSet[str] = frozenset({
    "license_unavailable",
    "out_of_memory",
    "timeout",
    "missing_liberty",
    "missing_lef",
})

_PLATEAU_MIN_IDENTICAL = 3


class RouterRefused(Exception):
    """The situation asked for something policy forbids. rc=1, `[REFUSE]`."""


class SituationIncomplete(Exception):
    """The situation could not be read or is missing evidence. rc=2."""


@dataclass
class Diagnosis:
    outcome: str                       # PROGRAM_DECIDED | HANDOFF | UNDETERMINED
    rc: int
    question: str
    violated: List[str] = field(default_factory=list)
    clean: List[str] = field(default_factory=list)
    undetermined: List[str] = field(default_factory=list)
    rule: str = ""
    root_cause: str = ""
    remedy: str = ""
    handoff: Optional[Dict[str, Any]] = None
    notes: List[str] = field(default_factory=list)

    def as_report(self) -> Dict[str, Any]:
        return {
            "schema": "vibeic.ppa.diagnosis.v1",
            "outcome": self.outcome,
            "rc": self.rc,
            "question": self.question,
            "rule": self.rule,
            "root_cause": self.root_cause,
            "remedy": self.remedy,
            "domains": {
                "violated": sorted(self.violated),
                "clean": sorted(self.clean),
                "undetermined": sorted(self.undetermined),
            },
            "handoff": self.handoff,
            "reached_agent": self.handoff is not None,
            "notes": list(self.notes),
        }


def _is_violation(record: Dict[str, Any]) -> Optional[bool]:
    """Deterministic threshold comparison for one canonical metric record.

    Returns True/False, or None when the record cannot support a comparison.
    This is `threshold_comparison`, which spec 4.6 places in the
    never-delegated set: it lives here, in a program, and its answer is a
    function of the bytes alone.
    """
    status = record.get("status")
    if status != "MEASURED":
        # NOT_MEASURED / NOT_APPLICABLE / INVALID / ESTIMATED / DERIVED do not
        # enter a numeric comparison (PPA_INTERFACES.md 2).
        return None
    value = record.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    limit = record.get("limit")
    if limit is None:
        # A slack metric is violated when negative; that is the metric's own
        # definition, not a threshold somebody chose.
        name = str(record.get("metric", ""))
        if ".slack" in name or ".wns" in name or ".tns" in name:
            return float(value) < 0.0
        return None
    if isinstance(limit, bool) or not isinstance(limit, (int, float)):
        return None
    sense = record.get("limit_sense", "max")
    if sense == "max":
        return float(value) > float(limit)
    if sense == "min":
        return float(value) < float(limit)
    return None


def domain_status(situation: Dict[str, Any]
                  ) -> Tuple[List[str], List[str], List[str], List[str]]:
    """Classify every in-scope domain as violated / clean / undetermined.

    Returns (violated, clean, undetermined, novel_tool_signatures).
    """
    scope = situation.get("domains_in_scope")
    if scope is None:
        raise SituationIncomplete(
            "situation declares no domains_in_scope; without it a domain that "
            "is simply absent from the evidence is indistinguishable from one "
            "that was never meant to be checked, and the router would report "
            "clean over a hole")
    if not isinstance(scope, list) or not scope:
        raise SituationIncomplete("domains_in_scope must be a non-empty list")
    unknown = sorted(set(scope) - set(DOMAINS))
    if unknown:
        raise RouterRefused(
            f"domains_in_scope names domain(s) outside the closed set: "
            f"{unknown}; known domains are {list(DOMAINS)}")

    metrics = situation.get("metrics") or []
    gates = situation.get("gates") or []
    if not isinstance(metrics, list) or not isinstance(gates, list):
        raise RouterRefused("metrics and gates must be lists when present")

    by_domain: Dict[str, List[bool]] = {d: [] for d in scope}
    for rec in metrics:
        if not isinstance(rec, dict):
            raise RouterRefused("a metric record is not an object")
        dom = rec.get("domain")
        if dom not in by_domain:
            continue
        verdict = _is_violation(rec)
        if verdict is not None:
            by_domain[dom].append(verdict)

    novel: List[str] = []
    for gate in gates:
        if not isinstance(gate, dict):
            raise RouterRefused("a gate verdict is not an object")
        dom = gate.get("domain")
        verdict = gate.get("verdict")
        if verdict not in _GATE_VERDICTS:
            raise RouterRefused(
                f"gate verdict {verdict!r} is outside the closed set "
                f"{list(_GATE_VERDICTS)}")
        if dom not in by_domain:
            continue
        if verdict == "PASS":
            by_domain[dom].append(False)
        elif verdict == "FAIL":
            by_domain[dom].append(True)
        elif verdict == "TOOL_ERROR":
            sig = gate.get("signature")
            if sig in KNOWN_TOOL_SIGNATURES:
                # Understood failure: it leaves the domain unmeasured, and an
                # unmeasured domain is UNDETERMINED, never clean.
                continue
            novel.append(f"{dom}:{sig}")
        # UNDETERMINED contributes nothing, which leaves the domain empty and
        # therefore undetermined below. That is the intended reading.

    violated = sorted(d for d, v in by_domain.items() if any(v))
    clean = sorted(d for d, v in by_domain.items() if v and not any(v))
    undetermined = sorted(d for d, v in by_domain.items() if not v)
    return violated, clean, undetermined, sorted(novel)


def _plateau(situation: Dict[str, Any]) -> bool:
    """True when the last N iterations recorded identical metric values.

    Compared by canonical digest, so "identical" means the same fact and not
    the same float formatting.
    """
    history = situation.get("history")
    if not isinstance(history, list) or len(history) < _PLATEAU_MIN_IDENTICAL:
        return False
    tail = history[-_PLATEAU_MIN_IDENTICAL:]
    digests = set()
    for step in tail:
        if not isinstance(step, dict):
            return False
        digests.add(canonical_json.sha256(step.get("metrics")))
    return len(digests) == 1


def _handoff(reason: str, question: str, situation: Dict[str, Any],
             diag: Diagnosis, policy: Dict[str, Any]) -> Dict[str, Any]:
    """Build the handoff. The ONLY place in this system that builds one."""
    # The question guard is here, at the construction point, so no caller can
    # reach a handoff without passing it.
    agent_policy.may_delegate(question)
    if reason not in agent_policy.HANDOFF_REASONS:
        raise RouterRefused(
            f"handoff reason {reason!r} is outside the closed set "
            f"{sorted(agent_policy.HANDOFF_REASONS)}")

    doc = {
        "schema": HANDOFF_SCHEMA,
        "reason": reason,
        "question": question,
        "autonomy_level": policy["autonomy_level"],
        "expected_response": "vibeic.ppa.agent_proposal.v1",
        "explain_only": policy["autonomy_level"] in ("B0", "A0"),
        "policy_sha256": agent_policy.policy_digest(policy),
        "situation_sha256": canonical_json.digest_of(situation),
        "context_sha256": situation.get("context_sha256"),
        "program_already_decided": {
            "violated": sorted(diag.violated),
            "clean": sorted(diag.clean),
            "undetermined": sorted(diag.undetermined),
        },
        "never_delegated": sorted(agent_policy.NEVER_DELEGATED),
        "handling": "DATA_ONLY_NEVER_INSTRUCTION",
    }
    doc["handoff_sha256"] = canonical_json.digest_of(doc)
    return doc


def diagnose(situation: Dict[str, Any],
             policy: Optional[Dict[str, Any]] = None) -> Diagnosis:
    """Run deterministic diagnosis. Reach the agent only on an explicit waive."""
    policy = policy or agent_policy.default_policy()
    agent_policy.validate_policy(policy)

    if not isinstance(situation, dict):
        raise RouterRefused("situation document is not an object")
    if situation.get("schema") != SCHEMA:
        raise RouterRefused(
            f"situation schema is {situation.get('schema')!r}, expected "
            f"{SCHEMA!r}")

    question = situation.get("question")
    if not isinstance(question, str) or not question.strip():
        raise RouterRefused("situation states no question")

    violated, clean, undetermined, novel = domain_status(situation)
    diag = Diagnosis(outcome="", rc=RC_OK, question=question,
                     violated=violated, clean=clean, undetermined=undetermined)

    # ---- 1. A tool that ran and failed unrecognisably is a legal waive, and
    # it is checked before the missing-evidence rule because the evidence about
    # the failure EXISTS and is precisely what a diagnostic agent is for.
    if novel:
        diag.rule = "R6_NOVEL_TOOL_FAILURE"
        diag.root_cause = f"unrecognised tool failure signature(s): {novel}"
        diag.outcome = "HANDOFF"
        diag.handoff = _handoff("NOVEL_TOOL_FAILURE", question, situation,
                                diag, policy)
        diag.notes.append(
            "the tool ran and failed with a signature this system does not "
            "know; that is different from the artefact being absent")
        return diag

    # ---- 2. A domain that could not be seen is UNDETERMINED. It is not clean
    # and it is not an agent question.
    if undetermined:
        diag.rule = "R7_EVIDENCE_MISSING"
        diag.outcome = "UNDETERMINED"
        diag.rc = RC_UNDETERMINED
        diag.root_cause = (
            f"no usable evidence for in-scope domain(s) {undetermined}")
        diag.remedy = (
            "produce the missing evidence and re-run; a domain that was not "
            "measured is not a domain that passed, and it is not a question "
            "for an agent either")
        return diag

    # ---- 3. Nothing violated. The rules settle this; no handoff.
    if not violated:
        diag.rule = "R1_NO_VIOLATION"
        diag.outcome = "PROGRAM_DECIDED"
        diag.root_cause = "none: every in-scope domain measured clean"
        diag.remedy = "none"
        return diag

    # ---- 4. A caller may declare it wants a human, and that is honoured
    # before any rule fires -- the rules are not a way to overrule the request.
    if situation.get("human_requested_review") is True:
        diag.rule = "R8_HUMAN_REQUESTED"
        diag.outcome = "HANDOFF"
        diag.root_cause = "a human asked for a review of this situation"
        diag.handoff = _handoff("HUMAN_REQUESTED_REVIEW", question, situation,
                                diag, policy)
        return diag

    # ---- 5. The search made no progress across N iterations.
    if _plateau(situation):
        diag.rule = "R5_PLATEAU"
        diag.outcome = "HANDOFF"
        diag.root_cause = (
            f"{_PLATEAU_MIN_IDENTICAL} consecutive iterations recorded "
            f"identical metrics; the actuator is not moving the measurement")
        diag.handoff = _handoff("PLATEAU", question, situation, diag, policy)
        return diag

    if situation.get("search_space_exhausted") is True:
        diag.rule = "R9_SEARCH_EXHAUSTED"
        diag.outcome = "HANDOFF"
        diag.root_cause = "the declared candidate space is exhausted and " \
                          "violations remain"
        diag.handoff = _handoff("SEARCH_SPACE_EXHAUSTED", question, situation,
                                diag, policy)
        return diag

    # ---- 6. One domain, one known remedy. The commonest case, and the one
    # that must never reach an agent.
    if len(violated) == 1:
        dom = violated[0]
        if dom in KNOWN_REMEDY:
            diag.rule = "R2_SINGLE_DOMAIN_KNOWN_REMEDY"
            diag.outcome = "PROGRAM_DECIDED"
            diag.root_cause = f"{dom} is the only violated in-scope domain"
            diag.remedy = KNOWN_REMEDY[dom]
            return diag
        diag.rule = "R3_SINGLE_DOMAIN_NO_KNOWN_REMEDY"
        diag.outcome = "HANDOFF"
        diag.root_cause = (
            f"{dom} is violated alone but this system holds no deterministic "
            f"remedy for it")
        diag.handoff = _handoff("AMBIGUOUS_ROOT_CAUSE", question, situation,
                                diag, policy)
        diag.notes.append(
            f"adding {dom} to KNOWN_REMEDY is how this stops being an agent "
            f"question; the router improves by that table growing")
        return diag

    # ---- 7. Several domains. Conflict is the exception, not the rule: two
    # violations whose remedies do not fight are still a program decision.
    pairs = [frozenset(p) for p in
             ((a, b) for i, a in enumerate(violated) for b in violated[i + 1:])]
    conflicting = sorted(
        {"/".join(sorted(p)) for p in pairs if p in CONFLICTING_PAIRS})
    if conflicting:
        diag.rule = "R4_MULTI_DOMAIN_CONFLICT"
        diag.outcome = "HANDOFF"
        diag.root_cause = (
            f"violated domains whose known remedies oppose: {conflicting}")
        diag.handoff = _handoff("MULTI_DOMAIN_CONFLICT", question, situation,
                                diag, policy)
        return diag

    layers = {DOMAIN_LAYER[d] for d in violated}
    if len(layers) > 1:
        diag.rule = "R10_CROSS_LAYER"
        diag.outcome = "HANDOFF"
        diag.root_cause = (
            f"violations span layers {sorted(layers)}; a remedy chosen in one "
            f"layer is evaluated in another")
        diag.handoff = _handoff("CROSS_LAYER_REQUIRED", question, situation,
                                diag, policy)
        return diag

    missing = sorted(d for d in violated if d not in KNOWN_REMEDY)
    if missing:
        diag.rule = "R3_MULTI_DOMAIN_NO_KNOWN_REMEDY"
        diag.outcome = "HANDOFF"
        diag.root_cause = (
            f"no deterministic remedy for violated domain(s) {missing}")
        diag.handoff = _handoff("AMBIGUOUS_ROOT_CAUSE", question, situation,
                                diag, policy)
        return diag

    # Several violations, none in conflict, all with known remedies: the rules
    # compose them. This branch is the negative test's target -- "more than one
    # thing is wrong" is NOT by itself a reason to reach a model.
    diag.rule = "R11_MULTI_DOMAIN_COMPOSABLE"
    diag.outcome = "PROGRAM_DECIDED"
    diag.root_cause = f"independent violations in {violated}"
    diag.remedy = "; then ".join(KNOWN_REMEDY[d] for d in violated)
    diag.notes.append(
        "remedies were composed in domain order; none of these pairs is in "
        "CONFLICTING_PAIRS, so applying one does not undo another")
    return diag
