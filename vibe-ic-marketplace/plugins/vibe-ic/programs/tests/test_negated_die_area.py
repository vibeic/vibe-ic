#!/usr/bin/env python3
"""A die figure a document DENIES must not become that document's mandate.

MEASURED on a real retarget. A design was moved from the process it was authored
for onto a different one. Its own L9 constraints document said, in as many words,
that the old fixed die no longer applied:

    The origin project's fixed die rectangle of <W> x <H> um is the die of an
    external harness on a different process. It has NO meaning here and is
    REMOVED, not translated.

`_DIE_LABELLED_WXH_RE` matched "die ... <W> x <H> um" inside that statement, and
`extract_floorplan_contract` published <W>x<H> as `die_area_budget_um` — the
design's MANDATED fixed die. `phase3_one_shot_runner` documents its precedence as
`... > L19-mandated die_area_budget_um > 'auto'`, so a run would have been hard
-sized onto a die belonging to a different chip on a different process, and the
report would have cited the design's own document as the authority for it.

The document said the opposite of what was recorded. There was no phrasing of the
denial that worked, because every phrasing restates the number, and the number was
all the extractor read.

THIS EXACT DEFECT WAS ALREADY FIXED ONCE, IN THE NEIGHBOURING FIELD.
`phase1_doc_one_shot_runner` carries `_FOUNDRY_NEGATION_RE` +
`_foundry_match_trustworthy` for `pdk_target`, added because "prose like 'fabbed
at <foundry> but NOT as a process target' mis-extracts the commercial name". The
hardening was never extended to the floorplan contract in the same document, so
the identical polarity blindness survived one field over.

WHAT THE GUARD MUST NOT DO, and both halves are pinned below:

  * A parenthetical negation is a QUALIFIER, not a denial. "1300 x 1300 um (no
    seal ring)" and "2200 x 1600 um (not including scribe)" are real die
    statements from the corpus `test_issue376_die_budget_from_a_labelled_row`
    was written against. Vetoing them would convert a silent wrong value into a
    silent missing value, which is not an improvement.
  * A markdown TABLE ROW is a self-contained record. An unrelated row in the
    same block ("| Status | not final |") must not veto the die row above it.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import floorplan_contract as F  # noqa: E402


def _die(prose: str):
    """`die_area_budget_um` for a project whose only input doc is this L9."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        docs = proj / "input" / "docs"
        docs.mkdir(parents=True)
        (docs / "L9_constraints_floorplan.md").write_text(prose, encoding="utf-8")
        return F.extract_floorplan_contract(proj).get("die_area_budget_um")


# ---------------------------------------------------------------- the defect --

def test_the_measured_case_a_removed_harness_die_is_not_a_mandate():
    """The statement that produced this test, with neutral numbers."""
    assert _die(
        "## Floorplan\n"
        "The origin project's fixed die rectangle of 2400 x 1800 um is the die of "
        "an external harness on a different process. It has NO meaning here and "
        "is REMOVED, not translated.\n"
    ) is None


def test_not_applicable_die_is_not_a_mandate():
    assert _die("## Floorplan\nDie size 3000 x 3000 um is NOT APPLICABLE on "
                "this process.\n") is None


def test_negated_die_area_rect_is_not_a_mandate():
    """The keyword form is guarded too, not only the labelled W x H form."""
    assert _die(
        "## Floorplan\nThe harness config declares DIE_AREA = [0, 0, 1800, 1400] "
        "but that mandate does not apply to this block.\n") is None


def test_a_denial_does_not_poison_a_later_affirmative_statement():
    """Skip the negated match and keep reading — the #457 pdk_target doctrine."""
    assert _die(
        "## Floorplan\nThe legacy die of 5000 x 5000 um is no longer targeted.\n\n"
        "The die for this design is 1600 x 1200 um.\n") == "1600x1200"


# ------------------------------------------------- what must still be read in --

def test_plain_labelled_row_still_read():
    assert _die("## Floorplan\n| Die size | 2400 x 2400 um |\n") == "2400x2400"


def test_parenthetical_negation_is_a_qualifier_not_a_denial():
    """`test_issue376...` depends on this exact row; it must keep working."""
    assert _die("## Floorplan\n| Core die (no seal ring) | 1300 x 1300 um |\n"
                ) == "1300x1300"


def test_parenthetical_exclusion_is_a_qualifier_not_a_denial():
    assert _die("## Floorplan\nDie size 2200 x 1600 um (not including scribe "
                "lanes).\n") == "2200x1600"


def test_an_unrelated_negated_table_row_does_not_veto_the_die_row():
    assert _die("## Floorplan\n| Die size | 2400 x 2400 um |\n"
                "| Status | not final |\n") == "2400x2400"


def test_affirmative_rect_form_still_read():
    """The value lives inside brackets here, so bracket-blanking must keep it."""
    assert _die("## Floorplan\nFP_SIZING = absolute, DIE_AREA = [0, 0, 900, 700] "
                "um.\n") == "900x700"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
