import inspect

import pytest

import spec_coverage_check as coverage
from test_reset_role_behavioral_coverage import fixture, measured


@pytest.mark.parametrize("extra", ["baseline", "retention", "clear", "additional_clear_edge", "pre_assert_baseline"])
def test_additional_valid_observation_keeps_complete_ordered_witness(extra):
    prompt, rtl, tb = fixture()
    label = extra if extra in {"baseline", "retention", "clear"} else "clear"
    value = 0 if label == "clear" else 17
    original = f'if (state !== 5\'d{value}) $fatal(1, "{label}");'
    added = f'#1; if (state !== 5\'d{value}) $fatal(1, "extra observation");'
    if extra == "additional_clear_edge":
        added = 'clock_i=0; #1; clock_i=1; #1; if(state!==0)$fatal(1,"still clear");'
    if extra == "pre_assert_baseline":
        tb = tb.replace("purge_i=1;", 'if(state!==17)$fatal(1,"additional baseline"); purge_i=1;')
    else:
        tb = tb.replace(original, original + "\n" + added)
    report, reset = measured(prompt, rtl, tb)
    assert reset["covered"] is True, reset
    assert report["blocked"] is False, report


def with_unused_port(rtl, tb, initial):
    rtl = rtl.replace("input purge_i,", "input purge_i, input spare,")
    tb = tb.replace("reg purge_i;", "reg purge_i; reg spare;").replace(
        ".purge_i(purge_i),", ".purge_i(purge_i), .spare(spare),").replace(
        "initial begin", f"initial begin spare={initial};", 1)
    return rtl, tb


@pytest.mark.parametrize("mode", ["zero", "toggle", "unknown"])
def test_unused_input_values_do_not_replace_the_actual_data_role(mode):
    prompt, rtl, tb = fixture()
    rtl, tb = with_unused_port(rtl, tb, "1'bx" if mode == "unknown" else "0")
    if mode == "toggle":
        tb = tb.replace("purge_i=1; #1;", "purge_i=1; spare=1; #1; spare=0;")
    report, reset = measured(prompt, rtl, tb)
    assert reset["covered"] is True, reset
    assert report["blocked"] is False, report


@pytest.mark.parametrize("phase", ["assertion", "baseline"])
def test_irrelevant_nonzero_input_cannot_rescue_zero_actual_data(phase):
    prompt, rtl, tb = fixture()
    rtl, tb = with_unused_port(rtl, tb, "1")
    if phase == "assertion":
        tb = tb.replace("purge_i=1;", "purge_i=1; payload=0;")
    else:
        tb = tb.replace('if (state !== 5\'d17) $fatal(1, "baseline");',
            'payload=0; if (state !== 5\'d17) $fatal(1, "baseline");')
    report, reset = measured(prompt, rtl, tb)
    assert reset["covered"] is False, reset
    assert report["blocked"] is True, report


@pytest.mark.parametrize("expression", ["payload ^ payload", "payload & 5'd0", "payload + spare"])
def test_data_expression_is_outside_the_new_direct_copy_proof(expression):
    prompt, rtl, tb = fixture()
    rtl, tb = with_unused_port(rtl, tb, "1")
    rtl = rtl.replace("state <= payload;", f"state <= {expression};")
    report, reset = measured(prompt, rtl, tb)
    assert reset["covered"] is False, reset
    assert report["blocked"] is True, report
    markers = set()
    kwargs = {"reset_checks": markers} if "reset_checks" in inspect.signature(coverage._tb_direct_state_checks).parameters else {}
    coverage._tb_direct_state_checks(rtl, coverage._HDL.strip_hdl_comments_and_strings(tb), **kwargs)
    assert markers == set(), markers


def held_literal_fixture(literal, input_width=5, output_width=5):
    prompt, rtl, tb = fixture()
    for old, new in (("input [4:0] payload", f"input [{input_width-1}:0] payload"),
                     ("output reg [4:0] state", f"output reg [{output_width-1}:0] state")):
        prompt, rtl = prompt.replace(old, new), rtl.replace(old, new)
    tb = tb.replace("reg [4:0] payload", f"reg [{input_width-1}:0] payload").replace(
        "wire [4:0] state", f"wire [{output_width-1}:0] state")
    tb = tb.replace('if (state !== 5\'d17) $fatal(1, "baseline");',
                    f'payload={literal}; if (state !== 5\'d17) $fatal(1, "baseline");')
    return prompt, rtl, tb


def assert_public_and_consumer(tmp_path, prompt, rtl, tb, expected):
    import benchmark_dispatch as dispatch
    report, reset = measured(prompt, rtl, tb)
    design, challenge = tmp_path / "dut.sv", tmp_path / "tb.sv"
    design.write_text(rtl)
    challenge.write_text(tb)
    consumer = dispatch._program_review_coverage_result(prompt, {"rtl_paths": [str(design)]},
        [{"path": str(challenge), "sha256": dispatch._sha256_text(tb)}])
    assert reset["covered"] is expected, reset
    assert report["blocked"] is not expected, report
    assert consumer["status"] == ("PASS" if expected else "FAIL"), consumer
    assert consumer["blocking_gaps"] == (0 if expected else 1), consumer


@pytest.mark.parametrize("literal,input_width,output_width,expected", [
    ("6'd32", 5, 5, False), ("5'd32", 5, 5, False), ("6'd64", 8, 8, False),
    ("6'd18", 5, 5, True), ("6'd33", 5, 5, True), ("5'd31", 5, 5, True),
    ("6'sd32", 8, 8, True), ("6'd32", 6, 5, False), ("6'd33", 6, 5, True),
])
def test_copy_value_after_literal_input_and_output_widths(tmp_path, literal, input_width, output_width, expected):
    assert_public_and_consumer(tmp_path, *held_literal_fixture(literal, input_width, output_width), expected)


@pytest.mark.parametrize("unknown", ["input", "tb_net"])
def test_unknown_held_data_width_cannot_fabricate_proof(tmp_path, unknown):
    prompt, rtl, tb = held_literal_fixture("6'd32")
    if unknown == "input":
        rtl = rtl.replace("input [4:0] payload", "input [UNRESOLVED-1:0] payload")
    else:
        tb = tb.replace("reg [4:0] payload", "reg [UNRESOLVED-1:0] payload")
    assert_public_and_consumer(tmp_path, prompt, rtl, tb, False)
