#!/usr/bin/env python3
"""A comment declared nothing, denied nothing, and decided the compile order.

`package_first_order` orders sources so a package is compiled before the
package that imports it, because `verilator --binary` is single-pass. It found
declarations and references by regex over the raw file text, so a COMMENT
counted as both.

MEASURED on this tree, 2026-09-04, plugin v1.17.12:

    x.sv   package pkg_x;
             // historical note: this used to read pkg_y::WIDTH
           endpackage
    y.sv   package pkg_y;
             int w = pkg_x::w;
           endpackage

    package_first_order([y.sv, x.sv]) -> ['y.sv', 'x.sv']
    the same call with that ONE comment line removed -> ['x.sv', 'y.sv']

The comment made x.sv appear to depend on y.sv, which closed a cycle, which
dropped both files into the `cycle: keep them` fallback -- and that fallback
preserves the GIVEN order, so the answer became whatever order the caller
happened to pass. `verilator --binary` cannot compile that in one pass.

WHY THE STRIPPER IS LOCAL AND STRING-AWARE, and this is the load-bearing half.
Three comment strippers already exist in this tree (`arith_ss_corner_risk_check`,
`cdc_async_input_check`, `clock_domain_reg_crossing_check`) and all three treat
`//` inside a string literal as the start of a comment. Reusing one would blank

    $display("a//b", pkg_x::VAL);

from the `//` onward and LOSE a real dependency. Trading a wrong order for a
missing edge is not a fix, so `_hdl_code_only` tracks the string state, and the
third test below is what stops that trade from being made later.

Chip-AGNOSTIC: SystemVerilog `package X;` / `X::` grammar only; no IC, vendor,
SKU or process appears here.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import testbench_gen as tb                                      # noqa: E402


def _order(tmp_path, files, given):
    for name, text in files.items():
        (tmp_path / name).write_text(text)
    return [p.name for p in
            tb.package_first_order([tmp_path / g for g in given])]


# --------------------------------------------------------------------------- #
# The defect
# --------------------------------------------------------------------------- #
def test_a_comment_naming_a_package_does_not_create_a_dependency(tmp_path):
    """The measurement above, driven. One comment line is the whole diff
    between the two calls, so nothing else can be producing the change."""
    files = {
        "x.sv": ("package pkg_x;\n"
                 "  // historical note: this used to read pkg_y::WIDTH\n"
                 "  int w = 8;\n"
                 "endpackage\n"),
        "y.sv": "package pkg_y;\n  int w = pkg_x::w;\nendpackage\n",
    }
    assert _order(tmp_path, files, ["y.sv", "x.sv"]) == ["x.sv", "y.sv"], (
        "a commented-out reference still creates a dependency; the cycle it "
        "closes drops both files into the given order")


def test_a_commented_out_declaration_is_not_a_declaration(tmp_path):
    """A `package X;` inside `/* */` is not a package. b.sv's reference to it
    therefore resolves to nothing, and b.sv -- the only real package -- leads."""
    files = {
        "a.sv": "/*\npackage pkg_a;\nendpackage\n*/\nmodule a; endmodule\n",
        "b.sv": "package pkg_b;\n  int q = pkg_a::y;\nendpackage\n",
    }
    assert _order(tmp_path, files, ["b.sv", "a.sv"]) == ["b.sv", "a.sv"]


# --------------------------------------------------------------------------- #
# NEGATIVE CONTROLS — each one fails if the fix over-reaches
# --------------------------------------------------------------------------- #
def test_a_slash_slash_inside_a_string_does_not_hide_a_real_reference(tmp_path):
    """THE REASON THE STRIPPER IS NOT ONE OF THE THREE ALREADY IN THIS TREE.

    All three blank from the `//` onward regardless of string state, which
    would delete `pkg_x::w` from this line and lose a real edge. A fix that
    swaps a wrong order for a missing dependency has not fixed anything.
    """
    files = {
        "s.sv": ('package pkg_s;\n'
                 '  initial $display("a//b", pkg_x::w);\n'
                 'endpackage\n'),
        "x.sv": "package pkg_x;\n  int w = 8;\nendpackage\n",
    }
    assert _order(tmp_path, files, ["s.sv", "x.sv"]) == ["x.sv", "s.sv"], (
        "the dependency inside a line carrying a string with `//` was lost")


def test_ordinary_code_is_ordered_exactly_as_before(tmp_path):
    """The control that stops "it fails" being read as "it fails on
    everything": real packages, a real reference, and a non-package file."""
    files = {
        "p1.sv": "package p1;\n  int a = 1;\nendpackage\n",
        "p2.sv": "package p2;\n  int b = p1::a;\nendpackage\n",
        "m.sv": "module m; endmodule\n",
    }
    assert _order(tmp_path, files, ["m.sv", "p2.sv", "p1.sv"]) == [
        "p1.sv", "p2.sv", "m.sv"]


def test_a_genuine_cycle_is_still_tolerated(tmp_path):
    """Two packages that really do reference each other are a REAL cycle. The
    function's contract is to keep them, not to drop one or raise."""
    files = {
        "c1.sv": "package c1;\n  int a = c2::b;\nendpackage\n",
        "c2.sv": "package c2;\n  int b = c1::a;\nendpackage\n",
    }
    assert sorted(_order(tmp_path, files, ["c1.sv", "c2.sv"])) == [
        "c1.sv", "c2.sv"]


# --------------------------------------------------------------------------- #
# The stripper itself
# --------------------------------------------------------------------------- #
def test_the_stripper_preserves_offsets_and_line_count():
    """Blanked, not deleted. A regex that reports a line number over the
    stripped text must name the same line in the file."""
    src = ('package p;\n'
           '  /* two\n     lines */ int a = 1;  // tail\n'
           '  int b = 2;\n'
           'endpackage\n')
    out = tb._hdl_code_only(src)
    assert len(out) == len(src)
    assert out.count("\n") == src.count("\n")
    assert "two" not in out and "tail" not in out
    assert "int a = 1;" in out and "int b = 2;" in out


def test_an_unterminated_block_comment_blanks_the_rest_and_keeps_the_length():
    """An unterminated `/*` runs to EOF. Two of the three existing strippers
    `break` there and silently TRUNCATE the file, which would make everything
    after it invisible rather than commented."""
    src = "package p;\nint a = 1;\n/* never closed\nint b = pkg_q::z;\n"
    out = tb._hdl_code_only(src)
    assert len(out) == len(src)
    assert "int a = 1;" in out
    assert "pkg_q::" not in out
