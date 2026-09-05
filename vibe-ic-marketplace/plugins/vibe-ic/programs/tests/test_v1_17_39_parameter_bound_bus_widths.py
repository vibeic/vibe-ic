"""Parameter-bound bus widths and reset-under-active-controls (issue #2035, family 3).

Defect class distilled: "bus test widths differ from unoverridden DUT defaults;
reset under active controls is missed". The driver used to emit 32-bit address
and data everywhere. That is not a neutral default — on a design whose bus is
not 32 bits it produces a transaction that is ACCEPTED with the upper bits
silently dropped, which no waveform makes obvious.

The width is DECLARED in the design's own input: a module parameter with a
default, possibly overridden where the module is instantiated, feeding the range
of a bus-struct field. So it is READ (§4.05: design input only, never an oracle
or a golden output). When it cannot be read, the resolution REFUSES and names the
blocking symbol; the emission is then byte-identical to before rather than guessed.
"""
import subprocess
import sys

import pytest
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import register_bus_driver_gen as D            # noqa: E402
from test_v1_16_41_tb_drives_the_whole_dut import _tb   # noqa: E402

PKG = """
package bus_pkg;
  typedef struct packed {
    logic a_valid; logic [AW-1:0] a_address; logic [DW-1:0] a_data;
    logic [2:0] a_opcode; logic d_ready;
  } h2d_t;
  typedef struct packed {
    logic a_ready; logic d_valid; logic [DW-1:0] d_data;
  } d2h_t;
endpackage
"""
DUT = """
module dut_mod #(parameter int AW = 12, parameter int DW = 32) (
  input clk, input rst_ni,
  input bus_pkg::h2d_t tl_i, output bus_pkg::d2h_t tl_o);
endmodule
"""
TOP_PLAIN = "module top; dut_mod u (.clk(c), .tl_i(a), .tl_o(b)); endmodule"
TOP_OVERRIDE = "module top; dut_mod #(.DW(64)) u (.clk(c), .tl_i(a), .tl_o(b)); endmodule"

BUS = {"h2d_type": "bus_pkg::h2d_t", "d2h_type": "bus_pkg::d2h_t",
       "h2d": {"addr": "a_address", "wdata": "a_data"},
       "d2h": {"rdata": "d_data"}}


def _srcs(top):
    return [("pkg.sv", PKG), ("dut.sv", DUT), ("top.sv", top)]


# --------------------------------------------------------------------------
# 1. the contract is EXTRACTED from the design's own input
# --------------------------------------------------------------------------
def test_parameter_defaults_are_read_from_the_dut_header():
    assert D.dut_parameter_defaults(DUT, "dut_mod") == {"AW": 12, "DW": 32}


def test_unoverridden_defaults_bind_the_widths():
    w, why = D.resolve_bus_widths(_srcs(TOP_PLAIN), DUT, "dut_mod", BUS)
    assert w is not None, why
    # the address bus is 12 bits, NOT the 32 the emitter used to assume
    assert (w["addr"], w["data"]) == (12, 32)


# --------------------------------------------------------------------------
# 2. ALTERNATIVE-ARCHITECTURE CONTROL — an override is a legitimate design
# --------------------------------------------------------------------------
def test_instantiation_override_beats_the_module_default():
    """A 64-bit build is not a mistake to be corrected back to the default."""
    assert D.parameter_overrides(_srcs(TOP_OVERRIDE), "dut_mod") == {"DW": 64}
    w, why = D.resolve_bus_widths(_srcs(TOP_OVERRIDE), DUT, "dut_mod", BUS)
    assert w is not None, why
    assert w["data"] == 64 and w["addr"] == 12
    assert w["overridden"] == ["DW"]


# --------------------------------------------------------------------------
# 3. UNRESOLVED IS REFUSED BY NAME — never a silent 32
# --------------------------------------------------------------------------
def test_unresolvable_width_refuses_and_names_the_symbol():
    bad = DUT.replace("parameter int DW = 32", "parameter int OTHER = 5")
    w, why = D.resolve_bus_widths(_srcs(TOP_PLAIN), bad, "dut_mod", BUS)
    assert w is None
    assert "DW" in why and "unresolved" in why


