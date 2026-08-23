#!/usr/bin/env python3
"""A data file that only a PROGRAM opens still reached no test (vibe-ic#1176).

WHERE #1178 STOPPED
===================
#1178 added rule 7's SECOND hop: a key is now found when a HELPER under
`programs/tests/` names it, resolved through rule 4. That closed the headline
instance of #1176 — measured on `75776dbbb`, a flow-yaml change now selects all
eight matrix dimensions, `test_matrix_d4_criteria_match` among them.

#1176 was deliberately left open for a RESIDUAL that hop does not reach, and
this file is that residual. Hop one globs `test_*.py`; hop two globs the helpers
under `programs/tests/`. Neither looks at `programs/*.py`. So a data file that
only a PROGRAM opens is invisible, and so is every test that exercises the
program through it. Measured on `75776dbbb` — a one-line edit to
`flow/phase1_phase2_phase3.yaml`, 160 files selected, and all seven of these
absent:

    test_flow_dashboard_data.py                      D._load_flow()
    test_issue492_gate_argv_conversions.py           local _load_flow()
    test_issue492_umbrella_gate_invocation.py        local _load_flow()
    test_issue559_not_a_project_gate.py              local _load_flow()
    test_issue559_polluter_conversion.py             local _load_flow()
    test_issue559_semantic_argv_gates.py             local _load_flow()
    test_si_mcf_not_run_is_not_a_design_failure.py   F.DEFAULT_FLOW_DEF

Every one reaches the flow through `flow_compliance_check.py` or
`flow_dashboard_data.py` — programs, not helpers.

THE TWO HOPS THIS ADDS
======================
1. `_build_key_source_index` — key -> source stems that hold it as a LIVE string
   literal, resolved through the same rules a direct edit of those modules takes.
   Live-literal, not lexical: 66 source modules MENTION the flow yaml (537
   dependent tests) but only 23 can open it (159). The 43 that drop out cite it
   in module docstrings — `design_one_shot_runner` has 138 import-edge
   dependents on this tree, yet its mentions remain prose-only.

2. `_LOADER_CALL_RE` — the loader edge keyed on the file LOADED, not the alias
   BOUND. `spec_from_file_location("fcc_i492_conv", … / "flow_compliance_check.py")`
   filed an edge under `fcc_i492_conv`, which matches no source stem, so it was
   dropped. Two of the seven are reachable only through this.

Neither hop alone closes the seven; the assertions below pin that.

WHAT IS **NOT** ASSERTED HERE
=============================
That the selection reaches some particular SIZE. Following #1178's reasoning: a
count is a property of the tree on the day it was written, and pinning one makes
this file fail for republication rather than for regression. What is asserted is
that each named test is REACHABLE from a flow-yaml change, that the specific edge
carries it, and that the third hop stays additive.
"""
from __future__ import annotations

import functools
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
PREFIX = "vibe-ic-marketplace/plugins/vibe-ic"

sys.path.insert(0, str(PLUGIN_ROOT / "programs"))
import ci_targeted_test_select as S  # noqa: E402

FLOW_REL = "flow/phase1_phase2_phase3.yaml"
FLOW_KEY = "phase1_phase2_phase3.yaml"

#: The residual #1176 stayed open for, with the program each reaches the flow
#: through. All seven were absent from the 160-file selection on `75776dbbb`.
RESIDUAL = {
    "programs/tests/test_flow_dashboard_data.py": "flow_dashboard_data",
    "programs/tests/test_issue492_gate_argv_conversions.py": "flow_compliance_check",
    "programs/tests/test_issue492_umbrella_gate_invocation.py": "flow_compliance_check",
    "programs/tests/test_issue559_not_a_project_gate.py": "flow_compliance_check",
    "programs/tests/test_issue559_polluter_conversion.py": "flow_compliance_check",
    "programs/tests/test_issue559_semantic_argv_gates.py": "flow_compliance_check",
    "programs/tests/test_si_mcf_not_run_is_not_a_design_failure.py":
        "flow_compliance_check",
}

