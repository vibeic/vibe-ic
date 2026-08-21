#!/usr/bin/env python3
"""An L5 analog block's stored evidence must contain the keyword it evidences.

THE DEFECT (chip-AGNOSTIC, reproduced here on synthetic prose only).
`gen_l5_adi_spec` stores, for each detected block, the paragraph the keyword
was found in — computed as the span between consecutive blank lines and then
cut to a fixed width from that span's START.

A markdown list carries no blank line between its items, so an entire list is
ONE such span. For a keyword in item 2 the reader is therefore shown item 1,
and when the list is long enough the stored evidence is truncated before it
ever reaches the keyword. Measured shape: a block whose `evidence` field names
a keyword, whose `evidence_paragraph` is about an unrelated subject, and whose
`evidence_paragraph_truncated` flag is the only hint that anything was cut.

Worse, two blocks whose keywords sit in DIFFERENT items of the same list both
receive the SAME first item as their evidence — so the field cannot even
distinguish them.

THE RULE: the span that evidences a keyword is the list ITEM the keyword sits
in, when there is one. Same reasoning as the table-CELL scope already used by
`_v0_1_62_analog_kw_negated` — a row is not a sentence, and an item is not the
list.

DIRECTION OF RISK, and why the reverse controls below are not optional.
Narrowing a span is the direction that can silently DESTROY evidence: narrow it
too far and every block's evidence becomes a fragment, the emitter still emits,
and nothing fails. So this file pins BOTH sides — the narrowing happens for
lists, and does NOT happen for ordinary prose, for a keyword in a list's
lead-in, or to the set of blocks detected. A filter tightened until the count
reached zero would pass the two negative controls and be caught by the four
reverse controls.

Every behavioural assertion drives the SHIPPED entry point `gen_l5_adi_spec`
and reads the emitted document, so each one REPRODUCES the defect on an unfixed
tree rather than skipping over it.

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
    return {b.get("type"): b for b in (doc.get("analog_blocks") or [])}


# A list whose FIRST item is about an unrelated subject and carries its own
# numbers, and whose SECOND item is where the block keyword appears.
_DOC_LIST = """# Notes

Findings from the enablement review:

1. **Reference trim.** The measured output voltage is 1.20 V and the
   temperature coefficient is 25 ppm/C over the full operating range, which
   is inside the budget allocated to this block in the earlier study.
2. **Regulator availability.** The LDO exists only as a schematic-level cell
   with no abstract view, so the digital flow cannot instantiate it.
3. **Extraction deck.** No parasitic-extraction deck ships with this kit.
"""


# ── negative controls: these FAIL on the unfixed tree ────────────────────

def test_stored_evidence_contains_the_keyword_it_evidences(tmp_path):
    b = _blocks(_emit(tmp_path, _DOC_LIST)).get("ldo")
    assert b is not None, "the ldo keyword in item 2 must still be detected"
    para = b.get("evidence_paragraph") or ""
    assert "ldo" in para.lower(), (
        "the stored evidence does not contain the keyword it claims to "
        "evidence; it shows a sibling list item instead:\n" + repr(para))


def test_two_blocks_in_different_items_do_not_share_one_evidence(tmp_path):
    """Distinct blocks must not both be evidenced by the same first item."""
    doc = """# Notes

Findings:

1. **Reference trim.** The bandgap output is 1.20 V and the temperature
   coefficient is 25 ppm/C over the full operating range.
2. **Regulator availability.** The LDO exists only as a schematic-level
   cell, so the digital flow cannot instantiate it.
"""
    got = _blocks(_emit(tmp_path, doc))
    ldo, bg = got.get("ldo"), got.get("bandgap")
    assert ldo is not None and bg is not None
    p_ldo = (ldo.get("evidence_paragraph") or "").lower()
    p_bg = (bg.get("evidence_paragraph") or "").lower()
    assert p_ldo != p_bg, (
        "two blocks whose keywords are in different list items received "
        "byte-identical evidence; the field cannot distinguish them")
    assert "ldo" in p_ldo, p_ldo
    assert "bandgap" in p_bg, p_bg


# ── reverse controls: these must hold in BOTH directions ─────────────────

def test_ordinary_prose_paragraph_is_not_narrowed(tmp_path):
    """No list, so the blank-line paragraph is still the whole span. Pins that
    the change is scoped to lists and did not narrow prose evidence."""
    doc = """# Notes

The LDO delivers a dropout voltage of 200 mV and a load regulation of
5 mV/mA across the operating range, measured at room temperature.
"""
    b = _blocks(_emit(tmp_path, doc)).get("ldo")
    assert b is not None
    para = b.get("evidence_paragraph") or ""
    assert "ldo" in para.lower(), para
    # the WHOLE paragraph survives, including the sentence tail
    assert "load regulation" in para.lower(), para


def test_keyword_in_the_lead_in_above_a_list_keeps_its_lead_in(tmp_path):
    """A keyword above a list is evidenced by the lead-in, not by item 1."""
    doc = """# Notes

The LDO is documented in the sections below.

1. **Reference trim.** Output is 1.20 V and the coefficient is 25 ppm/C.
2. **Extraction deck.** No parasitic-extraction deck ships with this kit.
"""
    b = _blocks(_emit(tmp_path, doc)).get("ldo")
    assert b is not None
    para = b.get("evidence_paragraph") or ""
    assert "ldo" in para.lower(), para
    assert "documented in the sections below" in para.lower(), para


def test_single_item_list_still_yields_that_item(tmp_path):
    doc = """# Notes

Finding:

1. **Regulator.** The LDO supplies the analog domain from the main rail
   and is enabled by the sequencer at start-up.
"""
    b = _blocks(_emit(tmp_path, doc)).get("ldo")
    assert b is not None
    para = b.get("evidence_paragraph") or ""
    assert "ldo" in para.lower(), para
    assert "sequencer" in para.lower(), para


def test_the_set_of_detected_blocks_is_unchanged(tmp_path):
    """The narrowing must change only WHICH TEXT evidences a block, never
    WHICH BLOCKS are detected. This is the control that a span narrowed until
    nothing matched would fail."""
    got = _blocks(_emit(tmp_path, _DOC_LIST))
    assert "ldo" in got, sorted(got)
    doc2 = """# Notes

Findings:

1. **Reference trim.** The bandgap output is 1.20 V.
2. **Regulator availability.** The LDO has no abstract view.
"""
    got2 = _blocks(_emit(tmp_path, doc2))
    assert {"ldo", "bandgap"} <= set(got2), sorted(got2)
