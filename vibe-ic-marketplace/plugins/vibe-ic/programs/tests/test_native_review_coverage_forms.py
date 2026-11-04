"""Neutral source forms through the ordinary Program review consumer."""
import re

import pytest

import benchmark_dispatch as bd
import spec_coverage_check as coverage
from test_initial_state_coverage import PROMPT, RTL, TB, native, native_challenge


def consumer(tmp_path, prompt, rtl, tb):
    design = tmp_path / "unit.sv"
    design.write_text(rtl)
    challenge = tmp_path / "challenge.sv"
    challenge.write_text(tb)
    return bd._program_review_coverage_result(prompt, {"rtl_paths": [str(design)]},
        [{"path": str(challenge), "sha256": bd._sha256_text(tb)}])


@pytest.mark.parametrize("declaration", ["reg clk=0,x=0;", "logic x=0,clk=0;", "bit x=0,clk=0,spare=0;"])
def test_combined_scalar_initializers_cover_bound_clock(tmp_path, declaration):
    tb = TB.replace("reg clk, x;", declaration).replace(" clk=0; x=0;", "")
    result = consumer(tmp_path, PROMPT, RTL, tb)
    assert result["status"] == "PASS", result


@pytest.mark.parametrize("mutation", ["wrong_clock", "parallel_driver", "forced_output", "no_assert", "active_initial"])
def test_combined_declaration_does_not_bypass_clock_or_observer_guards(tmp_path, mutation):
    tb = TB.replace("reg clk, x;", "reg clk=0,x=0;").replace(" clk=0; x=0;", "")
    if mutation == "wrong_clock":
        tb = tb.replace("reg clk=0,x=0;", "reg clk=0,x=0,decoy=0;").replace("clk=1;", "decoy=1;")
    elif mutation == "parallel_driver":
        tb = tb.replace("initial begin", "always #1 clk=~clk; initial begin")
    elif mutation == "forced_output":
        tb = tb.replace("initial begin", "initial begin force observed=0;")
    elif mutation == "active_initial":
        tb = tb.replace("reg clk=0", "reg clk=1")
    else:
        tb = re.sub(r"if \(observed.*? end", "", tb)
    assert consumer(tmp_path, PROMPT, RTL, tb)["status"] == "FAIL"


def test_wrapped_preoperation_assumption_keeps_independent_runtime_reset(tmp_path):
    prompt = PROMPT.replace("before the machine", "before the\nmachine")
    assert consumer(tmp_path, prompt, RTL, TB)["status"] == "PASS"
    kinds = {item.kind for item in coverage.extract_checklist(prompt)}
    assert "initial_state" in kinds and "reset" not in kinds
    prompt += "Runtime reset input rst clears the state when asserted.\n"
    measured = consumer(tmp_path, prompt, RTL, TB)
    assert measured["status"] == "FAIL"
    assert {item["kind"] for item in measured["blocking_gap_items"]} == {"reset"}


COUNTER_PROMPT = """module bounded_count(input clk,input rst,input advance,input up,output [2:0] count);
Implement a three-bit saturating counter. When advance is high it increments
or decrements according to up, holding at the maximum of 7 or minimum of 0.
Reset rst is active high synchronous and clears the count.
Assume all sequential logic is triggered on the positive edge of the clock.
"""
COUNTER_RTL = """module bounded_count(input clk,input rst,input advance,input up,output reg [2:0] count);
always @(posedge clk) begin
 if(rst) count<=0;
 else if(advance) begin
  if(up) begin if(count!=7)count<=count+1; end
  else begin if(count!=0)count<=count-1; end
 end
end
endmodule
"""


