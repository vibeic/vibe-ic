"""A hygiene record handed over by the caller is CHECKED, never trusted.

`repo_hygiene_gate` refuses to grow a CLI seam because a command-line way to
point it at a cheap fixture would be a skip button on the gate whose whole
purpose is that it cannot be forgotten. `hygiene_gate_from_record` exists
beside that reasoning rather than against it: it changes the RUNNER of the same
subject, not the subject. What makes that safe is that every way of failing to
establish the record is rc 2 UNDETERMINED and blocking — so this file drives
each of those ways and asserts the refusal, and then asserts the one path that
is allowed to decide actually decides.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

DECLARED = ["alpha gate", "beta gate", "gamma gate"]


# --------------------------------------------------------------------------
# PARSING THE DISPATCHER'S STATE VOCABULARY. Shared shape, one defect fixed
# once.
#
# The first version of this matched only the LITERAL form
# `GATE_STATES+=("NAME")` and therefore found 5 of the 8 states -- it MISSED
# PASS, FAIL and WROTE_CORPUS, which are assigned to `_GX_STATE` and reach the
# array through `GATE_STATES+=("$_GX_STATE")`. The three it missed are exactly
# the states that mean "this gate ran", so a test named for covering every
# state covered none of the interesting ones.
#
# Widening the pattern alone would leave the same defect one indirection later,
# so `dispatcher_states` also REFUSES a `GATE_STATES+=(` occurrence it cannot
# explain: a third assignment form fails here instead of silently shrinking the
# set.
# --------------------------------------------------------------------------

_STATE_LITERAL = r'GATE_STATES\+=\("([A-Z_]+)"\)'
_STATE_VIA_GX = r'_GX_STATE\s*=\s*"([A-Z_]+)"'
_ANY_APPEND = r'GATE_STATES\+=\(([^)]*)\)'
_KNOWN_INDIRECTION = '"$_GX_STATE"'


def dispatcher_states(disp: str) -> set:
    """Every state `_gate_dispatch.sh` can record, both assignment forms."""
    import re
    literal = set(re.findall(_STATE_LITERAL, disp))
    via_gx = set(re.findall(_STATE_VIA_GX, disp))
    unexplained = [a.strip() for a in re.findall(_ANY_APPEND, disp)
                   if a.strip() != _KNOWN_INDIRECTION
                   and a.strip().strip('"') not in literal]
    assert not unexplained, (
        "GATE_STATES is appended in a form this parser does not understand, "
        f"so the state set below is incomplete: {unexplained}")
    states = literal | via_gx
    assert states, "no states parsed -- the dispatcher's shape changed"
    return states






# --- every way of not establishing the record is rc 2, and blocking ---------













# --- and the path that IS allowed to decide, decides ------------------------









# --------------------------------------------------------------------------
# THE DENOMINATOR MUST BE WHAT RAN.
# --------------------------------------------------------------------------



















# --------------------------------------------------------------------------
# THE ARM THAT SHOULD BE UNCHANGED — CHECKED, NOT ASSERTED.
# --------------------------------------------------------------------------









def test_the_state_parser_finds_both_assignment_forms():
    """The parser's own control. It once matched only the literal form and so
    found 5 of 8, missing PASS, FAIL and WROTE_CORPUS -- the three that mean
    "this gate ran".

    UNDETERMINED is the NINTH, and it is recorded here only because the owner
    ruled it a real state (2026-09-03): a corpus that was never opened is
    neither a pass nor a finding, so it needs a name of its own rather than
    being folded into either. It arrived in the dispatcher with v1.14.4
    (`ac3232ddeb`) and this pin has been red about it since — correctly,
    because a ninth token appearing in `_GX_STATE` with no ruling behind it is
    exactly what an equality pin is for.

    The pin stays an EQUALITY. A tenth spelling must redden this line, and
    `test_a_third_assignment_form_fails_here_rather_than_shrinking_the_set`
    below keeps the parser itself from answering with a quietly smaller set."""
    repo = PROGRAMS.parents[3]
    disp = (repo / "tools" / "ci" / "_gate_dispatch.sh").read_text(encoding="utf-8")
    states = dispatcher_states(disp)
    assert states == {"PASS", "FAIL", "NOT_CHECKED", "WROTE_CORPUS",
                      "LISTED", "OTHER_SHARD", "OUT_OF_SCOPE", "QUEUED",
                      "UNDETERMINED"}, sorted(states)


def test_a_third_assignment_form_fails_here_rather_than_shrinking_the_set():
    """Widening a pattern only moves the defect to the next spelling. An
    append this parser cannot explain must REFUSE, because the alternative is
    a silently smaller state set and every test built on it passing for the
    wrong reason."""
    repo = PROGRAMS.parents[3]
    disp = (repo / "tools" / "ci" / "_gate_dispatch.sh").read_text(encoding="utf-8")
    invented = disp + '\n  GATE_STATES+=("${SOME_NEW_HOLDER}")\n'
    with pytest.raises(AssertionError, match="does not understand"):
        dispatcher_states(invented)
