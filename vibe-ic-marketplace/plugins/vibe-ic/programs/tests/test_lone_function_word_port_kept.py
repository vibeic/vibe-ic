"""v1.1.34 clean-room (VerilogEval Prob145_circuit8) — a lone single-letter
function-word port (`- input a`, the whole bullet) is a genuine 1-bit port under
the "all ports are one bit unless otherwise specified" convention, NOT a
conjunction scraped from a prose sentence.

The ORGANIC #770 function-word guard dropped `- input a` (no `(N bits)` width
anchor) to catch `- Input and output signals adhere to …`. That over-fired on a
real lone single-letter port. The fix restricts the drop to a NON-EMPTY tail (the
SENTENCE shape), rescuing the bare lone-token port.

§4.05 no-leak: every #770/#785 prose bullet still carries a descriptive tail, so
each is still dropped; only the bare lone-token port is rescued.
"""
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import _specrtl_common as S  # noqa: E402


# ── positive: a lone function-word port (empty tail) is KEPT ──────────────────
@pytest.mark.parametrize("name", ["a", "an", "the", "or"])
def test_lone_function_word_port_with_empty_tail_is_kept(name):
    assert not S._nl_port_is_prose(name, "", has_width=False), \
        f"lone `- input {name}` (empty tail) must be a port, not prose"


def test_prob145_style_block_parses_a_and_q():
    txt = (
        "Interface:\n"
        " - input  clock\n"
        " - input  a\n"
        " - output p\n"
        " - output q\n")
    names = {p.name for p in S._parse_nl_ports(txt)}
    assert {"clock", "a", "p", "q"} <= names, names


# ── §4.05 NO-LEAK: a function word with a prose TAIL is still DROPPED ──────────
@pytest.mark.parametrize("name,tail", [
    ("and", "output AXI Stream signals adhere to the protocol"),  # #770
    ("or", "the result is forwarded to the next stage"),
    ("the", "register holds the accumulated value"),
    ("a", "data stream split into byte pairs"),                   # #785-shape
])
def test_function_word_with_prose_tail_still_dropped(name, tail):
    assert S._nl_port_is_prose(name, tail, has_width=False), \
        f"`- Input {name} {tail}` is prose and must stay dropped (no leak)"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
