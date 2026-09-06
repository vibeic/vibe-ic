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


# The L9 extraction for the DUT below. It carries NO msb/lsb, on purpose: this
# file is about resolving the width from the RTL's own constants, and supplying
# L9 numbers would let the resolver answer from those instead and hide whether
# the harvest works at all.
_L9 = {"top_module": "core_top", "top_ports": [
    {"name": "clk", "direction": "input"},
    {"name": "rst_n", "direction": "input"},
    {"name": "adr", "direction": "input"},
    {"name": "wdat", "direction": "input"},
    {"name": "rdat", "direction": "output"},
    {"name": "ack", "direction": "output"}]}


def _seed(tmp_path, rtl_text, name="core_top"):
    """A minimal project: L9 beside one RTL file, the shape both generators read."""
    proj = tmp_path / "proj"
    gd = P2._pl.generated_docs_dir(proj)
    gd.mkdir(parents=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(_L9))
    rtl = P2._pl.rtl_dir(proj)
    rtl.mkdir(parents=True)
    (rtl / f"{name}.v").write_text(rtl_text)
    return proj, rtl


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


def test_a_package_that_is_NOT_imported_does_not_leak_its_name():
    """THE CASE THAT MAKES IMPORT-SCOPING LOAD BEARING, not bookkeeping.

    A name can be defined by several packages at once with DIFFERENT values.
    Flattening every package in the source set into one unqualified scope would
    resolve the width to whichever definition happened to be reachable, and the
    resulting number is not a guess a reader would ever see -- it is a plain
    wrong bus width that says PASS.

    Three packages define `NumAlerts` here. The module imports exactly one, and
    that one is the answer; the other two are visible only under their scope.
    """
    p_two = "package two_pkg;\n  parameter int NumAlerts = 2;\nendpackage\n"
    p_three = "package three_pkg;\n  parameter int NumAlerts = 3;\nendpackage\n"
    p_four = "package four_pkg;\n  parameter int NumAlerts = 4;\nendpackage\n"
    rtl = ("module m\n  import two_pkg::*;\n"
           "  (input [NumAlerts-1:0] alert_rx_i);\nendmodule\n")
    srcs = [("a.sv", p_two), ("b.sv", p_three), ("c.sv", p_four),
            ("m.sv", rtl)]
    params = PW.defaults_from_sources(srcs, "m")
    assert params["NumAlerts"] == 2, params
    assert params["three_pkg::NumAlerts"] == 3
    assert params["four_pkg::NumAlerts"] == 4
    assert PW.resolve("[NumAlerts-1:0]", params)[0] == " [1:0]"

    # ...and importing a different one gives that one's number, which is what
    # proves the line above reads the IMPORT and not the source order.
    other = rtl.replace("two_pkg::*", "three_pkg::*")
    p2 = PW.defaults_from_sources(
        [("a.sv", p_two), ("b.sv", p_three), ("c.sv", p_four),
         ("m.sv", other)], "m")
    assert p2["NumAlerts"] == 3, p2
    assert PW.resolve("[NumAlerts-1:0]", p2)[0] == " [2:0]"


def test_a_constant_derived_ACROSS_packages_and_over_a_slash():
    """The two additions meeting in one constant, which is the shape that
    actually occurs: a package states a value over ANOTHER package's constant
    and Verilog's integer `/`."""
    a = "package a_pkg;\n  parameter int NumRegsIv = 4;\nendpackage\n"
    b = ("package b_pkg;\n  parameter int unsigned SliceSize = 16;\n"
         "  parameter int unsigned NumSlices = a_pkg::NumRegsIv * 32 "
         "/ SliceSize;\nendpackage\n")
    rtl = ("module m\n  import b_pkg::*;\n"
           "  (output [NumSlices-1:0] we_o);\nendmodule\n")
    params = PW.defaults_from_sources(
        [("a.sv", a), ("b.sv", b), ("m.sv", rtl)], "m")
    assert params["NumSlices"] == 8, params
    assert PW.resolve("[NumSlices-1:0]", params)[0] == " [7:0]"


