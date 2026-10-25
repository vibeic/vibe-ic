"""Finite native RTL validation: timing and hierarchy without synthesis admission."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import benchmark_dispatch as dispatch
import flow_phase_attribution as fpa


CASES = {
    "periodic_clock": (True, None,
        "Output tick starts low and toggles every four ns forever; PERIOD defaults to 4.",
        """`timescale 1ns/1ps
module neutral_design(output reg tick);
parameter integer PERIOD=4;
initial begin tick=0; forever #PERIOD tick=~tick; end
endmodule
""",
        "wire tick; neutral_design dut(.tick(tick)); initial begin #1; if(tick!==0) $fatal; "
        "#4; if(tick!==1) $fatal; #4; if(tick!==0) $fatal; $finish; end"),
    "hierarchical_output": (True, None,
        "Input a drives output pair={a,~a} through two helper modules.",
        """module neutral_design(input wire a,output wire [1:0] pair);
wire bp,bg;
echo_helper first(.a(a),.q(bp));
invert_helper second(.a(a),.q(bg));
assign pair={bp,bg};
endmodule
module echo_helper(input wire a,output wire q); assign q=a; endmodule
module invert_helper(input wire a,output wire q); assign q=~a; endmodule
""",
        "reg a=0; wire [1:0] pair; neutral_design dut(.a(a),.pair(pair)); "
        "initial begin #1; if(pair!==2'b01) $fatal; a=1; #1; if(pair!==2'b10) $fatal; $finish; end"),
    "undriven": (False, "UNDRIVEN", "Combinational output q follows input a.",
        "module neutral_design(input wire a,output wire q); endmodule\n", None),
    "unknown_module": (False, None, "Combinational output q follows input a.",
        "module neutral_design(input wire a,output wire q); missing_cell u(.a(a),.q(q)); endmodule\n", None),
    "multidriver": (False, "MULTIDRIVEN", "Output q samples a on the rising edge of clk.",
        "module neutral_design(input wire clk,a,output reg q); "
        "always @(posedge clk) q<=a; always @(negedge clk) q<=~a; endmodule\n", None),
    "latch": (False, "LATCH", "Combinational q is a when enable is high, otherwise zero.",
        "module neutral_design(input wire enable,a,output reg q); "
        "always @* begin if(enable) q=a; end endmodule\n", None),
}


@pytest.mark.parametrize("case", CASES)
def test_original_native_rtl_step2_and_required_consumer(tmp_path, case):
    assert shutil.which("verilator") and shutil.which("iverilog") and shutil.which("vvp")
    good, code, prose, text, stimulus = CASES[case]
    project = tmp_path / case
    prompt = project / "input/phase1_prompt.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("Module name: neutral_design\n" + prose + "\n")
    rtl = project / "phase2/stage1/rtl/neutral_design.sv"
    rtl.parent.mkdir(parents=True)
    rtl.write_text(text)
    switch = project / "phase3/librelane_switch.json"
    switch.parent.mkdir(parents=True)
    switch.write_text('{"steps":{"2":"direct"}}')
    expected_hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (prompt, rtl)}
    if stimulus:
        tb = tmp_path / "tb.sv"
        tb.write_text("`timescale 1ns/1ps\nmodule tb; " + stimulus + " endmodule\n")
        product = tmp_path / "probe.vvp"
        compile_run = subprocess.run(["iverilog", "-g2012", "-s", "tb", "-o", str(product),
                                      str(rtl), str(tb)], capture_output=True, text=True)
        assert compile_run.returncode == 0, compile_run.stderr
        simulate = subprocess.run(["vvp", str(product)], capture_output=True, text=True)
        assert simulate.returncode == 0, simulate.stdout + simulate.stderr
    argv = [sys.executable, str(PROGRAMS / "vibe_ic_one_shot_runner.py"), str(project),
            "--entry-step", "2", "--exit-step", "2", "--rtl-input", "original", "--route", "ip",
            "--skip-analog", "--skip-hardware", "--skip-phase3", "--no-dashboard"]
    native = subprocess.run(argv, capture_output=True, text=True)
    (project / "native.stdout.txt").write_text(native.stdout)
    (project / "native.stderr.txt").write_text(native.stderr)
    (project / "native.command.json").write_text(json.dumps({"argv": argv, "returncode": native.returncode}, indent=2))
    report_path = project / "reports/orchestrator/phase2_one_shot.json"
    assert report_path.is_file(), native.stderr
    report = json.loads(report_path.read_text())
    row = next(s for s in report["steps"] if s["name"] == "rtl_validate")
    assert row["status"] == ("PASS" if good else "FAIL"), row
    measured = json.loads((project / "reports/phase2/lint/rtl_hygiene.json").read_text())
    assert measured["tool"] == "verilator"
    assert measured["top"] == "neutral_design"
    assert "--timing" in measured["command"]
    assert measured["input_sha256"] == expected_hashes
    assert measured["verdict"] == ("PASS" if good else "FAIL")
    assert Path(measured["transcript"]).is_file()
    if code:
        assert code in {f["code"] for f in measured["blocking"]}
    elif not good:
        assert any(f["severity"] == "ERROR" for f in measured["blocking"])
    ledger = dispatch._required_gate_ledger({"exit": "2", "phases": {
        "phase3_verifying": fpa.phase3_verifying(report, None)}})
    (project / "reports/required_gate_ledger.json").write_text(json.dumps(ledger, indent=2))
    assert ledger["eligibility"] == ("ELIGIBLE" if good else "INELIGIBLE"), ledger
    assert {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (prompt, rtl)} == expected_hashes
