"""Regression for ORGANIC #645 (P0) — the #643 full-stack TB-gen connected DUT
power pins (`.vccd1(vccd1)`) UNCONDITIONALLY, but the reference_tb / oracle
compile omits `-DUSE_POWER_PINS` and the DUT RTL declares those supply ports
ONLY inside `` `ifdef USE_POWER_PINS ``. Result: `port vccd1 is not a port of
u_dut` → iverilog rc=2 → reference_tb FAIL → ~25 downstream steps blocked.

Fix (option B, mirrors the RTL's own gating): `step_full_stack_tb_gen` emits the
power/ground DUT connections inside a `` `ifdef USE_POWER_PINS `` block (leading-
comma style), so TB↔DUT↔compile stay self-consistent in BOTH modes:
  - WITHOUT the define → neither the DUT nor the TB has the supply pins → rc=0.
  - WITH the define    → both do → rc=0.

ACCEPTANCE (issue): an SoC wrapper whose power ports sit behind
`` `ifdef USE_POWER_PINS `` → generated TB + reference_tb compile self-consistent
(rc=0).

NEGATIVE no-leak: a design WITHOUT power pins is unchanged (no `ifdef` emitted);
the power connection only appears inside the guard, never unconditionally.

chip-AGNOSTIC: the `USE_POWER_PINS` define is the universal sky130 / Caravel /
OpenLane convention; the guard shape carries no chip/SKU literal.
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

# DUT whose supply pins are gated behind `ifdef USE_POWER_PINS (the convention).
_RTL = (
    "module soc_top(\n wb_clk_i, wbs_dat_i\n"
    "`ifdef USE_POWER_PINS\n , vccd1, vssd1\n`endif\n);\n"
    " input wb_clk_i; input [31:0] wbs_dat_i;\n"
    "`ifdef USE_POWER_PINS\n inout vccd1, vssd1;\n`endif\nendmodule\n")
_L9 = {"top_module": "soc_top", "top_ports": [
    {"name": "wb_clk_i", "direction": "input", "width": 1},
    {"name": "wbs_dat_i", "direction": "input", "width": 32,
     "msb": 31, "lsb": 0},
    {"name": "vccd1", "direction": "inout", "width": 1, "io": "POWER"},
    {"name": "vssd1", "direction": "inout", "width": 1, "io": "POWER"}]}


def _seed(tmp_path, l9, rtl_text, top="soc_top"):
    proj = tmp_path / "proj"
    gd = P2._pl.generated_docs_dir(proj)
    gd.mkdir(parents=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(l9))
    rd = P2._pl.rtl_dir(proj)
    rd.mkdir(parents=True)
    (rd / f"{top}.v").write_text(rtl_text)
    return proj, rd


def _tb(proj):
    return list((P2._pl.sim_full_stack_dir(proj)).glob("tb_*_full.v"))[0]


def test_power_connection_behind_ifdef(tmp_path):
    """The power connections sit INSIDE `ifdef USE_POWER_PINS, never as an
    unconditional inst arg."""
    proj, _ = _seed(tmp_path, _L9, _RTL)
    P2.step_full_stack_tb_gen(proj, "chip_top")
    body = _tb(proj).read_text()
    assert "`ifdef USE_POWER_PINS" in body and "`endif" in body
    # the .vccd1 connection must be AFTER the `ifdef line (guarded)
    i_if = body.index("`ifdef USE_POWER_PINS")
    i_v = body.index(".vccd1(vccd1)")
    i_end = body.index("`endif", i_if)
    assert i_if < i_v < i_end, "power connection not inside the ifdef guard"


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog not on this host")
@pytest.mark.parametrize("defines", [[], ["-DUSE_POWER_PINS"]])
def test_tb_compiles_both_modes(tmp_path, defines):
    """ACCEPTANCE: TB + ifdef-guarded DUT compile rc=0 WITHOUT and WITH the
    define (the self-consistency the #643-introduced contradiction broke)."""
    proj, rd = _seed(tmp_path, _L9, _RTL)
    P2.step_full_stack_tb_gen(proj, "chip_top")
    tb = _tb(proj)
    r = subprocess.run(
        ["iverilog", "-g2012"] + defines
        + ["-o", str(tmp_path / "a.out"), str(tb), str(rd / "soc_top.v")],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_no_power_pins_design_has_no_ifdef_NOLEAK(tmp_path):
    """NO-LEAK: a design with no power ports emits no `ifdef USE_POWER_PINS
    block (the guard appears only when power pins exist)."""
    l9 = {"top_module": "plain", "top_ports": [
        {"name": "clk", "direction": "input", "width": 1},
        {"name": "q", "direction": "output", "width": 1}]}
    rtl = "module plain(input clk, output q); assign q = clk; endmodule\n"
    proj, _ = _seed(tmp_path, l9, rtl, top="plain")
    P2.step_full_stack_tb_gen(proj, "chip_top")
    body = _tb(proj).read_text()
    assert "`ifdef USE_POWER_PINS" not in body


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
