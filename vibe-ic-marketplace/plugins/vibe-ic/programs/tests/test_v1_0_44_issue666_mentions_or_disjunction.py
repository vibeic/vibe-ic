"""tests/test_v1_0_44_issue666_mentions_or_disjunction.py — v1.0.44

Covers GitHub issue #666 (ORGANIC, MEDIUM, chip-AGNOSTIC).

ROOT CAUSE
    `_evaluate_match_rule`'s "L<n> mentions '...'" handler was anchored to a
    SINGLE quoted value + end-of-string. The multi-alternative form
    "mentions 'X' or 'Y' or 'Z'" (alternatives joined by lowercase `or`
    inside one clause) therefore did not match the handler. The top-level
    AND/OR splitter only splits on UPPERCASE AND/OR, so the lowercase-or
    clause was not split either. The pattern fell through to the generic
    free-text fallback, which requires ALL quoted phrases to be present
    (`all(q in full_text ...)` — AND semantics) instead of ANY. A record
    mentioning only ONE of several synonyms was silently dropped, even
    though the sibling "contains 'X' or 'Y'" handler ORs alternatives
    correctly. (Filed by the field agent: round-4 v1.0.42 6-IC re-run.)

FIX
    Give "mentions" the same multi-alternative OR handling that "contains"
    already has: parse ALL quoted values (re.findall) and return matched=
    True with the alias confidence (0.7) if ANY value is present in the
    full text. The multi-alternative "X or Y or Z" form is a DISJUNCTION.

ACCEPTANCE
    A `mentions 'a' or 'b' or 'c'` query returns records matching ANY of
    a/b/c (not only records matching all).

NO-LEAK
    A single-term `mentions` query and an explicit (uppercase) AND query
    are unchanged.

CHIP-AGNOSTIC
    Pure query-grammar logic — no chip/IP literal is used as a detection
    key. The fixtures below use a deliberately neutral, generic full_text.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))

import ip_catalog_query as cat  # noqa: E402


# A deliberately generic, chip-agnostic document. Only "alpha" (and the
# unrelated word "delta") are present; "beta" and "gamma" are absent. This
# lets a single OR-list assert disjunction without leaning on any chip
# vocabulary.
_FACTS = {"_full_text": "The document mentions alpha and also delta downstream."}


# ---------------------------------------------------------------------------
# ACCEPTANCE — multi-alternative "mentions 'a' or 'b' or 'c'" is a DISJUNCTION
# ---------------------------------------------------------------------------
def test_mentions_or_matches_when_only_first_alternative_present():
    """The PRIMARY bug: only the FIRST synonym is present, yet the rule
    must fire (ANY semantics), not AND-fail."""
    matched, conf = cat._evaluate_match_rule(
        "L2 mentions 'alpha' or 'beta' or 'gamma'", _FACTS)
    assert matched is True
    assert conf == 0.7


def test_mentions_or_matches_when_only_middle_alternative_present():
    matched, conf = cat._evaluate_match_rule(
        "L2 mentions 'beta' or 'alpha' or 'gamma'", _FACTS)
    assert matched is True
    assert conf == 0.7


def test_mentions_or_matches_when_only_last_alternative_present():
    matched, conf = cat._evaluate_match_rule(
        "L2 mentions 'beta' or 'gamma' or 'alpha'", _FACTS)
    assert matched is True
    assert conf == 0.7


def test_mentions_or_no_false_positive_when_no_alternative_present():
    """ANY semantics must still mean ANY — a list where NONE of the
    synonyms appear must NOT fire."""
    matched, conf = cat._evaluate_match_rule(
        "L2 mentions 'beta' or 'gamma' or 'epsilon'", _FACTS)
    assert matched is False
    assert conf == 0.0


def test_mentions_or_two_alternative_form():
    """The 2-alternative shape is the minimal disjunction."""
    matched, _ = cat._evaluate_match_rule(
        "L2 mentions 'alpha' or 'beta'", _FACTS)
    assert matched is True
    matched, _ = cat._evaluate_match_rule(
        "L2 mentions 'beta' or 'epsilon'", _FACTS)
    assert matched is False


# ---------------------------------------------------------------------------
# NO-LEAK 1 — single-term `mentions` unchanged
# ---------------------------------------------------------------------------
def test_single_term_mentions_present_unchanged():
    matched, conf = cat._evaluate_match_rule("L2 mentions 'alpha'", _FACTS)
    assert matched is True
    assert conf == 0.7


def test_single_term_mentions_absent_unchanged():
    matched, conf = cat._evaluate_match_rule("L2 mentions 'beta'", _FACTS)
    assert matched is False
    assert conf == 0.0


# ---------------------------------------------------------------------------
# NO-LEAK 2 — explicit (uppercase) AND keeps conjunction semantics
# ---------------------------------------------------------------------------
def test_explicit_uppercase_and_requires_all_terms():
    """An explicit AND across two `mentions` terms must still require BOTH
    terms (conjunction); the OR-list fix must not turn AND into OR."""
    both_present = cat._evaluate_match_rule(
        "L2 mentions 'alpha' AND L2 mentions 'delta'", _FACTS)
    assert both_present[0] is True

    one_absent = cat._evaluate_match_rule(
        "L2 mentions 'alpha' AND L2 mentions 'beta'", _FACTS)
    assert one_absent[0] is False
    assert one_absent[1] == 0.0


def test_explicit_uppercase_or_across_terms_still_disjunctive():
    """A top-level uppercase OR across full terms remains a disjunction
    (this path is handled by the splitter, not the mentions handler)."""
    one_present = cat._evaluate_match_rule(
        "L2 mentions 'beta' OR L2 mentions 'alpha'", _FACTS)
    assert one_present[0] is True


# ---------------------------------------------------------------------------
# NO-LEAK 3 — sibling "contains" OR-grammar is unchanged (parity anchor)
# ---------------------------------------------------------------------------
def test_contains_or_grammar_parity_preserved():
    """The `contains` handler already OR'd alternatives; the `mentions`
    fix must not change `contains` behaviour. (Confidence differs by
    handler: contains full-text fallback is 0.3, mentions alias is 0.7 —
    we assert only the matched bit here to pin the OR semantics.)"""
    matched, _ = cat._evaluate_match_rule(
        "L8.submodule contains 'alpha' or 'nonexistent_xyz'", _FACTS)
    assert matched is True
    matched, _ = cat._evaluate_match_rule(
        "L8.submodule contains 'beta' or 'nonexistent_xyz'", _FACTS)
    assert matched is False


# ---------------------------------------------------------------------------
# CHIP-AGNOSTIC structural anchor — the handler must parse N quoted values
# generically (re.findall), never branch on a specific synonym literal.
# ---------------------------------------------------------------------------
def test_mentions_or_handles_arbitrary_alternative_count():
    """Five generic alternatives, only the fourth present — proves the
    parse is N-ary and value-agnostic."""
    facts = {"_full_text": "only token_d is here"}
    matched, conf = cat._evaluate_match_rule(
        "L2 mentions 'token_a' or 'token_b' or 'token_c' or "
        "'token_d' or 'token_e'", facts)
    assert matched is True
    assert conf == 0.7


def test_mentions_or_phrase_with_internal_spaces_and_symbols():
    """Alternatives can be multi-word phrases with symbols (e.g. the real
    'RF + I-mem + D-mem' synonym); the present one must fire."""
    facts = {"_full_text": "uses a unified memory map across the soc"}
    matched, conf = cat._evaluate_match_rule(
        "L2 mentions 'shared SRAM' or 'unified memory' or "
        "'RF + I-mem + D-mem'", facts)
    assert matched is True
    assert conf == 0.7
