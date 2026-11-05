#!/usr/bin/env python3
"""A stated justification must be checkable.

The motivating measurement, reproduced in `test_the_motivating_funnel_shape_is_caught`:
a guard narrowed its predicate from a stated 113 raw matches to 13 to 5. The 13
and the 5 reproduce exactly. The 113 reproduces under no reading of the clause
it describes — reconstructions of the same predicate measured 41, 49, 71, 440
and 595 on this tree. The narrowing is sound; one of the figures offered in
support of it is not evidence, because a reader cannot get it back out.

These tests are written against OBSERVABLE PROPERTIES — what a docstring says
about this checkout, and what the guard reports for a given corpus — never
against the identity of a helper. A different correct fix (a different seam
name, a different placeholder syntax, a hand-rolled renderer) passes all of
them.
"""
from __future__ import annotations

import sys
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parents[1]
PLUGIN = PROGRAMS.parent
sys.path.insert(0, str(PROGRAMS))


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# --------------------------------------------------------------------------
# helpers — deliberately independent of the module under test
# --------------------------------------------------------------------------






#: A module that walks a tree — otherwise the funnel clause is out of scope.
_WALKER = 'from pathlib import Path\n\n\ndef sweep(r):\n    return list(Path(r).rglob("*.py"))\n'




# ==========================================================================
# 1. THE CONTROLS — these fail on the pre-fix tree, on a value difference
# ==========================================================================








# ==========================================================================
# 2. THE SWEEP MUST DEMONSTRABLY FIRE — the rule applied to my own evidence
# ==========================================================================






# ==========================================================================
# 3. THE REVERSE CASES — every one is an over-correction that must NOT happen
# ==========================================================================














# ==========================================================================
# 4. THE BINDING CONTRACT — no name allow-list; a site changes or stays flagged
# ==========================================================================










def test_the_guard_is_wired_to_something_other_than_its_own_test():
    """`checker_execution_wiring_audit`'s rule, applied to this PR's own guard."""
    gates = (PLUGIN.parents[2] / "tools" / "ci" / "repo_hygiene_gates.sh")
    assert gates.is_file(), gates
    assert "derived_corpus_figure_check.py" in gates.read_text()
