"""The five PURE helpers the DFT inout fix rests on, driven directly.

`test_fault_scan_inout_ports.py` reaches them through `fault_scan_chain_insert`,
so the module itself had no direct test and `plugin_full_audit` D1 reported it
as an untested program. That is the right verdict: these are pure functions with
one decision each, and the one that matters — `port_is_connected` — decides
whether a port is REMOVED from a netlist that later ships.

Its bias is the property to protect, not its accuracy. Every way the predicate
can be wrong under-counts the declaration lines it subtracts and therefore
over-reports CONNECTED, which leaves the port in place and reports the honest
failure. The dangerous direction — a connected port read as unconnected and
stripped — needs `decls` OVER-counted, which takes duplicate declaration lines
that are themselves real.

MEASURED ON THE TRACKED CORPUS, both directions on real designs:

    caravel_user_project/.../user_project_wrapper_synth.v   analog_io    strippable
    caravel_user_project/.../netlist.v                      analog_io    strippable
    phase1_parity/lpc/.../netlist.v          clkrun_n, serirq   left in place

The `lpc` row is the load-bearing one: it is the case where stripping would ship
a wrong netlist, and the predicate refuses. Both are pinned below against the
real files when they are present.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
_REPO = _PROGRAMS.parents[3]


def _load():
    spec = importlib.util.spec_from_file_location(
        "_dft_netlist_ports", _PROGRAMS / "_dft_netlist_ports.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_dft_netlist_ports"] = mod
    spec.loader.exec_module(mod)
    return mod


M = _load()

_UNCONNECTED = """\
module top (clk, analog_io, q);
  input clk;
  inout [28:0] analog_io;
  output q;
  wire q;
endmodule
"""

_CONNECTED = """\
module top (clk, analog_io, q);
  input clk;
  inout [28:0] analog_io;
  output q;
  BUF u (.A(analog_io[0]), .Z(q));
