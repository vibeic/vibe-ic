#!/usr/bin/env python3
"""Tests for real_artefact_test_backing_check (vibe-ic#400).

A change whose tests are all synthetic fixtures authored alongside it cannot
distinguish itself from its own absence. This classifier reports the split.

Every case is paired: a classifier that called everything SYNTHETIC would
satisfy the headline case, and one that called everything REAL would satisfy
its inverse. Only both together say anything.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))






















def test_the_skill_no_longer_pushes_authors_to_a_synthetic_suite():
    """Criterion 4 said fixtures must be synthesised neutral data, full stop.
    Read literally that produces the 100%-synthetic suite this program
    reports on, so the two would contradict each other."""
    doc = (_PROGRAMS.parent / "skills" / "flow-change-acceptance"
           / "SKILL.md").read_text()
    assert "cannot distinguish\nitself from its own absence" in doc \
        or "cannot distinguish" in doc
    assert "require_repo" in doc
    assert "real_artefact_test_backing_check" in doc


# --------------------------------------------------------------------------- #
# The zero-backed NOTE asserted more than the program measured.
#
# MEASURED, on a real branch: a pad-ring suite of 90 tests scored `0 of 90`
# and was told "every test in this change is a fixture authored alongside it".
# Three of those tests iterate the host's INSTALLED PDK trees — naming no PDK,
# foundry or library, and skipping honestly where none is present. That is not
# a fixture authored alongside the change, and it is not a checked-in artefact
# either; it is a third thing this program cannot see.
#
# The COUNT is not the defect and is not changed here: under-claiming is the
# decided design choice (see _GIT_REPO_READS), because over-claiming "real" is
# what lets a fixture-only change look backed. The defect is the sentence — a
# conservative measurement licenses a question, not a conclusion.
# --------------------------------------------------------------------------- #
