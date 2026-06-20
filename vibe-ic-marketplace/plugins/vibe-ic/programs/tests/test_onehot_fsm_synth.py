"""v1.1.38 §4.2 absorption — deterministic one-hot FSM next-state/output synth.

The "derive next-state logic by inspection assuming one-hot encoding" prompts give
the encoding (state->bit), the transition table, and the asserted outputs — all in
the prompt. The next-state equation is mechanical (OR of incoming edges). The synth
absorbs it as a PROGRAM (was per-round single-shot variance).

§4.05 no-leak: FIRES only with an explicit one-hot encoding tuple + parseable
transition table; SKIPs otherwise (preserves original-case testbench-facing port
names like B3_next).
"""
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import onehot_fsm_synth as O  # noqa: E402

_FSM = """
Implement a module named TopModule.
 - input  d
 - input  ack
 - input  state (3 bits)
 - output A_next
 - output B_next
 - output go

Implement the Moore state machine using a one-hot encoding.

state   (output)   --input--> next state
  A     ()         --d=0--> A
  A     ()         --d=1--> B
  B     (go=1)     --ack=0--> B
  B     (go=1)     --ack=1--> A

one-hot encoding: (A, B, C) = (3'b001, 3'b010, 3'b100)
"""


def test_onehot_fires_and_is_correct():
    rtl = O.synth(_FSM, "TopModule")
    assert rtl is not None
    # into-A edges: A&~d, B&ack ; into-B edges: A&d, B&~ack ; go = state[B]
    assert "assign A_next = state[0] & ~d | state[1] & ack;" in rtl
    assert "assign B_next = state[0] & d | state[1] & ~ack;" in rtl
    assert "assign go = state[1];" in rtl


def test_onehot_preserves_port_case():
    rtl = O.synth(_FSM, "TopModule")
    # testbench-facing case preserved (not lowercased a_next/b_next)
    assert "output A_next" in rtl and "output B_next" in rtl
    assert "a_next" not in rtl and "b_next" not in rtl


def test_onehot_skip_without_encoding():
    p = _FSM.replace("one-hot encoding: (A, B, C) = (3'b001, 3'b010, 3'b100)", "")
    assert O.synth(p, "TopModule") is None


def test_onehot_skip_when_not_onehot():
    p = _FSM.replace("one-hot encoding", "binary encoding").replace(
        "using a one-hot encoding", "using a binary encoding")
    assert O.synth(p, "TopModule") is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
