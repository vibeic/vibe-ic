#!/usr/bin/env python3
"""R-0915-131 — the `instruction` coverage dimension arrives WITH its instrument.

THE MEASUREMENT this deck is written from (subservient x gf180mcuD, FRONT DOOR,
run1 on main 48bf6576b, lane icsub5, 2026-09-22), taken AFTER every declared
functional VECTOR had been given a real oracle:

    step4_functional_evidence FAIL: ... and every declared functional vector
    executed its own oracle, but 0 of 1 declared coverage goal(s) met their
    stated percentage. rv32i_40 [NOT_MEASURED] case 'rv32i_40': the stated
    scope names no coverage dimension this run measures (branch/line/toggle):
    '整套 RV32I 指令(40+ 條)單元測試'

The design's L7 plan states an acceptance percentage over its INSTRUCTION SET.
`bind_scope` was right to refuse it -- the flow held no instrument -- and the
gate was right to refuse NOT_MEASURED. What was missing was the instrument.

The rules this deck pins, in both directions:
  * a scope naming instructions BINDS, and one naming a dimension the flow
    still has no instrument for does NOT (negative arm);
  * the three pre-existing dimensions and their words are UNTOUCHED (pinned);
  * the instrument is DECLARATION-DERIVED: no declared goal binding to the
    dimension => it does not run and publishes nothing (never a name pattern);
  * only a case that EXECUTED AND PASSED contributes a tally;
  * a goal that binds with NO contributing tally stays NOT_MEASURED **with the
    reason** -- absent is not zero and not a pass;
  * a published tally gives a verdict by the NUMBER: PASS at/above the stated
    percentage, FAIL below it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parents[1]
if str(PROG) not in sys.path:
    sys.path.insert(0, str(PROG))

import l10_coverage_goal_classify as G            # noqa: E402

#: The design's own row, transcribed from its L7 verification plan.
GOAL_INSTRUCTION = {
    "name": "rv32i_40", "kind": "functional_vector",
    "stimulus": "整套 RV32I 指令(40+ 條)單元測試",
    "expected": "100% PASS(可用 RISC-V Compliance suite 或 SERV 內附 testbench)",
}
#: A goal over a dimension nothing measures — the NEGATIVE arm. It must stay
#: NOT_MEASURED by name however many dimensions are added.
GOAL_UNBINDABLE = {
    "name": "message_length", "kind": "coverage_goal",
    "coverage_scope": "1 byte / 55 bytes / 64 bytes / 1024 bytes",
    "expected": "100% PASS",
}


# ── 1. the vocabulary, both directions, with the old three pinned ─────────
def test_an_instruction_scope_binds_to_the_instruction_dimension():
    dim, why = G.bind_scope("整套 RV32I 指令(40+ 條)單元測試")
    assert dim == "instruction"
    assert "instruction dimension" in why


@pytest.mark.parametrize("scope", [
    "all RV32I instructions unit tested",
    "every opcode in the command table",
    "full ISA coverage",
    "each mnemonic exercised once",
])
def test_the_instruction_vocabulary_is_not_one_language_or_one_word(scope):
    assert G.bind_scope(scope)[0] == "instruction"


def test_a_scope_naming_no_measured_dimension_still_binds_to_nothing():
    """NEGATIVE ARM. Adding a dimension must not make unbindable scopes bind."""
    dim, why = G.bind_scope(GOAL_UNBINDABLE["coverage_scope"])
    assert dim is None
    assert "names no coverage dimension" in why
    assert "55 bytes" in why          # the scope is QUOTED, not summarised
    assert "instruction" in why       # and the new dimension is listed as tried


def test_the_three_pre_existing_dimensions_are_untouched():
    """PIN. R-0915-131 ADDS a dimension; it changes none of the others."""
    assert G.DIMENSION_WORDS["line"] == (
        "line", "lines", "statement", "statements", "code coverage")
    assert G.DIMENSION_WORDS["toggle"] == (
        "toggle", "toggles", "bit toggle", "signal toggle")
    assert G.DIMENSION_WORDS["branch"] == (
        "branch", "branches", "decision", "decisions", "condition",
        "conditions")
    assert G.bind_scope("line coverage over the whole datapath")[0] == "line"
    assert G.bind_scope("toggle coverage")[0] == "toggle"
    assert G.bind_scope("branch coverage")[0] == "branch"


def test_a_scope_naming_two_dimensions_still_refuses_rather_than_picking():
    dim, why = G.bind_scope("instruction and line coverage")
    assert dim is None and "2 dimensions" in why


# ── 2. the fusion: one instrument, one dimension ──────────────────────────


EMIT_FULL = ("[TB rv32i_40] INSTRUCTION COVERAGE 41/41 = 100%\n"
             "VIBEIC_FUNCTIONAL_COVERAGE dimension=instruction "
             "covered=41 total=41\n[TB rv32i_40] PASS\n")
EMIT_SHORT = ("VIBEIC_FUNCTIONAL_COVERAGE dimension=instruction "
              "covered=30 total=41\n")










# ── 3. the refusals — absent is not zero, and not a pass ──────────────────










# ── 4. fusing several tallies ─────────────────────────────────────────────
