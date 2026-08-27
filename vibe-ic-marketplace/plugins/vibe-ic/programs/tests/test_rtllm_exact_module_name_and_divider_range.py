#!/usr/bin/env python3
"""Real RTLLM prompt shapes keep exact identifiers and legal divider widths."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
FIXTURE = (Path(__file__).resolve().parent / "fixtures" / "real_benchmark"
           / "explicit_module_name_case_sensitive_prompts.json")
sys.path.insert(0, str(PROGRAMS))

import counter_advanced_synth as counter  # noqa: E402
import phase1_doc_one_shot_runner as phase1  # noqa: E402


@pytest.mark.parametrize("record", json.loads(FIXTURE.read_text()))
def test_rtllm_module_name_label_preserves_exact_case(record):
    docs = {"design_description.txt": record["prompt"]}
    assert phase1._extract_top_module_from_docs(docs) == record["module_name"]


@pytest.mark.parametrize("bad", ["DATA_WIDTH", "Step_9", "Interface_Signals"])
def test_explicit_label_still_rejects_parameter_and_heading_shapes(bad):
    assert phase1._extract_top_module_from_docs(
        {"design_description.txt": f"Module name:\n  {bad}\n"}) is None


EVEN_DIVIDER_PROMPT = """\
Please act as a professional verilog designer.

Frequency divider that divides the input clock frequency by even numbers. This
module generates a divided clock signal by toggling its output every specified
number of input clock cycles.

Module name:
    freq_diveven

Input ports:
    clk: Input clock signal that will be divided.
    rst_n: Active-low reset signal to initialize the module.

Output ports:
    clk_div: Divided clock output signal.

Implementation:
    The frequency divider uses a counter (`cnt`) to count the number of clock
    cycles. The `NUM_DIV` parameter specifies the division factor, which must be
    an even number and defaults to 6. With the 4-bit counter, the valid even
    values are from 2 to 32.
"""


def _divider_rtl() -> str:
    rtl = counter.synth(EVEN_DIVIDER_PROMPT, "freq_diveven")
    assert rtl is not None
    return rtl


def test_declared_counter_width_outranks_default_parameter_width():
    rtl = _divider_rtl()
    assert "reg [3:0] cnt;" in rtl
    assert "reg [2:0] cnt;" not in rtl


@pytest.mark.skipif(not shutil.which("iverilog") or not shutil.which("vvp"),
                    reason="iverilog/vvp absent")
@pytest.mark.parametrize("num_div", range(2, 33, 2))
def test_every_declared_even_override_toggles_at_the_right_half_period(
        tmp_path, num_div):
    dut = tmp_path / "dut.v"
    tb = tmp_path / "tb.v"
    dut.write_text(_divider_rtl())
    tb.write_text(f"""\
module tb;
  reg clk = 0;
  reg rst_n = 0;
  wire clk_div;
  integer cycles = 0;
  integer toggles = 0;
  reg last = 0;
  freq_diveven #(.NUM_DIV({num_div})) dut(
    .clk(clk), .rst_n(rst_n), .clk_div(clk_div));
  always #1 clk = ~clk;
  always @(posedge clk) begin
    if (!rst_n) begin cycles = 0; last = clk_div; end
    else cycles = cycles + 1;
  end
  always @(clk_div) begin
    if (rst_n && clk_div !== last) begin
      if (cycles != {num_div // 2}) begin
        $display("BAD half-period=%0d expected={num_div // 2}", cycles);
        $finish_and_return(1);
      end
      cycles = 0;
      toggles = toggles + 1;
      last = clk_div;
      if (toggles == 4) $finish_and_return(0);
    end
  end
  initial begin
    repeat (2) @(negedge clk);
    rst_n = 1;
    repeat ({num_div * 4 + 10}) @(posedge clk);
    $display("BAD timeout");
    $finish_and_return(1);
  end
endmodule
""")
    build = subprocess.run(
        ["iverilog", "-g2012", "-s", "tb", "-o", str(tmp_path / "simv"),
         str(dut), str(tb)], capture_output=True, text=True)
    assert build.returncode == 0, build.stderr
    sim = subprocess.run(["vvp", str(tmp_path / "simv")],
                         capture_output=True, text=True)
    assert sim.returncode == 0, sim.stdout + sim.stderr
