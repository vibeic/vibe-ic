from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

import spec_coverage_check as SC  # noqa: E402
from _hostpaths import require_repo  # noqa: E402


_TB = """module tb;
reg [7:0] data_i; wire [7:0] data_o;
neutral dut(.data_i(data_i), .data_o(data_o));
initial begin data_i = 8'h00; #1; end
endmodule
"""


def _rtl(width: str = "8", *, extra_input: bool = False) -> str:
    extra = ", input enable_i" if extra_input else ""
    return (f"module neutral(input [{width}-1:0] data_i, "
            f"output [{width}-1:0] data_o{extra});\n"
            "assign data_o = ~data_i;\nendmodule\n")


def _spec(rtl: str, illustration: str) -> str:
    return illustration + "\nExact source interface:\n```systemverilog\n" + rtl + "```\n"


def _worked(spec: str, rtl: str | None, tb: str = _TB):
    report = SC.run({"user_prompt": spec}, rtl, tb, None, True)
    examples = [item for item in report["items"]
                if item["kind"] == "worked_example"]
    assert examples
    return report, examples


def test_real_source_separate_width_illustration_is_advisory():
    rtl = require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "programs", "tests",
        "fixtures", "librelane_lint_frontend", "plain.v").read_text()
    spec = _spec(
        rtl,
        "For example, a 16-bit vector given the input 0x1234 -> 0x1234.")
    tb = """module tb;
reg [7:0] value_i; wire [7:0] value_o;
plain dut(.value_i(value_i), .value_o(value_o));
initial begin value_i = 8'h00; #1; end
endmodule
"""
    report, examples = _worked(spec, rtl, tb)
    assert report["blocked"] is False
    assert all(item["covered"] is False for item in examples)
    assert all(item["block_eligible"] is False for item in examples)
    assert all(item["advisory_note"] for item in examples)


def test_source_owned_requirement_has_to():
    rtl = _rtl()
    owner = ("For example, a 16-bit vector given the input 0x1234 -> 0xEDCB "
             "and the implementation has to satisfy this example.")
    report, examples = _worked(_spec(rtl, owner), rtl)
    assert report["blocked"] is True
    assert all(item["covered"] is False for item in examples)
    assert all(item["block_eligible"] is True for item in examples)


def test_source_owned_requirement_needs_to():
    rtl = _rtl()
    owner = ("For example, a 16-bit vector given the input 0x1234 -> 0xEDCB "
             "and the implementation needs to satisfy this example.")
    report, examples = _worked(_spec(rtl, owner), rtl)
    assert report["blocked"] is True
    assert all(item["covered"] is False for item in examples)
    assert all(item["block_eligible"] is True for item in examples)


def test_source_owned_requirement_prefix():
    rtl = _rtl()
    owner = ("The implementation must satisfy, for example, a 16-bit vector "
             "given the input 0x1234 -> 0xEDCB.")
    report, examples = _worked(_spec(rtl, owner), rtl)
    assert report["blocked"] is True
    assert all(item["covered"] is False for item in examples)
    assert all(item["block_eligible"] is True for item in examples)


def test_source_owned_requirement_inside_owner_prefix():
    rtl = _rtl()
    owner = ("For example, a 16-bit vector that the implementation must "
             "satisfy, given the input 0x1234 -> 0xEDCB.")
    report, examples = _worked(_spec(rtl, owner), rtl)
    assert report["blocked"] is True
    assert all(item["covered"] is False for item in examples)
    assert all(item["block_eligible"] is True for item in examples)


@pytest.mark.parametrize("case", [
    "same_width",
    "default_width",
    "source_owned_requirement",
    "ambiguous_width",
    "no_explicit_owner",
    "owner_in_other_sentence",
    "candidate_width_mismatch",
    "unknown_source_width",
    "extra_candidate_input",
    "no_rtl",
])
def test_real_or_ambiguous_examples_remain_blocking(case: str):
    source_rtl = _rtl()
    candidate = source_rtl
    owner = "For example, a 16-bit vector given the input 0x1234 -> 0xEDCB."
    if case == "same_width":
        owner = "For example, an 8-bit vector given the input 0x12 -> 0xED."
    elif case == "default_width":
        source_rtl = candidate = (
            "module neutral(input data_i, output data_o); "
            "assign data_o = ~data_i; endmodule\n")
    elif case == "source_owned_requirement":
        owner = ("For example, a 16-bit vector given the input 0x1234 -> 0xEDCB; "
                 "the implementation must satisfy this example.")
    elif case == "ambiguous_width":
        owner = "For example, a wide vector given the input 0x1234 -> 0xEDCB."
    elif case == "no_explicit_owner":
        owner = "Worked example: 0x1234 -> 0xEDCB."
    elif case == "owner_in_other_sentence":
        owner = ("For example, consider a 16-bit vector. "
                 "Given the input 0x1234 -> 0xEDCB.")
    elif case == "candidate_width_mismatch":
        candidate = _rtl("4")
    elif case == "unknown_source_width":
        source_rtl = candidate = _rtl("WIDTH")
    elif case == "extra_candidate_input":
        source_rtl = candidate = _rtl(extra_input=True)
    elif case == "no_rtl":
        candidate = None
    report, examples = _worked(_spec(source_rtl, owner), candidate)
    assert report["blocked"] is True
    assert all(item["covered"] is False for item in examples)
    assert all(item["block_eligible"] is True for item in examples)


@pytest.mark.parametrize("suffix,eligible", [
    (".", False),
    (", because the lowest high bit determines the position.", False),
    (" and the implementation must satisfy this example.", True),
    (", because the implementation must satisfy this example.", True),
])
def test_worded_hdl_literals_retain_separate_width_owner(suffix, eligible):
    rtl = _rtl()
    spec = _spec(rtl, "For example, a 12-bit priority encoder given the input "
                 "12'b000100000000 would output 4'd8" + suffix)
    report, examples = _worked(spec, rtl)
    assert all(item["block_eligible"] is eligible for item in examples)


@pytest.mark.parametrize("owner_width,candidate_width", [(8, 8), (12, 4)])
def test_worded_illustration_never_waives_real_or_changed_interface(owner_width, candidate_width):
    source_rtl = _rtl()
    spec = _spec(source_rtl, f"For example, a {owner_width}-bit encoder given the input "
                 "12'd256 would output 4'd8.")
    _, examples = _worked(spec, _rtl(str(candidate_width)))
    assert all(item["block_eligible"] for item in examples)
