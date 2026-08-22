"""Protocol-controller datasheet (SPI master) — transition-prose FSM recall.

A third datasheet — an APB-mapped SPI master controller — exercises the L3/L4/L6
protocol path. It surfaced that a datasheet FSM stated purely as TRANSITION PROSE
with BACKTICK-quoted states ("In the `IDLE` state … transitions to `LOAD`; from
`LOAD` … moves to `SHIFT` …") was extracted as 0 states / 0 transitions, because:

  1. `<NAME> state` prose detection could not cross the backtick (`IDLE`-tick-space-
     "state"), so no structural state source was found; and
  2. the transition-implied-state seeding only ran in a `not order` fallback, so a
     state-shaped token ELSEWHERE in the multi-section doc (a register / mode
     table) made `order` non-empty and silently dropped the real FSM.

Fixes: backtick-aware prose state, transition source/dest seeding that runs
UNCONDITIONALLY, and a capitalization guard so a register bit-field value gloss
("1 = enabled", "0 = shift LSB first") never mints a phantom state.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROG = Path(__file__).resolve().parents[1]
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import spec_fsm_extract as F  # noqa: E402

_FSM_PROSE = (
    "The shift engine is a finite state machine:\n"
    "- In the `IDLE` state, when `EN` is set, the FSM transitions to `LOAD`.\n"
    "- From `LOAD`, on the next clock, it moves to `SHIFT`.\n"
    "- In `SHIFT`, after 8 bits it transitions to `DONE`.\n"
    "- From `DONE`, it asserts `irq` and returns to `IDLE`.\n")

# the FSM prose embedded in a multi-section doc whose register/mode tables carry
# state-shaped tokens + bit-field value glosses (the real-datasheet shape)
_FULL_DOC = (
    "## L4 Register Map\n"
    "| Offset | Name | Access | Width |\n"
    "| 0x00 | CTRL | RW | 32 |\n"
    "| 0x04 | STATUS | RO | 32 |\n"
    "### CTRL bit-fields\n"
    "| 0 | EN | Module enable (1 = enabled) |\n"
    "| 3 | LSBFIRST | 1 = shift LSB first, 0 = MSB first |\n\n"
    + _FSM_PROSE)


def _states(text):
    return {d["state"] for d in F.extract(text) if d["kind"] == "fsm_state"}


def _transitions(text):
    return {(d["state"], d["next_state"]) for d in F.extract(text)
            if d["kind"] == "fsm_transition"}


def test_backtick_transition_prose_fsm_isolated():
    assert {"IDLE", "LOAD", "SHIFT", "DONE"} <= _states(_FSM_PROSE)
    tr = _transitions(_FSM_PROSE)
    assert ("IDLE", "LOAD") in tr and ("LOAD", "SHIFT") in tr and ("DONE", "IDLE") in tr


def test_fsm_survives_in_multisection_doc():
    # a register/mode table elsewhere must NOT suppress the transition-prose FSM
    assert {"IDLE", "LOAD", "SHIFT", "DONE"} <= _states(_FULL_DOC)


def test_no_phantom_state_from_bitfield_value_gloss():
    # "1 = enabled" / "0 = shift LSB first" are bit-field glosses, not states
    st = _states(_FULL_DOC)
    assert "enabled" not in st and "shift_LSB_first" not in st
    assert all(s.isupper() or s[:1].isupper() for s in st)


def test_capitalized_encoding_state_still_works():
    # a real lettered state encoding is unaffected
    st = _states("States: 00 = Idle, 01 = Transmit, 10 = Done. "
                 "From Idle it moves to Transmit.")
    assert {"Idle", "Transmit"} <= st


def test_no_fsm_in_plain_prose():
    assert F.extract("The module adds two numbers and outputs the sum.") == []
    assert F.extract("The counter resets to 0 on reset and increments each clock.") == []
