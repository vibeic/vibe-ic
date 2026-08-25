#!/usr/bin/env python3
r"""Tests for arith_ext_synth — the N-bit adder with a carry-in and a SEPARATE
carry-out output.

FUNCTION, NOT TEXT. The positive arms compile the emitted RTL with iverilog,
sweep the DUT EXHAUSTIVELY over a 4-bit interface (16 x 16 x 2 = 512 vectors),
and compare every (sum, cout) against Python's own `a + b + cin`. The oracle is
outside the emitter and outside Verilog, so an emitter that dropped the carry-in,
swapped the concatenation order or truncated the carry goes red on real numbers,
not on a changed string.

§4.05 NO-LEAK is the other half, and the load-bearing half: a wrong adder is far
worse than an honest skip, so each negative arm states one structural or prose
reason this FORM is not the one described and requires None.
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_PROG = Path(__file__).resolve().parents[1]
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import arith_ext_synth as A  # noqa: E402

_HAVE_TOOLS = bool(shutil.which("iverilog") and shutil.which("vvp"))


def _prompt(width=8, name="adder_8bit", extra=""):
    hi = width - 1
    return (f"Please act as a professional verilog designer.\n\n"
            f"Implement a {width}-bit adder built from multiple full adders.\n\n"
            f"Module name: {name}\n\n"
            f"Input ports:\n"
            f"    a [{hi}:0]: {width}-bit first operand.\n"
            f"    b [{hi}:0]: {width}-bit second operand.\n"
            f"    cin: 1-bit carry in.\n"
            f"Output ports:\n"
            f"    sum [{hi}:0]: {width}-bit sum.\n"
            f"    cout: 1-bit carry out.\n" + extra)


def _sim_sweep(rtl, top, width, tmp_path):
    """Compile `rtl` and dump (a, b, cin, sum, cout) for EVERY input vector."""
    hi = width - 1
    tb = (f"module tb;\n"
          f"  reg [{hi}:0] a, b; reg cin;\n"
          f"  wire [{hi}:0] sum; wire cout;\n"
          f"  integer i, j, k;\n"
          f"  {top} dut(.a(a), .b(b), .cin(cin), .sum(sum), .cout(cout));\n"
          f"  initial begin\n"
          f"    for (i = 0; i < {1 << width}; i = i + 1)\n"
          f"      for (j = 0; j < {1 << width}; j = j + 1)\n"
          f"        for (k = 0; k < 2; k = k + 1) begin\n"
          f"          a = i[{hi}:0]; b = j[{hi}:0]; cin = k[0];\n"
          f"          #1 $display(\"V %0d %0d %0d %0d %0d\", a, b, cin, sum, cout);\n"
          f"        end\n"
          f"    $finish;\n"
          f"  end\n"
          f"endmodule\n")
    (tmp_path / "dut.v").write_text(rtl)
    (tmp_path / "tb.v").write_text(tb)
    exe = tmp_path / "sim.out"
    cp = subprocess.run(["iverilog", "-g2012", "-o", str(exe),
                         str(tmp_path / "dut.v"), str(tmp_path / "tb.v")],
                        capture_output=True, text=True)
    assert cp.returncode == 0, cp.stderr
    cp = subprocess.run(["vvp", str(exe)], capture_output=True, text=True,
                        cwd=str(tmp_path))
    assert cp.returncode == 0, cp.stderr
    rows = [tuple(int(x) for x in m.groups())
            for m in re.finditer(r"^V (\d+) (\d+) (\d+) (\d+) (\d+)$",
                                 cp.stdout, re.M)]
    return rows


@pytest.mark.skipif(not _HAVE_TOOLS, reason="iverilog/vvp not installed on this host")
def test_emitted_adder_computes_a_plus_b_plus_cin_over_every_vector(tmp_path):
    width = 4
    rtl = A.synth(_prompt(width, "adder_4bit"),
                  [("a", width), ("b", width), ("cin", 1)],
                  [("sum", width), ("cout", 1)], "adder_4bit")
    assert rtl is not None, "the solver must fire on the separate-carry-out FORM"
    rows = _sim_sweep(rtl, "adder_4bit", width, tmp_path)
    assert len(rows) == (1 << width) * (1 << width) * 2
    mask = (1 << width) - 1
    for a, b, cin, sum_, cout in rows:
        total = a + b + cin
        assert (sum_, cout) == (total & mask, total >> width), (
            f"a={a} b={b} cin={cin} -> sum={sum_} cout={cout}, "
            f"expected {total & mask}/{total >> width}")


@pytest.mark.skipif(not _HAVE_TOOLS, reason="iverilog/vvp not installed on this host")
def test_the_carry_in_is_actually_summed(tmp_path):
    """The distinguishing input of this FORM. An emitter that ignored cin would
    still pass a cin=0 sweep."""
    width = 4
    rtl = A.synth(_prompt(width, "adder_4bit"),
                  [("a", width), ("b", width), ("cin", 1)],
                  [("sum", width), ("cout", 1)], "adder_4bit")
    rows = _sim_sweep(rtl, "adder_4bit", width, tmp_path)
    by_key = {(a, b, cin): (s, c) for a, b, cin, s, c in rows}
    assert by_key[(3, 4, 0)] == (7, 0)
    assert by_key[(3, 4, 1)] == (8, 0)
    assert by_key[(15, 0, 1)] == (0, 1)     # carry-in alone produces the carry-out


def test_names_come_from_the_declared_interface_not_from_a_design_name():
    """chip-AGNOSTIC: nothing is keyed on `adder_8bit`. Rename every port and the
    top and the emitted module must bind the new names."""
    text = _prompt(8, "some_other_block").replace("a [7:0]", "x [7:0]") \
        .replace("b [7:0]", "y [7:0]").replace("cin:", "carry_in:") \
        .replace("sum [7:0]", "result [7:0]").replace("cout:", "Co:")
    rtl = A.synth(text, [("x", 8), ("y", 8), ("carry_in", 1)],
                  [("result", 8), ("Co", 1)], "some_other_block")
    assert rtl is not None
    assert "module some_other_block (" in rtl
    assert "assign {Co, result} = x + y + carry_in;" in rtl


def test_an_absent_carry_in_is_allowed_and_not_invented():
    rtl = A.synth(_prompt(8).replace("    cin: 1-bit carry in.\n", ""),
                  [("a", 8), ("b", 8)], [("sum", 8), ("cout", 1)], "TopModule")
    assert rtl is not None
    assert "assign {cout, sum} = a + b;" in rtl
    assert "cin" not in rtl


# --------------------------------------------------------------------------- #
# §4.05 — every reason this is NOT the described FORM must produce a SKIP
# --------------------------------------------------------------------------- #
_SKIPS = [
    ("packed carry (no separate carry-out output)",
     _prompt(8), [("a", 8), ("b", 8), ("cin", 1)], [("sum", 9)]),
    ("two data operands of different widths",
     _prompt(8), [("a", 8), ("b", 4), ("cin", 1)], [("sum", 8), ("cout", 1)]),
    ("a third data operand",
     _prompt(8), [("a", 8), ("b", 8), ("c", 8), ("cin", 1)],
     [("sum", 8), ("cout", 1)]),
    ("two carry-in candidates",
     _prompt(8), [("a", 8), ("b", 8), ("cin", 1), ("ci", 1)],
     [("sum", 8), ("cout", 1)]),
    ("a sum narrower than the operands",
     _prompt(8), [("a", 8), ("b", 8), ("cin", 1)], [("sum", 4), ("cout", 1)]),
    ("scalar operands (the half/full-adder FORM another solver owns)",
     _prompt(8), [("a", 1), ("b", 1), ("cin", 1)], [("sum", 1), ("cout", 1)]),
    ("no adder cue in the prose at all",
     "A combinational block with two operands and a flag output.\n",
     [("a", 8), ("b", 8), ("cin", 1)], [("sum", 8), ("cout", 1)]),
    ("a sequential design (positive edge of the clock)",
     _prompt(8, extra="\nRegister the result on the positive edge of the clock.\n"),
     [("a", 8), ("b", 8), ("cin", 1)], [("sum", 8), ("cout", 1)]),
    ("a signed two's-complement overflow flag (a different function)",
     _prompt(8, extra="\nAlso report signed overflow in two's-complement.\n"),
     [("a", 8), ("b", 8), ("cin", 1)], [("sum", 8), ("cout", 1)]),
    ("BCD arithmetic",
     _prompt(8, extra="\nThe operands are BCD digits.\n"),
     [("a", 8), ("b", 8), ("cin", 1)], [("sum", 8), ("cout", 1)]),
    ("add/subtract by control (a borrow appears)",
     _prompt(8, extra="\nIt must also subtract and report a borrow.\n"),
     [("a", 8), ("b", 8), ("cin", 1)], [("sum", 8), ("cout", 1)]),
    ("a multiplier",
     _prompt(8, extra="\nThe block multiplies the operands.\n"),
     [("a", 8), ("b", 8), ("cin", 1)], [("sum", 8), ("cout", 1)]),
    ("an accumulator",
     _prompt(8, extra="\nThe block accumulates across calls.\n"),
     [("a", 8), ("b", 8), ("cin", 1)], [("sum", 8), ("cout", 1)]),
]


@pytest.mark.parametrize("why,text,ins,outs", _SKIPS,
                         ids=[c[0] for c in _SKIPS])
def test_out_of_form_specs_skip_rather_than_emit_a_wrong_adder(why, text, ins, outs):
    assert A.synth(text, ins, outs, "TopModule") is None, why


def test_empty_inputs_are_a_skip_not_a_crash():
    assert A.synth("", [("a", 8)], [("sum", 8)], "TopModule") is None
    assert A.synth(_prompt(8), [], [], "TopModule") is None
