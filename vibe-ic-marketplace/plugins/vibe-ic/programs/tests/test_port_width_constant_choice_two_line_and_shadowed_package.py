"""A width the design states as a CHOICE, on TWO LINES, or in a package it ships
TWICE — three shapes the resolver refused on numbers the design states in full.

`_port_width` resolves a DUT port's declared width to literal bounds or REFUSES
by name. After the body/package/`/` work it refused 40 of 25,343 corpus ports,
and three of the four residual shapes are these:

  A CONSTANT CHOICE.  A width is not always a constant SUM:

      localparam int DataOutW = EnableDataIntgPt ? SramDw + IntgWidth : SramDw

    Both arms and the constant that picks between them are stated, but `?:` is
    not Python syntax and `&&`, `||`, `!` are not Python operators, so the
    expression could not even be PARSED and every port over it refused. The
    corpus carries 48 such declarations, 21 of them needing a relational
    operator. The evaluator is widened to relational and logical forms OVER
    CONSTANTS ONLY -- no name it has not harvested, no side effect, still no
    `eval` of the design's own text -- and each Verilog form is rewritten onto
    the whitelisted AST rather than assumed to mean what the Python spelling
    means. `!` is the one that would have gone wrong silently: Python's `not`
    binds LOOSER than `==` and Verilog's `!` binds TIGHTER.

  A VALUE ON TWO LINES.  The declaration pattern captured `[^,\\n]+` -- a
    deliberate bound, because a capture that runs on swallows the NEXT
    declaration. But a design writes a long constant across two lines:

      parameter int RsvdWidth = top_pkg::TL_AUW - prim_mubi_pkg::MuBi4Width -
                                H2DCmdIntgWidth - DataIntgWidth;

    and the value was the dangling `A - B -`. The bound moves from the LINE to
    BRACKET DEPTH: the value ends at the declaration's own terminator, a `,` or
    `;` at depth 0 or the `)` that closes the header. It still cannot swallow
    the next declaration, and a `,` inside `(...)`, `[...]` or `{...}` is no
    longer a terminator either.

  A PACKAGE DECLARED TWICE.  A source set can carry one package twice, agreeing
    on most constants and disagreeing on one. Refusing both is honest, but the
    design INPUT says which copy it builds: the file list a tool is handed is
    rooted where the top's own modules live, so the copy on the elaboration
    path from the declared top WINS and the other is SHADOWED and named. With
    no top, or with no copy nearer the top than another, the old rule stands
    and the contested name is dropped.

WHAT STAYS REFUSED, ON PURPOSE. A comparison CHAIN (`a < b < c`) means
different things in the two languages and refuses rather than picking one. A
name unknown in the arm the ternary does NOT take still refuses: an undefined
constant is an elaboration error in Verilog whichever way the choice goes. A
sized literal INSIDE an expression (`c ? 1'b0 : 1'b1`) is not parsed and
refuses. A user package function still refuses.

chip-AGNOSTIC: every module, parameter and package name below is ordinary
Verilog; no chip, SKU, vendor or PDK literal appears.
"""
import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import _port_width as PW              # noqa: E402
import register_bus_driver_gen as RB  # noqa: E402
import design_one_shot_runner as P2   # noqa: E402
import testbench_gen as TBG           # noqa: E402


_L9 = {"top_module": "core_top", "top_ports": [
    {"name": "clk", "direction": "input"},
    {"name": "rst_n", "direction": "input"},
    {"name": "adr", "direction": "input"},
    {"name": "wdat", "direction": "input"},
    {"name": "rdat", "direction": "output"},
    {"name": "ack", "direction": "output"}]}


def _seed(tmp_path, rtl_text, name="core_top"):
    """A minimal project: L9 beside one RTL file, the shape both generators read.

    The L9 carries no msb/lsb on purpose -- supplying them would let the
    resolver answer from those and hide whether the harvest works at all.
    """
    proj = tmp_path / "proj"
    gd = P2._pl.generated_docs_dir(proj)
    gd.mkdir(parents=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(_L9))
    rtl = P2._pl.rtl_dir(proj)
    rtl.mkdir(parents=True)
    (rtl / f"{name}.v").write_text(rtl_text)
    return proj, rtl


