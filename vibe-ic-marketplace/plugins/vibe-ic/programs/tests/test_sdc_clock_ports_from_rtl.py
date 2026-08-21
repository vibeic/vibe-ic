"""`sdc_gen` derives clock ports from edge-sensitive event controls — unguarded.

`d9574e997` replaced a NAME heuristic (`clk`/`clock`) with a property of the
language: a signal appearing after `posedge`/`negedge` in an event control IS a
clock. That is the right fix — the same "stop using a text proxy for the
property" move this repo keeps making — and it shipped with no test.

Measured by mutation before writing this file: stubbing `_clock_ports_from_rtl`
to `return []` — which switches the entire fix off — leaves all 21 sdc-named
test files GREEN. So the fix could be reverted, or quietly broken by an
unrelated edit, with the suite silent.

That is the same shape as the v1.8.48 -> v1.8.93 ATPG episode recorded in
`dc94f9421`: a commit about something else deleted 166 lines, nine tests went
red and stayed red because nobody read them. Here there were no tests to go red
at all, which is the quieter version of the same failure.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "sdc_gen", _PROGRAMS / "sdc_gen.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["sdc_gen"] = mod
    spec.loader.exec_module(mod)
    return mod


S = _load()


def _write(tmp_path, name, text):
    f = tmp_path / name
    f.write_text(text, encoding="utf-8")
    return f


UNCONVENTIONAL = """\
module conv(input wire CK4, input wire CK5, input wire rst_n,
            output reg [7:0] o);
  always @(posedge CK4 or negedge rst_n) begin
    if (!rst_n) o <= 8'd0;
    else        o <= o + 8'd1;
  end
  always @(negedge CK5) begin
    o <= o;
  end
endmodule
"""

#: The same design with the reset written FIRST in the event control. Legal,
#: common, and the case that broke: the caller takes `_derived[0]`, so a
#: position-based rule picks the reset as the clock here.
RESET_FIRST = """\
module conv(input wire CK4, input wire rst_n, output reg [7:0] o);
  always @(negedge rst_n or posedge CK4) begin
    if (!rst_n) o <= 8'd0;
    else        o <= o + 8'd1;
  end
endmodule
"""

#: Active-high async reset, also written first.
RESET_FIRST_ACTIVE_HIGH = """\
module conv(input wire CK4, input wire rst, output reg [7:0] o);
  always @(posedge rst or posedge CK4) begin
    if (rst) o <= 8'd0;
    else     o <= o + 8'd1;
  end
endmodule
"""

#: A legitimate falling-edge clock. `negedge` must not by itself mean reset.
NEGEDGE_CLOCK = """\
module n(input wire CK4, output reg q);
  always @(negedge CK4) q <= ~q;
endmodule
"""

CONVENTIONAL = """\
module conv(input wire clk, input wire rst_n, output reg q);
  always @(posedge clk) q <= ~q;
endmodule
"""

COMBINATIONAL = """\
module comb(input wire a, input wire b, output wire y);
  assign y = a & b;
endmodule
"""


def test_a_clock_not_named_clk_is_found(tmp_path):
    """The case the fix exists for.

    A design whose clocks are CK4/CK5 has no port matching `clk`, the old
    selection fell through to a bare "clk" literal, that port does not exist,
    and the emitted SDC was vacuous — no create_clock, so STA had no clock.
    """
    f = _write(tmp_path, "conv.v", UNCONVENTIONAL)
    got = S._clock_ports_from_rtl([f], {"CK4", "CK5", "rst_n", "o"})
    assert set(got) == {"CK4", "CK5"}, got


def test_the_conventional_name_still_works(tmp_path):
    """The accept case. Without it, a function returning [] passes the test
    above only if that test is the sole assertion — this one makes an
    always-empty implementation fail."""
    f = _write(tmp_path, "c.v", CONVENTIONAL)
    got = S._clock_ports_from_rtl([f], {"clk", "rst_n", "q"})
    assert set(got) == {"clk"}, got


def test_a_reset_in_the_event_control_is_not_a_clock(tmp_path):
    """`negedge rst_n` shares an event control with `posedge CK4`."""
    f = _write(tmp_path, "conv.v", UNCONVENTIONAL)
    got = S._clock_ports_from_rtl([f], {"CK4", "CK5", "rst_n", "o"})
    assert "rst_n" not in got, got


def test_reset_written_first_is_still_not_the_clock(tmp_path):
    """The case that was broken, and the reason position cannot decide it.

    `always @(negedge rst_n or posedge CK4)` is legal and common. The caller
    uses `_derived[0]`, so with a position-based rule the SDC got a
    create_clock on the RESET — worse than the vacuous SDC this derivation
    exists to prevent.
    """
    f = _write(tmp_path, "r.v", RESET_FIRST)
    got = S._clock_ports_from_rtl([f], {"CK4", "rst_n", "o"})
    assert got and got[0] == "CK4", got
    assert "rst_n" not in got, got


def test_active_high_reset_written_first_is_not_the_clock(tmp_path):
    """`posedge rst` — so `negedge` cannot be the discriminator either."""
    f = _write(tmp_path, "r.v", RESET_FIRST_ACTIVE_HIGH)
    got = S._clock_ports_from_rtl([f], {"CK4", "rst", "o"})
    assert got and got[0] == "CK4", got
    assert "rst" not in got, got


def test_a_falling_edge_clock_is_still_a_clock(tmp_path):
    """The accept case for the reset rule.

    A rule that treated every `negedge` as a reset would drop the clock of a
    design that legitimately clocks on the falling edge, turning a wrong clock
    into no clock at all.
    """
    f = _write(tmp_path, "n.v", NEGEDGE_CLOCK)
    assert S._clock_ports_from_rtl([f], {"CK4", "q"}) == ["CK4"]


def test_a_single_edge_block_that_tests_its_own_clock_keeps_it(tmp_path):
    """The `len(edges) < 2` guard, pinned.

    A block with ONE edge has no reset to identify — the single signal there is
    the clock, whatever the body happens to test. Gating on it is not
    decoration: without the guard, a body that reads its own clock (a gated or
    self-sampling construct) makes the rule classify the clock as a reset and
    the design ends up with no clock at all.

    Found by mutation: removing the guard left every other test in this file
    green, so this fixture is the only thing holding it.
    """
    src = """\
module m(input wire CK4, output reg q);
  always @(posedge CK4) begin
    if (CK4) q <= 1'b0;
    else     q <= ~q;
  end
endmodule
"""
    f = _write(tmp_path, "m.v", src)
    assert S._clock_ports_from_rtl([f], {"CK4", "q"}) == ["CK4"]


def test_purely_combinational_rtl_yields_no_clock(tmp_path):
    """No edge-sensitive control means no clock — and no invented one."""
    f = _write(tmp_path, "comb.v", COMBINATIONAL)
    assert S._clock_ports_from_rtl([f], {"a", "b", "y"}) == []


def test_a_clock_absent_from_the_port_surface_is_dropped(tmp_path):
    """Intersection with the synthesizable surface is load-bearing.

    An internally generated clock is edge-sensitive but is NOT a port, and
    emitting `get_ports` for it produces an SDC that refers to something that
    does not exist — the same vacuity, one step further along.
    """
    src = """\
module g(input wire src_clk, output reg q);
  reg div;
  always @(posedge src_clk) div <= ~div;
  always @(posedge div)     q   <= ~q;
endmodule
"""
    f = _write(tmp_path, "g.v", src)
    got = S._clock_ports_from_rtl([f], {"src_clk", "q"})
    assert set(got) == {"src_clk"}, got
    assert "div" not in got, got
