#!/usr/bin/env python3
"""An L5 analog block's stored evidence must CONTAIN the keyword it evidences.

THE DEFECT (chip-AGNOSTIC; reproduced here on synthetic prose only).
`gen_l5_adi_spec` stores, for every detected block, `evidence_paragraph` — the
blank-line paragraph the keyword was found in, cut to a fixed 240 characters
**from the paragraph START**. When the keyword sits further into the paragraph
than that, the stored evidence is a prefix about some other subject and never
contains the keyword it claims to evidence. Only the
`evidence_paragraph_truncated` flag hints that anything was dropped.

Measured on the real corpus before the fix: 10 of 27 detected blocks stored
evidence that did not contain their own keyword — every one of them by this
truncation, and none of them inside a markdown list.

THE RULE: the 240-character window is anchored on the KEYWORD, not on the span
start. The window stays at the span start whenever the keyword already fits
inside it, so evidence that was already correct is byte-for-byte unchanged.

WHY THE SPAN IS NOT NARROWED, and why the nested-list control below is the
load-bearing test in this file. An earlier attempt at this defect narrowed the
span to the markdown list ITEM containing the keyword. Narrowing is the
direction that silently DESTROYS evidence: a list item's numbers routinely live
in its own indented sub-items, so cutting the span at "the next line that looks
like a list item" excised the block's actual specification and turned a real
`spec` into `null` with `low_confidence=True` — an emitter that still emits,
and nothing fails. This file therefore pins that the span is UNCHANGED (spec,
count and the detected block set all survive) while the WINDOW moves.

THE THIRD DEFECT, found while fixing the first two: the window was deciding
SEMANTICS. `_v1_6_563_apply_subqualifier_guard` grouped blocks by
`evidence_paragraph` equality and located each block's keyword inside that
string — i.e. inside the 240-character display window. That made the guard
wrong in two OPPOSITE ways depending on where the window sat, and the last two
tests in this file reproduce both end-to-end:

  * with the window pinned at the span start, a keyword past 240 was not
    findable at all, so the guard fell through to its dict-iteration-order
    fallback and decremented the HEAD block instead of the parenthetical one;
  * with the window anchored on the keyword, two blocks in one span get
    DIFFERENT windows, the group never forms, and the guard silently does
    nothing.

Grouping and prose-position classification therefore read the whole span. 0
corpora trigger this today; it is closed because a display width must not be
what decides a count.

Every assertion drives the SHIPPED entry point `gen_l5_adi_spec` and reads the
emitted document. None of them touches a private helper by name, so each one
REPRODUCES a behaviour on an unfixed tree rather than dying on a new symbol.

All fixtures are SYNTHESIZED neutral prose — invented values and generic
electrical-engineering vocabulary. No design, PDK, vendor or part number
appears, and no sentence is copied from any input document.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

runner = pytest.importorskip("phase1_doc_one_shot_runner")


def _emit(tmp_path: Path, doc: str) -> dict:
    """Drive the shipped emitter and return the L5 document it wrote."""
    (tmp_path / "phase1" / "generated_docs").mkdir(parents=True, exist_ok=True)
    res = runner.gen_l5_adi_spec(tmp_path, {"L1_notes.md": doc})
    return json.loads(Path(res.path).read_text())


def _blocks(doc: dict) -> dict:
    """Map type -> block. Blocks are keyed by CONTENT, never by position."""
    return {b.get("type"): b for b in (doc.get("analog_blocks") or [])}


def _kw_literal(block: dict) -> str:
    """The keyword literal this block was detected on, as the emitter stored
    it in `evidence`: ``input/docs/<file> (<literal>)``."""
    ev = block.get("evidence") or ""
    assert "(" in ev and ev.endswith(")"), ev
    return ev[ev.rindex("(") + 1:-1]


def _assert_evidence_carries_its_keyword(block: dict) -> None:
    lit = _kw_literal(block)
    para = block.get("evidence_paragraph") or ""
    assert lit.lower() in para.lower(), (
        "block %r was detected on keyword %r but the evidence stored for it "
        "does not contain that keyword:\n%r"
        % (block.get("type"), lit, para))


# Neutral filler, ~60 chars, carrying no analog vocabulary of its own. Repeated
# to push the keyword past the 240-character window.
_FILLER = "The enablement review recorded the item below for tracking. "


# ── negative controls: FAIL on both the unfixed tree and the list-item
#    attempt, because neither anchors the window on the keyword ─────────

@pytest.mark.parametrize("repeats", [4, 6, 8])
def test_keyword_past_the_window_is_still_inside_its_evidence(
        tmp_path, repeats):
    """The keyword sits beyond character 240 of its own list item."""
    doc = ("# Notes\n\nFindings:\n\n"
           "1. **Supply review.** " + _FILLER * repeats +
           "The LDO drops 250 mV at full load.\n"
           "2. **Extraction.** The deck ships with the kit.\n")
    b = _blocks(_emit(tmp_path, doc)).get("ldo")
    assert b is not None, "the keyword must still be detected"
    _assert_evidence_carries_its_keyword(b)


@pytest.mark.parametrize("repeats", [4, 6, 8])
def test_keyword_past_the_window_in_plain_prose_is_inside_its_evidence(
        tmp_path, repeats):
    """Same defect with NO list anywhere — the majority shape on the real
    corpus, and the one a markdown-structure rule cannot reach."""
    doc = ("# Notes\n\n" + _FILLER * repeats +
           "The LDO drops 250 mV at full load.\n")
    b = _blocks(_emit(tmp_path, doc)).get("ldo")
    assert b is not None, "the keyword must still be detected"
    _assert_evidence_carries_its_keyword(b)


# ── the load-bearing reverse control: narrowing the span destroys a real
#    spec, so the span must be left alone ──────────────────────────────

def test_nested_sub_items_of_the_keywords_own_item_still_yield_its_spec(
        tmp_path):
    """A list item whose numbers live in its own INDENTED sub-items.

    This is the shape that a "cut the span at the next list-item marker" rule
    destroys: the sub-items each start with `- `, so the span is cut at the
    first of them and every number the block is specified by is excised. The
    emitter still emits a block, so the only visible symptom is `spec: null`
    plus `low_confidence: true` — a silent loss of a real specification.
    """
    doc = """# Notes

