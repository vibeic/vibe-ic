"""Regression for ORGANIC #643 (P0) — step_full_stack_tb_gen emitted an
UNCOMPILABLE connectivity TB for SoC-class wrappers (multi-bit buses + power
pins), failing iverilog (rc!=0) → reference_tb FAIL → ~25 downstream Phase-2/3
steps blocked. Three deterministic generator defects (caravel user_project_
wrapper clean-room, 7th benchmark IC):

  1. ILLEGAL IDENTIFIER leaked — a corrupted L9 port name (`vccd1_/_vssd1`,
     a '/' in the id) was emitted verbatim, making the whole TB uncompilable.
  2. MULTI-BIT ports mis-declared 1-bit — `[31:0] wbs_dat_i`, `[127:0]
     la_data_in`, `[37:0] io_in` lost their `[msb:lsb]` width (the #629
     RTL-surface reconciliation parsed but discarded the width cell).
  3. POWER inout pins DRIVEN as stimulus — `io=='POWER'` inouts were declared
     `reg ..._drive` + `assign`ed, instead of tied for `USE_POWER_PINS`.

Fix (in step_full_stack_tb_gen): skip illegal identifiers; declare every port
at its REAL width (from the parsed RTL surface / L9); tie (not drive)
POWER/ground inout pins.

SUPERSEDED CLAUSE, kept visible on purpose: this file used to say that a
parameterized `[size-1:0]` "falls back to 1-bit so it stays elaboratable". It
did stay elaboratable, and it was WRONG — a wide bus declared one bit binds
bit 0 and floats the rest, and the step reported CONNECTIVITY_PASS over it. The
width cell is now EVALUATED over the DUT's own parameter defaults, and a cell
that cannot be evaluated REFUSES BY NAME instead of being narrowed.

ACCEPTANCE (issue): an SoC-wrapper L9 with a multi-bit bus + a POWER inout →
the generated TB compiles under iverilog.

NEGATIVE no-leak: a parameterized-width datapath top still compiles (width
falls back to 1-bit, not a non-constant dimension); a regular 1-bit design is
unchanged.

chip-AGNOSTIC: legal-identifier shape + generic power-rail vocabulary + numeric
width; no chip/vendor/SKU literal.
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

import design_one_shot_runner as P2  # noqa: E402

_HAS_IVERILOG = shutil.which("iverilog") is not None

# SoC wrapper: 32-bit bus + 128-bit bus + 38-bit bus + POWER inouts (incl a
# CORRUPTED slashed-name power pin) + an analog inout.
_SOC_L9 = {
    "top_module": "soc_top",
    "top_ports": [
        {"name": "wb_clk_i", "direction": "input", "width": 1},
        {"name": "wbs_dat_i", "direction": "input",
         "width": 32, "msb": 31, "lsb": 0},
        {"name": "wbs_dat_o", "direction": "output",
         "width": 32, "msb": 31, "lsb": 0},
        {"name": "la_data_in", "direction": "input",
         "width": 128, "msb": 127, "lsb": 0},
        {"name": "io_in", "direction": "input",
         "width": 38, "msb": 37, "lsb": 0},
        {"name": "vccd1", "direction": "inout", "width": 1, "io": "POWER"},
        {"name": "vssd1", "direction": "inout", "width": 1, "io": "POWER"},
        {"name": "vccd1_/_vssd1", "direction": "inout",
         "width": 1, "io": "POWER"},                       # illegal id
        {"name": "analog_io", "direction": "inout",
         "width": 29, "msb": 28, "lsb": 0},
    ],
}
_SOC_RTL = (
    "module soc_top(wb_clk_i,wbs_dat_i,wbs_dat_o,la_data_in,io_in,"
    "vccd1,vssd1,analog_io);\n"
    " input wb_clk_i; input [31:0] wbs_dat_i; output [31:0] wbs_dat_o;\n"
    " input [127:0] la_data_in; input [37:0] io_in;\n"
    " inout vccd1, vssd1; inout [28:0] analog_io;\n"
    " assign wbs_dat_o = wbs_dat_i;\nendmodule\n")


def _seed(tmp_path, l9, rtl_text, top="soc_top"):
    proj = tmp_path / "proj"
    gd = P2._pl.generated_docs_dir(proj)
    gd.mkdir(parents=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(l9))
    rtl = P2._pl.rtl_dir(proj)
    rtl.mkdir(parents=True)
    (rtl / f"{top}.v").write_text(rtl_text)
    return proj, rtl


def _tb(proj):
    return list((P2._pl.sim_full_stack_dir(proj)).glob("tb_*_full.v"))[0]


# ── (1) the acceptance: SoC-wrapper TB compiles ──────────────────────────────

@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog not on this host")
def test_soc_wrapper_tb_compiles(tmp_path):
    proj, rtl = _seed(tmp_path, _SOC_L9, _SOC_RTL)
    P2.step_full_stack_tb_gen(proj, "chip_top")
    tb = _tb(proj)
    r = subprocess.run(
        ["iverilog", "-g2012", "-o", str(tmp_path / "a.out"),
         str(tb), str(rtl / "soc_top.v")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_soc_wrapper_tb_structure(tmp_path):
    """The three defects are gone in the emitted text (no iverilog needed)."""
    proj, _ = _seed(tmp_path, _SOC_L9, _SOC_RTL)
    P2.step_full_stack_tb_gen(proj, "chip_top")
    body = _tb(proj).read_text()
    # (1) illegal identifier excluded
    assert "vccd1_/_vssd1" not in body
    # (2) multi-bit buses at real width
    for w in ("[31:0] wbs_dat_i", "[127:0] la_data_in", "[37:0] io_in",
              "[28:0] analog_io"):
        assert w in body, f"missing width decl: {w}"
    # (3) power pins tied — no _drive reg for vccd1/vssd1
    assert "vccd1_drive" not in body and "vssd1_drive" not in body
    assert "vccd1" in body and "vssd1" in body   # still bound to the DUT


# ── (2) NEGATIVE no-leak ─────────────────────────────────────────────────────

@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog not on this host")
def test_parameterized_width_still_compiles_NOLEAK(tmp_path):
    """A parameterized-width datapath top (`[size-1:0]`) must still compile —
    and must now compile AT ITS REAL WIDTH, not narrowed to one bit.

    Compiling was never the property that mattered here: the 1-bit declaration
    compiled too. `test_parameterized_width_is_resolved_not_narrowed` below
    asserts the part this test cannot see."""
    l9 = {"top_module": "mul_top", "top_ports": [
        {"name": "x", "direction": "input"},
        {"name": "p", "direction": "output"}]}
    rtl = ("module mul_top #(parameter size = 8) "
           "(input [size-1:0] x, output [2*size-1:0] p);\n"
           " assign p = x;\nendmodule\n")
    proj, rd = _seed(tmp_path, l9, rtl, top="mul_top")
    P2.step_full_stack_tb_gen(proj, "chip_top")
    tb = _tb(proj)
    r = subprocess.run(
        ["iverilog", "-g2012", "-o", str(tmp_path / "a.out"),
         str(tb), str(rd / "mul_top.v")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_parameterized_width_is_resolved_not_narrowed(tmp_path):
    """`[size-1:0]` with `size = 8` is EIGHT bits in the TB, not one.

    This is the assertion the compile test above structurally cannot make: the
    1-bit declaration this generator used to emit compiled perfectly well. What
    it did not do was connect the bus.
    """
    l9 = {"top_module": "mul_top", "top_ports": [
        {"name": "x", "direction": "input"},
        {"name": "p", "direction": "output"}]}
    rtl = ("module mul_top #(parameter size = 8) "
           "(input [size-1:0] x, output [2*size-1:0] p);\n"
           " assign p = x;\nendmodule\n")
    proj, _rd = _seed(tmp_path, l9, rtl, top="mul_top")
    P2.step_full_stack_tb_gen(proj, "chip_top")
    body = _tb(proj).read_text()
    assert "reg [7:0] x = 0;" in body, body
    assert "wire [15:0] p;" in body, body
    # the pre-fix text, which compiled and said CONNECTIVITY_PASS:
    assert "reg x = 0;" not in body


# ── (3) helper units ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("nm,ok", [
    ("wbs_dat_i", True), ("clk", True), ("_x", True), ("a$b", True),
    ("vccd1_/_vssd1", False), ("1abc", False), ("a b", False), ("", False)])
def test_legal_verilog_id(nm, ok):
    assert P2._v643_legal_verilog_id(nm) is ok


@pytest.mark.parametrize("nm,io,is_pwr", [
    ("vccd1", "POWER", True), ("vssd1", None, True), ("vdda1", None, True),
    ("vgnd", None, True), ("wbs_dat_i", None, False), ("clk", "DIGITAL", False),
    ("data", "POWER", True)])
def test_is_power_pin(nm, io, is_pwr):
    assert P2._v643_is_power_pin({"io": io}, nm) is is_pwr


@pytest.mark.parametrize("p,expect", [
    ({"width_decl": "[31:0]"}, " [31:0]"),
    ({"msb": 127, "lsb": 0}, " [127:0]"),
    ({"width": 38}, " [37:0]"),
    ({"width": 1}, ""),
    ({}, "")])
def test_width_decl(p, expect):
    assert P2._v643_width_decl(p) == expect


# ── the parameterized width cell ─────────────────────────────────────────────
# This case used to assert `""`, i.e. "declare the bus as ONE BIT and carry on".
# That is not a narrower answer, it is a WRONG one: `reg adr = 0;` binds bit 0
# of a wide port, leaves the rest floating, compiles with only a port-width
# padding warning, and the step then reports CONNECTIVITY_PASS over a bus that
# is not connected. The assertion is not relaxed here, it is REPLACED by a
# stronger one -- resolve it, or refuse it by name. Nothing may still be "".

def test_parameterized_width_resolves_over_the_dut_params():
    """A cell that EVALUATES over the DUT's own defaults gives literal bounds."""
    assert P2._v643_width_decl({"width_decl": "[size-1:0]"},
                               {"size": 32}) == " [31:0]"
    assert P2._v643_width_decl({"width_decl": "[2*size-1:0]"},
                               {"size": 8}) == " [15:0]"


