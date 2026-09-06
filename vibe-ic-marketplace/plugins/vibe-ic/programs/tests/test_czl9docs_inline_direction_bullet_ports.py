#!/usr/bin/env python3
"""#czl9docs — a bullet that carries its OWN direction keyword IS a port.

Measured on live main 73728b9f: a docs-mode Phase-1 over an input whose first
lines are

    - input  clk
    - output cmd_out (4 bits)

emitted L1.pin_table = [] and L9.ports = [], and asserted
`no_pin_table_in_input` — a positive claim about an input that declares five
ports. Both pre-existing bullet extractors are HEADING-anchored
(`_l1_bullet_port_extract` needs a `Ports:` line, `_l1_directional_prose_port_
extract` needs an `Inputs:` line), so a plain-language description that lists
its pins one per bullet under no heading matched neither.

Pinned in BOTH directions: the declaration shapes must extract, and the
documentation-prose shapes that begin with the same word must NOT.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import phase1_doc_one_shot_runner as R  # noqa: E402

def _F(text):
    # Resolved lazily so a build WITHOUT the extractor fails as a readable
    # per-test red ("the extractor is absent") rather than a collection error.
    fn = getattr(R, "_l1_inline_direction_bullet_port_extract", None)
    assert fn is not None, ("_l1_inline_direction_bullet_port_extract is "
                            "absent — the inline-direction bullet grammar is "
                            "not extracted at all")
    return fn(text)


def _names(text):
    return [(e["name"], e["mode"]) for e in _F(text)]


def test_no_heading_needed_the_bullet_states_its_own_direction():
    text = ("Implement a framed serial receiver.\n"
            "\n"
            " - input  clk\n"
            " - input  rst\n"
            " - input  rx\n"
            " - output cmd_out (4 bits)\n"
            " - output frame_done\n")
    assert _names(text) == [("clk", "input"), ("rst", "input"),
                            ("rx", "input"), ("cmd_out", "output"),
                            ("frame_done", "output")]


def test_width_is_read_from_a_bracket_and_from_a_bit_parenthetical():
    got = {e["name"]: e["width"] for e in _F(
        "- input [7:0] data_in\n"
        "- output cmd_out (4 bits)\n"
        "- output data_out[3:0]\n"
        "- input strobe\n")}
    assert got == {"data_in": "8", "cmd_out": "4",
                   "data_out": "4", "strobe": None}


def test_a_separated_description_is_kept_and_a_width_parenthetical_is_not():
    got = {e["name"]: e["description"] for e in _F(
        "- inout  sda : the bidirectional data pad\n"
        "- output cmd_out (4 bits)\n"
        "- output q — the decoded result\n")}
    assert got == {"sda": "the bidirectional data pad",
                   "cmd_out": None,
                   "q": "the decoded result"}


def test_backticked_forms_extract():
    assert _names("- `input` `scl`\n- `output` `sda`\n") == [
        ("scl", "input"), ("sda", "output")]


def test_documentation_prose_beginning_with_the_same_word_is_not_a_port():
    # The discriminator: after the identifier the bullet runs on into bare
    # prose words, so it is a SENTENCE. A regex that only keyed on the leading
    # direction word would harvest every one of these as a phantom pin.
    prose = ("- Input validation is performed by the host before sending.\n"
             "- Output format follows the vendor convention above.\n"
             "- Input requirements are listed in the table.\n"
             "- output the result to the console when done\n"
             "- Inputs: three\n"
             "- inout\n")
    assert _F(prose) == []


def test_a_stop_word_identifier_never_becomes_a_port():
    assert _F("- input ports\n- output signals\n- inout width\n") == []