# ── 1. the constant choice: the evaluator's new forms ────────────────────────

@pytest.mark.parametrize("expr,params,want", [
    # the shape that refused: a header constant chosen between two arms
    ("EnableDataIntgPt ? SramDw + IntgWidth : SramDw",
     {"EnableDataIntgPt": 0, "SramDw": 32, "IntgWidth": 7}, 32),
    ("EnableDataIntgPt ? SramDw + IntgWidth : SramDw",
     {"EnableDataIntgPt": 1, "SramDw": 32, "IntgWidth": 7}, 39),
    # a ternary INSIDE a call -- a rewrite that only looked at depth 0 misses it
    ("$clog2(ExplicitErrs ? N+1 : N)", {"ExplicitErrs": 1, "N": 4}, 3),
    ("$clog2(ExplicitErrs ? N+1 : N)", {"ExplicitErrs": 0, "N": 4}, 2),
    # relational
    ("(Gran > 0) ? 33 - Gran : 32", {"Gran": 0}, 32),
    ("(Gran > 0) ? 33 - Gran : 32", {"Gran": 4}, 29),
    ("W <= 4 ? 4 : W <= 11 ? 5 : 6", {"W": 4}, 4),
    ("W <= 4 ? 4 : W <= 11 ? 5 : 6", {"W": 9}, 5),
    ("W <= 4 ? 4 : W <= 11 ? 5 : 6", {"W": 40}, 6),
    # `||` and `&&`
    ("(D != 0 || R == 31) ? 0 : R+1", {"D": 0, "R": 14}, 15),
    ("(D != 0 || R == 31) ? 0 : R+1", {"D": 1, "R": 14}, 0),
    ("(A > 0 && B > 0) ? 1 : 0", {"A": 1, "B": 1}, 1),
    ("(A > 0 && B > 0) ? 1 : 0", {"A": 1, "B": 0}, 0),
    # `!`, at VERILOG's precedence: `!A == B` is `(!A) == B`, not `!(A == B)`
    ("!A ? 2 : 3", {"A": 0}, 2),
    ("!A ? 2 : 3", {"A": 5}, 3),
    ("!A == B", {"A": 0, "B": 1}, 1),
    ("!(A == B)", {"A": 0, "B": 1}, 1),
    ("!!A", {"A": 7}, 1),
    # a relational result is an INTEGER 1/0, the way Verilog states it
    ("A == 1", {"A": 1}, 1),
    ("A != 1", {"A": 1}, 0),
    # `%` inside the condition, and the right-associative nesting
    ("(S * 4) % O != 0 ? 1 : 0", {"S": 288, "O": 64}, 0),
    ("(S * 4) % O != 0 ? 1 : 0", {"S": 289, "O": 64}, 1),
    ("c1 ? 1 : c2 ? 2 : 3", {"c1": 0, "c2": 1}, 2),
    ("c1 ? 1 : c2 ? 2 : 3", {"c1": 0, "c2": 0}, 3),
    ("c1 ? c2 ? 2 : 3 : 4", {"c1": 1, "c2": 0}, 3),
    ("c1 ? c2 ? 2 : 3 : 4", {"c1": 0, "c2": 0}, 4),
])
def test_a_constant_choice_evaluates_to_the_arm_the_design_picks(
        expr, params, want):
    got = RB._int_expr(expr, params)
    assert got == want, (expr, params, got)
    assert type(got) is int and not isinstance(got, bool), type(got)


