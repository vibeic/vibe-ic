"""A width is STATED in three places, and the resolver read only one of them.

`_port_width` evaluates a port's declared width over the constants that are in
scope where the port is declared, and REFUSES by name when it cannot. It read
the module's `#( ... )` parameter header and nothing else, so three ordinary
SystemVerilog shapes came back as refusals on numbers the design states in full:

  BODY CONSTANTS.  Verilog-1995 has no parameter header at all:

      module ram (rd_out, addr_in, ...);
        parameter BITS = 39;
        output reg [BITS-1:0] rd_out;

    Every port of every such module was unresolvable. A behavioural memory
    model is exactly the shape that has no header, so this is not a corner.

  PACKAGE CONSTANTS.  A constant more than one module is declared over lives in
    a package, reached either by SCOPE (`[top_pkg::TL_DW-1:0]`) or by IMPORT
    (`module m import aes_reg_pkg::*; #(...) (... [NumRegsData-1:0] ...)`).
    The module's own text can never state those, so reading only the module
    left them unknown -- and `::` is not Python, so a scoped bound could not
    even be PARSED, whatever the package said.

  VERILOG INTEGER DIVISION.  `localparam int RegBw = RegDw/8` is ordinary
    SystemVerilog and IEEE 1364 says `/` on integers TRUNCATES. Python's `/`
    yields a float, so the constant evaluated to a non-integer and was dropped,
    and every width declared over it refused. One `/` in a chain took the whole
    chain down: `W = Width/25` -> `L = $clog2(W)` -> `MaxRound = 12+2*L` ->
    `RndW = $clog2(MaxRound+1)`, four constants and a port lost to one operator.

WHAT STAYS REFUSED, ON PURPOSE.  Refusal is the third state and it is load
bearing. A width over a USER-DEFINED package function (`prim_util_pkg::vbits(N)`)
or over `$bits(some_type_t)` is NOT resolved: the first would mean running the
design's own code and the second needs the design's type system. Both refuse BY
NAME. `$clog2` is admitted because it is a pure integer function of one integer
with fixed IEEE semantics.

MEASURED, so the admitted set is not a guess: across 25,343 corpus ports, ZERO
`$` functions appear in a width CELL. In the constant DECLARATIONS those cells
are written over, exactly two appear: `$clog2` and `$bits`.

chip-AGNOSTIC: every module, parameter and package name below is ordinary
Verilog; no chip, SKU, vendor or PDK literal appears.
"""
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import _port_width as PW              # noqa: E402
import register_bus_driver_gen as RB  # noqa: E402


# ── body constants: the shape with no parameter header at all ────────────────

_BODY_RTL = (
    "module blk (rd_out, addr_in, clk);\n"
    "   parameter BITS = 39;\n"
    "   parameter ADDR_WIDTH = 11;\n"
    "   output reg [BITS-1:0]   rd_out;\n"
    "   input  [ADDR_WIDTH-1:0] addr_in;\n"
    "   input                   clk;\n"
    "endmodule\n"
)


def test_a_body_parameter_states_the_width():
    params = PW.dut_defaults(_BODY_RTL, "blk")
    assert params == {"BITS": 39, "ADDR_WIDTH": 11}, params
    assert PW.resolve("[BITS-1:0]", params)[0] == " [38:0]"
    assert PW.resolve("[ADDR_WIDTH-1:0]", params)[0] == " [10:0]"


def test_without_the_body_declaration_the_same_width_refuses():
    """THE OTHER DIRECTION. Delete the one line that states the number and the
    width must go back to refusing BY NAME -- not to one bit, not to a guess."""
    stripped = _BODY_RTL.replace("   parameter BITS = 39;\n", "")
    params = PW.dut_defaults(stripped, "blk")
    assert "BITS" not in params, params
    decl, why = PW.resolve("[BITS-1:0]", params)
    assert decl is None and "BITS" in why, (decl, why)


def test_a_body_constant_declared_twice_with_two_values_is_ambiguous():
    """A generate arm or a function-local constant is not the module-scope
    constant a port is declared over. Two values, no answer -- never the first
    one seen."""
    rtl = ("module blk (a);\n"
           "  parameter W = 8;\n"
           "  input [W-1:0] a;\n"
           "  generate if (1) begin : g\n"
           "    localparam W = 16;\n"
           "  end endgenerate\n"
           "endmodule\n")
    params = PW.dut_defaults(rtl, "blk")
    assert "W" not in params, params
    assert PW.resolve("[W-1:0]", params)[0] is None


