import pytest

import arithmetic_synth as arithmetic
from test_explicit_fulladder_emission import request, assert_fulladder_composition


@pytest.mark.parametrize("style", ["not built from full-adder cells", "never built from full-adder cells"])
def test_attached_composition_denial_is_ordinary(style):
    prompt, _, _ = request(style=style)
    ordinary, _, _ = request(style="")
    assert arithmetic.synth(prompt, "neutral_sum") == arithmetic.synth(ordinary, "neutral_sum")


@pytest.mark.parametrize("statement", [
    "Do not construct the implementation from full adders.",
    "Never build the adder using full adders.",
    "A different design was built from full-adder cells.",
    "Another implementation was constructed using full adders.",
])
def test_governing_denial_or_past_description_cannot_activate_style(statement):
    prompt, _, _ = request(style="")
    assert arithmetic.synth(prompt + "\n" + statement, "neutral_sum") == arithmetic.synth(prompt, "neutral_sum")


@pytest.mark.parametrize("statement", [
    "Construct the implementation from full adders.",
    "Build the adder using full adders.",
    "Please construct\nthe implementation from full\nadders.",
    "Do not add registers. Construct the implementation from full adders.",
    "Construct the implementation from full adders. Never add registers.",
    "Use\nfull adders.",
])
def test_current_request_binds_style_across_wraps_and_separate_statements(statement):
    prompt, _, spans = request(style="")
    rtl = arithmetic.synth(prompt + "\n" + statement, "neutral_sum")
    assert_fulladder_composition(rtl, 5, ("operand_u", "operand_v", "total"), spans)


@pytest.mark.parametrize("style", ["built from full-adder cells", "using full\nadders", "using full adders without registers"])
def test_qualified_attached_composition_keeps_existing_chain(style):
    prompt, _, spans = request(style=style)
    assert_fulladder_composition(arithmetic.synth(prompt, "neutral_sum"), 5,
        ("operand_u", "operand_v", "total"), spans)


def test_mixed_negated_constraint_and_composition_is_explicitly_unqualified():
    prompt, _, _ = request(style="not using registers, but using full adders")
    assert arithmetic.synth(prompt, "neutral_sum") is None


def test_same_statement_later_composition_denial_is_not_ignored():
    prompt, _, _ = request(style="using full adders but do not build it from full adders")
    ordinary, _, _ = request(style="")
    assert arithmetic.synth(prompt, "neutral_sum") == arithmetic.synth(ordinary, "neutral_sum")


def test_same_statement_opposed_directions_are_unqualified():
    prompt, _, _ = request(style="not built from full adders but using full adders")
    assert arithmetic.synth(prompt, "neutral_sum") is None


def test_repeated_positive_composition_in_one_statement_stays_valid():
    prompt, _, spans = request(style="using full adders and built from full adders")
    assert_fulladder_composition(arithmetic.synth(prompt, "neutral_sum"), 5,
        ("operand_u", "operand_v", "total"), spans)


@pytest.mark.parametrize("style", [
    "without registers using full adders",
    ", unlike a previous design that was built from full-adder cells",
    "and document why the previous design used full adders",
])
def test_unqualified_body_cannot_misbind_composition_or_polarity(style):
    prompt, _, _ = request(style=style)
    assert arithmetic.synth(prompt, "neutral_sum") is None
