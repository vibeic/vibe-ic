#!/usr/bin/env python3
"""A denial written AFTER a family name still denies it. vibe-ic#2071.

`phase1_doc_one_shot_runner._declared_pdk_alternates` consulted polarity over
the 24 characters BEFORE the name and nothing after it, so a design's
own target row could deny a process and have it co-declared anyway:

    gf180mcu is the target and sky130 is not used   ->  ['gf180mcu', 'sky130']

`submission_template_fetch.declared_pdk_families` publishes that list as "the
families the design NAMES", and `family_named_by_design` then ACCEPTS a run on
a process the row denied in the same breath — fetching one operator's terms for
a process the design said it does not target. This is the loud direction of the
same defect `_prose_polarity` was written for (#706 / #711).

The reach is now `_prose_polarity.sentence_scope`, the tree's one rule for what
text a denial governs, with `extra_breaks=("|",)` because a MARKDOWN TABLE CELL
is a field rather than a clause — five of the six benchmark designs' real L1
target rows are pipe tables carrying no sentence punctuation at all, so without
a cell break a denial in an unrelated cell retracts a family this cell
declares. That direction is the SILENT one, so it is pinned here too.

BOTH DIRECTIONS. Every assertion below is written to FAIL against the pre-fix
look-back; `test_the_look_back_window_is_gone` states that structurally, and
the behavioural tests were measured red with the old span restored.

chip-AGNOSTIC: the fixtures name open PDKs (the public namespace the flow's own
registry already carries) and pipe-table syntax. No chip, foundry SKU, node or
design literal appears here.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import phase1_doc_one_shot_runner as p1              # noqa: E402
import submission_template_fetch as stf              # noqa: E402


def _design(tmp_path: Path, row: str) -> Path:
    """A project whose input docs are exactly one target row."""
    docs = tmp_path / "input" / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L1_product_metadata.md").write_text(row + "\n", encoding="utf-8")
    return tmp_path


def _families(project: Path) -> list:
    """What the real consumer publishes.

    `_declared_pdk_alternates` returns `[]` for "the row names nothing BESIDES
    the adopted target", and the caller carries the adopted target on its own.
    Asserting at the caller is what makes "none" and "the target alone"
    distinguishable — at the function alone both are `[]`.
    """
    return list(stf.declared_pdk_families(project)["families"])


# ---------------------------------------------------------------------------
# (1) a denial AFTER the name denies it — the defect
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("row", [
    "gf180mcu is the target and sky130 is not used",
    "gf180mcu is the target. sky130 is not used",
    "target: gf180mcu, with sky130 excluded",
    "| target PDK | gf180mcu is the target and sky130 is not used |",
])
def test_a_denied_family_is_not_co_declared(tmp_path: Path, row: str) -> None:
    """Each of these yielded ['gf180mcu', 'sky130'] before #2071."""
    assert _families(_design(tmp_path, row)) == ["gf180mcu"], row


# A MEASURED RESIDUAL, ASSERTED AT THE HALF #2071 OWNS.
#
# `_extract_pdk_target_with_provenance`'s open-PDK tier — a DIFFERENT function,
# 150 lines below — still carries the same 24-character look-back, so when the
# denied name is the row's FIRST name-list match it is adopted as `pdk_target`
# itself:
#
#     "sky130 is not used and gf180mcu is the target"  ->  pdk_target = sky130
#
# That is a wider blast radius than #2071 (phase 3 sizes and gates on
# `pdk_target`) and is reported separately rather than widened into here. What
# #2071 owns is asserted directly: handed the target the row actually declares,
# the co-declaration reader denies the family the row denies. The row is NOT
# pinned at the caller, because pinning today's wrong `families` would block
# the residual's own fix.