def test_the_SAME_body_constant_declared_ONCE_does_resolve():
    """The control for the case above: what is refused is the AMBIGUITY, not
    the body scan. One declaration, same name, same module shape -> resolved."""
    rtl = ("module blk (a);\n"
           "  parameter W = 8;\n"
           "  input [W-1:0] a;\n"
           "  generate if (1) begin : g\n"
           "    localparam Other = 16;\n"
           "  end endgenerate\n"
           "endmodule\n")
    params = PW.dut_defaults(rtl, "blk")
    assert params.get("W") == 8, params
    assert PW.resolve("[W-1:0]", params)[0] == " [7:0]"


def test_the_header_wins_a_clash_with_the_body():
    rtl = ("module blk #(parameter W = 8) (input [W-1:0] a);\n"
           "  localparam W = 99;\n"
           "endmodule\n")
    assert PW.dut_defaults(rtl, "blk")["W"] == 8
    # ...and with the header gone the BODY value is the one in scope, which is
    # what makes the line above a precedence statement rather than a body-blind
    # one.
    headerless = ("module blk (a);\n"
                  "  localparam W = 99;\n"
                  "  input [W-1:0] a;\n"
                  "endmodule\n")
    assert PW.dut_defaults(headerless, "blk")["W"] == 99


def test_a_body_harvest_stops_at_endmodule():
    """The NEXT module's constants are not this one's."""
    rtl = ("module first (a);\n"
           "  parameter W = 4;\n"
           "  input [W-1:0] a;\n"
           "endmodule\n"
           "module second (b);\n"
           "  parameter Z = 9;\n"
           "  input [Z-1:0] b;\n"
           "endmodule\n")
    assert PW.dut_defaults(rtl, "first") == {"W": 4}
    assert PW.dut_defaults(rtl, "second") == {"Z": 9}


# ── package constants: scoped and imported ───────────────────────────────────

_PKG = ("package bus_pkg;\n"
        "  localparam int BUS_DW  = 32;\n"
        "  localparam int BUS_DBW = (BUS_DW>>3);\n"
        "  parameter  int NumRegs = 4;\n"
        "endpackage\n")

_SCOPED_RTL = ("module scoped (input [bus_pkg::BUS_DW-1:0] d);\n"
               "endmodule\n")

_IMPORT_RTL = ("module imp\n"
               "  import bus_pkg::*;\n"
               "#(parameter int Unused = 1)\n"
               "  (input [NumRegs-1:0] qe);\n"
               "endmodule\n")


def test_a_scope_qualified_bound_resolves_over_the_package():
    srcs = [("pkg.sv", _PKG), ("scoped.sv", _SCOPED_RTL)]
    params = PW.defaults_from_sources(srcs, "scoped")
    assert params.get("bus_pkg::BUS_DW") == 32, params
    assert params.get("bus_pkg::BUS_DBW") == 4, params
    assert PW.resolve("[bus_pkg::BUS_DW-1:0]", params)[0] == " [31:0]"


def test_without_the_package_the_scoped_bound_refuses_by_its_FULL_name():
    """THE OTHER DIRECTION, and the refusal must name the symbol WHOLE.

    Splitting `bus_pkg::BUS_DW` into two bare names sends a reader after
    `bus_pkg` or after `BUS_DW`, neither of which is the thing to look up.
    """
    params = PW.defaults_from_sources([("scoped.sv", _SCOPED_RTL)], "scoped")
    decl, why = PW.resolve("[bus_pkg::BUS_DW-1:0]", params)
    assert decl is None
    # The SYMBOL LIST, not the echoed cell: the cell text contains the name
    # whatever the resolver understood about it, so asserting on the echo
    # cannot tell a whole scoped name from two halves of one.
    assert PW._unresolved_symbols("[bus_pkg::BUS_DW-1:0]", params) \
        == ["bus_pkg::BUS_DW"]
    assert "['bus_pkg::BUS_DW']" in why, why


def test_an_import_puts_the_package_names_in_scope_unqualified():
    srcs = [("pkg.sv", _PKG), ("imp.sv", _IMPORT_RTL)]
    params = PW.defaults_from_sources(srcs, "imp")
    assert params.get("NumRegs") == 4, params
    assert PW.resolve("[NumRegs-1:0]", params)[0] == " [3:0]"


def test_without_the_import_the_unqualified_name_is_NOT_in_scope():
    """THE OTHER DIRECTION, and it isolates the IMPORT as the cause: the same
    package is present in the sources, only the `import` line is gone."""
    no_import = _IMPORT_RTL.replace("  import bus_pkg::*;\n", "")
    srcs = [("pkg.sv", _PKG), ("imp.sv", no_import)]
    params = PW.defaults_from_sources(srcs, "imp")
    assert "NumRegs" not in params, params
    assert params.get("bus_pkg::NumRegs") == 4, params      # still scoped
    decl, why = PW.resolve("[NumRegs-1:0]", params)
    assert decl is None and "NumRegs" in why, (decl, why)


