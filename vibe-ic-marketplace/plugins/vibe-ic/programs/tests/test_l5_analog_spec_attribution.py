#!/usr/bin/env python3
"""An L5 analog spec value must be ATTRIBUTED to a named quantity, not merely
NEAR one.

THE DEFECT (chip-AGNOSTIC, reproduced here on synthetic prose only).
`_analog_spec_from_paragraph` assembled a block's spec by taking the first six
numeric+unit tokens anywhere in the paragraph that mentioned the block's
keyword, in document order, and joining them into a prose string. Nothing tied
a number to the QUANTITY it measures. Two consequences, both reproduced below:

  (1) TWO DIFFERENT BLOCKS whose keywords appear in the same paragraph receive
      BYTE-IDENTICAL spec strings — the same six numbers — even though the
      numbers are properties of neither. A spec that is identical for a
      one block type and another is not a measurement of either.
  (2) The string it produced is unparseable by the consumer
      (`analog_real_corner_sweep.l5_block_specs`), so the block-spec gate
      FAILs on it.

WHY THE OBVIOUS REPAIR IS WORSE. Type-casting the same six numbers into a
structured `specs[]` would clear the gate and make the flow LESS truthful: the
corner sweep would then grade a block against a number that belongs to a
different quantity and stamp a real PASS/FAIL on it. A fabricated measurement
is worse than an unparseable one. So the rule under test is not "produce
structure" but "produce structure ONLY where the text attributes a number to a
named quantity, and emit NOTHING otherwise".

DIRECTION OF RISK. Emitting a spec is the dangerous direction — a wrong spec
becomes a graded corner result downstream. The negative set below is therefore
much larger than the positive set, and every negative asserts the EMPTY result.

All fixtures are SYNTHESIZED neutral prose — invented values, generic
electrical-engineering vocabulary. No design, PDK, vendor or part number
appears, and no sentence is copied from any input document.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

runner = pytest.importorskip("phase1_doc_one_shot_runner")

_assoc = getattr(runner, "_analog_spec_associations", None)
_spec_fn = getattr(runner, "_analog_spec_from_paragraph", None)


def _spec(paragraph, block_type="synth_block_type_a"):
    """Drive the SHIPPED entry point, whatever arity it has.

    THIS SHIM IS THE POINT OF THIS FILE, not an accommodation. The pre-fix
    function takes `(paragraph)` and the fixed one takes `(paragraph,
    block_type)`. A suite that reaches for the NEW helper by name and skips
    when it is absent cannot fail on the tree that has the defect — it is not a
    control, it is an abstention. Every behavioural assertion below therefore
    goes through this shim, so the defect is REPRODUCED on the unfixed tree
    rather than skipped over.
    """
    try:
        return _spec_fn(paragraph, block_type)
    except TypeError:
        return _spec_fn(paragraph)


#: Tests that exercise the structured helper by name can only run where it
#: exists. They are the ADDITIONAL detail, never the control.
_needs_helper = pytest.mark.skipif(
    _assoc is None,
    reason="structured-attribution helper absent (pre-fix tree); the "
           "behavioural controls in this file still run and still fail there")


# ── POSITIVE: a number the text attributes to a named quantity ─────────────

@_needs_helper
def test_label_immediately_before_the_value_is_attributed():
    got = _assoc("Output voltage vout 1.80 V under load.", "synth_block_type_a")
    assert len(got) == 1, got
    assert got[0]["name"] == "vout"
    assert got[0]["target"] == pytest.approx(1.8)
    assert got[0]["unit"] == "V"


@_needs_helper
def test_label_immediately_after_the_value_is_attributed():
    got = _assoc("The block regulates 1.80 V vout across corners.", "synth_block_type_a")
    assert [a["name"] for a in got] == ["vout"], got
    assert got[0]["target"] == pytest.approx(1.8)


@_needs_helper
def test_values_are_scaled_to_si():
    """`12 uA` must become 1.2e-05 A, not 12. A consumer comparing against a
    target in amps would otherwise be off by six orders of magnitude."""
    got = _assoc("Nominal vout 1.80 V and quiescent current iq 12 uA.",
                 "synth_block_type_a")
    by = {a["name"]: a for a in got}
    assert set(by) == {"vout", "iq"}, got
    assert by["iq"]["target"] == pytest.approx(12e-6)
    assert by["iq"]["unit"] == "A"


@_needs_helper
def test_every_attributed_spec_carries_its_own_evidence():
    """A value that cannot be traced back to text is not auditable."""
    for a in _assoc("Output voltage vout 1.80 V under load.", "synth_block_type_a"):
        assert a.get("evidence_text"), a
        assert "1.80" in a["evidence_text"], a
        assert a.get("attribution") in (
            "label_before_value", "label_after_value"), a


@_needs_helper
def test_a_supply_unit_spelling_is_not_silently_dropped():
    """`Vdd` is a unit spelling the numeric+unit regex emits. Without a
    dimension entry the token matches and is then DISCARDED with no report —
    the same silent-drop shape this function exists to end."""
    got = _assoc("Supply rail vin 1.80 Vdd nominal.", "synth_block_type_a")
    assert [a["name"] for a in got] == ["vin"], got
    assert got[0]["target"] == pytest.approx(1.8)


# ── NEGATIVE CONTROLS: nothing attributable ⇒ NOTHING emitted ─────────────

def test_a_bare_list_of_numbers_attributes_nothing():
    """THE ORIGINAL DEFECT. Six numeric+unit tokens, no quantity named next to
    any of them: a timing enumeration and a register-field enumeration. The
    old assembler emitted all six as the block's spec."""
    para = ("Options are 55 us, 110 us, 220 us, 3.3 ms; the field encodes "
            "7.7 V and 8.8 V.")
    assert _spec(para, "synth_block_type_a") is None, (
        "six unattributed numbers were emitted as this block's spec: %r"
        % (_spec(para, "synth_block_type_a"),))