@pytest.mark.parametrize("expr,params", [
    ("1 < 2 < 3", {}),                       # a CHAIN: refuse, do not pick
    ("A < B < C", {"A": 1, "B": 2, "C": 3}),
    ("A ? B : C", {"A": 1, "B": 8}),         # the arm not taken is still unknown
    ("A ? B : C", {"A": 0, "B": 8}),
    ("A ? 1", {"A": 1}),                     # a `?` with no `:`
    ("A ? 1 : ", {"A": 1}),
    ("Sat ? 1'b0 : 1'b1", {"Sat": 1}),       # a sized literal INSIDE an expr
    ("prim_util_pkg::vbits(N)", {"N": 8}),   # a USER function, still refused
    ("$bits(my_struct_t)", {}),
    ("A ? 1 : 2", {"A": "x"}),               # a non-integer never becomes a width
    ("9**9**9", {}),
])
def test_what_a_constant_choice_must_still_refuse(expr, params):
    assert RB._int_expr(expr, params) is None, (expr, params)


_CHOICE_RTL = (
    "module core_top #(\n"
    "  parameter  int  NumSrc   = 32,\n"
    "  parameter  bit  Saturate = 1'b1,\n"
    "  parameter  int  InWidth  = 8,\n"
    "  localparam int  NumLevels = $clog2(NumSrc),\n"
    "  localparam int  OutWidth  = Saturate ? InWidth : InWidth + NumLevels\n"
    ") (\n"
    "  input clk,\n  input rst_n,\n"
    "  input  [InWidth-1:0]  adr,\n"
    "  input  [OutWidth-1:0] wdat,\n"
    "  output [OutWidth-1:0] rdat,\n"
    "  output ack);\n"
    "  assign rdat = wdat;\n  assign ack = 1'b1;\n"
    "endmodule\n"
)


def test_a_port_declared_over_a_constant_choice_resolves():
    params = PW.dut_defaults(_CHOICE_RTL, "core_top")
    assert params["OutWidth"] == 8, params
    assert PW.resolve("[OutWidth-1:0]", params)[0] == " [7:0]"


def test_flipping_the_constant_that_picks_flips_the_width():
    """THE OTHER DIRECTION. The width follows the design's own choice, so the
    same module with `Saturate = 1'b0` is a DIFFERENT, wider port -- 8 + 5."""
    rtl = _CHOICE_RTL.replace("Saturate = 1'b1", "Saturate = 1'b0")
    params = PW.dut_defaults(rtl, "core_top")
    assert params["OutWidth"] == 13, params
    assert PW.resolve("[OutWidth-1:0]", params)[0] == " [12:0]"


def test_removing_the_ternary_rewrite_refuses_the_same_width(monkeypatch):
    """THE MUTATION. Take the `?:` rewrite away and the width goes RED again,
    by name -- so the test is measuring the rewrite and not something else."""
    monkeypatch.setattr(RB, "_rewrite_ternary", lambda s, budget=0: None)
    params = PW.dut_defaults(_CHOICE_RTL, "core_top")
    assert "OutWidth" not in params, params
    decl, why = PW.resolve("[OutWidth-1:0]", params)
    assert decl is None and "OutWidth" in why, (decl, why)


def test_removing_the_logical_not_rewrite_refuses_the_same_width(monkeypatch):
    """The same mutation for `!`: without the rewrite the expression does not
    parse, and the constant is absent rather than wrong."""
    monkeypatch.setattr(RB, "_rewrite_not", lambda s, budget=0: None)
    assert RB._int_expr("!A ? 2 : 3", {"A": 0}) is None


def test_a_bare_relational_bound_is_the_integer_1_or_0_not_a_python_bool():
    """A comparison is the INTEGER 1 or 0 in Verilog, and this evaluator has
    always refused to return a bool -- so without the integer wrapping the
    bound would come back as `True` and the width would refuse. `[(A==B):0]`
    is therefore `[1:0]` when the comparison holds and one bit when it does
    not."""
    assert PW.resolve("[(A==B):0]", {"A": 1, "B": 1})[0] == " [1:0]"
    assert PW.resolve("[(A==B):0]", {"A": 1, "B": 2})[0] == ""
    assert PW.resolve("[(A==B)+1:0]", {"A": 1, "B": 1})[0] == " [2:0]"


# ── 2. a value that spans two lines ──────────────────────────────────────────