def test_two_imported_packages_that_disagree_leave_the_name_AMBIGUOUS():
    a = "package a_pkg;\n  localparam int W = 8;\nendpackage\n"
    b = "package b_pkg;\n  localparam int W = 16;\nendpackage\n"
    rtl = ("module m\n  import a_pkg::*;\n  import b_pkg::*;\n"
           "  (input [W-1:0] d);\nendmodule\n")
    params = PW.defaults_from_sources(
        [("a.sv", a), ("b.sv", b), ("m.sv", rtl)], "m")
    assert "W" not in params, params
    assert params["a_pkg::W"] == 8 and params["b_pkg::W"] == 16
    assert PW.resolve("[W-1:0]", params)[0] is None


def test_two_imported_packages_that_AGREE_do_resolve():
    """The control for the case above: ambiguity is what is refused, not
    duplication."""
    a = "package a_pkg;\n  localparam int W = 8;\nendpackage\n"
    b = "package b_pkg;\n  localparam int W = 8;\nendpackage\n"
    rtl = ("module m\n  import a_pkg::*;\n  import b_pkg::*;\n"
           "  (input [W-1:0] d);\nendmodule\n")
    params = PW.defaults_from_sources(
        [("a.sv", a), ("b.sv", b), ("m.sv", rtl)], "m")
    assert PW.resolve("[W-1:0]", params)[0] == " [7:0]"


def test_the_package_harvest_reaches_a_fixpoint_across_packages():
    """One package legitimately states a constant over another's."""
    a = "package a_pkg;\n  localparam int Base = 16;\nendpackage\n"
    b = ("package b_pkg;\n  localparam int Wide = a_pkg::Base*2;\n"
         "endpackage\n")
    got = RB.package_constants([("b.sv", b), ("a.sv", a)])  # b listed FIRST
    assert got["a_pkg"]["Base"] == 16
    assert got["b_pkg"]["Wide"] == 32, got


def test_a_module_constant_beats_an_imported_one():
    rtl = ("module m\n  import bus_pkg::*;\n#(parameter int NumRegs = 7)\n"
           "  (input [NumRegs-1:0] q);\nendmodule\n")
    params = PW.defaults_from_sources([("p.sv", _PKG), ("m.sv", rtl)], "m")
    assert params["NumRegs"] == 7, params
    assert PW.resolve("[NumRegs-1:0]", params)[0] == " [6:0]"


def test_a_COMMENTED_OUT_declaration_is_not_a_declaration():
    """#731, in the three scans this change adds. A comment that says a name is
    not a declaration of it, and a scan that counts one reads the wrong file --
    or mints a package that does not exist."""
    decoy = "\n".join([
        "// module imp is described here, and",
        "// package bus_pkg used to define NumRegs = 999;",
        "/* module imp ( ... ); */",
        ""])
    srcs = [("decoy.sv", decoy), ("pkg.sv", _PKG), ("imp.sv", _IMPORT_RTL)]
    params = PW.defaults_from_sources(srcs, "imp")
    assert params.get("NumRegs") == 4, params        # the REAL package's value
    assert PW.resolve("[NumRegs-1:0]", params)[0] == " [3:0]"
    assert "bus_pkg" in RB.package_constants([("pkg.sv", _PKG)])
    assert RB.package_constants([("decoy.sv", decoy)]) == {}


def test_the_module_is_found_in_whichever_source_declares_it():
    """The control for the case above: what must be ignored is the DECOY, not
    every source that is not the first one."""
    other = "module other (input a);\nendmodule\n"
    srcs = [("other.sv", other), ("pkg.sv", _PKG), ("imp.sv", _IMPORT_RTL)]
    assert PW.defaults_from_sources(srcs, "imp").get("NumRegs") == 4


# ── Verilog integer arithmetic ───────────────────────────────────────────────

@pytest.mark.parametrize("expr,want", [
    ("32/8", 4),
    ("7/2", 3),            # truncates, does not round
    ("-7/2", -3),          # toward zero, not toward -inf
    ("7/-2", -3),
    ("7%2", 1),
    ("-7%2", -1),          # the sign follows the DIVIDEND
    ("1600/25", 64),
    ("32/0", None),        # refuses, never raises
    ("32%0", None),
])
def test_verilog_integer_division_and_modulo(expr, want):
    assert RB._int_expr(expr, {}) == want


def test_one_slash_took_a_whole_derivation_chain_down():
    """The measured shape: four derived constants and a port, all lost to `/`."""
    rtl = ("module k #(\n"
           "  parameter int Width = 1600,\n"
           "  localparam int W        = Width/25,\n"
           "  localparam int L        = $clog2(W),\n"
           "  localparam int MaxRound = 12 + 2*L,\n"
           "  localparam int RndW     = $clog2(MaxRound+1)\n"
           ") (input [RndW-1:0] rnd_i, input [Width-1:0] s_i);\n"
           "endmodule\n")
    params = PW.dut_defaults(rtl, "k")
    assert (params["W"], params["L"], params["MaxRound"], params["RndW"]) \
        == (64, 6, 24, 5), params
    assert PW.resolve("[RndW-1:0]", params)[0] == " [4:0]"


