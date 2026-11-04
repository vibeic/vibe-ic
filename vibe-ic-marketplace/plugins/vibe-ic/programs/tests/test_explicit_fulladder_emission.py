"""Neutral explicit full-adder composition through the existing public emitter."""
import re

import pytest

import arithmetic_synth as arithmetic
import module_port_audit as ports


def request(width=5, names=("operand_u", "operand_v", "total"), *, style="using full adders",
            spans=None):
    a, b, result = names
    spans = spans or {a: (width - 1, 0), b: (width - 1, 0), result: (width, 0)}
    def declaration(direction, name):
        hi, lo = spans[name]
        return f"{direction} [{hi}:{lo}] {name}"
    header = "module neutral_sum(" + ", ".join([
        declaration("input", a), declaration("input", b), declaration("output", result)]) + ");"
    prompt = (f"Implement an unsigned {width}-bit adder {style}. "
              "The output should include the carry bit.\n" + header)
    return prompt, header, spans


def assignments(rtl):
    return {re.sub(r"\s+", "", target): re.sub(r"\s+", "", expr)
            for target, expr in re.findall(r"\bassign\s+([^=;]+)=([^;]+);", rtl)}


def bit_name(name, spans, offset):
    hi, lo = spans[name]
    index = lo + offset * (1 if hi >= lo else -1)
    return f"{name}[{index}]"


def assert_fulladder_composition(rtl, width, names, spans):
    a, b, result = names
    equations = assignments(rtl)
    # A vector addition is not an explicit logical full-adder composition.
    vector_additions = sum(expression.count("+") for expression in equations.values())
    assert vector_additions == 0, equations
    first_sum = equations[bit_name(result, spans, 0)]
    terms = first_sum.split("^")
    assert len(terms) == 3, first_sum
    incoming = terms[2]
    assert equations[incoming] == "1'b0", equations
    for offset in range(width):
        left = bit_name(a, spans, offset)
        right = bit_name(b, spans, offset)
        target = bit_name(result, spans, offset)
        assert equations[target] == f"{left}^{right}^{incoming}", equations
        carry_expression = f"({left}&{right})|(({left}^{right})&{incoming})"
        successors = [target for target, expression in equations.items()
                      if expression == carry_expression]
        assert len(successors) == 1, equations
        incoming = successors[0]
    assert equations[bit_name(result, spans, width)] == incoming, equations


@pytest.mark.parametrize("width,names,style", [
    (2, ("x", "y", "s"), "with full adders"),
    (5, ("word_left", "word_right", "wide_total"), "using full adders"),
    (9, ("first_word", "next_word", "result_bits"), "built from full-adder cells"),
    (1, ("low_a", "low_b", "wide_bit"), "using full adders"),
    (3, ("foo", "bar", "extended"), "using\nfull adders"),
    (6, ("operand_one", "operand_two", "answer"), "using full adders without registers"),
])
def test_explicit_request_emits_logical_fulladder_chain(width, names, style):
    prompt, _, spans = request(width, names, style=style)
    rtl = arithmetic.synth(prompt, "neutral_sum")
    assert rtl is not None
    assert_fulladder_composition(rtl, width, names, spans)


@pytest.mark.parametrize("spans", [
    {"operand_u": (8, 4), "operand_v": (15, 11), "total": (12, 7)},
    {"operand_u": (2, 6), "operand_v": (10, 14), "total": (20, 25)},
    {"operand_u": (8, 4), "operand_v": (10, 14), "total": (20, 25)},
])
def test_explicit_style_preserves_declared_packed_spans(spans):
    prompt, _, _ = request(spans=spans)
    rtl = arithmetic.synth(prompt, "neutral_sum")
    module, = ports.parse_modules(rtl, "<generated>")
    actual = {name: re.sub(r"\s+", "", declaration.width_expr)
              for name, declaration in module.ports.items()}
    for name, (hi, lo) in spans.items():
        assert actual[name] == f"[{hi}:{lo}]", rtl
    assert_fulladder_composition(rtl, 5, ("operand_u", "operand_v", "total"), spans)


def test_internal_carry_name_cannot_replace_or_alias_a_public_operand():
    names = ("_vibeic_carry", "second", "answer")
    prompt, _, spans = request(3, names)
    rtl = arithmetic.synth(prompt, "neutral_sum")
    assert_fulladder_composition(rtl, 3, names, spans)
    module, = ports.parse_modules(rtl, "<generated>")
    assert set(module.ports) == set(names)


def test_whole_prompt_followup_can_explicitly_request_full_adders():
    prompt, _, spans = request(style="")
    prompt += "\nConstruct the implementation from full adders.\n"
    rtl = arithmetic.synth(prompt, "neutral_sum")
    assert_fulladder_composition(rtl, 5, ("operand_u", "operand_v", "total"), spans)


@pytest.mark.parametrize("style", ["", "using ordinary arithmetic",
    "without full adders", "but do not use full adders", "and never use full adders"])
def test_no_positive_style_request_keeps_ordinary_arithmetic_emission(style):
    prompt, _, _ = request(style=style)
    rtl = arithmetic.synth(prompt, "neutral_sum")
    assert assignments(rtl) == {"total": "operand_u+operand_v"}, rtl


@pytest.mark.parametrize("change", ["width_mismatch", "missing_carry_bit", "clock",
    "extra_output", "parameterized", "non_ansi"])
def test_existing_unsupported_interface_or_clock_shape_stays_unsupported(change):
    prompt, _, _ = request()
    if change == "width_mismatch":
        prompt = prompt.replace("[4:0] operand_v", "[3:0] operand_v")
    elif change == "missing_carry_bit":
        prompt = prompt.replace("[5:0] total", "[4:0] total")
    elif change == "clock":
        prompt = prompt.replace("module neutral_sum(", "module neutral_sum(input clk, ")
    elif change == "extra_output":
        prompt = prompt.replace("output [5:0] total", "output flag, output [5:0] total")
    elif change == "parameterized":
        prompt = prompt.replace("[4:0]", "[WIDTH-1:0]").replace("[5:0]", "[WIDTH:0]")
    else:
        prompt = prompt[:prompt.index("module")] + "module neutral_sum(operand_u, operand_v, total);"
    assert arithmetic.synth(prompt, "neutral_sum") is None


def test_bullet_interface_uses_existing_width_contract():
    prompt = ("Implement a five-bit unsigned adder using full adders. "
              "The output should include the carry bit.\n"
              "- input [4:0] operand_u\n- input [4:0] operand_v\n- output [5:0] total\n")
    rtl = arithmetic.synth(prompt, "neutral_sum")
    spans = {"operand_u": (4, 0), "operand_v": (4, 0), "total": (5, 0)}
    assert_fulladder_composition(rtl, 5, ("operand_u", "operand_v", "total"), spans)
