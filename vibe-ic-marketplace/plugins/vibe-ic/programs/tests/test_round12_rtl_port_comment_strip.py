#!/usr/bin/env python3
"""Regression test for CLUSTER R12C2 (cvdp_copilot_flop_0002).

BUG: `_specrtl_common.parse_rtl_ports` did NOT strip Verilog comments before the
`_PORT_DECL` regex ran. An ANSI module header with inline port comments
(`// Clock input`, `// J input of the JK flip-flop`, `// Q output`) made the regex
match the comment words `input`/`output` and harvest the following comment token as
a phantom port, while consuming the next REAL `input`/`output` keyword into its name
group — INJECTING phantom ports (`of`, `input`, `output`) and DROPPING real ports
(`i_rst_b`, `o_Q_b`). A dropped reset port => `_rtl_reset_ports()==[]` =>
spec_coverage_check reset coverage falls back to the fixed `['reset','rst','por']`
token list which never matches the TB's `i_rst_b` => false reset-UNCOVERED hard-block
under --strict (rc=1) on correct, spec-faithful RTL.

FIX: in `parse_rtl_ports`, apply the existing `strip_comments(region)` BEFORE
`_strip_subprograms(region)`. chip-AGNOSTIC (Verilog comment grammar only).

This test imports the program from a path given by env var VIBE_PROGRAMS so it runs
in CI; fixtures are inline (self-contained).
"""
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

# ----------------------------------------------------------------------------
# Locate the programs dir under test (env override for CI, repo-relative default)
# ----------------------------------------------------------------------------
_DEFAULT_PROGRAMS = __import__("pathlib").Path(__file__).resolve().parent.parent
PROGRAMS = Path(os.environ.get("VIBE_PROGRAMS", _DEFAULT_PROGRAMS)).resolve()
COMMON = PROGRAMS / "_specrtl_common.py"
COVERAGE = PROGRAMS / "spec_coverage_check.py"


def _load_common():
    if str(PROGRAMS) not in sys.path:
        sys.path.insert(0, str(PROGRAMS))
    spec = importlib.util.spec_from_file_location("_specrtl_common", str(COMMON))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_specrtl_common"] = mod  # dataclass needs the module registered
    spec.loader.exec_module(mod)
    return mod


# ----------------------------------------------------------------------------
# Inline fixtures
# ----------------------------------------------------------------------------
# The affected case: ANSI header with inline port comments containing the words
# `input` / `output` and the phantom-trigger phrase `... input of the ...`.
RTL_COMMENTED = """\
module JK_flipflop(
    input i_J,       // J input of the JK flip-flop
    input i_K,       // K input of the JK flip-flop
    input i_clk,     // Clock input
    input i_rst_b,   // Asynchronous reset, active low
    output reg o_Q,  // Q output
    output reg o_Q_b // Inverted Q output
);
    always @(posedge i_clk or negedge i_rst_b)
        if (!i_rst_b) begin o_Q <= 1'b0; o_Q_b <= 1'b1; end
        else begin o_Q <= i_J; o_Q_b <= ~i_J; end
endmodule
"""

REAL_PORTS = {"i_J", "i_K", "i_clk", "i_rst_b", "o_Q", "o_Q_b"}

SPEC = """\
# JK Flip-Flop
Asynchronous active-low reset i_rst_b. When i_rst_b is low, o_Q is forced low and
o_Q_b high, regardless of clock. Otherwise the JK flip-flop updates on the rising
edge of i_clk.
"""

# A TB that faithfully drives the real reset port i_rst_b (the affected POSITIVE).
TB_COVERS_RESET = """\
module tb;
  reg i_J, i_K, i_clk, i_rst_b; wire o_Q, o_Q_b;
  JK_flipflop dut(.i_J(i_J), .i_K(i_K), .i_clk(i_clk), .i_rst_b(i_rst_b),
                  .o_Q(o_Q), .o_Q_b(o_Q_b));
  always #5 i_clk = ~i_clk;
  initial begin
    i_clk=0; i_J=0; i_K=0; i_rst_b=0; #7 i_rst_b=1; #20 $finish;
  end
endmodule
"""

