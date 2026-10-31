"""Neutral pre-operation state/clock witnesses; no external benchmark inputs."""
import json
import os
from pathlib import Path
import subprocess

import pytest

import benchmark_dispatch as bd
import spec_coverage_check as coverage


PROMPT = """Implement this interface:
module neutral_ff(input wire clk, input wire x, output wire z);
The output is registered: z holds the most recently sampled x.
Assume that the D flip-flops are initially reset to zero before the machine begins.
Assume all sequential logic is triggered on the positive edge of the clock.
"""
RTL = """module neutral_ff(input wire clk, input wire x, output wire z);
reg q = 1'b0;
assign z = q;
always @(posedge clk) q <= x;
endmodule
"""
TB = """module vibeic_ai_challenge_tb;
reg clk, x; wire observed;
neutral_ff dut(.clk(clk), .x(x), .z(observed));
initial begin
 clk=0; x=0;
 #1;
 if (observed !== 1'b0) begin $display("VIBEIC_AI_CHALLENGE=FAIL"); $fatal(1,"initial state"); end
 x=1; #4; clk=1; #1;
 if (observed !== 1'b1) begin $display("VIBEIC_AI_CHALLENGE=FAIL"); $fatal(1,"first sample"); end
 clk=0; x=0; #4; clk=1; #1;
 if (observed !== 1'b0) begin $display("VIBEIC_AI_CHALLENGE=FAIL"); $fatal(1,"second sample"); end
 $display("VIBEIC_AI_CHALLENGE=PASS"); $finish;
end
endmodule
"""


def report(tb=TB, prompt=PROMPT, rtl=RTL):
    return coverage.run({"user_prompt": prompt}, rtl, tb, None, True)


def test_initial_state_is_a_blocking_obligation_covered_by_real_preclock_output_check():
    measured = report()
    assert measured["blocking_gaps"] == 0, measured
    initial, = [item for item in measured["items"] if item["kind"] == "initial_state"]
    assert initial["block_eligible"] is True and initial["covered"] is True
    assert "initially reset to zero" in initial["evidence"]
    assert not any(item["kind"] == "reset" for item in measured["items"])
    assert report(None)["blocking_gaps"] > 0


def test_manual_bound_clock_covers_latency_without_keyword_or_signal_name_credit():
    assert "posedge" not in TB and "latency" not in TB and "cycle" not in TB
    result = report(prompt=PROMPT.split("Assume that")[0])
    latency, = [item for item in result["items"] if item["kind"] == "latency"]
    assert latency["covered"] is True, latency


@pytest.mark.parametrize("case", ["late", "disabled", "local", "force", "parallel_clock", "weak_equality", "no_observer"])
def test_initial_state_cannot_be_discharged_by_false_or_late_observers(case):
    tb = TB
    first = 'if (observed !== 1\'b0) begin $display("VIBEIC_AI_CHALLENGE=FAIL"); $fatal(1,"initial state"); end'
    if case == "late":
        tb = tb.replace(" #1;\n " + first, " #1; clk=1; #1;\n " + first)
    elif case == "disabled":
        tb = tb.replace(first, "if (1'b0) begin " + first + " end")
    elif case == "local":
        tb = tb.replace("reg clk, x;", "reg clk, x; reg decoy=0;").replace(first, first.replace("observed", "decoy"))
    elif case == "force":
        tb = tb.replace(" clk=0;", " force observed=0; clk=0;")
    elif case == "parallel_clock":
        tb = tb.replace("initial begin", "always #1 clk=~clk;\ninitial begin")
    elif case == "weak_equality":
        tb = tb.replace(first, first.replace("!==", "!="))
    else:
        tb = tb.replace(first, "")
    result = report(tb)
    initial, = [item for item in result["items"] if item["kind"] == "initial_state"]
    assert initial["covered"] is False and initial["block_eligible"] is True, result
    assert result["blocking_gaps"] > 0


def test_runtime_reset_is_separate_from_an_initial_state_assumption():
    source = PROMPT + "Runtime reset input rst clears the state when asserted.\n"
    kinds = {item.kind for item in coverage.extract_checklist(source)}
    assert {"initial_state", "reset"} <= kinds
    reset, = [item for item in report(prompt=source)["items"] if item["kind"] == "reset"]
    assert reset["covered"] is False and reset["block_eligible"] is True


