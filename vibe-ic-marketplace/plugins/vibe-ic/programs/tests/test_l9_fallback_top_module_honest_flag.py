"""BIDIRECTIONAL control for `no_top_module_in_input` lying on the
`l1_ic_name_fallback` path.

THE QUESTION the flag exists to answer: did the design's own input declare a
top-level module? WHAT IT ACTUALLY MEASURED: is the `top_module` field
non-empty? Those coincide everywhere except on the one branch the flag
matters most: `l1_ic_name_fallback` fires precisely BECAUSE no
`module <name>(...)` declaration was found, and it then fills `top_module`
with a Verilog-sanitised copy of `L1.ic_name`. The field is non-empty by
construction, so the flag was structurally pinned to False in exactly the
case it exists to report.

`_v1_6_581_route_l1_fallback_top_module()` was written to stamp the honest
flag, but its `promoted_from_l1` early return sat ABOVE the stamp. Its
docstring delegated to "the normal no_top_module path" — MEASURED, that path
is `_flag_no_X_in_input(top_module, …)`, which returns False the moment it is
handed a non-empty value. So on `promoted_from_l1=True` neither site stamped
it: a design whose docs never name a top module shipped
`no_top_module_in_input: false` alongside
`top_module_extraction_strategy: l1_ic_name_fallback` — the strategy stamp and
the flag contradicting each other in the same record.

chip-AGNOSTIC: pure dict-in/dict-out on the provenance stamp. No vendor, no
SKU, no process node, no part number, no chip-class vocabulary.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase1_doc_one_shot_runner as p1doc  # noqa: E402

FALLBACK = "l1_ic_name_fallback"
FLAG = "no_top_module_in_input"
_fn = p1doc._v1_6_581_route_l1_fallback_top_module


def _pins(n=4):
    return [{"name": f"p{i}", "direction": "input", "width": 1} for i in range(n)]


def test_forward_fallback_and_promoted_stamps_the_honest_flag():
    """The strategy stamp already says the input named no module; the flag
    must not contradict it in the same record — even when the pins were
    promoted verbatim from a real L1.pin_table."""
    l9 = {"top_module": "ID_LIKE_NAME",
          "top_module_extraction_strategy": FALLBACK,
          "top_module_pins": _pins(), "top_ports": _pins(), "ports": _pins(),
          FLAG: False}
    _fn(l9, True)
    assert l9[FLAG] is True


def test_reverse_r1_real_extraction_never_marked_absent():
    """A fix that simply always stamped True would pass FORWARD and destroy
    the signal here — a REAL extraction must never be flagged as absent."""
    for real_strategy in ("doc_module_decl_or_heading",
                          "staged_rtl_structural_top",
                          "rtl_filesystem_scan",
                          "doc_prose_top_cell_v1_6_398",
                          "doc_prose_top_module_v1_6_409"):
        l9 = {"top_module": "real_top",
              "top_module_extraction_strategy": real_strategy,
              "top_module_pins": _pins(), "top_ports": _pins(),
              "ports": _pins(), FLAG: False}
        rv = _fn(l9, True)
        assert l9[FLAG] is False and rv is False, real_strategy
        assert len(l9["top_module_pins"]) == 4, real_strategy


def test_reverse_r2_promoted_pins_stay_promoted():
    """The whole point of the promoted_from_l1 follow-up: genuine extracted
    pins must NOT be discarded by this fix."""
    l9 = {"top_module": "ID_LIKE_NAME",
          "top_module_extraction_strategy": FALLBACK,
          "top_module_pins": _pins(), "top_ports": _pins(), "ports": _pins(),
          FLAG: False}
    rv = _fn(l9, True)
    assert len(l9["top_module_pins"]) == 4
    assert len(l9["top_ports"]) == 4
    assert len(l9["ports"]) == 4
    assert rv is False
    assert "top_module_pins_evidence" not in l9, (
        "the cleared-pins evidence block must not appear when pins were "
        "preserved — it would describe a clear that did not happen")


def test_reverse_r3_unpromoted_path_unchanged():
    l9 = {"top_module": "ID_LIKE_NAME",
          "top_module_extraction_strategy": FALLBACK,
          "top_module_pins": _pins(), "top_ports": _pins(), "ports": _pins(),
          FLAG: False}
    rv = _fn(l9, False)
    assert l9[FLAG] is True
    assert l9["top_module_pins"] == [] and l9["top_ports"] == [] and l9["ports"] == []
    assert rv is True
    assert (l9.get("top_module_pins_evidence", {}).get("reason")
            == "no_module_declaration_in_input_docs")
    assert l9["top_module"] == "ID_LIKE_NAME", (
        "the tentative top_module label is kept, not blanked — downstream "
        "needs a human-readable handle")


def test_reverse_r4_sentinel_path_untouched():
    l9 = {"top_module": "chip_top",
          "top_module_extraction_strategy": "canonical_chip_top_sentinel",
          "top_module_pins": _pins(), FLAG: False}
    _fn(l9, True)
    assert l9[FLAG] is False, (
        "canonical_chip_top_sentinel is not this function's business")


def test_reverse_r5_malformed_input_never_raises():
    for bad in (None, [], "not-a-dict", 7):
        assert _fn(bad, True) is False
    l9 = {"top_module_pins": _pins(), FLAG: False}          # strategy missing
    assert _fn(l9, True) is False and l9[FLAG] is False
    l9 = {"top_module_extraction_strategy": None, "top_module_pins": _pins(),
          FLAG: False}
    assert _fn(l9, True) is False and l9[FLAG] is False


def test_reverse_r6_idempotent():
    l9 = {"top_module": "ID_LIKE_NAME",
          "top_module_extraction_strategy": FALLBACK,
          "top_module_pins": _pins(), "top_ports": _pins(), "ports": _pins(),
          FLAG: False}
    _fn(l9, True)
    snap = dict(l9)
    _fn(l9, True)
    assert l9 == snap

    l9 = {"top_module": "ID_LIKE_NAME",
          "top_module_extraction_strategy": FALLBACK,
          "top_module_pins": _pins(), "top_ports": _pins(), "ports": _pins(),
          FLAG: False}
    _fn(l9, False)
    snap = dict(l9)
    _fn(l9, False)
    assert l9 == snap
