"""tests/test_v1_0_51_issue681_mentions_optional_negation_layer_scope.py

Covers GitHub issue #681 (ORGANIC, LOW/P3, chip-AGNOSTIC).

ROOT CAUSE
    `_evaluate_match_rule`'s "L<n> mentions 'X'" handler (and its #666
    multi-alternative OR form) did a plain whole-document
    `_full_text.lower()` substring search. Two defects followed:
      (a) it IGNORED the declared layer scope — the "L2"/"L8" prefix was
          parsed but never used to scope the search, so an L8 term could
          be satisfied by text in any layer (e.g. an L18 metadata blob);
      (b) it had NO optional-qualifier / explicit-negation / NOT-constrained
          suppression — the sibling cpu_extensions/cpu_isa `contains`
          branch carried `_extension_excluded` / `_extension_optional_only`
          guards, but the free-text `mentions` rules carried none.
    Result: a bus/interconnect manifest's
        L2 mentions 'Wishbone' AND L8 mentions 'interconnect'/'crossbar'/...
    rule fired even when the only 'Wishbone' occurrences were in an
    OPTIONAL ('Plugin 可自行加 ... wrapper，但不強制') or NOT-constrained
    ('對 Wishbone 級 protocol' / 'must NOT use Wishbone') section, and
    'interconnect' was satisfied only by an EMPTY metadata key NAME
    (`interconnect_rules: []`) sitting in an unrelated layer's doc — a hard
    interconnect-IP catalog hit on a from-scratch IP class.

    Minimal demo of the bug (pre-fix):
        mentions 'Wishbone' returned (True, 0.7) on 'must NOT use Wishbone',
        while contains cpu_extensions 'F' correctly returned (False, 0.0)
        on 'rv32i no F'.

FIX (Bucket A, chip-AGNOSTIC)
    1. GENERIC phrase-grammar helper `_term_optional_or_negated` (bilingual
       EN + zh-Hant, no chip literal) suppresses a 'mentions' hit when the
       term occurs ONLY inside an optional / explicit-negation window; a
       single genuine unqualified occurrence anywhere defeats suppression.
    2. SCOPE the 'mentions' search to the layer named in the rule via
       `_scoped_section_text(facts, field_ref)` (per-layer `_layer_text`),
       falling back to whole-doc only when no per-layer text is captured.
    3. `_strip_empty_metadata_keys` treats a JSON key whose value is empty
       (`"interconnect_rules": []` / `""` / `{}` / `null`) as NON-evidence.

ACCEPTANCE (POSITIVE — the real round-5 bug shape)
    'Wishbone' only in an optional/NOT-constrained section + 'interconnect'
    only as an empty metadata key NAME → the wb_intercon mentions-rule does
    NOT fire (no hard catalog hit).

NO-LEAK (§4.05 NEGATIVE)
    A genuine unqualified 'L2 mentions Wishbone' in a real constrained spec
    section STILL fires; a real multi-master interconnect manifest STILL
    matches; the #666 OR form still works for genuine mentions; the
    contains/ext_field branch is unchanged.

CHIP-AGNOSTIC
    Pure bilingual phrase / JSON-shape grammar — no chip / IP / vendor / SKU
    literal is used as a detection key.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))

import ip_catalog_query as cat  # noqa: E402


# The real wb_intercon-class match rule (AND of an L2 free-text term and an
# L8 multi-alternative OR term) — verbatim grammar shape from the manifest.
_WB_INTERCON_RULE = (
    "L2 mentions 'Wishbone' AND "
    "L8 mentions 'interconnect' or 'crossbar' or 'multi-master'"
)

# Real round-5 repro strings, embedded verbatim.
_OPTIONAL_ZH = "Plugin 可自行加 Wishbone wrapper，但不強制。對 Wishbone 級 protocol。"
_NEGATION_EN = "The design must NOT use Wishbone for any bus."
_EMPTY_META = json.dumps({"interconnect_rules": []}, ensure_ascii=False)


def _facts(layers: dict) -> dict:
    """Build a facts dict with both `_full_text` and per-layer `_layer_text`
    from a {bare_layer_id: doc_dict} mapping, mirroring load_project_facts."""
    layer_text = {}
    parts = []
    for lid, doc in layers.items():
        blob = doc if isinstance(doc, str) else json.dumps(doc, ensure_ascii=False)
        layer_text[lid] = blob
        parts.append(blob)
    return {"_full_text": "\n".join(parts), "_layer_text": layer_text}


# ---------------------------------------------------------------------------
# POSITIVE — the real round-5 bug shape must NOT produce a hard catalog hit
# ---------------------------------------------------------------------------
def test_round5_bug_shape_does_not_fire():
    """'Wishbone' only optional/NOT-constrained + 'interconnect' only an
    empty metadata key name → the AND rule must NOT fire."""
    facts = _facts({
        "L2": {"desc": _OPTIONAL_ZH},
        "L8": {"arch": "simple single-master register file, no shared fabric"},
        "L18": {"interconnect_rules": []},
    })
    matched, conf = cat._evaluate_match_rule(_WB_INTERCON_RULE, facts)
    assert matched is False
    assert conf == 0.0


def test_optional_zh_window_suppresses_single_term():
    matched, conf = cat._evaluate_match_rule(
        "L2 mentions 'Wishbone'",
        _facts({"L2": {"desc": _OPTIONAL_ZH}}))
    assert matched is False
    assert conf == 0.0


def test_negation_en_window_suppresses_single_term():
    matched, conf = cat._evaluate_match_rule(
        "L2 mentions 'Wishbone'",
        _facts({"L2": {"note": _NEGATION_EN}}))
    assert matched is False
    assert conf == 0.0


def test_empty_metadata_key_name_is_not_evidence():
    """A key NAME whose value is empty must not satisfy a mention."""
    matched, conf = cat._evaluate_match_rule(
        "L8 mentions 'interconnect'",
        _facts({"L8": {"interconnect_rules": []}}))
    assert matched is False
    assert conf == 0.0


def test_layer_scope_term_in_other_layer_does_not_satisfy():
    """An L8 term satisfied only by L2 text must NOT fire (scope honored)."""
    facts = _facts({
        "L2": {"note": "an interconnect crossbar appears only here in L2"},
        "L8": {"note": "nothing relevant to the fabric"},
    })
    matched, conf = cat._evaluate_match_rule("L8 mentions 'interconnect'", facts)
    assert matched is False
    assert conf == 0.0


def test_minimal_demo_from_issue_negation():
    """The exact minimal demo: mentions 'Wishbone' on 'must NOT use
    Wishbone' must be (False, 0.0), matching the sibling contains/ext
    branch's correct (False, 0.0) on 'rv32i no F'."""
    mentions = cat._evaluate_match_rule(
        "L2 mentions 'Wishbone'", {"_full_text": "must NOT use Wishbone"})
    assert mentions == (False, 0.0)
    # parity anchor: the ext_field contains branch was already correct
    contains = cat._evaluate_match_rule(
        "L2.cpu_isa contains 'F'", {"L2_FRS.cpu_isa": "rv32i no F"})
    assert contains == (False, 0.0)


