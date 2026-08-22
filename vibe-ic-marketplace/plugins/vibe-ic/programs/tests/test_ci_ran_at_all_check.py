"""test_ci_ran_at_all_check.py — "no CI run" must never render as "CI passed".

WHAT WENT WRONG (vibe-ic#550)
=============================
GitHub Actions was disabled at the ACCOUNT level. The repo-level setting still
said `enabled=true`, the workflows were `active`, and the trigger blocks were
correct — so from inside the repo nothing was wrong, and **561 commits landed on
main over nine days with no CI at all**.

What made it survive nine days is that `gh run list` prints nothing when a
workflow has never run and prints nothing when a filter matched nothing. Those
two are byte-identical at the point of observation, and filtered by branch and
event — the natural way to ask "what happened to my push?" — an empty result
reads as "nothing new since the one I already saw". A maintainer read a stale
`success` line exactly that way and pushed on it.

THE PROPERTY UNDER TEST
=======================
Not "the program runs". The property is that its five outcomes are FIVE, and in
particular that PASSED and NEVER_RAN can never be confused:

    PASSED      rc 0
    FAILED      rc 1
    NEVER_RAN   rc 1   <- a finding about the commit, NOT a gap in measurement
    PENDING     rc 2
    UNREACHABLE rc 2   <- "I could not look", loud and non-blocking

NEVER_RAN is deliberately rc 1 rather than rc 2. rc 2 means the gate could not
look; here it looked and the answer was "nothing ran". Collapsing those is the
defect, one level up.

The API is stubbed rather than called: a test that needs the network would go
NOT_CHECKED in CI and prove nothing, which is the same shape again.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import ci_ran_at_all_check as C  # noqa: E402


def _stub(monkeypatch, runs, ok=True, total=None):
    def _gh(args, timeout=60):
        if not ok:
            return 1, "", "HTTP 403: Actions has been disabled for this user."
        joined = " ".join(args)
        if "per_page=1" in joined:
            return 0, json.dumps({"total_count": total if total is not None
                                  else len(runs), "workflow_runs": []}), ""
        return 0, json.dumps({"total_count": len(runs),
                              "workflow_runs": runs}), ""
    monkeypatch.setattr(C, "_gh", _gh)


_RUN_OK = {"name": "CI", "status": "completed", "conclusion": "success"}
_RUN_BAD = {"name": "CI", "status": "completed", "conclusion": "failure"}
_RUN_RUNNING = {"name": "CI", "status": "in_progress", "conclusion": None}
_RUN_NONCI = {"name": "Dependency Graph", "status": "completed",
              "conclusion": "success"}


@pytest.mark.parametrize("runs,ok,state,rc", [
    ([_RUN_OK], True, "PASSED", 0),
    ([_RUN_BAD], True, "FAILED", 1),
    ([], True, "NEVER_RAN", 1),
    ([_RUN_RUNNING], True, "PENDING", 2),
    ([], False, "UNREACHABLE", 2),
])
def test_each_outcome_has_its_own_state_and_exit_code(monkeypatch, runs, ok,
                                                      state, rc):
    _stub(monkeypatch, runs, ok)
    res = C.evaluate("o/r", "deadbeefcafe")
    assert res["state"] == state
    assert C.render(res)[0] == rc


def test_passed_and_never_ran_are_not_interchangeable(monkeypatch):
    """THE LOAD-BEARING ONE. Everything else in this module is bookkeeping if
    these two can be mistaken for each other."""
    _stub(monkeypatch, [_RUN_OK])
    good = C.render(C.evaluate("o/r", "sha1"))
    _stub(monkeypatch, [])
    none = C.render(C.evaluate("o/r", "sha1"))
    assert good[0] != none[0], "same exit code for 'passed' and 'never ran'"
    assert good[1] != none[1], "same message for 'passed' and 'never ran'"
    assert "NO CI RUN EXISTS" in none[1]


def test_a_non_ci_workflow_cannot_stand_in_for_ci(monkeypatch):
    """This repo has a Dependency Graph workflow whose runs ARE present while CI
    has none. Counting those would have made the gate green throughout the very
    outage it exists to catch — the substitution defect, one level down."""
    _stub(monkeypatch, [_RUN_NONCI])
    res = C.evaluate("o/r", "sha1")
    assert res["state"] == "NEVER_RAN", (
        "a dependency-graph run was accepted as CI having run")


def test_unreachable_says_it_could_not_look_rather_than_passing(monkeypatch):
    _stub(monkeypatch, [], ok=False)
    rc, line = C.render(C.evaluate("o/r", "sha1"))
    assert rc == 2
    assert "could not" in line.lower() and "NOT a pass" in line


def test_an_implausible_repo_history_is_reported(monkeypatch):
    """What an account-level block looks like from inside is not one missing
    run but a history that never happened."""
    _stub(monkeypatch, [_RUN_OK], total=2)
    res = C.evaluate("o/r", "sha1", min_total=50)
    assert res.get("repo_history_implausible") == 2
    rc, line = C.render(res)
    assert rc == 1 and "whole history" in line


def test_the_implausibility_check_is_off_unless_asked(monkeypatch):
    _stub(monkeypatch, [_RUN_OK], total=2)
    res = C.evaluate("o/r", "sha1")
    assert "repo_history_implausible" not in res
    assert C.render(res)[0] == 0


# --- the merge-gate policy, pinned -----------------------------------------

def test_the_merge_gate_discloses_at_every_cadence_and_blocks_at_none(
        monkeypatch, tmp_path):
    """A missing CI run must never be SILENT, and is no longer fatal anywhere.

    HISTORY, because this test used to assert the opposite half and the change
    is a policy decision rather than a bug fix. It required a milestone (FULL
    cadence) to have a GitHub Actions run, reasoning that "a milestone is the
    one landing that must not rest on a single machine's word".

    That reasoning still holds. What changed is the evidence it named: owner
    directive 2026-08-01 — GitHub is repo storage only, CI is ours. Actions is
    disabled account-wide (vibe-ic#550), so the clause blocked every future
    x.y.0 on a run that is never coming.

    Re-pointing it at our own record was considered and rejected in #570:
    `gatekeeper-land.sh` writes `.git/gatekeeper-stamp` per SHA and the pre-push
    hook enforces it, but `.git/` does not travel with a push, so that record IS
    one machine's word. Aiming the clause at it would go green on every
    milestone while satisfying none of its reason.

    So the disclosure runs at every cadence and blocks at neither, and the
    milestone summary NAMES the property that is currently unmet — a reader of
    the review record has to be able to see that the guarantee is absent, which
    is the half that must not be lost.
    """
    import gatekeeper_review as G

    def _fake(prog, args, **kw):
        return 1, "", ("[FAIL] NO CI RUN EXISTS for deadbeefc. This is not the "
                       "same as a passing run")
    monkeypatch.setattr(G, "_run_program", _fake)

    patch_gate = G.ci_ran_gate(tmp_path, "HEAD", "TARGETED")
    assert patch_gate.green is True, "a patch landing was blocked by a missing CI run"
    assert "NO CI RUN" in patch_gate.summary, (
        "the patch path went green WITHOUT saying CI never ran — silent is the "
        "one outcome this whole issue is about")

    milestone_gate = G.ci_ran_gate(tmp_path, "HEAD", "FULL")
    assert milestone_gate.green is True, (
        "the milestone block is retired (#570) — it required evidence we have "
        "decided not to produce")
    assert "NO CI RUN" in milestone_gate.summary
    assert "NOT met" in milestone_gate.summary, (
        "a milestone went green without recording that the independent-evidence "
        "property is unmet — going quiet is how the guarantee gets forgotten")
    assert "#570" in milestone_gate.summary, (
        "the summary must name where the decision is recorded, or the next "
        "reader re-derives it")


def test_the_milestone_gate_does_not_read_the_local_stamp():
    """The trap #570 names, pinned as a property of the source.

    `.git/gatekeeper-stamp` is a per-SHA record that exists TODAY and would make
    this gate green on every milestone. Using it would look like the fix and
    mean less than the disclosure it replaced: the stamp is local, so it is
    exactly the "one machine's word" the retired clause existed to require
    something stronger than.
    """
    src = (Path(__file__).resolve().parents[1]
           / "gatekeeper_review.py").read_text(encoding="utf-8")
    body = src.split("def ci_ran_gate", 1)[1].split("\ndef ", 1)[0]
    # COMMENTS STRIPPED. The function's own comment EXPLAINS why it must not read
    # the stamp, and names it to do so. A scan that cannot tell documentation
    # from code has to be weakened the first time someone documents something —
    # the same mistake this repo made in `test_dont_use_ordering` (v1.9.6), where
    # six step names in prose read as six steps in the wrong order.
    code = "\n".join(ln for ln in body.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "gatekeeper-stamp" not in code, (
        "ci_ran_gate reads the local stamp — that satisfies the gate without "
        "satisfying its reason (#570)")
    assert "gatekeeper-stamp" in body, (
        "the function no longer explains why it does not use the stamp; without "
        "that, the next reader wires it in as an obvious improvement")


def test_a_real_ci_failure_blocks_at_every_cadence(monkeypatch, tmp_path):
    """CONTROL. The downgrade above is scoped to NEVER_RAN. A CI run that
    actually FAILED must still block a patch — otherwise the disclosure path
    became a way to land red."""
    import gatekeeper_review as G

    def _fake(prog, args, **kw):
        return 1, "", "[FAIL] CI ran on deadbeefc and did NOT pass: CI=failure"
    monkeypatch.setattr(G, "_run_program", _fake)

    for cadence in ("TARGETED", "FULL"):
        assert G.ci_ran_gate(tmp_path, "HEAD", cadence).green is False, (
            f"a failing CI run was waved through at cadence={cadence}")


def test_not_checked_never_blocks_a_merge(monkeypatch, tmp_path):
    """rc 2 means "I could not look" and must not refuse the merge.

    Caught by the EXISTING `test_gatekeeper_review` suite, which drives the
    review over a plain temp directory: my first version returned rc 2 straight
    through, and `GateResult.green` counts only 0 and -1, so an offline
    maintainer, a rate limit, or a review run outside a git repo would all have
    been refused. The reason stays in the summary — non-blocking is not the
    same as silent.
    """
    import gatekeeper_review as G

    def _fake(prog, args, **kw):
        return 2, "", "[NOT CHECKED] could not ask GitHub about deadbeefc"
    monkeypatch.setattr(G, "_run_program", _fake)

    for cadence in ("TARGETED", "FULL"):
        g = G.ci_ran_gate(tmp_path, "HEAD", cadence)
        assert g.green is True, f"NOT CHECKED blocked the merge at {cadence}"
        assert "NOT CHECKED" in g.summary, (
            "it went green without saying it could not look")


# --- the deny-list left the door open for exactly what this program stops

def test_automation_the_repo_did_not_commit_is_not_ci():
    """A run's own `path` says whether the repository declared that workflow.

    The name deny-list classified `CodeQL`, `Deploy Pages` and `Greetings` as
    CI — measured — so ONE green run of any of them would have made this program
    report CI as passing. That is the substitution it exists to stop, arriving
    through the door it left open, and a longer list does not fix it: the next
    workflow nobody thought of is not on that one either.

    The failure directions are not symmetric. An unrecognised name treated as
    NOT-CI costs a false NEVER_RAN, which is loud. Treated as CI it costs a
    false PASSED, which is silent and is the whole subject of #550.
    """
    for name, path in (("CodeQL", "dynamic/github-code-scanning/codeql"),
                       ("Deploy Pages", "dynamic/pages/build-deployment"),
                       ("Dependency Graph", "dynamic/dependabot/update-graph")):
        assert not C._is_ci_run(name, path), \
            f"{name} would stand in for the test suite"

    # ISOLATING THE PATH RULE. The three above are ALSO on the fallback name
    # list now, so removing the path check entirely left this test green — the
    # list answered for it. A mutation that survives means the test is measuring
    # the other half of the fix. This name is on no list and never will be,
    # which is the whole argument for asking the repo instead of keeping one.
    assert not C._is_ci_run("Nightly Fuzz", "dynamic/some-app/whatever"), \
        ("a workflow the repository never committed is being treated as its "
         "CI — the path rule is not in force, and a name list cannot cover a "
         "name nobody has thought of")


def test_a_committed_workflow_is_ci_whatever_it_is_called():
    """The allow-side. A repo's own workflow counts even under a name this
    program has never seen — which is the point of asking the repo rather than
    keeping a list of names someone has to remember to extend."""
    assert C._is_ci_run("CI", ".github/workflows/ci.yml")
    assert C._is_ci_run("Gatekeeper CI", ".github/workflows/gatekeeper-ci.yml")
    assert C._is_ci_run("some-new-suite", ".github/workflows/whatever.yml")


def test_the_name_list_still_answers_when_there_is_no_path():
    """Belt and braces, in that order: an older API shape or a bare-name caller
    still gets the weaker answer rather than an exception."""
    assert C._is_ci_run("CI") is True
    assert C._is_ci_run("Dependency Graph") is False
    assert C._is_ci_run("CodeQL") is False, \
        "the fallback list gained the names the probe found"


def test_the_run_filter_passes_the_path_through():
    """WIRING. Classifying correctly and then not passing `path` changes
    nothing — the defect would be invisible because the fallback still answers.
    """
    import inspect
    src = inspect.getsource(C.evaluate)
    assert '_is_ci_run(r.get("name", ""), r.get("path"))' in src, \
        "evaluate() drops the path, so every run is judged by name alone"


def test_never_ran_and_failed_both_produce_a_failing_exit_code(monkeypatch):
    """The states are distinguished in the REPORT; the caller reads the CODE.

    Measured: replacing the FAIL branch's `return` with the pass value left all
    seventeen tests green — the gate whose entire subject is "an absence must
    not render as a pass" could itself return a pass on a finding.
    """
    for state in ("NEVER_RAN", "FAILED"):
        monkeypatch.setattr(C, "evaluate",
                            lambda slug, sha, min_total=None, _s=state:
                            {"state": _s, "sha": "a" * 9, "runs": 0,
                             "workflows": [], "detail": "x"})
        monkeypatch.setattr(C, "_repo_slug", lambda d: "o/r")
        monkeypatch.setattr(C, "_head_sha", lambda d, rev: "a" * 40)
        assert C.main(["."]) == C.RC_FAIL, f"{state} did not exit non-zero"


def test_passed_produces_a_passing_exit_code(monkeypatch):
    """The other direction, or the test above is met by always failing."""
    monkeypatch.setattr(C, "evaluate", lambda slug, sha, min_total=None:
                        {"state": "PASSED", "sha": "a" * 9, "runs": 1,
                         "workflows": ["CI"], "detail": "ok"})
    monkeypatch.setattr(C, "_repo_slug", lambda d: "o/r")
    monkeypatch.setattr(C, "_head_sha", lambda d, rev: "a" * 40)
    assert C.main(["."]) == C.RC_PASS


def test_unreachable_is_rc_2_not_rc_0(monkeypatch):
    """"I could not look" must never share a code with "I looked and it passed"
    — the whole thesis of #550."""
    monkeypatch.setattr(C, "evaluate", lambda slug, sha, min_total=None:
                        {"state": "UNREACHABLE", "sha": "a" * 9,
                         "detail": "api down"})
    monkeypatch.setattr(C, "_repo_slug", lambda d: "o/r")
    monkeypatch.setattr(C, "_head_sha", lambda d, rev: "a" * 40)
    assert C.main(["."]) == C.RC_NOT_CHECKED
