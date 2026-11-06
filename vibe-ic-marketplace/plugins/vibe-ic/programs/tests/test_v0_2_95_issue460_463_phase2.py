#!/usr/bin/env python3
"""v0.2.95 — ORGANIC-20260606 #460 + #463 (design_one_shot_runner).

#460 — genuine oracle-TB PASS earns nothing at Step 4.
  The oracle run writes phase2/stage1/sim_full_stack/oracle_run/oracle.log
  carrying `ORACLE_TB_DONE pass=N/N` and the reference_tb step records
  functional_verified=true / vectors_passed==vectors_total>0 /
  verification_track=oracle_tb. But the Step-4 Simulation gate only accepted
  phase2/stage1/sim/{results.xml,pass.flag}, which since #433 (canned
  pass.flag retired) is no longer written for the oracle track. FIX: a
  genuine oracle PASS bridges the Step-4 gate by emitting sim/results.xml
  (with oracle vector counts + an evidence backlink to oracle.log). A
  skeleton-WAIVED or FAILed oracle run NEVER gets the bridge.

#463 — the auto-emitted pass-through wrapper phase2/stage1/rtl/chip_top.v
  copied the inner module port block verbatim, so `output reg p` survived
  into a wrapper whose outputs are instance-driven (illegal/lint-fatal in
  strict SV). FIX: strip reg/logic storage keywords from OUTPUT port chunks
  only when building the wrapper port block; width / signedness / input
  ports preserved. CORPUS-SWEEP guard: wide buses, signed outputs,
  multi-output wrappers all stay correct.

chip-AGNOSTIC: synthetic generic fixtures only.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

PROG_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG_DIR))
import design_one_shot_runner as P  # noqa: E402


# =====================================================================
# #463 — wrapper output-storage normalisation
# =====================================================================
def test_strip_output_reg_single_output():
    pb = ("(\n  input  wire        clk,\n  input  wire        d,\n"
          "  output reg         q\n)")
    out = P._chip_top_strip_output_storage(pb)
    # the output's `reg` storage keyword is gone…
    assert not re.search(r"output\s+reg\b", out)
    assert "output" in out and "q" in out
    # …and inputs are untouched
    assert out.count("input") == 2
    # balanced parens preserved
    assert out.count("(") == out.count(")") == 1


def test_strip_output_logic_keyword():
    pb = "(input clk, output logic y)"
    out = P._chip_top_strip_output_storage(pb)
    assert "logic" not in out
    assert "output" in out and "y" in out
    # input keeps its own form
    assert "input clk" in out


def test_input_reg_is_preserved():
    # `input` ports must NEVER have reg/logic stripped (only outputs are
    # structurally driven). Synthetic: an input that happens to spell `reg`.
    pb = "(input wire a, output reg b)"
    out = P._chip_top_strip_output_storage(pb)
    # the output's reg is gone
    assert not re.search(r"output\s+reg\b", out)
    # input wire unchanged (it never had reg, and `wire` stays)
    assert "input wire a" in out


def test_signed_output_width_preserved():
    # CORPUS-SWEEP: signed + width must survive; only the storage keyword
    # is surgically removed.
    pb = "(input clk, output reg signed [15:0] result)"
    out = P._chip_top_strip_output_storage(pb)
    assert "signed" in out
    assert "[15:0]" in out
    assert "result" in out
    assert not re.search(r"\breg\b", out)


def test_wide_bus_output_preserved():
    pb = "(input wire [31:0] din, output reg [63:0] dout)"
    out = P._chip_top_strip_output_storage(pb)
    assert "[31:0]" in out  # input width
    assert "[63:0]" in out  # output width
    assert "din" in out and "dout" in out
    assert not re.search(r"output\s+reg\b", out)
    # input bus width untouched
    assert "input wire [31:0] din" in out


def test_multi_output_wrapper_all_normalised():
    pb = ("(input clk, output reg [7:0] a, "
          "output logic b, output reg signed [3:0] c)")
    out = P._chip_top_strip_output_storage(pb)
    assert not re.search(r"\breg\b", out)
    assert "logic" not in out
    for name in ("a", "b", "c"):
        assert name in out
    assert "[7:0]" in out and "[3:0]" in out and "signed" in out


def test_ansi_continuation_chunk_group():
    # `output reg [7:0] a, b` — `b` is a continuation that inherits
    # `output reg`. Stripping the leading chunk normalises the group; the
    # bare `b` chunk has no keyword to remove and stays a name.
    pb = "(input clk, output reg [7:0] a, b)"
    out = P._chip_top_strip_output_storage(pb)
    assert not re.search(r"\breg\b", out)
    assert "a" in out and "b" in out
    assert "[7:0]" in out


def test_purely_combinational_output_unchanged():
    # An `output wire`/bare `output` has no storage keyword → byte-identical.
    pb = "(input a, output wire y, output z)"
    out = P._chip_top_strip_output_storage(pb)
    assert out == pb  # nothing to strip


def test_port_name_containing_reg_substring_preserved():
    # a port literally named `reg_out` must not be mangled (\b…\b guards it).
    pb = "(input clk, output reg reg_out)"
    out = P._chip_top_strip_output_storage(pb)
    # the storage `reg` keyword is gone but the identifier survives
    assert "reg_out" in out
    assert not re.search(r"output\s+reg\b\s+reg\b", out)
    # exactly the standalone keyword removed → `output reg_out`
    assert re.search(r"output\s+reg_out", out)


def test_input_only_block_unchanged():
    pb = "(input clk, input rst)"
    assert P._chip_top_strip_output_storage(pb) == pb


# --- end-to-end: the emitted wrapper is what the runner writes ----------
SPM_LIKE = """module datacore #(
    parameter size = 32
) (
    input  wire             clk,
    input  wire             rst,
    input  wire [size-1:0]  x,
    input  wire             y,
    output reg              p
);
    always @(posedge clk) p <= y;
