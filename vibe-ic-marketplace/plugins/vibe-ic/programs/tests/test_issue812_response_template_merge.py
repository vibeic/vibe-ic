"""Regression tests for #812 — Phase 1 stamped a synthesised template over
the one it extracted from the document.

DEFECT SHAPE
------------
`gen_l3_cmd_protocol` extracts the response bytes VERBATIM when the source
document states them, into `opcodes[].response_payload_template_extracted`.
The per-opcode enrichment pass then assigned a SYNTHESISED placeholder onto
the canonical `opcodes[].response_payload_template`, unconditionally. That
placeholder exists only to satisfy a downstream typed-shape requirement
("the gate's typed-shape requirement is met"), and no consumer anywhere in
the plugin read the `..._extracted` sibling — a grep found exactly one hit,
the write itself.

So for `tx_len >= 2` the canonical template was `[{value: op+1},
{source: payload}..., {source: crc8}]` REGARDLESS of what the document
said, and an opcode whose document gave the full response was
indistinguishable, to every consumer, from one that gave nothing. The
polarity was inverted: the better-documented the input, the more
information was discarded.

THE FIX
-------
`_merge_response_payload_template` merges per `byte_offset`: the document
wins every offset it covers, the synthesised placeholder survives only in
the gaps, and the union of both offset domains is emitted. The typed-shape
guarantee is untouched for undocumented bytes.

TEST STRUCTURE — read this before trusting any assertion below
--------------------------------------------------------------
SECTION A1 holds the four BIDIRECTIONAL / BEHAVIOURAL controls, and only
those four. Every assertion there calls entry points that existed BEFORE
the fix (`gen_l3_cmd_protocol`,
`design_one_shot_runner._golden_bytes_from_l3_opcode`) and asserts on the
PRE-EXISTING key `response_payload_template`. Run against the pre-fix tree
they fail on a VALUE comparison — not on an ImportError or an AttributeError
for a symbol that did not exist yet. Measured at e3aa9b126:

    test_documented_response_survives_into_the_canonical_key
        assert ['0x41', None, ...] == ['0x41', '0xAA', ..., '0x89']
    test_documented_opcode_does_not_claim_it_has_no_reference_output
        assert None == '41,AA,BB,CC,DD,89'
    test_documented_and_undocumented_are_distinguishable
        assert all(v is not None for v in full) -> False
    test_partially_documented_response_keeps_its_documented_bytes
        assert ['0x61', None, ...] == ['0x61', '0x99', None, ...]

SECTION A2 holds checks that PASS ON BOTH TREES. They are not evidence that
the defect existed; they are the guards that keep A1 from passing vacuously
and that pin what the fix must NOT change.

SECTION B unit-tests the new merge helper directly. Those tests CANNOT run
against the pre-fix tree (the symbol does not exist), so they are NOT
evidence that the defect existed. They guard the merge rule against future
drift; they prove nothing about the before-state.

SECTION C is the NO-REGRESSION control: the undocumented path must behave
exactly as it did before. It passes on BOTH trees by construction.

All inputs are synthetic. No chip / vendor / SKU / IC literal participates.
"""
import importlib
import json

import pytest

mod = importlib.import_module("phase1_doc_one_shot_runner")
dsr = importlib.import_module("design_one_shot_runner")


# ---------------------------------------------------------------------------
# Fixture — one synthetic command table carrying three rows that differ ONLY
# in how much of the response the document states.
#
#   0x40  document states the response IN FULL      (6 of 6 bytes)
#   0x50  document states NO response bytes         (0 of 6 bytes)
#   0x60  document states the response IN PART      (2 of 6 bytes)
#
# All three declare tx_len=6, so under the pre-fix enrichment all three
# produced the SAME canonical template — which is the defect.
# ---------------------------------------------------------------------------
_DOC = (
    "Command Table\n"
    "RxLen\tTxLen\tTxAddr\tOpCode\tTX-content\tRX-content\tDescription\n"
    "4\t6\t00\t40\t40\t11\t22\t33\t\t41\tAA\tBB\tCC\tDD\t89\t\tFULL row\n"
    "4\t6\t00\t50\t50\t11\t22\t33\t\t\tSILENT row\n"
    "4\t6\t00\t60\t60\t11\t22\t33\t\t61\t99\t\tPARTIAL row\n"
)

