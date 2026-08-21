#!/usr/bin/env python3
"""A0 is explain-only, and these tests are what makes that a fact rather than a
sentence in a document.

The spec stages autonomy activation behind gates: B0 replay, then A0/A1
preview, then A2, then A3. A staged gate is only a gate if something goes red
when it is stepped over, so the tests below try to step over it in every way a
future author plausibly would -- a config value, a wider proposal, a key the
schema has not heard of.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from _ppa import agent_policy as ap  # noqa: E402


def proposal(**kw):
    base = {"schema": "vibeic.ppa.agent_proposal.v1",
            "handoff_sha256": "sha256:" + "0" * 64,
            "explanation": "the hold violation is on the scan path"}
    base.update(kw)
    return base


# --------------------------------------------------------------------------
# The staged activation gate.
# --------------------------------------------------------------------------

def test_only_a0_is_activated_today():
    assert ap.ACTIVATED_LEVEL == "A0"
    assert ap.is_activated("B0")
    assert ap.is_activated("A0")
    for level in ("A1", "A2", "A3"):
        assert not ap.is_activated(level)


def test_a_policy_above_the_activated_level_is_refused():
    for level in ("A1", "A2", "A3"):
        policy = ap.default_policy()
        policy["autonomy_level"] = level
        with pytest.raises(ap.PolicyError) as exc:
            ap.validate_policy(policy)
        assert level in str(exc.value)


def test_the_refusal_says_that_raising_the_level_is_a_code_change():
    """The message is the control. A refusal that reads like a configuration
    error invites the reader to look for the configuration that fixes it."""
    policy = ap.default_policy()
    policy["autonomy_level"] = "A3"
    with pytest.raises(ap.PolicyError) as exc:
        ap.validate_policy(policy)
    assert "code change" in str(exc.value)


def test_an_unknown_level_is_refused_and_does_not_sort_below_everything():
    """A sentinel rank would make an unknown level compare as lower than the
    activated one, so an unrecognised level would PASS an `<=` check."""
    with pytest.raises(ap.PolicyError):
        ap.level_rank("A99")
    with pytest.raises(ap.PolicyError):
        ap.is_activated("")


def test_the_default_policy_is_the_most_restrictive_one_expressible():
    """An absent policy must never be more permissive than a present one --
    absence is the commonest way a restriction stops applying."""
    policy = ap.default_policy()
    assert policy["autonomy_level"] == "A0"
    assert policy["allow_list"] == []
    assert policy["blast_radius"]["max_files"] == 0
    assert policy["blast_radius"]["max_actions"] == 0
    assert policy["blast_radius"]["paths"] == []
    assert policy["budget"]["max_tokens"] == 0
    ap.validate_policy(policy)


def test_a0_may_not_declare_a_blast_radius_it_cannot_use():
    """A document describing a capability the level does not have is the one
    somebody later reads as permission."""
    for key in ("max_files", "max_actions"):
        policy = ap.default_policy()
        policy["blast_radius"][key] = 1
        with pytest.raises(ap.PolicyError):
            ap.validate_policy(policy)
    policy = ap.default_policy()
    policy["blast_radius"]["paths"] = ["phase3/"]
    with pytest.raises(ap.PolicyError):
        ap.validate_policy(policy)


def test_a_negative_budget_is_refused():
    policy = ap.default_policy()
    policy["budget"]["max_tokens"] = -1
    with pytest.raises(ap.PolicyError):
        ap.validate_policy(policy)


def test_a_boolean_budget_is_refused():
    """`True` is an int in Python and would pass a naive isinstance check."""
    policy = ap.default_policy()
    policy["budget"]["max_agent_calls"] = True
    with pytest.raises(ap.PolicyError):
        ap.validate_policy(policy)


# --------------------------------------------------------------------------
# The never-delegated closed set.
# --------------------------------------------------------------------------

def test_the_never_delegated_set_is_the_one_the_spec_names():
    assert ap.NEVER_DELEGATED == frozenset({
        "metric_parsing", "hashing", "threshold_comparison",
        "pass_fail_undetermined", "pareto", "budget_accounting",
        "rollback", "waivers", "public_claim_eligibility"})


def test_every_never_delegated_question_is_refused():
    for question in sorted(ap.NEVER_DELEGATED):
        with pytest.raises(ap.PolicyError):
            ap.may_delegate(question)


def test_a_delegable_question_is_allowed():
    ap.may_delegate("root_cause")
    ap.may_delegate("explain_this_report")


def test_a_policy_may_not_narrow_the_never_delegated_set():
    """The narrowing is the interesting edit, so it is the one that is caught.
    A document that quietly drops `waivers` from the list would otherwise look
    like an ordinary configuration."""
    policy = ap.default_policy()
    policy["never_delegated"] = [q for q in policy["never_delegated"]
                                 if q != "waivers"]
    with pytest.raises(ap.PolicyError) as exc:
        ap.validate_policy(policy)
    assert "waivers" in str(exc.value)


def test_a_policy_may_list_extra_never_delegated_questions():
    """Widening the set is always safe and must not be refused, or a caller
    with a stricter local rule would be forced to drop it."""
    policy = ap.default_policy()
    policy["never_delegated"] = sorted(
        set(policy["never_delegated"]) | {"tapeout_signoff"})
    ap.validate_policy(policy)


# --------------------------------------------------------------------------
# The proposal boundary: the artefact that crosses BACK.
# --------------------------------------------------------------------------

def test_an_explain_only_proposal_is_accepted():
    ap.validate_proposal(proposal(
        hypotheses=["the clock tree is unbalanced"],
        suggested_next_checks=["re-run STA at the slow corner"],
        confidence=0.4))


@pytest.mark.parametrize("key", [
    "actions", "action", "tool_calls", "tool_call", "commands", "command",
    "patch", "diff", "file_writes", "writes", "apply", "execute", "shell",
    "eco", "edits", "mutations",
])
def test_a_proposal_that_tries_to_act_is_refused_at_a0(key):
    with pytest.raises(ap.PolicyError) as exc:
        ap.validate_proposal(proposal(**{key: ["anything"]}))
    assert key in str(exc.value)


def test_an_action_named_something_new_is_refused_for_being_unknown():
    """This is why unknown keys are refused rather than ignored. A schema that
    drops what it does not recognise is one an action passes through by being
    given a name nobody enumerated."""
    with pytest.raises(ap.PolicyError) as exc:
        ap.validate_proposal(proposal(perform_operations=["rm -rf"]))
    assert "perform_operations" in str(exc.value)


def test_an_empty_action_list_is_still_an_action_bearing_key():
    """Refusing only non-empty lists would let the shape through today and be
    filled in by a later caller."""
    with pytest.raises(ap.PolicyError):
        ap.validate_proposal(proposal(actions=[]))


def test_a_proposal_must_cite_the_handoff_it_answers():
    p = proposal()
    del p["handoff_sha256"]
    with pytest.raises(ap.PolicyError):
        ap.validate_proposal(p)


def test_a_proposal_answering_a_different_handoff_is_refused():
    """Without this an agent could explain a different, easier situation and
    nothing would notice."""
    with pytest.raises(ap.PolicyError) as exc:
        ap.validate_proposal(proposal(),
                             expected_handoff_sha256="sha256:" + "1" * 64)
    assert "different handoff" in str(exc.value)


def test_a_matching_handoff_hash_is_accepted():
    ap.validate_proposal(proposal(),
                         expected_handoff_sha256="sha256:" + "0" * 64)


def test_a_bare_hex_handoff_reference_is_refused():
    """A bare hex string does not say what produced it. The `sha256:` prefix
    carries the algorithm with the value."""
    with pytest.raises(ap.PolicyError):
        ap.validate_proposal(proposal(handoff_sha256="0" * 64))


def test_an_empty_explanation_is_refused():
    with pytest.raises(ap.PolicyError):
        ap.validate_proposal(proposal(explanation="   "))


def test_confidence_outside_zero_to_one_is_refused():
    for bad in (-0.1, 1.5):
        with pytest.raises(ap.PolicyError):
            ap.validate_proposal(proposal(confidence=bad))


def test_confidence_is_flagged_as_not_being_evidence():
    """It is the number most likely to be quoted as if it were a measurement."""
    notes = ap.validate_proposal(proposal(confidence=0.9))
    assert any("NOT evidence" in n for n in notes)


def test_a_proposal_is_refused_when_the_policy_itself_is_refused():
    """The level check must run before the proposal shape, or an A3 policy
    would be accepted so long as its proposal happened to look like A0."""
    policy = ap.default_policy()
    policy["autonomy_level"] = "A3"
    with pytest.raises(ap.PolicyError):
        ap.validate_proposal(proposal(), policy)


def test_the_policy_digest_is_stable_and_prefixed():
    d1 = ap.policy_digest(ap.default_policy())
    d2 = ap.policy_digest(ap.default_policy())
    assert d1 == d2
    assert d1.startswith("sha256:") and len(d1) == 71