def test_two_block_types_do_not_receive_the_same_numbers():
    """The sharpest form of the defect: one paragraph, two block types, and
    the old code handed both the identical six-number string."""
    para = ("Options are 55 us, 110 us, 220 us, 3.3 ms; the field encodes "
            "7.7 V and 8.8 V.")
    a, b = _spec(para, "synth_block_type_a"), _spec(para, "synth_block_type_b")
    assert a is None and b is None, (a, b)


@_needs_helper
def test_a_filler_word_between_label_and_value_breaks_attribution():
    """`vout of 1.80 V` — the label is near, not adjacent. Declining here is
    the point: a rule that tolerates one filler word tolerates a sentence."""
    assert _assoc("Output voltage vout of 1.80 V.", "synth_block_type_a") == []



@_needs_helper
def test_a_separator_between_label_and_value_breaks_attribution():
    """`threshold voltage 00: 9.9V` — the `00:` between the words and the
    number is what makes this number belong to a register field, not to a
    quantity the words name."""
    assert _assoc("threshold voltage 00: 9.9V", "synth_block_type_a") == []


@_needs_helper
def test_a_dimension_mismatch_is_rejected_not_coerced():
    """A label naming a VOLTAGE may not bind a CURRENT-dimensioned number.
    This is what makes an attribution falsifiable rather than a guess."""
    assert _assoc("Output voltage vout 12 uA.", "synth_block_type_a") == []


def test_empty_and_number_free_prose_attribute_nothing():
    assert _spec("", "synth_block_type_a") is None
    assert _spec("The block is enabled by the sequencer.",
                 "synth_block_type_a") is None


def test_the_contract_on_no_evidence_is_none_not_a_default():
    """The caller marks the block `low_confidence` and emits `spec: null` off
    this None. Returning a canned default here is the v1.6.66 defect that
    fabricated a spec on a keyword-only prose mention."""
    assert _spec("Mentions the block and nothing measurable.",
                 "synth_block_type_a") is None


# ── the table this function grades with must have no silent holes ─────────

def test_every_emittable_unit_has_a_dimension():
    """A unit the numeric+unit regex can PRODUCE but the dimension table does
    not KNOW is matched and then dropped without a word. Enumerated by
    matching real strings, not by parsing the alternation — an earlier draft
    parsed it and got the answer wrong."""
    rx = runner._RE_NUMERIC_WITH_UNIT
    tbl = runner._UNIT_DIMENSION_SCALE
    spellings = ["V", "Vpp", "mV", "uV", "kV", "mA", "uA", "nA", "A",
                 "GHz", "MHz", "kHz", "Hz", "ns", "us", "ms", "s",
                 "ppm", "°C", "pF", "nF", "uF", "ohm", "%", "dB", "Vdd"]
    emittable = []
    for u in spellings:
        m = rx.search("50 %s " % u)
        if m and m.group("unit") == u:
            emittable.append(u)
    missing = [u for u in emittable if u.lower() not in tbl]
    assert missing == [], (
        "the regex emits these unit spellings but the dimension table has no "
        "entry, so a number carrying one is matched and silently discarded: %r"
        % missing)
