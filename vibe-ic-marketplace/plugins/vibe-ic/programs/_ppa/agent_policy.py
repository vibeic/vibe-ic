#!/usr/bin/env python3
"""What an agent is ALLOWED to do — the closed sets, and the level that is live.

WHY THIS MODULE IS THE FIRST ONE IN THE AGENT LANE
==================================================
The other two modules in this lane both ask this one for permission. The
context builder asks it what an agent may be shown; the router asks it whether
a question may be handed over at all. Concentrating those answers here is not
tidiness — it is so that "may an agent do X?" has exactly ONE implementation to
audit, and so that raising an autonomy level is a one-line change in a file
whose whole purpose is to be read before that line is changed.

THE STAGED ACTIVATION GATE (spec 4.9.1), AND WHY IT IS A CONSTANT HERE
======================================================================
The spec requires the autonomy levels to be activated in order, each behind its
own gate: B0 replay first, then A0/A1 preview, then A2, then A3. Today only A0
is activated.

`ACTIVATED_LEVEL` below is that gate expressed as data. It is deliberately NOT
a parameter, an environment variable or a CLI flag, because every one of those
turns "the staged gate" into "the staged gate unless someone passes a flag",
and the flag is exactly what gets passed at 3am by the person who is certain
their case is the safe one. Raising autonomy is a code change, a review and a
gate run. That friction is the feature.

A0 IS EXPLAIN-ONLY, AND "EXPLAIN-ONLY" HAS TO BE MACHINE-CHECKABLE
==================================================================
It is not enough to write "A0 is explain-only" in a document and hope every
caller honours it. At A0 the agent returns a PROPOSAL, and this module refuses
any proposal that carries an action, a tool call or a file write — so the
boundary is enforced on the artefact that crosses it, by a program, on every
run. A prose boundary is one an implementation can drift past silently; this
one goes red.

THE QUESTIONS THAT ARE NEVER HANDED OVER, AT ANY LEVEL
======================================================
`NEVER_DELEGATED` is a closed set from spec 4.6, and its membership has one
thing in common: every item is a question whose answer is a CLAIM, and a claim
must be reproducible by re-running a program over the same bytes. If a model
decides whether a number passes a threshold, then the verdict is a function of
the model, so re-running it is not a check and the number it blesses cannot be
published as measured.

Note what this implies and what the router enforces: when the program CANNOT
answer a NEVER_DELEGATED question, the answer is UNDETERMINED. It is never
"ask the agent". A gap in deterministic coverage is a gap to be closed by
writing a rule, not a licence to route around the rule that is missing.

chip-AGNOSTIC: nothing here reasons about any IC, vendor, SKU or process.
"""
from __future__ import annotations

from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from . import canonical_json

__all__ = [
    "SCHEMA",
    "AUTONOMY_LEVELS",
    "ACTIVATED_LEVEL",
    "NEVER_DELEGATED",
    "HANDOFF_REASONS",
    "PolicyError",
    "level_rank",
    "is_activated",
    "default_policy",
    "validate_policy",
    "validate_proposal",
    "may_delegate",
]

SCHEMA = "vibeic.ppa.agent_policy.v1"

# Ordered lowest-authority first. The order IS the staged activation order of
# spec 4.9.1, so `level_rank` and "which levels are live" read off one list.
AUTONOMY_LEVELS: Tuple[str, ...] = ("B0", "A0", "A1", "A2", "A3")

_LEVEL_MEANING: Dict[str, str] = {
    "B0": "replay only: re-runs a recorded case, decides nothing",
    "A0": "explain-only: may describe and propose, may not act",
    "A1": "preview: may render an action it would take, still may not run it",
    "A2": "bounded action inside the allow-list and blast radius",
    "A3": "closed-loop action with rollback authority",
}

# The one live level. See the module docstring for why this is a constant.
ACTIVATED_LEVEL = "A0"

# spec 4.6. Closed set. Every one of these is a claim, and a claim has to be
# reproducible from the bytes by a program.
NEVER_DELEGATED: FrozenSet[str] = frozenset({
    "metric_parsing",
    "hashing",
    "threshold_comparison",
    "pass_fail_undetermined",
    "pareto",
    "budget_accounting",
    "rollback",
    "waivers",
    "public_claim_eligibility",
})

# spec 4.6. Closed set. A handoff carrying anything else is not a handoff this
# system knows how to audit, so it is refused rather than passed along.
HANDOFF_REASONS: FrozenSet[str] = frozenset({
    "PROGRAM_WAIVE",
    "AMBIGUOUS_ROOT_CAUSE",
    "MULTI_DOMAIN_CONFLICT",
    "NOVEL_TOOL_FAILURE",
    "PLATEAU",
    "SEARCH_SPACE_EXHAUSTED",
    "CROSS_LAYER_REQUIRED",
    "HUMAN_REQUESTED_REVIEW",
})

