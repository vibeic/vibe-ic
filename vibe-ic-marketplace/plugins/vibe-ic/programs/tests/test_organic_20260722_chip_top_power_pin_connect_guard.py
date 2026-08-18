#!/usr/bin/env python3
"""Regression for ORGANIC-20260722 — the auto-emitted chip_top wrapper
connected DUT power pins UNCONDITIONALLY.

Root cause pinned: `_autoemit_chip_top_wrapper` copies the wrapped DUT's ANSI
port list verbatim into the wrapper header (via `_chip_top_strip_output_storage`),
so a power/ground pin declared behind `` `ifdef USE_POWER_PINS `` keeps that guard
on the wrapper's OWN port face. But the `u_dut` instance previously connected
EVERY parsed port name unconditionally (`.vccd1(vccd1)`, `.vssd1(vssd1)`). Under
the synth define-set (`-DSYNTHESIS`, no `-DUSE_POWER_PINS`) the guarded
declaration is gone while the connection remains, binding to a DUT port that
does not exist — all three frontends correctly reject it:
  - slang: "port 'vccd1' does not exist in 'user_proj_example'"
  - sv2v : unknown bindings "vccd1","vssd1" ... in instance "u_dut"
  - yosys: "Module 'user_proj_example' ... does not have a port named 'vssd1'"
→ 0-byte netlist → yosys_synth FAIL rc=1 → the whole backend cascade blocked.

Fix (mirrors the reference-tb `_v645` convention): emit the power connections
inside a matching `` `ifdef USE_POWER_PINS `` block so declaration and connection
are guarded by the SAME macro. Then:
  - WITHOUT the define → neither the wrapper port nor the connection exists → OK.
  - WITH the define    → both exist → OK.

CONFOUND (why the prior caravel run passed): the defect is INDEPENDENT of the
top string — any top with no matching rtl/<top>.v file triggers wrapper emission
around the power-pinned DUT (test_top_name_independent). The prior run named
`user_project_wrapper`, which HAS a matching rtl file, so `_autoemit`
short-circuits at the file-existence check and dodges the path entirely
(test_top_with_matching_file_dodges). It is NOT a regression vs prior tooling.

chip-AGNOSTIC: `USE_POWER_PINS` is the universal sky130 / Caravel / OpenLane
convention; the guard shape carries no chip / vendor / SKU / rail literal. A DUT
with NO power pins is byte-identical to the pre-fix output (test_no_power_pins_*).
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROG_DIR = Path(__file__).resolve().parent.parent
if str(PROG_DIR) not in sys.path:
    sys.path.insert(0, str(PROG_DIR))
import design_one_shot_runner as P  # noqa: E402

_HAS_IVERILOG = shutil.which("iverilog") is not None

# ---------------------------------------------------------------------------
# Faithful minimal caravel structure: user_proj_example is the real DUT and
# carries the `ifdef USE_POWER_PINS power pins in its ANSI port list.
# ---------------------------------------------------------------------------
_DUT = """\
`default_nettype none
module user_proj_example #(
    parameter BITS = 32
)(
`ifdef USE_POWER_PINS
    inout vccd1,	// User area 1 1.8V supply
    inout vssd1,	// User area 1 digital ground
`endif
    input  wb_clk_i,
    input  wb_rst_i,
    input  [31:0] wbs_dat_i,
    output [31:0] wbs_dat_o,
    output wbs_ack_o
);
    reg [31:0] dat_o;
    reg ack_o;
    always @(posedge wb_clk_i or posedge wb_rst_i) begin
        if (wb_rst_i) begin
            dat_o <= 32'b0;
            ack_o <= 1'b0;
        end else begin
            dat_o <= wbs_dat_i + BITS;
            ack_o <= 1'b1;
        end
    end
    assign wbs_dat_o = dat_o;
    assign wbs_ack_o = ack_o;
endmodule
`default_nettype wire
"""

# The caravel canonical top: filename ends in _wrapper (skipped as a wrapper
# CANDIDATE) yet a FILE user_project_wrapper.v exists, so naming it as top
# short-circuits _autoemit at the file-existence check.
_WRAPPER = """\
`default_nettype none
module user_project_wrapper #(
    parameter BITS = 32
)(
`ifdef USE_POWER_PINS
    inout vccd1,
    inout vssd1,