def test_missing_struct_refuses_and_says_so():
    w, why = D.resolve_bus_widths([("dut.sv", DUT)], DUT, "dut_mod", BUS)
    assert w is None and "no packed struct" in why


# --------------------------------------------------------------------------
# 4. the resolved contract BINDS THE EMISSION
# --------------------------------------------------------------------------
def test_emission_binds_to_the_resolved_widths():
    body = _tb(widths={"addr": 12, "data": 64})
    assert "task automatic bus_write(input [11:0] addr," in body
    assert "input [63:0] data);" in body
    assert "reg [63:0] rdata;" in body
    assert "32'h" not in body, "a 32-bit literal survived on a 64-bit bus"


def test_no_resolved_contract_leaves_the_emission_byte_identical():
    """The control that matters most: a design whose widths cannot be read is
    driven exactly as it was before this change, not guessed at differently."""
    body = _tb()
    assert "task automatic bus_write(input [31:0] addr," in body
    assert "reg [31:0] rdata;" in body
    assert "// --- reset asserted WHILE the controls are active ---" not in body


# --------------------------------------------------------------------------
# 5. reset under ACTIVE controls
# --------------------------------------------------------------------------
def test_reset_is_exercised_while_the_controls_are_active():
    body = _tb(widths={"addr": 12, "data": 32})
    assert "// --- reset asserted WHILE the controls are active ---" in body
    lines = body.splitlines()
    cfg = next(i for i, l in enumerate(lines) if "configuration FIRST" in l)
    rst = next(i for i, l in enumerate(lines) if "reset asserted WHILE" in l)
    assert cfg < rst, "reset is exercised before anything is configured"
    end = next(i for i, l in enumerate(lines)
               if "end reset-under-active-controls" in l)
    assert any("after reset under active controls" in l
               for l in lines[rst:end]), "the reset condition is never observed"
    assert any("reprogram" in l for l in lines[rst:end])


def test_second_reset_input_is_driven_with_the_primary_one():
    body = _tb(widths={"addr": 12, "data": 32})
    lines = body.splitlines()
    rst = next(i for i, l in enumerate(lines) if "reset asserted WHILE" in l)
    end = next(i for i, l in enumerate(lines)
               if "end reset-under-active-controls" in l)
    seg = "\n".join(lines[rst:end])
    assert "rst_shadowed_ni = 1'b0;" in seg and "rst_shadowed_ni = 1'b1;" in seg


# --------------------------------------------------------------------------
# 6. REACHED THROUGH THE GENERAL FRONT DOOR
# --------------------------------------------------------------------------
def test_front_door_resolves_and_passes_the_width_contract():
    """`known_answer_vector_tb_gen` is the ordinary Phase-2 entry point. No
    harness, no benchmark name, no design id — it must reach the contract on its
    own or nobody gets the fix."""
    src = (PROGRAMS / "known_answer_vector_tb_gen.py").read_text()
    assert "resolve_bus_widths(" in src
    assert "widths=_widths" in src
    assert "bus widths: {_wwhy}" in src


def test_extraction_is_deterministic():
    a = D.resolve_bus_widths(_srcs(TOP_OVERRIDE), DUT, "dut_mod", BUS)[0]
    b = D.resolve_bus_widths(_srcs(TOP_OVERRIDE), DUT, "dut_mod", BUS)[0]
    assert a == b