def counter_tb(mode="full"):
    values = list(range(1, 8)) + [7, 7] + list(range(6, -1, -1)) + [0, 0, 1]
    if mode == "smoke":
        values = [1, 2, 3]
    elif mode == "upper_only":
        values = list(range(1, 8)) + [7, 7, 6]
    elif mode == "no_recovery":
        values = list(range(1, 8)) + [7, 7] + list(range(6, -1, -1)) + [0, 0]
    body = ["#1;clk=1;#1;if(count!==3'd0)begin $display(\"VIBEIC_AI_CHALLENGE=FAIL\");$fatal(1);end #1;clk=0;rst=0;advance=1;"]
    for index, value in enumerate(values):
        up = int(index < 9 or index == len(values)-1)
        body.append(f"up={up};#1;clk=1;#1;if(count!==3'd{value})begin $display(\"VIBEIC_AI_CHALLENGE=FAIL\");$fatal(1);end #1;clk=0;")
    return """module vibeic_ai_challenge_tb;
reg clk=0,rst=1,advance=0,up=1;wire [2:0] count;
bounded_count dut(.clk(clk),.rst(rst),.advance(advance),.up(up),.count(count));
initial begin
""" + "\n".join(body) + '\n$display("VIBEIC_AI_CHALLENGE=PASS");$finish;end endmodule'


@pytest.mark.parametrize("mode", ["full", "smoke", "upper_only", "no_recovery", "token_only", "no_assert", "forced_output", "wrong_clock"])
def test_saturation_requires_exercised_output_regions(tmp_path, mode):
    tb = counter_tb(mode)
    if mode == "token_only":
        tb = counter_tb("smoke").replace("wire [2:0] count;", "reg saturation,clamp,clip;wire [2:0] count;")
    elif mode == "no_assert":
        tb = re.sub(r"if\(count.*?end", "", tb)
    elif mode == "forced_output":
        tb = tb.replace("initial begin", "initial begin force count=0;")
    elif mode == "wrong_clock":
        tb = tb.replace("reg clk=0,", "reg decoy=0,clk=0,").replace("clk=1;", "decoy=1;")
    result = consumer(tmp_path, COUNTER_PROMPT, COUNTER_RTL, tb)
    assert result["status"] == "FAIL", result  # legacy overflow still needs its own region witness
    items = {item["kind"]: item for item in coverage.run(
        {"user_prompt": COUNTER_PROMPT}, COUNTER_RTL, tb, None, True)["items"]
        if item["kind"] in {"overflow", "saturation"}}
    assert items["saturation"]["covered"] == (mode == "full")
    assert items["overflow"]["covered"] is False


@pytest.mark.parametrize("mutant", ["good", "wrapping"])
def test_native_endpoint_trace_distinguishes_saturation_from_wrapping(tmp_path, native, mutant):
    rtl = COUNTER_RTL
    if mutant == "wrapping":
        rtl = rtl.replace("if(count!=7)", "").replace("if(count!=0)", "")
    tb = counter_tb()
    result, candidate, challenge = native_challenge(tmp_path, native, rtl, tb)
    assert result["status"] == ("PASS" if mutant == "good" else "FAIL"), result
    # Source coverage establishes exercise; native execution judges the values.
    measured = bd._program_review_coverage_result(COUNTER_PROMPT, candidate, [challenge])
    assert measured["status"] == "FAIL"  # no new endpoint credit on legacy overflow
    saturation, = [item for item in coverage.run({"user_prompt": COUNTER_PROMPT}, rtl, tb, None, True)["items"]
                   if item["kind"] == "saturation"]
    assert saturation["covered"] == (mutant == "good")


@pytest.mark.parametrize("local", [False, True])
def test_direct_output_concat_requires_every_member_to_be_bound(tmp_path, local):
    rtl = RTL.replace("output wire z)", "output wire z, output wire nz)").replace("assign z = q;", "assign z = q; assign nz = ~q;")
    prompt = PROMPT.replace("output wire z)", "output wire z, output wire nz)")
    tb = TB.replace("wire observed;", "wire observed, other; reg decoy=1;").replace(".z(observed)", ".z(observed), .nz(other)")
    tb = tb.replace("observed !== 1'b0", "{observed,other} !== 2'b01").replace("observed !== 1'b1", "{observed,other} !== 2'b10")
    if local:
        tb = tb.replace("{observed,other}", "{observed,decoy}")
    assert consumer(tmp_path, prompt, rtl, tb)["status"] == ("FAIL" if local else "PASS")


def test_unrelated_output_endpoints_do_not_prove_internal_saturation(tmp_path):
    rtl = COUNTER_RTL.replace("if(count!=7)", "").replace("if(count!=0)", "")
    result = consumer(tmp_path, COUNTER_PROMPT, rtl, counter_tb())
    assert result["status"] == "FAIL"
    assert {item["kind"] for item in result["blocking_gap_items"]} >= {"overflow", "saturation"}


