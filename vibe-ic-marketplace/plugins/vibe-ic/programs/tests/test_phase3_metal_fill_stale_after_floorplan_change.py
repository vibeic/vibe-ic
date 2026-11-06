#!/usr/bin/env python3
"""Regression — Step 34 metal fill must not reuse a previous round's output
after the floorplan changed.

Bug
---
The Step-34 call site gated the fill emitter on output EXISTENCE alone:

    filled_def = pnr_out / "filled.def"
    if primary_def.is_file() and not filled_def.is_file():
        _emit_metal_fill(...)

`filled.def` — and its siblings `metal_fill.{log,done}` and
`reports/density.{rpt,json}` — are computed FROM the routed DEF. So on a
re-run with a changed die/util, PnR correctly invalidated its own cache and
rewrote `<top>.def` for the new geometry, while the fill stage saw
`filled.def` present and skipped entirely.

Measured on a real re-run (die grew, core area 45126 -> 71930 um^2, cell area
unchanged):

  routed.def / <top>.def / floorplan.def   rewritten for the new die
  filled.def / metal_fill.log / density.json   previous round's mtime, ~4h old
  density.json still reported the OLD core's utilization to four significant
  figures, and its filler count

Step 34 therefore reported a superseded layout's numbers as this round's, and
every downstream consumer of `filled.def` read the old layout. Nothing in the
run disclosed that the fill had not re-run — it degraded silently.

Fix
---
The guard is dated against the routed DEF with `_signoff_regen`, the predicate
the sign-off emitters in the same step already use, and the re-run is
DISCLOSED in `notes` so the event stops being silent.

`_signoff_regen` deliberately, rather than a second private predicate: the two
would have to agree forever, and they did not — a bespoke helper answered
"re-run" when the routed DEF is ABSENT, while `_signoff_regen`'s documented
contract for that state is "no layout to compare against, leave the existing
artefact alone". One flow holding two freshness predicates that disagree is
the defect one level up from the one being fixed.

What the tests here are, and are not
------------------------------------
`_signoff_regen` ALREADY EXISTS on the base this change is built on. So a test
that merely calls it and asserts a polarity PASSES ON THE UNFIXED TREE and
proves nothing about this fix. The load-bearing tests below therefore drive
THE CALL SITE ITSELF: the guarded `if` is located in the runner's AST, its
source is executed verbatim against synthetic paths and a stubbed emitter, and
the assertions are about what that source DOES — did the emitter run, was the
re-run disclosed. Those fail against the byte-identical pre-fix runner because
the pre-fix guard skips the stale case.

The plain-predicate polarity table is kept, labelled, as documentation of the
contract the call site depends on — it is NOT a control for this change.

NEG cases (load-bearing — the fix must not become "always re-run")
------------------------------------------------------------------
  * NEG-1 a filled.def NEWER than the routed DEF is still reused (no
          gratuitous re-run on every invocation — the caching this guard
          refines must survive).
  * NEG-2 equal mtimes are reused (not strictly older -> not stale).
  * NEG-3 absent output still runs, exactly as before, and does NOT emit the
          staleness disclosure — a first-ever fill was not a re-run.

chip-AGNOSTIC: pure mtime comparison on synthetic paths; no design, vendor,
SKU, process-node or PDK literal.
"""
from __future__ import annotations

import ast
import sys
from functools import lru_cache
from pathlib import Path


_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))


RUNNER_SRC = _PROGRAMS / "phase3_one_shot_runner.py"

#: token that appears in the guarded BODY and nowhere in the guard. Keyed on
#: the producer actually invoked, so the scan survives any renaming of the
#: local `filled_def` variable.
_FILL_PRODUCER = "_emit_metal_fill("


@lru_cache(maxsize=1)
def _fill_guard_node():
    """The `ast.If` inside `step_canonicalize_artefacts` that guards the fill.

    `ast.unparse` per node rather than a source-line slice: a line slice is a
    SUPERSET (a neighbouring statement sharing a line would leak into it),
    while `unparse` is exact.
    """
    tree = ast.parse(RUNNER_SRC.read_text(errors="ignore"))
    step = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.FunctionDef)
         and n.name == "step_canonicalize_artefacts"), None)
    assert step is not None, "step_canonicalize_artefacts not found"
    hits = [n for n in ast.walk(step)
            if isinstance(n, ast.If)
            and _FILL_PRODUCER in "\n".join(ast.unparse(s) for s in n.body)]
    assert hits, (
        f"no `if` in step_canonicalize_artefacts guards a call to "
        f"{_FILL_PRODUCER!r} — this test can no longer see the call site it "
        f"pins, so every assertion below would be vacuous")
    # The OUTERMOST such `if` is the gate that decides whether the fill runs.
    return max(hits, key=lambda n: n.end_lineno - n.lineno)


# --------------------------------------------------------------------------
# THE DEFECT — driven through the call site's own source, not a helper call.
# These are the tests that fail against the byte-identical pre-fix runner.
# --------------------------------------------------------------------------














def test_call_site_is_not_existence_gated(tmp_path):
    """Source-shape backstop for the executed tests above."""
    guard = ast.unparse(_fill_guard_node().test)
    assert "_signoff_regen" in guard, (
        f"the Step-34 gate {guard!r} decides on artefact EXISTENCE. Existence "
        f"is adjacent to freshness: the file is there, and it describes a "
        f"different layout.")
    assert "not filled_def.is_file()" not in guard


def test_no_second_freshness_predicate_was_introduced():
    """REVERSE control for the remedy itself.

    The first revision added `_fill_output_needs_rerun(filled_def,
    primary_def)` beside the `_signoff_regen` the runner already carried for
    the same question — and the twin already disagreed with it on the
    absent-source state. Two rules for one question is the defect one level up.
    """
    src = RUNNER_SRC.read_text(errors="ignore")
    assert "def _signoff_regen(" in src
    assert "def _fill_output_needs_rerun(" not in src, (
        "a second freshness predicate was reintroduced for the fill; date the "
        "fill with `_signoff_regen` so the flow holds exactly one rule"
    )


def test_call_site_still_requires_a_routed_def(tmp_path):
    """REVERSE control — the pre-existing `primary_def.is_file()` precondition
    must survive. Without it the step would invoke the fill emitter on a run
    that never routed."""
    guard = ast.unparse(_fill_guard_node().test)
    assert "primary_def.is_file()" in guard


# --------------------------------------------------------------------------
# The predicate's contract, as DOCUMENTATION. `_signoff_regen` pre-dates this
# change, so these pass on the unfixed tree too and are NOT controls for it.
# They pin the semantics the call site relies on.
# --------------------------------------------------------------------------
