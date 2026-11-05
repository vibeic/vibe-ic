"""Neutral synchronous-clear attribution through the public coverage consumer."""
import pytest

import spec_coverage_check as coverage


def fixture(control="purge_i", *, active=1, negative_edge=False):
    edge = "negedge" if negative_edge else "posedge"
    idle, tick = (1, 0) if negative_edge else (0, 1)
    condition = control if active else "!" + control
    rtl = f"""module storage(input clock_i, input {control}, input [4:0] payload,
output reg [4:0] state);
always @({edge} clock_i) if ({condition}) state <= 5'd0; else state <= payload;
endmodule
"""
    tb = f"""module checks;
reg clock_i; reg {control}; reg [4:0] payload; wire [4:0] state;
storage dut(.clock_i(clock_i), .{control}({control}), .payload(payload), .state(state));
initial begin
clock_i={idle}; {control}={1-active}; payload=5'd17; #2;
clock_i={tick}; #1;
if (state !== 5'd17) $fatal(1, "baseline");
clock_i={idle}; #1; {control}={active}; #1;
if (state !== 5'd17) $fatal(1, "retention");
clock_i={tick}; #1;
if (state !== 5'd0) $fatal(1, "clear");
clock_i={idle}; {control}={1-active}; payload=5'd9; #2;
clock_i={tick}; #1;
if (state !== 5'd9) $fatal(1, "recovery");
$finish;
end
endmodule
"""
    prompt = (f"A storage register has active-{'high' if active else 'low'} "
              "synchronous reset clearing state to zero. "
              "Hold state between clock edges.\n" + rtl.split("always")[0])
    return prompt, rtl, tb


def measured(prompt, rtl, tb):
    report = coverage.run({"user_prompt": prompt}, rtl, tb, None, True)
    reset, = [item for item in report["items"] if item["kind"] == "reset"]
    return report, reset


@pytest.mark.parametrize("control,active,negative_edge", [
    ("purge_i", 1, False), ("discard_i", 0, False), ("invalidate_i", 1, True),
])
def test_role_bound_clear_retention_and_recovery(control, active, negative_edge):
    prompt, rtl, tb = fixture(control, active=active, negative_edge=negative_edge)
    report, reset = measured(prompt, rtl, tb)
    assert reset["covered"] is True, reset
    assert report["blocked"] is False, report


def test_named_connection_local_alias_is_behaviorally_bound():
    prompt, rtl, tb = fixture()
    tb = tb.replace("reg purge_i;", "reg control_local;").replace(
        "(purge_i)", "(control_local)").replace("purge_i=", "control_local=")
    _, reset = measured(prompt, rtl, tb)
    assert reset["covered"] is True, reset