endmodule"""


def _emit_runner_wrapper(rtl_dir: Path, synth_top: str, dut_src: str,
                         dut_name: str) -> str:
    """Replicate the runner's wrapper emission using the SAME helpers, so a
    regression in the emission path fails this test."""
    (rtl_dir / f"{dut_name}.v").write_text(dut_src)
    scan = P._chip_top_mask_comments(dut_src)
    m = re.compile(r"module\s+(\w+)\s*[(#]").search(scan)
    param_block, port_block = P._chip_top_extract_param_and_ports(
        scan, m.end() - 1)
    wrapper_port_block = P._chip_top_strip_output_storage(port_block)
    inner = port_block.strip()[1:-1]
    kw = {"input", "output", "inout", "wire", "reg", "logic", "signed",
          "unsigned", "var"}
    names = []
    for chunk in inner.split(","):
        ids = [t for t in re.findall(r"[A-Za-z_]\w*", chunk) if t not in kw]
        if ids:
            names.append(ids[-1])
    connects = ",\n    ".join(f".{n}({n})" for n in names)
    param_header = f" {param_block.strip()}" if param_block.strip() else ""
    inst_params = ""
    if param_block.strip():
        pn = []
        for pm in re.finditer(
                r"\b(?:parameter|localparam)\b[^=,()]*?([A-Za-z_]\w*)\s*=",
                param_block):
            if pm.group(1) not in pn:
                pn.append(pm.group(1))
        if pn:
            inst_params = " #(" + ", ".join(f".{p}({p})" for p in pn) + ")"
    return (f"`default_nettype none\n"
            f"module {synth_top}{param_header} {wrapper_port_block};\n"
            f"  {dut_name}{inst_params} u_dut (\n    {connects}\n  );\n"
            f"endmodule\n`default_nettype wire\n")


def test_emitted_wrapper_has_no_output_reg(tmp_path):
    w = _emit_runner_wrapper(tmp_path, "chip_top", SPM_LIKE, "datacore")
    # the #463 bug: `output reg p` leaking into the instance-driven wrapper
    assert not re.search(r"output\s+reg\b", w), w
    # but the port + the instance connection still exist
    assert "module chip_top #(" in w
    assert ".p(p)" in w
    assert "[size-1:0]" in w  # input width preserved


def test_emitted_wrapper_iverilog_strict_compiles(tmp_path):
    import shutil
    import subprocess
    if not shutil.which("iverilog"):
        pytest.skip("iverilog not available")
    (tmp_path / "datacore.v").write_text(SPM_LIKE)
    w = _emit_runner_wrapper(tmp_path, "chip_top", SPM_LIKE, "datacore")
    (tmp_path / "chip_top.v").write_text(w)
    r = subprocess.run(
        ["iverilog", "-g2012", "-o", str(tmp_path / "a.out"),
         "-s", "chip_top",
         str(tmp_path / "chip_top.v"), str(tmp_path / "datacore.v")],
        capture_output=True, text=True)
    assert r.returncode == 0, f"iverilog failed: {r.stderr}"


# =====================================================================
# #460 — oracle-TB PASS bridges the Step-4 Simulation gate
# =====================================================================












# --- manifest emitter preserves the oracle bridge (does not clobber) ----










if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