endmodule
"""


# ── find ─────────────────────────────────────────────────────────────────────
def test_find_returns_the_exact_declaration_line():
    """The declaration is what gets restored byte-for-byte, so it is the thing
    that has to be captured, not just the name."""
    got = M.find_inout_ports(_UNCONNECTED)
    assert list(got) == ["analog_io"]
    assert got["analog_io"].strip() == "inout [28:0] analog_io;"


def test_find_ignores_input_and_output():
    assert M.find_inout_ports(
        "module m (a, b);\n  input a;\n  output b;\nendmodule\n") == {}


# ── connected: the decision that can ship a wrong netlist ────────────────────
def test_an_unconnected_inout_is_strippable():
    assert M.port_is_connected(_UNCONNECTED, "analog_io") is False


def test_a_connected_inout_is_not_strippable():
    """The load-bearing direction. A false 'unconnected' here removes a real net
    from a netlist that goes on to be shipped."""
    assert M.port_is_connected(_CONNECTED, "analog_io") is True


def test_a_bit_select_counts_as_a_use():
    """`analog_io[0]` is the only form the connection takes in the corpus case
    that motivated this — a substring match would work, a token match that
    stopped at `[` would not."""
    src = _UNCONNECTED.replace("  wire q;\n",
                               "  BUF u (.A(analog_io[3]), .Z(q));\n")
    assert M.port_is_connected(src, "analog_io") is True


def test_a_longer_name_sharing_the_prefix_is_not_a_use():
    """`analog_io_extra` must not make `analog_io` look connected — the whole
    point of the identifier boundaries."""
    src = _UNCONNECTED.replace(
        "  wire q;\n", "  wire analog_io_extra;\n  BUF u (.A(clk), .Z(q));\n")
    assert M.port_is_connected(src, "analog_io") is False


@pytest.mark.parametrize("variant,why", [
    ("  inout [28:0] analog_io; // pads\n", "declaration with a trailing comment"),
    ("  // analog_io is an unbonded pass-through\n"
     "  inout [28:0] analog_io;\n", "the name mentioned in a comment"),
])
def test_comment_shapes_fail_towards_keeping_the_port(variant, why):
    """Both read as CONNECTED, so the port is kept and the honest failure is
    reported rather than a wrong netlist produced.

    Pinned as the CURRENT behaviour and its DIRECTION, not as desirable: the
    fix silently does not apply on such a netlist. Measured over the tracked
    netlists, 0 of the inout declarations carry a trailing comment, so this
    costs nothing today. If someone teaches the helpers to strip comments,
    these flip to False and that is an improvement — this test then needs
    re-stating, which is the point of writing it down.
    """
    src = _UNCONNECTED.replace("  inout [28:0] analog_io;\n", variant)
    assert M.port_is_connected(src, "analog_io") is True, why


# ── position ─────────────────────────────────────────────────────────────────
def test_successor_is_the_next_name_in_the_header():
    assert M.port_list_successor(_UNCONNECTED, "analog_io") == "q"


def test_successor_is_none_for_the_last_port():
    assert M.port_list_successor(_UNCONNECTED, "q") is None


def test_successor_is_none_for_a_name_that_is_not_a_port():
    assert M.port_list_successor(_UNCONNECTED, "no_such") is None


# ── strip / restore round-trip ───────────────────────────────────────────────
def test_strip_then_restore_preserves_the_port_LIST_position_verbatim():
    """What actually round-trips, stated exactly — "byte-for-byte" overstates it.

    The PORT-LIST position is restored precisely, and the declaration text is
    re-added verbatim. The declaration LINE moves: `restore_inout_ports` puts it
    immediately after the module header rather than where it was. That is what
    the function's own docstring says it does, and it is semantically lossless —
    Verilog does not order port declarations — but a reader told "byte-for-byte"
    would be surprised by a diff, so it is pinned here as the real contract.
    """
    decls = M.find_inout_ports(_UNCONNECTED)
    succ = {n: M.port_list_successor(_UNCONNECTED, n) for n in decls}
    stripped = M.strip_inout_ports(_UNCONNECTED, list(decls))
    assert "analog_io" not in stripped
    back = M.restore_inout_ports(stripped, decls, succ)

    # the header is exact
    assert "module top (clk, analog_io, q);" in back
    # the declaration text is exact
    assert "  inout [28:0] analog_io;" in back
    # same lines, in a different order -> nothing gained or lost
    assert sorted(back.split("\n")) == sorted(_UNCONNECTED.split("\n"))
    # and it is NOT byte-identical, which is the part worth knowing
    assert back != _UNCONNECTED


def test_restore_puts_the_port_back_before_its_original_successor():
    """The position that MATTERS: a fault tool reorders nothing, but the
    restored header must name the ports in their original order or every
    positional instantiation of this module breaks."""
    src = ("module top (a, mid, b);\n  input a;\n  inout mid;\n"
           "  output b;\nendmodule\n")
    decls = M.find_inout_ports(src)
    succ = {n: M.port_list_successor(src, n) for n in decls}
    back = M.restore_inout_ports(M.strip_inout_ports(src, list(decls)),
                                 decls, succ)
    assert "module top (a, mid, b);" in back


def test_restore_appends_when_the_port_was_last():
    """No successor to anchor on — it goes before the closing paren rather than
    silently vanishing."""
    src = ("module top (a, last);\n  input a;\n  inout last;\nendmodule\n")
    decls = M.find_inout_ports(src)
    succ = {n: M.port_list_successor(src, n) for n in decls}
    back = M.restore_inout_ports(M.strip_inout_ports(src, list(decls)),
                                 decls, succ)
    assert "last" in back
    assert "  inout last;" in back


def test_strip_removes_it_from_the_header_and_the_declaration():
    stripped = M.strip_inout_ports(_UNCONNECTED, ["analog_io"])
    assert "inout" not in stripped
    assert "module top (clk, q);" in stripped.replace("  ", " ")


# ── the real corpus, both directions ─────────────────────────────────────────
@pytest.mark.parametrize("rel,port,expect_connected", [
    ("benchmark-data/ic/caravel_user_project/phase2/stage2/synth/"
     "user_project_wrapper_synth.v", "analog_io", False),
    ("benchmark-data/evaluation/phase1_parity/lpc/phase2/stage2/synth/"
     "netlist.v", "clkrun_n", True),
])
def test_the_predicate_on_real_netlists(rel, port, expect_connected):
    """Fixtures prove the logic; these prove it on the artefacts the gate runs
    against. Skipped rather than assumed when the corpus is not checked out —
    "I could not look" and "I looked and it is fine" are different claims.
    """
    f = _REPO / rel
    if not f.is_file():
        pytest.skip(f"corpus file absent: {rel}")
    text = f.read_text(errors="replace")
    assert port in M.find_inout_ports(text), f"{port} is not an inout in {rel}"
    assert M.port_is_connected(text, port) is expect_connected