@pytest.mark.parametrize("row", [
    "sky130 is not used. gf180mcu is the target",
    "sky130 is not used and gf180mcu is the target",
])
def test_a_denial_before_the_target_denies_that_family_too(
        tmp_path: Path, row: str) -> None:
    project = _design(tmp_path, row)
    _tok, _snip, src, line = p1._extract_pdk_target_with_provenance(project)
    # `[]` is this function's "the row names nothing BESIDES the target".
    got = p1._declared_pdk_alternates(project, src, line, "gf180mcu")
    assert got == [], row


# ---------------------------------------------------------------------------
# (2) the positive forms are unchanged — the fix must be a tightening
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("row,want", [
    ("sky130 primary, gf180mcu secondary",             ["sky130", "gf180mcu"]),
    ("targets gf180mcu and sky130 both",               ["gf180mcu", "sky130"]),
    ("| target PDK | open-source(SKY130 primary;GF180MCU secondary) |",
                                                       ["sky130", "gf180mcu"]),
    ("| target PDK family | open-source(SKY130 main,GF180MCU alternate) |",
                                                       ["sky130", "gf180mcu"]),
    ("- **Target PDK:** SKY130A (open-source sky130 130 nm)",
                                                       ["sky130a", "sky130"]),
])
def test_a_co_declaration_survives(tmp_path: Path, row: str, want) -> None:
    assert _families(_design(tmp_path, row)) == want, row


def test_a_row_that_denies_the_only_family_names_none(tmp_path: Path) -> None:
    """Unchanged by #2071, and the control that separates "none" from "one"."""
    row = "the design targets no sky130 process"
    assert _families(_design(tmp_path, row)) == []


def test_a_name_elsewhere_in_the_document_is_still_only_a_mention(
        tmp_path: Path) -> None:
    """Same-row scope is untouched: #2071 changed the reach WITHIN the row."""
    docs = tmp_path / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "spec.md").write_text(
        "| target PDK | SKY130 |\n"
        "\n"
        "Prior art was demonstrated on GF180MCU by a third party.\n",
        encoding="utf-8")
    assert _families(tmp_path) == ["sky130"]


# ---------------------------------------------------------------------------
# (3) the SILENT direction — a denial in a NEIGHBOURING CELL governs nothing
# ---------------------------------------------------------------------------
#
# Measured: with `sentence_scope` and no `extra_breaks`, both rows below lose
# `gf180mcu`, because a pipe-table row carries no sentence punctuation and the
# whole row becomes one scope. Both rows carry the STRUCTURE of the real L1
# target rows of two benchmark designs — pipe table, bracketed co-declaration,
# no sentence punctuation — with one unrelated cell appended. The real rows
# themselves, whose labels are not English, are measured against the live
# documents rather than transcribed here.

@pytest.mark.parametrize("row", [
    "| target PDK family | open-source(SKY130 main,GF180MCU alternate) "
    "| no OTP is included |",
    "| target PDK | open-source(SKY130 primary;GF180MCU secondary) "
    "| no OTP is included |",
])
def test_a_denial_in_another_cell_does_not_retract_this_cell(
        tmp_path: Path, row: str) -> None:
    assert _families(_design(tmp_path, row)) == ["sky130", "gf180mcu"], row


# ---------------------------------------------------------------------------
# (4) the structural claim, so the window cannot come back unnoticed
# ---------------------------------------------------------------------------

def test_the_look_back_window_is_gone_and_the_shared_reach_is_used() -> None:
    """A behavioural test can be satisfied by a second private matcher.

    This one says WHICH rule is consulted, so re-growing a private scope inside
    this function is caught even if it happens to agree on the fixtures above.
    """
    import inspect
    src = inspect.getsource(p1._declared_pdk_alternates)
    body = src.split('"""')[-1]                    # past the docstring
    assert "m.start() - 24" not in body, "the 24-character look-back is back"
    assert "_prose_sentence_scope(" in body, "shared reach not consulted"
    assert 'extra_breaks=("|",)' in body, "the cell break is not declared"
