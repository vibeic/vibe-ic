import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import counter_advanced_synth as counter


def prompt(digits=6, enable_range="[8:4]", style="header", q_range=None,
           clock_range="", duplicate=""):
    q_range = q_range or f"[{digits * 4 - 1}:0]"
    declarations = [f"input {clock_range} clock", "input rst",
                    f"output {enable_range} upper_tick",
                    f"output {q_range} digits"]
    if duplicate:
        declarations.append(duplicate)
    if style == "header":
        interface = "module DecimalChain(" + ", ".join(declarations) + ");"
    else:
        interface = "\n".join("- " + declaration for declaration in declarations)
    return interface + (f"\nImplement a {digits}-digit BCD counter. "
                        "Output an enable signal indicating when each upper digit "
                        "should increment. Include a synchronous active-high reset.")


@pytest.mark.parametrize("style", ["header", "bullet"])
@pytest.mark.parametrize("digits,span", [(6, "[8:4]"), (6, "[4:8]"),
                                        (3, "[6:5]"), (3, "[5:6]"),
                                        (2, "[9:9]")])
def test_opaque_enable_preserves_packed_bounds(style, digits, span):
    rtl = counter.synth(prompt(digits, span, style), top="DecimalChain")
    assert rtl is not None
    declaration = re.search(r"output\s+(\[[^]]+\])\s+upper_tick\b", rtl)
    actual = declaration.group(1) if declaration else "scalar"
    assert actual == span


@pytest.mark.parametrize("style", ["header", "bullet"])
def test_zero_based_enable_and_scalar_controls_stay_supported(style):
    rtl = counter.synth(prompt(3, "[1:0]", style), top="DecimalChain")
    assert rtl is not None
    assert "output [1:0] upper_tick" in rtl
    assert "input clock," in rtl and "input rst," in rtl
    assert "assign upper_tick = enable[2:1];" in rtl


def test_scalar_enable_stays_supported():
    rtl = counter.synth(prompt(2, ""), top="DecimalChain")
    assert rtl is not None and "output upper_tick," in rtl


def test_width_only_bullets_stay_supported():
    text = ("- input clock\n- input rst\n- output upper_tick (5 bits)\n"
            "- output digits (24 bits)\nImplement a 6-digit BCD counter. "
            "Output an enable signal indicating when each upper digit should "
            "increment. Include a synchronous active-high reset.")
    rtl = counter.synth(text, top="DecimalChain")
    assert rtl is not None and "output [4:0] upper_tick" in rtl


@pytest.mark.parametrize("overrides", [
    {"q_range": "[27:4]"}, {"q_range": "[0:23]"},
    {"clock_range": "[1:0]"}, {"enable_range": "[9:4]"},
    {"duplicate": "output [9:5] upper_tick"},
])
def test_incompatible_or_ambiguous_interface_is_refused(overrides):
    assert counter.synth(prompt(**overrides), top="DecimalChain") is None


@pytest.mark.parametrize("span", ["[4:0]", "[8:4]", "[4:8]"])
@pytest.mark.parametrize("description", [": enable output, asserted on carry",
                                         " enable output, asserted on carry"])
def test_classic_bullet_description_does_not_add_ports(span, description):
    text = prompt(6, span, "bullet").replace(
        "upper_tick\n", f"upper_tick{description}\n")
    rtl = counter.synth(text, top="DecimalChain")
    assert rtl is not None
    assert f"output {span} upper_tick" in rtl


@pytest.mark.parametrize("bullet_span", ["[7:3]", "[4:8]"])
def test_header_and_bullet_endpoint_conflict_is_refused(bullet_span):
    text = prompt(6, "[8:4]", "header") + "\n" + prompt(6, bullet_span, "bullet")
    assert counter.synth(text, top="DecimalChain") is None


@pytest.mark.parametrize("bullet_span", ["[8:4]", "[ 8 : 4 ]", "[08:04]"])
def test_matching_header_and_reordered_bullets_stay_supported(bullet_span):
    lines = prompt(6, bullet_span, "bullet").splitlines()
    text = prompt(6, "[8:4]", "header") + "\n" + "\n".join(
        list(reversed(lines[:4])) + lines[4:])
    rtl = counter.synth(text, top="DecimalChain")
    assert rtl is not None
    assert "assign upper_tick = enable[5:1];" in rtl


def test_header_bounds_with_width_only_bullets_stay_supported():
    text = prompt(6, "[8:4]", "header") + (
        "\n- input clock\n- input rst\n- output upper_tick (5 bits)\n"
        "- output digits (24 bits)\n")
    rtl = counter.synth(text, top="DecimalChain")
    assert rtl is not None
    assert "output [8:4] upper_tick" in rtl


