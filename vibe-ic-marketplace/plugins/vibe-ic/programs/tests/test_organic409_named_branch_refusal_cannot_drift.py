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

MEASURED CORRECTION (vibe-ic#452). Main DOES now carry a parallel
acceptance constant: `_PDK_NAMED_BRANCHES` at phase3_one_shot_runner.py
:4876, feeding `_known_pdk_names()`, feeding the `_assert_pdk_name_
resolvable` gate that runs as `_detect_pdk`'s FIRST statement (#389's
fail-closed fix). So the acceptance set really does sit ahead of the chain
— the withdrawn branch's shape — but fail-closed and, as measured, in
sync. This file used to assert `"_PDK_NAMED_BRANCHES" not in _SRC`; that
assertion was RED on main for an unknown length of time, and a substring
search could not have told a definition from a mention anyway. It is
replaced by the invariant that shape can actually violate: no named branch
may be unreachable behind the gate.

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


def _string_collection_consts(tree: ast.AST):
    """Every `NAME = (<string literals>, …)` ASSIGNMENT in `tree`, as
    ``{name: (lineno, frozenset_of_values)}``.

    Read from assignment NODES. A comment or a docstring that merely NAMES a
    constant is not an assignment and is correctly invisible here — which is
    the entire point of this extractor existing. Collections holding anything
    other than string literals are skipped: this is about name sets.
    """
    out = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign):
            targets, value = n.targets, n.value
        elif isinstance(n, ast.AnnAssign):
            targets, value = [n.target], n.value
        else:
            continue
        if not isinstance(value, (ast.Tuple, ast.List, ast.Set)):
            continue
        elts = list(value.elts)
        vals = {e.value for e in elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)}
        if not elts or len(vals) != len(elts):
            continue
        for t in targets:
            if isinstance(t, ast.Name):
                out[t.id] = (n.lineno, frozenset(vals))
    return out


def _acceptance_gate_constant_names():
    """Which module-level constants the FAIL-CLOSED acceptance gate actually
    reads, derived from `_known_pdk_names`'s own AST rather than named here.

    `_detect_pdk`'s first statement is `_assert_pdk_name_resolvable(override)`,
    which refuses any `--pdk` name not in `_known_pdk_names()`. So the gate
    genuinely does sit BEFORE the branch chain on main — the shape #409
    recorded. Sourcing the constant NAME from the gate's own AST means
    renaming or replacing the constant cannot silently empty this check.
    """
    fn = next((n for n in ast.walk(_TREE)
               if isinstance(n, ast.FunctionDef) and n.name == "_known_pdk_names"),
              None)
    if fn is None:
        return set()
    read = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    return read & set(_string_collection_consts(_TREE))


def _registry_names():
    """The other lane `_known_pdk_names` unions in — read from the shipped
    JSON, the way the code reads it."""
    import json
    try:
        reg = json.loads((_PROGRAMS / "pdk_registry.json").read_text())
    except (OSError, ValueError):
        return set()
    return {e["name"] for e in (reg.get("pdks") or []) if e.get("name")}


def test_the_constant_detector_reads_definitions_not_mentions():
    """BOTH HALVES, pinned on synthetic source so neither depends on what
    `phase3_one_shot_runner.py` happens to contain today.

    This test file's predecessor asserted `"_PDK_NAMED_BRANCHES" not in _SRC`.
    A substring search over source text cannot tell a DEFINITION from a
    MENTION: it fires on the comment above the constant, on this docstring's
    own vocabulary if it lived in that file, and on a `# never add
    _PDK_NAMED_BRANCHES` warning — while a constant spelled any other name
    slips past untouched. Structure is the fix, and a structural detector is
    only trustworthy if its blindness to prose AND its sight of real
    assignments are both nailed down.
    """
    # (1) BLIND to mentions — comment, then docstring.
    comment = ast.parse(
        '# _PDK_NAMED_BRANCHES = ("sky130A", "nangate45") must never exist\n'
        'X = 1\n')
    assert "_PDK_NAMED_BRANCHES" not in _string_collection_consts(comment)
    doc = ast.parse(
        '"""Do not reintroduce _PDK_NAMED_BRANCHES = (\'sky130A\',)."""\n'
        'X = 1\n')
    assert "_PDK_NAMED_BRANCHES" not in _string_collection_consts(doc)

    # (2) SIGHTED on a real assignment — the half that makes (1) non-vacuous.
    real = ast.parse('_PDK_NAMED_BRANCHES = ("sky130A", "nangate45")\n')
    got = _string_collection_consts(real)
    assert "_PDK_NAMED_BRANCHES" in got, (
        "the detector missed a plain module-level assignment — every other "
        "assertion built on it is vacuous")
    assert got["_PDK_NAMED_BRANCHES"][1] == {"sky130A", "nangate45"}
    # annotated form must be seen too, or the drift just needs a type hint
    ann = ast.parse('_PDK_NAMED_BRANCHES: tuple = ("asap7",)\n')
    assert _string_collection_consts(ann)["_PDK_NAMED_BRANCHES"][1] == {"asap7"}


