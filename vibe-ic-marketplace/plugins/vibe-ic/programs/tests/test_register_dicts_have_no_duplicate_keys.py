#!/usr/bin/env python3
"""A duplicate key in a register dict is INVISIBLE at runtime.

MEASURED on main `758ac4516`: `prose_polarity_consulted_check._NOT_PROSE`
carries `"crosslayer_rewrite_equivalence::module_ports"` TWICE -- once at line
~927 and again at line ~1124, a duplicate left by an earlier merge. Python
evaluates both and keeps the LAST, so the first entry's argument -- which was
the only place naming the non-ANSI port form `module m(a, b); input [7:0] a;`,
the `_pad_ring::parse_def` precedent, and "a call that can never fire is a
green light rather than a check" -- silently vanished. The file read as though
it held 65 exemptions; the module held 64.

WHY THIS NEEDS `ast` AND CANNOT BE DONE AT RUNTIME. By the time the dict
object exists the duplicate is already gone: `len()` reports the collapsed
count, `in` finds the survivor, and every value equals the last literal. There
is no runtime observation that distinguishes "written once" from "written
twice and one silently discarded". Only the SOURCE carries that fact, so the
only instrument that can see it is a parse of the source.

SCOPE: every module-level dict literal in the file, so a register added later
is covered without anyone remembering to list it here. `_NOT_PROSE` and
`_OFFENDER_REGISTER` are named explicitly as well, so that deleting or renaming
one of them cannot quietly empty this test's population.
"""
from __future__ import annotations

import ast
import collections
from pathlib import Path


PROG = Path(__file__).resolve().parent.parent
TARGET = PROG / "prose_polarity_consulted_check.py"










def test_the_instrument_can_actually_see_a_duplicate():
    """CONTROL FOR THE INSTRUMENT ITSELF. A duplicate-key check that cannot
    detect a planted duplicate would pass this file for the wrong reason --
    which is exactly the failure mode being fixed. Plant one and require the
    parser to report it."""
    planted = ast.parse('_R = {"a": "one", "b": "two", "a": "three"}\n')
    node = planted.body[0]
    keys = [k.value for k in node.value.keys]
    dupes = [k for k, c in collections.Counter(keys).items() if c > 1]
    assert dupes == ["a"], (
        "the ast-based duplicate detector failed on a planted duplicate")
    # and the runtime view really is blind to it, which is why ast is used
    scope: dict = {}
    exec(compile(planted, "<planted>", "exec"), scope)          # noqa: S102
    assert list(scope["_R"]) == ["a", "b"] and scope["_R"]["a"] == "three", (
        "the runtime dict unexpectedly preserved the duplicate -- if this ever "
        "holds, the premise of this whole test file needs re-deriving")
