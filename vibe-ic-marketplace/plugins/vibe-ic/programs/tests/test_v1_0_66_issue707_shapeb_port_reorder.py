#!/usr/bin/env python3
"""ORGANIC #707 (MEDIUM) — wire the dead-code port_convention_corpus.order_ports
into the SOLE Shape-B emit path so genre-conventional positional port order is
actually applied.

RTLLM-class hidden testbenches instantiate the DUT POSITIONALLY with an
undocumented order (`LFSR DUT(out_tb, clk_tb, rst_tb);` → out, clk, rst). The
prompt lists ports by name only, so a blind author writes prompt order
(clk, rst, out) → a positional bind mismatches widths and FAILs to elaborate.
The deterministic remedy (order_ports / genre_order_policy) already existed but
was NEVER wired into shape_b_sample_export — dead code at flow time.

FIX: shape_b_sample_export.reorder_top_ports applies a PURE reorder of the
TB-facing top's ANSI port-list declaration segments before emit, with a
structural sequential-detector so a clocked design (clk + reset + posedge) gets
outputs→clk→reset→inputs even when ic_class=digital_arithmetic_primitive.

§4.05 NO-LEAK (this MUTATES the emitted RTL): a PURE reorder — never adds /
drops / renames a port; an already-conventional list is BYTE-IDENTICAL; a
NAMED-binding TB is unaffected (named binding ignores order); a commented /
bundled / ambiguous port list FALLS BACK to verbatim; and a reorder that fails
the standalone guard is reverted to the verbatim original (never makes a
shippable sample unshippable).

chip-AGNOSTIC: genre-order grammar + structural detector; no chip literal.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import shape_b_sample_export as S  # noqa: E402
import _path_layout as _pl  # noqa: E402

_HAS_IVERILOG = shutil.which("iverilog") is not None

# prompt-order LFSR (clk, rst, out) — the blind-author order the issue cites.
_LFSR_PROMPT_ORDER = (
    "module LFSR(input clk, input rst, output reg [3:0] out);\n"
    "  always @(posedge clk or posedge rst)\n"
    "    if(rst) out<=4'b1; else out<={out[2:0],out[3]^out[2]};\n"
    "endmodule\n")

# RTLLM-style POSITIONAL testbench: DUT(out_tb, clk_tb, rst_tb).
_POSITIONAL_TB = (
    "module tb; reg clk_tb=0,rst_tb=1; wire [3:0] out_tb;\n"
    "LFSR DUT(out_tb, clk_tb, rst_tb);\n"
    "always #5 clk_tb=~clk_tb;\n"
    "initial begin #12 rst_tb=0; #50\n"
    "  $display(\"=========== Your Design Passed ===========\"); $finish; end\n"
    "endmodule\n")


def _build_shapeb_fixture(tmp_path, rtl_text, leaf="LFSR"):
    proj = tmp_path / "work" / leaf
    rtl = _pl.rtl_dir(proj)
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / f"{leaf}.v").write_text(rtl_text)
    return proj, rtl


def _compile(tmp_path, sample_path, tb_text):
    tb = tmp_path / "testbench.v"
    tb.write_text(tb_text)
    binp = tmp_path / "a.out"
    r = subprocess.run(["iverilog", "-g2012", "-o", str(binp),
                        str(sample_path), str(tb)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return r.returncode, r.stderr
    run = subprocess.run([str(binp)], capture_output=True, text=True)
    return run.returncode, run.stdout


# ── END-STATE: the real exporter + a positional TB (the 現象) ────────────────
def test_export_reorders_to_genre_order(tmp_path):
    proj, rtl = _build_shapeb_fixture(tmp_path, _LFSR_PROMPT_ORDER)
    samples = tmp_path / "samples"
    res = S.export(rtl, "LFSR", samples)
    assert res["verdict"] == "PASS", res
    header = (samples / "LFSR.v").read_text().splitlines()[0]
    # out before clk before rst (sequential genre order)
    assert header.index("out") < header.index("clk") < header.index("rst"), header


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog unavailable")
def test_reordered_sample_passes_positional_tb_LOADBEARING(tmp_path):
    """The reordered sample compiles AND passes the RTLLM positional TB, while
    the verbatim prompt-order RTL FAILS it — proving the reorder is load-bearing
    (not a cosmetic no-op)."""
    proj, rtl = _build_shapeb_fixture(tmp_path, _LFSR_PROMPT_ORDER)
    samples = tmp_path / "samples"
    S.export(rtl, "LFSR", samples)
    rc, out = _compile(tmp_path, samples / "LFSR.v", _POSITIONAL_TB)
    assert rc == 0 and "Passed" in out, (rc, out)

    # the un-reordered prompt-order RTL FAILS the SAME positional TB
    bad = tmp_path / "prompt_order.v"
    bad.write_text(_LFSR_PROMPT_ORDER)
    rc2, err2 = _compile(tmp_path, bad, _POSITIONAL_TB)
    assert rc2 != 0, "prompt-order RTL should FAIL the positional TB"


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog unavailable")
def test_noleak_named_binding_tb_unaffected(tmp_path):
    """§4.05: a NAMED-binding TB ignores port order — the reordered sample must
    still compile + pass it (the reorder never breaks named binding)."""
    proj, rtl = _build_shapeb_fixture(tmp_path, _LFSR_PROMPT_ORDER)
    samples = tmp_path / "samples"
    S.export(rtl, "LFSR", samples)
    named_tb = (
        "module tb; reg clk_tb=0,rst_tb=1; wire [3:0] out_tb;\n"
        "LFSR DUT(.clk(clk_tb), .rst(rst_tb), .out(out_tb));\n"
        "always #5 clk_tb=~clk_tb;\n"
        "initial begin #12 rst_tb=0; #50\n"
        "  $display(\"=========== Your Design Passed ===========\"); $finish; end\n"
        "endmodule\n")
    rc, out = _compile(tmp_path, samples / "LFSR.v", named_tb)
    assert rc == 0 and "Passed" in out, (rc, out)


# ── unit-level reorder_top_ports + §4.05 fall-back fail-safes ────────────────
def test_sequential_reorder_outputs_clk_reset_inputs():
    r = S.reorder_top_ports(_LFSR_PROMPT_ORDER, "LFSR")
    h = r.splitlines()[0]
    assert h.index("out") < h.index("clk") < h.index("rst"), h


def test_noleak_already_conventional_byte_identical():
    conv = ("module LFSR(output reg [3:0] out, input clk, input rst);\n"
            "  always @(posedge clk) out<=out+1;\nendmodule\n")
    assert S.reorder_top_ports(conv, "LFSR") == conv


def test_noleak_commented_port_list_verbatim():
    c = ("module M(input clk, // the clock\n input rst, output o);\n"
         "assign o=1;\nendmodule\n")
    assert S.reorder_top_ports(c, "M") == c


def test_noleak_name_set_preserved():
    import re
    r = S.reorder_top_ports(_LFSR_PROMPT_ORDER, "LFSR")
    def names(t):
        return sorted(re.findall(r"\b(clk|rst|out)\b", t.splitlines()[0]))
    assert names(r) == names(_LFSR_PROMPT_ORDER)


def test_combinational_outputs_first():
    comb = ("module addr(input [3:0] xa, input [3:0] xb, output [4:0] xs);\n"
            "assign xs=xa+xb;\nendmodule\n")
    h = S.reorder_top_ports(comb, "addr").splitlines()[0]
    assert h.index("xs") < h.index("xa") and h.index("xa") < h.index("xb"), h


def test_sequential_detector_overrides_arithmetic_ic_class():
    """A clocked design classified digital_arithmetic_primitive still gets the
    sequential order (structural detector overrides the coarse ic_class)."""
    pol = S._resolve_order_policy(
        _LFSR_PROMPT_ORDER, "LFSR",
        [("input", "", "clk"), ("input", "", "rst"),
         ("output", "", "out")],
        "digital_arithmetic_primitive")
    assert pol == "outputs_clk_reset_inputs"


def test_combinational_top_not_flagged_sequential():
    comb = ("module addr(input [3:0] xa, output [4:0] xs);\n"
            "assign xs=xa+1;\nendmodule\n")
    assert S._resolve_order_policy(
        comb, "addr", [("input", "", "xa"), ("output", "", "xs")],
        "digital_arithmetic_primitive") == "outputs_first"


def test_export_threads_ic_class_param(tmp_path):
    """export() accepts the #707 ic_class param without disturbing the verdict."""
    proj, rtl = _build_shapeb_fixture(tmp_path, _LFSR_PROMPT_ORDER)
    res = S.export(rtl, "LFSR", tmp_path / "samples",
                   ic_class="digital_arithmetic_primitive")
    assert res["verdict"] == "PASS", res


def test_chip_agnostic_guard():
    prog = _PROGRAMS / "source_chip_agnostic_check.py"
    r = subprocess.run([sys.executable, str(prog), str(_PROGRAMS.parent)],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-400:]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