def test_dropping_clog2_re_refuses_the_derived_width(monkeypatch):
    """MUTATION. `$clog2` is what turns `N` into an index width; take it out of
    the admitted set and the derived width must go RED again -- which is what
    proves the test is reading the clog2 path and not something else."""
    rtl = ("module arb #(\n"
           "  parameter  int N    = 8,\n"
           "  localparam int IdxW = $clog2(N)\n"
           ") (output [IdxW-1:0] idx_o);\nendmodule\n")
    assert PW.resolve("[IdxW-1:0]", PW.dut_defaults(rtl, "arb"))[0] == " [2:0]"
    funcs = dict(RB._CONST_FUNCS)
    funcs.pop("clog2")
    monkeypatch.setattr(RB, "_CONST_FUNCS", funcs)
    params = PW.dut_defaults(rtl, "arb")
    assert "IdxW" not in params, params
    decl, why = PW.resolve("[IdxW-1:0]", params)
    assert decl is None and "IdxW" in why, (decl, why)


# ── what stays refused ───────────────────────────────────────────────────────

def test_a_user_package_FUNCTION_still_refuses():
    """NO-LEAK. Evaluating `prim_util_pkg::vbits(N)` would mean running the
    design's own code. It is not arithmetic and it is not admitted."""
    rtl = ("module f #(\n"
           "  parameter  int Depth = 4,\n"
           "  localparam int PtrW  = util_pkg::vbits(Depth)\n"
           ") (output [PtrW-1:0] p);\nendmodule\n")
    pkg = ("package util_pkg;\n"
           "  function automatic integer vbits(integer v);\n"
           "    vbits = (v == 1) ? 1 : $clog2(v);\n"
           "  endfunction\n"
           "endpackage\n")
    params = PW.defaults_from_sources([("u.sv", pkg), ("f.sv", rtl)], "f")
    assert params.get("Depth") == 4
    assert "PtrW" not in params, params
    decl, why = PW.resolve("[PtrW-1:0]", params)
    assert decl is None and "PtrW" in why, (decl, why)


def test_dollar_bits_refuses_and_says_so():
    """`$bits` needs the design's TYPE system, not integer arithmetic. It is
    the ONLY other `$` function the corpus uses in a constant declaration, and
    it is not admitted."""
    assert RB._int_expr("$bits(my_struct_t)", {}) is None
    rtl = ("module b #(localparam int W = $bits(my_t)) "
           "(input [W-1:0] d);\nendmodule\n")
    params = PW.dut_defaults(rtl, "b")
    assert "W" not in params, params
    decl, why = PW.resolve("[$bits(my_t)-1:0]", params)
    assert decl is None and "$bits" in why, (decl, why)


def test_an_unresolvable_expression_is_still_the_third_state():
    """Not "", not one bit, not a default -- None, with the symbol named."""
    for cell in ("[RUNTIME_N-1:0]", "[other_pkg::Missing-1:0]",
                 "[$bits(t)-1:0]"):
        decl, why = PW.resolve(cell, {"Known": 4})
        assert decl is None, (cell, decl)
        assert why, cell


# ── the control: nothing that resolved before resolves differently now ───────

@pytest.mark.parametrize("cell,params,want", [
    ("[aw-1:0]", {"aw": 10}, " [9:0]"),
    ("[dw-1:0]", {"dw": 32}, " [31:0]"),
    ("[2*size-1:0]", {"size": 8}, " [15:0]"),
    ("[31:0]", {}, " [31:0]"),
    ("[N-1:0]", {"N": 1}, ""),
    ("", {}, ""),
])
def test_adding_the_new_scopes_does_not_move_an_old_answer(cell, params, want):
    """THE CONTROL. Every new name only ADDS to the scope, so an expression that
    already evaluated must evaluate to the SAME number with a package scope
    present as without one."""
    assert PW.resolve(cell, params)[0] == want
    wider = dict(params)
    wider.update({"bus_pkg::BUS_DW": 32, "bus_pkg::NumRegs": 4, "Spare": 77})
    assert PW.resolve(cell, wider)[0] == want


def test_the_scope_marker_is_not_silently_rewritten():
    """The scope operator is rewritten to a name sequence before parsing. If
    that sequence is ALREADY in the text the rewrite is ambiguous, so the
    expression refuses rather than being mangled into something else."""
    poisoned = f"a{RB._SCOPE_SEP}b"
    assert RB._int_expr(poisoned, {poisoned: 4}) is None