_DOCUMENTED_RESPONSE = ["0x41", "0xAA", "0xBB", "0xCC", "0xDD", "0x89"]


def _eligible_l2():
    """L2 that opens the document-level opcode-synthesis gate."""
    return {"protocol_overview": {"half_duplex": True,
                                  "protocol_class": "half_duplex"}}


def _run_l3(tmp_path):
    proj = tmp_path / "proj"
    (proj / "phase1" / "generated_docs").mkdir(parents=True, exist_ok=True)
    mod.gen_l3_cmd_protocol(proj, {"cmd_table.txt": _DOC}, _eligible_l2())
    data = json.loads(
        (proj / "phase1" / "generated_docs" /
         "L3_CMD_PROTOCOL.json").read_text())
    return {op["hex"]: op for op in data.get("opcodes", [])
            if isinstance(op, dict) and "hex" in op}


@pytest.fixture(scope="module")
def opcodes(tmp_path_factory):
    return _run_l3(tmp_path_factory.mktemp("i812"))


def _values(tmpl):
    """byte_offset-ordered `value` list; None where the entry carries only
    a `source` pointer. Uses .get() so a missing key is a VALUE mismatch,
    never a KeyError — the assertion has to fail on the claim itself."""
    return [e.get("value") for e in
            sorted(tmpl, key=lambda e: e.get("byte_offset", -1))]


# ===========================================================================
# SECTION A2 — holds on BOTH trees. Keeps A1 from passing vacuously.
# ===========================================================================

def test_precondition_document_response_is_extracted(opcodes):
    """Guard on the fixture itself: the parser really did read the response
    bytes out of the document. If this ever stops holding, the A1 controls
    would pass vacuously.

    Holds on BOTH trees — the extraction was never the broken half."""
    assert set(opcodes) == {"0x40", "0x50", "0x60"}
    assert _values(opcodes["0x40"]["response_payload_template_extracted"]) \
        == _DOCUMENTED_RESPONSE
    assert opcodes["0x50"].get(
        "response_payload_template_extracted") is None
    assert opcodes["0x40"]["tx_len"] == opcodes["0x50"]["tx_len"] == 6


# ===========================================================================
# SECTION A1 — the four BIDIRECTIONAL / BEHAVIOURAL controls.
# Pre-existing entry points, pre-existing keys. These FAIL pre-fix on a
# value comparison; the exact pre-fix text is quoted in the module docstring.
# ===========================================================================

def test_documented_response_survives_into_the_canonical_key(opcodes):
    """THE NEGATIVE CONTROL the issue names, carrying BOTH byte groups.

    The canonical `response_payload_template` — the key every consumer
    reads — must carry the bytes the DOCUMENT stated.

    PRE-FIX: the canonical key held
      [{0, value 0x41}, {1..4, source: payload}, {5, source: crc8}]
    so this assertion failed with
      assert ['0x41', None, None, None, None, None] == [...'0xAA'...]
    POST-FIX: it holds the document's six bytes."""
    assert _values(opcodes["0x40"]["response_payload_template"]) \
        == _DOCUMENTED_RESPONSE


def test_documented_opcode_does_not_claim_it_has_no_reference_output(
        opcodes):
    """The same negative control read through a REAL pre-existing consumer.

    `design_one_shot_runner._golden_bytes_from_l3_opcode` is the function
    that decides whether a functional vector can be scored against a spec
    golden. It returns None when any byte of the template is not a concrete
    literal — which, pre-fix, was EVERY opcode with tx_len >= 2, including
    the ones whose document spelled the response out. So a fully documented
    opcode described itself as having no reference output and its vector was
    emitted UNVERIFIED.

    PRE-FIX: returns None.  POST-FIX: returns the document's bytes."""
    assert dsr._golden_bytes_from_l3_opcode(opcodes["0x40"]) \
        == "41,AA,BB,CC,DD,89"


