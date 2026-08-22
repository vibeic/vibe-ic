"""test_mealy_sequence_synth.py — the prompt predicates this solver routes on.

`mealy_sequence_synth` had no test file. This one covers `_is_moore`, which
decides whether a prompt is handed to the Moore solver instead of this one --
so it does not extract a value, it routes the whole job, and reading it wrong
synthesises the wrong machine.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ── polarity on a PREDICATE, not a value (#712) ─────────────────────────────
#
# `_is_moore` decides whether this solver hands the prompt to the Moore solver.
# A prompt that explicitly refuses Moore was handed over anyway, so the wrong
# machine was synthesised from a document that says so plainly. No widening of a
# write-shape census would ever reach a predicate; the harm is the same.

def _moore(prompt):
    import mealy_sequence_synth as M
    return M._is_moore(prompt)


def test_a_prompt_that_refuses_Moore_is_not_read_as_Moore():
    assert _moore("The detector is not a Moore machine; it is Mealy.") is False


def test_a_denial_does_not_end_the_search():
    assert _moore("It is not a Moore machine.\nActually it is a Moore FSM.") is True


def test_a_prompt_that_names_itself_Moore_still_is():
    """The control arm: returning False always would pass the rest."""
    assert _moore("The detector is a Moore machine.") is True
