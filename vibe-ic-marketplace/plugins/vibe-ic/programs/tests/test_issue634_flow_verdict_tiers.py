#!/usr/bin/env python3
"""vibe-ic#634's anti-drift property, carried forward onto `programs/verdict.py`.

WHAT #634 WAS. `flow_compliance_check` PRODUCED per-step verdict words and
`flow_step_execution_coverage_check` CONSUMED them, and each kept its own list
of which words meant "done". The lists drifted: a step wearing `STRUCTURE-ONLY`
was counted as done by the producer's arithmetic and was invisible to the
ordering guard, so a tree that DISCLOSED its content came from a library default
scored where one that said nothing passed. `_flow_verdict_tiers` fixed it by
DERIVING done-ness — "a word is a done-claim iff it is neither EXCUSED nor
NON-GREEN" — so a tier invented tomorrow was adjudicated without anyone
remembering to register it.

WHY THAT MODULE IS GONE, AND THIS FILE IS NOT. Derivation-by-subtraction was the
right answer to a vocabulary that could grow. R-0915-85 made it a vocabulary
that cannot: declared words at the producers, `verdict.parse` refusing an
unregistered word, and
a tree-wide ratchet (`step_verdict_vocabulary_ratchet`) that fails at the commit
which introduces one. So the derivation goes with the module it lived in — but
#634's PROPERTY does not, and it is pinned here against the replacement.

THE ONE ANSWER THAT MOVES, stated because it is a real behaviour change and not
a rename: `INCOMPLETE`, `NOT-MEASURED`, `VACUOUS-PASS` and `STRUCTURE-ONLY` sat
in NEITHER negative set, so by subtraction they were DONE-CLAIMS — a step that
had measured nothing was adjudicated as claiming to be done. Two of them are
`NOT_MEASURED` now and answer False. That is #634's own incentive argument
reaching its conclusion.
"""
from __future__ import annotations

import inspect
import sys

import pytest

from _plugin_tree import plugin_path

sys.path.insert(0, str(plugin_path() / "programs"))

import die_level_deck_rule_attribution as D  # noqa: E402
import verdict as T  # noqa: E402


# ── the vocabulary is closed, and that is now a fact not a convention ────

def test_the_producer_vocabulary_includes_the_declared_attribution_tier():
    """An EXACT, closed set.

    The DRV sign-off standard (owner-approved 2026-09-28, verdict rule 7:
    "只剩有效 waiver，就是 WAIVED ... 永遠不算 PASS") adds one word, WAIVED,
    as a schema change (verdict.SCHEMA_VERSION 2 -> 3). It is NON-GREEN, so
    the #634 partition below is unchanged.
    """
    assert T.PRODUCER_STATUSES == frozenset(
        {"PASS", "PASS_WITH_WAIVERS", D.TIER_PASS_WITH_ATTRIBUTION, "WAIVED",
         "FAIL", "NOT_MEASURED", "NOT_APPLICABLE"})
    assert T.SCHEMA_VERSION == 3


def test_a_word_registered_nowhere_is_refused_not_adjudicated():
    """#634's fail-SAFE direction, strengthened.

    Its rule was "an unregistered word IS a done-claim, which is the fail-safe
    side". The fail-safe side is now earlier: the word never becomes a row.
    """
    for pred in (T.is_done_claim, T.is_excused, T.is_non_green,
                 T.is_full_pass, T.is_qualified_done,
                 T.says_nothing_was_measured):
        with pytest.raises(T.UnknownVerdictWord):
            pred("A-TIER-INVENTED-TOMORROW")


def test_the_two_negative_sets_still_partition_the_vocabulary():
    """EXCUSED and NON_GREEN are disjoint, and what is in neither is a
    done-claim — #634's derivation, asserted over the declared vocabulary."""
    assert not (T.EXCUSED & T.NON_GREEN)
    derived = T.PRODUCER_STATUSES - T.EXCUSED - T.NON_GREEN
    assert derived == {w for w in T.PRODUCER_STATUSES if T.is_done_claim(w)}
    assert derived == {"PASS", "PASS_WITH_WAIVERS"}


# ── the classifications, each in both directions ─────────────────────────

@pytest.mark.parametrize("word,excused,non_green,done,full", [
    ("PASS",              False, False, True,  True),
    ("PASS_WITH_WAIVERS", False, False, True,  False),
    (D.TIER_PASS_WITH_ATTRIBUTION, False, True, False, False),
    ("FAIL",              False, True,  False, False),
    ("NOT_MEASURED",      False, True,  False, False),
    ("NOT_APPLICABLE",    True,  False, False, False),
    ("WAIVED",            False, True,  False, False),
])
def test_each_word_is_classified_one_way(word, excused, non_green, done, full):
    assert T.is_excused(word) is excused
    assert T.is_non_green(word) is non_green
    assert T.is_done_claim(word) is done
    assert T.is_full_pass(word) is full


def test_a_step_that_measured_nothing_is_no_longer_a_done_claim():
    """THE ANSWER THAT MOVED. Under `_flow_verdict_tiers` this was True for
    four words, which is how a disclosure came to cost more than silence."""
    assert not T.is_done_claim("NOT_MEASURED")
    assert T.says_nothing_was_measured("NOT_MEASURED")
    # And the direction that made #634 necessary is now impossible: a step
    # that DISCLOSES a library default is PASS_WITH_WAIVERS carrying
    # Disclosure.STRUCTURE_ONLY, which is a done-claim, so disclosing costs
    # nothing against a silent pass.
    assert T.is_done_claim("PASS_WITH_WAIVERS")
    assert T.is_qualified_done("PASS_WITH_WAIVERS")


def test_only_the_full_pass_satisfies_a_predecessor_outright():
    assert T.FULL_PASS == "PASS"
    assert T.done_claims_in(
        ["PASS", "PASS_WITH_WAIVERS", "NOT_MEASURED", "NOT_APPLICABLE"]) == {
        "PASS", "PASS_WITH_WAIVERS"}


# ── the scope predicates that moved here with the module ─────────────────

def test_only_a_declared_inapplicable_step_is_out_of_the_verdict_scope():
    assert not T.scoped_into_verdict({"status": "NOT_APPLICABLE"})
    for w in ("PASS", "PASS_WITH_WAIVERS", "FAIL", "NOT_MEASURED"):
        assert T.scoped_into_verdict({"status": w}), w


def test_the_analog_track_is_read_from_the_steps_own_stage():
    assert T.in_analog_track({"stage": "stage_analog"})
    assert not T.in_analog_track({"stage": "stage_mixed_signal"})


# ── the anti-drift device itself ─────────────────────────────────────────

def test_the_module_carries_no_alias_map():
    """#634's successor must not acquire the one thing R-0915-85 forbids."""
    src = inspect.getsource(T)
    # CODE, not prose: the module's DESIGN section names `_LEGACY_STATUS_MAP`
    # in the sentence that forbids it, so the scan strips comments and
    # docstrings first — the same discipline `_NOT_PROSE` gates use.
    code = "\n".join(l.split("#")[0] for l in src.splitlines())
    for banned in ("_LEGACY_STATUS_MAP =", "def normalize(",
                   '"SKIPPED-CONDITION":', '"INCOMPLETE":',
                   '"SKIP":', '"WAIVED":'):
        assert banned not in code, banned