# What an A0 proposal may contain. Anything outside this set is either an
# action (which A0 forbids) or an unknown key (which we refuse rather than
# ignore -- silently dropping a key is how an action sneaks through a schema).
_PROPOSAL_ALLOWED_KEYS: FrozenSet[str] = frozenset({
    "schema", "handoff_sha256", "explanation", "hypotheses",
    "suggested_next_checks", "confidence", "agent_identity",
})
_PROPOSAL_REQUIRED_KEYS: Tuple[str, ...] = (
    "schema", "handoff_sha256", "explanation",
)

# Keys whose presence means the proposal is trying to ACT. Named explicitly so
# the refusal message can say which one appeared, rather than "unknown key".
_ACTION_BEARING_KEYS: Tuple[str, ...] = (
    "actions", "action", "tool_calls", "tool_call", "commands", "command",
    "patch", "diff", "file_writes", "writes", "apply", "execute", "shell",
    "eco", "edits", "mutations",
)


class PolicyError(Exception):
    """A policy refusal. Callers map this to rc=1 and print `[REFUSE]`.

    Deliberately NOT raised for "I could not read the input" -- that is a
    different verdict (rc=2) with a different marker, and collapsing the two is
    the failure this repository has paid for more than once: a run that never
    opened its input must not report a finding about the design.
    """


def level_rank(level: str) -> int:
    """Position of `level` in the staged activation order.

    Raises PolicyError for a level that is not in the closed set, rather than
    returning -1 -- a sentinel would compare as "lower than everything" and so
    an unknown level would silently pass an `<= ACTIVATED_LEVEL` check.
    """
    try:
        return AUTONOMY_LEVELS.index(level)
    except ValueError:
        raise PolicyError(
            f"unknown autonomy level {level!r}; the closed set is "
            f"{list(AUTONOMY_LEVELS)}") from None


def is_activated(level: str) -> bool:
    """True when `level` is at or below the one level that is live today."""
    return level_rank(level) <= level_rank(ACTIVATED_LEVEL)


def describe_level(level: str) -> str:
    return _LEVEL_MEANING[level] if level in _LEVEL_MEANING else "unknown"


def default_policy() -> Dict[str, Any]:
    """The policy a caller gets when it does not supply one.

    It is the most restrictive policy the system can express, on the principle
    that a missing policy must never be more permissive than a present one. An
    absent config is the commonest way a restriction stops applying, so absence
    here resolves to A0, an empty allow-list and a zero action budget.
    """
    return {
        "schema": SCHEMA,
        "autonomy_level": "A0",
        "allow_list": [],
        "blast_radius": {
            "max_files": 0,
            "max_actions": 0,
            "paths": [],
        },
        "budget": {
            "max_agent_calls": 1,
            "max_tokens": 0,
            "max_wall_seconds": 0,
        },
        "never_delegated": sorted(NEVER_DELEGATED),
    }


def validate_policy(policy: Dict[str, Any]) -> List[str]:
    """Refuse a policy document that does not describe a live, safe policy.

    Returns the list of notes for the report. Raises PolicyError on refusal.
    """
    if not isinstance(policy, dict):
        raise PolicyError("policy document is not an object")
    if policy.get("schema") != SCHEMA:
        raise PolicyError(
            f"policy schema is {policy.get('schema')!r}, expected {SCHEMA!r}")

    level = policy.get("autonomy_level")
    if not isinstance(level, str):
        raise PolicyError("policy carries no autonomy_level")
    if not is_activated(level):
        # The staged gate. This is the refusal that stops this lane from
        # becoming the thing the staged gates exist to prevent.
        raise PolicyError(
            f"autonomy level {level!r} ({describe_level(level)}) is not "
            f"activated; the activated level is {ACTIVATED_LEVEL!r} "
            f"({describe_level(ACTIVATED_LEVEL)}). Raising it is a code "
            f"change behind its own gate (spec 4.9.1), not a config value.")

    notes: List[str] = []

    # A policy may only ever SHRINK the never-delegated set relative to nothing
    # -- i.e. it may not remove an item from it. A document that lists a
    # narrower set is refused, because the narrowing is the interesting edit.
    declared = policy.get("never_delegated")
    if declared is not None:
        if not isinstance(declared, list):
            raise PolicyError("never_delegated must be a list when present")
        missing = sorted(NEVER_DELEGATED - set(declared))
        if missing:
            raise PolicyError(
                "policy narrows the never-delegated set; these questions are "
                f"never delegable at any autonomy level and were dropped: "
                f"{missing}")

    br = policy.get("blast_radius") or {}
    if not isinstance(br, dict):
        raise PolicyError("blast_radius must be an object when present")
    # At A0 nothing may act, so a non-zero blast radius is not merely unused --
    # it is a policy that describes a capability the level does not have, and
    # such a document is the one somebody later reads as permission.
    if level == "A0":
        for key in ("max_files", "max_actions"):
            val = br.get(key, 0)
            if not isinstance(val, int) or val != 0:
                raise PolicyError(
                    f"A0 is explain-only, so blast_radius.{key} must be 0, "
                    f"got {val!r}")
        if br.get("paths"):
            raise PolicyError(
                "A0 is explain-only, so blast_radius.paths must be empty; "
                f"got {br.get('paths')!r}")
        notes.append("A0: blast radius is zero by level, not by configuration")

    budget = policy.get("budget") or {}
    if not isinstance(budget, dict):
        raise PolicyError("budget must be an object when present")
    for key, val in sorted(budget.items()):
        if not isinstance(val, int) or isinstance(val, bool) or val < 0:
            raise PolicyError(
                f"budget.{key} must be a non-negative integer, got {val!r}")

    return notes


