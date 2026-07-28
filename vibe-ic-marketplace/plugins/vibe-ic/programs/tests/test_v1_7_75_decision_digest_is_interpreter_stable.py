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


def test_comments_and_formatting_do_not_move_it():
    """A fingerprint that moved on a reflow would train its reader to re-stamp
    it without reading, which is how a real drift gets waved through."""
    noisy = _SRC.replace("def helper(b):", "# a comment\ndef helper(  b  ):")
    assert _digest(_SRC) == _digest(noisy)


def test_a_docstring_rewrite_does_not_move_it():
    with_doc = _SRC.replace("def helper(b):\n", 'def helper(b):\n    """One."""\n')
    other_doc = _SRC.replace("def helper(b):\n", 'def helper(b):\n    """Two."""\n')
    assert _digest(with_doc) == _digest(other_doc)
