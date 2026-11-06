#!/usr/bin/env python3
"""The surviving runner row refuses unknown verdict words at construction."""
from __future__ import annotations

import sys

import pytest

from _plugin_tree import plugin_path

sys.path.insert(0, str(plugin_path() / "programs"))

import verdict as V  # noqa: E402



@pytest.fixture(scope="module")
def agg():
    """The real runner's surviving row type, imported not copied."""
    import design_one_shot_runner as D  # noqa: PLC0415 — heavy, module-scoped
    return D.StepResult




# ── the catch-all is gone BY CONSTRUCTION ────────────────────────────────

def test_an_unknown_status_cannot_reach_the_aggregator_at_all(agg):
    """The replacement for "an unknown status is reported, not absorbed".

    It is not reported, because it cannot be built: the row refuses it.
    """
    SR = agg
    with pytest.raises(V.UnknownVerdictWord):
        SR("b", "SOME_NEW_STATUS")


def test_the_deleted_word_this_file_was_written_about_is_refused(agg):
    """`SKIP` — 118 sites in this runner, and the one that reached the
    catch-all. It is not a status any more."""
    SR = agg
    with pytest.raises(V.UnknownVerdictWord):
        SR("lec", "SKIP")




# ── the roll-up, in both directions ──────────────────────────────────────