_TWO_LINE_PKG = (
    "package a_pkg;\n  parameter int AUW = 32;\nendpackage\n"
    "package b_pkg;\n  parameter int MUBI = 4;\nendpackage\n"
    "package w_pkg;\n"
    "  parameter int CMD_INTG = 7;\n"
    "  parameter int DATA_INTG = 7;\n"
    "  parameter int RsvdWidth = a_pkg::AUW - b_pkg::MUBI -\n"
    "                            CMD_INTG - DATA_INTG;\n"
    "  parameter int OneLine   = 5;\n"
    "endpackage\n"
)
_TWO_LINE_DUT = (
    "module core_top\n  import w_pkg::*;\n#(\n"
    "  parameter  int A = 8,\n"
    "  localparam int B = A *\n"
    "                     2\n"
    ") (\n"
    "  input clk,\n  input rst_n,\n"
    "  input  [RsvdWidth-1:0] adr,\n"
    "  input  [B-1:0]         wdat,\n"
    "  output [OneLine-1:0]   rdat,\n"
    "  output ack);\n"
    "  assign ack = 1'b1;\n"
    "endmodule\n"
)


def test_a_package_constant_written_across_two_lines_resolves():
    pk = RB.package_constants([("p.sv", _TWO_LINE_PKG)])
    assert pk["w_pkg"]["RsvdWidth"] == 32 - 4 - 7 - 7, pk["w_pkg"]
    params = PW.defaults_from_sources(
        [("p.sv", _TWO_LINE_PKG), ("m.sv", _TWO_LINE_DUT)], "core_top")
    assert PW.resolve("[RsvdWidth-1:0]", params)[0] == " [13:0]"


def test_a_header_constant_written_across_two_lines_resolves():
    params = PW.defaults_from_sources(
        [("p.sv", _TWO_LINE_PKG), ("m.sv", _TWO_LINE_DUT)], "core_top")
    assert params["B"] == 16, params
    assert PW.resolve("[B-1:0]", params)[0] == " [15:0]"


def test_restoring_the_end_of_line_bound_refuses_the_same_width(monkeypatch):
    """THE MUTATION. Put the old end-of-LINE bound back and the two-line value
    is the dangling `A - B -` again: the constant is absent and the port
    refuses BY NAME. Nothing else in this file changes."""
    real = RB._trim_value
    monkeypatch.setattr(RB, "_trim_value",
                        lambda text: real(text.split("\n", 1)[0]))
    pk = RB.package_constants([("p.sv", _TWO_LINE_PKG)])
    assert "RsvdWidth" not in pk["w_pkg"], pk["w_pkg"]
    assert pk["w_pkg"]["OneLine"] == 5, pk["w_pkg"]      # the rest is untouched


def test_a_value_that_never_terminates_does_not_swallow_the_next_declaration():
    """THE BOUND THAT MATTERS. The old `[^,\\n]+` existed so a capture could not
    run into the following declaration. A missing `;` must still cost only its
    OWN constant -- the next one is harvested normally."""
    runon = ("package q_pkg;\n"
             "  parameter int X = 1\n"
             "  parameter int Y = 2;\n"
             "  parameter int Z = 3;\n"
             "endpackage\n")
    got = RB.package_constants([("q.sv", runon)])["q_pkg"]
    assert "X" not in got, got
    assert got["Y"] == 2 and got["Z"] == 3, got


@pytest.mark.parametrize("body,want", [
    # a `,` inside brackets is part of the value, not a terminator
    ("package p;\n  parameter int W = 8;\n"
     "  parameter int V = $clog2(W) + 1;\nendpackage\n", {"W": 8, "V": 4}),
    # comma-separated declarations still stop at the comma
    ("package p;\n  parameter int A = 3, B = 9;\n"
     "  parameter int C = 4;\nendpackage\n", {"A": 3, "C": 4}),
    # a `;`-terminated body declaration is unchanged
    ("package p;\n  parameter int A = 2;\n  parameter int B = A*2;\n"
     "endpackage\n", {"A": 2, "B": 4}),
])
def test_a_single_line_declaration_reads_exactly_as_before(body, want):
    """THE CONTROL for the wider capture: what already terminated on its own
    line must come back with the same value and the same NAME SET."""
    got = RB.package_constants([("p.sv", body)])["p"]
    assert got == want, got


