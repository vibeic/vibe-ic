#!/usr/bin/env python3
"""The decision digest must measure the LOGIC, not the interpreter.

THE DEFECT (v1.7.74, caught by CI and not by me)
================================================
`_record_adjudication.decision_digest` hashed `ast.dump(node,
include_attributes=False)`. `ast.dump` serialises NODE FIELDS, and CPython adds
fields between releases — 3.12 gave `FunctionDef` a `type_params`. So identical
source hashed differently on 3.11 and 3.12.

The consequence was not a wrong answer, it was a *misattributed* one: on CI's
3.11 the digest did not match the declaration stamped on 3.12, the gate reported
`RULES_UNREVIEWED`, its 7 si_mcf records became undecidable, the two recorded
debt entries therefore looked "resolved", and `published_record_staleness_check`
failed with "the debt was paid; shrink the register". Every one of those
statements was false, and each followed correctly from the one before.

The gate itself behaved right — it refused to certify what it could not verify.
What was wrong is the quantity it verified against: a fingerprint claiming to
measure the decision logic while measuring the logic AND the interpreter.

WHAT IS PINNED HERE
===================
1. The serialisation carries no AST node-field names at all, so a future CPython
   adding another field cannot leak into the digest the way `type_params` did.
2. The digest is still SENSITIVE: a real edit inside the closure moves it.
3. Formatting and comments do not move it — that is what makes it a logic
   fingerprint rather than a file hash.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import _record_adjudication as _ra  # noqa: E402

_SRC = """
def root(a):
    return helper(a) + 1

def helper(b):
    return b * 2

def unrelated(c):
    return c - 1
"""


def _digest(src: str) -> str:
    return _ra.decision_fingerprint(src, ["root"])


def test_serialisation_carries_no_ast_node_field_names():
    """The regression's mechanism, pinned at its root.

    `type_params` was invisible until a Python upgrade. Any node-field name in
    the serialised form is the same latent defect waiting for the next release,
    so the property is asserted over the serialisation, not over one field."""
    node = ast.parse("def f(a, /, b=1, *, c=2):\n    return a\n").body[0]
    text = ast.unparse(_ra._without_docstring(node))
    for field in ("type_params", "decorator_list", "posonlyargs", "kw_defaults",
                  "kwonlyargs", "ctx=", "Load()", "FunctionDef("):
        assert field not in text, f"{field!r} leaked into the digest input"


def test_a_real_edit_inside_the_closure_moves_the_digest():
    """The paired half: version-stability must not have cost it its teeth."""
    before = _digest(_SRC)
    after = _digest(_SRC.replace("return b * 2", "return b * 3"))
    assert before != after


def test_an_edit_OUTSIDE_the_closure_does_not_move_it():
    before = _digest(_SRC)
    after = _digest(_SRC.replace("return c - 1", "return c - 99"))
    assert before == after, "unrelated() is not reachable from root()"


def test_reformatting_inside_the_closure_DOES_move_it_and_that_is_the_price():
    """The cost of an interpreter-independent fingerprint, pinned so it is a
    decision and not a surprise.

    v1.7.74 hashed `ast.dump`, v1.7.75 hashed `ast.unparse`; CI rejected both,
    because both ask CPython to re-emit the tree and CPython changes what it
    emits between releases. The only input nothing in CPython can move is the
    file's own bytes. That buys correctness and costs quiet: re-wrapping a CODE
    line inside a decision function now moves the digest. Blank and
    comment-only lines are still dropped, so those remain free.

    A slightly noisy fingerprint that works beats a quiet one that does not."""
    rewrapped = _SRC.replace("    return b * 2", "    return (\n        b * 2\n    )")
    assert _digest(_SRC) != _digest(rewrapped)


def test_blank_and_comment_only_lines_alone_do_NOT_move_it():
    """The normalisation that survives: pure text, no parser asked to
    normalise anything, so it cannot drift with the interpreter."""
    padded = _SRC.replace("def helper(b):\n", "\ndef helper(b):\n\n")
    assert _digest(_SRC) == _digest(padded)


def test_a_docstring_rewrite_DOES_move_it_as_the_declaration_always_claimed():
    """This is a repair, not a regression.

    si_mcf_sta_check.py's own comment above `decision_digest` says the digest
    "changes when the decision logic changes — INCLUDING the written reasons,
    which are part of what a rule pins", and that a fingerprint staying quiet
    through a prose rewrite "would be the wrong kind of quiet".

    The previous implementation ran `_without_docstring` first, so it stayed
    quiet through exactly that. The stored comment described a behaviour the
    code did not have. Hashing the file's own bytes brings them into
    agreement."""
    one = _SRC.replace("def helper(b):\n", 'def helper(b):\n    """One."""\n')
    two = _SRC.replace("def helper(b):\n", 'def helper(b):\n    """Two."""\n')
    assert _digest(one) != _digest(two)