Findings:

1. **Regulator.** The LDO supplies the analog domain from the main rail.
   - Output voltage: 1.80 V
   - Dropout: 250 mV
   - Quiescent current: 12 uA
2. **Extraction.** The deck ships with the kit.
"""
    b = _blocks(_emit(tmp_path, doc)).get("ldo")
    assert b is not None
    assert b.get("spec") is not None, (
        "the sub-items that specify this block were excised from its span; "
        "a real specification silently became null")
    assert b.get("low_confidence") is False, b.get("low_confidence")
    para = b.get("evidence_paragraph") or ""
    # every sub-item is part of the item's own evidence
    for token in ("1.80 V", "250 mV", "12 uA"):
        assert token in para, (token, para)


# ── reverse controls: the window MOVES, nothing else changes ───────────

def test_short_paragraph_evidence_is_the_whole_paragraph(tmp_path):
    """A span that fits in the window is stored whole and untruncated — the
    pin that the anchoring did not start trimming evidence that was fine."""
    doc = """# Notes

The LDO delivers a dropout voltage of 200 mV and a load regulation of
5 mV/mA across the operating range, measured at room temperature.
"""
    b = _blocks(_emit(tmp_path, doc)).get("ldo")
    assert b is not None
    para = b.get("evidence_paragraph") or ""
    assert para == (
        "The LDO delivers a dropout voltage of 200 mV and a load regulation "
        "of\n5 mV/mA across the operating range, measured at room "
        "temperature."), repr(para)
    assert b.get("evidence_paragraph_truncated") is False


def test_a_lists_lead_in_sentence_survives_in_the_evidence(tmp_path):
    """The sentence that says what a list IS belongs to the evidence of a
    keyword inside that list, whenever it fits in the window. Narrowing the
    span to the item is what drops it.

    The lead-in is attached to the list with NO blank line between them, so it
    is part of the same blank-line span — the shape this actually occurs in.
    """
    doc = """# Notes

Power management moves onto the module in this generation:
- The LDO supplies the analog domain from the main rail.
- The deck ships with the kit.
"""
    b = _blocks(_emit(tmp_path, doc)).get("ldo")
    assert b is not None
    para = b.get("evidence_paragraph") or ""
    assert "power management moves onto the module" in para.lower(), para
    _assert_evidence_carries_its_keyword(b)


def test_every_block_in_a_shared_paragraph_carries_its_own_keyword(tmp_path):
    """Two blocks detected in one paragraph each store evidence containing
    THEIR OWN keyword.

    Their evidence may legitimately be byte-identical when the shared
    paragraph fits in the window: it then contains both keywords, and each
    block's `evidence` field names the literal it was detected on. Requiring
    the two to DIFFER is what motivated narrowing the span, and that is the
    requirement this file replaces — uniqueness is not the property that makes
    evidence auditable; containment is.
    """
    doc = """# Notes

