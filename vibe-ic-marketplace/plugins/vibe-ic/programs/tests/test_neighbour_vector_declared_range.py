#!/usr/bin/env python3
"""comb_advanced `_neighbour_vector` must emit each output at its DECLARED port
range, not a normalized full-width [N-1:0].

The VerilogEval neighbour-vector prompt has two twins:
  - full-width twin: declares out_both/out_any/out_different all [N-1:0]
    (boundary don't-care bit present, driven to 0);
  - boundary-omitted twin: declares out_both[N-2:0] and out_any[N-1:1]
    (the edge don't-care bit is OUTSIDE the port range).

Emitting full-width [N-1:0] for an out_any[N-1:1] port mis-aligns: the body's
LSB 0-bit lands at the hidden TB's bit 1 (the TB connects an [N-1:1] net LSB-
first), corrupting every bit -> functional_mismatch (Prob092/094 on VE-Human).
This pins the declared-range-preserving emit for BOTH twins.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import comb_advanced_synth as cav  # noqa: E402

_BODY = (
    "(1) out_both[i] = in[i] and its neighbour to the LEFT (higher index). "
    "out_both[98] uses in[98] and in[99]; out_both[99] is obvious so we don't "
    "need it.\n"
    "(2) out_any[i] = in[i] OR its neighbour to the RIGHT (lower index). "
    "out_any[0] don't need.\n"
    "(3) out_different[i] = in[i] XOR neighbour to the left, WRAP around.\n"
)


def _header_twin():
    return (
        "module TopModule (\n"
        "  input [99:0] in,\n"
        "  output [98:0] out_both,\n"
        "  output [99:1] out_any,\n"
        "  output [99:0] out_different\n"
        ");\n" + _BODY
    )


def _bullet_twin():
    return (
        "module TopModule (input [99:0] in, output [99:0] out_both, "
        "output [99:0] out_any, output [99:0] out_different);\n"
        " - output out_both (100 bits)\n - output out_any (100 bits)\n" + _BODY
    )


def _decl(rtl, name):
    m = re.search(r'output\s+(?:\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*)?' + name, rtl)
    assert m, f"no output decl for {name} in:\n{rtl}"
    return (int(m.group(1)), int(m.group(2))) if m.group(1) else ("scalar", "scalar")


def test_boundary_omitted_twin_declares_offset_ranges():
    ins = [("in", 100)]
    outs = [("out_both", 99), ("out_any", 99), ("out_different", 100)]
    rtl = cav._neighbour_vector(_header_twin(), ins, outs, "TopModule")
    assert rtl is not None
    assert _decl(rtl, "out_both") == (98, 0)        # [98:0], not [99:0]
    assert _decl(rtl, "out_any") == (99, 1)         # [99:1], not [99:0]
    assert _decl(rtl, "out_different") == (99, 0)
    # out_any body must NOT prepend the boundary 0 (it would land at bit 1)
    assert "1'b0 }" not in rtl.split("out_any")[1].split(";")[0]


def test_full_width_twin_keeps_full_range_and_boundary():
    ins = [("in", 100)]
    outs = [("out_both", 100), ("out_any", 100), ("out_different", 100)]
    rtl = cav._neighbour_vector(_bullet_twin(), ins, outs, "TopModule")
    assert rtl is not None
    assert _decl(rtl, "out_both") == (99, 0)
    assert _decl(rtl, "out_any") == (99, 0)
    # full-width keeps the boundary 0 bits
    assert "1'b0" in rtl
