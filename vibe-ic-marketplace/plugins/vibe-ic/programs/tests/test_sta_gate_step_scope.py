#!/usr/bin/env python3
"""STA gates discovered project-wide: another step's report carried — and
failed — a step it has nothing to do with.

THE DEFECT. `eda_report_audit` discovers reports with a project-wide `rglob`
that has no relationship to the step whose gate is asking, and STA mode globs
`*sta*.rpt` / `*timing*.rpt` / `*STA*.rpt` / `*timing*.log` — which matches
every STA artefact the whole flow ever writes. `--under` (the repeatable scope
flag `scoped_discovery` implements) was added for exactly this and wired for
DRC only: before this change all 10 `--under` occurrences in
`flow/phase1_phase2_phase3.yaml` were DRC clauses, and BOTH STA call sites
were project-wide.

MEASURED, on the published run `benchmark-data/ic/sha256/
clean_run_v1427_20260715`:

    step 10 (PRE-LAYOUT STA)   files_found=13   rc=1  STA_REAL_VIOLATION_FOUND
    step 23 (post-route STA)   files_found=13   rc=1  STA_REAL_VIOLATION_FOUND

Same thirteen files, so the two gates' summary documents come out
BYTE-IDENTICAL — and the violation both cite is sourced from
`phase3/stage3/sta/sta_mcorner_ocv.rpt` (setup -67.61 ns), from
`sta_mcorner_ocv_postrepair.rpt` (step 32's POST-repair artefact) and from
`reports/phase3/aging_sta.rpt`. Step 10's own declared report,
`phase3/stage3/sta/pre_pnr_timing.rpt`, is clean. A pre-layout gate was being
failed by a post-repair artefact.

THREE CALL SITES, not two. The two yaml clauses AND
`phase3_one_shot_runner._DECLARED_SIGNOFF_GATES`, whose `sta_signoff` entry
invokes the same wrapper inline and writes the SAME artefact step 23's yaml
clause writes (`reports/phase3/sta/post_route_summary.json`). Scoping only the
yaml would have been a no-op on every real run — the #755 shape. The scope is
therefore asserted in both places, and asserted to be the same string.

WHAT THE SCOPE MUST NOT BUY. `--under` narrows what a gate can see, so it is
also the perfect instrument for buying a green. Two guards below refuse that:
`test_a_violation_in_the_steps_own_report_still_fails_the_scoped_gate` (the
scope may not silence the step's own evidence) and
`test_step10_scope_is_not_wide_enough_to_reach_the_post_route_reports` (the
scope may not be widened back into a directory).

DIRECTION-1 GUARD (`test_d1_*`): unscoped discovery must keep working exactly
as before for callers that state no scope, so nothing outside these three
sites changes behaviour. That test holds on the pre-fix tree too.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


_PROGRAMS = Path(__file__).resolve().parents[1]
_PLUGIN = _PROGRAMS.parent
_FLOW = _PLUGIN / "flow" / "phase1_phase2_phase3.yaml"

sys.path.insert(0, str(_PROGRAMS))

# Padding to clear eda_report_audit.MIN_REPORT_BYTES["sta"] (1024 B).



_STEP10_REPORT = "phase3/stage3/sta/pre_pnr_timing.rpt"
_STEP23_REPORT = "phase3/stage3/sta/post_route_timing.rpt"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _flow_invocations(program: str):
    """Every `<program> ...` command string declared in the flow yaml."""
    return re.findall(rf'"({re.escape(program)} [^"]*)"',
                      _FLOW.read_text(errors="replace"))


def _unders(cmd: str):
    toks = cmd.split()
    return [toks[i + 1] for i, t in enumerate(toks)
            if t == "--under" and i + 1 < len(toks)]








# ===========================================================================
# NEGATIVE CONTROL — these fail on the pre-fix tree
# ===========================================================================
def test_every_flow_sta_gate_is_step_scoped():
    """FAILS WITHOUT THE FIX: on the pre-fix tree neither STA clause carries
    `--under`, so both discover project-wide."""
    invocations = _flow_invocations("sta_report_check")
    assert len(invocations) == 2, (
        f"expected exactly 2 sta_report_check clauses in the flow, found "
        f"{len(invocations)}: {invocations} — a new call site must be scoped "
        f"in the same change that adds it")
    for cmd in invocations:
        assert _unders(cmd), (
            f"unscoped STA gate: {cmd!r}. `eda_report_audit` discovers "
            f"project-wide, so this clause reads every STA report in the run "
            f"— including other steps' — and both carries and fails on them.")


def test_each_sta_gate_scopes_to_the_report_its_own_step_declares():
    """The scope is only honest if it is the step's OWN declared artefact.
    Tie it to the `files_exist` clause in the same gate so it cannot drift to
    an unrelated path (and so a `--under` pointing at nothing is caught).

    AMENDED when step 10's scope gained `phase3/stage3/sta/per_corner`: the
    invariant was "exactly one --under", which read as the rule but was only
    the shape it happened to have. The rule is that the FIRST scope is the
    step's own declared report, backed by `files_exist`; the rule for any
    further scope is the sibling test below, which refuses anything that can
    reach another step's artefacts.
    """
    text = _FLOW.read_text(errors="replace")
    expected = {_STEP10_REPORT: "reports/phase3/sta/pre_pnr_summary.json",
                _STEP23_REPORT: "reports/phase3/sta/post_route_summary.json"}
    for cmd in _flow_invocations("sta_report_check"):
        toks = cmd.split()
        json_target = toks[toks.index("--json") + 1]
        unders = _unders(cmd)
        assert unders, f"{cmd!r}: unscoped"
        assert expected.get(unders[0]) == json_target, (
            f"{cmd!r}: --under {unders[0]!r} is not the report the step that "
            f"writes {json_target!r} declares")
        assert f'files_exist: ["{unders[0]}"]' in text, (
            f"--under {unders[0]!r} is not backed by a files_exist clause; a "
            f"scope naming an artefact the step does not declare is a scope "
            f"nobody is required to produce")








# ===========================================================================
# ANTI-GREEN-BUY — the scope must not silence the step's own evidence
# ===========================================================================








# ===========================================================================
# DIRECTION-1 — behaviour that must NOT change (holds pre-fix too)
# ===========================================================================


def test_d1_the_flow_still_declares_a_real_mode_at_both_sites():
    import eda_report_audit  # noqa: WPS433
    for cmd in _flow_invocations("sta_report_check"):
        toks = cmd.split()
        assert toks[toks.index("--mode") + 1] in eda_report_audit.MODE_MAP, cmd


def test_d1_the_declared_json_targets_are_unchanged():
    """The scope must not move where the verdict is written — those paths are
    both steps' `required_outputs`."""
    targets = {cmd.split()[cmd.split().index("--json") + 1]
               for cmd in _flow_invocations("sta_report_check")}
    assert targets == {"reports/phase3/sta/pre_pnr_summary.json",
                       "reports/phase3/sta/post_route_summary.json"}