@pytest.mark.parametrize("enable,width", [("(5 bits) upper_tick", "(24 bits) digits"),
                                          ("(5 bits) upper_tick", "digits (24 bits)"),
                                          ("upper_tick (5 bits)", "(24 bits) digits")])
@pytest.mark.parametrize("header", [False, True])
def test_before_name_width_bullets_stay_supported(enable, width, header):
    text = (f"- input clock\n- input rst\n- output {enable}\n- output {width}\n"
            "Implement a 6-digit BCD counter. Output an enable signal indicating "
            "when each upper digit should increment. Include a synchronous "
            "active-high reset.\n")
    if header:
        text = prompt(6, "[8:4]", "header") + "\n" + text
    rtl = counter.synth(text, top="DecimalChain")
    assert rtl is not None
    assert f"output {'[8:4]' if header else '[4:0]'} upper_tick" in rtl


@pytest.mark.parametrize("header", [False, True])
def test_identical_bullet_restatements_stay_supported(header):
    text = prompt(6, "[4:0]", "bullet")
    text += "\n" + "\n".join(text.splitlines()[:4])
    if header:
        text = prompt(6, "[4:0]", "header") + "\n" + text
    rtl = counter.synth(text, top="DecimalChain")
    assert rtl is not None
    assert rtl.count("output [4:0] upper_tick") == 1


def test_width_only_restatement_does_not_impose_zero_based_endpoints():
    text = prompt(6, "[4:8]", "bullet")
    text += "\n- output (5 bits) upper_tick\n- output (24 bits) digits"
    rtl = counter.synth(text, top="DecimalChain")
    assert rtl is not None and "output [4:8] upper_tick" in rtl


@pytest.mark.parametrize("span", ["[8:4]", "[4:8]"])
def test_section_bounded_numeric_spans_use_existing_port_grammar(span):
    text = ("### Inputs:\n- `clock`\n- `rst`\n### Outputs:\n"
            f"- `upper_tick` {span}\n- `digits` [23:0]\n"
            "Implement a 6-digit BCD counter. Output an enable signal indicating "
            "when each upper digit should increment. Include a synchronous "
            "active-high reset.\n")
    rtl = counter.synth(text, top="DecimalChain")
    assert rtl is not None and f"output {span} upper_tick" in rtl


def section_prompt(enable="[8:4] (5 bits)", digits="[23:0] (24 bits)"):
    return ("### Inputs:\n- `clock`\n- `rst`\n### Outputs:\n"
            f"- `upper_tick` {enable}\n- `digits` {digits}\n"
            "Implement a 6-digit BCD counter. Output an enable signal indicating "
            "when each upper digit should increment. Include a synchronous "
            "active-high reset.\n")


@pytest.mark.parametrize("span", ["[8:4]", "[4:8]"])
@pytest.mark.parametrize("annotation", ["{} (5 bits)", "(5 bits) {}"])
def test_section_explicit_span_survives_redundant_width(span, annotation):
    rtl = counter.synth(section_prompt(annotation.format(span)), top="DecimalChain")
    assert rtl is not None and f"output {span} upper_tick" in rtl


@pytest.mark.parametrize("span", ["[27:4]", "[0:23]"])
def test_section_annotated_digit_span_keeps_indexed_refusal(span):
    assert counter.synth(section_prompt(digits=f"{span} (24 bits)"),
                         top="DecimalChain") is None


def test_section_annotated_explicit_span_conflict_is_refused():
    text = prompt(6, "[8:4]") + "\n" + section_prompt("[7:3] (5 bits)")
    assert counter.synth(text, top="DecimalChain") is None


@pytest.mark.parametrize("header", [False, True])
@pytest.mark.parametrize("description", [
    ": 5-bit output, computed from digits[8:4]",
    "5-bit output, computed from digits[8:4]",
    "(5 bits): output computed from digits[8:4]",
])
def test_section_description_slice_does_not_declare_port_bounds(header, description):
    text = section_prompt(description, "[23:0]")
    if header:
        text = prompt(6, "[4:0]") + "\n" + text
    rtl = counter.synth(text, top="DecimalChain")
    assert rtl is not None and "output [4:0] upper_tick" in rtl


@pytest.mark.parametrize("declaration", [
    "**upper_tick [8:4]** (5 bits): output computed from digits[4:0]",
    "`output [8:4] upper_tick` (5 bits): enable output",
    "`upper_tick([8:4])` (5 bits): enable output",
])
def test_section_span_stays_adjacent_to_declared_name(declaration):
    text = section_prompt().replace("`upper_tick` [8:4] (5 bits)", declaration)
    rtl = counter.synth(text, top="DecimalChain")
    assert rtl is not None and "output [8:4] upper_tick" in rtl