def reference_tb(indexed=False, helper=False):
    reference = "model[slot]" if indexed else "model"
    declaration = "reg [2:0] model[0:1];integer slot=0;" if indexed else "reg [2:0] model=0;"
    tb = counter_tb().replace("wire [2:0] count;", "wire [2:0] count;" + declaration)
    if indexed:
        tb = tb.replace("initial begin", "initial begin model[0]=0;", 1)
    update = f"if(up)begin if({reference}<3'd7){reference}={reference}+3'd1;end else begin if({reference}>3'd0){reference}={reference}-3'd1;end "
    tb = re.sub(r"if\(count!==3'd[0-7]\)", lambda m: update + f"if(count!=={reference})", tb)
    # The reset observation precedes normal training and its reference update.
    tb = tb.replace(update, "", 1)
    tb = tb.replace(update, "")
    tb = tb.replace("initial begin", f"always @(posedge clk)begin if(rst){reference}=0;else if(advance)begin {update}end end\ninitial begin", 1)
    if helper:
        tb = tb.replace(f"if(count!=={reference})begin $display(\"VIBEIC_AI_CHALLENGE=FAIL\");$fatal(1);end", f"ck(count==={reference});")
        tb = tb.replace("initial begin", 'task ck(input ok);begin if(!ok)begin $display("VIBEIC_AI_CHALLENGE=FAIL");$fatal(1);end end endtask\ninitial begin', 1)
    return tb


@pytest.mark.parametrize("indexed,helper", [(False, False), (True, False), (True, True)])
def test_clamped_reference_value_is_compared_to_bound_output(tmp_path, indexed, helper):
    tb = reference_tb(indexed, helper)
    result = consumer(tmp_path, COUNTER_PROMPT, COUNTER_RTL, tb)
    saturation, = [item for item in coverage.run({"user_prompt": COUNTER_PROMPT}, COUNTER_RTL, tb, None, True)["items"] if item["kind"] == "saturation"]
    assert saturation["covered"] is True, result
    assert result["status"] == "PASS", result


@pytest.mark.parametrize("mutation", ["loop_only", "missing_lower_guard", "unrelated_reference", "forced_output", "no_fatal"])
def test_reference_counter_cannot_be_replaced_by_loop_bound_or_unused_model(tmp_path, mutation):
    tb = reference_tb(True, True)
    if mutation == "loop_only":
        tb = '''module vibeic_ai_challenge_tb;
reg clk=0,rst=1,advance=0,up=1;wire [2:0] count;integer i;
bounded_count dut(.clk(clk),.rst(rst),.advance(advance),.up(up),.count(count));
initial begin for(i=0;i<4;i=i+1)begin
#1;clk=1;#1;if(count!==3'd0)begin $display("VIBEIC_AI_CHALLENGE=FAIL");$fatal(1);end
#1;clk=0;end $display("VIBEIC_AI_CHALLENGE=PASS");$finish;end endmodule'''
    elif mutation == "missing_lower_guard":
        tb = tb.replace("if(model[slot]>3'd0)", "")
    elif mutation == "unrelated_reference":
        tb = tb.replace("ck(count===model[slot])", "ck(count===3'd0)")
    elif mutation == "forced_output":
        tb = tb.replace("initial begin", "initial begin force count=0;")
    else:
        tb = tb.replace("$fatal(1)", "$display(\"diagnostic\")")
    saturation, = [item for item in coverage.run({"user_prompt": COUNTER_PROMPT}, COUNTER_RTL, tb, None, True)["items"] if item["kind"] == "saturation"]
    assert saturation["covered"] is False
    assert consumer(tmp_path, COUNTER_PROMPT, COUNTER_RTL, tb)["status"] == "FAIL"


@pytest.mark.parametrize("mutant", ["good", "wrapping"])
def test_native_indexed_reference_counter_and_helper_comparison(tmp_path, native, mutant):
    rtl = COUNTER_RTL
    if mutant == "wrapping":
        rtl = rtl.replace("if(count!=7)", "").replace("if(count!=0)", "")
    tb = reference_tb(True, True)
    result, candidate, challenge = native_challenge(tmp_path, native, rtl, tb)
    assert result["status"] == ("PASS" if mutant == "good" else "FAIL"), result
    saturation, = [item for item in coverage.run({"user_prompt": COUNTER_PROMPT}, rtl, tb, None, True)["items"] if item["kind"] == "saturation"]
    assert saturation["covered"] is True


