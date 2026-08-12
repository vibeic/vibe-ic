#!/usr/bin/env python3
"""A flow-yaml change selected the smoke floor and nothing else.

THE HOLE
========
`select_tests` drops every changed path that is not `.py`::

    if not rel.endswith(".py"):
        continue

so `flow/phase1_phase2_phase3.yaml` — the canonical 44-step flow that
`flow_compliance_check.py` enforces, and that the whole 63x8 matrix recomputes
itself from on every run — reached no rule at all. MEASURED on `947547716`:
touching the flow yaml selected **16** files, the smoke floor, and none of the
dimensions that measure flow-yaml correctness.

FOUND THE EXPENSIVE WAY. While fixing `test_matrix_d4_criteria_match[step1]`
the change edited the flow yaml, the selection did not contain the d4 file, and
the fix was verified only because the failing test was run BY HAND.

This is a DIFFERENT hole from vibe-ic#1057/Rule 6, which reaches repo-ROOT tool
scripts. Neither subsumes the other: the flow yaml is inside the plugin, and
`tools/gatekeeper-land.sh` is not a plugin data file.

WHY TWO HOPS
============
`test_matrix_d4_criteria_match.py` does NOT contain the string
`phase1_phase2_phase3.yaml`. It reaches the flow through
`from matrix_63x8 import flowref`, and the path lives in
`programs/tests/matrix_63x8/flowref.py:203`. A direct-mention index alone took
the selection 16 -> 131 and STILL missed the one test whose failure prompted
the rule — a fix that looks right and does not fix the subject. The second hop
composes with rule 4 (`_helper_consumers`) rather than re-deriving it, so it
cannot drift from the rule that already owns helper->test resolution.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
SELECT = PLUGIN_ROOT / "programs" / "ci_targeted_test_select.py"
FLOW_YAML = PLUGIN_ROOT / "flow" / "phase1_phase2_phase3.yaml"

sys.path.insert(0, str(PLUGIN_ROOT / "programs"))
import ci_targeted_test_select as S  # noqa: E402


def _select(changed):
    """Run the shipped selector over an explicit changed-path list."""
    return set(S.select_tests(list(changed), PLUGIN_ROOT,
                              plugin_prefix="vibe-ic-marketplace/plugins/vibe-ic"))


def _smoke():
    return set(S._smoke_set(PLUGIN_ROOT))


# ===========================================================================
# THE RULE
# ===========================================================================
def test_a_flow_yaml_change_reaches_the_matrix_that_reads_it():
    """THE DEFECT, on the case that found it.

    d4 recomputes itself from the flow yaml on every run; a change to that yaml
    must select it. Before this rule the selection was the smoke floor.
    """
    got = _select(["vibe-ic-marketplace/plugins/vibe-ic/flow/"
                   "phase1_phase2_phase3.yaml"])
    d4 = "programs/tests/test_matrix_d4_criteria_match.py"
    assert d4 in got, (
        f"a flow-yaml change did not select {d4}; selected {len(got)} file(s). "
        f"This is the exact miss that let a flow-yaml fix be verified by a "
        f"selection that never ran the dimension measuring flow-yaml "
        f"correctness.")
    assert len(got) > len(_smoke()), "selection is still the smoke floor"


def test_the_second_hop_is_what_reaches_it():
    """The yaml is named by a HELPER, not by the test.

    Pins the reason the one-hop version failed: if `test_matrix_d4…` ever
    starts naming the yaml directly this still passes, but the helper edge is
    what carries it today and this states so.
    """
    idx = S._build_data_reference_index(
        PLUGIN_ROOT, {"phase1_phase2_phase3.yaml"})
    namers = idx.get("phase1_phase2_phase3.yaml", set())
    assert any(n.startswith("programs/tests/matrix_63x8/") for n in namers), (
        f"no matrix_63x8 helper names the flow yaml; namers={sorted(namers)[:5]}")
    d4 = "programs/tests/test_matrix_d4_criteria_match.py"
    assert d4 not in namers, (
        "d4 now names the yaml directly — the two-hop claim above needs "
        "re-deriving, not deleting")


# ===========================================================================
# NEGATIVE CONTROLS — the rule must not fire on everything
# ===========================================================================
def test_a_docs_only_change_is_STILL_the_smoke_floor():
    """The control that makes the rule a check rather than 'select more'.

    `.md` is deliberately outside `_DATA_SUFFIXES`: every skill is a `.md`,
    prose changes constantly, and a doc edit selecting 100+ files makes the
    selector something people route around.
    """
    got = _select(["vibe-ic-marketplace/plugins/vibe-ic/README.md"])
    assert got == _smoke(), (
        f"a docs-only change selected {len(got)} files, not the smoke floor "
        f"({len(_smoke())})")


def test_a_data_file_OUTSIDE_the_declared_dirs_does_not_fire():
    """Scoped to `_DATA_DIRS`. A json anywhere in the tree firing this rule
    would make every fixture edit select 100+ files."""
    got = _select(["vibe-ic-marketplace/plugins/vibe-ic/programs/tests/"
                   "fixtures/matrix_d3_output_manifest.json"])
    assert got == _smoke(), f"a fixture json fired rule 7; selected {len(got)}"


def test_a_python_change_is_unaffected_by_this_rule():
    """Regression control: rule 7 must add nothing to a `.py` lane."""
    got = _select(["vibe-ic-marketplace/plugins/vibe-ic/programs/"
                   "flow_compliance_check.py"])
    assert "programs/tests/test_flow_compliance_check.py" in got
    # ...and it is not the smoke floor either, i.e. the existing rules still run
    assert len(got) > len(_smoke())


def test_the_selection_is_never_empty():
    """The floor invariant the module docstring states, re-asserted here since
    rule 7 touches the loop that builds the selection."""
    assert _select([]) == _smoke()
    assert _select(["some/unrelated/path.txt"]) == _smoke()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