@pytest.mark.parametrize("cell,params,want", [
    ("[aw-1:0]", {"aw": 10}, " [9:0]"),
    ("[dw-1:0]", {"dw": 32}, " [31:0]"),
    ("[2*size-1:0]", {"size": 8}, " [15:0]"),
    ("[31:0]", {}, " [31:0]"),
    ("[N-1:0]", {"N": 1}, ""),
    ("", {}, ""),
    ("[Aw-1:0]", {}, None),
])
def test_the_widened_evaluator_does_not_move_an_old_answer(cell, params, want):
    """THE CONTROL. Every form added here is a form that used to REFUSE, so an
    expression that already evaluated must evaluate to the same number."""
    assert PW.resolve(cell, params)[0] == want


# ── 3. one package, two copies, and which one the design builds ─────────────

_PKG_A = ("package dup_pkg;\n  parameter int SAME = 8;\n"
          "  parameter int CONTESTED = 1;\nendpackage\n")
_PKG_B = ("package dup_pkg;\n  parameter int SAME = 8;\n"
          "  parameter int CONTESTED = 2;\n"
          "  parameter int ONLY_HERE = 5;\nendpackage\n")
_DUP_DUT = ("module core_top\n  import dup_pkg::*;\n"
            "  (input [CONTESTED-1:0] a, input [SAME-1:0] b);\nendmodule\n")


def test_the_copy_the_elaboration_reaches_wins_and_the_other_is_named():
    notes = []
    got = RB.package_constants(
        [("rtl/dup_pkg.sv", _PKG_A), ("doc/dup_pkg.sv", _PKG_B),
         ("rtl/core_top.sv", _DUP_DUT)], top="core_top", notes=notes)
    assert got["dup_pkg"]["CONTESTED"] == 1, got["dup_pkg"]
    assert "ONLY_HERE" not in got["dup_pkg"], got["dup_pkg"]
    assert len(notes) == 1, notes
    assert "rtl/dup_pkg.sv" in notes[0] and "doc/dup_pkg.sv" in notes[0], notes
    assert "CONTESTED" in notes[0], notes


def test_moving_the_top_moves_which_copy_wins():
    """THE OTHER DIRECTION, and the reason this is a PATH and not a preference:
    the same two copies, the top declared beside the other one, and the answer
    flips. Nothing here reads a directory NAME."""
    notes = []
    got = RB.package_constants(
        [("rtl/dup_pkg.sv", _PKG_A), ("doc/dup_pkg.sv", _PKG_B),
         ("doc/core_top.sv", _DUP_DUT)], top="core_top", notes=notes)
    assert got["dup_pkg"]["CONTESTED"] == 2, got["dup_pkg"]
    assert got["dup_pkg"]["ONLY_HERE"] == 5, got["dup_pkg"]
    assert "doc/dup_pkg.sv" in notes[0] and "shadowed" in notes[0], notes


def test_a_port_over_the_contested_constant_now_resolves():
    params = PW.defaults_from_sources(
        [("rtl/dup_pkg.sv", _PKG_A), ("doc/dup_pkg.sv", _PKG_B),
         ("rtl/core_top.sv", _DUP_DUT)], "core_top")
    assert PW.resolve("[CONTESTED-1:0]", params)[0] == ""      # 1 bit
    assert PW.resolve("[SAME-1:0]", params)[0] == " [7:0]"


def test_one_copy_only_is_byte_identical_and_says_nothing():
    """THE CONTROL. Drop the shadowed copy from the source set and the package
    scope must be IDENTICAL, with no note: the winner contributed all of it."""
    both, one = [], []
    a = RB.package_constants(
        [("rtl/dup_pkg.sv", _PKG_A), ("doc/dup_pkg.sv", _PKG_B),
         ("rtl/core_top.sv", _DUP_DUT)], top="core_top", notes=both)
    b = RB.package_constants(
        [("rtl/dup_pkg.sv", _PKG_A), ("rtl/core_top.sv", _DUP_DUT)],
        top="core_top", notes=one)
    assert a == b, (a, b)
    assert one == [], one
    assert len(both) == 1, both