@pytest.mark.parametrize("separator", ["\n", ".\n"])
def test_wrapped_initial_assumption_cannot_swallow_independent_runtime_reset(tmp_path, separator):
    prompt = PROMPT.replace("before the machine begins.", "before the\nmachine begins" + separator + "Reset clears state.")
    result = consumer(tmp_path, prompt, RTL, TB)
    assert result["status"] == "FAIL"
    assert {item["kind"] for item in result["blocking_gap_items"]} == {"reset"}


DECISION_PROMPT = """module decision_cell(input clk,input rst,input step,input up,output decision);
A two-bit internal counter saturates at each limit. Active-high synchronous
reset clears the counter. On each positive clock edge, step enables one increment
when up is high or one decrement otherwise. decision is the counter MSB.
"""
DECISION_RTL = """module decision_cell(input clk,input rst,input step,input up,output decision);
reg [1:0] count;
assign decision=count[1];
always @(posedge clk)begin
 if(rst)count<=0;
 else if(step)begin
  if(up)begin if(count!=3)count<=count+1;end
  else begin if(count!=0)count<=count-1;end
 end
end
endmodule
"""


def decision_tb():
    prefix = """module vibeic_ai_challenge_tb;
reg clk=0,rst=1,step=0,up=1;wire observed;reg [1:0] model=0;
decision_cell dut(.clk(clk),.rst(rst),.step(step),.up(up),.decision(observed));
always @(posedge clk)begin
 if(rst)model=0;
 else if(step)begin
  if(up)begin if(model<3)model=model+1;end
  else begin if(model>0)model=model-1;end
 end
end
initial begin #1;clk=1;#1;clk=0;rst=0;step=1;
"""
    trace = []
    for direction in [1]*6 + [0]*6 + [1]*3:
        trace.append(f"up={direction};#1;clk=1;#1;if(observed!==model[1])begin $display(\"VIBEIC_AI_CHALLENGE=FAIL\");$fatal(1);end #1;clk=0;")
    return prefix + "\n".join(trace) + '\n$display("VIBEIC_AI_CHALLENGE=PASS");$finish;end endmodule'


@pytest.mark.parametrize("mutant", ["good", "wrapping"])
def test_native_internal_counter_uses_independent_model_msb_not_unrelated_endpoints(tmp_path, native, mutant):
    rtl = DECISION_RTL
    if mutant == "wrapping":
        rtl = rtl.replace("if(count!=3)", "").replace("if(count!=0)", "")
    tb = decision_tb()
    measured = consumer(tmp_path, DECISION_PROMPT, rtl, tb)
    assert measured["status"] == "PASS", measured
    result, _, _ = native_challenge(tmp_path, native, rtl, tb)
    assert result["status"] == ("PASS" if mutant == "good" else "FAIL"), result


@pytest.mark.parametrize("helper", [False, True])
def test_unrelated_unreachable_fatal_cannot_back_a_reference_comparison(tmp_path, helper):
    tb = reference_tb(True, helper).replace('$fatal(1);', '$display("diagnostic");')
    tb = tb.replace('$finish;', "if(1'b0)$fatal(1);$finish;")
    assert consumer(tmp_path, COUNTER_PROMPT, COUNTER_RTL, tb)["status"] == "FAIL"


@pytest.mark.parametrize("mutation", ["wrong_polarity", "diagnostic_helper", "disabled_call"])
def test_reference_helper_must_fatally_reject_false_and_be_called(tmp_path, mutation):
    tb = reference_tb(True, True)
    if mutation == "wrong_polarity":
        tb = tb.replace("if(!ok)", "if(ok)")
    elif mutation == "diagnostic_helper":
        tb = tb.replace('$fatal(1);', '$display("diagnostic");') + "\nmodule unused;initial $fatal(1);endmodule"
    else:
        tb = tb.replace("ck(count===model[slot]);", "if(1'b0)ck(count===model[slot]);")
    assert consumer(tmp_path, COUNTER_PROMPT, COUNTER_RTL, tb)["status"] == "FAIL"
