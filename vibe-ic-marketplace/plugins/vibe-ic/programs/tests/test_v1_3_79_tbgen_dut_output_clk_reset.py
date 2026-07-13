"""Regression for the PR #123 fix (ORGANIC, v1.3.79 follow-up) —
step_full_stack_tb_gen bound a DUT **output/inout** port named `clk` /
`reset_n` to the TB's internal stimulus reg of the same name. That drives a
`reg` from a DUT output → iverilog "Unable to assign to unresolved wires" →
`reference_tb` FAIL on a CORRECT RTL (e.g. a display/video controller passing
its pixel clock through to the connector as an OUTPUT named `clk`).

Fix (in step_full_stack_tb_gen): only an **input**-direction `clk` / `reset_n`
binds the stimulus reg; an output/inout one is OBSERVED on a fresh
`<name>__dut_out` wire. Keyed on DIRECTION only — chip-AGNOSTIC.

ACCEPTANCE: a DUT whose `clk` port is an OUTPUT → the generated full-stack TB
compiles under iverilog (no unresolved-wire assign).

NEGATIVE no-leak: an ordinary INPUT `clk` / `reset_n` still binds the stimulus
directly (`.clk(clk)` with `clk` a driven reg) — the common case is unchanged.

chip-AGNOSTIC: generic clk/reset_n names + direction only; no chip/vendor/SKU
literal.
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

# A pass-through controller: `clk` and `reset_n` are DUT OUTPUTS (it forwards a
# generated clock + an active-low reset to a downstream connector), plus a
# normal data input/output so the TB has stimulus to drive.
_OUT_CLK_L9 = {
    "top_module": "passthru_top",
    "top_ports": [
        {"name": "sys_en", "direction": "input", "width": 1},
        {"name": "clk", "direction": "output", "width": 1},
        {"name": "reset_n", "direction": "output", "width": 1},
        {"name": "dout", "direction": "output", "width": 8, "msb": 7, "lsb": 0},
    ],
}
_OUT_CLK_RTL = (
    "module passthru_top(sys_en, clk, reset_n, dout);\n"
    " input sys_en; output clk; output reset_n; output [7:0] dout;\n"
    " assign clk = sys_en;\n"
    " assign reset_n = sys_en;\n"
    " assign dout = {8{sys_en}};\n"
    "endmodule\n")

# NEGATIVE control: a normal design with INPUT clk + reset_n.
_IN_CLK_L9 = {
    "top_module": "normal_top",
    "top_ports": [
        {"name": "clk", "direction": "input", "width": 1},
        {"name": "reset_n", "direction": "input", "width": 1},
        {"name": "dout", "direction": "output", "width": 8, "msb": 7, "lsb": 0},
    ],
}
_IN_CLK_RTL = (
    "module normal_top(clk, reset_n, dout);\n"
    " input clk; input reset_n; output [7:0] dout;\n"
    " reg [7:0] dout;\n"
    " always @(posedge clk or negedge reset_n)\n"
    "   if (!reset_n) dout <= 8'd0; else dout <= dout + 8'd1;\n"
    "endmodule\n")


def _seed(tmp_path, l9, rtl_text, top):
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


# ── (1) ACCEPTANCE — output clk/reset_n TB compiles ─────────────────────────

@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog not on this host")
def test_output_clk_reset_tb_compiles(tmp_path):
    proj, rtl = _seed(tmp_path, _OUT_CLK_L9, _OUT_CLK_RTL, "passthru_top")
    P2.step_full_stack_tb_gen(proj, "chip_top")
    tb = _tb(proj)
    r = subprocess.run(
        ["iverilog", "-g2012", "-o", str(tmp_path / "a.out"),
         str(tb), str(rtl / "passthru_top.v")],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_output_clk_reset_observed_on_dut_out_wire(tmp_path):
    """The output clk/reset_n bind to a fresh `<name>__dut_out` wire, NOT the
    stimulus reg (text check — no iverilog needed)."""
    proj, _ = _seed(tmp_path, _OUT_CLK_L9, _OUT_CLK_RTL, "passthru_top")
    P2.step_full_stack_tb_gen(proj, "chip_top")
    body = _tb(proj).read_text()
    # observed on the renamed wire
    assert "clk__dut_out" in body, "output clk not remapped to __dut_out wire"
    assert "reset_n__dut_out" in body
    assert ".clk(clk__dut_out)" in body
    assert ".reset_n(reset_n__dut_out)" in body
    # NOT bound to a same-named stimulus reg
    assert ".clk(clk)" not in body
    assert ".reset_n(reset_n)" not in body


# ── (2) NEGATIVE no-leak — INPUT clk/reset_n unchanged ──────────────────────

def test_input_clk_reset_still_bind_stimulus_NOLEAK(tmp_path):
    proj, _ = _seed(tmp_path, _IN_CLK_L9, _IN_CLK_RTL, "normal_top")
    P2.step_full_stack_tb_gen(proj, "chip_top")
    body = _tb(proj).read_text()
    # input clk/reset_n keep the direct stimulus binding
    assert ".clk(clk)" in body, "input clk lost its direct stimulus binding"
    assert ".reset_n(reset_n)" in body
    # and are NOT remapped to a dut-out wire
    assert "clk__dut_out" not in body
    assert "reset_n__dut_out" not in body


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog not on this host")
def test_input_clk_reset_tb_compiles_NOLEAK(tmp_path):
    proj, rtl = _seed(tmp_path, _IN_CLK_L9, _IN_CLK_RTL, "normal_top")
    P2.step_full_stack_tb_gen(proj, "chip_top")
    tb = _tb(proj)
    r = subprocess.run(
        ["iverilog", "-g2012", "-o", str(tmp_path / "a.out"),
         str(tb), str(rtl / "normal_top.v")],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