def test_two_copies_that_AGREE_resolve_with_no_note():
    """THE OTHER CONTROL. Duplication alone decides nothing: copies that state
    the same names with the same values are one package written twice."""
    notes = []
    got = RB.package_constants(
        [("rtl/dup_pkg.sv", _PKG_A), ("doc/dup_pkg.sv", _PKG_A),
         ("rtl/core_top.sv", _DUP_DUT)], top="core_top", notes=notes)
    assert got["dup_pkg"] == {"SAME": 8, "CONTESTED": 1}, got
    assert notes == [], notes


def test_with_no_top_the_contested_constant_is_still_dropped():
    """The old rule is untouched where nothing decides: no top, no path, so the
    disagreement is REFUSED rather than picked."""
    notes = []
    got = RB.package_constants(
        [("rtl/dup_pkg.sv", _PKG_A), ("doc/dup_pkg.sv", _PKG_B)], notes=notes)
    assert got["dup_pkg"]["SAME"] == 8, got
    assert "CONTESTED" not in got["dup_pkg"], got
    assert notes and "dropped" in notes[0], notes


def test_two_copies_the_same_distance_from_the_top_decide_nothing():
    notes = []
    got = RB.package_constants(
        [("a/dup_pkg.sv", _PKG_A), ("b/dup_pkg.sv", _PKG_B),
         ("c/core_top.sv", _DUP_DUT)], top="core_top", notes=notes)
    assert "CONTESTED" not in got["dup_pkg"], got
    assert notes and "no copy wins" in notes[0], notes


def test_a_top_no_source_declares_decides_nothing_and_says_which():
    notes = []
    got = RB.package_constants(
        [("rtl/dup_pkg.sv", _PKG_A), ("doc/dup_pkg.sv", _PKG_B)],
        top="absent_top", notes=notes)
    assert "CONTESTED" not in got["dup_pkg"], got
    assert notes and "absent_top" in notes[0], notes


def test_a_comment_naming_the_top_is_not_a_declaration():
    """#731 again: the file that DECLARES the top is found with comments
    blanked, so a sentence about the module cannot move the elaboration path."""
    decoy = "// the elaboration starts at module core_top\n"
    notes = []
    got = RB.package_constants(
        [("doc/notes.sv", decoy), ("rtl/dup_pkg.sv", _PKG_A),
         ("doc/dup_pkg.sv", _PKG_B), ("rtl/core_top.sv", _DUP_DUT)],
        top="core_top", notes=notes)
    assert got["dup_pkg"]["CONTESTED"] == 1, got["dup_pkg"]


# ── the two shipped consumers, end to end from an on-disk project ────────────

_SHADOW_DUT = ("module core_top\n  import dup_pkg::*;\n"
               "  (input clk,\n   input rst_n,\n"
               "   input  [CONTESTED-1:0] adr,\n"
               "   input  [SAME-1:0]      wdat,\n"
               "   output [SAME-1:0]      rdat,\n"
               "   output ack);\n"
               "  assign rdat = wdat;\n  assign ack = 1'b1;\n"
               "endmodule\n")


def _seed_two_copies(tmp_path, second_copy=True):
    """A project whose RTL tree carries `dup_pkg` twice, in two directories,
    with the DUT beside ONE of them. Both generators read the tree with rglob,
    so this is the on-disk shape the resolver actually meets."""
    proj, rtl = _seed(tmp_path, _SHADOW_DUT)
    (rtl / f"core_top.v").unlink()
    near = rtl / "core"
    near.mkdir()
    (near / "core_top.sv").write_text(_SHADOW_DUT)
    (near / "dup_pkg.sv").write_text(_PKG_A)
    if second_copy:
        far = rtl / "docs"
        far.mkdir()
        (far / "dup_pkg.sv").write_text(_PKG_B)
    return proj


