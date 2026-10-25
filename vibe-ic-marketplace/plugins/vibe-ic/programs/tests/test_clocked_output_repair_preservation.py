"""Public clocked-output timing survives the ordinary gate-directed repair caller."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import worked_example_sequence_oracle_check as oracle
import gate_directed_rtl_repair as repair
import flow_phase_attribution as fpa
import benchmark_dispatch as dispatch


BASE = """Module name: edge_marker
Input ports: clk, rst_n and stream are one bit. Output mark is one bit.
Detect a sampled 1,0,1 pulse. For example, stream is 10101, mark is 00101.
"""
CLOCKED = BASE + """
Inside an always block sensitive to the positive edge of clk and negative edge of rst_n,
implement state updates and output generation. On reset set mark to zero. On each
positive edge assign mark from the pulse completed by this sample, retaining it until
the next edge; otherwise set mark to zero.
"""
COMB = BASE + """
The positive edge always block updates state history and unrelated status output generation.
Output mark is combinational.
"""
REGISTERED = """`timescale 1ns/1ps
module edge_marker(input clk,input rst_n,input stream,output reg mark);
reg [1:0] history;
always @(posedge clk or negedge rst_n)
  if(!rst_n) begin history<=0; mark<=0; end
  else begin history<={history[0],stream}; mark<=(history==2'b10)&&stream; end
endmodule
"""
COMBINATIONAL = """module edge_marker(input clk,input rst_n,input stream,output reg mark);
reg [1:0] history;
always @(posedge clk or negedge rst_n)
  if(!rst_n) history<=0; else history<={history[0],stream};
always @* if(!rst_n) mark=0; else mark=(history==2'b10)&&stream;
endmodule
"""
DELAYED = REGISTERED.replace("reg [1:0] history;", "reg [1:0] history; reg stage;")
DELAYED = DELAYED.replace("history<=0; mark<=0;", "history<=0; stage<=0; mark<=0;")
DELAYED = DELAYED.replace("mark<=(history==2'b10)&&stream;",
                          "stage<=(history==2'b10)&&stream; mark<=stage;")


def test_explicit_clocked_pulse_keeps_its_register():
    measured = oracle.analyze(REGISTERED, CLOCKED)
    assert measured["verdict"] == "PASS", measured
    assert measured["phase_verdicts"] == {"pre-edge": "BLOCK", "post-edge": "PASS"}
    assert measured["one_cycle_late"] is False
    result = repair.repair(REGISTERED, CLOCKED)
    assert result["verdict"] == "NOT_APPLICABLE", result
    assert result["rtl"] is None and result["transform"] is None


def test_clocked_wrong_latency_blocks_without_removing_register():
    measured = oracle.analyze(DELAYED, CLOCKED)
    assert measured["verdict"] == "BLOCK", measured
    assert measured["one_cycle_late"] is False
    result = repair.repair(DELAYED, CLOCKED)
    assert result["verdict"] == "NO_REPAIR", result
    assert result["rtl"] is None and result["attempts"] == []


def test_selected_combinational_output_ignores_unrelated_clocked_paragraph():
    assert oracle._requires_clocked_output(COMB, "mark") is False
    assert oracle.analyze(COMBINATIONAL, COMB)["verdict"] == "PASS"
    assert oracle.analyze(REGISTERED, COMB)["verdict"] == "BLOCK"
    fixed = repair.repair(REGISTERED, COMB)
    assert fixed["verdict"] == "REPAIRED", fixed
    assert fixed["transform"] == "deregister_output"
    assert oracle.analyze(fixed["rtl"], COMB)["verdict"] == "PASS"


@pytest.mark.parametrize("ambiguous", [
    BASE + "\nAn always block on the positive edge performs output generation.\n",
    CLOCKED + "\nOutput mark is combinational.\n",
])
def test_unbound_or_conflicting_output_timing_does_not_guess(ambiguous):
    assert oracle._requires_clocked_output(ambiguous, "mark") is None
    measured = oracle.analyze(REGISTERED, ambiguous)
    assert measured["verdict"] == "SKIP" and "timing" in measured["reason"]
    assert repair.repair(REGISTERED, ambiguous)["rtl"] is None


CHALLENGE = """`timescale 1ns/1ps
module contract_tb;
reg clk=0,rst_n=0,stream=0; wire mark;
reg [4:0] stimuli=5'b10101, expected=5'b00101; integer i;
edge_marker dut(.clk(clk),.rst_n(rst_n),.stream(stream),.mark(mark));
always #5 clk=~clk;
initial begin
  repeat(2) @(posedge clk);
  @(negedge clk); rst_n=1;
  for(i=0;i<5;i=i+1) begin
    if(i>0) @(negedge clk);
    stream=stimuli[4-i]; @(posedge clk); #1;
    if(mark!==expected[4-i]) $fatal(1,"sampled pulse mismatch");
    #1; stream=~stream; #1;
    if(mark!==expected[4-i]) $fatal(1,"clocked output did not hold between edges");
  end
  $display("CLOCKED_CONTRACT_PASS"); $finish;