`endif
    input  wb_clk_i,
    input  wb_rst_i,
    input  [31:0] wbs_dat_i,
    output [31:0] wbs_dat_o,
    output wbs_ack_o
);
    user_proj_example #(.BITS(BITS)) mprj (
`ifdef USE_POWER_PINS
        .vccd1(vccd1),
        .vssd1(vssd1),
`endif
        .wb_clk_i(wb_clk_i),
        .wb_rst_i(wb_rst_i),
        .wbs_dat_i(wbs_dat_i),
        .wbs_dat_o(wbs_dat_o),
        .wbs_ack_o(wbs_ack_o)
    );
endmodule
`default_nettype wire
"""

# A design with NO power pins — must be byte-identical to the pre-fix behaviour.
_NOPOWER = """\
`default_nettype none
module adder8 (
    input  [7:0] a,
    input  [7:0] b,
    input        cin,
    output [7:0] sum,
    output       cout
);
    assign {cout, sum} = a + b + cin;
endmodule
`default_nettype wire
"""


def _stage(tmp_path: Path, files: dict) -> tuple:
    """Create a project dir with phase2/stage1/rtl and the given files.
    Returns (project, rtl_dir)."""
    proj = tmp_path
    rtl = proj / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        (rtl / name).write_text(body)
    return proj, rtl


def _instance_region(txt: str) -> str:
    """The `<mod> u_dut ( ... );` instance body of the emitted wrapper."""
    i = txt.index("u_dut")
    j = txt.index(");", i)
    return txt[i:j + 2]


def _guarded_and_unconditional(region: str) -> tuple:
    """Split an instance region into (unconditional_part, guarded_part)."""
    marker = "`ifdef USE_POWER_PINS"
    if marker not in region:
        return region, ""
    head, rest = region.split(marker, 1)
    guarded = rest.split("`endif", 1)[0]
    tail = rest.split("`endif", 1)[1] if "`endif" in rest else ""
    return head + tail, guarded


# ---- the defect / fix: connection guarded, never unconditional --------------
def test_power_connections_guarded_not_unconditional(tmp_path):
    proj, rtl = _stage(tmp_path, {"user_proj_example.v": _DUT})
    emitted = P._autoemit_chip_top_wrapper(proj, rtl, "caravel_user_project")
    assert emitted is not None, "wrapper should be emitted for a non-matching top"
    txt = Path(emitted).read_text()

    # declaration is guarded (copied verbatim from the DUT)
    assert "`ifdef USE_POWER_PINS" in txt
    assert re.search(r"inout\s+vccd1", txt)

    region = _instance_region(txt)
    uncond, guarded = _guarded_and_unconditional(region)
    # THE FIX: the power connections live ONLY inside the `ifdef guard.
    assert ".vccd1(vccd1)" not in uncond, \
        "vccd1 connected UNCONDITIONALLY — the pre-fix defect"
    assert ".vssd1(vssd1)" not in uncond, \
        "vssd1 connected UNCONDITIONALLY — the pre-fix defect"
    assert ".vccd1(vccd1)" in guarded and ".vssd1(vssd1)" in guarded, \
        "power connections missing from the `ifdef USE_POWER_PINS block"
    # the ordinary ports stay unconditional
    for n in ("wb_clk_i", "wb_rst_i", "wbs_dat_i", "wbs_dat_o", "wbs_ack_o"):
        assert f".{n}({n})" in uncond


# ---- CONFOUND case (a) mechanism: top-name independent ----------------------
def test_top_name_independent(tmp_path):
    """The malformed connect is NOT specific to the string
    'caravel_user_project' — any non-matching top triggers the SAME wrapper
    around the power-pinned DUT (modulo the wrapper's module name)."""
    p1, r1 = _stage(tmp_path / "a", {"user_proj_example.v": _DUT})
    p2, r2 = _stage(tmp_path / "b", {"user_proj_example.v": _DUT})
    t1 = Path(P._autoemit_chip_top_wrapper(p1, r1, "caravel_user_project")).read_text()
    t2 = Path(P._autoemit_chip_top_wrapper(p2, r2, "some_other_top_xyz")).read_text()
    # normalise the wrapper module name so only the structure is compared
    n1 = t1.replace("caravel_user_project", "TOP")
    n2 = t2.replace("some_other_top_xyz", "TOP")
    assert n1 == n2, "wrapper structure differs by top name — should be identical"
    # and both are correctly guarded
    for t in (t1, t2):
        _, guarded = _guarded_and_unconditional(_instance_region(t))
        assert ".vccd1(vccd1)" in guarded


# ---- CONFOUND case (b): a top with a matching rtl file dodges the path -------
def test_top_with_matching_file_dodges(tmp_path):
    proj, rtl = _stage(tmp_path, {
        "user_proj_example.v": _DUT,
        "user_project_wrapper.v": _WRAPPER,
    })
    # user_project_wrapper.v exists → file-existence short-circuit → no wrapper
    assert P._autoemit_chip_top_wrapper(proj, rtl, "user_project_wrapper") is None


# ---- USE_POWER_PINS fixture: both port AND connection present ----------------
def test_use_power_pins_declaration_and_connection_present(tmp_path):
    proj, rtl = _stage(tmp_path, {"user_proj_example.v": _DUT})
    txt = Path(P._autoemit_chip_top_wrapper(
        proj, rtl, "caravel_user_project")).read_text()
    # declaration guarded
    decl_guarded = txt.split("`ifdef USE_POWER_PINS", 1)[1].split("`endif", 1)[0]
    assert re.search(r"inout\s+vccd1", decl_guarded)
    assert re.search(r"inout\s+vssd1", decl_guarded)
    # connection guarded by the SAME macro
    _, conn_guarded = _guarded_and_unconditional(_instance_region(txt))
    assert ".vccd1(vccd1)" in conn_guarded and ".vssd1(vssd1)" in conn_guarded


# ---- no-power design is UNAFFECTED (no `ifdef, unconditional connects) -------
def test_no_power_pins_unaffected(tmp_path):
    proj, rtl = _stage(tmp_path, {"adder8.v": _NOPOWER})
    txt = Path(P._autoemit_chip_top_wrapper(proj, rtl, "chip_top")).read_text()
    assert "`ifdef USE_POWER_PINS" not in txt, \
        "no power-pin guard should be emitted for a design without power pins"
    region = _instance_region(txt)
    for n in ("a", "b", "cin", "sum", "cout"):
        assert f".{n}({n})" in region


# ---- helper unit tests: _chip_top_power_pin_gated_names ----------------------
def test_gated_names_flat_guard():
    block = ("(\n`ifdef USE_POWER_PINS\n inout vccd1,\n inout vssd1,\n"
             "`endif\n input clk, output q)")
    g = P._chip_top_power_pin_gated_names(block)
    assert {"vccd1", "vssd1"} <= g
    assert "clk" not in g and "q" not in g


def test_gated_names_no_guard_empty():
    block = "( input clk, inout vccd1, output q )"
    g = P._chip_top_power_pin_gated_names(block)
    # NO `ifdef → nothing is gated (even a power-named pin stays unconditional,
    # matching its unconditional declaration).
    assert "vccd1" not in g


def test_gated_names_else_branch_not_gated():
    block = ("(\n`ifdef USE_POWER_PINS\n inout vccd1,\n"
             "`else\n input alt_pin,\n`endif\n input clk)")
    g = P._chip_top_power_pin_gated_names(block)
    assert "vccd1" in g
    assert "alt_pin" not in g  # `else branch is NOT under USE_POWER_PINS


def test_gated_names_unrelated_ifdef_not_gated():
    block = ("(\n`ifdef FEATURE_X\n input dbg,\n`endif\n input clk)")
    g = P._chip_top_power_pin_gated_names(block)
    assert "dbg" not in g and "clk" not in g


def test_gated_names_nested_ifdef_inside_upp():
    block = ("(\n`ifdef USE_POWER_PINS\n inout vccd1,\n"
             "`ifdef EXTRA\n inout vccd2,\n`endif\n`endif\n input clk)")
    g = P._chip_top_power_pin_gated_names(block)
    assert {"vccd1", "vccd2"} <= g  # nested-inside-UPP stays gated
    assert "clk" not in g


# ---- end-to-end compile self-consistency (iverilog) -------------------------
@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog not installed")
@pytest.mark.parametrize("define", ["SYNTHESIS", "USE_POWER_PINS"])
def test_wrapper_compiles_both_define_sets(tmp_path, define):
    proj, rtl = _stage(tmp_path, {"user_proj_example.v": _DUT})
    emitted = P._autoemit_chip_top_wrapper(proj, rtl, "caravel_user_project")
    assert emitted is not None
    r = subprocess.run(
        ["iverilog", "-g2012", f"-D{define}", "-o", str(tmp_path / "a.out"),
         str(rtl / "user_proj_example.v"), str(emitted)],
        capture_output=True, text=True)
    assert r.returncode == 0, (
        f"wrapper failed to compile under -D{define}:\n{r.stderr}")