# ---------------------------------------------------------------------------
# §4.05 NO-LEAK — genuine mentions STILL fire; sibling branches unchanged
# ---------------------------------------------------------------------------
def test_genuine_unqualified_mention_still_fires():
    """A real constrained spec section (unqualified) STILL fires."""
    matched, conf = cat._evaluate_match_rule(
        "L2 mentions 'Wishbone'",
        _facts({"L2": {"bus": "The core implements a Wishbone B4 classic bus."}}))
    assert matched is True
    assert conf == 0.7


def test_genuine_multi_master_interconnect_manifest_still_matches():
    """A real multi-master crossbar interconnect manifest STILL matches the
    full AND rule."""
    facts = _facts({
        "L2": {"bus": "Wishbone B4 classic interface on all masters"},
        "L8": {"arch": "a multi-master crossbar interconnect with arbiter"},
    })
    matched, conf = cat._evaluate_match_rule(_WB_INTERCON_RULE, facts)
    assert matched is True
    assert conf == 0.7


def test_666_or_form_still_works_for_genuine_mentions():
    """The #666 multi-alternative OR disjunction is preserved for genuine
    mentions (only the LAST alternative present, no qualifiers)."""
    facts = _facts({"L8": {"arch": "uses a multi-master fabric"}})
    matched, conf = cat._evaluate_match_rule(
        "L8 mentions 'interconnect' or 'crossbar' or 'multi-master'", facts)
    assert matched is True
    assert conf == 0.7


