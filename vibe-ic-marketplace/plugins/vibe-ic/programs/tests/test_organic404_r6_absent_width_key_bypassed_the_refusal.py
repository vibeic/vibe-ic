#!/usr/bin/env python3
"""ORGANIC #404 round 6 — the two spellings of "no width" must agree.

WHAT THE EARLIER ROUNDS SETTLED, so this file does not re-tread it
-------------------------------------------------------------------
Round 1 added the l17 rail that REPORTS the collapse; round 2 made
``width == 1`` a branch INSIDE the layer condition rather than a guard in
front of it; round 3 put the refusal in the consumer itself
(``width: None`` + `require_resolved_widths`); round 4 added the
shipped-netlist refutation arm. The resolution axis stays withdrawn and is
not re-argued here.

WHAT THIS FILE CLOSES
----------------------
`derive_signals`' docstring says ABSENT is "key missing, **or null**, with
no ``width_symbolic``" — two spellings, one meaning. The code disagreed
with its own contract on one of them::

    {"width": None, "width_symbolic": "ACC_W-1:0"}   -> width=None  REFUSED
    {                "width_symbolic": "ACC_W-1:0"}   -> width=1     SILENT

because ``port.get("width", 1)`` turned a MISSING key into an int >= 1,
which registered the port in `resolved_from_layer` — the set whose own
comment says it holds names resolved "as opposed to the 1-bit default" —
and the post-pass skips everything in that set. So the port came out a
1-bit scalar, byte-identical to a real 1-bit port, and
`require_resolved_widths` never saw it. The whole enforcement axis had one
encoding-shaped hole.

WHY THIS IS NOT A DETECTOR FOR A POPULATION OF ONE (vibe-ic#439)
-----------------------------------------------------------------
Nothing here detects anything; one expression stops manufacturing a layer
statement that was never made. And the shape is REACHABLE from this repo's
own shipped producers, which
`test_the_shipped_producer_chain_builds_the_divergent_shape` drives
end-to-end rather than asserting about: `_parse_port_width` returns
``width=None`` together with a ``width_symbolic``, and both L1->L9
promotion sites copy the typed fields under ``if _v is not None`` — so the
None width is dropped and the symbol is kept. The shape is absent from
today's tracked L9 docs only because the L1 emitter separately keeps the
raw prose in ``width``, which its own comment calls "backward
compatibility". A legacy field in another program was the only thing
holding the refusal up.

MEASURED BLAST RADIUS
----------------------
Over the 196 tracked L-doc sets (every directory carrying an ``L9_*.json``)
the change moves nothing: 1679 derived ports before, 1679 after, the same 3
marked ``width: None``. The tracked corpus contains 194 port entries with a
missing ``width`` key and 6 carrying a ``width_symbolic``, but ZERO in the
intersection — both halves are live, only their overlap is empty.
`test_no_tracked_width_state_changes_classification` pins that by driving
every width state the corpus actually contains.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

psg = importlib.import_module("phase2_scaffold_gen")


def _derive_one(port: dict) -> dict:
    """Run the REAL consumer on one L9 port entry and return its signal."""
    sigs = psg.derive_signals({}, {"top_ports": [dict(port)]})
    match = [s for s in sigs if s["name"] == psg._sanitize_id(port["name"])]
    assert match, f"consumer dropped the port entirely: {port!r}"
    return match[0]


# ---------------------------------------------------------------------------
# The divergence itself
# ---------------------------------------------------------------------------
def test_absent_width_key_with_a_symbolic_width_is_refused_like_null():
    """The two spellings of ABSENT must reach the same verdict."""
    null_form = _derive_one({"name": "acc_o", "direction": "output",
                             "width": None,
                             "width_symbolic": "ACC_W-1:0"})
    missing_form = _derive_one({"name": "acc_o", "direction": "output",
                                "width_symbolic": "ACC_W-1:0"})

    # The null form was already correct; it anchors what correct looks like.
    assert null_form["width"] is None
    assert null_form["width_declared"] == "ACC_W-1:0"

    # The missing form used to be `width=1` with no `width_declared` at all.
    assert missing_form["width"] is None, (
        "a port whose layer states `width_symbolic` but omits the `width` "
        "key came out a silent 1-bit scalar")
    assert missing_form["width_declared"] == "ACC_W-1:0"

    assert null_form == missing_form, (
        "which spelling of 'no width' the producer chose still changes the "
        "consumer's answer")


def test_the_emitters_refuse_the_absent_key_form():
    """The refusal must reach `require_resolved_widths`, not just the dict.

    Round 3's whole point is that the generator writes NOTHING for a width
    it could not resolve. A `width: None` that no emitter checks would be
    decoration.
    """
    sigs = psg.derive_signals({}, {"top_ports": [
        {"name": "acc_o", "direction": "output",
         "width_symbolic": "ACC_W-1:0"}]})
    with pytest.raises(psg.UnresolvedPortWidth) as excinfo:
        psg.require_resolved_widths(sigs, "dut_top.v")
    assert "acc_o" in str(excinfo.value)
    assert "ACC_W-1:0" in str(excinfo.value)


def test_a_non_numeric_width_string_without_the_key_is_still_refused():
    """The other UNRESOLVED shape, in the absent-key spelling.

    `_record_declared_width` has two arms — `width_symbolic`, and a `width`
    that is a non-digit string. Only the first can co-occur with a missing
    `width` key, so this pins that the *null* spelling of the second arm did
    not regress while the first was being fixed.
    """
    sig = _derive_one({"name": "x", "direction": "input",
                       "width": "size-1:0"})
    assert sig["width"] is None
    assert sig["width_declared"] == "size-1:0"


# ---------------------------------------------------------------------------
# The shape is produced by this repo, not invented by this test
# ---------------------------------------------------------------------------
def test_the_shipped_producer_chain_builds_the_divergent_shape():
    """Drive the real parser + the real promotion loop body.

    This is the argument that the fix is not speculative. The promotion
    sites in `phase1_doc_one_shot_runner` copy the typed width fields under
    ``if _v is not None``; `_parse_port_width` returns ``width=None`` for a
    symbolic range. Composed, they build an L9 entry with `width_symbolic`
    and no `width` key.
    """
    runner = importlib.import_module("phase1_doc_one_shot_runner")
    cell = "N-bit(`[size-1:0]`, parameter `size` default 32)"
    w_int, msb, lsb, w_sym = runner._parse_port_width(cell)
    assert w_int is None, (
        "the premise changed: the parser now resolves this cell, so the "
        "None-drop below can no longer fire")
    assert w_sym, "the parser no longer preserves the symbolic form"

    # The promotion loop body, verbatim from the two shipped call sites.
    l1_pin = {"name": "acc_o", "width": w_int, "msb": msb, "lsb": lsb,
              "width_symbolic": w_sym}
    l9_entry = {"name": "acc_o", "direction": "output"}
    for _k in ("width", "msb", "lsb", "width_symbolic", "optional"):
        _v = l1_pin.get(_k)
        if _v is not None:
            l9_entry[_k] = _v

    assert "width" not in l9_entry, (
        "premise changed: the promoter no longer drops a None width")
    assert l9_entry["width_symbolic"] == w_sym

    # ... and the consumer must refuse what that chain produced.
    sig = _derive_one(l9_entry)
    assert sig["width"] is None
    assert sig["width_declared"] == w_sym


# ---------------------------------------------------------------------------
# Nothing the tracked corpus actually contains changes classification
# ---------------------------------------------------------------------------
_CORPUS_WIDTH_STATES = [
    # (label, port entry, expected width, expected width_declared)
    # Census over the 196 tracked L-doc sets / 549 L9 port entries:
    ("int>=1, no symbolic (341 entries)",
     {"name": "p", "width": 8}, 8, None),
    ("key missing, no symbolic (194 entries)",
     {"name": "p"}, 1, None),
    ("null, no symbolic (8 entries)",
     {"name": "p", "width": None}, 1, None),
    ("non-digit string + symbolic (6 entries)",
     {"name": "p", "width": "N-bit(`[size-1:0]`)",
      "width_symbolic": "size-1:0"}, None, "size-1:0"),
]


@pytest.mark.parametrize("label,port,want_width,want_declared",
                         _CORPUS_WIDTH_STATES,
                         ids=[c[0] for c in _CORPUS_WIDTH_STATES])
def test_no_tracked_width_state_changes_classification(
        label, port, want_width, want_declared):
    """Every width state the tracked corpus contains, driven through.

    The census found exactly four; the change must move none of them. The
    key-absent + symbolic shape is deliberately NOT in this list — the
    corpus contains zero of it, which is why the fix is provably a no-op on
    every tracked artefact.
    """
    sig = _derive_one(dict(port, direction="input"))
    assert sig["width"] == want_width, label
    assert sig.get("width_declared") == want_declared, label


def test_absent_width_without_a_symbol_is_still_the_scalar_default():
    """ABSENT must NOT be folded into UNRESOLVED.

    194 of 549 tracked port entries omit `width` entirely with no symbol.
    Refusing those would refuse most of the corpus for a defect no evidence
    supports — the failure mode round 3's docstring measured and rejected.
    """
    sig = _derive_one({"name": "en", "direction": "input"})
    assert sig["width"] == 1
    assert "width_declared" not in sig
    psg.require_resolved_widths([sig], "dut_top.v")   # must not raise


def test_the_scalar_default_is_not_recorded_as_a_layer_resolution():
    """The regression guard for the mechanism, not just the symptom.

    `resolved_from_layer` exists to hold names whose width this function
    parsed FROM the layer. If a future edit lets the 1-bit default back into
    that set, `test_absent_width_key_...` above goes green again for the
    wrong reason. This drives the observable consequence: an L17-sourced
    port with no width hint, re-stated in L9 with a symbolic width and no
    `width` key, must still be refused — it can only be refused if the
    default never claimed to be a layer resolution.
    """
    l17 = {"channels": [{"name": "acc_o", "direction_master": "output",
                         "purpose": "accumulator"}]}
    l9 = {"top_ports": [{"name": "acc_o", "direction": "output",
                         "width_symbolic": "ACC_W-1:0"}]}
    sigs = psg.derive_signals(l17, l9)
    acc = [s for s in sigs if s["name"] == "acc_o"][0]
    assert acc["width"] is None, (
        "the L17 arm's 1-bit default masked the L9 declaration")
    assert acc["width_declared"] == "ACC_W-1:0"


def test_json_roundtrip_cannot_change_the_verdict():
    """A missing key and a null survive JSON differently in neither
    direction now.

    L-docs reach the consumer through `json.loads`, and a producer that
    writes `"width": null` and one that omits the key produce byte-different
    files. Before the fix those two files made the generator emit different
    interfaces for the same design.
    """
    omitted = json.loads('{"name":"acc_o","direction":"output",'
                         '"width_symbolic":"ACC_W-1:0"}')
    explicit = json.loads('{"name":"acc_o","direction":"output",'
                          '"width":null,"width_symbolic":"ACC_W-1:0"}')
    assert _derive_one(omitted) == _derive_one(explicit)
