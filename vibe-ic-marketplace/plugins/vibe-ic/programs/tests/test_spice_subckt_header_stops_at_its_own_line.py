#!/usr/bin/env python3
"""A `.subckt` header ends at its own line — the parser swallowed the BODY.

MEASURED. The port character class carried `\\s`, which matches a newline, and
under `re.MULTILINE` the `$` anchor matches at ANY line end — so the greedy
class ran the header past its own line and absorbed everything up to the last
line end it could reach. On a three-port cell with one device in it:

    .subckt blk a b c / R1 a b 1k / .ends blk
        -> ports ['a','b','c','R1','a','b','1k','.ends','blk']

and on an interface-only declaration the ports came back as
`['a','b','c','.ends','blk']`. Only a COMMENT line between header and body
stopped it, so the defect was invisible on any netlist that happens to carry
one — and every consumer of `L9.submodules[].ports` downstream was reading
device names and literals as pins.

chip/PDK-AGNOSTIC: pure SPICE structural grammar.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import phase1_doc_one_shot_runner as P  # noqa: E402


def _ports(text: str, name: str = "blk"):
    m = P._v1_6_350_parse_spice_metadata(text)
    for sc in m["subckts"]:
        if sc["name"] == name:
            return sc["ports"]
    return None


def test_a_device_in_the_body_is_not_a_port():
    assert _ports(".subckt blk a b c\nR1 a b 1k\n.ends blk\n") == ["a", "b", "c"]


def test_an_interface_only_declaration_stops_at_ends():
    assert _ports(".subckt blk a b c\n.ends blk\n") == ["a", "b", "c"]


def test_a_blank_line_is_not_what_terminates_it():
    assert _ports(".subckt blk a b c\n\n.ends blk\n") == ["a", "b", "c"]


def test_a_comment_line_still_works_it_just_is_not_required():
    assert _ports(".subckt blk a b c\n* body\n.ends blk\n") == ["a", "b", "c"]


def test_continuation_rows_are_still_joined():
    """The `+` continuation join REMOVES the newline, so a folded pin list is
    one physical line by the time the header regex scans — the fix above must
    not undo it."""
    assert _ports(".subckt blk a b c\n+ d e\n.ends blk\n") == [
        "a", "b", "c", "d", "e"]


def test_alias_and_split_net_port_forms_survive():
    got = _ports(".SUBCKT top A|B C$1 D\n.ends\n", "top")
    assert got == ["A", "C_split1", "D"]


def test_a_multi_subckt_file_keeps_each_headers_own_ports():
    text = (".subckt one a b\nR1 a b 1k\n.ends one\n"
            ".subckt two c d e\nR2 c d 1k\n.ends two\n")
    assert _ports(text, "one") == ["a", "b"]
    assert _ports(text, "two") == ["c", "d", "e"]