#: Bound to `flow_compliance_check.py` ONLY by a `spec_from_file_location` whose
#: first argument is a private alias. Invisible to the alias-keyed edge index.
ALIAS_LOADED = [
    "programs/tests/test_issue492_gate_argv_conversions.py",
    "programs/tests/test_issue492_umbrella_gate_invocation.py",
]


@functools.lru_cache(maxsize=None)
def _select_cached(changed: tuple[str, ...], mode: str) -> frozenset[str]:
    """One selection per (diff, mode), reused across the cases that share it.

    `select_tests` rebuilds the import-edge index over ~2.5k test files on every
    call — ~10 s. Seven parametrized cases asking the same question of the same
    diff paid that seven times (127 s for this file). The cache is keyed on the
    exact arguments, so each distinct question is still really asked; nothing is
    shared between two different diffs or two different modes.
    """
    return frozenset(S.select_tests([f"{PREFIX}/{c}" for c in changed],
                                    PLUGIN_ROOT, plugin_prefix=PREFIX,
                                    mode=mode))


def _select(*changed, mode=S.MODE_IMPORT_EDGE):
    """Select in the mode the CI GATE actually runs.

    `select_tests`'s own default is `ownership`; the CLI's is `import-edge`, and
    the CLI is what the gate invokes. The residual below is reachable only along
    a dependency edge, so measuring it in `ownership` would measure a mode that
    declines dependency edges by construction and report a fix as absent. The
    mode is therefore stated here rather than inherited — see
    `test_ownership_mode_still_declines_dependency_edges`, which pins that the
    narrow mode stays narrow.
    """
    return set(_select_cached(tuple(changed), mode))


# ===========================================================================
# THE DEFECT — behavioural, on the real tree
# ===========================================================================
@pytest.mark.parametrize("test_rel,via", sorted(RESIDUAL.items()))
def test_a_flow_yaml_change_reaches_its_program_side_readers(test_rel, via):
    """THE RESIDUAL. Each of these reads the flow through a PROGRAM.

    The failure message names the mechanism rather than the count, so a
    regression here reads as "the third hop stopped carrying X" and not as
    "some number moved".
    """
    assert (PLUGIN_ROOT / test_rel).is_file(), f"{test_rel} vanished; re-measure"
    selected = _select(FLOW_REL)
    assert test_rel in selected, (
        f"a flow-yaml change did not select {test_rel}; "
        f"{len(selected)} file(s) selected. It reaches the flow through "
        f"{via}.py — a program, not a tests/ helper — so hops one and two "
        f"cannot see it and only the third hop can.")


# ===========================================================================
# THE MECHANISM — each hop pinned separately, so a partial revert is named
# ===========================================================================
def test_the_third_hop_finds_the_programs_that_can_open_the_flow():
    """Hop 3 itself: the key resolves to the two programs that read the flow."""
    idx = S._build_key_source_index(
        PLUGIN_ROOT, {FLOW_KEY}, S._source_stems(PLUGIN_ROOT))
    stems = idx.get(FLOW_KEY, set())
    for expected in sorted(set(RESIDUAL.values())):
        assert expected in stems, (
            f"{expected} holds the flow path as a live literal but the third "
            f"hop did not key it; {len(stems)} stem(s) found")


def test_the_third_hop_excludes_modules_that_only_CITE_the_flow():
    """The live-literal discriminator, which is what makes hop 3 affordable.

    `design_one_shot_runner` names the yaml in prose only and carries 138
    import-edge dependents on this tree. A lexical hop would select all of them
    for a change it cannot observe. This is the assertion that keeps hop 3 from
    becoming the blast radius #1176 warned about.
    """
    src = (PLUGIN_ROOT / "programs" / "design_one_shot_runner.py").read_text(
        encoding="utf-8", errors="replace")
    pat = S._tool_ref_pattern(FLOW_KEY)
    assert pat.search(src), (
        "design_one_shot_runner no longer mentions the flow yaml at all; this "
        "test's premise is stale — pick another prose-only citer or drop it")
    assert not S._names_key_as_live_literal(src, pat), (
        "design_one_shot_runner now holds the flow path as a live literal. If "
        "that is deliberate the module really can open the flow and this test "
        "should be re-pointed; if not, the discriminator has broken open.")

    idx = S._build_key_source_index(
        PLUGIN_ROOT, {FLOW_KEY}, S._source_stems(PLUGIN_ROOT))
    assert "design_one_shot_runner" not in idx.get(FLOW_KEY, set())


