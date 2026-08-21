#!/usr/bin/env python3
"""Rule 7 found a data file only when a TEST named it, never when a HELPER did.

WHAT #1068 FIXED, AND WHERE IT STOPPED
======================================
#1068 stopped `select_tests` from silently dropping every path outside
`programs/`: an unmapped path now reaches `_build_tool_reference_index` and
selects the tests that NAME it. Measured on `a38902d1`, a change to
`flow/phase1_phase2_phase3.yaml` went from the 16-file smoke floor to **128**
files. Real progress.

But that index globs ``test_*.py``, so a data file is reachable only when a
TEST names it literally — and the one test whose failure proves the hole does
not:

    grep -c phase1_phase2_phase3.yaml test_matrix_d4_criteria_match.py   -> 0
    grep -c phase1_phase2_phase3.yaml matrix_63x8/flowref.py             -> 3

`test_matrix_d4_criteria_match` reaches the flow through
``from matrix_63x8 import flowref``. So on `a38902d1` a flow-yaml change
selects 128 files and **d4 is not one of them** — the dimension that measures
flow-yaml correctness is the one a flow-yaml change does not run. That is not
hypothetical: `test_matrix_d4_criteria_match[step1]` was red on main all day,
and the fix for it (#1131) edits the flow yaml.

THE HOP THIS ADDS
=================
Find the HELPERS that name the key, and hand them to `_helper_consumers` —
rule 4, which already owns helper -> importing-test resolution. Composing
rather than re-deriving means this cannot drift from rule 4.

WHAT IS **NOT** ASSERTED HERE
=============================
That the selection reaches some particular SIZE. A count is a property of the
tree on the day it was written; it rots, and pinning it would make this file
fail for republication rather than for regression. The assertions are: d4 is
reachable from a flow-yaml change, the helper edge is what carries it, and the
lanes that must not change do not.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
PREFIX = "vibe-ic-marketplace/plugins/vibe-ic"

sys.path.insert(0, str(PLUGIN_ROOT / "programs"))
import ci_targeted_test_select as S  # noqa: E402

FLOW_REL = "flow/phase1_phase2_phase3.yaml"
D4 = "programs/tests/test_matrix_d4_criteria_match.py"


def _select(*changed):
    return set(S.select_tests([f"{PREFIX}/{c}" for c in changed],
                              PLUGIN_ROOT, plugin_prefix=PREFIX))


def _smoke():
    return set(S._smoke_set(PLUGIN_ROOT))


# ===========================================================================
# THE RULE
# ===========================================================================
def test_a_flow_yaml_change_reaches_the_dimension_that_recomputes_from_it():
    """THE DEFECT. d4 rebuilds itself from the flow yaml on every run."""
    got = _select(FLOW_REL)
    assert D4 in got, (
        f"a flow-yaml change did not select {D4}; {len(got)} file(s) selected. "
        f"d4 recomputes from that yaml, so this is the dimension a flow-yaml "
        f"change most needs to run.")


def test_the_HELPER_edge_is_what_carries_it():
    """PREMISE, and the reason one hop was not enough.

    If d4 ever names the yaml directly this still passes — but the helper edge
    is what carries it today, and that is the thing #1068's index cannot see.
    """
    idx = S._build_key_helper_index(PLUGIN_ROOT, {"phase1_phase2_phase3.yaml"})
    helpers = idx.get("phase1_phase2_phase3.yaml", set())
    assert helpers, "no helper names the flow yaml — re-derive this rule"
    assert any(h.startswith("programs/tests/matrix_63x8/") for h in helpers), (
        f"the matrix helper no longer names the flow yaml; got {sorted(helpers)}")
    d4_text = (PLUGIN_ROOT / D4).read_text(errors="replace")
    assert "phase1_phase2_phase3.yaml" not in d4_text, (
        "d4 now names the yaml directly — the two-hop claim needs re-deriving, "
        "not deleting")


def test_the_helper_index_returns_helpers_and_never_tests():
    """The two hops must stay separate. If this index started returning
    `test_*.py` they would double-count, and a bug in hop 2 would be masked by
    hop 1 silently covering for it."""
    idx = S._build_key_helper_index(PLUGIN_ROOT, {"phase1_phase2_phase3.yaml"})
    for hits in idx.values():
        for h in hits:
            assert not Path(h).name.startswith("test_"), h
            assert S._is_test_helper(h), h


def test_the_helper_index_MATCHES_rather_than_returning_every_helper():
    """The assertion an always-fires mutant demanded.

    Two earlier mutants SURVIVED this file and both survivals were my fault:
      * dropping the `test_*.py` skip is inert, because `_is_test_helper`
        filters those anyway;
      * making the index ignore the pattern was never exercised, because the
        only negative control used a path that does not exist, so
        `_distinctive_key` returned nothing and `keys` was empty — the mutated
        code never ran.

    So nothing here pinned that the index MATCHES. "Return every helper" would
    have passed, which is a ban wearing a check. This asserts the discrimination
    directly: a real key must select the helpers that name it and NOT the ones
    that do not.
    """
    idx = S._build_key_helper_index(PLUGIN_ROOT, {"phase1_phase2_phase3.yaml"})
    hit = idx.get("phase1_phase2_phase3.yaml", set())
    assert hit, "the key matched no helper at all"

    all_helpers = {
        f"programs/tests/{q.relative_to(PLUGIN_ROOT / 'programs/tests').as_posix()}"
        for q in (PLUGIN_ROOT / "programs" / "tests").rglob("*.py")
        if not q.name.startswith("test_")
    }
    unmatched = all_helpers - hit
    assert unmatched, (
        f"the index returned EVERY helper ({len(hit)} of {len(all_helpers)}) — "
        f"it is not matching, it is selecting everything")
    # ...and prove the exclusion is real: pick one it left out and confirm the
    # key genuinely does not occur in it.
    for cand in sorted(unmatched):
        txt = (PLUGIN_ROOT / cand).read_text(errors="replace")
        if "phase1_phase2_phase3.yaml" not in txt:
            break
    else:                                            # pragma: no cover
        pytest.fail("every excluded helper names the key — exclusion is fake")


# ===========================================================================
# NEGATIVE CONTROLS — lanes that must not move
# ===========================================================================
def test_a_python_source_change_is_unaffected():
    """Rule 7 is the unmapped-path lane; a `.py` change must not gain anything
    from this hop."""
    got = _select("programs/flow_compliance_check.py")
    assert "programs/tests/test_flow_compliance_check.py" in got
    assert len(got) > len(_smoke())


def test_the_selection_is_never_empty():
    """The floor invariant, re-asserted because this change touches the
    unmapped-path resolution that runs just before the return."""
    assert _select() == _smoke()


def test_an_unmapped_path_that_nothing_names_is_still_the_floor():
    """The rule must fire on a stated dependency, not on any unknown path.
    Without this, 'select more' passes the headline assertion."""
    got = _select("flow/zzz_no_such_file_names_this.yaml")
    assert got == _smoke(), (
        f"an unreferenced data path selected {len(got)} files, not the floor")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
