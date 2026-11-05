"""A tie the rung inserts creates two new gaps, and it must look at them.

MEASURED on spm run15, from the row DF.13_MV caught. Row y=1642.48 held 75
instances and exactly TWO well ties, at x=393.12 and x=2767.52 -- 2374.4 um
apart. The anchor set is {row start, row end, midpoint between each pair of
consecutive ties}, so two ties give THREE points and exactly ONE uncovered:
the midpoint at x=1580.88. One tie was placed there and the row was declared
done -- while the two fresh 1187 um half-gaps that very insertion created were
never examined, because `_wtpts` was built ONCE before the loop and only
`_wtc` was appended to inside it.

That is why run15 reported

    WELLTIE_COVERAGE_REPAIR: pitch=15.0um radius=15.0um anchor_rows=32
    uncovered_anchors=75 ties_added=75 unplaceable=0

-- every initially-computed point got a tie, so the rung declared success --
on rows still hundreds of microns bare. The sign-off DRC then found it:
DF.13_MV, one pactive at (528.26,1644.84)-(535.24,1646.06) whose nearest ntap
inside its own nwell is 17.91 um against a 15.0 um rule. The nwell island
holds 42 ntaps and its in-row gaps are 29.12 um everywhere EXCEPT one of
407.68 um -- the residue of the single non-iterated pass.

THE POINT SET IS A FUNCTION OF THE TIES, so it cannot be computed once and
then inserted into. The rung now repeats the whole computation until a pass
finds nothing uncovered, or finds nothing it can place, or trips a cap on
PASSES -- and then RE-DERIVES the point set one last time from the ties that
actually exist, so `ties_added` becomes a claim about the ROW rather than
about the loop. Whatever is still uncovered is named by row and span
(WELLTIE_ROW_STILL_UNCOVERED) and counted in rows_still_uncovered. Never
both silent.
"""
import shutil
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

tclsh = shutil.which("tclsh")








# ── the spec, in Python, which the emitted Tcl is written to ───────────────

def _iterate(row_x0, row_x1, ties, radius, width, site, blocked=()):
    """What the fixed rung must do: insert until nothing is uncovered."""
    centres = sorted(t + width // 2 for t in ties)
    added = []
    for _ in range(64):
        pts = sorted({row_x0, row_x1,
                      *[(a + b) // 2 for a, b in zip(centres, centres[1:])]})
        unc = [p for p in pts
               if not any(abs(c - p) <= radius for c in centres)]
        if not unc:
            return added, []
        progress = False
        for px in unc:
            placed = None
            k0 = (px - row_x0) // site
            for j in range(radius // site + 1):
                for sgn in (1, -1):
                    x = row_x0 + (k0 + sgn * j) * site
                    if x < row_x0 or x + width > row_x1:
                        continue
                    if abs(x + width // 2 - px) > radius:
                        continue
                    if any(x < b and a < x + width for a, b in blocked):
                        continue
                    placed = x
                    break
                if placed is not None:
                    break
            if placed is not None:
                centres = sorted(centres + [placed + width // 2])
                added.append(placed)
                progress = True
        if not progress:
            break
    pts = sorted({row_x0, row_x1,
                  *[(a + b) // 2 for a, b in zip(centres, centres[1:])]})
    return added, [p for p in pts
                   if not any(abs(c - p) <= radius for c in centres)]


def test_run15s_own_row_needs_more_than_one_tie():
    """THE DEFECT, as arithmetic. Two ties 2374.4 um apart, radius 15 um: one
    insertion leaves two 1187 um half-gaps, and the old rung stopped there."""
    U = 1000                       # DEF units per micron
    row_x0, row_x1 = 392 * U, 2770 * U
    ties = [393 * U + 120, 2767 * U + 520]
    added, left = _iterate(row_x0, row_x1, ties, 15 * U, 1120, 560)
    assert len(added) > 1, (
        "one insertion cannot cover a 2374 um gap at a 15 um radius; the "
        "old rung added exactly one and called the row done")
    assert left == [], "the spec must reach full coverage on a free row"
    assert len(added) >= 75, (
        f"a 2374 um gap needs ~79 ties at 30 um effective pitch, got "
        f"{len(added)}")


def test_the_spec_stops_and_reports_when_nothing_can_be_placed():
    """A row whose whole span is occupied cannot be covered, and that must be
    a NAMED residue rather than a silent success."""
    U = 1000
    row_x0, row_x1 = 0, 200 * U
    added, left = _iterate(row_x0, row_x1, [0], 15 * U, 1120, 560,
                           blocked=[(0, 200 * U)])
    assert added == []
    assert left, "an uncoverable row must report what is still uncovered"


# ── the emitted Tcl carries the same shape ─────────────────────────────────









# ── the row logic, EXECUTED ────────────────────────────────────────────────
#
# A string-presence assertion cannot tell a live branch from a dead one: my
# first version of the test below passed while the refusal was mutated to
# `if {0}`, because the marker TEXT was still in the emitted deck. So the
# per-row section is sliced out of the real emission and driven through tclsh
# with the arrays it reads prepared by hand.

_ROW_BEGIN = "foreach _wty [lsort -integer [array names _wtanc]] {"
_ROW_END = "set ::_vibeic_welltie_uncovered $_wtfail"




_ROW_HARNESS = """
set _wtrad %(rad)d
set _wttw  %(tw)d
array set _wtanc {%(y)d 1}
array set _wtrx0 {%(y)d %(x0)d}
array set _wtrx1 {%(y)d %(x1)d}
array set _wtrsw {%(y)d %(site)d}
array set _wttie {%(y)d {%(ties)s}}
array set _wtocc {%(y)d {%(occ)s}}
array set _wtro  {%(y)d R0}
set _wtblk ::BLK
set _wtm   ::MASTER
set _wtadded 0; set _wtneed 0; set _wtfail 0; set _wtrows 0
set _wtrowsleft 0
set _wtfaildesc {}
set ::created {}
proc ::BLK {method args} {
  switch -- $method { getInsts { return {} } }
  return NULL
}
proc ::MASTER {args} { return "" }
namespace eval odb {
  proc dbInst_create {blk master name} { lappend ::created $name ; return ::NEWI }
}
proc ::NEWI {method args} { return "" }
"""
