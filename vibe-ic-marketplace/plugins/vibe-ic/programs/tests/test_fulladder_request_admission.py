import pytest

import arithmetic_synth as arithmetic
import port_parser
from test_explicit_fulladder_emission import request, assert_fulladder_composition


@pytest.mark.parametrize("style", ["but do not instantiate full adders",
    "and never instantiate full adders", "without using individual full adders",
    "without using a network of full adders", "but do not use multiple full adders"])
def test_negated_actions_keep_exact_ordinary_output(style):
    ordinary, _, _ = request(style="")
    prompt, _, _ = request(style=style)
    assert arithmetic.synth(prompt, "neutral_sum") == arithmetic.synth(ordinary, "neutral_sum")


@pytest.mark.parametrize("tail", ["Do not use full adders.",
    "Do not instantiate individual full adders.", "Never use a network of full adders."])
def test_later_negative_instruction_defeats_positive_clause(tail):
    prompt, _, _ = request()
    ordinary, _, _ = request(style="")
    assert arithmetic.synth(prompt + "\n" + tail, "neutral_sum") == arithmetic.synth(ordinary, "neutral_sum")


def test_unrelated_descriptive_mention_is_not_an_instruction():
    prompt, _, _ = request(style="")
    assert arithmetic.synth(prompt + "\nA different design uses a network of full adders.", "neutral_sum") == arithmetic.synth(prompt, "neutral_sum")


@pytest.mark.parametrize("bad", ["input", "output"])
def test_span_cardinality_conflict_refuses_before_emission(bad):
    prompt = ("Implement an unsigned five-bit adder using full adders. "
              "The output should include the carry bit.\n### Inputs:\n"
              "- `operand_u` [4:0] (5 bits)\n- `operand_v` [4:0] (5 bits)\n"
              "### Outputs:\n- `total` [5:0] (6 bits)\n")
    if bad == "input":
        prompt = prompt.replace("`operand_u` [4:0]", "`operand_u` [1:0]")
    else:
        prompt = prompt.replace("`total` [5:0]", "`total` [2:0]")
    assert port_parser.parse_ports(prompt) == ([('operand_u', 5), ('operand_v', 5)], [('total', 6)])
    assert arithmetic.synth(prompt, "neutral_sum") is None


@pytest.mark.parametrize("last_span,accepted", [("[4:0]", True), ("[8:4]", False), ("[0:4]", False)])
def test_repeated_endpoint_declarations_require_identical_spans(last_span, accepted):
    prompt = ("Implement an unsigned five-bit adder using full adders. "
              "The output should include the carry bit.\n- input [4:0] operand_u\n"
              "- input [4:0] operand_v\n- output [5:0] total\n"
              f"- input {last_span} operand_u\n")
    generated = arithmetic.synth(prompt, "neutral_sum")
    if accepted:
        assert_fulladder_composition(generated, 5, ("operand_u", "operand_v", "total"),
            {"operand_u": (4, 0), "operand_v": (4, 0), "total": (5, 0)})
    else:
        assert generated is None


def test_width_only_restatements_preserve_compatible_header_endpoints():
    spans = {"operand_u": (8, 4), "operand_v": (10, 14), "total": (20, 25)}
    prompt, _, _ = request(spans=spans)
    prompt += "\n- input operand_u (5 bits)\n- input operand_v (5 bits)\n- output total (6 bits)\n"
    assert port_parser.parse_ports(prompt) == ([('operand_u', 5), ('operand_v', 5)], [('total', 6)])
    generated = arithmetic.synth(prompt, "neutral_sum")
    assert_fulladder_composition(generated, 5, ("operand_u", "operand_v", "total"), spans)


@pytest.mark.parametrize("restatement", [
    "- input operand_u (5 bits)\n- input operand_v (5 bits)\n- output total (6 bits)",
    "- input operand_u (5 bits)\n- input operand_v (5 bits)\n- output total (6 bits)\n- input spare",
    "- input operand_u (5 bits)\n- output operand_v (5 bits)\n- output total (6 bits)",
])
def test_header_metadata_is_admitted_against_selected_port_tuples(restatement):
    prompt, _, _ = request()
    prompt = prompt.replace("[4:0] operand_u", "[3:0] operand_u") + "\n" + restatement
    assert arithmetic.synth(prompt, "neutral_sum") is None


@pytest.mark.parametrize("style", ["using a network of full adders", "using individual full adders",
    "using full adders without registers"])
def test_same_action_qualifiers_work_in_positive_requests(style):
    prompt, _, spans = request(style=style)
    assert_fulladder_composition(arithmetic.synth(prompt, "neutral_sum"), 5,
        ("operand_u", "operand_v", "total"), spans)
