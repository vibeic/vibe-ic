"""Actual DUT input/output periods, not unrelated source-clock labels.

The fixtures are neutral. Native controls execute the very assertions whose
source coverage the ordinary strict consumer attributes below.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import spec_coverage_check as SC


PROMPT = ("The input clock frequency is 125 MHz. "
          "The output clock frequencies are 62.5 MHz and 31.25 MHz.")
RTL = """module rate_pair(input ref_clk,output reg fast_clk,
output reg slow_clk);
reg phase;
initial begin phase=0;fast_clk=0;slow_clk=0;end
always @(posedge ref_clk) begin
 fast_clk<=~fast_clk;phase<=~phase;
 if(phase)slow_clk<=~slow_clk;
end
endmodule
"""
INPUT_PROOF = """@(posedge drive); t_input=$time; @(posedge drive);
if(($time-t_input)!=8)$fatal(1,"input period");
"""
FAST_PROOF = """@(posedge observed_fast); t_fast=$realtime; @(posedge observed_fast);
if(($realtime-t_fast)!=16)begin $display("wrong fast period");$fatal(1,"fast period");end
done_fast=1;
"""
SLOW_PROOF = """@(negedge observed_slow); t_slow=$time; @(negedge observed_slow);
if(($time-t_slow)!=32)$fatal(1,"slow period");
"""
TB = """`timescale 1ns/1ps
module tb;
reg drive=0,done_fast=0;wire observed_fast,observed_slow;
time t_input,t_slow;realtime t_fast;
rate_pair dut(.ref_clk(drive),.fast_clk(observed_fast),.slow_clk(observed_slow));
always #4 drive=~drive;
initial begin
""" + INPUT_PROOF + FAST_PROOF + SLOW_PROOF + """
if(!done_fast)$fatal(1,"disabled observer");
$display("NATIVE_CLOCK_PROOF_PASS");$finish;
end
endmodule
"""


def _report(tb=TB, prompt=PROMPT, rtl=RTL):
    return SC.run({"user_prompt": prompt}, rtl, tb, None, True)


def _clocks(report):
    return {item["coverage_tokens"][0]: item
            for item in report["items"] if item["kind"] == "clock_frequency"}


def _native(tmp_path, tb, rtl=RTL):
    design = tmp_path / "design.sv"
    challenge = tmp_path / "challenge.sv"
    output = tmp_path / "simulation.vvp"
    design.write_text(rtl)
    challenge.write_text(tb)
    compile_result = subprocess.run(
        ["iverilog", "-g2012", "-s", "tb", "-o", str(output),
         str(design), str(challenge)], capture_output=True, text=True, timeout=30)
    (tmp_path / "compile.log").write_text(compile_result.stdout + compile_result.stderr)
    assert compile_result.returncode == 0, compile_result.stdout + compile_result.stderr
    simulation = subprocess.run(["vvp", str(output)], capture_output=True,
                                text=True, timeout=30)
    (tmp_path / "simulation.log").write_text(simulation.stdout + simulation.stderr)
    return simulation


@pytest.mark.parametrize("binding", ["named", "positional"])
def test_direct_input_and_two_output_periods_cover_real_bound_clocks(binding):
    tb = TB
    if binding == "positional":
        tb = tb.replace(".ref_clk(drive),.fast_clk(observed_fast),.slow_clk(observed_slow)",
                        "drive,observed_fast,observed_slow")
    report = _report(tb)
    clocks = _clocks(report)
    assert set(clocks) == {"125", "62.5", "31.25"}
    assert {rate for rate, item in clocks.items() if item["covered"]} == set(clocks)
    assert not report["blocked"]
    assert "observed_fast" in clocks["62.5"]["coverage_note"]


def test_native_direct_input_and_output_assertions_pass(tmp_path):
    simulation = _native(tmp_path, TB)
    assert simulation.returncode == 0, simulation.stdout + simulation.stderr
    assert "NATIVE_CLOCK_PROOF_PASS" in simulation.stdout
    assert all(item["covered"] for item in _clocks(_report()).values())


@pytest.mark.parametrize("mutation", ["wrong_period", "disabled_observer"])
def test_native_bad_period_or_disabled_observer_fails_and_stays_uncovered(tmp_path, mutation):
    if mutation == "wrong_period":
        tb = TB.replace("t_fast)!=16", "t_fast)!=17")
    else:
        tb = TB.replace(FAST_PROOF, "if(0)begin\n" + FAST_PROOF + "end\n")
    simulation = _native(tmp_path, tb)
    assert simulation.returncode != 0
    assert "FATAL" in simulation.stdout + simulation.stderr
    assert "NATIVE_CLOCK_PROOF_PASS" not in simulation.stdout
    report = _report(tb)
    assert not _clocks(report)["62.5"]["covered"]
    assert report["blocked"]


def test_native_unbound_oscillator_can_pass_but_cannot_cover_dut_output(tmp_path):
    tb = TB.replace("reg drive=0,done_fast=0;", "reg drive=0,done_fast=0,decoy=0;")
    tb = tb.replace("always #4 drive=~drive;", "always #4 drive=~drive;always #8 decoy=~decoy;")
    tb = tb.replace(FAST_PROOF, FAST_PROOF.replace("observed_fast", "decoy"))
    simulation = _native(tmp_path, tb)
    assert simulation.returncode == 0, simulation.stdout + simulation.stderr
    assert "NATIVE_CLOCK_PROOF_PASS" in simulation.stdout
    report = _report(tb)
    assert not _clocks(report)["62.5"]["covered"]
    assert report["blocked"]


@pytest.mark.parametrize("mutation", [
    "missing_edge", "different_edge", "missing_fatal", "synthetic_drive",
    "helper_only", "comment_only", "diagnostic_only", "early_finish",
])
def test_inactive_or_unbound_period_text_does_not_close_output_gap(mutation):
    if mutation == "missing_edge":
        replacement = FAST_PROOF.replace("; @(posedge observed_fast)", "; #16")
    elif mutation == "different_edge":
        replacement = FAST_PROOF.replace("t_fast=$realtime; @(posedge", "t_fast=$realtime; @(negedge")
    elif mutation == "missing_fatal":
        replacement = FAST_PROOF.replace('$fatal(1,"fast period")', '$display("not a verdict")')
    elif mutation == "synthetic_drive":
        replacement = "force observed_fast=drive;\n" + FAST_PROOF
    elif mutation == "helper_only":
        replacement = "done_fast=1;\n"
    elif mutation == "comment_only":
        replacement = "/* " + FAST_PROOF + " */ done_fast=1;\n"
    elif mutation == "diagnostic_only":
        replacement = '$display("@(posedge observed_fast); t_fast=$realtime; @(posedge observed_fast); if($realtime-t_fast!=16)$fatal(1)");done_fast=1;\n'
    else:
        replacement = "$finish;\n" + FAST_PROOF
    tb = TB.replace(FAST_PROOF, replacement)
    if mutation == "helper_only":
        tb += "module decoy_helper;reg observed_fast=0,done_fast=0;realtime t_fast;initial begin\n" + FAST_PROOF + "end endmodule\n"
    report = _report(tb)
    assert not _clocks(report)["62.5"]["covered"]
    assert report["blocked"]


def test_source_input_requirement_is_not_paid_by_an_output_measurement():
    tb = TB.replace(INPUT_PROOF, "")
    # The input still has a periodic drive, but no actual measured proof.
    report = _report(tb)
    assert not _clocks(report)["125"]["covered"]
    assert _clocks(report)["62.5"]["covered"]
    assert report["blocked"]


@pytest.mark.parametrize("direction", ["output", "inout", "commented_output"])
def test_helper_output_or_inout_cannot_supply_the_dut_clock(tmp_path, direction):
    # This DUT supplies no fast clock. The TB helper manufactures it, making
    # all native period assertions pass while the DUT obligation is unproved.
    rtl = RTL.replace("output reg fast_clk", "output wire fast_clk")
    rtl = rtl.replace("fast_clk=0;", "").replace("fast_clk<=~fast_clk;", "")
    rtl = rtl.replace("reg phase;", "assign fast_clk=1'bz;reg phase;")
    if direction == "commented_output":
        rtl += "\n// module clock_supplier is diagnostic text, not a design module.\n"
        direction = "output"
    tb = TB.replace("always #4 drive=~drive;",
                    "clock_supplier fake(drive,observed_fast);always #4 drive=~drive;")
    tb += f"""module clock_supplier(input source,{direction} wire supplied);
reg level=0;always @(posedge source)level<=~level;
assign supplied=level;endmodule
"""
    simulation = _native(tmp_path, tb, rtl)
    assert simulation.returncode == 0, simulation.stdout + simulation.stderr
    assert "NATIVE_CLOCK_PROOF_PASS" in simulation.stdout
    report = _report(tb, rtl=rtl)
    assert {rate for rate, item in _clocks(report).items() if item["covered"]} == {
        "125", "31.25"}
    assert report["blocked"]


def test_helper_input_monitor_preserves_actual_output_proof(tmp_path):
    tb = TB.replace("always #4 drive=~drive;",
                    "clock_observer monitor(.sample(observed_fast));always #4 drive=~drive;")
    tb += "module clock_observer(input sample);endmodule\n"
    simulation = _native(tmp_path, tb)
    assert simulation.returncode == 0, simulation.stdout + simulation.stderr
    assert all(item["covered"] for item in _clocks(_report(tb)).values())


def test_unknown_helper_port_direction_is_not_assumed_input():
    tb = TB.replace("always #4 drive=~drive;",
                    "opaque_helper monitor(.sample(observed_fast));always #4 drive=~drive;")
    report = _report(tb)
    assert not _clocks(report)["62.5"]["covered"]
    assert report["blocked"]