def test_documented_and_undocumented_are_distinguishable(opcodes):
    """The defect in one line: two opcodes that differ ONLY in whether the
    document states the response must not produce the same canonical
    template.

    PRE-FIX both were [{value: op+1}, source..., source: crc8] and this
    failed — the verdict was a pure function of `tx_len >= 2`."""
    full = _values(opcodes["0x40"]["response_payload_template"])
    silent = _values(opcodes["0x50"]["response_payload_template"])
    assert full != silent
    # ... and specifically: the documented one is fully bound, the silent
    # one is not bound past the echo byte.
    assert all(v is not None for v in full)
    assert any(v is None for v in silent)


def test_partially_documented_response_keeps_its_documented_bytes(opcodes):
    """Merge-per-byte-offset, the property "fill, don't overwrite" alone
    would not give: the document stated 2 of 6 bytes, so those 2 offsets
    carry the document's bytes and only the remaining 4 stay placeholders.

    PRE-FIX the two documented bytes were discarded entirely and offset 1
    read `source: payload`."""
    tmpl = opcodes["0x60"]["response_payload_template"]
    assert _values(tmpl) == ["0x61", "0x99", None, None, None, None]
    by_off = {e["byte_offset"]: e for e in tmpl}
    # The gaps still carry the typed-shape placeholder, unchanged.
    assert by_off[2].get("source") == "payload"
    assert by_off[5].get("source") == "crc8"


# ===========================================================================
# SECTION A2 (continued) — holds on BOTH trees.
# ===========================================================================

def test_partial_documentation_still_yields_no_concrete_golden(opcodes):
    """Honesty in the other direction: a PARTIALLY documented response is
    not a reference output. The consumer must still refuse to score it.

    Passes on BOTH trees (pre-fix for the wrong reason — everything was
    refused; post-fix because 4 of 6 bytes genuinely remain unknown). It is
    here to pin that the fix did not turn a partial document into a
    fabricated golden."""
    assert dsr._golden_bytes_from_l3_opcode(opcodes["0x60"]) is None


def test_merged_template_never_drops_a_byte_offset(opcodes):
    """Shape invariant, holds on BOTH trees. The synthesised placeholder
    spans byte_offset 0..tx_len-1; the merge may only ADD offsets (when the
    document describes a longer response), never remove one. A consumer
    that indexed the template by offset before must still find every
    offset."""
    for op in opcodes.values():
        tx_len = op.get("tx_len")
        tmpl = op["response_payload_template"]
        offsets = {e["byte_offset"] for e in tmpl}
        assert offsets >= set(range(tx_len)), (
            f"opcode {op['hex']} lost an offset: {sorted(offsets)}")


# ===========================================================================
# SECTION B — unit tests of the NEW merge helper.
#
# NOT bidirectional evidence: `_merge_response_payload_template` does not
# exist on the pre-fix tree, so these die on AttributeError there and prove
# nothing about the before-state. They exist to pin the merge RULE against
# future drift.
# ===========================================================================

def test_merge_document_wins_every_offset_it_covers():
    doc = [{"byte_offset": 0, "value": "0xAA"},
           {"byte_offset": 1, "value": "0xBB"}]
    synth = [{"byte_offset": 0, "value": "0x11"},
             {"byte_offset": 1, "source": "payload"},
             {"byte_offset": 2, "source": "crc8"}]
    out = mod._merge_response_payload_template(doc, synth)
    assert [e["byte_offset"] for e in out] == [0, 1, 2]
    assert [e.get("value") for e in out] == ["0xAA", "0xBB", None]
    assert [e["provenance"] for e in out] == [
        "document", "document", "synthesised_placeholder"]


def test_merge_with_no_document_is_the_placeholder_unchanged():
    synth = [{"byte_offset": 0, "value": "0x11"},
             {"byte_offset": 1, "source": "crc8"}]
    for empty in (None, [], "not-a-list", {}):
        out = mod._merge_response_payload_template(empty, synth)
        assert [{k: v for k, v in e.items() if k != "provenance"}
                for e in out] == synth
        assert all(e["provenance"] == "synthesised_placeholder"
                   for e in out)


