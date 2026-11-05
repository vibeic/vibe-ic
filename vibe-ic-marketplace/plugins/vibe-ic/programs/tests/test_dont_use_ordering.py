#!/usr/bin/env python3
"""The cell exclusion must be in force BEFORE anything can insert a cell.

vibe-ic#551, established by controlled experiment on ibex (sky130A, 47 846
instances), in vibeic-eda:0.2.45:

    exclusion at ROUTE time, from post_cts.def (probe=61)
        -> [ERROR DRT-0085] Valid access pattern combination not found
    exclusion before CTS,    from placed.def  (probe=0)
        -> 0 probe cells after CTS, DRT-0085 = 0, DRT-0073 = 0

`set_dont_use` governs the optimizer's FUTURE cell pool. Against a DEF that
already contains those cells it is inert — and the run still prints
`DONT_USE_APPLIED: 52 cells`, so the guard reads as working while the route
dies. Measured on the real artefacts:

    floorplan.def  probe=0      placed.def  probe=0      post_cts.def  probe=61

The 61 unroutable instances enter between placement and CTS, which is precisely
the window the exclusion has to precede.

The emitted TCL already gets this right — the block sits after `link_design`
and before `set_wire_rc`, resizing, CTS and routing. NOTHING KEPT IT THERE.
These tests are what makes the ordering a property rather than a coincidence,
because the failure it prevents is silent: no error, no warning, just probe
cells in the DEF and a route that cannot finish.
"""
from __future__ import annotations

import pathlib
import re
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import phase3_one_shot_runner as P                            # noqa: E402


#: The marker substituted for the exclusion block, so its position is found by
#: identity rather than by matching a command the emitted TCL also contains.
_MARKER = "SET_DONT_USE_MARKER"

#: A complete argument set for the builder. Every block-valued parameter is
#: empty: the ordering asserted here is a property of the TEMPLATE, and a
#: fixture that filled them would be asserting the fixture's own layout.

#: The steps that can insert a cell. `set_dont_use` governs the optimizer's
#: future pool, so each must run AFTER the exclusion is in force.
_INSERTERS = ("clock_tree_synthesis", "repair_design", "repair_timing",
              "global_route", "detailed_route", "detailed_placement")


# ── A MENTION IS NOT AN INVOCATION ────────────────────────────────────────────
#
# MEASURED on live main a9b98b6bf (lane icslot11): this file asserted the
# ordering with a plain substring search, and it went red reporting
# "`global_route` appears BEFORE the cell exclusion" at offset 496. Nothing
# routes there. The template now opens with a ROUTE-GUIDE DISCIPLINE PROLOGUE
# that WRAPS those two commands:
#
#     if {[llength [info commands detailed_route]] == 0 || ... } { ... }
#     rename global_route _vibeic_real_global_route
#     proc   global_route {args} { ... }
#     rename detailed_route _vibeic_real_detailed_route
#     proc   detailed_route {args} { ... }
#
# Every pre-marker occurrence is introspection, a rename, a proc HEADER, a
# diagnostic string, or the renamed original `_vibeic_real_*`. A `proc` body is
# not executed where it is written, and installing a wrapper inserts no cell —
# so #551's invariant was never violated. What broke is the INSTRUMENT: it could
# not tell "this step runs here" from "this command's name appears here".
#
# THE RULE IS CONSERVATIVE ON PURPOSE, and this is the load-bearing choice. The
# obvious rule — "an invocation is the command in Tcl command position, i.e. the
# first word of the line" — is WRONG and I measured it before rejecting it:
# almost every real call in this template is `if {[catch {cmd ...}]}`, so that
# rule recognises 1 of 33 real invocations and would have turned a guard into a
# decoration. Errors here must fall on the STRICT side: a mention miscounted as
# an invocation only makes the test harsher, while a missed invocation silently
# removes the thing #551 exists to prevent. So this excludes ONLY the contexts
# that PROVABLY cannot call, and counts everything else.
_QUOTED = re.compile(r'"[^"\n]*"')