def test_a_loader_edge_is_keyed_on_the_file_loaded_not_the_alias_bound():
    """Hop 3 alone leaves two of the seven unreachable; this is why.

    Asserted on the index rather than on the selection so that a regression
    distinguishes "the alias fix went" from "the third hop went".
    """
    idx = S._build_import_edge_index(PLUGIN_ROOT, S._source_stems(PLUGIN_ROOT))
    consumers = idx.get("flow_compliance_check", set())
    for rel in ALIAS_LOADED:
        assert rel in consumers, (
            f"{rel} loads flow_compliance_check.py under a private alias and "
            f"the edge index did not record it; {len(consumers)} consumer(s). "
            f"Keying on argument one drops exactly this shape.")


# ===========================================================================
# THE LANES THAT MUST NOT MOVE
# ===========================================================================
def test_the_third_hop_is_purely_additive():
    """It may only ADD. Everything hops 1-2 selected must survive."""
    selected = _select(FLOW_REL)
    smoke = set(S._smoke_set(PLUGIN_ROOT))
    assert smoke <= selected, "the smoke floor is no longer a floor"
    # The dimensions #1178 bought must still be there.
    for d in ("d4_criteria_match", "d6_skip_discipline", "d7_outputs_list_complete"):
        rel = f"programs/tests/test_matrix_{d}.py"
        assert rel in selected, f"third hop displaced {rel}, a hop-2 selection"


def test_ownership_mode_still_declines_dependency_edges():
    """The narrow mode must stay narrow — the third hop respects `--mode`.

    Hop 3 resolves its stems through the same per-mode rules a direct edit of
    those modules takes, so `ownership` gets a stem's OWNED tests and nothing
    more. Pinned because the tempting shortcut — always resolving hop 3 by
    import edge — would silently make the opt-in narrowing stop narrowing, and
    nothing else in the suite would notice.
    """
    edge_only = [rel for rel, _ in RESIDUAL.items()
                 if rel != "programs/tests/test_flow_dashboard_data.py"]
    narrow = _select(FLOW_REL, mode=S.MODE_OWNERSHIP)
    wide = _select(FLOW_REL, mode=S.MODE_IMPORT_EDGE)
    for rel in edge_only:
        assert rel in wide, f"{rel} unreachable even in import-edge mode"
        assert rel not in narrow, (
            f"{rel} is reachable only along an import edge, yet `ownership` "
            f"selected it — hop 3 is ignoring the mode it was given")


def test_a_mapped_source_change_does_not_pay_for_the_third_hop():
    """Hop 3 is lazy: no unmapped path in the diff, no index built.

    Guards the cost argument rules 4, 6 and 7 all rest on — the common case
    (a change under `programs/`) must still read nothing extra.
    """
    calls = []
    real = S._build_key_source_index
    S._build_key_source_index = lambda *a, **k: (calls.append(a), real(*a, **k))[1]
    try:
        # Deliberately NOT through `_select`: a cached answer would never reach
        # the patched function, and the test would pass by not running.
        S.select_tests([f"{PREFIX}/programs/flow_compliance_check.py"],
                       PLUGIN_ROOT, plugin_prefix=PREFIX,
                       mode=S.MODE_IMPORT_EDGE)
    finally:
        S._build_key_source_index = real
    assert not calls, (
        "the third hop's index was built for a diff with no unmapped path; "
        "it must stay lazy or every source change pays to parse the tree")