def test_unparsable_width_expression_refuses_rather_than_guessing():
    """A SystemVerilog width expression the resolver cannot evaluate (here
    `$clog2(...)`) must REFUSE. Added because a mutation that returned 32 for an
    unparsable expression survived the first version of this file — the tests
    covered the unknown-symbol path but not the unparsable-expression path."""
    pkg = PKG.replace("logic [AW-1:0] a_address;",
                      "logic [$clog2(AW)-1:0] a_address;")
    w, why = D.resolve_bus_widths(
        [("pkg.sv", pkg), ("dut.sv", DUT), ("top.sv", TOP_PLAIN)],
        DUT, "dut_mod", BUS)
    assert w is None, f"guessed a width instead of refusing: {w}"
    assert "unresolved" in why and "a_address" in why


# --------------------------------------------------------------------------
# A width expression is DESIGN INPUT, so it must not be able to wedge the flow.
#
# Found by auditing my own code rather than by a failing test: `_int_expr`
# whitelisted Pow and LShift, so `[9**9**9-1:0]` in a design's own package
# parsed to a legal tree of allowed nodes and then computed FOREVER with no
# diagnostic -- measured, the process had to be killed at 20s. Every operand is
# now bounded and an exponent must RESOLVE small, so an unreasonable expression
# is REFUSED like any other unresolvable width instead of hanging.
# --------------------------------------------------------------------------
@pytest.mark.parametrize("expr,want", [
    ("8", 8), ("AW-1", 11), ("AW*2", 24), ("(AW+4)-1", 15),
    ("2**16", 65536), ("1<<5", 32),
    ("2**AW", 4096), ("1<<AW", 4096),      # parameter exponents are ordinary SV
])
def test_legitimate_width_expressions_still_resolve(expr, want):
    assert D._int_expr(expr, {"AW": 12}) == want


@pytest.mark.parametrize("expr", [
    "9**9**9",          # the one that hung: a legal tree that never terminates
    "1<<99999999",      # shift distance that allocates without bound
    "2**BIG",           # exponent resolves, but to something absurd
    "99999999999",      # a literal that is not a width
])
def test_unreasonable_width_expressions_refuse_instead_of_hanging(expr):
    """Run in a SUBPROCESS with a timeout, deliberately.

    An in-process `assert elapsed < 1` cannot fail when the call never returns --
    it hangs the whole suite instead, and a hung CI is worse than a red one.
    Measured: removing the bounds made this file hang rather than go red, which
    is why the check is shaped this way. Out of process, a regression is a clean
    FAILURE naming the expression."""
    code = (f"import sys; sys.path.insert(0, {str(PROGRAMS)!r});"
            f"import register_bus_driver_gen as R;"
            f"print(R._int_expr({expr!r}, {{'AW': 12, 'BIG': 10**9}}))")
    try:
        r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                           text=True, timeout=15)
    except subprocess.TimeoutExpired:
        raise AssertionError(
            f"_int_expr({expr!r}) did not return within 15s -- an unbounded "
            f"width expression out of a design file can wedge the flow")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "None", r.stdout


def test_an_unreasonable_width_in_a_package_refuses_by_name():
    """End to end: the hostile expression reaches resolve_bus_widths through the
    design's own package and comes back as a NAMED refusal, not a hang.

    Out of process for the same reason as the test above -- in-process this
    HANGS the suite when the bounds regress instead of failing, which is exactly
    what happened when the bounds were mutated away."""
    code = (
        "import sys; sys.path.insert(0, %r)\n"
        "import register_bus_driver_gen as D\n"
        "pkg = %r\n"
        "w, why = D.resolve_bus_widths([('pkg.sv', pkg), ('dut.sv', %r),\n"
        "                               ('top.sv', %r)], %r, 'dut_mod', %r)\n"
        "print(w is None, 'unresolved' in why, 'd_data' in why)\n"
    ) % (str(PROGRAMS),
         PKG.replace("logic [DW-1:0] d_data;", "logic [9**9**9-1:0] d_data;"),
         DUT, TOP_PLAIN, DUT, BUS)
    try:
        r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                           text=True, timeout=20)
    except subprocess.TimeoutExpired:
        raise AssertionError(
            "resolve_bus_widths did not return within 20s on a package carrying "
            "an unbounded width expression -- design input can wedge the flow")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "True True True", r.stdout