def test_parameterized_width_refuses_by_name_when_unresolvable():
    """No params, no L9 numbers -> REFUSE, and say which symbol blocked it."""
    p = {"width_decl": "[size-1:0]"}
    assert P2._v643_width_decl(p) is None
    why = P2._v643_width_refusal(p)
    assert "size" in why, why
    # It must never come back as a width, least of all as one bit.
    assert P2._v643_width_decl(p) != ""


def test_width_decl_is_monotone_in_its_input():
    """#RB-18 THE BOTH CASE -- the case the table above could not express.

    Every row of the old table supplied EITHER a `width_decl` OR the L9
    `msb`/`lsb` numbers, never both, so the table could not see that the
    `width_decl` branch RETURNED EARLY and threw the L9 numbers away. The
    function was therefore non-monotone in its input: given both, it answered
    one bit; given strictly LESS (the same port with `width_decl` deleted) it
    answered `[9:0]` correctly. Deleting evidence improved the answer.

    Both directions must now give the SAME answer.
    """
    both = {"width_decl": "[aw-1:0]", "msb": 9, "lsb": 0}
    less = {"msb": 9, "lsb": 0}                      # the same port, width cell deleted
    assert P2._v643_width_decl(less) == " [9:0]"
    assert P2._v643_width_decl(both) == " [9:0]"
    assert P2._v643_width_decl(both) == P2._v643_width_decl(less)


def test_width_decl_prefers_the_dut_params_over_the_l9_numbers():
    """When the cell DOES evaluate, the RTL is the authority.

    The L9 numbers are a second, independent extraction; they are the fallback
    for a cell that cannot be evaluated, never an override of one that can.
    """
    p = {"width_decl": "[aw-1:0]", "msb": 3, "lsb": 0}
    assert P2._v643_width_decl(p, {"aw": 10}) == " [9:0]"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