def _invokes(line: str, cmd: str) -> bool:
    """Does this template line CALL `cmd`? Conservative: see the note above."""
    text = _QUOTED.sub(" ", line)                    # diagnostics are not code
    text = text.replace(f"_vibeic_real_{cmd}", " ")  # the renamed original
    if "info commands" in text:                      # introspection
        return False
    head = text.strip().split(" ")[0] if text.strip() else ""
    if head in ("rename", "proc"):                   # renaming / defining
        return False
    return re.search(r'(?<![\w:])' + re.escape(cmd) + r'(?![\w:])',
                     text) is not None


def _invocation_lines(template: str, cmd: str):
    """`(before, after)` line indices that invoke `cmd`, split at the marker."""
    marker_at = template.index(_MARKER)
    before, after, offset = [], [], 0
    for index, line in enumerate(template.split("\n")):
        if _invokes(line, cmd):
            (before if offset < marker_at else after).append(index)
        offset += len(line) + 1
    return before, after










def test_the_exclusion_reaches_the_template_at_all():
    """A block computed and never interpolated is the wiring failure that
    version of this bug would take: `_dont_use_tcl` runs, the log says nothing,
    and no cell is excluded."""
    src = pathlib.Path(P.__file__).read_text()
    assert "dont_use_block = _dont_use_tcl(pdk)" in src
    assert "{dont_use_block}" in src, "computed and never emitted"
    assert "dont_use_block=dont_use_block" in src, "never passed to the emitter"




# ── the INSTRUMENT, pinned both ways ──────────────────────────────────────────
#
# The ordering assertion above is only as good as `_invokes`, and `_invokes` is
# the part this lane had to replace. A rule that is too loose reports a defect
# that is not there (the red that opened this work); one that is too tight
# removes the guard silently. Both directions are therefore cases of their own,
# over the SHAPES the shipped template actually contains rather than invented
# ones — each string below is copied from the emitted Tcl.
_NOT_AN_INVOCATION = (
    'if {[llength [info commands detailed_route]] == 0 || '
    '[llength [info commands global_route]] == 0} {',
    'rename global_route _vibeic_real_global_route',
    'proc global_route {args} {',
    '    return [uplevel 1 _vibeic_real_global_route $args]',
    '      if {[catch {_vibeic_real_global_route} _rgd_e]} {',
    '        puts "ROUTE_GUIDES_UNAVAILABLE: global_route returned cleanly"',
)

_IS_AN_INVOCATION = (
    'global_route',
    '  global_route',
    'if {[catch {global_route} _e]} { puts "X" }',
)


@pytest.mark.parametrize("line", _NOT_AN_INVOCATION)
def test_a_mention_is_not_read_as_an_invocation(line):
    """Introspection, a rename, a proc HEADER, the renamed original, and a
    diagnostic string all NAME the command without calling it. Installing a
    wrapper inserts no cell, so none of these may trip the ordering guard."""
    assert _invokes(line, "global_route") is False, line


@pytest.mark.parametrize("line", _IS_AN_INVOCATION)
def test_a_real_call_is_read_as_an_invocation(line):
    """The direction that matters more. `if {[catch {cmd ...}]}` is how almost
    every step in this template is actually called — 32 of the 33 real
    invocations — so a rule keyed on Tcl command position would recognise
    nearly none of them and the guard would become a decoration."""
    assert _invokes(line, "global_route") is True, line


def test_the_denominator_can_actually_fail():
    """`assert after` is the anti-vacuity half, and it needs a proven detector:
    over a template that never calls the command, `_invocation_lines` must
    report an empty `after` rather than silently satisfying the ordering."""
    template = f"read_lef /t.lef\n{_MARKER}\ndetailed_placement\n"
    before, after = _invocation_lines(template, "global_route")
    assert (before, after) == ([], [])
    before, after = _invocation_lines(template, "detailed_placement")
    assert before == [] and after, (before, after)
