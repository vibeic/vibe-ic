#!/usr/bin/env python3
"""vibe-ic#886 — two defects in `flow_gate_enforcement_audit` cancelled into a
clean PASS.

Measured on the shipped program AFTER #885 landed the clause-grammar walk: 150
gates in the flow definition, 129 of them AUDIT_ONLY, 127 with no declared
intent — and the audit exited 0 with `[PASS] no NEW enforcement contradiction`.

It could do that because the only failing shape was "a gate DECLARES blocking
and is wired AUDIT_ONLY", and no gate was in it. The other 113 AUDIT_ONLY gates
had declared nothing at all and were therefore exempt BY CONSTRUCTION: saying
nothing was the reliable way to stay clean, which is the exact inversion of
what a gate register is for.

The second defect hid inside the first. The declaration pattern was unanchored,
so it matched the token anywhere — including the sentence in the audit's OWN
docstring that DOCUMENTS the convention. The audit read that sentence as a
declaration about itself. It stayed invisible only because the orphan scan
globbed `*_check.py` and `*_disclosure.py` and so could not reach a
`*_audit.py`. Widening the glob alone made the program report ITSELF as an
orphan declaring blocking.

Every test here is paired: the failing shape AND the shape that must stay
clean, because "reports a finding" is trivially satisfiable by a program that
reports everything.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent




# The sentence from the audit's own docstring that documents the convention.
# It is prose ABOUT the declaration, not a declaration. Reproduced here so the
# regression is pinned to the real text, not a paraphrase of it.
_CONVENTION_PROSE = '''"""A gate program declares its own intent in its
docstring via
              `ENFORCEMENT: blocking` or `ENFORCEMENT: advisory`
and this file only DESCRIBES that convention.
"""
'''

_REAL_DECLARATION = '''"""A gate that means it.

ENFORCEMENT: blocking — and it says so at the start of its own line.
"""
'''




# ------------------------------------------------- (a) silence is not consent







# -------------------------------------- (b) prose about a rule is not the rule















# ------------------------------------------------------- (c) it must be run



# ------------------------- (d) the new class is DIFFERENT debt, recorded apart
#
# THE REFUTATION VECTOR. The first fix for #886 was correct about (a) and (b)
# and still had to be rejected: it appended the new `undeclared::` entries to
# `known`, the register whose documented contract is "gates that DECLARE an
# intent they are not wired for". That grew a SHRINK-ONLY register from 0 to 86
# in one commit and turned five previously-green tests red —
#
#     test_306_register_never_grows                    (register grew 0 -> 86)
#     test_306_shipped_tree_is_green_against_its_register
#     test_316_shipped_tree_passes_against_its_recorded_debt
#     test_316_the_recorded_debt_is_named_not_hidden    (kind not in the pair)
#     test_316_a_new_contradiction_fails                (failure wording merged)
#
# — two of them inside the file `ci_targeted_test_select.py` picks for this very
# change. Every test below fails on that shape and passes on this one, so the
# guard is the separation itself and not just the reporting.

_BASELINE = _PROGRAMS / "flow_gate_enforcement_baseline.json"


def test_the_undeclared_class_is_not_recorded_in_the_known_register():
    """`known` keeps its contract. An `undeclared::` entry there makes the
    register's own `_comment` false and is the precise shape that turned the
    two #316 guards red."""
    doc = json.loads(_BASELINE.read_text())
    assert [k for k in doc["known"] if k.startswith("undeclared::")] == [], (
        "the #886 class was appended to `known`, whose stated contract is "
        "gates that DECLARE an intent they are not wired for")
    for k in doc["known"]:
        assert k.partition("::")[0] in ("contradiction", "orphan"), k


def test_the_new_register_is_ratcheted_too():
    """A second register that nobody ratchets is a waiver list with extra
    steps. It carries its own recorded size, in its own key, so growth in one
    class can never be licensed by a reason given for the other."""
    doc = json.loads(_BASELINE.read_text())
    assert "undeclared_known" in doc, "the #886 register is not in the baseline"
    assert "undeclared_previous_size" in doc, (
        "`undeclared_known` has no recorded previous size, so nothing stops "
        "it growing")
    prev_u = doc["undeclared_previous_size"]
    assert prev_u is None or len(doc["undeclared_known"]) <= prev_u
    assert doc["undeclared_known"], (
        "the register is empty while the audit reports the class — that would "
        "mean the finding is not actually recorded anywhere")














# --------------------------------------------------------------------- helper

_COUNT = [0]




if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