def test_a_module_default_written_over_a_PACKAGE_constant_resolves():
    """The seam between the two harvests, and it was a hole.

    `parameter int DATA_WIDTH = top_pkg::TL_DW` is a module's OWN default
    stated over a PACKAGE constant. Harvesting the header against nothing but
    itself left DATA_WIDTH unknown and every port declared over it refusing, on
    a number stated in a file the same run had already read. The header and body
    harvests are seeded with what is in scope before them.
    """
    rtl = ("module m\n  import bus_pkg::*;\n"
           "#(parameter int DATA_WIDTH = bus_pkg::BUS_DW,\n"
           "  parameter int MASK_WIDTH = DATA_WIDTH/8)\n"
           "  (input [DATA_WIDTH-1:0] d, input [MASK_WIDTH-1:0] be);\n"
           "endmodule\n")
    params = PW.defaults_from_sources([("p.sv", _PKG), ("m.sv", rtl)], "m")
    assert params["DATA_WIDTH"] == 32, params
    assert params["MASK_WIDTH"] == 4, params          # ...and over `/` as well
    assert PW.resolve("[DATA_WIDTH-1:0]", params)[0] == " [31:0]"
    assert PW.resolve("[MASK_WIDTH-1:0]", params)[0] == " [3:0]"


def test_without_the_package_that_same_default_refuses():
    """THE OTHER DIRECTION. Take the package out of the source set and both
    constants go back to unknown -- and the port refuses BY NAME, which is what
    proves the line above reads the package and not a default."""
    rtl = ("module m\n  import bus_pkg::*;\n"
           "#(parameter int DATA_WIDTH = bus_pkg::BUS_DW)\n"
           "  (input [DATA_WIDTH-1:0] d);\nendmodule\n")
    params = PW.defaults_from_sources([("m.sv", rtl)], "m")
    assert "DATA_WIDTH" not in params, params
    decl, why = PW.resolve("[DATA_WIDTH-1:0]", params)
    assert decl is None and "DATA_WIDTH" in why, (decl, why)


def test_the_modules_own_name_still_wins_over_the_seed():
    """Seeding must not let a package silently redefine the module's own
    parameter. The seed is what is in scope BEFORE the module speaks."""
    rtl = ("module m\n  import bus_pkg::*;\n"
           "#(parameter int NumRegs = 9)\n"
           "  (input [NumRegs-1:0] q);\nendmodule\n")
    params = PW.defaults_from_sources([("p.sv", _PKG), ("m.sv", rtl)], "m")
    assert params["NumRegs"] == 9, params             # not the package's 4
    assert PW.resolve("[NumRegs-1:0]", params)[0] == " [8:0]"


def test_a_body_constant_may_also_be_written_over_a_package_constant():
    rtl = ("module m\n  import bus_pkg::*;\n  (input [LOCAL_W-1:0] d);\n"
           "  localparam int LOCAL_W = bus_pkg::BUS_DW/2;\n"
           "endmodule\n")
    params = PW.defaults_from_sources([("p.sv", _PKG), ("m.sv", rtl)], "m")
    assert params["LOCAL_W"] == 16, params
    assert PW.resolve("[LOCAL_W-1:0]", params)[0] == " [15:0]"


def test_one_package_declared_TWICE_with_two_values_is_ambiguous():
    """MEASURED IN THE CORPUS, not invented: a source set can contain the same
    package twice — a vendor copy and a docs copy — agreeing on most constants
    and DISAGREEING on one. Keeping whichever file sorted first would resolve a
    width to a number the other copy contradicts, and nothing would say so.

    The names the two copies AGREE on are still resolved. Only the contested one
    is dropped, so a width over it refuses BY NAME.
    """
    a = ("package dup_pkg;\n  parameter int SAME = 8;\n"
         "  parameter int CONTESTED = 2;\nendpackage\n")
    b = ("package dup_pkg;\n  parameter int SAME = 8;\n"
         "  parameter int CONTESTED = 1;\nendpackage\n")
    got = RB.package_constants([("a.sv", a), ("b.sv", b)])
    assert got["dup_pkg"]["SAME"] == 8, got
    assert "CONTESTED" not in got["dup_pkg"], got

    rtl = ("module m\n  import dup_pkg::*;\n"
           "  (input [SAME-1:0] ok, input [CONTESTED-1:0] bad);\nendmodule\n")
    params = PW.defaults_from_sources(
        [("a.sv", a), ("b.sv", b), ("m.sv", rtl)], "m")
    assert PW.resolve("[SAME-1:0]", params)[0] == " [7:0]"
    decl, why = PW.resolve("[CONTESTED-1:0]", params)
    assert decl is None and "CONTESTED" in why, (decl, why)


def test_one_package_declared_twice_that_AGREES_still_resolves():
    """The control: what is refused is the DISAGREEMENT, not the duplication."""
    a = "package dup_pkg;\n  parameter int W = 8;\nendpackage\n"
    got = RB.package_constants([("a.sv", a), ("b.sv", a)])
    assert got["dup_pkg"]["W"] == 8, got
    rtl = ("module m\n  import dup_pkg::*;\n"
           "  (input [W-1:0] d);\nendmodule\n")
    params = PW.defaults_from_sources(
        [("a.sv", a), ("b.sv", a), ("m.sv", rtl)], "m")
    assert PW.resolve("[W-1:0]", params)[0] == " [7:0]"


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


