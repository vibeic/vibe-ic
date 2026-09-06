#!/usr/bin/env python3
"""Four declaration scans that read text no stripper had touched. vibe-ic#731.

The scans, each fixed AT ITS PRODUCER by lane czto12 in v1.18.26 (the value
reaching the scan is stripped; stripping a sibling variable would not make
these safe). THESE TESTS REQUIRE v1.18.26 -- they are the consequence pins that
landing did not carry, and they are RED on any tree before it:

    canonical_primitive_synth::_rtl_input_port_widths::_HDR(rtl)
    canonical_primitive_synth::_rtl_input_port_widths::_PORT_DECL(entry)
    phase1_port_extract::_verilog_region_spans::_MODULE_SPAN(text)
    sparse_fsm_detect::_module_at::_MODULE_RE(text)

These tests pin the CONSEQUENCE, not the dataflow, so a fix cannot be
satisfied by renaming a variable: the commented-out text must not contribute a
port, a module, a region or a parameter value that nobody wrote, and the real
declaration standing beside it must still be recovered. Every case below was
MEASURED failing on the pre-fix tree — the wrong answer is recorded in each
docstring so a future reader can tell a real regression from a changed shape.

Run: python3 -m pytest -q programs/tests/test_issue731_declaration_scans_strip_at_the_producer.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import _hdl_code_text  # noqa: E402
import canonical_primitive_synth as CPS  # noqa: E402
import design_one_shot_runner as DOSR  # noqa: E402
import phase1_port_extract as PPX  # noqa: E402
import sparse_fsm_detect as SFD  # noqa: E402


# ─── canonical_primitive_synth._rtl_input_port_widths ────────────────────────
_PHANTOM_PORT_RTL = (
    "// module ghost_top (input [7:0] phantom_port);\n"
    "module real_top (input [3:0] real_port, output q);\n"
    "endmodule\n"
)


def test_a_commented_out_header_contributes_no_input_port_width():
    """PRE-FIX this returned {'phantom_port': 8, 'real_port': 4}.

    The width map feeds `_rtl_shift_poles`, so a port read out of a comment
    becomes a shift POLE the design never declared.
    """
    widths = CPS._rtl_input_port_widths(_PHANTOM_PORT_RTL)
    assert "phantom_port" not in widths, widths
    assert widths.get("real_port") == 4, widths


def test_rtl_with_no_comments_is_unaffected():
    """The blanker is length-preserving, so comment-free RTL is untouched."""
    plain = "module m (input [3:0] a, output q);\nendmodule\n"
    assert CPS._rtl_input_port_widths(plain) == {"a": 4}


# ─── sparse_fsm_detect._module_at ────────────────────────────────────────────
def test_a_block_commented_module_header_does_not_capture_the_enclosing_name():
    """PRE-FIX `_module_at` returned 'ghost_mod' for a `localparam` in
    `real_mod`.

    `_MODULE_RE` is line-anchored, so `//` cannot do this and only a BLOCK
    comment can: it leaves the commented header at the start of its own line.
    """
    text = ("module real_mod;\n"
            "/*\n"
            "module ghost_mod\n"
            "*/\n"
            "localparam X=1;\n")
    assert SFD._module_at(text, text.index("localparam")) == "real_mod"


def test_module_at_offsets_survive_the_strip():
    """`pos` is the CALLER's offset, so the strip must not move any byte.

    This is why `_module_at` uses the length-preserving blanker and not the
    module's own `_strip_comments`, which deletes `/*...*/` down to one space.
    """
    text = "module real_mod;\n/* a */\nlocalparam X=1;\n"
    blanked = _hdl_code_text.strip_hdl_comments_and_strings(text)
    assert len(blanked) == len(text)


# ─── phase1_port_extract._verilog_region_spans ───────────────────────────────
_FENCED_WITH_A_COMMENTED_MODULE = (
    "```verilog\n"
    "/*\n"
    "module ghost_top (input wire phantom);\n"
    "endmodule\n"
    "*/\n"
    "module real_top (input wire clk, output wire tx);\n"
    "endmodule\n"
    "```\n"
)


def test_a_commented_out_module_is_not_a_verilog_region():
    """PRE-FIX this returned THREE spans, one of them the `ghost_top` header.

    No phantom PORT escaped (both consumers strip the region before matching
    declarations), but the SPAN is the #2060 evidence artefact: `source_line`
    quotes the document line a port was read from, and a span cut from a
    comment quotes a line the design never declared.
    """
    doc = _FENCED_WITH_A_COMMENTED_MODULE
    spans = PPX._verilog_region_spans(doc)
    ghost = [(a, b) for a, b in spans
             if doc[a:b].lstrip().startswith("module ghost_top")]
    assert not ghost, f"a commented-out header became a region: {ghost}"
    assert any("module real_top" in doc[a:b] for a, b in spans), spans


def test_the_real_module_region_is_still_found():
    """The population must shrink by the phantom ONLY."""
    doc = ("```verilog\n"
           "module real_top (input wire clk, output wire tx);\n"
           "endmodule\n"
           "```\n")
    spans = PPX._verilog_region_spans(doc)
    assert spans and any("module real_top" in doc[a:b] for a, b in spans)


# ─── design_one_shot_runner._resolve_param_defaults_in_block ─────────────────
# CZBLANK-007. v1.18.26 closed the commented-out-declaration defect here but
# took the SPAN from the match made on the BLANKED copy. For a STRING-valued
# default the blanker turns `"fast"` into spaces, the pattern's `\s*=\s*` eats
# them, and `([^,;)\n]+)` can only back off onto the LAST one -- so the cut
# landed INSIDE the literal and the emitted wrapper carried `"fast"slow"`.
#
# An integer or expression default is untouched by the blanker, which is why
# every case v1.18.26 measured came out clean. Those two are the controls: they
# must keep passing, or the fix has changed something it had no business
# changing.
#
# NOT OVERSTATED: no fixture in this tree RESOLVES a string-valued parameter
# (the derivation compares the current value against RTL identifiers, and a
# quoted value matches none), so this was a LATENT corruption of the emitted
# wrapper rather than one happening on every run.
def test_a_string_valued_default_is_replaced_whole():
    """The one that was wrong: the literal must be replaced, not cut open."""
    out = DOSR._resolve_param_defaults_in_block(
        '  parameter MODE = "fast"\n', {"MODE": {"value": '"slow"'}})
    assert out == '  parameter MODE = "slow"\n', out


def test_control_a_numeric_default_is_unchanged_in_behaviour():
    out = DOSR._resolve_param_defaults_in_block(
        "  parameter WIDTH = 8\n", {"WIDTH": {"value": "16"}})
    assert out == "  parameter WIDTH = 16\n", out


def test_control_an_expression_default_is_unchanged_in_behaviour():
    out = DOSR._resolve_param_defaults_in_block(
        "  parameter DEPTH = 1 << 3\n", {"DEPTH": {"value": "64"}})
    assert out == "  parameter DEPTH = 64\n", out


def test_the_commented_out_declaration_is_still_not_the_one_rewritten():
    """v1.18.26's own property must survive this fix — the whole point of
    choosing the occurrence on the blanked copy."""
    out = DOSR._resolve_param_defaults_in_block(
        "  // parameter VARIANT = 0,   <- kept for reference\n"
        "  parameter VARIANT = 0\n", {"VARIANT": {"value": "1"}})
    assert "parameter VARIANT = 1\n" in out, out
    assert "// parameter VARIANT = 0," in out, out


def test_a_parameter_the_derivation_did_not_resolve_is_untouched():
    """No entry, no edit — byte for byte."""
    block = '  parameter MODE = "fast"\n  parameter WIDTH = 8\n'
    assert DOSR._resolve_param_defaults_in_block(block, {}) == block
