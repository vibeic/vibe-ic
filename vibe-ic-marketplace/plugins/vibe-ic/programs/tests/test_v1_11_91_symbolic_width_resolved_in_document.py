#!/usr/bin/env python3
"""v1.11.91 — a SYMBOLIC port width is resolved IN THE EMITTED DOCUMENT.

THE DEFECT
----------
`L9_INTEGRATION_SPEC.json` declared a port with `width_symbolic:
"size-1:0"` and a prose `width` string. `phase2_scaffold_gen.derive_signals`
correctly refused it (`width: None`), every scaffold emitter then raised
`UnresolvedPortWidth`, and two gates reported the layer:
`l17_channel_catalog_consumer_contract_check` with
PORT_WIDTH_UNRESOLVED_BY_CONSUMER, and `cross_layer_reference_check` with
CONSUMER_CANNOT_REACH — while the SAME document already declared
`parameters[] = [{"name": "size", "default": "32", ...}]`.

WHY THE FIX IS IN THE PRODUCER AND NOT IN `derive_signals`
----------------------------------------------------------
Both gates state the remedy verbatim
(`l17_channel_catalog_consumer_contract_check.py:1000-1004`):

    "The remedy is in L1/L9: state the width as an integer, or declare the
     parameter the range names in the same document. Resolving it inside the
     consumer is NOT the remedy -- #404 measured that a wrong resolution and
     a right one are indistinguishable from outside."

So the number is written into the DOCUMENT, where it is auditable: the
symbol, the parameter, that parameter's own `default` and `source` all ship
beside it in `width_resolution`. `width_symbolic` is REMOVED from the entry —
leaving it would keep the gates' rail firing on a width that is no longer
symbolic, which is the defect wearing the fix's clothes.

BOTH DIRECTIONS ARE PINNED HERE, and the second half is the load-bearing one.
A resolver that resolves everything is exactly the #404 failure. Every case
in `_UNRESOLVABLE` is a range this program must REFUSE, leaving the entry
byte-identical so the consumer keeps refusing and the gates keep firing.

MEASURED, on the halted SPM run (`spm_v11190_run2`) and on four adversarial
copies of it built by mutating only `L9.parameters` / `width_symbolic`:

    resolvable (as shipped)   l17 rc 1 -> 0   cross_layer rc 1 -> 0
    no such parameter         l17 rc 1        cross_layer rc 1
    two identifiers in range  l17 rc 1        cross_layer rc 1
    non-integer default       l17 rc 1        cross_layer rc 1
    two defaults, one name    l17 rc 1        cross_layer rc 1

A fifth copy mutated the parameter default to 4 — contradicting the width
the design's own shipped netlist declares. The resolution is then WRONG but
still derivable from the document, so this program does resolve it; it is
NOT invisible from outside, which is the #404 property that matters:
`cross_layer_reference_check` resolves `size` from the L8 parameter table
independently, sees 32 against the consumer's 4, and stays rc 1.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

p1 = importlib.import_module("phase1_doc_one_shot_runner")
psg = importlib.import_module("phase2_scaffold_gen")
spm = importlib.import_module("serial_parallel_mul_synth")

# The real entry as shipped in `L9_INTEGRATION_SPEC.json` for the SPM run.
_PROSE_WIDTH = "N-bit(`[size-1:0]`,parameter `size` 32)"
_SIZE_PARAM = {"name": "size", "default": "32",
               "source": "L3_external_interface.md",
               "extraction_strategy": "rst_param_grid_table_anchorless_v1_6_400"}


def _l9(symbolic: str = "size-1:0", parameters=None) -> dict:
    port = {"name": "x", "mode": "input", "direction": "input",
            "evidence": "input/docs/L3_external_interface.md",
            "extraction_strategy": "rst_grid_interface_table",
            "width": _PROSE_WIDTH, "width_symbolic": symbolic,
            "description": "parallel multiplicand"}
    return {"parameters": [dict(p) for p in
                           (parameters if parameters is not None
                            else [_SIZE_PARAM])],
            "ports": [dict(port)], "top_ports": [dict(port)],
            "top_module_pins": [dict(port)]}


def _x(doc: dict, key: str = "ports") -> dict:
    return [p for p in doc[key] if p["name"] == "x"][0]


def _derive_x(doc: dict) -> dict:
    sigs = psg.derive_signals({}, doc)
    match = [s for s in sigs if s["name"] == "x"]
    assert match, "the consumer dropped the port entirely"
    return match[0]


# ---------------------------------------------------------------------------
# DIRECTION 1 — the number IS derivable, so it lands in the document
# ---------------------------------------------------------------------------
def test_resolvable_symbol_becomes_an_integer_width_in_the_document():
    doc = _l9()
    assert p1._v1_11_91_resolve_symbolic_port_widths_in_doc(doc) == 3

    for key in ("ports", "top_ports", "top_module_pins"):
        entry = _x(doc, key)
        assert entry["width"] == 32
        assert entry["msb"] == 31 and entry["lsb"] == 0
        # The gates' rail keys on exactly these two shapes
        # (l17_channel_catalog_consumer_contract_check.py:953-956): a truthy
        # `width_symbolic`, or a `width` that is a non-digit string. Neither
        # may survive a resolution, or the gate fires on a resolved width.
        assert "width_symbolic" not in entry
        assert not (isinstance(entry["width"], str)
                    and not str(entry["width"]).strip().isdigit())


def test_the_resolution_ships_its_own_provenance():
    """The number must be re-derivable by a reader, without running this."""
    doc = _l9()
    p1._v1_11_91_resolve_symbolic_port_widths_in_doc(doc)
    prov = _x(doc)["width_resolution"]

    assert prov["width_symbolic"] == "size-1:0"
    assert prov["identifier"] == "size"
    assert prov["parameter_default"] == "32"
    assert prov["parameter_source"] == "L3_external_interface.md"
    assert prov["scope"] == "same_document_parameters"
    assert (prov["resolved_width"], prov["msb"], prov["lsb"]) == (32, 31, 0)
    # The sentence the layer actually stated is not lost.
    assert prov["width_declared"] == _PROSE_WIDTH
    assert "symbolic_width_resolved_v1_11_91" in _x(doc)["extraction_strategy"]


def test_the_consumer_then_derives_32_and_the_emitters_render():
    doc = _l9()
    assert _derive_x(doc)["width"] is None, (
        "unresolved is the state this fix starts from")

    p1._v1_11_91_resolve_symbolic_port_widths_in_doc(doc)
    sig = _derive_x(doc)
    assert sig["width"] == 32
    assert "width_declared" not in sig

    sigs = psg.derive_signals({}, doc)
    assert "[31:0] x" in psg.emit_top_v("spm", sigs, "spm")
    assert "[31:0] x" in psg.emit_tb_v("spm", sigs)
    assert "[31:0] x" in psg.emit_soc_wrap_v("spm", sigs, [])
    psg.emit_cocotb_test("spm", sigs, {}, [])


def test_resolution_is_idempotent():
    doc = _l9()
    assert p1._v1_11_91_resolve_symbolic_port_widths_in_doc(doc) == 3
    before = [dict(p) for p in doc["ports"]]
    assert p1._v1_11_91_resolve_symbolic_port_widths_in_doc(doc) == 0
    assert doc["ports"] == before


# ---------------------------------------------------------------------------
# DIRECTION 2 — the number is NOT derivable, so nothing is written
#
# This is the half that keeps the fix from being a guess. Each case is a
# document that genuinely cannot decide the width; the program must leave the
# entry exactly as the layer stated it.
# ---------------------------------------------------------------------------
_UNRESOLVABLE = {
    # The range names an identifier no parameter of THIS document declares.
    "no_such_parameter": ("size-1:0", [dict(_SIZE_PARAM, name="word_len")]),
    # Two identifiers: resolving needs a choice, and a choice is a guess.
    "two_identifiers": ("size-pad:0",
                        [_SIZE_PARAM, {"name": "pad", "default": "2"}]),
    # The declared default is prose, not an integer.
    "non_integer_default": ("size-1:0",
                            [dict(_SIZE_PARAM, default="8 / 16 / 32")]),
    # One name, two different defaults — the document contradicts itself.
    # `L9.parameters` is deduplicated by `name.upper()` upstream, so `SIZE`
    # and `size` are the same parameter to this corpus.
    "two_defaults_one_name": ("size-1:0",
                              [_SIZE_PARAM, dict(_SIZE_PARAM, name="SIZE",
                                                 default="16")]),
    # The document declares no parameters at all.
    "no_parameter_table": ("size-1:0", []),
    # Not a range at all.
    "bare_identifier": ("size", [_SIZE_PARAM]),
    # An arithmetic form outside the grammar this program will evaluate.
    "multiplication": ("size*2-1:0", [_SIZE_PARAM]),
}


@pytest.mark.parametrize("case", sorted(_UNRESOLVABLE))
def test_an_underivable_width_is_left_exactly_as_the_layer_stated_it(case):
    symbolic, params = _UNRESOLVABLE[case]
    doc = _l9(symbolic=symbolic, parameters=params)
    before = [dict(p) for p in doc["ports"]]

    assert p1._v1_11_91_resolve_symbolic_port_widths_in_doc(doc) == 0, (
        f"{case}: the width was resolved from a document that cannot "
        f"determine it — that is guessing, which is exactly the #404 "
        f"failure this fix must not reintroduce")
    assert doc["ports"] == before
    for key in ("ports", "top_ports", "top_module_pins"):
        entry = _x(doc, key)
        assert entry["width"] == _PROSE_WIDTH
        assert entry["width_symbolic"] == symbolic
        assert "width_resolution" not in entry


@pytest.mark.parametrize("case", sorted(_UNRESOLVABLE))
def test_the_consumer_still_refuses_an_underivable_width(case):
    """The refusal must survive to the consumer AND to every emitter.

    A document left alone is only half the property: what makes the gates
    keep firing is that `derive_signals` still returns `width: None` and the
    emitters still raise.
    """
    symbolic, params = _UNRESOLVABLE[case]
    doc = _l9(symbolic=symbolic, parameters=params)
    p1._v1_11_91_resolve_symbolic_port_widths_in_doc(doc)

    sig = _derive_x(doc)
    assert sig["width"] is None
    assert sig["width_declared"] == symbolic

    sigs = psg.derive_signals({}, doc)
    for emit, args in ((psg.emit_top_v, ("spm", sigs, "spm")),
                       (psg.emit_tb_v, ("spm", sigs)),
                       (psg.emit_soc_wrap_v, ("spm", sigs, []))):
        with pytest.raises(psg.UnresolvedPortWidth):
            emit(*args)


def test_the_hook_is_wired_into_the_phase1_post_emit_chain():
    """A resolver nothing calls would leave both gates red on a real run."""
    src = (_PROGRAMS / "phase1_doc_one_shot_runner.py").read_text()
    assert src.count(
        "_post_emit_resolve_symbolic_port_widths_v1_11_91(project)") == 1, (
        "the post-emit hook is defined but never called")


def test_the_refusal_assertions_would_catch_a_guessing_resolver(monkeypatch):
    """CONTROL — direction 2 must be able to go red for the RIGHT reason.

    Against the UNFIXED program every test in this file fails with
    `AttributeError`: absence, not disagreement. That proves the file is new,
    not that its refusal assertions discriminate. This substitutes a resolver
    that answers EVERY range with 32 — the guessing failure #404 is about —
    and shows all seven refusal cases flip, so the assertions above are load
    bearing rather than vacuous.
    """
    def _guess(symbolic, parameters):
        if not isinstance(symbolic, str) or not symbolic.strip():
            return None
        return {"width_symbolic": symbolic.strip(), "identifier": "?",
                "parameter_default": "32", "parameter_default_int": 32,
                "parameter_source": None,
                "parameter_extraction_strategy": None,
                "scope": "same_document_parameters",
                "resolved_width": 32, "msb": 31, "lsb": 0,
                "resolved_by": "guessing_resolver"}

    monkeypatch.setattr(p1, "_v1_11_91_resolve_symbolic_range", _guess)
    for case, (symbolic, params) in sorted(_UNRESOLVABLE.items()):
        doc = _l9(symbolic=symbolic, parameters=params)
        if not params:
            # `no_parameter_table` is refused one level OUT, by the walker
            # itself: a document with no parameter table has nothing to join
            # against, so no resolver is consulted at all. Its refusal is
            # pinned by the tests above; it cannot flip here.
            assert p1._v1_11_91_resolve_symbolic_port_widths_in_doc(doc) == 0
            continue
        assert p1._v1_11_91_resolve_symbolic_port_widths_in_doc(doc) == 3, case
        assert _x(doc)["width"] == 32, case
        assert "width_symbolic" not in _x(doc), case
        assert _derive_x(doc)["width"] == 32, case


# ---------------------------------------------------------------------------
# BLAST RADIUS — the one downstream reader that read the symbol directly
# ---------------------------------------------------------------------------
def test_the_parametric_width_reader_follows_the_symbol_into_provenance():
    """`serial_parallel_mul_synth._size_param_from` must not degrade silently.

    It recovered the parameter NAME and DEFAULT by regexing `width_symbolic` /
    the width prose / a symbolic `msb`. After the resolution all three carry
    integers, so every source misses and the function would fall back to its
    own `default_name`/`default_val` — a real parameter name replaced by a
    guess, with no diagnostic. It reads `width_resolution` first instead.

    The fallback IS still correct behaviour for a port that never carried a
    symbol; what must not happen is a RESOLVED port answering with the
    fallback's literal.
    """
    doc = _l9(parameters=[dict(_SIZE_PARAM, name="word_len", default="48")])
    doc["ports"][0]["width_symbolic"] = "word_len-1:0"
    doc["top_ports"][0]["width_symbolic"] = "word_len-1:0"
    doc["top_module_pins"][0]["width_symbolic"] = "word_len-1:0"
    port = _x(doc)
    # BEFORE: the regex path recovers the NAME from `width_symbolic` but has
    # nowhere to read the default from, so it answers with its own literal 32.
    # That limit is pre-existing and is not what this test is about.
    assert spm._size_param_from(port) == ("word_len", 32)
    assert spm._port_width_is_wide(port)

    p1._v1_11_91_resolve_symbolic_port_widths_in_doc(doc)
    resolved = _x(doc)
    assert resolved["width"] == 48
    assert spm._size_param_from(resolved) == ("word_len", 48), (
        "the resolved port answered with the function's own default instead "
        "of the parameter the document names")
    assert spm._port_width_is_wide(resolved)