def test_checked_in_neutral_combinational_source_does_not_invent_initial_state():
    from _hostpaths import require_repo
    text = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "programs", "tests",
        "fixtures", "phase1_local", "plain_design_source_provenance", "plain_combinational_input.txt").read_text()
    assert not any(item.kind == "initial_state" for item in coverage.extract_checklist(text))


@pytest.fixture
def native():
    container = os.environ.get("VIBEIC_INITIAL_STATE_TEST_CONTAINER")
    image = os.environ.get("VIBEIC_INITIAL_STATE_TEST_IMAGE")
    if not container or not image or "@sha256:" not in image:
        pytest.skip("native state controls NOT_MEASURED: select container and immutable image")
    info, = json.loads(subprocess.run(["docker", "inspect", container], text=True,
        capture_output=True, check=True).stdout)
    image_id = subprocess.run(["docker", "image", "inspect", image, "--format", "{{.Id}}"],
        text=True, capture_output=True, check=True).stdout.strip()
    assert info["Image"] == image_id
    return {"backend": "native", "selection": "explicit-neutral-initial-state-control",
        "container": container, "container_id": info["Id"], "image_id": image_id,
        "image_digest": image.split("@", 1)[1]}


def native_challenge(tmp_path, native, rtl, tb):
    project = tmp_path / "project"
    output = project / "phase2/stage1/rtl"
    output.mkdir(parents=True)
    (output / "unit.sv").write_text(rtl)
    candidate = bd._archive_candidate("neutral", project, {"completion": rtl}, tmp_path, "PROGRAM")
    challenge = tmp_path / "challenge.sv"
    challenge.write_text(tb)
    result = bd._run_verification_challenge(candidate, {"path": str(challenge),
        "sha256": bd._sha256_text(tb), "top_module": "vibeic_ai_challenge_tb",
        "execution_backend": native})
    (tmp_path / "native_result.json").write_text(json.dumps(result, indent=2))
    return result, candidate, {"path": str(challenge), "sha256": bd._sha256_text(tb)}


@pytest.mark.parametrize("mutant", ["good", "wrong_initial", "wrong_uninitialized", "wrong_sequence", "false_observer"])
def test_native_challenge_distinguishes_initial_value_sequence_and_false_observer(tmp_path, native, mutant):
    rtl, tb = RTL, TB
    if mutant == "wrong_initial":
        rtl = rtl.replace("q = 1'b0", "q = 1'b1")
    elif mutant == "wrong_uninitialized":
        rtl = rtl.replace("reg q = 1'b0;", "reg q;")
    elif mutant == "wrong_sequence":
        rtl = rtl.replace("q <= x", "q <= ~x")
    elif mutant == "false_observer":
        rtl = rtl.replace("q = 1'b0", "q = 1'b1")
        tb = tb.replace("reg clk, x;", "reg clk, x; reg decoy=0;").replace(
            "if (observed !== 1'b0)", "if (decoy !== 1'b0)", 1)
    result, candidate, challenge = native_challenge(tmp_path, native, rtl, tb)
    assert result["status"] == ("FAIL" if mutant.startswith("wrong_") else "PASS"), result
    measured = bd._program_review_coverage_result(PROMPT, candidate, [challenge])
    assert measured["status"] == ("FAIL" if mutant == "false_observer" else "PASS"), measured


@pytest.mark.parametrize("mutant", ["good", "undriven_reset", "wrong_reset_value"])
def test_native_runtime_reset_still_needs_real_drive_and_output_observation(tmp_path, native, mutant):
    rtl = RTL.replace("input wire x,", "input wire x, input wire rst,").replace(
        "reg q = 1'b0;", "reg q;").replace("q <= x;", "if (rst) q <= 1'b0; else q <= x;")
    tb = TB.replace("reg clk, x;", "reg clk, x, rst;").replace(".x(x),", ".x(x), .rst(rst),")
    tb = tb.replace("clk=0; x=0;", "clk=0; x=1; rst=1; #1; clk=1;").replace(
        "x=1; #4;", "clk=0; rst=0; x=1; #4;")
    if mutant == "undriven_reset":
        tb = tb.replace("rst=1;", "").replace("rst=0;", "")
    elif mutant == "wrong_reset_value":
        rtl = rtl.replace("if (rst) q <= 1'b0", "if (rst) q <= 1'b1")
    result, _, _ = native_challenge(tmp_path, native, rtl, tb)
    assert result["status"] == ("PASS" if mutant == "good" else "FAIL"), result