# ── the two CONSUMERS, not just the resolver ─────────────────────────────────
#
# A resolver that returns the right string and a GENERATOR that emits it are two
# different claims. These drive the shipped entry points end to end, on the two
# shapes this change added, so a future refactor that stops passing the source
# set through cannot pass on the unit tests alone.

_V1995_RTL = (
    "module core_top (clk, rst_n, adr, wdat, rdat, ack);\n"
    "   parameter BITS = 39;\n"
    "   parameter ADDR_WIDTH = 11;\n"
    "   input                    clk;\n"
    "   input                    rst_n;\n"
    "   input  [ADDR_WIDTH-1:0]  adr;\n"
    "   input  [BITS-1:0]        wdat;\n"
    "   output [BITS-1:0]        rdat;\n"
    "   output                   ack;\n"
    "   assign rdat = wdat;\n"
    "   assign ack  = 1'b1;\n"
    "endmodule\n"
)

_PKG_RTL = (
    "package w_pkg;\n"
    "  localparam int DW = 32;\n"
    "  localparam int AW = DW/4;\n"
    "endpackage\n"
)
_PKG_DUT = (
    "module core_top\n  import w_pkg::*;\n"
    "  (input clk,\n   input rst_n,\n"
    "   input  [AW-1:0] adr,\n"
    "   input  [w_pkg::DW-1:0] wdat,\n"
    "   output [DW-1:0] rdat,\n"
    "   output ack);\n"
    "  assign rdat = wdat;\n  assign ack = 1'b1;\n"
    "endmodule\n"
)


def test_unit_tb_resolves_a_verilog_1995_body_width(tmp_path):
    proj, _ = _seed(tmp_path, _V1995_RTL)
    mod, ports, why = TBG.resolve_dut(proj, "core_top")
    assert mod == "core_top", why
    widths = {n: w for _d, w, n in ports}
    assert widths["adr"] == "[10:0]", widths
    assert widths["wdat"] == "[38:0]", widths
    assert widths["rdat"] == "[38:0]", widths
    assert widths["clk"] == "", widths


def test_full_stack_tb_declares_a_verilog_1995_bus_at_its_real_width(tmp_path):
    proj, _ = _seed(tmp_path, _V1995_RTL)
    res = P2.step_full_stack_tb_gen(proj, "chip_top")
    assert res.status != "FAIL", res.detail
    body = list(P2._pl.sim_full_stack_dir(proj).glob("tb_*_full.v"))[0].read_text()
    assert "reg [10:0] adr = 0;" in body, body
    assert "reg [38:0] wdat = 0;" in body, body
    assert "wire [38:0] rdat;" in body, body
    # the pre-fix text: a wide bus bound ONE BIT wide, which still said PASS
    assert "reg adr = 0;" not in body
    assert "reg wdat = 0;" not in body


def test_both_consumers_resolve_a_package_width_the_same_way(tmp_path):
    proj, rtl = _seed(tmp_path, _PKG_DUT)
    (rtl / "w_pkg.sv").write_text(_PKG_RTL)
    mod, ports, why = TBG.resolve_dut(proj, "core_top")
    assert mod == "core_top", why
    widths = {n: w for _d, w, n in ports}
    assert widths["adr"] == "[7:0]", widths          # AW = DW/4 = 8
    assert widths["wdat"] == "[31:0]", widths        # scope-qualified
    assert widths["rdat"] == "[31:0]", widths        # imported unqualified

    res = P2.step_full_stack_tb_gen(proj, "chip_top")
    assert res.status != "FAIL", res.detail
    body = list(P2._pl.sim_full_stack_dir(proj).glob("tb_*_full.v"))[0].read_text()
    assert "reg [7:0] adr = 0;" in body, body
    assert "reg [31:0] wdat = 0;" in body, body
    assert "wire [31:0] rdat;" in body, body


def test_the_package_file_is_what_makes_that_work(tmp_path):
    """THE OTHER DIRECTION, at the CONSUMER. Same DUT, package file absent:
    both generators must REFUSE, naming the port — not emit a one-bit bus."""
    proj, _rtl = _seed(tmp_path, _PKG_DUT)
    mod, ports, why = TBG.resolve_dut(proj, "core_top")
    assert mod is None, (mod, ports, why)
    assert "adr" in why or "wdat" in why or "rdat" in why, why

    res = P2.step_full_stack_tb_gen(proj, "chip_top")
    assert res.status == "FAIL", res.detail
    assert "not derivable" in res.detail, res.detail


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
