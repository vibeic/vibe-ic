"""Regression: a port whose width the interface line omits is recovered from an
EXPLICIT `reg/wire/logic [hi:lo] <name>` declaration in the prose body.

Negative control: against pre-fix port_parser (no prose recovery) the first test
returns width 1 and FAILS — a test that could not fail proves nothing. The
false-positive tests guard against the recovery firing on legitimate state.

General, chip-AGNOSTIC: the docs below are synthetic Phase-1 prose, not any
benchmark oracle. The rule keys only on generic Verilog grammar + the port name.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import port_parser as p  # noqa: E402


# A generic serial-in shift register doc: the Output-ports line gives q no width,
# but the Implementation body declares it explicitly. This is the exact under-spec
# pattern (interface omits the width the body pins).
_DOC = """
Implement a right shifter.

- input clk
- input d
- output q

Implementation:
The register is defined as reg [7:0] q and initialized to 0. The value of q is
right-shifted by 1 bit: q <= (q >> 1). The MSB q[7] <= d.
"""


def _outs(text):
    return dict(p.parse_ports(text)[1])


def test_prose_declared_width_recovered():
    # port list omits q's width; body says `reg [7:0] q` -> width 8, not 1.
    assert _outs(_DOC).get("q") == 8


def test_explicit_portlist_width_not_overridden():
    # an explicit interface width is authoritative even if the body says otherwise.
    doc = ("- input clk\n"
           "- output [3:0] q\n"
           "Body: reg [7:0] q;\n")
    assert _outs(doc).get("q") == 4


def test_no_prose_decl_leaves_width_one():
    # a genuine 1-bit port with no explicit prose declaration is untouched.
    doc = ("- input clk\n"
           "- output done\n"
           "Body: done goes high for one cycle.\n")
    assert _outs(doc).get("done") == 1


def test_index_usage_does_not_trigger():
    # `q[7]` is an index usage, not a declaration -> must not set width.
    assert p._prose_declared_width("always q[7] <= d;", "q") is None


def test_parametric_range_abstains():
    # a non-numeric `[WIDTH-1:0]` range is left to the solver, not guessed.
    assert p._prose_declared_width("reg [WIDTH-1:0] q;", "q") is None


def test_name_boundary_no_false_match():
    # `reg [7:0] q_r` must not satisfy a lookup for port `q`.
    assert p._prose_declared_width("reg [7:0] q_r;", "q") is None


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([os.path.abspath(__file__), "-q"]))
