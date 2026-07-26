#!/usr/bin/env python3
"""ORGANIC #409 — the refusal message and the branch chain must not drift.

#409 records a WITHDRAWN branch (never pushed) that added an acceptance
tuple `_PDK_NAMED_BRANCHES` ahead of `_detect_pdk`'s branch chain and
documented it as "one tuple so the gate and the branch chain cannot drift
apart". Measured there: nothing derived one from the other, a new
hand-written lane became unreachable dead code behind the gate, and the
refusal said "matches no named branch" about a name that DID match one.
Its tests read the same tuple as the gate, so 23/23 stayed green on the
drifted tree — both sides of a check reading the same side of a
duplication proves nothing.

MAIN DOES NOT HAVE THAT DEFECT, and these tests exist to keep it that way:
on main the refusal sits at the FALL-THROUGH of the branch chain, so
reaching it *is* the proof that no named branch matched — the message is
true by construction, not by bookkeeping. What these tests pin is the
construction itself, read from the OTHER side of any future duplication:
the AST of `_detect_pdk`, not a parallel constant.

#389 recurred three times because each fix added another named branch. The
next person to add one is exactly who these tests speak to.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))

_SRC = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()
_TREE = ast.parse(_SRC)
_FN = next(n for n in ast.walk(_TREE)
           if isinstance(n, ast.FunctionDef) and n.name == "_detect_pdk")


def _branch_literals():
    """Every `override == "<name>"` comparison inside `_detect_pdk` — the
    branch chain read from its own AST, never from a parallel list."""
    out = []
    for n in ast.walk(_FN):
        if (isinstance(n, ast.Compare) and isinstance(n.left, ast.Name)
                and n.left.id == "override" and len(n.ops) == 1
                and isinstance(n.ops[0], ast.Eq)
                and isinstance(n.comparators[0], ast.Constant)
                and isinstance(n.comparators[0].value, str)):
            out.append((n.lineno, n.comparators[0].value))
    return out


def _named_branch_refusal_lines():
    """Lines of raises whose message claims no named branch matched."""
    out = []
    for n in ast.walk(_FN):
        if isinstance(n, ast.Raise):
            seg = ast.get_source_segment(_SRC, n) or ""
            # The message is an f-string split across two literals
            # (`"...matches no named "` + `"branch and no entry..."`), so a
            # search for the whole phrase finds nothing. An earlier version of
            # this test did exactly that and reported the refusal as VANISHED
            # against correct code — a source assertion that spans a line join
            # asserts about a string that never exists in the AST.
            if "matches no named" in seg:
                out.append(n.lineno)
    return out


def test_the_branch_chain_is_readable_from_the_ast():
    """If this extraction ever returns empty while branches exist, every
    other assertion here is vacuous — so emptiness is itself a failure."""
    lits = _branch_literals()
    assert lits, "no override == '<lit>' comparisons found — extractor broken"
    names = {v for _, v in lits}
    assert {"sky130A", "nangate45", "asap7"} <= names


def test_the_refusal_sits_after_every_named_branch():
    """THE construction. The withdrawn branch put an acceptance gate BEFORE
    the chain, which made a new hand-written lane unreachable dead code and
    the refusal message false. On main, reaching the refusal proves no
    branch matched — but only while it stays at the fall-through. Anyone
    moving it up front re-creates the withdrawn defect, and this fails."""
    refusals = _named_branch_refusal_lines()
    assert refusals, "the 'matches no named branch' refusal vanished"
    last_branch = max(l for l, _ in _branch_literals())
    for r in refusals:
        assert r > last_branch, (
            f"refusal at line {r} sits BEFORE the last named branch "
            f"(line {last_branch}) — a name that matches a branch would be "
            f"refused with a message claiming it matches none")


def test_no_parallel_acceptance_constant_exists():
    """The withdrawn branch's mechanism was a hand-maintained tuple that
    nothing derived and nothing checked. If an acceptance set is ever
    (re)introduced, it must be DERIVED from the chain — at which point this
    test should be updated to assert equality against `_branch_literals()`,
    a check that reads the OTHER side of the duplication and can fail."""
    assert "_PDK_NAMED_BRANCHES" not in _SRC


def test_each_named_branch_returns_before_the_refusal():
    """Every `override == "<name>"` branch must RETURN (or raise its own
    specific error) rather than fall through — otherwise a matched name
    reaches the fall-through refusal and the message lies."""
    for n in ast.walk(_FN):
        if (isinstance(n, ast.If) and isinstance(n.test, ast.Compare)
                and isinstance(n.test.left, ast.Name)
                and n.test.left.id == "override"
                and len(n.test.ops) == 1
                and isinstance(n.test.ops[0], ast.Eq)
                and isinstance(n.test.comparators[0], ast.Constant)):
            name = n.test.comparators[0].value
            exits = [x for x in ast.walk(n)
                     if isinstance(x, (ast.Return, ast.Raise))]
            assert exits, (
                f"branch for {name!r} has no Return/Raise — it falls "
                f"through to the refusal, which would then claim the name "
                f"matches no branch")
