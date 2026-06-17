"""ORGANIC #805 + #807 — latency_conformance_check `_is_clock` used an
EXACT-MATCH `_CLK_NAMES` whitelist, missing every conventional but non-listed
clock spelling (i_clk, async-FIFO w_clk/r_clk, sys_clk, AMBA aclk/pclk/hclk,
clk0, core_clk). Such a clock fell into the constant-driven `others`, so the
generated TB drove a free-running `clk` wired to NOTHING in the DUT → the design
never saw a clock edge → correct RTL false-blocked with LATENCY-TIMEOUT.

FIX: (#805) `_is_clock` convention-aware — strip i_/o_/io_ prefix + trailing
index digits, require a clk/clock WHOLE TOKEN, glued AMBA allow-list, and a
clock-CONTROL deny-list (clk_en/clk_div/clk_sel/clk_gate/...); (#807) a
multi-clock (≥2) CDC guard → rc=3 NOT_APPLICABLE (single-clock latency undefined
across async domains).

§4.05: data/control ports never promoted; existing clk_in byte-identical; a
genuinely never-pulsing detector still rc=1. chip-AGNOSTIC.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import latency_conformance_check as L  # noqa: E402

_IV = shutil.which("iverilog") and shutil.which("vvp")
_LAT = PROGRAMS / "latency_conformance_check.py"


@pytest.mark.parametrize("n", [
    "clk", "clock", "clk_in", "clock_i", "i_clk", "o_clk", "w_clk", "r_clk",
    "wr_clk", "rd_clk", "sys_clk", "aclk", "pclk", "hclk", "clk0", "core_clk",
    "clk_dsp", "i_axi_clk", "serial_clk"])
def test_805_conventional_clocks_recognised(n):
    assert L._is_clock(n) is True, n


@pytest.mark.parametrize("n", [
    "clk_en", "clk_ena", "clk_div", "clk_sel", "clk_gate", "clk_gate_en",
    "en_clk_dsp", "clk_count", "clk_valid", "block", "lock", "tick", "data",
    "address", "din"])
def test_805_control_and_data_ports_not_clocks(n):
    assert L._is_clock(n) is False, n


def _run(tmp_path, rtl, top, event, output, expect, name="dut"):
    f = tmp_path / f"{name}.v"
    f.write_text(rtl)
    jp = tmp_path / "r.json"
    r = subprocess.run(
        [sys.executable, str(_LAT), "--rtl", str(f), "--top", top,
         "--event", event, "--output", output, "--expect", str(expect),
         "--json", str(jp)], capture_output=True, text=True)
    return r.returncode, json.loads(jp.read_text())


@pytest.mark.skipif(not _IV, reason="iverilog/vvp unavailable")
def test_805_edge_detector_i_clk_now_measures(tmp_path):
    rtl = ("module edge_detector(input i_clk, input rst_n, input d,"
           " output reg pe);\n reg dq;\n"
           " always @(posedge i_clk or negedge rst_n)\n"
           "  if(!rst_n) begin dq<=1'b0; pe<=1'b0; end\n"
           "  else begin dq<=d; pe<=d & ~dq; end\nendmodule")
    rc, rep = _run(tmp_path, rtl, "edge_detector", "d", "pe", 1)
    assert rc == 0, rep                 # was false LATENCY-TIMEOUT rc=1
    assert rep["clk"] == "i_clk"


def test_807_multi_clock_cdc_screens_to_not_applicable(tmp_path):
    # a real async FIFO edge-senses BOTH clocks (write domain + read domain).
    rtl = ("module fifo_async(input w_clk, input r_clk, input rst_n,"
           " input push, input [7:0] din, output reg [7:0] dout);\n"
           " reg [7:0] mem;\n"
           " always @(posedge w_clk) if(push) mem<=din;\n"
           " always @(posedge r_clk or negedge rst_n)"
           " if(!rst_n) dout<=8'd0; else dout<=mem;\nendmodule")
    rc, rep = _run(tmp_path, rtl, "fifo_async", "push", "dout", 1)
    assert rc == 3, rep
    assert rep["verdict"] == "NOT_APPLICABLE"
    assert set(rep.get("clock_inputs", [])) == {"w_clk", "r_clk"}


@pytest.mark.skipif(not _IV, reason="iverilog/vvp unavailable")
def test_805_noleak_standard_clk_in_single_clock_unchanged(tmp_path):
    rtl = ("module s(input clk_in, input rst_n, input start, output reg done);\n"
           " always @(posedge clk_in or negedge rst_n)"
           " if(!rst_n) done<=0; else done<=start;\nendmodule")
    rc, rep = _run(tmp_path, rtl, "s", "start", "done", 1)
    assert rc == 0, rep


# ── Step-2.7 §4.05 — the clock-STATUS/HEALTH family must NOT inflate the CDC
#    count and false-screen a single-clock measurable design to rc=3. ──────────
@pytest.mark.parametrize("n", [
    "clk_lock", "clk_locked", "clk_status", "clk_mon", "clk_test",
    "clk_stable", "clk_ok", "clk_err", "clk_error", "clk_jitter", "clk_skew"])
def test_805_clock_status_health_family_not_clocks(n):
    assert L._is_clock(n) is False, n


def test_805_real_sync_clock_not_over_denied():
    # `sync`/`active` are deliberately NOT denied so a real synchronized clock
    # is never over-rejected (the edge-aware CDC count is the backstop).
    assert L._is_clock("clk_sync") is True


@pytest.mark.skipif(not _IV, reason="iverilog/vvp unavailable")
def test_805_807_noleak_status_input_does_not_false_screen_cdc(tmp_path):
    # clk + clk_mon (a status input), real latency 4 vs --expect 3 → the gate
    # must MEASURE and MISMATCH (rc=1), NOT false-screen to rc=3 (which would
    # hide the real timing bug). clk_mon is denied AND never edge-sensed.
    rtl = ("module T(input clk, input rst, input start, input clk_mon,"
           " output reg done);\n reg [2:0] cnt;\n"
           " always @(posedge clk or posedge rst) begin\n"
           "  if(rst) begin cnt<=0; done<=0; end\n"
           "  else if(start) begin cnt<=1; done<=0; end\n"
           "  else if(cnt!=0) begin cnt<=cnt+1; done<=(cnt==3'd3); end\n"
           "  else done<=0; end\nendmodule")
    rc, rep = _run(tmp_path, rtl, "T", "start", "done", 3)
    assert rc == 1, rep                         # real bug caught, NOT rc=3
    assert rep["verdict"] == "MISMATCH"
    assert rep.get("measured_latency") == 4


@pytest.mark.skipif(not _IV, reason="iverilog/vvp unavailable")
def test_805_noleak_clk_en_not_a_second_clock(tmp_path):
    # clk + clk_en is a SINGLE-clock design — clk_en must NOT trigger CDC rc=3.
    rtl = ("module ce(input clk, input clk_en, input rst_n, input start,"
           " output reg done);\n always @(posedge clk or negedge rst_n)"
           " if(!rst_n) done<=0; else if(clk_en) done<=start;\nendmodule")
    rc, rep = _run(tmp_path, rtl, "ce", "start", "done", 1)
    assert rc != 3, rep
    assert rep["clk"] == "clk"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