end
endmodule
"""


def test_actual_ordinary_step2_keeps_bytes_and_same_clocked_challenge(tmp_path):
    assert shutil.which("iverilog") and shutil.which("vvp") and shutil.which("verilator")
    project = tmp_path / "ordinary_clocked"
    prompt = project / "input/phase1_prompt.md"; prompt.parent.mkdir(parents=True)
    prompt.write_text(CLOCKED)
    rtl = project / "phase2/stage1/rtl/edge_marker.sv"; rtl.parent.mkdir(parents=True)
    rtl.write_text(REGISTERED)
    switch = project / "phase3/librelane_switch.json"; switch.parent.mkdir(parents=True)
    switch.write_text('{"steps":{"2":"direct"}}')
    challenge = tmp_path / "contract_tb.sv"; challenge.write_text(CHALLENGE)
    before = hashlib.sha256(rtl.read_bytes()).hexdigest()
    challenge_hash = hashlib.sha256(challenge.read_bytes()).hexdigest()
    def measure(label):
        product = tmp_path / (label + ".vvp")
        built = subprocess.run(["iverilog", "-g2012", "-s", "contract_tb", "-o", str(product),
                                str(rtl), str(challenge)], capture_output=True, text=True)
        assert built.returncode == 0, built.stderr
        run = subprocess.run(["vvp", str(product)], capture_output=True, text=True)
        (project / (label + ".run.log")).write_text(run.stdout + run.stderr)
        assert run.returncode == 0 and "CLOCKED_CONTRACT_PASS" in run.stdout, run.stdout + run.stderr
    measure("before")
    argv = [sys.executable, str(PROGRAMS / "vibe_ic_one_shot_runner.py"), str(project),
            "--entry-step", "2", "--exit-step", "2", "--rtl-input", "original", "--route", "ip",
            "--skip-analog", "--skip-hardware", "--skip-phase3", "--no-dashboard"]
    native = subprocess.run(argv, capture_output=True, text=True)
    (project / "ordinary.stdout.txt").write_text(native.stdout)
    (project / "ordinary.stderr.txt").write_text(native.stderr)
    assert hashlib.sha256(rtl.read_bytes()).hexdigest() == before
    assert hashlib.sha256(challenge.read_bytes()).hexdigest() == challenge_hash
    measure("after")
    report = json.loads((project / "reports/orchestrator/phase2_one_shot.json").read_text())
    assert next(s for s in report["steps"] if s["name"] == "determinism_gates")["status"] == "PASS"
    ledger = dispatch._required_gate_ledger({"exit": "2", "phases": {
        "phase3_verifying": fpa.phase3_verifying(report, None)}})
    assert ledger["eligibility"] == "ELIGIBLE", ledger
    (project / "proof.json").write_text(json.dumps({"argv": argv, "returncode": native.returncode,
        "rtl_sha256_before": before, "rtl_sha256_after": hashlib.sha256(rtl.read_bytes()).hexdigest(),
        "unchanged_challenge_sha256": challenge_hash, "required_gate_ledger": ledger}, indent=2))
