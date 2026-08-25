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


# --- a reader may ADD ports and may not SUBTRACT them ----------------------- #
# The chain's claim was "each reader is a no-op on text it does not recognise,
# so trying them in sequence is safe by construction". It is not: a reader can
# recognise a text PARTIALLY, and because `parse_ports` documents "bullet form
# wins", the block it prepends REPLACES what the prose already said instead of
# adding to it. Both fixtures below are the same shape as the CVDP records that
# measured it; both key on STRUCTURE, never on a design name.

#: A reader reads ONE of this spec's four ports. The other three are stated in a
#: form it is right to decline — a range AFTER the name, and a width carried in a
#: group header — but `parse_ports` reads all four out of the prose unaided.
PARTIALLY_READ = """Design the module named `ctrl`.

### Inputs:
- `i_fb [5:0]`: the feedback word.

### Outputs:

**Heating Control (1-bit each)**
- `o_heat_hi`
- `o_heat_lo`

**State (3-bit)**
- `o_state [2:0]`
"""

#: The MIRROR case, and the reason the cost check cannot simply defend every name
#: the raw parse produced. `port_parser`'s bullet reader takes the first word of a
#: prose bullet as a port name, so it reads a port called `Enables` here. The
#: markdown reader declines to, because the word is not a delimited token — and
#: declining to invent a port must not cost a reader the text.
FABRICATED_BY_THE_RAW_PARSE = """Design a registering module.

### Inputs
- **`clk`** (1-bit): system clock.
- **`data_in`** (8-bits, [7:0]): the operand.
- Enables the block while high.

### Outputs
- **`data_out`** (8-bits, [7:0]): the registered result.
"""


def test_a_reader_that_would_delete_a_delimited_port_does_not_claim_the_text():
    """RED before the cost check: `o_heat_hi` and `o_heat_lo` vanished."""
    whole = pp.parse_ports(PARTIALLY_READ)
    assert whole == ([("i_fb", 6)],
                     [("o_heat_hi", 1), ("o_heat_lo", 1), ("o_state", 3)])
    # the reader really does recognise this text, and really does read less
    import prose_interface_bridge_md as md
    assert pp.parse_ports(md.bridge_prompt(PARTIALLY_READ)) == (
        [("i_fb", 6)], [("o_state", 3)])
    # ...so the chain declines it and the caller keeps the reading it had
    assert B.bridge(PARTIALLY_READ) == PARTIALLY_READ
    assert B.which_bridged(PARTIALLY_READ) is None
    assert pp.parse_ports(B.bridge(PARTIALLY_READ)) == whole


def test_declining_to_invent_a_port_does_not_cost_a_reader_the_text():
    """The cost check defends what the PROSE DELIMITS, not whatever the raw
    bullet reader produced — otherwise it would defend the fabrications too and
    refuse the better reader for dropping them."""
    raw_ins, _raw_outs = pp.parse_ports(FABRICATED_BY_THE_RAW_PARSE)
    assert ("Enables", 1) in raw_ins, "fixture no longer exercises the fabrication"
    assert "Enables" not in B._delimited_names(FABRICATED_BY_THE_RAW_PARSE)
    assert B.which_bridged(FABRICATED_BY_THE_RAW_PARSE) == "markdown_table"
    assert pp.parse_ports(B.bridge(FABRICATED_BY_THE_RAW_PARSE)) == (
        [("clk", 1), ("data_in", 8)], [("data_out", 8)])


#: A spec that states its ports in a Verilog module header and backticks only ONE
#: of them in the prose beneath. `parse_ports` reads all three via its header
#: reader; a bridge that prepended bullets would replace them wholesale.
MODULE_HEADER_ONLY = """Implement the module below.

module TopModule (
    input  wire [7:0] a,
    input  wire       clk,
    output wire [7:0] y
);

It adds one to `a` every clock.
"""


def test_a_header_declared_port_is_defended_even_when_the_prose_never_quotes_it():
    """PINS A COUPLING that would otherwise weaken the guard in silence.

    `_delimited_names` asks `port_parser._header_ports` for the ports a Verilog
    module header declares, because the header delimits them just as a backtick
    does — and only `clk`/`y` here have no backtick anywhere in the prose. That
    call reaches for a PRIVATE helper. If it is renamed, `_delimited_names`
    quietly returns a smaller set, the cost check defends less, and a lossy
    reader starts slipping through with nothing going red. This test is what
    makes that rename loud, and it is the reason the reach is acceptable at all:
    the alternative was re-implementing the header parse here, where it could
    drift from the reader whose answer it is meant to mirror."""
    assert hasattr(pp, "_header_ports"), (
        "port_parser._header_ports is gone; prose_interface_bridge._delimited_names "
        "reads it to defend header-declared ports and now defends none of them")
    assert pp.parse_ports(MODULE_HEADER_ONLY) == (
        [("a", 8), ("clk", 1)], [("y", 8)])
    assert {"a", "clk", "y"} <= B._delimited_names(MODULE_HEADER_ONLY)


def test_bridges_reports_the_readers_actually_in_the_chain():
    assert B.bridges() == [name for name, _fn in B.BRIDGES]
    assert B.bridges() == ["indented_bullets", "markdown_table",
                           "signal_direction_table"]
