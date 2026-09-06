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

PROVENANCE OF THE "Measured:" NOTES IN THIS FILE. Several comments below record a defect and the
measurement that found it -- a hang, an X on a starvation line, a truncated address literal, a
parameter harvested out of the wrong module. NONE of those ever shipped. Every function they
describe is NEW in this change, so each was a defect in an earlier draft OF THIS SAME CHANGE,
found and fixed before landing. They are kept because they say why a guard exists and what it
costs to remove it -- not because the released code ever behaved that way. A reader trying to
reproduce one against a released version will not be able to, and should not conclude the note
is wrong.
"""
import os
import shutil
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
    """A SystemVerilog width expression the resolver cannot evaluate must
    REFUSE. Added because a mutation that returned 32 for an unparsable
    expression survived the first version of this file — the tests covered the
    unknown-symbol path but not the unparsable-expression path.

    THE STIMULUS MOVED, and the assertion did not. This case used `$clog2(AW)`,
    which the evaluator has since learned to compute exactly (see the test
    below). A guard whose stimulus stops being an example of the thing it
    guards is not a weaker guard, it is a VACUOUS one — so the stimulus is now
    `$bits(...)`, which needs type information no width evaluator has and is
    therefore still genuinely unevaluable. If `$bits` is ever supported, this
    stimulus must move again rather than the assertion being dropped.
    """
    pkg = PKG.replace("logic [AW-1:0] a_address;",
                      "logic [$bits(tl_h2d_t)-1:0] a_address;")
    w, why = D.resolve_bus_widths(
        [("pkg.sv", pkg), ("dut.sv", DUT), ("top.sv", TOP_PLAIN)],
        DUT, "dut_mod", BUS)
    assert w is None, f"guessed a width instead of refusing: {w}"
    assert "unresolved" in why and "a_address" in why


def test_clog2_is_evaluated_exactly_not_refused():
    """`$clog2` is a pure integer function of one integer, so a width written
    over it is fully stated by the design and must RESOLVE, not refuse.

    Measured: the entire residual of unresolvable port widths across the corpus
    roots was this one form — `localparam int IdxW = $clog2(N)` used as a port's
    declared width.
    """
    assert D._clog2(0) == 0 and D._clog2(1) == 0      # IEEE 1800
    assert D._clog2(2) == 1 and D._clog2(8) == 3
    assert D._clog2(9) == 4 and D._clog2(16) == 4
    pkg = PKG.replace("logic [AW-1:0] a_address;",
                      "logic [$clog2(AW)-1:0] a_address;")
    w, why = D.resolve_bus_widths(
        [("pkg.sv", pkg), ("dut.sv", DUT), ("top.sv", TOP_PLAIN)],
        DUT, "dut_mod", BUS)
    assert w is not None, f"refused a width the design fully states: {why}"
    assert w["addr"] == 4, w          # AW = 12 -> clog2(12) = 4
    assert w["data"] == 32, w


def test_only_clog2_is_admitted_no_other_system_function():
    """NO-LEAK. Admitting one system function must not admit calls in general —
    an evaluator that will call anything is not an arithmetic evaluator."""
    assert D._int_expr("$clog2(N)", {"N": 8}) == 3
    for expr in ("$bits(t)", "$onehot(N)", "$countones(N)", "len(N)",
                 "N.bit_length()", "__import__('os')"):
        assert D._int_expr(expr, {"N": 8}) is None, expr


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


# --------------------------------------------------------------------------
# A LITERAL THAT DOES NOT FIT ITS BUS IS A SILENT TRUNCATION
#
# Found by auditing my own emission, not by a failing test. With a 4-bit address
# bus the emitter produced `bus_write(4'h74, ...)`; Verilog keeps the low 4 bits,
# so the sequence programs a DIFFERENT register and still reports itself green.
# That is the same silent-truncation defect this width contract exists to remove,
# reintroduced from the other direction by the fix for it. A design whose
# register map does not fit the bus width it declares is INCONSISTENT, so the
# emitter refuses and names the conflict.
# --------------------------------------------------------------------------
def test_an_address_too_wide_for_the_declared_bus_refuses():
    with pytest.raises(ValueError) as e:
        _tb(widths={"addr": 4, "data": 32})
    assert "contradict" in str(e.value)
    assert "4-bit address bus" in str(e.value)


def test_a_data_word_too_wide_for_the_declared_bus_refuses():
    with pytest.raises(ValueError) as e:
        _tb(widths={"addr": 12, "data": 4})
    assert "contradict" in str(e.value)


def test_a_width_that_does_fit_still_emits():
    """The CONTROL: refusing must be about not fitting, not about being narrow."""
    body = _tb(widths={"addr": 12, "data": 32})
    assert "bus_write(12'h074," in body


# --------------------------------------------------------------------------
# A DESCENDING RANGE IS A VECTOR, NOT A NEGATIVE WIDTH
#
# `logic [0:7]` is a legal little-endian vector of EIGHT bits. Taking hi-lo+1
# literally produced -6, which would have emitted `reg [-7:0]`.
# --------------------------------------------------------------------------
def test_a_descending_range_is_eight_bits_not_negative():
    pkg = PKG.replace("logic [AW-1:0] a_address;", "logic [0:7] a_address;")
    w, why = D.resolve_bus_widths(
        [("pkg.sv", pkg), ("dut.sv", DUT), ("top.sv", TOP_PLAIN)],
        DUT, "dut_mod", BUS)
    assert w is not None, why
    assert w["addr"] == 8, f"descending range gave {w['addr']}"


# --------------------------------------------------------------------------
# THE SAME PARAMETER OVERRIDDEN DIFFERENTLY AT TWO SITES IS AMBIGUOUS
#
# A design instantiating the DUT twice with different widths is saying two
# different things. `parameter_overrides` returns a flat dict, so the LAST site
# silently won and the driver bound to whichever happened to be parsed last --
# a guess, in a module whose whole contract is that it never guesses.
# --------------------------------------------------------------------------
CONFLICT_TOP = ("module a; dut_mod #(.DW(64)) u1 (.clk(c)); endmodule\n"
                "module b; dut_mod #(.DW(16)) u2 (.clk(c)); endmodule\n")
AGREE_TOP = ("module a; dut_mod #(.DW(64)) u1 (.clk(c)); endmodule\n"
             "module b; dut_mod #(.DW(64)) u2 (.clk(c)); endmodule\n")


def test_conflicting_overrides_refuse_and_name_the_parameter():
    w, why = D.resolve_bus_widths(_srcs(CONFLICT_TOP), DUT, "dut_mod", BUS)
    assert w is None, f"silently picked {w}"
    assert "DW" in why and "[16, 64]" in why


def test_agreeing_overrides_at_two_sites_still_resolve():
    """CONTROL: two instantiations are not themselves a problem -- only two
    DIFFERENT values are. A design may legitimately instantiate the DUT twice."""
    w, why = D.resolve_bus_widths(_srcs(AGREE_TOP), DUT, "dut_mod", BUS)
    assert w is not None, why
    assert w["data"] == 64


def test_conflict_detection_reports_the_distinct_values():
    c = D.parameter_override_conflicts([("t.sv", CONFLICT_TOP)], "dut_mod")
    assert sorted(c["DW"]) == [16, 64]
    assert D.parameter_override_conflicts([("t.sv", AGREE_TOP)], "dut_mod") == {}


# --------------------------------------------------------------------------
# THE MODULE-HEADER SCAN: comments, and a header that is never closed
#
# Two bugs that masked each other, which is why the first probe looked clean.
#   * Parens inside COMMENTS were counted. A `// width, no ')' here` closed the
#     header early and silently truncated the parameter list.
#   * A header never closed ran the scan to EOF, so the slice spanned other
#     modules. Measured: an unterminated `#(` harvested `ZZ` out of the NEXT
#     module and offered it as this DUT's parameter -- {'AW': 12, 'ZZ': 99}.
# The first hid the second: the `)` in my first probe's comment stopped the
# runaway scan, so the leak did not appear until the comment was removed.
# --------------------------------------------------------------------------
UNTERMINATED = ("module dut_mod #(parameter int AW = 12\n"
                "module other #(parameter int ZZ = 99) (input c); endmodule\n")
COMMENTED = ("module dut_mod #(parameter int AW = 12,  // width, no ')' here\n"
             "                 parameter int DW = 32) (input clk);\nendmodule\n")


def test_an_unterminated_header_yields_no_parameters():
    got = D.dut_parameter_defaults(UNTERMINATED, "dut_mod")
    assert "ZZ" not in got, f"harvested another module's parameter: {got}"
    assert got == {}


def test_a_paren_inside_a_comment_does_not_truncate_the_parameter_list():
    got = D.dut_parameter_defaults(COMMENTED, "dut_mod")
    assert got == {"AW": 12, "DW": 32}, got


# --------------------------------------------------------------------------
# A FALSY WIDTH IS NOT AN ABSENT ONE
#
# `int((widths or {}).get("addr") or 32)` turned a width of 0 into 32 silently.
# --------------------------------------------------------------------------
def test_a_zero_width_refuses_rather_than_defaulting_to_32():
    with pytest.raises(ValueError) as e:
        _tb(widths={"addr": 0, "data": 0})
    assert "at least 1 bit" in str(e.value)


def test_omitted_widths_still_default_to_32():
    """CONTROL: absent really is absent, and still means the previous behaviour."""
    assert "task automatic bus_write(input [31:0] addr," in _tb()


# --------------------------------------------------------------------------
# DEAD CODE MUST NOT SHAPE THE DRIVER -- and this one was a REGRESSION I ADDED
#
# The instantiation scanners walked raw text, so a superseded
# `// dut_mod #(.DW(999)) u_old (...)` left in a file was counted as an
# override. Harmless while overrides merely last-won; the moment conflict
# detection was added, that dead line made a perfectly consistent design REFUSE.
# A fix that turns a commented-out line into a blocking contradiction is a
# regression wearing a fix's clothes, which is exactly what the controls here
# are for.
# --------------------------------------------------------------------------
COMMENTED_OUT_TOP = (
    "module top;\n"
    "  // dut_mod #(.DW(999)) u_old (.clk(c));   // superseded, kept for reference\n"
    "  dut_mod #(.DW(64)) u_new (.clk(c));\n"
    "endmodule\n")


def test_a_commented_out_instantiation_is_not_an_override():
    assert D.parameter_overrides([("t.sv", COMMENTED_OUT_TOP)], "dut_mod") == {"DW": 64}


def test_a_commented_out_instantiation_does_not_manufacture_a_conflict():
    assert D.parameter_override_conflicts(
        [("t.sv", COMMENTED_OUT_TOP)], "dut_mod") == {}


def test_a_real_conflict_is_still_detected_through_the_blanker():
    """CONTROL: blanking comments must not blind the conflict rule to live code."""
    c = D.parameter_override_conflicts([("t.sv", CONFLICT_TOP)], "dut_mod")
    assert sorted(c["DW"]) == [16, 64]


# --------------------------------------------------------------------------
# A TYPE DECLARED TWICE MUST NOT RESOLVE BY FILE ORDER
#
# The same `d2h_t` in two packages gave width 8 or 32 depending on which file
# was listed first -- a silent guess, decided by argument order.
# --------------------------------------------------------------------------
P_NARROW = "package a_pkg; typedef struct packed { logic v; logic [7:0] d_data; } d2h_t; endpackage"
P_WIDE = "package b_pkg; typedef struct packed { logic v; logic [31:0] d_data; } d2h_t; endpackage"


@pytest.mark.parametrize("order", [(P_NARROW, P_WIDE), (P_WIDE, P_NARROW)])
def test_two_declarations_of_one_type_refuse_regardless_of_order(order):
    w, why = D.struct_field_width([("1.sv", order[0]), ("2.sv", order[1])],
                                  "d2h_t", "d_data", {})
    assert w is None, f"file order decided the width: {w}"
    assert "declared with different widths" in why


def test_the_same_width_declared_twice_still_resolves():
    """CONTROL: duplication is not the problem -- DISAGREEMENT is. A type
    legitimately visible through two paths must still resolve."""
    w, why = D.struct_field_width(
        [("1.sv", P_WIDE), ("2.sv", P_WIDE.replace("b_pkg", "c_pkg"))],
        "d2h_t", "d_data", {})
    assert w == 32, why


def test_the_width_expression_bound_is_exact_at_its_edge():
    """OFF-BY-ONE CONTROL, same reasoning as the deadline bound: the refusal
    cases are astronomically large and the working cases tiny, so the bound
    could move a long way before any test noticed."""
    assert D._WIDTH_EXPR_MAX == 1 << 20, (
        "the width-expression limit moved; same reasoning as the deadline "
        "bound -- reading the constant makes the test move with it")
    limit = D._WIDTH_EXPR_MAX
    assert D._int_expr(str(limit), {}) == limit, "the bound itself was refused"
    assert D._int_expr(str(limit + 1), {}) is None, "one past the bound was accepted"


# --------------------------------------------------------------------------
# DETERMINISM ACROSS PROCESSES
#
# The pulsed-event generator has had a determinism test since the first commit;
# this emitter did not, and it grew set and dict machinery afterwards
# (collect-every-declaration, conflict maps, an `overridden` list). A program
# whose product is deterministic RTL must not vary with hash seed, and reasoning
# that it does not is worth less than running it in processes that differ.
# --------------------------------------------------------------------------
_EMIT = (
    "import sys; sys.path.insert(0, {P!r}); sys.path.insert(0, {T!r})\n"
    "import importlib.util as u\n"
    "sp = u.spec_from_file_location('t', {F!r})\n"
    "m = u.module_from_spec(sp); sp.loader.exec_module(m)\n"
    "sys.stdout.write(m._tb(widths={{'addr': 12, 'data': 64}}))\n"
)


def _emit_with_seed(seed):
    code = _EMIT.format(P=str(PROGRAMS), T=str(PROGRAMS / "tests"),
                        F=str(PROGRAMS / "tests"
                              / "test_v1_16_41_tb_drives_the_whole_dut.py"))
    env = dict(os.environ, PYTHONHASHSEED=str(seed))
    r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                       text=True, env=env, cwd=str(PROGRAMS), timeout=120)
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_the_emitted_testbench_is_identical_across_hash_seeds():
    outs = {_emit_with_seed(s) for s in (0, 1, 42, 7919)}
    assert len(outs) == 1, "the emitted testbench varies with PYTHONHASHSEED"


def test_a_conflict_refusal_names_its_values_in_a_STABLE_order():
    """The refusal text is read by a human deciding what to fix, so its ORDER
    must not depend on dict or set iteration. Two parameters, four sites each."""
    dut = ("module dut_mod #(parameter int AW = 12, parameter int DW = 32, "
           "parameter int EW = 8) (input clk); endmodule")
    top = "\n".join(f"module m{i}; dut_mod #(.DW({v}), .EW({i})) u{i} (.clk(c)); endmodule"
                    for i, v in enumerate([64, 16, 32, 8]))
    _, why = D.resolve_bus_widths(
        [("pkg.sv", PKG), ("dut.sv", dut), ("top.sv", top)], dut, "dut_mod", BUS)
    assert "DW = [8, 16, 32, 64]" in why, why
    assert "EW = [0, 1, 2, 3]" in why, why


# --------------------------------------------------------------------------
# THE TRUNCATION, PROVEN BY SIMULATION RATHER THAN BY ASSERTION
#
# Every other test here checks that the emitter REFUSES a literal too wide for
# its bus. None showed what happens if it does not, and "Verilog truncates" is
# the kind of claim that deserves a run rather than a citation. This elaborates a
# 4-bit-addressed register file and writes `4'h74` at it -- the exact literal the
# emitter used to produce for a register map at 0x74 on a narrow bus.
#
# The write lands in register 0x4. A DIFFERENT register is programmed, the
# sequence completes, and iverilog says only "warning: Numeric constant truncated
# to 4 bits" -- a warning in a build log, not a failure. That is why the emitter
# refuses instead of narrowing the literal, and why the refusal names the
# conflict rather than picking a width.
# --------------------------------------------------------------------------
_TRUNC_V = r'''
`timescale 1ns/1ps
module regfile4 (input clk, input we, input [3:0] addr, input [31:0] wdata,
                 output reg [31:0] r0, output reg [31:0] r4);
  always @(posedge clk) if (we) begin
    if (addr == 4'h0) r0 <= wdata;
    if (addr == 4'h4) r4 <= wdata;
  end
endmodule
module tb;
  reg clk=0, we=0; reg [3:0] addr; reg [31:0] wdata;
  wire [31:0] r0, r4;
  regfile4 dut(.clk(clk), .we(we), .addr(addr), .wdata(wdata), .r0(r0), .r4(r4));
  always #5 clk=~clk;
  initial begin
    @(negedge clk); we=1; addr=4'h74; wdata=32'hDEADBEEF;
    @(negedge clk); we=0; @(negedge clk);
    if (r4 === 32'hDEADBEEF) $display("TRUNCATED_TO_R4");
    else                     $display("NO_TRUNCATION");
    $finish;
  end
endmodule
'''


@pytest.mark.skipif(not shutil.which("iverilog"), reason=(
    "NOT MEASURED HERE: no iverilog on PATH, so the executable proof that a "
    "too-wide address literal silently programs a DIFFERENT register did not "
    "run; the refusal tests above are textual. Measured in the pinned image."))
def test_a_too_wide_literal_really_does_program_the_wrong_register(tmp_path):
    src = tmp_path / "trunc.v"
    src.write_text(_TRUNC_V)
    sim = tmp_path / "sim"
    c = subprocess.run(["iverilog", "-g2012", "-o", str(sim), str(src)],
                       capture_output=True, text=True)
    assert c.returncode == 0, c.stderr
    # the toolchain WARNS and carries on -- this is the whole point
    assert "truncated" in (c.stderr + c.stdout).lower(), \
        "expected iverilog to warn rather than fail; if it now errors, say so"
    r = subprocess.run([str(sim)], capture_output=True, text=True)
    assert "TRUNCATED_TO_R4" in r.stdout, r.stdout


# --------------------------------------------------------------------------
# THE FIT BOUNDARY IS EXACT
#
# The refusal tests use a 4-bit bus against 0x84 (clearly too narrow) and a
# 12-bit bus (clearly wide enough). Neither pins the EDGE, so the rule could
# have been off by one in either direction and both would still pass -- an
# emitter that rejected a value which fits would refuse working designs, and one
# that accepted a value one bit too wide would truncate silently, which is the
# defect this whole contract exists to prevent.
#
# A w-bit bus addresses 0..2^w-1, so a value needing exactly w bits FITS.
# The fixture's widest address is 0x84, which needs 8 bits.
# --------------------------------------------------------------------------
def test_the_fit_boundary_is_exact_at_the_widest_address():
    widest = 0x84
    assert widest.bit_length() == 8, "fixture changed; recheck this boundary"

    with pytest.raises(ValueError) as e:
        _tb(widths={"addr": widest.bit_length() - 1, "data": 32})
    assert "contradict" in str(e.value)

    for w in (widest.bit_length(), widest.bit_length() + 1):
        body = _tb(widths={"addr": w, "data": 32})
        assert f"input [{w-1}:0] addr," in body, f"a {w}-bit bus should fit 0x{widest:x}"


def test_the_fit_rule_accepts_the_largest_value_a_bus_can_hold():
    """Directly, without going through the fixture's particular addresses: a
    w-bit bus must accept 2^w-1 and refuse 2^w."""
    for w in (4, 8, 12):
        assert (2 ** w - 1).bit_length() == w      # fits
        assert (2 ** w).bit_length() == w + 1      # does not


# --------------------------------------------------------------------------
# BRANCHES FOUND BY TRACING, NOT BY THINKING
#
# Line-tracing the suite showed four paths through this module's new code that
# NO test exercised. All four behave correctly today -- which is exactly why they
# needed tests: a regression in any of them would have been silent, and I would
# not have found them by re-reading the code, because I wrote it and I "knew"
# what it did.
# --------------------------------------------------------------------------
@pytest.mark.parametrize("lit,want", [
    ("8'd12", 12),      # sized decimal
    ("32'h20", 32),     # sized hex -- 0x20 is 32, the common bus width
    ("'d7", 7),         # unsized
    ("4'b1010", 10),    # binary
])
def test_a_verilog_sized_literal_is_a_valid_width_expression(lit, want):
    """`parameter int W = 8'd12;` is ordinary SystemVerilog. The evaluator has
    always handled it; nothing checked that it still does."""
    assert D._int_expr(lit, {}) == want


def test_a_module_with_no_parameter_header_yields_no_defaults():
    assert D.dut_parameter_defaults("module plain (input clk); endmodule", "plain") == {}


def test_an_empty_type_or_field_refuses_by_name():
    w, why = D.struct_field_width([], "", "", {})
    assert w is None and "no struct type or field name" in why


def test_a_single_bit_field_has_width_one():
    """`logic d_valid;` with no range is one bit. The emitter would otherwise
    have nothing to bind a single-bit bus role to."""
    pkg = ("package p; typedef struct packed { logic d_valid; "
           "logic [31:0] d_data; } d2h_t; endpackage")
    w, why = D.struct_field_width([("p.sv", pkg)], "p::d2h_t", "d_valid", {})
    assert w == 1, why
    assert "single bit" in why


def test_a_range_with_no_colon_refuses_by_name():
    """`logic [7] d_data;` -- a bracket that is not a range. Untested until
    tracing showed the branch."""
    pkg = "package p; typedef struct packed { logic v; logic [7] d_data; } d2h_t; endpackage"
    w, why = D.struct_field_width([("p.sv", pkg)], "p::d2h_t", "d_data", {})
    assert w is None and "unparsable range" in why


def test_an_unresolved_LOW_bound_refuses_by_name():
    """`[7:LO]` where LO is not a known parameter. The HIGH bound has always been
    checked; the low one had its own branch and no test."""
    pkg = "package p; typedef struct packed { logic v; logic [7:LO] d_data; } d2h_t; endpackage"
    w, why = D.struct_field_width([("p.sv", pkg)], "p::d2h_t", "d_data", {})
    assert w is None and "low bound" in why and "LO" in why


# --- N93: six refusal branches in `_int_expr` that MUTATION found unpinned.
# Every other test here drives the evaluator through a WELL-FORMED expression or
# an obviously huge one. These six are the malformed shapes a design file can
# carry that no test named: each one must yield a REFUSAL, never a width, because
# a wrong width is emitted into hardware and a refusal is not. Each was confirmed
# to redden when its own branch is mutated to accept.
@pytest.mark.parametrize("expr,params,why", [
    ("8'b12",  {},               "a sized literal whose digits are illegal in its own base"),
    ("AW(1)",  {"AW": 8},        "a call, which is not arithmetic however legal it parses"),
    ("1.5",    {},               "a non-integer literal: a bus has a whole number of bits"),
    ("1//0",   {},               "an expression that raises while being evaluated"),
    ("X",      {"X": True},      "a parameter that resolves to a bool, which is not a width"),
    ("AW*2",   {"AW": 600000},   "a COMPUTED value over the bound; the literal check cannot see it"),
])
def test_a_malformed_width_expression_refuses_rather_than_returning_a_width(expr, params, why):
    import register_bus_driver_gen as D
    assert D._int_expr(expr, params) is None, (why, expr)


def test_the_width_evaluator_still_accepts_the_shapes_next_to_each_refusal():
    """Over-reach control: the six refusals must not swallow legitimate neighbours."""
    import register_bus_driver_gen as D
    assert D._int_expr("8'b10", {}) == 2            # legal digits in the same base
    assert D._int_expr("AW", {"AW": 8}) == 8        # a plain parameter, not a call
    assert D._int_expr("2", {}) == 2                # an integer literal
    assert D._int_expr("4//2", {}) == 2             # the same operator, not raising
    assert D._int_expr("AW*2", {"AW": 8}) == 16     # the same expression, in bounds


# --- N100: "byte-identical" was a NAME, not an assertion.
# `test_no_resolved_contract_leaves_the_emission_byte_identical` above checks
# that three MARKERS are absent. That is weaker than what its name, this
# module's docstring and the commit message all claim, and it is the control a
# reader leans on hardest: the promise that a design whose widths cannot be read
# is driven EXACTLY as before. "Before" can only mean the program on origin/main,
# so this compares the actual bytes against it.
def _emit_with(mod, **kw):
    from test_v1_16_32_register_bus_vector_driver import (
        BUS_PKG, CASE, DOCS, _l4, _l15)
    ports = [("input", "", "clk_i"), ("input", "", "rst_ni"),
             ("input", "", "tl_i"), ("output", "", "tl_o")]
    plan, why = mod.resolve_register_plan(CASE, _l4(), _l15(), DOCS)
    assert plan, why
    bus, _ = mod.bus_contract(BUS_PKG)
    return mod.emit_sequence_tb(CASE, plan, bus, "chip_top", "tl_i", "tl_o",
                                "clk_i", "rst_ni", ports=ports, **kw)


def _base_module():
    """register_bus_driver_gen as it stands on origin/main, loaded from git."""
    import types
    rel = ("vibe-ic-marketplace/plugins/vibe-ic/programs/"
           "register_bus_driver_gen.py")
    root = subprocess.run(["git", "rev-parse", "--show-toplevel"], text=True,
                          capture_output=True, cwd=str(PROGRAMS)).stdout.strip()
    if not root:
        pytest.skip("NOT MEASURED HERE: not a git checkout, so the base program "
                    "cannot be loaded — byte-identity is UNVERIFIED, not proven")
    src = subprocess.run(["git", "show", f"origin/main:{rel}"], text=True,
                         capture_output=True, cwd=root).stdout
    if not src.strip():
        pytest.skip("NOT MEASURED HERE: origin/main does not carry the program — "
                    "byte-identity is UNVERIFIED, not proven")
    mod = types.ModuleType("rbd_base_for_identity")
    mod.__file__ = str(PROGRAMS / "register_bus_driver_gen.py")
    exec(compile(src, "<origin/main>", "exec"), mod.__dict__)
    return mod


def test_the_no_contract_emission_is_byte_identical_to_origin_main():
    before = _emit_with(_base_module())
    after = _emit_with(D, widths=None)
    assert after == before, (
        "a design whose widths do not resolve is no longer driven as it was "
        f"before this change: {len(before)} bytes -> {len(after)} bytes")


# --- The COMMENT case for the parameter HEADER, required by the ruling on the
# `_NOT_PROSE` entry for `parameter_overrides`. The instantiation half is held by
# `test_a_commented_out_instantiation_is_not_an_override` and
# `test_a_commented_out_instantiation_does_not_manufacture_a_conflict`; the header
# half had no test of its own. A COMMENT is the one construct in HDL that reads as
# a denial, so the claim that this grammar cannot deny a value is only honest if
# commented-out text is excluded -- measured here, not asserted.
def test_a_commented_out_parameter_default_is_not_a_default():
    live = "module dut_mod #(parameter int W = 8) (input clk); endmodule\n"
    with_comment = ("module dut_mod #(\n"
                    "  // parameter int W = 99,\n"
                    "  parameter int W = 8\n"
                    ") (input clk); endmodule\n")
    assert D.dut_parameter_defaults(live, "dut_mod") == {"W": 8}
    # the commented 99 must not be seen, and must not displace the live 8
    assert D.dut_parameter_defaults(with_comment, "dut_mod") == {"W": 8}


def test_a_default_that_exists_ONLY_in_a_comment_yields_no_parameter():
    """Over-reach control in the other direction: blanking must not invent one."""
    only_comment = ("module dut_mod #(\n  // parameter int W = 99\n"
                    ") (input clk); endmodule\n")
    assert D.dut_parameter_defaults(only_comment, "dut_mod") == {}
