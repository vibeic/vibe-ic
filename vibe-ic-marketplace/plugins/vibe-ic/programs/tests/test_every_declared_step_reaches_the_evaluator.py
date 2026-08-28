"""A step that stops reaching the evaluator must be reported by name.

Measured on the 68x9 matrix (mutation probe, plugin v1.12.33): removing what
hands the executor its gate dict for step 21 left dimension D1 green -- 86
passed -- because D1's observation point is inside `_evaluate_gate` and the
test supplies the caller. On a real project the step vanished from the tally,
MISSING dropped 40 -> 39, and 18 blocked steps silently unblocked.

The can-fail arm below performs that mutation on a real tree: the SUBJECT's
own evaluator is replaced by one that drops a step, and the gate must name it.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

import every_declared_step_reaches_the_evaluator_check as G

_PROGRAMS = Path(G.__file__).resolve().parent
_ROOT = _PROGRAMS.parents[3]
_SEAM = 'steps = flow.get("steps", [])'


def _subject_tree(tmp_path: Path, drop: str) -> Path:
    """A subject tree identical to this one but for an evaluator that drops `drop`.

    Everything is symlinked except the evaluator, which is a real, patched
    file: the point is to change ONE thing and keep every other input the same,
    so a difference in the verdict can only come from the mutation.
    """
    plugin = tmp_path / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    plugin.mkdir(parents=True)
    real_plugin = _PROGRAMS.parent
    for child in real_plugin.iterdir():
        if child.name != "programs":
            os.symlink(child, plugin / child.name)
    programs = plugin / "programs"
    programs.mkdir()
    for child in _PROGRAMS.iterdir():
        if child.name != "flow_compliance_check.py":
            os.symlink(child, programs / child.name)
    text = (_PROGRAMS / "flow_compliance_check.py").read_text(encoding="utf-8")
    assert text.count(_SEAM) == 1, "the seam this mutation edits has moved"
    patched = text.replace(
        _SEAM,
        _SEAM + f'\n    steps = [s for s in steps if str(s.get("id")) != "{drop}"]')
    (programs / "flow_compliance_check.py").write_text(patched, encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------- can PASS --
def test_this_tree_reaches_every_step_it_declares():
    report = G.audit(_ROOT)
    assert report["unreached"] == [], report["unreached"]
    assert report["uninvited"] == [], report["uninvited"]
    assert report["declared"] == report["evaluated"] > 1


# ---------------------------------------------------------------- can FAIL --
def test_the_measured_mutation_names_the_step(tmp_path):
    """MUT-B: the evaluator stops receiving step 21."""
    root = _subject_tree(tmp_path, "21")
    report = G.audit(root)
    assert report["unreached"] == ["21"], report
    assert report["evaluated"] == report["declared"] - 1


def test_the_mutation_is_reported_through_the_exit_code(tmp_path):
    root = _subject_tree(tmp_path, "21")
    assert G.main(["--root", str(root)]) == 1


# ------------------------------------------------------------- fail-safe ----
def test_a_tree_with_no_flow_is_cannot_check_not_pass(tmp_path):
    assert G.main(["--root", str(tmp_path)]) == 2


def test_a_tree_with_no_evaluator_is_cannot_check_not_pass(tmp_path):
    flow = tmp_path / G.FLOW_REL
    flow.parent.mkdir(parents=True)
    flow.write_text("steps:\n  - id: '1'\n")
    assert G.main(["--root", str(tmp_path)]) == 2