@pytest.mark.parametrize("change", [
    "missing_retention", "missing_clear", "missing_recovery", "missing_baseline",
    "unbound_control", "unobserved_output", "asynchronous_dut", "keywords_only",
    "comments_only", "wrong_retained_value", "same_time_retention", "no_assertion",
    "aliased_input", "helper_driven_control", "wrong_polarity",
    "zero_data_at_clear", "irrelevant_control", "ignores_clear",
    "second_sequential_driver", "disabled_reset_branch", "non_scalar_control",
])
def test_incomplete_or_unbound_clear_witness_stays_blocked(change):
    prompt, rtl, tb = fixture()
    missing = {"missing_retention": "retention", "missing_clear": "clear",
               "missing_recovery": "recovery", "missing_baseline": "baseline"}
    if change in missing:
        tb = "\n".join(line for line in tb.splitlines()
                       if f'"{missing[change]}"' not in line)
    elif change == "unbound_control":
        tb = tb.replace(".purge_i(purge_i)", ".purge_i(1'b0)")
    elif change == "unobserved_output":
        tb = tb.replace(".state(state)", ".state()").replace(
            "wire [4:0] state;", "reg [4:0] state;")
    elif change == "asynchronous_dut":
        rtl = rtl.replace("posedge clock_i)", "posedge clock_i or posedge purge_i)")
    elif change in {"keywords_only", "comments_only"}:
        annotation = '$display("reset rst por");' if change == "keywords_only" else "// reset rst por"
        tb = tb[:tb.index("initial begin")] + "initial begin\n" + annotation + "\n$finish; end endmodule"
    elif change == "wrong_retained_value":
        tb = tb.replace('state !== 5\'d17) $fatal(1, "retention")',
                        'state !== 5\'d0) $fatal(1, "retention")')
    elif change == "same_time_retention":
        tb = tb.replace("purge_i=1; #1;", "purge_i=1;")
    elif change == "no_assertion":
        tb = tb.replace("purge_i=1;", "purge_i=0;")
    elif change == "aliased_input":
        rtl = rtl.replace("input purge_i,", "input purge_i, input shared,")
        tb = tb.replace(".purge_i(purge_i),", ".purge_i(purge_i), .shared(purge_i),")
    elif change == "helper_driven_control":
        tb = tb.replace("initial begin", "source extra(purge_i); initial begin")
        tb += "\nmodule source(output reg driven); initial driven=0; endmodule\n"
    elif change == "wrong_polarity":
        prompt = prompt.replace("active-high", "active-low")
    elif change == "zero_data_at_clear":
        tb = tb.replace("purge_i=1;", "purge_i=1; payload=0;")
    elif change == "irrelevant_control":
        rtl = rtl.replace("input purge_i,", "input purge_i, input unrelated,")
        tb = tb.replace("reg purge_i;", "reg purge_i; reg unrelated;").replace(
            ".purge_i(purge_i),", ".purge_i(purge_i), .unrelated(unrelated),")
        tb = tb.replace("purge_i=1;", "unrelated=1; payload=0;")
    elif change == "ignores_clear":
        rtl = rtl.replace("if (purge_i) state <= 5'd0; else ", "")
    elif change == "second_sequential_driver":
        rtl = rtl.replace("endmodule", "always @(posedge purge_i) state<=0; endmodule")
    elif change == "disabled_reset_branch":
        rtl = rtl.replace("always @", "if (0) begin always @").replace("endmodule", "end endmodule")
    elif change == "non_scalar_control":
        rtl = rtl.replace("input purge_i,", "input [2:0] purge_i,")
    report, reset = measured(prompt, rtl, tb)
    assert reset["covered"] is False, reset
    assert report["blocked"] is True, report


def test_legacy_named_reset_with_complete_witness_stays_covered():
    report, reset = measured(*fixture("rst_n", active=0))
    assert reset["covered"] is True, reset
    assert report["blocked"] is False, report


@pytest.mark.parametrize("form", ["nonzero_inline", "zero_task"])
def test_existing_valid_reset_witnesses_outside_inline_zero_grammar_stay_covered(form):
    prompt, rtl, tb = fixture()
    tb = tb.replace('"clear"', '"synchronous reset value"')
    if form == "nonzero_inline":
        prompt = prompt.replace("[4:0]", "[7:0]").replace("clearing state to zero", "setting state to 165")
        rtl = rtl.replace("[4:0]", "[7:0]").replace("5'd0", "8'd165")
        tb = tb.replace("[4:0]", "[7:0]").replace("5'd0", "8'd165")
    else:
        task = "task tick; begin clock_i=1; #1; end endtask\n"
        tb = tb.replace("clock_i=1; #1;", "tick;")
        tb = tb.replace("initial begin", task + "initial begin")
    report, reset = measured(prompt, rtl, tb)
    assert reset["covered"] is True, reset
    assert report["blocked"] is False, report


def test_supported_grammar_alone_is_not_an_unspecified_polarity_witness():
    prompt, rtl, tb = fixture()
    prompt = prompt.replace("active-high ", "")
    tb = tb[:tb.index("initial begin")] + 'initial begin $display("reset rst por"); $finish; end endmodule'
    report, reset = measured(prompt, rtl, tb)
    assert reset["covered"] is False, reset
    assert report["blocked"] is True, report


@pytest.mark.parametrize("complete", [False, True])
def test_ordinary_program_review_consumer_reads_same_obligation(tmp_path, complete):
    import benchmark_dispatch as dispatch
    prompt, rtl, tb = fixture()
    if not complete:
        tb = "\n".join(line for line in tb.splitlines() if '"retention"' not in line)
    design = tmp_path / "unit.sv"
    challenge = tmp_path / "check.sv"
    design.write_text(rtl)
    challenge.write_text(tb)
    result = dispatch._program_review_coverage_result(prompt, {"rtl_paths": [str(design)]},
        [{"path": str(challenge), "sha256": dispatch._sha256_text(tb)}])
    assert result["status"] == ("PASS" if complete else "FAIL"), result
    assert result["blocking_gaps"] == (0 if complete else 1), result