def test_merge_spans_the_union_when_the_document_is_longer():
    doc = [{"byte_offset": i, "value": f"0x{i:02X}"} for i in range(4)]
    synth = [{"byte_offset": 0, "value": "0x11"}]
    out = mod._merge_response_payload_template(doc, synth)
    assert [e["byte_offset"] for e in out] == [0, 1, 2, 3]
    assert all(e["provenance"] == "document" for e in out)


@pytest.mark.parametrize("bad", [
    "not-a-dict",
    {"value": "0xAA"},                       # no byte_offset
    {"byte_offset": "x", "value": "0xAA"},   # unparseable byte_offset
    {"byte_offset": 0},                      # no value at all
    {"byte_offset": 0, "value": ""},         # empty value
    {"byte_offset": 0, "value": "   "},      # whitespace-only value
    {"byte_offset": 0, "value": True},       # bool is not a byte
])
def test_merge_ignores_structurally_unusable_document_entries(bad):
    """A malformed extraction may only ever leave the placeholder standing.
    It must never be able to replace a well-formed placeholder with
    something worse."""
    synth = [{"byte_offset": 0, "value": "0x11", "source": None}]
    out = mod._merge_response_payload_template([bad], synth)
    assert len(out) == 1
    assert out[0]["byte_offset"] == 0
    assert out[0]["value"] == "0x11"
    assert out[0]["provenance"] == "synthesised_placeholder"


def test_merge_never_returns_an_empty_template():
    """The typed-shape guarantee is the placeholder's whole reason to
    exist; the merge must not be a way to lose it."""
    synth = [{"byte_offset": None, "value": "0x11"}]
    assert mod._merge_response_payload_template(None, synth) == synth


def test_merge_does_not_mutate_its_inputs():
    doc = [{"byte_offset": 0, "value": "0xAA"}]
    synth = [{"byte_offset": 0, "value": "0x11"},
             {"byte_offset": 1, "source": "crc8"}]
    mod._merge_response_payload_template(doc, synth)
    assert doc == [{"byte_offset": 0, "value": "0xAA"}]
    assert synth == [{"byte_offset": 0, "value": "0x11"},
                     {"byte_offset": 1, "source": "crc8"}]


# ===========================================================================
# SECTION C — NO-REGRESSION control.
# Passes on BOTH trees. Asserts only on the fields that existed before, so
# the added `provenance` tag cannot make it green by accident.
# ===========================================================================

def test_undocumented_response_keeps_the_typed_shape_placeholder(opcodes):
    """An opcode whose document says nothing about the response must come
    out byte-for-byte as it did before the fix: echo at offset 0, `source`
    pointers for the payload, CRC residue at the last offset."""
    tmpl = opcodes["0x50"]["response_payload_template"]
    stripped = [{k: v for k, v in e.items() if k != "provenance"}
                for e in sorted(tmpl, key=lambda e: e["byte_offset"])]
    assert stripped == [
        {"byte_offset": 0, "value": "0x51",
         "description": "response opcode echo"},
        {"byte_offset": 1, "source": "payload",
         "description": "payload byte 1"},
        {"byte_offset": 2, "source": "payload",
         "description": "payload byte 2"},
        {"byte_offset": 3, "source": "payload",
         "description": "payload byte 3"},
        {"byte_offset": 4, "source": "payload",
         "description": "payload byte 4"},
        {"byte_offset": 5, "source": "crc8",
         "description": "CRC-8 residue"},
    ]


def test_every_opcode_still_carries_a_typed_shape_template(opcodes):
    """The downstream typed-shape requirement the placeholder was written
    for still holds for every opcode, documented or not."""
    for op in opcodes.values():
        tmpl = op["response_payload_template"]
        assert isinstance(tmpl, list) and tmpl
        for ent in tmpl:
            assert isinstance(ent, dict)
            assert isinstance(ent.get("byte_offset"), int)
            assert ("value" in ent) or ("source" in ent)