def test_666_or_form_suppressed_when_all_alts_optional_or_negated():
    """If every present OR-alternative sits in an optional/negation window,
    the disjunction must NOT fire."""
    facts = _facts({"L8": {"note": "may add an interconnect later; not required"}})
    matched, conf = cat._evaluate_match_rule(
        "L8 mentions 'interconnect' or 'crossbar' or 'multi-master'", facts)
    assert matched is False
    assert conf == 0.0


def test_fulltext_fallback_preserved_when_no_layer_text():
    """Fixtures with only `_full_text` (no `_layer_text`) keep whole-doc
    fallback — this is what the #666 tests rely on."""
    facts = {"_full_text": "The document mentions alpha and also delta."}
    assert cat._evaluate_match_rule("L2 mentions 'alpha'", facts) == (True, 0.7)
    assert cat._evaluate_match_rule("L2 mentions 'beta'", facts) == (False, 0.0)
    # OR disjunction over whole-doc fallback still ANY-matches.
    matched, conf = cat._evaluate_match_rule(
        "L2 mentions 'beta' or 'gamma' or 'alpha'", facts)
    assert matched is True
    assert conf == 0.7


def test_contains_ext_field_branch_unchanged():
    """The cpu_extensions/cpu_isa contains branch is untouched: a genuine
    mandatory ext fires, an optional/negated one does not."""
    # mandatory in base ISA → fires high-confidence
    matched, conf = cat._evaluate_match_rule(
        "L2.cpu_isa contains 'm'", {"L2_FRS.cpu_isa": "rv32im"})
    assert matched is True
    assert conf == 0.9
    # explicit negation → suppressed
    assert cat._evaluate_match_rule(
        "L2.cpu_isa contains 'f'",
        {"L2_FRS.cpu_isa": "rv32i", "_full_text": "no FPU, integer-only"}
    ) == (False, 0.0)


# ---------------------------------------------------------------------------
# GENERIC helper unit anchors — pure phrase/JSON grammar, value-agnostic
# ---------------------------------------------------------------------------
def test_term_optional_or_negated_helper_generic():
    # optional-only → suppressed
    assert cat._term_optional_or_negated("foo", "you may add foo here") is True
    assert cat._term_optional_or_negated("foo", "foo is optional") is True
    assert cat._term_optional_or_negated("foo", "可自行加 foo，但不強制") is True
    # negation-only → suppressed
    assert cat._term_optional_or_negated("foo", "must not use foo") is True
    assert cat._term_optional_or_negated("foo", "without foo support") is True
    assert cat._term_optional_or_negated("foo", "no foo here") is True
    # a single genuine unqualified occurrence defeats suppression
    assert cat._term_optional_or_negated(
        "foo", "foo is core. you may add foo later too.") is False
    # term absent → not suppressed (handler short-circuits on presence)
    assert cat._term_optional_or_negated("foo", "nothing relevant") is False


def test_strip_empty_metadata_keys_generic():
    src = json.dumps(
        {"a_list": [], "a_str": "", "a_obj": {}, "a_null": None,
         "real": "interconnect value"}, ensure_ascii=False)
    stripped = cat._strip_empty_metadata_keys(src)
    # empty-value key NAMES are gone
    assert "a_list" not in stripped
    assert "a_str" not in stripped
    assert "a_obj" not in stripped
    assert "a_null" not in stripped
    # a key with a real value survives
    assert "interconnect value" in stripped
    # non-JSON text untouched
    assert cat._strip_empty_metadata_keys("plain prose") == "plain prose"


