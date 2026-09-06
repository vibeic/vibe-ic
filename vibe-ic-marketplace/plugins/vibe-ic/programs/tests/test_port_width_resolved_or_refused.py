"""A port width the generators could not resolve had TWO different wrong
answers, and this pins both of them shut.

THE DEFECT. A port declared `input [aw-1:0] adr` parses to the width cell
`[aw-1:0]`. `aw` is a parameter of the DUT's own header; it does not exist in
the scope of the testbench module that declares the stimulus. Two generators
did two different wrong things with that cell:

  SILENT  `design_one_shot_runner.step_full_stack_tb_gen` matched only a
          LITERAL `[N:M]` and emitted "" otherwise -- i.e. `reg adr = 0;`, ONE
          BIT of a wide port. iverilog accepts that with a port-width padding
          warning, the simulation runs, and the step reports CONNECTIVITY_PASS
          over a bus that is not connected. Measured in a PUBLISHED artefact:
          a 32-bit port declared `reg x = 0;`.

  LOUD    `testbench_gen` copied the cell VERBATIM, so `reg [aw-1:0] adr;`
          reached iverilog:
              error: Unable to bind parameter `aw' in `tb_<case>'
              error: Dimensions must be a constant with no unknown or high-Z bits.
          rc=2, and every L10 unit TB for that DUT died.

Both are the same missing step: nobody EVALUATED the expression against the
parameter defaults the DUT itself declares.

THE NON-MONOTONICITY, which is the part that made it hard to see. The silent
path's early `return ""` also skipped the L9 `msb`/`lsb` branch below it. So a
port carrying BOTH the RTL width cell AND the L9 numbers resolved to one bit,
while the SAME port with the width cell DELETED resolved correctly to `[9:0]`.
Deleting evidence improved the answer. `test_more_input_is_not_a_worse_answer`
is that control, and it must now give the same answer in both directions.

THE REFUSAL. When the cell cannot be evaluated -- an unknown symbol, no
parameter header, a shape that is not a single packed dimension -- the width is
NOT defaulted, NOT narrowed to one bit, and NOT guessed. The generator refuses
by name and the step FAILS saying which port and which symbol. A wrong answer
that says PASS is worse than no answer.

chip-AGNOSTIC: the module names, parameter names and widths here are ordinary
Verilog; no chip, SKU, vendor or PDK literal appears.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import design_one_shot_runner as P2   # noqa: E402
import testbench_gen as TBG           # noqa: E402
import _port_width as PW              # noqa: E402

_HAS_IVERILOG = shutil.which("iverilog") is not None

# A DUT whose ports are declared over its OWN parameters -- the ordinary shape
# of a bus-attached core.
_PARAM_RTL = (
    "module core_top #(parameter aw = 10, parameter dw = 32)\n"
    "  (input clk,\n"
    "   input rst_n,\n"
    "   input  [aw-1:0] adr,\n"
    "   input  [dw-1:0] wdat,\n"
    "   output [dw-1:0] rdat,\n"
    "   output ack);\n"
    "  assign rdat = wdat;\n"
    "  assign ack  = 1'b1;\n"
    "endmodule\n"
)
_PARAM_L9 = {"top_module": "core_top", "top_ports": [
    {"name": "clk", "direction": "input"},
    {"name": "rst_n", "direction": "input"},
    {"name": "adr", "direction": "input"},
    {"name": "wdat", "direction": "input"},
    {"name": "rdat", "direction": "output"},
    {"name": "ack", "direction": "output"}]}

# The same DUT with NO parameter header -- `aw` is declared nowhere, so the
# width is genuinely underivable and the only honest answer is a refusal.
_UNRESOLVABLE_RTL = (
    "module core_top\n"
    "  (input clk,\n"
    "   input rst_n,\n"
    "   input  [aw-1:0] adr,\n"
    "   output ack);\n"
    "  assign ack = 1'b1;\n"
    "endmodule\n"
)


def _seed(tmp_path, l9, rtl_text, name="core_top"):
    proj = tmp_path / "proj"
    gd = P2._pl.generated_docs_dir(proj)
    gd.mkdir(parents=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(l9))
    rtl = P2._pl.rtl_dir(proj)
    rtl.mkdir(parents=True)
    (rtl / f"{name}.v").write_text(rtl_text)
    return proj, rtl


# ── the resolver itself ──────────────────────────────────────────────────────

def test_resolver_evaluates_over_the_dut_own_defaults():
    assert PW.resolve("[aw-1:0]", {"aw": 10})[0] == " [9:0]"
    assert PW.resolve("[dw-1:0]", {"dw": 32})[0] == " [31:0]"
    assert PW.resolve("[2*size-1:0]", {"size": 8})[0] == " [15:0]"
    assert PW.resolve("[31:0]", {})[0] == " [31:0]"        # literal needs nothing
    assert PW.resolve("", {})[0] == ""                     # a scalar really is 1 bit
    assert PW.resolve(None, {})[0] == ""


def test_resolver_refuses_by_name_and_never_defaults():
    decl, why = PW.resolve("[aw-1:0]", {})
    assert decl is None                    # not "", not " [0:0]", not a guess
    assert "aw" in why, why
    decl, why = PW.resolve("[aw-1:0]", {"dw": 32})
    assert decl is None and "aw" in why, why
    # a shape that is not a single packed dimension is refused, not called 1 bit
    decl, why = PW.resolve("[3:0][7:0]", {})
    assert decl is None, (decl, why)


def test_resolver_reads_the_dut_parameter_header():
    assert PW.dut_defaults(_PARAM_RTL, "core_top") == {"aw": 10, "dw": 32}
    assert PW.dut_defaults(_UNRESOLVABLE_RTL, "core_top") == {}


def test_more_input_is_not_a_worse_answer():
    """THE CONTROL. Deleting the width cell must not improve the answer.

    Pre-fix this asserted-false in the most damning way available: `both` gave
    "" (one bit) and `less` -- strictly less information about the same port --
    gave the correct " [9:0]".
    """
    both = {"width_decl": "[aw-1:0]", "msb": 9, "lsb": 0}
    less = dict(both)
    del less["width_decl"]
    assert P2._v643_width_decl(less) == " [9:0]"
    assert P2._v643_width_decl(both) == P2._v643_width_decl(less)


# ── consumer 1: the full-stack TB (the SILENT path) ──────────────────────────

def test_full_stack_tb_declares_the_bus_at_its_real_width(tmp_path):
    proj, _ = _seed(tmp_path, _PARAM_L9, _PARAM_RTL)
    res = P2.step_full_stack_tb_gen(proj, "chip_top")
    assert res.status != "FAIL", res.detail
    body = list(P2._pl.sim_full_stack_dir(proj).glob("tb_*_full.v"))[0].read_text()
    assert "reg [9:0] adr = 0;" in body, body
    assert "reg [31:0] wdat = 0;" in body, body
    assert "wire [31:0] rdat;" in body, body
    # the pre-fix text: a wide bus bound one bit wide, which still PASSED
    assert "reg adr = 0;" not in body
    assert "reg wdat = 0;" not in body


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog not on this host")
def test_full_stack_tb_compiles_at_full_width(tmp_path):
    proj, rtl = _seed(tmp_path, _PARAM_L9, _PARAM_RTL)
    P2.step_full_stack_tb_gen(proj, "chip_top")
    tb = list(P2._pl.sim_full_stack_dir(proj).glob("tb_*_full.v"))[0]
    r = subprocess.run(
        ["iverilog", "-g2012", "-o", str(tmp_path / "a.out"),
         str(tb), str(rtl / "core_top.v")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_full_stack_tb_refuses_an_underivable_width(tmp_path):
    """No parameter header -> the step FAILS by name and writes NO TB.

    The alternative -- declare it one bit and carry on -- is the defect.
    """
    l9 = {"top_module": "core_top", "top_ports": [
        {"name": "clk", "direction": "input"},
        {"name": "rst_n", "direction": "input"},
        {"name": "adr", "direction": "input"},
        {"name": "ack", "direction": "output"}]}
    proj, _ = _seed(tmp_path, l9, _UNRESOLVABLE_RTL)
    res = P2.step_full_stack_tb_gen(proj, "chip_top")
    assert res.status == "FAIL", (res.status, res.detail)
    assert "adr" in res.detail and "aw" in res.detail, res.detail
    assert not list(P2._pl.sim_full_stack_dir(proj).glob("tb_*_full.v"))


# ── consumer 2: the L10 unit TBs (the LOUD path) ─────────────────────────────

def test_unit_tb_resolve_dut_returns_literal_widths(tmp_path):
    proj, _ = _seed(tmp_path, _PARAM_L9, _PARAM_RTL)
    mod, ports, why = TBG.resolve_dut(proj, "core_top")
    assert mod == "core_top", why
    widths = {n: w for _d, w, n in ports}
    assert widths["adr"] == "[9:0]", widths
    assert widths["wdat"] == "[31:0]", widths
    assert widths["rdat"] == "[31:0]", widths
    assert widths["clk"] == "", widths
    # the pre-fix value, which iverilog could not bind
    assert "[aw-1:0]" not in "".join(widths.values())


def test_unit_tb_refuses_an_underivable_width(tmp_path):
    proj, _ = _seed(tmp_path, _PARAM_L9, _UNRESOLVABLE_RTL)
    mod, ports, why = TBG.resolve_dut(proj, "core_top")
    assert mod is None and ports == [], (mod, ports)
    assert "adr" in why and "aw" in why, why


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog not on this host")
def test_the_verbatim_cell_is_what_iverilog_rejects(tmp_path):
    """The one-line control behind the LOUD half, both directions.

    `[aw-1:0]` in a TB scope is an elaboration error; `[9:0]` is not. That is
    the whole of the defect, and the reason a resolver -- not a copy -- is
    needed.
    """
    bad = tmp_path / "bad.v"
    bad.write_text("module tb_bad;\n  reg [aw-1:0] adr;\n"
                   "  initial $finish;\nendmodule\n")
    good = tmp_path / "good.v"
    good.write_text("module tb_good;\n  reg [9:0] adr;\n"
                    "  initial $finish;\nendmodule\n")
    rb = subprocess.run(["iverilog", "-g2012", "-o", str(tmp_path / "b.out"),
                         str(bad)], capture_output=True, text=True)
    rg = subprocess.run(["iverilog", "-g2012", "-o", str(tmp_path / "g.out"),
                         str(good)], capture_output=True, text=True)
    assert rb.returncode != 0 and "aw" in rb.stderr, rb.stderr
    assert rg.returncode == 0, rg.stderr


# ── the width cell no parameter table can resolve ────────────────────────────
# Measured on the corpus: three instantiation-graph ROOTS -- modules a TB really
# would bind to -- declare a width over something that is not a parameter at all:
#   caravel_user_project::user_project_wrapper   `[`MPRJ_IO_PADS-1:0]`  a MACRO
#   edge_llm_accel::fakeram45_2048x39            `[BITS-1:0]`, no param header
#   opentitan_aes prim_* (17)                    `[IdxW-1:0]`, a localparam
# No parameter table can evaluate those. The L9 extraction measured the same
# ports independently, and the #629 RTL reconcile used to THROW THOSE NUMBERS
# AWAY -- so the flow refused on a width it actually knew.

_MACRO_RTL = (
    "`define IO_PADS 38\n"
    "module pad_top (input clk,\n"
    "                input  [`IO_PADS-1:0] io_in,\n"
    "                output [`IO_PADS-1:0] io_out);\n"
    "  assign io_out = io_in;\n"
    "endmodule\n"
)
_MACRO_L9 = {"top_module": "pad_top", "top_ports": [
    {"name": "clk", "direction": "input", "width": 1},
    {"name": "io_in", "direction": "input", "width": 38, "msb": 37, "lsb": 0},
    {"name": "io_out", "direction": "output", "width": 38, "msb": 37, "lsb": 0}]}


def test_a_macro_width_is_resolved_from_the_l9_bounds(tmp_path):
    """The RTL cell is a `define; L9 measured the port. Use what is known."""
    proj, _ = _seed(tmp_path, _MACRO_L9, _MACRO_RTL, name="pad_top")
    res = P2.step_full_stack_tb_gen(proj, "pad_top")
    assert res.status != "FAIL", res.detail
    body = list(P2._pl.sim_full_stack_dir(proj).glob("tb_*_full.v"))[0].read_text()
    assert "reg [37:0] io_in = 0;" in body, body
    assert "wire [37:0] io_out;" in body, body
    assert "reg io_in = 0;" not in body          # the pre-fix 1-bit declaration


def test_the_l9_bounds_survive_the_rtl_reconcile(tmp_path):
    """The #629 reconcile replaces the port dicts with RTL-derived ones. It must
    CARRY the L9 numbers across, or the fallback above can never fire in the
    real flow even though the numbers were on disk the whole time."""
    proj, _ = _seed(tmp_path, _MACRO_L9, _MACRO_RTL, name="pad_top")
    P2.step_full_stack_tb_gen(proj, "pad_top")
    l9 = P2._port_width.l9_bounds(P2._pl.generated_docs_dir(proj))
    assert l9["io_in"]["msb"] == 37 and l9["io_in"]["lsb"] == 0, l9


def test_a_macro_width_with_no_l9_number_still_refuses(tmp_path):
    """NO-LEAK. The L9 fallback must not become a way to guess: strip the
    numbers and the same design refuses again, by name."""
    l9 = {"top_module": "pad_top", "top_ports": [
        {"name": "clk", "direction": "input"},
        {"name": "io_in", "direction": "input"},
        {"name": "io_out", "direction": "output"}]}
    proj, _ = _seed(tmp_path, l9, _MACRO_RTL, name="pad_top")
    res = P2.step_full_stack_tb_gen(proj, "pad_top")
    assert res.status == "FAIL", (res.status, res.detail)
    assert "io_in" in res.detail and "IO_PADS" in res.detail, res.detail


# ── the two generators must agree ────────────────────────────────────────────

def test_both_generators_resolve_the_same_width(tmp_path):
    """One resolver, two consumers — so a port cannot be 10 bits in one TB and
    1 bit in the other, which is exactly what the two separate code paths
    produced before."""
    proj, _ = _seed(tmp_path, _PARAM_L9, _PARAM_RTL)
    P2.step_full_stack_tb_gen(proj, "chip_top")
    fs = list(P2._pl.sim_full_stack_dir(proj).glob("tb_*_full.v"))[0].read_text()
    _mod, ports, _why = TBG.resolve_dut(proj, "core_top")
    unit = {n: w for _d, w, n in ports}
    assert unit["adr"] == "[9:0]" and "reg [9:0] adr = 0;" in fs
    assert unit["wdat"] == "[31:0]" and "reg [31:0] wdat = 0;" in fs


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