def test_the_unit_tb_reason_names_the_winning_and_the_shadowed_copy(tmp_path):
    """THE RECORD HAS A CONSUMER. The run chose which copy of a duplicated
    package the widths came from; the reason the generator hands back says so,
    names both files, and names the constant they disagreed on."""
    proj = _seed_two_copies(tmp_path)
    mod, ports, why = TBG.resolve_dut(proj, "core_top")
    assert mod == "core_top", why
    widths = {n: w for _d, w, n in ports}
    assert widths["adr"] == "", widths            # CONTESTED = 1 -> one bit
    assert widths["wdat"] == "[7:0]", widths
    assert "dup_pkg" in why and "shadowed" in why, why
    assert "core/dup_pkg.sv" in why, why          # the copy that won
    assert "docs/dup_pkg.sv" in why, why          # the copy that did not
    assert "CONTESTED" in why, why


def test_with_one_copy_the_same_reason_carries_no_note(tmp_path):
    """THE CONTROL. Same DUT, same widths, one copy of the package: the reason
    is the plain one and says nothing about shadowing, because nothing was
    decided."""
    proj = _seed_two_copies(tmp_path, second_copy=False)
    mod, ports, why = TBG.resolve_dut(proj, "core_top")
    assert mod == "core_top", why
    widths = {n: w for _d, w, n in ports}
    assert widths["adr"] == "" and widths["wdat"] == "[7:0]", widths
    assert "shadowed" not in why and "dup_pkg" not in why, why


def test_two_copies_that_AGREE_leave_the_reason_alone(tmp_path):
    """The other control at the CONSUMER: duplication alone records nothing."""
    proj = _seed_two_copies(tmp_path, second_copy=False)
    far = P2._pl.rtl_dir(proj) / "docs"
    far.mkdir()
    (far / "dup_pkg.sv").write_text(_PKG_A)
    mod, _ports, why = TBG.resolve_dut(proj, "core_top")
    assert mod == "core_top", why
    assert "shadowed" not in why, why


def test_unit_tb_declares_a_constant_choice_width(tmp_path):
    proj, _ = _seed(tmp_path, _CHOICE_RTL)
    mod, ports, why = TBG.resolve_dut(proj, "core_top")
    assert mod == "core_top", why
    widths = {n: w for _d, w, n in ports}
    assert widths["wdat"] == "[7:0]", widths
    assert widths["rdat"] == "[7:0]", widths
    assert widths["adr"] == "[7:0]", widths


def test_full_stack_tb_declares_a_two_line_bus_at_its_real_width(tmp_path):
    proj, rtl = _seed(tmp_path, _TWO_LINE_DUT)
    (rtl / "w_pkg.sv").write_text(_TWO_LINE_PKG)
    res = P2.step_full_stack_tb_gen(proj, "chip_top")
    assert res.status != "FAIL", res.detail
    body = list(P2._pl.sim_full_stack_dir(proj).glob("tb_*_full.v"))[0].read_text()
    assert "reg [13:0] adr = 0;" in body, body
    assert "reg [15:0] wdat = 0;" in body, body
    assert "wire [4:0] rdat;" in body, body
    # the pre-fix text: a wide bus bound ONE BIT wide, which still said PASS
    assert "reg adr = 0;" not in body


def test_without_the_package_file_both_consumers_still_refuse(tmp_path):
    """THE OTHER DIRECTION AT THE CONSUMER: the two-line constant lives in a
    package, and with that file absent the port must REFUSE by name -- not fall
    back to one bit."""
    proj, _rtl = _seed(tmp_path, _TWO_LINE_DUT)
    mod, ports, why = TBG.resolve_dut(proj, "core_top")
    assert mod is None, (mod, ports, why)
    res = P2.step_full_stack_tb_gen(proj, "chip_top")
    assert res.status == "FAIL", res.detail
    assert "not derivable" in res.detail, res.detail
