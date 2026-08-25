#!/usr/bin/env python3
r"""Tests for prose_interface_bridge — the chain of prose-interface readers.

The capability this file exists for is REACH: three readers with the same
`bridge_prompt(text) -> str` contract, tried in order, so one import gets a
caller every form. The markdown-table reader had ZERO importers before the
chain; a test that only imported the module would have been green then too.

So each arm drives the WHOLE way through: prose in -> `bridge()` -> the shared
`port_parser.parse_ports`, asserting the ports that come out. That is the thing
the chain is for, and it goes red if any reader stops being reached.

Also pinned:
  * `which_bridged` attributes the text to the reader that actually claims it —
    the three forms must not collapse onto one reader;
  * prose no reader recognises comes back BYTE-IDENTICAL (a no-op bridge, which
    is what makes trying them in sequence safe by construction);
  * a reader that RAISES is skipped and the chain keeps going.
"""
import sys
from pathlib import Path

import pytest

_PROG = Path(__file__).resolve().parents[1]
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import port_parser as pp                 # noqa: E402
import prose_interface_bridge as B       # noqa: E402


# --- the three prose forms, one per reader in the chain --------------------- #

INDENTED_BULLETS = """Please act as a professional verilog designer.

Implement an 8-bit adder.

Input ports:
    a [7:0]: 8-bit first operand.
    b [7:0]: 8-bit second operand.
    cin: 1-bit carry in.
Output ports:
    sum [7:0]: 8-bit sum.
    cout: 1-bit carry out.
"""

MARKDOWN_SECTION = """Design a registering module.

### Inputs
- **`clk`** (1-bit): system clock.
- [7:0] data_in: An 8-bit input vector.

### Outputs
- **`data_out`** (8-bits, [7:0]): the registered output.
"""

SIGNAL_TABLE = """The block has the following interface.

| Signal   | Direction | Bit Width | Description        |
|----------|-----------|-----------|--------------------|
| clk      | Input     | 1         | system clock       |
| data_in  | Input     | [7:0]     | operand            |
| result   | Output    | [7:0]     | sum                |

Behaviour: result registers data_in.
"""

NO_INTERFACE = ("This prose states no interface at all. It is a paragraph of "
                "words about a design and names no ports.\n")

# (reader, prose, emitted bullet block, ports parse_ports must then read)
_FORMS = [
    ("indented_bullets", INDENTED_BULLETS,
     " - input a (8 bits)\n - input b (8 bits)\n - input cin\n"
     " - output sum (8 bits)\n - output cout\n\n",
     [("a", 8), ("b", 8), ("cin", 1)], [("sum", 8), ("cout", 1)]),
    ("markdown_table", MARKDOWN_SECTION,
     " - input clk\n - input data_in (8 bits)\n - output data_out (8 bits)\n\n",
     [("clk", 1), ("data_in", 8)], [("data_out", 8)]),
    ("signal_direction_table", SIGNAL_TABLE,
     " - input clk\n - input data_in (8 bits)\n - output result (8 bits)\n\n",
     [("clk", 1), ("data_in", 8)], [("result", 8)]),
]


@pytest.mark.parametrize("reader,text,block,ins,outs", _FORMS)
def test_every_form_is_bridged_to_a_block_the_shared_parser_reads(
        reader, text, block, ins, outs):
    """Each reader must PREPEND the equivalent bullet block, and that block must
    be what the shared parser then reads. Asserting the block itself (not only
    the parsed result) is what makes this bite for a form `parse_ports` can
    already read on its own: drop the reader from the chain and the block is
    gone."""
    bridged = B.bridge(text)
    assert bridged.startswith(block)
    assert pp.parse_ports(bridged) == (ins, outs)


@pytest.mark.parametrize("reader,text,_b,_i,_o", _FORMS)
def test_which_bridged_names_the_reader_that_claims_the_text(
        reader, text, _b, _i, _o):
    assert B.which_bridged(text) == reader


@pytest.mark.parametrize("text", [INDENTED_BULLETS, SIGNAL_TABLE])
def test_the_forms_the_shared_parser_cannot_read_on_its_own(text):
    """Two of the three forms are INVISIBLE to `port_parser` until bridged —
    which is the reach the chain exists to provide."""
    assert pp.parse_ports(text) == ([], [])
    assert pp.parse_ports(B.bridge(text)) != ([], [])


def test_the_original_prose_survives_the_bridge():
    """Consumers still read the body semantics out of the untouched prose; the
    bridge PREPENDS a port block, it does not rewrite the spec."""
    out = B.bridge(SIGNAL_TABLE)
    assert out.endswith(SIGNAL_TABLE)
    assert out != SIGNAL_TABLE


def test_unrecognised_prose_is_returned_unchanged():
    assert B.bridge(NO_INTERFACE) == NO_INTERFACE
    assert B.which_bridged(NO_INTERFACE) is None


def test_empty_text_is_a_no_op():
    assert B.bridge("") == ""
    assert B.bridge("   \n") == "   \n"


def test_a_raising_reader_does_not_break_the_chain(monkeypatch):
    """Each reader is independent; one blowing up must not cost the caller the
    others. Put an exploding reader FIRST and the table form must still bridge."""
    def _boom(_text):
        raise ValueError("reader exploded")

    monkeypatch.setattr(B, "BRIDGES", [("boom", _boom)] + list(B.BRIDGES))
    assert pp.parse_ports(B.bridge(SIGNAL_TABLE)) == (
        [("clk", 1), ("data_in", 8)], [("result", 8)])
    assert B.which_bridged(SIGNAL_TABLE) == "signal_direction_table"


def test_bridges_reports_the_readers_actually_in_the_chain():
    assert B.bridges() == [name for name, _fn in B.BRIDGES]
    assert B.bridges() == ["indented_bullets", "markdown_table",
                           "signal_direction_table"]
