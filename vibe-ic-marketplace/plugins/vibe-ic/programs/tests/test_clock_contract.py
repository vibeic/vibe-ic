#!/usr/bin/env python3
"""``clock_contract`` — the decision boundary, pinned at the module itself.

The sibling test ``test_l8_clock_contract_one_period_per_clock.py`` drives this
module's ONE caller (``phase1_doc_one_shot_runner``) and asserts on the emitted
L8 document. That is the right test for the producer, but it leaves the module's
own contract unpinned: every branch below is reachable only through whatever the
runner happens to emit for one fixture, so a regression in the rule itself would
be caught only by accident.

This module IS a rule, and the rule is a three-way decision — that is its whole
value:

    a record that BORROWED the name vs the record that OWNS it
        -> FOLD the borrowed one away, keeping its number as evidence
    two records that BOTH own the name, at different periods
        -> REFUSE; keep both, pick neither, say so in the document
    the same name at the same period
        -> nothing to reconcile, and nothing reported

Fold what was mis-named, refuse what genuinely disagrees, stay silent when there
is nothing to reconcile. A regression in any one of those three arms is a
different defect, so each is measured here directly against ``clock_contract``.

Everything is asserted through the real functions on real return values — never
a source substring, never a private symbol. Inputs are synthetic (156.25 / 133.0
MHz, 6.4 / 11.2 ns, clocks ``refclk_a`` / ``refclk_b`` / ``div_ck``), chosen to
resemble no real design and to differ from the sibling test's numbers, so a fix
that hardcodes a value or a design name cannot pass.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import clock_contract as CC              # noqa: E402


# ---------------------------------------------------------------------------
# builders — the two record shapes the rule distinguishes
# ---------------------------------------------------------------------------
def _owner(name: str, period_ns: float, strategy: str = "strategy_a") -> dict:
    """A record that OWNS its name: read from the doc, with evidence."""
    return {"name": name, "role": "primary", "domain_kind": "primary",
            "period_ns": period_ns, "extraction_strategy": strategy,
            "evidence": {"file": "input/docs/synthetic.md", "line": 7}}


def _borrowed(name: str, freq_mhz: float) -> dict:
    """A bare frequency literal that had the canonical port name stapled on.

    Both markers the extractor itself writes: ``derived_from`` equal to the
    record's own name (self-referential, carrying no derivation information)
    and the harvesting role.
    """
    return {"name": name, "derived_from": name, "freq_mhz": freq_mhz,
            "role": "extracted_from_doc_freq_mention",
            "extraction_strategy": "doc_freq_mention_keyword_window"}


def _mentions(entry: dict) -> list:
    return entry.get(CC.MENTIONS_KEY) or []


def _periods_in(entries: list) -> list:
    return sorted(p for p in (CC.entry_period_ns(e) for e in entries)
                  if p is not None)


# ===========================================================================
# 1. the three-way decision — the reason this module exists
# ===========================================================================
def test_a_borrowed_name_folds_into_the_record_that_owns_it():
    """Arm 1. The borrowed record never outranks the owner, and its number
    survives as evidence — reconciling is not deleting."""
    owner = _owner("refclk_a", 6.4)
    doc = {"clock_domains": [owner, _borrowed("refclk_a", 133.0)]}

    assert CC.enforce(doc) == [], (
        "a borrowed name colliding with its owner is reconcilable by the "
        "stated rule and must not be reported as a conflict")

    rows = doc["clock_domains"]
    assert len(rows) == 1 and rows[0] is owner, (
        "the borrowed record was left standing next to the record that owns "
        "the name — the document still declares two periods for one clock")
    assert CC.entry_period_ns(rows[0]) == 6.4, (
        "folding changed the owner's period; the owner IS the contract")
    assert any(m.get("freq_mhz") == 133.0 for m in _mentions(owner)), (
        f"the folded frequency was deleted rather than preserved under "
        f"{CC.MENTIONS_KEY} — a reviewer can no longer see the doc mentioned "
        f"it")


def test_two_records_that_both_own_the_name_are_refused():
    """Arm 2. No stated rule ranks one owner over another, so the module
    picks neither, keeps both, and says so."""
    doc = {"clock_domains": [_owner("refclk_a", 6.4, "strategy_a"),
                             _owner("refclk_a", 11.2, "strategy_b")]}

    conflicts = CC.enforce(doc)

    assert len(conflicts) == 1, (
        "two records owning one name at two periods produced "
        f"{len(conflicts)} conflicts — the contradiction was resolved by "
        "picking a period nobody stated")
    c = conflicts[0]
    assert c["clock"] == "refclk_a"
    assert c["resolution"] == "refused"
    assert sorted(c["periods_ns"]) == [6.4, 11.2], (
        "the refusal must report BOTH periods, not the one that won a "
        "list-order race")
    assert len(doc["clock_domains"]) == 2, (
        "refusing dropped a record — that is picking a winner quietly, which "
        "is the defect this module exists to stop")
    assert _periods_in(doc["clock_domains"]) == [6.4, 11.2]
    assert doc[CC.CONFLICT_KEY] == conflicts, (
        "the conflict was returned to the caller but never stamped on the "
        "document, so nothing downstream can see it")


def test_the_same_name_at_the_same_period_is_not_a_conflict():
    """Arm 3. No false positive: one clock declared twice, consistently, in
    two containers and two unit systems, is not a contradiction."""
    doc = {"clocks": [{"name": "refclk_a", "period_ns": 6.4}],
           "clock_domains": [{"name": "refclk_a", "freq_mhz": 156.25}]}

    assert CC.enforce(doc) == [], (
        "156.25 MHz and 6.4 ns are the same period stated two ways; "
        "reporting that as a conflict would block every consistent document")
    assert CC.CONFLICT_KEY not in doc
    assert len(doc["clocks"]) == 1 and len(doc["clock_domains"]) == 1, (
        "a record was folded away although nothing disagreed — the fold must "
        "be triggered by a contradiction, not by a duplicate name")


def test_records_that_all_borrowed_the_name_are_refused_not_reconciled():
    """No owner means no record outranks another, so there is nothing to fold
    onto and the module must not elect one of the borrowers."""
    doc = {"clock_domains": [_borrowed("refclk_a", 156.25),
                             _borrowed("refclk_a", 133.0)]}

    conflicts = CC.enforce(doc)

    assert len(conflicts) == 1 and conflicts[0]["resolution"] == "refused", (
        "with no record owning the name the module promoted a borrowed "
        "record to the contract")
    assert len(doc["clock_domains"]) == 2


def test_refusing_records_the_provenance_of_every_conflicting_record():
    """A refusal a human cannot act on is only a louder silence: the report
    must name which extraction produced each period."""
    doc = {"clock_domains": [_owner("refclk_a", 6.4, "strategy_a"),
                             _owner("refclk_a", 11.2, "strategy_b")]}

    records = CC.enforce(doc)[0]["records"]

    assert {r["extraction_strategy"] for r in records} == {"strategy_a",
                                                           "strategy_b"}
    assert {r["period_ns"] for r in records} == {6.4, 11.2}
    assert all(r["owns_name"] for r in records), (
        "the report must say that each record owns the name — that is the "
        "fact which makes the conflict irreconcilable")
    assert all(r["container"] == "clock_domains" for r in records)


def test_a_stale_conflict_does_not_outlive_the_contradiction():
    """A document that has since become consistent must not stay blocked by
    the record of a conflict that no longer exists."""
    doc = {"clock_domains": [_owner("refclk_a", 6.4)],
           CC.CONFLICT_KEY: [{"clock": "refclk_a", "periods_ns": [6.4, 11.2]}]}

    assert CC.enforce(doc) == []
    assert CC.CONFLICT_KEY not in doc, (
        "a resolved conflict lingered on the document and will fail a clean "
        "run forever")


def test_a_document_with_nothing_to_check_is_not_an_error():
    """The rule is applied to every L8 document, most of which carry no clock
    record at all."""
    assert CC.enforce({}) == []
    assert CC.enforce({"clock_domains": []}) == []
    assert CC.enforce({"clock_domains": "not a list"}) == []
    assert CC.enforce({"clock_domains": [{"period_ns": 6.4}]}) == []
    assert CC.enforce("not a document") == []


def test_conflict_messages_names_the_clock_and_both_periods():
    """The refusal has to reach a human as a sentence, not only as JSON."""
    doc = {"clock_domains": [_owner("refclk_a", 6.4, "strategy_a"),
                             _owner("refclk_a", 11.2, "strategy_b")]}
    CC.enforce(doc)

    messages = CC.conflict_messages(doc, "L8_TIMING_WAVEFORM")

    assert len(messages) == 1
    text = messages[0]
    for token in ("L8_TIMING_WAVEFORM", "refclk_a", "6.4", "11.2",
                  "strategy_a", "strategy_b"):
        assert token in text, f"the refusal message never mentions {token!r}"
    assert CC.conflict_messages({}, "L8") == []


# ===========================================================================
# 2. PERIOD_REL_TOL — where "nearly the same" stops being the same clock
# ===========================================================================
# The tolerance decides whether a real disagreement gets folded away as noise,
# so it is pinned from BOTH sides with LITERAL periods. Deriving these numbers
# from CC.PERIOD_REL_TOL would move the fixtures with the constant and the
# tests could never go red on it.
#
#   20.0 vs 20.19 -> 0.95 % apart, inside the 1 % tolerance: the same clock
#   20.0 vs 20.21 -> 1.05 % apart, outside it: a real disagreement
def test_periods_just_inside_the_tolerance_are_one_clock():
    assert CC.periods_agree(20.0, 20.19), (
        "20.19 ns is 0.95 % from 20.0 ns — inside the 1 % tolerance — and "
        "must read as one clock measured twice")
    assert CC.periods_agree(20.19, 20.0), "the comparison is not symmetric"
    assert CC.distinct_periods([20.0, 20.19]) == [20.0]

    doc = {"clock_domains": [_owner("refclk_a", 20.0, "strategy_a"),
                             _owner("refclk_a", 20.19, "strategy_b")]}
    assert CC.enforce(doc) == [], (
        "two owners agreeing to within the tolerance were refused as a "
        "conflict — every rounded restatement of one clock now blocks a run")


def test_periods_just_outside_the_tolerance_are_a_real_disagreement():
    assert not CC.periods_agree(20.0, 20.21), (
        "20.21 ns is 1.05 % from 20.0 ns — outside the 1 % tolerance — and "
        "must read as two different periods")
    assert not CC.periods_agree(20.21, 20.0), "the comparison is not symmetric"
    assert CC.distinct_periods([20.0, 20.21]) == [20.0, 20.21]

    doc = {"clock_domains": [_owner("refclk_a", 20.0, "strategy_a"),
                             _owner("refclk_a", 20.21, "strategy_b")]}
    conflicts = CC.enforce(doc)
    assert len(conflicts) == 1, (
        "a genuine 1.05 % disagreement was absorbed by the tolerance — a "
        "widened tolerance silently folds real contradictions away")
    assert sorted(conflicts[0]["periods_ns"]) == [20.0, 20.21]


def test_the_tolerance_is_relative_to_the_period_not_an_absolute_slack():
    """The same absolute gap must be noise on a slow clock and a real
    disagreement on a fast one; an absolute tolerance cannot do both."""
    assert not CC.periods_agree(2.0, 2.15), (
        "0.15 ns is 7.0 % of a 2 ns period and must not be tolerated")
    assert CC.periods_agree(200.0, 200.15), (
        "the same 0.15 ns is 0.07 % of a 200 ns period and is the same clock")


def test_periods_that_are_exactly_equal_always_agree():
    """The degenerate end of the tolerance, including at zero-ish periods
    where the relative term collapses."""
    assert CC.periods_agree(6.4, 6.4)
    assert CC.periods_agree(0.0, 0.0)
    assert CC.distinct_periods([6.4, 6.4, 6.4]) == [6.4]
    assert CC.distinct_periods([]) == []


# ===========================================================================
# 3. ownership — which record's name was read, and which was stapled on
# ===========================================================================
def test_a_record_that_read_its_own_name_owns_it():
    assert CC.entry_owns_name(_owner("refclk_a", 6.4))
    assert CC.entry_owns_name({"name": "div_ck", "derived_from": "refclk_a"}), (
        "a genuinely derived clock still owns its own name; only a "
        "self-referential derived_from marks a borrowed one")


def test_a_self_referential_derived_from_marks_a_borrowed_name():
    assert not CC.entry_owns_name({"name": "refclk_a",
                                   "derived_from": "refclk_a"}), (
        "derived_from equal to the record's own name carries no derivation "
        "information — it is the canonical-port lookup filling both fields "
        "from one string")


def test_the_harvested_frequency_role_marks_a_borrowed_name():
    assert not CC.entry_owns_name(
        {"name": "refclk_a", "role": "extracted_from_doc_freq_mention"})
    assert not CC.entry_owns_name(
        {"name": "refclk_a", "role": "EXTRACTED_FROM_DOC_FREQ_MENTION"}), (
        "the role marker must be recognised regardless of case")
    assert not CC.entry_owns_name("not a record")


def test_a_generated_clock_is_recognised_as_derived():
    for entry in ({"name": "div_ck", "domain_kind": "derived"},
                  {"name": "div_ck", "domain_kind": "generated_from_refclk_a"},
                  {"name": "div_ck", "role": "generated_clock"},
                  {"name": "div_ck", "role": "derived"},
                  {"name": "div_ck", "derived_from": "refclk_a"}):
        assert CC.entry_is_derived(entry), f"{entry} was not read as derived"


def test_a_borrowed_record_is_not_mistaken_for_a_derived_clock():
    """The load-bearing disambiguation. Both shapes carry ``derived_from``;
    if the borrowed one were read as derived it would be exempt from the
    contract entirely and the original defect would ship untouched."""
    assert not CC.entry_is_derived(_borrowed("refclk_a", 133.0))
    assert not CC.entry_is_derived(_owner("refclk_a", 6.4))
    assert not CC.entry_is_derived("not a record")


def test_a_derived_clock_is_exempt_from_the_one_period_contract():
    """A generated clock legitimately runs at its own period under
    create_generated_clock, so sharing a parent is not a contradiction."""
    doc = {"clock_domains": [
        _owner("refclk_a", 6.4),
        {"name": "refclk_a", "domain_kind": "derived",
         "derived_from": "srcclk", "period_ns": 51.2},
    ]}

    assert CC.enforce(doc) == [], (
        "a derived clock was measured against its parent's period")
    assert len(doc["clock_domains"]) == 2, "a derived clock was folded away"


# ===========================================================================
# 4. entry_period_ns — what a record actually pins
# ===========================================================================
def test_period_precedence_is_period_then_mhz_then_hz():
    assert CC.entry_period_ns({"period_ns": 6.4, "freq_mhz": 133.0,
                               "freq_hz": 250_000_000.0}) == 6.4
    assert CC.entry_period_ns({"freq_mhz": 156.25,
                               "freq_hz": 250_000_000.0}) == 6.4
    assert CC.entry_period_ns({"freq_hz": 250_000_000.0}) == 4.0


def test_a_record_that_pins_no_period_is_not_given_one():
    """A range, a nonsense value or a bare name must not be turned into a
    period — a synthesised number would manufacture conflicts."""
    for entry in ({"low_mhz": 100.0, "high_mhz": 200.0},
                  {"freq_low_mhz": 100.0, "freq_high_mhz": 200.0},
                  {"period_ns": 0}, {"period_ns": -6.4},
                  {"freq_mhz": True}, {"freq_mhz": "156.25"},
                  {"name": "refclk_a"}, {}, "not a record"):
        assert CC.entry_period_ns(entry) is None, (
            f"{entry} was read as pinning a period")


# ===========================================================================
# 5. owning_entry_with_period — the query an extractor makes BEFORE emitting
# ===========================================================================
def test_owning_entry_with_period_finds_the_record_that_owns_the_name():
    """This is what stops the second record being written at all."""
    owner = _owner("refclk_a", 6.4)
    entries = [_borrowed("refclk_a", 133.0),
               _owner("refclk_b", 11.2),
               {"name": "refclk_a", "role": "primary"},      # pins no period
               owner]

    assert CC.owning_entry_with_period(entries, "refclk_a") is owner, (
        "the query returned something other than the record that owns the "
        "name and pins a period, so an extractor would fold onto the wrong "
        "record")


def test_owning_entry_with_period_answers_none_when_nothing_owns_the_name():
    """No owner means the caller must NOT fold — there is nothing to fold
    onto, and inventing an owner is exactly the silent pick to avoid."""
    assert CC.owning_entry_with_period([_borrowed("refclk_a", 133.0)],
                                       "refclk_a") is None
    assert CC.owning_entry_with_period(
        [{"name": "div_ck", "domain_kind": "derived", "period_ns": 51.2}],
        "div_ck") is None, "a derived clock was offered as the name's owner"
    assert CC.owning_entry_with_period([_owner("refclk_b", 11.2)],
                                       "refclk_a") is None
    assert CC.owning_entry_with_period([{"name": "refclk_a"}],
                                       "refclk_a") is None
    assert CC.owning_entry_with_period("not a list", "refclk_a") is None
    assert CC.owning_entry_with_period([_owner("refclk_a", 6.4)], None) is None


# ===========================================================================
# 6. record_alternate_mention — the number survives, the mis-assignment does not
# ===========================================================================
def test_an_alternate_mention_preserves_the_observation():
    owner = _owner("refclk_a", 6.4)
    CC.record_alternate_mention(owner, {
        "name": "refclk_a", "derived_from": "refclk_a", "freq_mhz": 133.0,
        "role": "extracted_from_doc_freq_mention", "source": "docs/spec.md",
        "evidence": {"file": "docs/spec.md", "line": 42}})

    assert len(_mentions(owner)) == 1
    rec = _mentions(owner)[0]
    assert rec["freq_mhz"] == 133.0
    assert rec["source"] == "docs/spec.md"
    assert rec["evidence"] == {"file": "docs/spec.md", "line": 42}, (
        "the evidence for the observation was dropped, so a reviewer cannot "
        "go back to the line it came from")
    assert "name" not in rec and "derived_from" not in rec, (
        "the borrowed NAME was carried onto the owner — that name assignment "
        "is the mistake being undone, and it must not be preserved")
    assert CC.entry_period_ns(owner) == 6.4, (
        "recording an observation changed the owner's own period")


def test_a_repeated_observation_collapses():
    owner = _owner("refclk_a", 6.4)
    mention = {"freq_mhz": 133.0, "role": "extracted_from_doc_freq_mention"}
    CC.record_alternate_mention(owner, mention)
    CC.record_alternate_mention(owner, dict(mention))

    assert len(_mentions(owner)) == 1, (
        "the same observation recorded twice accumulated; a document rewritten "
        "repeatedly would grow this list without bound")

    CC.record_alternate_mention(owner, {"freq_mhz": 156.25})
    assert len(_mentions(owner)) == 2, "a genuinely new observation was lost"


def test_an_observation_with_nothing_worth_keeping_is_not_recorded():
    owner = _owner("refclk_a", 6.4)
    CC.record_alternate_mention(owner, {"unrelated_key": "noise"})
    CC.record_alternate_mention(owner, {})
    CC.record_alternate_mention(owner, "not a record")

    assert CC.MENTIONS_KEY not in owner, (
        "an empty mention bucket was stamped on a record that has no "
        "alternate observation")


# ===========================================================================
# 7. the fold across containers — clocks[] and clock_domains[] are one namespace
# ===========================================================================
def test_a_borrowed_record_folds_onto_an_owner_in_the_other_container():
    """A name at one period in ``clocks`` and another in ``clock_domains`` is
    contradictory wherever it sits, so the fold must cross the two lists."""
    owner = _owner("refclk_a", 6.4)
    doc = {"clocks": [_borrowed("refclk_a", 133.0)],
           "clock_domains": [owner]}

    assert CC.enforce(doc) == []
    assert doc["clocks"] == [], (
        "the borrowed record survived in the other container — the two lists "
        "are one namespace and a consumer reading clocks[] still sees two "
        "periods for one clock")
    assert any(m.get("freq_mhz") == 133.0 for m in _mentions(owner)), (
        "the cross-container fold dropped the observation instead of moving "
        "it onto the owner")


def test_only_the_contradicting_record_is_folded():
    """Reconciliation is surgical: an unrelated clock, and a record that
    agrees with the owner, are both left exactly where they are."""
    owner = _owner("refclk_a", 6.4)
    other = _owner("refclk_b", 11.2)
    agreeing = {"name": "refclk_a", "derived_from": "refclk_a",
                "role": "extracted_from_doc_freq_mention", "freq_mhz": 156.25}
    doc = {"clock_domains": [owner, agreeing, _borrowed("refclk_a", 133.0),
                             other]}

    assert CC.enforce(doc) == []
    assert doc["clock_domains"] == [owner, agreeing, other], (
        "the fold removed a record that did not contradict the owner")
