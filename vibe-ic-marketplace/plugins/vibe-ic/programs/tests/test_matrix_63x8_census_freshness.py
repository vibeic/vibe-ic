#!/usr/bin/env python3
"""The published 63x8 census must reproduce, and it must carry its own caveats.

WHAT WENT WRONG
===============
``matrix_63x8/README.md`` published a hand-written census table::

    | **total** |  | **483** | **9** | **12** |

and, two lines underneath it, the command that disproves it. Run on
``origin/main`` at ``dee025059`` on 2026-08-09::

    Counter({'ENFORCED': 481, 'NA': 12, 'WAIVED': 11})

Four rows had drifted. Nothing recomputed the table, so the campaign's headline
number was a number someone typed once — while every cell underneath it was
recomputed live on every run, which is the entire premise of the suite.

The second half is worse than the drift. Dimension 8 substitutes a stand-in gate
for most of its cells; 45 of its 61 ENFORCED cells never touch the gate the step
declares. That is disclosed, carefully, in its module docstring, and then the
census added eight rows together and the disclosure was gone. A caveat that does
not travel with the number is not a caveat.

WHAT THIS FILE LOCKS
====================
1. The block is GENERATED. ``tools/gen_matrix_63x8_census.py --check`` re-derives
   it from the live suite and this test fails on any drift — the same shape as
   ``test_programs_index_freshness.py`` for ``programs/INDEX.md``.
2. The published figures EQUAL the live census, checked here independently of
   the generator's own diff. If both the generator and the committed README were
   wrong in the same way, (1) would still pass; this does not.
3. The substituted cells are published as their own column and are NEVER inside
   a figure presented as enforcement. This is the assertion that fails on the
   unfixed tree.

Run::

    cd .../plugins/vibe-ic && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \\
      python3 -m pytest programs/tests/test_matrix_63x8_census_freshness.py -q
"""
from __future__ import annotations

import re
import subprocess
import sys

import pytest

from _plugin_tree import plugin_path, repo_path_or_missing

from matrix_63x8 import substitution as SUB

import test_matrix_63x8_coverage as CV

GEN = repo_path_or_missing("tools", "gen_matrix_63x8_census.py")
README = plugin_path("programs", "tests", "matrix_63x8", "README.md")

BEGIN = ("<!-- BEGIN GENERATED CENSUS — tools/gen_matrix_63x8_census.py — "
         "DO NOT EDIT BY HAND -->")
END = "<!-- END GENERATED CENSUS -->"


def _block() -> str:
    text = README.read_text(encoding="utf-8")
    start = text.find(BEGIN)
    stop = text.find(END)
    assert 0 <= start < stop, (
        f"{README} has no generated-census block; the markers are what make "
        f"the published figure derived rather than typed, and without them a "
        f"hand edit is invisible to the freshness check"
    )
    return text[start:stop + len(END)]


def _total_row(block: str):
    """``(own, substituted, undeclared, contradicted, waived, na)``.

    Six figures, not five. CONTRADICTED became a column of its own when the
    three ENFORCED columns were moved onto the enforcement axis: they now span
    the ENFORCED cells only, so without a column of its own a contradicted cell
    would appear in no column at all and the row would silently drop 28 cells.
    """
    m = re.search(
        r"\|\s*\*\*total\*\*\s*\|[^|]*\|"
        r"\s*\*\*(\d+)\*\*\s*\|\s*\*\*(\d+)\*\*\s*\|\s*\*\*(\d+)\*\*\s*\|"
        r"\s*\*\*(\d+)\*\*\s*\|\s*\*\*(\d+)\*\*\s*\|\s*\*\*(\d+)\*\*\s*\|",
        block)
    assert m, (
        f"no ``**total**`` row with six bold figures found in the generated "
        f"census block. The published total is the number people quote; if it "
        f"cannot be parsed it cannot be checked.\n{block[:1200]}"
    )
    return tuple(int(g) for g in m.groups())


def test_the_census_block_is_present_and_marked_generated():
    block = _block()
    assert "DO NOT EDIT BY HAND" in block


def test_the_census_block_is_fresh():
    """Re-derive it and refuse any drift."""
    if not GEN.exists():
        pytest.skip(
            f"generator not present at {GEN} (mirror tree); freshness is "
            f"enforced in the source-of-truth tree only")
    r = subprocess.run(
        [sys.executable, str(GEN), "--check"],
        capture_output=True, text=True, timeout=1800)
    assert r.returncode == 0, (
        f"the census in {README} is stale — re-run "
        f"`python3 tools/gen_matrix_63x8_census.py`."
        f"\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}")