# §4.05 NO-LEAK negative: same comment-bearing-header class of RTL, but a TB that
# GENUINELY never references the reset port (positional connect, reset left
# unconnected). A real coverage defect of the same class — must STILL hard-block.
RTL_NOLEAK = """\
module dff_rst(
    input  i_d,      // data input
    input  i_clk,    // Clock input
    input  i_rst_n,  // Asynchronous reset, active low
    output reg o_q   // Q output
);
    always @(posedge i_clk or negedge i_rst_n)
        if (!i_rst_n) o_q <= 1'b0;
        else          o_q <= i_d;
endmodule
"""

SPEC_NOLEAK = """\
# DFF with async reset
The flip-flop has an asynchronous active-low reset i_rst_n. When i_rst_n is low,
o_q is forced to 0 regardless of clock. Otherwise o_q follows i_d on the rising edge.
"""

TB_NO_RESET = """\
module tb;
  reg dd, ck; wire qq;
  dff_rst dut(dd, ck, , qq);
  always #5 ck=~ck;
  initial begin ck=0; dd=0; #10 dd=1; #10 $finish; end
endmodule
"""


# ----------------------------------------------------------------------------
# Unit-level: the parser must not inject phantoms / drop real ports
# ----------------------------------------------------------------------------
def test_parse_rtl_ports_no_phantom_no_drop():
    """POSITIVE (parser): comment-bearing ANSI header parses to EXACTLY the real
    ports — no phantom (`of`/`input`/`output`) and none dropped (`i_rst_b`)."""
    m = _load_common()
    _, ports = m.parse_rtl_ports(RTL_COMMENTED, None)
    names = {p.name for p in ports}
    phantom = names - REAL_PORTS
    dropped = REAL_PORTS - names
    assert not phantom, f"phantom ports leaked from comments: {sorted(phantom)}"
    assert not dropped, f"real ports dropped: {sorted(dropped)}"
    assert names == REAL_PORTS


def test_reset_port_recovered_from_commented_header():
    """The real reset port i_rst_b must be recoverable from the parsed set
    (it was DROPPED pre-fix, collapsing reset coverage to the fixed fallback)."""
    m = _load_common()
    _, ports = m.parse_rtl_ports(RTL_COMMENTED, None)
    assert any(p.name == "i_rst_b" for p in ports)


# ----------------------------------------------------------------------------
# End-to-end gate: POSITIVE passes, §4.05 NEGATIVE still hard-blocks
# ----------------------------------------------------------------------------
def _run_gate(tmp_path, spec, rtl, tb):
    sp = tmp_path / "spec.md"; sp.write_text(spec)
    rp = tmp_path / "rtl.sv"; rp.write_text(rtl)
    tp = tmp_path / "tb.sv"; tp.write_text(tb)
    r = subprocess.run(
        [sys.executable, str(COVERAGE), "--spec", str(sp), "--rtl", str(rp),
         "--tb", str(tp), "--strict"],
        capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def test_coverage_gate_positive_affected_passes(tmp_path):
    """POSITIVE: the affected case (comment-bearing header + TB that drives the
    real reset) must PASS the strict coverage gate (rc 0) after the fix."""
    rc, out = _run_gate(tmp_path, SPEC, RTL_COMMENTED, TB_COVERS_RESET)
    assert rc == 0, f"affected case should pass but rc={rc}\n{out}"


def test_coverage_gate_noleak_negative_still_blocks(tmp_path):
    """§4.05 NO-LEAK: a genuine reset-coverage defect of the same class (TB never
    references the reset port) must STILL hard-block under --strict (rc 1).
    The fix must not become a blanket pass."""
    rc, out = _run_gate(tmp_path, SPEC_NOLEAK, RTL_NOLEAK, TB_NO_RESET)
    assert rc == 1, f"genuine reset-uncovered defect must block but rc={rc}\n{out}"
    assert "reset" in out.lower()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