Findings:

1. **Reference trim.** The bandgap output is 1.20 V and the temperature
   coefficient is 25 ppm/C over the full operating range.
2. **Regulator availability.** The LDO exists only as a schematic-level
   cell, so the digital flow cannot instantiate it.
"""
    got = _blocks(_emit(tmp_path, doc))
    assert {"ldo", "bandgap"} <= set(got), sorted(got)
    for cls in ("ldo", "bandgap"):
        _assert_evidence_carries_its_keyword(got[cls])


def test_the_set_of_detected_blocks_is_unchanged_by_the_anchoring(tmp_path):
    """The window must change only WHICH TEXT evidences a block, never WHICH
    BLOCKS are detected. This is the control a span narrowed until nothing
    matched would fail."""
    doc = ("# Notes\n\nFindings:\n\n"
           "1. **Supply review.** " + _FILLER * 8 +
           "The LDO drops 250 mV at full load.\n"
           "2. **Reference trim.** The bandgap output is 1.20 V.\n")
    got = _blocks(_emit(tmp_path, doc))
    assert {"ldo", "bandgap"} <= set(got), sorted(got)
    for cls in ("ldo", "bandgap"):
        _assert_evidence_carries_its_keyword(got[cls])


def test_truncation_flag_still_reports_the_span_not_the_window(tmp_path):
    """`evidence_paragraph_truncated` keeps its meaning: the stored text is
    not the whole span. Moving the window must not silently redefine it."""
    doc = ("# Notes\n\n" + _FILLER * 8 +
           "The LDO drops 250 mV at full load.\n")
    b = _blocks(_emit(tmp_path, doc)).get("ldo")
    assert b is not None
    assert b.get("evidence_paragraph_truncated") is True
    assert len(b.get("evidence_paragraph") or "") == 240


# ── the display window must not decide a COUNT ─────────────────────────

#: One sentence stating a head multiplicity with a parenthetical naming a
#: SECOND block class as a sub-set of it. `six copies of ...` gives both blocks
#: the same head count; `(one of them is ...)` is the sub-qualifier that must
#: pull the parenthetical block — and only it — down to 1.
_HEAD = ("The array provides six copies of the converter core (one of them "
         "is powered by an LDO regulator at 1.8 V) in this revision. ")
#: Trailer carrying the SECOND class's keyword. Both blocks land in one
#: blank-line span; only the distance of this keyword from the span start
#: differs between the two tests below.
_TAIL = "The delta-sigma loop filter settles in 12 us at 1.2 V.\n"


def _counts(tmp_path, doc):
    got = _blocks(_emit(tmp_path, doc))
    assert {"ldo", "delta_sigma"} <= set(got), sorted(got)
    return {k: got[k].get("count") for k in ("ldo", "delta_sigma")}


def test_subqualifier_count_is_unaffected_by_where_the_window_sits(tmp_path):
    """The SAME sentence, with the second keyword pushed past character 240,
    must produce the SAME counts.

    This is the pin that the guard reads the span and not the window. On an
    unfixed tree it fails in one of two opposite ways:

      * window at the span start — the `delta-sigma` keyword is past 240 and
        so is invisible to the classifier; the guard falls through to its
        dict-iteration-order fallback and decrements `delta_sigma`, the HEAD
        subject, leaving the parenthetical `ldo` at 6. Exactly inverted.
      * window anchored on the keyword but the guard still grouping on it —
        the two blocks no longer share a string, the group never forms, and
        NEITHER count is corrected (both stay 6).
    """
    near = _counts(tmp_path / "near", "# Notes\n\n" + _HEAD + _TAIL)
    far = _counts(tmp_path / "far",
                  "# Notes\n\n" + _HEAD + _FILLER * 3 + _TAIL)
    assert near == far, (near, far)


def test_the_parenthetical_block_is_the_one_decremented(tmp_path):
    """…and the shared count lands on the right block: the parenthetical one
    goes to the sub-qualifier, the head keeps the head count. Asserted on the
    far shape, where the keyword sits past the window."""
    got = _counts(tmp_path, "# Notes\n\n" + _HEAD + _FILLER * 3 + _TAIL)
    assert got == {"ldo": 1, "delta_sigma": 6}, got