def may_delegate(question: str) -> None:
    """Raise PolicyError when `question` is one that is never handed to an AI.

    Called by the router before any handoff is built. It takes the QUESTION,
    not the reason, on purpose: no handoff reason in the closed set makes a
    never-delegated question delegable, so the check must not be reachable via
    a reason the caller chose.
    """
    if question in NEVER_DELEGATED:
        raise PolicyError(
            f"{question!r} is never delegated to an agent at any autonomy "
            f"level (spec 4.6). When the program cannot answer it the answer "
            f"is UNDETERMINED, not a handoff -- a gap in deterministic "
            f"coverage is closed by writing a rule, not by routing around the "
            f"rule that is missing.")


def validate_proposal(proposal: Dict[str, Any],
                      policy: Optional[Dict[str, Any]] = None,
                      expected_handoff_sha256: Optional[str] = None
                      ) -> List[str]:
    """Refuse an agent proposal that exceeds the activated autonomy level.

    This is the enforcement point for "A0 is explain-only". The proposal is the
    artefact that crosses back from the agent, so it is the only place the
    boundary can be checked against what the agent actually produced rather
    than against what it was asked to produce.
    """
    policy = policy or default_policy()
    validate_policy(policy)
    level = policy["autonomy_level"]

    if not isinstance(proposal, dict):
        raise PolicyError("proposal document is not an object")
    if proposal.get("schema") != "vibeic.ppa.agent_proposal.v1":
        raise PolicyError(
            f"proposal schema is {proposal.get('schema')!r}, expected "
            f"'vibeic.ppa.agent_proposal.v1'")

    present_actions = [k for k in _ACTION_BEARING_KEYS if k in proposal]
    if present_actions and level in ("B0", "A0"):
        raise PolicyError(
            f"proposal carries action-bearing key(s) {present_actions} but "
            f"the activated level is {level!r} ({describe_level(level)}). An "
            f"explain-only proposal describes; it does not act.")

    unknown = sorted(set(proposal) - _PROPOSAL_ALLOWED_KEYS)
    if unknown:
        # Refused, not ignored. A schema that drops unknown keys is a schema an
        # action can be smuggled through by naming it something new.
        raise PolicyError(
            f"proposal carries key(s) not in the A0 proposal shape: {unknown}. "
            f"Unknown keys are refused rather than ignored, so a new name for "
            f"an action cannot pass by being unrecognised.")

    for key in _PROPOSAL_REQUIRED_KEYS:
        if key not in proposal:
            raise PolicyError(f"proposal is missing required key {key!r}")

    notes: List[str] = []

    # The proposal must answer the handoff it was given. Without this an agent
    # could return an explanation of a different, easier situation and nothing
    # would notice -- the hash is what makes the pairing checkable.
    got = proposal.get("handoff_sha256")
    if not isinstance(got, str) or not got.startswith("sha256:"):
        raise PolicyError(
            f"proposal.handoff_sha256 must be a 'sha256:<hex>' string, "
            f"got {got!r}")
    if expected_handoff_sha256 is not None and got != expected_handoff_sha256:
        raise PolicyError(
            "proposal answers a different handoff: it cites "
            f"{got} but was checked against {expected_handoff_sha256}")

    if not isinstance(proposal.get("explanation"), str) or \
            not proposal["explanation"].strip():
        raise PolicyError("proposal.explanation must be a non-empty string")

    conf = proposal.get("confidence")
    if conf is not None:
        if isinstance(conf, bool) or not isinstance(conf, (int, float)):
            raise PolicyError(
                f"proposal.confidence must be a number when present, "
                f"got {conf!r}")
        if not (0.0 <= float(conf) <= 1.0):
            raise PolicyError(
                f"proposal.confidence must lie in [0,1], got {conf!r}")
        notes.append(
            "confidence is the agent's own, is NOT evidence, and may not "
            "enter any threshold comparison (spec 4.6 never-delegated)")

    return notes


def policy_digest(policy: Dict[str, Any]) -> str:
    """`sha256:<hex>` of the policy actually in force, for the run record."""
    return canonical_json.digest_of(policy)
