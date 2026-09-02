#!/usr/bin/env python3
"""Three gates answered rc 0 without saying what they had looked at.

`gate_discloses_denominator_check` drives every `programs/*_check.py` against
two fixtures — a structurally EMPTY project, and a project path that DOES NOT
EXIST — and requires that a PASS there DISCLOSE its population (#511, #564).
MEASURED at 20031834c1 it returned 3 findings over 594 gates::

    [PASS_WITHOUT_DENOMINATOR]        crosslayer_rewrite_equivalence_check
    [PASS_WITHOUT_DENOMINATOR]        project_outputs_in_tree_check
    [PASS_ON_A_PROJECT_THAT_IS_NOT_THERE]
                                      on_pass_review_declared_command_runs_check

Each stated its FINDING and never its SCOPE, and the two are not the same
sentence:

    crosslayer_rewrite_equivalence_check   `PASS (no-op) — no cross-layer
        search was run.` True of a design whose search was audited clean, and
        equally true of a directory with nothing in it.
    project_outputs_in_tree_check          `no /tmp ... paths referenced in
        RESULT.md / waivers.json / reports/ / generated_docs/`. A statement
        about what was NOT FOUND, with no count of what was OPENED — and the
        count was zero.
    on_pass_review_declared_command_runs_check   answers about the FLOW and
        the published trees and never opens the `project_dir` positional at
        all. That is correct, and it is exactly why it must say so: rc 0 for a
        path that does not exist is otherwise indistinguishable from rc 0 for
        a clean chip, and the clean answer is the one that gets acted on.

WHY THIS FILE EXISTS ALONGSIDE `test_issue511_empty_project_pass_disclosure`.
That file drives the census and asserts the whole population is clean; when it
goes red it says "3 finding(s) over 594 gate(s)" and the three names are
findings in a list. This one NAMES them, so a regression in any one of them is
a test with that gate's name on it rather than a number that moved.

THE PREDICATES ARE THE STANDING CHECK'S OWN, imported and run. A retyped regex
here would be a second discriminator that agrees with the first today and
stops agreeing the day either is tuned.

LATER (#619): `project_outputs_in_tree_check` no longer answers rc 0 over an
empty project at all — it refuses (rc 2). Disclosing the zero was this file's
subject and was the right fix for it; a SECOND finding, from
`gate_zero_denominator_refuses_check`, was that the zero should not have been
an exit-0 verdict in the first place, because the P0 umbrella aggregates exit
codes and never the prose. See `_EMPTY_PROJECT_RC` below.
"""
import os
import pathlib
import subprocess
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

import gate_discloses_denominator_check as G  # noqa: E402

GATES = (
    "crosslayer_rewrite_equivalence_check",
    "project_outputs_in_tree_check",
    "on_pass_review_declared_command_runs_check",
)


def _drive(gate, project_arg, cwd):
    r = subprocess.run(
        [sys.executable, str(_PROGRAMS / f"{gate}.py"), project_arg],
        cwd=cwd, capture_output=True, text=True, timeout=900)
    return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()


def _empty_project(tmp_path):
    """The standing check's own fixture shape: the two directories a project
    always has, and nothing in either of them."""
    (tmp_path / "input" / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
    return tmp_path


# ---------------------------------------------------------------------------
# RED before the fix, GREEN after
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("gate", GATES)
def test_a_pass_over_an_empty_project_states_what_was_examined(gate, tmp_path):
    rc, out = _drive(gate, ".", str(_empty_project(tmp_path)))
    if rc != 0:
        pytest.skip(f"{gate} does not answer rc 0 over an empty project "
                    f"(rc={rc}); this rule asks only about rc 0")
    assert G.discloses(out), (
        f"{gate} passed over a project with nothing in it and its output is "
        f"indistinguishable from a real clean run:\n{out}")


@pytest.mark.parametrize("gate", GATES)
def test_a_pass_over_a_project_that_is_not_there_says_nothing_was_opened(gate):
    rc, out = _drive(gate, G._ABSENT, os.sep)
    if rc != 0:
        return          # rc 1 or rc 2 are both answers; only rc 0 is judged
    assert G._honest_about_an_absent_project(out), (
        f"{gate} returned success for a path that does not exist without "
        f"disclosing that nothing was opened:\n{out}")


# ---------------------------------------------------------------------------
# UNCHANGED in both directions
# ---------------------------------------------------------------------------
#: The verdict each of the three gives over a structurally EMPTY project, and
#: WHY — so that a change to any of them is an edit here rather than a number
#: that moved.
#:
#: #619 MOVED ONE OF THEM, deliberately and as its own measured change — which
#: is exactly what the rule below demands. The original rule was "a DISCLOSURE
#: fix must not smuggle in a verdict change", and it still is: what it forbids
#: is changing a verdict under a #511 label, not changing one on the evidence.
#: `gate_zero_denominator_refuses_check` then drove the same population and
#: reported `project_outputs_in_tree_check` as ZERO_DENOMINATOR_EXITS_ZERO —
#: a separate finding, separately argued, separately measured (196 real run
#: trees, 0 affected) — and the gate now refuses instead of passing. Recording
#: the new verdict HERE, per gate, keeps this a pin in both directions: the two
#: gates whose verdict did not move still may not move, and the one that did
#: may not drift back to a silent 0.
_EMPTY_PROJECT_RC = {
    "crosslayer_rewrite_equivalence_check": 0,
    # #619 — its subject IS "outputs written outside the tree", so an empty
    # canonical tree is that condition's strongest symptom. It cannot vouch
    # for a project it never opened a declaration file in.
    "project_outputs_in_tree_check": 2,
    "on_pass_review_declared_command_runs_check": 0,
}


@pytest.mark.parametrize("gate", GATES)
def test_the_verdict_did_not_move_only_the_disclosure(gate, tmp_path):
    """A disclosure is added TO a verdict, never INSTEAD of one — a #511-label
    change may not carry a verdict change with it. The expected verdict per
    gate is `_EMPTY_PROJECT_RC`; moving one is an edit to that table with a
    reason, never a silent drift."""
    rc, out = _drive(gate, ".", str(_empty_project(tmp_path)))
    assert rc == _EMPTY_PROJECT_RC[gate], out


@pytest.mark.parametrize("gate", GATES)
def test_none_of_the_three_was_silenced_by_the_exemption_inventory(gate):
    """THE OTHER WAY TO MAKE THE CENSUS GREEN, and it is not a fix.

    `_EMPTY_PROJECT_SILENT_PASS` is a visible list that cannot grow without an
    edit; that is what makes it honest and also what makes it tempting. These
    three were answerable, so they were answered.
    """
    assert gate not in G._EMPTY_PROJECT_SILENT_PASS, (
        f"{gate} was recorded as a known silent pass instead of being made to "
        "state its population")