# ---------------------------------------------------------------------------
# §4.05 NO-LEAK (v1.0.51-r2 — adversarial-review regression) — a MANDATORY
# term co-occurring with an `optional`/negation qualifier on a DIFFERENT noun
# in the SAME comma-less run-on clause must STILL FIRE. The original
# whole-clause governor branch over-suppressed these (dropped real catalog
# hits — a regression vs parent af82190f). Each case is verbatim from the
# reviewer's reproduced break list; all EXPECT (True, 0.7).
# ---------------------------------------------------------------------------
# (text, term) — a genuine MANDATORY mention of `term` despite an optional /
# negated SIBLING noun sharing the clause.
_REVIEWER_MANDATORY_CASES = [
    ("The Wishbone interconnect is mandatory but an optional AXI bridge "
     "can be added", "Wishbone"),
    ("A Wishbone crossbar is the core fabric while an AXI bridge is not "
     "required", "Wishbone"),
    ("Every master speaks Wishbone and the L2 cache is optional", "Wishbone"),
    ("The crossbar interconnect is the required fabric with an optional "
     "debug port", "interconnect"),
    ("The mandatory Wishbone bus is required and an optional debug port "
     "may exist", "Wishbone"),
    ("Wishbone B4 is the system bus and parity is not required on it",
     "Wishbone"),
    # the trickiest: a bare adjacent "optionally" modifies the VERB, not the
    # term's existence — "the interconnect optionally supports bursts" means
    # the interconnect (mandatory) does bursts optionally.
    ("The Wishbone interconnect optionally supports burst transfers",
     "interconnect"),
]


@pytest.mark.parametrize("text,term", _REVIEWER_MANDATORY_CASES)
def test_mandatory_term_with_optional_sibling_still_fires(text, term):
    """A mandatory term + optional/negated SIBLING in one comma-less clause
    must FIRE — term-anchored governor must not suppress the genuine term."""
    matched, conf = cat._evaluate_match_rule(
        f"L2 mentions '{term}'", {"_full_text": text})
    assert matched is True
    assert conf == 0.7


@pytest.mark.parametrize("text,term", _REVIEWER_MANDATORY_CASES)
def test_reviewer_cases_helper_returns_not_suppressed(text, term):
    """Direct helper assertion: the genuine term is NOT optional/negated."""
    assert cat._term_optional_or_negated(term, text) is False


def test_comma_separated_control_still_fires():
    """The reviewer's control: a comma DOES bound the clause, so the
    mandatory term before it fires even though an optional sibling follows."""
    text = "Wishbone interconnect is required, optional AXI bridge may be added"
    matched, conf = cat._evaluate_match_rule(
        "L2 mentions 'Wishbone'", {"_full_text": text})
    assert matched is True
    assert conf == 0.7


def test_e2e_genuine_mandatory_crossbar_with_optional_sibling_matches():
    """End-to-end: a genuine multi-master crossbar manifest whose docs
    contain an 'optional <sibling>' run-on phrase must STILL match the full
    wb_intercon AND-rule (the lost interconnect-IP catalog hit)."""
    facts = _facts({
        "L2": {"bus": "The Wishbone interconnect is mandatory but an "
                      "optional AXI bridge can be added"},
        "L8": {"arch": "A multi-master crossbar interconnect arbitrates all "
                       "masters with an optional debug port"},
    })
    matched, conf = cat._evaluate_match_rule(_WB_INTERCON_RULE, facts)
    assert matched is True
    assert conf == 0.7


def test_term_anchored_governor_does_not_over_suppress_verb_adverb():
    """Pin the verb-adverb distinction directly: '<term> optionally supports
    X' is NOT a governor on the term (term is genuine); '<term> is optional'
    IS."""
    # verb-adverb → genuine (not suppressed)
    assert cat._term_optional_or_negated(
        "interconnect",
        "the interconnect optionally supports burst transfers") is False
    # copula-bound existence → suppressed
    assert cat._term_optional_or_negated(
        "interconnect", "the interconnect is optional") is True
    assert cat._term_optional_or_negated(
        "interconnect", "the interconnect is not required") is True
    # preceding "optional <term>" → suppressed
    assert cat._term_optional_or_negated(
        "debug port", "an optional debug port may exist") is True