def test_no_named_branch_is_unreachable_behind_the_acceptance_gate():
    """#409's mechanism, now CHECKED instead of forbidden.

    The parallel acceptance constant this file once asserted the ABSENCE of
    now EXISTS on main — `_PDK_NAMED_BRANCHES`, feeding `_known_pdk_names()`,
    feeding the `_assert_pdk_name_resolvable` gate that runs as `_detect_pdk`'s
    first statement. That is the withdrawn branch's shape: an acceptance set
    ahead of the branch chain. It is fail-closed and currently in sync, so the
    honest invariant is not "this must not exist" — it is the one thing that
    shape can get wrong.

    THE DIRECTION THAT MATTERS IS ADDITION. Add `override == "<new>"` to
    `_detect_pdk` and forget the acceptance set, and the gate refuses `--pdk
    <new>` before the chain is ever reached: the new hand-written lane is
    UNREACHABLE DEAD CODE, which is verbatim what #409 measured on the
    withdrawn branch. #389 recurred three times because each fix added a named
    branch, so this is the edit that will actually be made.

    The other direction is not a finding: a name accepted by the gate with no
    branch falls through to the chain's own refusal, which is true by
    construction (`test_the_refusal_sits_after_every_named_branch`).

    Read from the AST of the chain and the AST of the gate — the two OTHER
    sides of the duplication, never the same constant the code reads.
    """
    branches = {v for _, v in _branch_literals()}
    assert branches, "no named branches found — extractor broken"

    const_names = _acceptance_gate_constant_names()
    assert const_names, (
        "`_known_pdk_names` reads no string-collection constant — either the "
        "gate was restructured or the extractor is broken; either way this "
        "test would silently pass on anything")

    consts = _string_collection_consts(_TREE)
    accepted = set()
    for name in const_names:
        accepted |= consts[name][1]
    accepted |= _registry_names()

    unreachable = branches - accepted
    assert not unreachable, (
        f"{sorted(unreachable)} have a hand-written branch in `_detect_pdk` "
        f"but are not in the acceptance set the fail-closed gate consults "
        f"({sorted(const_names)} + pdk_registry.json). `--pdk <name>` is "
        f"refused by `_assert_pdk_name_resolvable` BEFORE the chain runs, so "
        f"those branches are unreachable dead code — the exact defect "
        f"vibe-ic#409 recorded on the withdrawn branch.")


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


def _registry_lane_skip_literals():
    """The tuple in `if override not in (...)` that decides whether the
    registry lane is even tried — a hand-maintained restatement of the named
    branches, and the one duplication #409 named that main still carries.
    Read from the AST, so it cannot be satisfied by reading the same constant
    the code reads."""
    out = set()
    for n in ast.walk(_FN):
        if not (isinstance(n, ast.Compare) and len(n.ops) == 1
                and isinstance(n.ops[0], ast.NotIn)):
            continue
        left, right = n.left, n.comparators[0]
        if not (isinstance(left, ast.Name) and left.id == "override"):
            continue
        if isinstance(right, (ast.Tuple, ast.List, ast.Set)):
            out |= {e.value for e in right.elts
                    if isinstance(e, ast.Constant)
                    and isinstance(e.value, str)}
    return out


def test_the_registry_lane_skip_list_equals_the_branch_chain():
    """#409's remaining duplication, now CHECKED rather than claimed.

    `_detect_pdk` skips the pdk_registry lane for names it handles with a
    hand-written branch. That skip list is a second copy of the branch
    literals, and the drift that bites is REMOVAL: delete a named branch and
    leave the tuple, and that PDK loses its branch AND is refused the
    registry lane — it falls through to project-local resolution or None,
    silently, with no refusal naming it.

    Adding a branch without updating the tuple is harmless (the branch
    returns first), so this asserts equality in the direction that matters
    and explains why the other direction is not a finding.
    """
    branches = {v for _, v in _branch_literals()}
    skip = _registry_lane_skip_literals()
    assert skip, "no `override not in (...)` guard found — extractor broken"
    orphaned = skip - branches
    assert not orphaned, (
        f"{sorted(orphaned)} are refused the pdk_registry lane but have no "
        f"named branch in _detect_pdk — that PDK resolves to nothing and "
        f"nothing says so")