def test_the_published_total_equals_the_live_census():
    """Independent of the generator: the numbers on the page vs the tree.

    ``test_the_census_block_is_fresh`` compares the page against what the
    generator would emit. That is one source checked against itself: a
    generator that computed the wrong thing would agree with a README carrying
    the wrong thing, and both would be green. This recomputes from
    ``enforcement_census()`` / ``substitution_census()`` directly.

    INDEPENDENT IN SOURCE IS NOT INDEPENDENT IN AXIS. This test recomputed from
    ``state_census()`` -- the CONFIGURATION axis -- and so agreed with a
    generator that was wrong the same way. vibe-ic#898 moved the generator onto
    ``enforcement_census()`` and left this check behind, which is why the fold
    it was written to catch survived underneath it: the published ENFORCED
    split summed to 481 while the headline two lines above said 453, and this
    assertion passed, because 481 was exactly what the wrong axis predicted.
    A second opinion taken from the same mistaken premise is not a second
    opinion.
    """
    own, substituted, undeclared, contradicted, waived, na = _total_row(_block())
    states = {k: v.label for k, v in CV.enforcement_census().items()}
    subs = {k: v for k, v in CV.substitution_census().items()
            if states.get(k) == "ENFORCED"}
    live = {
        "ENFORCED": sum(1 for v in states.values() if v == "ENFORCED"),
        "CONTRADICTED": sum(
            1 for v in states.values() if v == "ENFORCED-CONTRADICTED"),
        "WAIVED": sum(1 for v in states.values() if v == "WAIVED"),
        "NA": sum(1 for v in states.values() if v == "NA"),
    }
    live_split = {b: sum(1 for v in subs.values() if v == b) for b in SUB.BUCKETS}
    assert (own, substituted, undeclared) == (
        live_split[SUB.OWN_MECHANISM],
        live_split[SUB.SUBSTITUTED],
        live_split[SUB.UNDECLARED_BUCKET],
    ), (
        f"the published ENFORCED split "
        f"(own={own}, substituted={substituted}, undeclared={undeclared}) "
        f"does not reproduce; the tree says {live_split}")
    assert (waived, na) == (live["WAIVED"], live["NA"]), (
        f"the published WAIVED/NA ({waived}/{na}) does not reproduce; the tree "
        f"says {live['WAIVED']}/{live['NA']}")
    assert contradicted == live["CONTRADICTED"], (
        f"the published CONTRADICTED ({contradicted}) does not reproduce; the "
        f"tree says {live['CONTRADICTED']}")
    assert own + substituted + undeclared == live["ENFORCED"], (
        f"the three ENFORCED columns sum to "
        f"{own + substituted + undeclared}, but {live['ENFORCED']} cells are "
        f"ENFORCED — some cell is in no column or in two")
    # THE ONE THAT WOULD HAVE CAUGHT THE FOLD. Every assertion above compares a
    # published figure to a live figure, so all of them stayed green while the
    # headline said 453 and the row said 481: no single one of them spans both
    # the headline and the row. This does -- the six columns must account for
    # every cell exactly once.
    assert own + substituted + undeclared + contradicted + waived + na == len(states), (
        f"the published columns account for "
        f"{own + substituted + undeclared + contradicted + waived + na} cells "
        f"but the matrix has {len(states)}. A published row that does not "
        f"partition is how a contradicted cell hides inside an enforcement "
        f"figure.")


def test_no_substituted_cell_is_inside_a_figure_presented_as_enforcement():
    """The finding, as an assertion. THIS is the one that fails on the old tree.

    Dimension 8's substituted cells were reported as plain ``ENFORCED`` and the
    README totalled them into one figure. Two properties are required, and the
    old tree had neither:

      * the census must be ABLE to tell the two apart — a suite where every
        ENFORCED cell reads OWN or UNDECLARED has no substitution vocabulary at
        all, which is how 45 cells travelled as enforcement of gates they never
        touched;
      * the published block must show the substituted count in its OWN column,
        never folded into an ENFORCED total.

    The second half is checked by construction: a block whose ENFORCED figure
    is a single number cannot satisfy the five-column total row, and a block
    that prints ``substituted`` as 0 while the tree measures 45 fails the
    equality above.
    """
    subs = CV.substitution_census()
    substituted = {k for k, v in subs.items() if v == SUB.SUBSTITUTED}
    assert substituted, (
        "no cell in the whole 504 reports itself as substituted, yet "
        "dimension 8 replaces every step's declared gate with a stand-in for "
        "45 of its 61 ENFORCED cells (KNOWN GAP #2 in its own docstring). "
        "Either the substitution contract is not wired — in which case those "
        "45 are being published as enforcement of gates they never touch, "
        "which is the defect — or dimension 8 stopped substituting and its "
        "docstring is now wrong."
    )

    block = _block()
    own, substituted_n, undeclared, _, _, _ = _total_row(block)
    assert substituted_n == len(substituted), (
        f"the block publishes {substituted_n} substituted cells; the tree "
        f"measures {len(substituted)}")
    # And the number is not merely present — it must be OUTSIDE the figure a
    # reader would take as enforcement.
    assert f"**{own + substituted_n}**" not in block, (
        f"the block prints **{own + substituted_n}** — own plus substituted "
        f"as one bold figure. That is precisely the fold this contract "
        f"removes: the substituted cells stop being visible the moment they "
        f"are added to the cells that were really measured.")


def test_every_substitution_disclosure_says_what_was_substituted():
    """A bare "substituted" label discloses nothing a reader can act on."""
    mods = CV.dimension_modules()
    seen = 0
    for (sid, dim), buck in CV.substitution_census().items():
        if buck != SUB.SUBSTITUTED:
            continue
        text = SUB.disclosure_for(mods[dim], sid, "ENFORCED")
        assert isinstance(text, str) and not SUB.validate(text), (
            f"d{dim}/{sid}: disclosure not admissible: {SUB.validate(text)}")
        seen += 1
    assert seen, (
        "NOTHING_SCANNED: no substituted cell was examined, so this test "
        "passed without grading a single disclosure")
