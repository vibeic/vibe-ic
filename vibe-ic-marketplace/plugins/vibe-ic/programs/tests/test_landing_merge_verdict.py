"""A red suite survived five merges because `gh pr merge` runs no gate at all.

`tools/gatekeeper-land.sh` runs the tests and stamps the commit it verified;
`tools/git-hooks/pre-push` refuses a push whose commit has no matching stamp.
The enforcement is attached to `git push` — and a server-side squash merge
pushes nothing from a local clone, so neither ever fires. Measured on
2026-08-12: Actions `{"enabled": false}` at the account level, `main` `404
Branch not protected`, no required status check exists. There is no
server-side check to fall back on and none can be created.

`tools/gatekeeper-verify-merge.sh` puts the existing gates on the path that
lands code. This file gates the DECISION that script defers to
(`landing_merge_verdict.decide`) and the plumbing that feeds it.

WHAT THIS FILE REFUSES
======================
1. **A gate that cannot refuse.** Nine independent refusal reasons, each
   asserted on the VERDICT rather than on the printed text, so the mutant that
   neuters only the decision line kills them.
2. **A gate that refuses everything.** :func:`test_a_known_good_pr_shape_is_allowed`
   and the end-to-end paired guard: a landing that broke nothing must LAND OK.
   PR #1020 lost a whole corpus's one true finding to an always-fires mutant
   hours before #1019 was filed; a landing gate that refuses every landing is a
   ban, not a check.
3. **Crediting a silenced failure as a fix.** `failed -> skipped` and
   `failed -> absent` are refusals. Without that row the differential rewards
   the cheat it exists to catch: delete the red test and the failed set shrinks.
4. **A permissive degradation.** Every way the differential can lose
   information — empty base, no overlap, a truncated candidate run, a selected
   file that produced no test case — is asserted to go STRICTER, never softer.
   That list was asked of the CANDIDATE arm only. The BASE arm's completeness
   is the one that goes SOFTER (vibe-ic#1443): `silenced` and `weakened` are
   read off what was red or passing ON THE BASE, so a base failure that never
   got measured is a base failure the branch may delete for free. Measured on
   `3d13e2c59`, one selected file missing from the base report turned
   `REFUSE 1 FAILING TEST(S) WERE SILENCED` into `LAND OK` with every other
   input byte-identical.
5. **A verdict about the wrong tree.** `gh pr merge --squash` creates the
   forge's merge tree. A rebase that produces a different tree, or a forge that
   disagrees with the local merge, is refused before any suite is run.
"""
from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import landing_merge_verdict as V  # noqa: E402

import _progress_run as _pr  # noqa: E402

_PROGRAMS = Path(__file__).resolve().parents[1]
_PROG = _PROGRAMS / "landing_merge_verdict.py"
_REPO_ROOT = _PROGRAMS.parents[3]
_VERIFY = _REPO_ROOT / "tools" / "gatekeeper-verify-merge.sh"
_LAND = _REPO_ROOT / "tools" / "gatekeeper-land.sh"
_GATEKEEPER_SKILL = Path(os.environ.get(
    "GATEKEEPER_SKILL_UNDER_TEST",
    _REPO_ROOT / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "skills"
    / "gatekeeper-loop" / "SKILL.md"))
_T = 55


def _service_program():
    return Path(os.environ.get("GATEKEEPER_SERVICE_UNDER_TEST", str(_PROG)))

# THE FILES THE MERGE VERIFIER EXECUTES OUT OF THE BASE SNAPSHOT, which the
# miniature repository below must carry as the real bytes.  This set used to be
# derived from the protected-path transition validator's two path registers;
# the owner removed that two-step mechanism on 2026-09-27, and the set it
# described is kept here, minus the two removed modules and plus the three the
# survivors now run (`landing_execution_plan.py`,
# `landing_record_primitives.py`, `landing_push_preflight.py`).
_SELECT_CONTROL_TESTS = (
    "programs/tests/test_ci_harness_timeout_ceiling_check.py",
    "programs/tests/test_gate_process_attestation.py",
    "programs/tests/test_landing_merge_verdict.py",
    "programs/tests/test_pytest_per_file_junit.py",
)

TREE = "a" * 40
OTHER_TREE = "b" * 40
SHA = "c" * 40

_GOOD_LOG = """=== gatekeeper landing gates — base=origin/main ===
--- cheap tier (also enforced by the pre-push hook) ---
  PASS  NDA — commit messages
  PASS  version monotonic (assigned at merge — deferred)
  REPORT  untracked scratch paths in this checkout
--- full tier (minutes; stamps the tree on success) ---
  PASS  targeted tests (21 file(s))
  PASS  repo hygiene gates
=== ALL GATES PASS — stamped %s ===
""" % SHA[:9]

_RED_TEST_TIER_LOG = """=== gatekeeper landing gates — base=origin/main ===
  PASS  NDA — commit messages
  PASS  version monotonic (assigned at merge — deferred)
  FAIL  targeted tests (21 file(s))
  PASS  repo hygiene gates
=== FAILURES ABOVE — stamp removed; the pre-push hook will refuse ===
"""


def _delta(**kw):
    d = V.Delta(base_total=kw.pop("base_total", 10),
                candidate_total=kw.pop("candidate_total", 10),
                overlap=kw.pop("overlap", 10))
    for k, v in kw.items():
        setattr(d, k, v)
    return d


def _decide(**over):
    """A LAND OK baseline; each test perturbs exactly one fact."""
    kw = dict(rebase_status="ok", expected_tree=TREE, verified_tree=TREE,
              github_tree=TREE, land=V.parse_land_log(_GOOD_LOG),
              base_land=V.parse_land_log(_GOOD_LOG),
              delta=_delta(), verified_sha=SHA, truncated=False,
              dropped_files=(), selection_size=21,
              hygiene={"status": "CLEAN", "introduced": [], "carried": [],
                       "cleared": [], "candidate_findings": 0,
                       "base_findings": 0, "declared": 1})
    kw.update(over)
    return V.decide(**kw)


# ============================================================ THE PAIRED GUARD


def test_a_known_good_pr_shape_is_allowed():
    """LOAD-BEARING, and the reason it is first. Everything else in this file
    proves the gate CAN refuse; a gate that refuses every landing is a ban.

    Nothing here is a stub of the decision: the log is a real
    `gatekeeper-land.sh` transcript shape, the trees agree with the forge, and
    the differential is empty."""
    v = _decide()
    assert v.ok is True, v.reasons
    assert v.reasons == []
    assert v.unmeasurable is False


def test_a_pre_existing_red_base_still_allows_the_landing():
    """`main` is RED right now (`test_ci_harness_timeout_ceiling_check`, 3 of 40
    at `e4880703b`, in files nothing in flight touches). Demanding green would
    refuse EVERY landing today — which is how a repo ends up with a landing path
    that has no gate. The same failure on both sides is nobody's."""
    d = _delta(preexisting=["m::t_red"])
    v = _decide(delta=d, land=V.parse_land_log(_RED_TEST_TIER_LOG))
    assert v.ok is True, v.reasons
    assert any("pre-existing" in n for n in v.notes)


def test_the_test_tier_failing_is_not_by_itself_a_refusal():
    """`gatekeeper-land.sh` withholds the stamp on ANY red test. The differential
    owns that verdict and no other: every OTHER gate's FAIL still blocks."""
    log = V.parse_land_log(_RED_TEST_TIER_LOG)
    assert log.test_tier_failed is True
    assert log.blocking_failures == []


def test_a_test_tier_failure_with_all_green_machine_record_is_refused():
    v = _decide(land=V.parse_land_log(_RED_TEST_TIER_LOG), delta=_delta())
    assert v.ok is False
    assert any("FAILED BUT THE CANDIDATE REPORT CONTAINS NO RED" in reason
               for reason in v.reasons)


def test_fixing_a_pre_existing_failure_is_reported_and_never_required():
    v = _decide(delta=_delta(fixed=["m::t_was_red"]))
    assert v.ok is True
    assert any("now pass" in n for n in v.notes)


# ==================================================== THE NINE REFUSAL REASONS


def test_a_new_failure_this_branch_owns_is_refused():
    v = _decide(delta=_delta(new_failures=["m::t_new"]))
    assert v.ok is False
    assert any("NEW FAILURE" in r for r in v.reasons)


def test_a_silenced_failure_is_refused_and_is_never_an_improvement():
    """`failed -> skipped` shrinks the failed set without fixing anything. If it
    counted as an improvement, the cheapest way to pass this gate would be to
    delete the test that fails."""
    v = _decide(delta=_delta(silenced=["m::t_skipped_now"]))
    assert v.ok is False
    assert any("SILENCED" in r for r in v.reasons)


def test_a_passing_test_weakened_to_skip_is_refused():
    """Green base evidence must not become a stale permission to stop asking.

    A cached PASS followed by a candidate SKIP is unsafe even when the live
    base would still pass; if runtime drift made the live base red, allowing
    PASS -> SKIP would hide the exact silenced failure the differential exists
    to catch.
    """
    v = _decide(delta=_delta(weakened=["m::t_skipped_now"]))
    assert v.ok is False
    assert any("WEAKENED" in r for r in v.reasons)


def test_a_rebase_conflict_is_refused():
    v = _decide(rebase_status="conflict")
    assert v.ok is False
    assert any("REBASE CONFLICT" in r for r in v.reasons)


def test_verifying_a_tree_that_is_not_the_merge_tree_is_refused():
    v = _decide(verified_tree=OTHER_TREE, github_tree=TREE)
    assert v.ok is False
    assert any("WRONG TREE" in r for r in v.reasons)


def test_the_forge_disagreeing_with_the_local_merge_is_refused():
    """`gh pr merge --squash` creates a commit with the FORGE's merge tree. If
    the local computation disagrees, the verified tree is not the landed one."""
    v = _decide(github_tree=OTHER_TREE)
    assert v.ok is False
    assert any("FORGE DISAGREES" in r for r in v.reasons)


def test_any_non_test_gate_failure_is_refused_when_there_is_no_base_to_compare():
    """Missing baseline is incomplete, even when a candidate failure is visible."""
    log = V.parse_land_log(
        "=== gatekeeper landing gates ===\n"
        "  PASS  targeted tests (3 file(s))\n"
        "  FAIL  tree contains the base it claims as parent\n")
    v = _decide(land=log, base_land=None)
    assert v.ok is False
    assert any("tree contains the base" in r for r in v.reasons)
    assert v.admission == "INCOMPLETE"
    assert "BASE_GATE_RECORD_MISSING_OR_INVALID" in v.incomplete


# ==================================== THE GATE TIER GETS THE SAME DIFFERENTIAL
#
# Measured at `e4880703b`: `flow_gate_enforcement_audit` and the 63x8 census
# freshness check are BOTH red on the base. An absolute rule would have refused
# every landing — the ban this program exists to avoid — so the gate tier is
# compared, not asserted.


def _gate_log(*lines, stamp=None):
    body = "=== gatekeeper landing gates ===\n" + "".join(
        f"  {w}  {label}\n" for w, label in lines)
    if stamp:
        body += f"=== ALL GATES PASS — stamped {stamp} ===\n"
    elif any(word == "FAIL" for word, _ in lines):
        body += V._FAILURES_TERMINAL + "\n"
    else:
        body += V._NON_TARGET_COMPLETE + "\n"
    return V.parse_land_log(body)


def test_a_gate_failing_on_the_base_too_is_not_this_branchs():
    base = _gate_log(("FAIL", "repo hygiene gates"), ("PASS", "plugin full audit"))
    cand = _gate_log(("FAIL", "repo hygiene gates"), ("PASS", "plugin full audit"),
                     ("PASS", "targeted tests (3 file(s))"))
    v = _decide(land=cand, base_land=base)
    assert v.ok is True, v.reasons
    assert any("fails on the base too" in n for n in v.notes)


def test_a_gate_this_branch_reddens_is_refused():
    base = _gate_log(("PASS", "repo hygiene gates"))
    cand = _gate_log(("FAIL", "repo hygiene gates"),
                     ("PASS", "targeted tests (3 file(s))"))
    v = _decide(land=cand, base_land=base)
    assert v.ok is False
    assert any("PASSED ON THE BASE" in r for r in v.reasons)


def test_a_failing_gate_that_stops_being_asked_is_refused():
    """The gate-tier twin of `failed -> skipped`. Deleting the gate that fails is
    the cheapest way to make a differential green, so it is a refusal."""
    base = _gate_log(("FAIL", "repo hygiene gates"))
    cand = _gate_log(("SKIP", "repo hygiene gates"),
                     ("PASS", "targeted tests (3 file(s))"))
    v = _decide(land=cand, base_land=base)
    assert v.ok is False
    assert any("SILENCED RATHER THAN FIXED" in r for r in v.reasons)

    gone = _gate_log(("PASS", "targeted tests (3 file(s))"))
    v2 = _decide(land=gone, base_land=base)
    assert v2.ok is False
    assert any("no longer asked here" in r for r in v2.reasons)


def test_repairing_a_gate_the_base_was_failing_is_reported():
    base = _gate_log(("FAIL", "worktree unchanged since the gates started"))
    cand = _gate_log(("PASS", "worktree unchanged since the gates started"),
                     ("PASS", "targeted tests (3 file(s))"))
    v = _decide(land=cand, base_land=base)
    assert v.ok is True, v.reasons
    assert any("now passes" in n for n in v.notes)


def test_the_replay_disagreeing_with_the_merge_is_refused():
    """Rebasing asks whether the branch's intent still applies; merging asks
    whether its text still combines. The phantom-revert shape is where the two
    answers come apart, and only one of them is what `gh pr merge` creates."""
    v = _decide(replayed_tree=OTHER_TREE)
    assert v.ok is False
    assert any("REPLAY AND THE MERGE DISAGREE" in r for r in v.reasons)


def test_a_stamp_naming_another_commit_is_refused():
    """The v1.9.16 shape: the suites read a WORKTREE for minutes while the stamp
    names a COMMIT, so a tree that never existed got stamped."""
    log = V.parse_land_log(_GOOD_LOG.replace(SHA[:9], "deadbeef1"))
    v = _decide(land=log)
    assert v.ok is False
    assert any("ANOTHER COMMIT" in r for r in v.reasons)


def test_a_truncated_candidate_run_is_refused_not_passed():
    """`--maxfail=10` stops pytest. The tests after it did not run, so their
    absence is not a result and the differential cannot be computed."""
    v = _decide(truncated=True, dropped_files=["programs/tests/test_x.py"])
    assert v.ok is False
    assert any("TRUNCATED" in r for r in v.reasons)


def test_a_selected_file_that_produced_no_test_case_is_refused():
    """Chosen and then never asked. A selection that silently drops a file is
    the hole #1019 is about, one level down."""
    v = _decide(dropped_files=["programs/tests/test_ghost.py"])
    assert v.ok is False
    assert any("NO TEST CASE" in r for r in v.reasons)


# ============================= ARM A'S COMPLETENESS IS ALSO A REFUSAL (#1443)


def test_a_base_arm_that_did_not_finish_is_refused_not_passed():
    """The same question as the test above, asked of the arm that is SUBTRACTED.

    #1443's law: "a two-arm comparison must assert that both arms emitted a
    summary line before it subtracts anything." The candidate arm had that
    check; the base arm had only `base_total == 0`, which is all-or-nothing and
    only a NOTE. A base arm that ran three of its five files sits between the
    two and was subtracted as though whole."""
    v = _decide(base_dropped_files=["programs/tests/test_alpha.py"])
    assert v.ok is False, v.notes
    assert any("NO TEST CASE ON THE BASE" in r for r in v.reasons), v.reasons


def test_a_complete_base_arm_is_not_flagged_as_partial():
    """THE FALSE-POSITIVE CONTROL. The check above must fire on a partial base
    arm and on nothing else — a gate that refuses every landing is a ban."""
    v = _decide(base_dropped_files=())
    assert v.ok is True, v.reasons
    assert not any("ON THE BASE" in r for r in v.reasons), v.reasons


def test_a_caller_that_never_says_what_arm_a_was_asked_for_is_disclosed():
    """DEGRADE LOUDLY. A caller supplying no base selection leaves the check
    unable to fire, and a check that cannot fire must not read as a clean sheet.
    Missing required coverage blocks admission while preserving the disclosure."""
    v = _decide(base_selection_supplied=False)
    assert v.ok is False, v.reasons
    assert v.admission == "INCOMPLETE"
    assert any("completeness was NOT checked" in n for n in v.notes), v.notes


# ================================================= UNMEASURABLE IS NOT A PASS


def test_land_gates_that_did_not_report_are_not_a_pass():
    v = _decide(land=V.parse_land_log("nothing here\n"))
    assert v.ok is False
    assert v.unmeasurable is True
    assert any("DID NOT RUN" in r for r in v.reasons)


def test_a_partial_non_target_gate_log_is_not_a_composite_pass():
    partial = V.parse_land_log(
        "=== gatekeeper landing gates — base=origin/main ===\n"
        "  PASS  one cheap gate\n")
    v = _decide(land=partial, candidate_gate_rc=0,
                require_composite_gate_record=True)
    assert v.ok is False
    assert v.unmeasurable is True
    assert any("NO COMPLETE TERMINAL RECORD" in r for r in v.reasons)


def test_a_non_target_gate_abnormal_exit_refuses_even_with_a_fake_terminal():
    fake = V.parse_land_log(
        "=== gatekeeper landing gates — base=origin/main ===\n"
        "  PASS  one cheap gate\n"
        "=== ALL NON-TARGET GATES COMPLETE — stamp withheld for composite verdict ===\n")
    v = _decide(land=fake, candidate_gate_rc=2,
                require_composite_gate_record=True)
    assert v.ok is False
    assert v.unmeasurable is True
    assert any("DID NOT EXIT NORMALLY" in r for r in v.reasons)


def test_a_complete_non_target_gate_record_can_join_the_composite():
    complete = V.parse_land_log(
        "=== gatekeeper landing gates — base=origin/main ===\n"
        "  PASS  one cheap gate\n"
        "=== ALL NON-TARGET GATES COMPLETE — stamp withheld for composite verdict ===\n")
    v = _decide(land=complete, base_land=complete, candidate_gate_rc=0,
                require_composite_gate_record=True)
    assert v.ok is True, v.reasons


def test_a_candidate_test_arm_that_wrote_the_tree_is_refused():
    v = _decide(candidate_test_worktree_status="dirty")
    assert v.ok is False
    assert any("TEST ARM WROTE" in r for r in v.reasons)


def test_an_uninspectable_candidate_test_worktree_is_unmeasurable():
    v = _decide(candidate_test_worktree_status="unknown")
    assert v.ok is False
    assert v.unmeasurable is True
    assert any("COULD NOT BE INSPECTED" in r for r in v.reasons)


def test_a_candidate_test_arm_that_moved_to_another_commit_is_refused():
    v = _decide(candidate_test_worktree_status="wrong-head")
    assert v.ok is False
    assert any("MOVED OFF THE VERIFIED COMMIT" in r for r in v.reasons)


def test_a_base_test_arm_that_wrote_the_tree_is_refused():
    v = _decide(base_test_worktree_status="dirty")
    assert v.ok is False
    assert any("BASE TEST ARM WROTE" in r for r in v.reasons)


def test_an_uninspectable_base_test_worktree_is_unmeasurable():
    v = _decide(base_test_worktree_status="unknown")
    assert v.ok is False
    assert v.unmeasurable is True
    assert any("BASE TEST WORKTREE COULD NOT BE INSPECTED" in r
               for r in v.reasons)


def test_a_base_test_arm_that_moved_to_another_commit_is_refused():
    v = _decide(base_test_worktree_status="wrong-head")
    assert v.ok is False
    assert any("MOVED OFF THE BASE COMMIT" in r for r in v.reasons)


def test_a_candidate_that_ran_no_tests_is_not_a_pass():
    v = _decide(delta=_delta(candidate_total=0, base_total=0, overlap=0))
    assert v.ok is False
    assert v.unmeasurable is True
    assert any("NO TESTS" in r for r in v.reasons)


def test_a_missing_tree_is_not_a_pass():
    v = _decide(expected_tree="")
    assert v.ok is False
    assert v.unmeasurable is True


def test_an_unmeasurable_refusal_still_names_the_reason_it_already_found():
    """A conflicting rebase and an uncomputable merge tree are the SAME event
    seen twice. The early return used to hand back a FRESH reason list, so the
    operator got the symptom ("the merge tree could not be computed") and not the
    cause ("REBASE CONFLICT") — and the end-to-end conflict case is what caught
    it."""
    v = _decide(rebase_status="conflict", expected_tree="")
    assert v.ok is False
    assert any("REBASE CONFLICT" in r for r in v.reasons), v.reasons
    assert any("COULD NOT BE COMPUTED" in r for r in v.reasons), v.reasons


# ======================================== EVERY DEGRADATION GOES STRICTER


def test_an_empty_base_report_makes_every_candidate_failure_new():
    """The only direction the differential may lose information in. With no base
    to compare against, `demand green` is what is left, and it is stricter."""
    base = {}
    cand = {"m::t_a": V.PASSED, "m::t_b": V.FAILED}
    d = V.failed_set_delta(base, cand)
    assert d.new_failures == ["m::t_b"]
    assert d.preexisting == []
    v = _decide(delta=_delta(base_total=0, overlap=0, new_failures=["m::t_b"]))
    assert v.ok is False


def test_no_overlapping_test_id_is_disclosed_as_a_degradation():
    v = _decide(delta=_delta(overlap=0))
    assert v.ok is True          # nothing broke; the note is the disclosure
    assert any("demand green" in n for n in v.notes)


def test_there_is_no_input_that_makes_the_verdict_more_permissive_than_green():
    """Stated as an assertion rather than a comment: for a candidate carrying a
    failure, no combination of the OTHER facts yields LAND OK unless the base
    carried that same failure."""
    for base_outcome in (V.PASSED, V.SKIPPED, V.XFAILED, V.ABSENT):
        base = {} if base_outcome is V.ABSENT else {"m::t": base_outcome}
        d = V.failed_set_delta(base, {"m::t": V.FAILED})
        assert d.new_failures == ["m::t"], base_outcome
        assert _decide(delta=_delta(new_failures=d.new_failures)).ok is False


def test_a_test_the_branch_brings_is_split_out_from_one_it_broke():
    """vibe-ic#1417. `b in RED` is false BOTH when the base ran the test and it
    passed AND when the base never had the test — and only the first is a
    behaviour this change broke. Reported as one number, they are a 5x
    overstatement on a batch.

    MEASURED on a 141-PR batch composed on `3d13e2c59`: 5 nodes reported NEW,
    of which FOUR do not exist on main at all (`grep 'def <name>'` -> main 0,
    batch 1) and ONE — `test_d8_downgrade_is_reachable_through_each_steps_own_
    real_gate` — passes alone on main and fails alone in the batch. One
    regression, reported as five.
    """
    base = {"m::t_broke": V.PASSED, "m::t_ok": V.PASSED}
    cand = {"m::t_broke": V.FAILED, "m::t_ok": V.PASSED,
            "m::t_brought": V.FAILED}
    d = V.failed_set_delta(base, cand)
    assert sorted(d.new_failures) == ["m::t_broke", "m::t_brought"]
    assert d.new_absent_on_base == ["m::t_brought"], (
        "a test the branch BRINGS, failing, is not separated from one it BROKE")


def test_splitting_the_count_moves_no_verdict():
    """LOAD-BEARING. The split is a disclosure and must never become a waiver:
    a failing test the branch brought is still the branch's. Asserted on the
    VERDICT, so a future edit that routes on `new_absent_on_base` to soften the
    refusal kills this."""
    for brought in ([], ["m::t_brought"]):
        v = _decide(delta=_delta(new_failures=["m::t_brought"],
                                 new_absent_on_base=brought))
        assert v.ok is False, brought
        assert any("NEW FAILURE(S) THIS BRANCH OWNS" in r for r in v.reasons)


def test_an_empty_base_does_not_report_everything_as_merely_brought():
    """The degradation that would flatter. With no base report every id is
    absent, so an unguarded split would announce "nothing was broken, it is all
    new" — false, and in the permissive direction. `decide` already discloses
    the empty base; this must add no second, wrong sentence."""
    d = V.failed_set_delta({}, {"m::t_b": V.FAILED})
    assert d.new_failures == ["m::t_b"]
    assert d.new_absent_on_base == [], (
        "an empty base made every failure look like a newly brought assertion")


def test_the_split_is_machine_readable_not_only_prose():
    d = V.failed_set_delta({"m::t": V.PASSED}, {"m::t": V.FAILED, "m::n": V.FAILED})
    assert "new_absent_on_base" in d.as_dict()
    assert d.as_dict()["new_absent_on_base"] == ["m::n"]


# ================================================== THE DECISION TABLE, EXACTLY


@pytest.mark.parametrize("base_o,cand_o,bucket", [
    (V.FAILED, V.FAILED, "preexisting"),
    (V.ERRORED, V.FAILED, "preexisting"),
    (V.FAILED, V.PASSED, "fixed"),
    (V.PASSED, V.FAILED, "new_failures"),
    (V.SKIPPED, V.ERRORED, "new_failures"),
    (V.FAILED, V.SKIPPED, "silenced"),
    (V.FAILED, V.XFAILED, "silenced"),
    (V.PASSED, V.SKIPPED, "weakened"),
])
def test_every_row_of_the_table(base_o, cand_o, bucket):
    d = V.failed_set_delta({"m::t": base_o}, {"m::t": cand_o})
    assert getattr(d, bucket) == ["m::t"], d.as_dict()
    for other in ("new_failures", "silenced", "fixed", "weakened", "preexisting"):
        if other != bucket:
            assert getattr(d, other) == [], (other, d.as_dict())


def test_a_test_that_stopped_existing_is_absent_not_missing():
    """ABSENT is an OUTCOME. On the red side it is a silencing, and a dict lookup
    that returned None would have made it invisible."""
    assert V.failed_set_delta({"m::t": V.FAILED}, {}).silenced == ["m::t"]
    assert V.failed_set_delta({}, {"m::t": V.FAILED}).new_failures == ["m::t"]


# ============================================================= JUNIT + THE LOG


def _junit(tmp_path, cases, name="r.xml"):
    body = []
    for classname, tname, outcome, f in cases:
        inner = {"passed": "", "failed": "<failure>x</failure>",
                 "errored": "<error>x</error>", "skipped": "<skipped/>",
                 "xfailed": '<skipped type="pytest.xfail"/>'}[outcome]
        body.append(f'<testcase classname="{classname}" name="{tname}"'
                    + (f' file="{f}"' if f else "") + f'>{inner}</testcase>')
    p = tmp_path / name
    p.write_text('<?xml version="1.0"?><testsuites><testsuite>'
                 + "".join(body) + "</testsuite></testsuites>")
    return p


def _attest_junit(path, cases, selection, *, aggregate=True, per_file=True):
    """Append the exact process-suite shapes emitted by the real driver."""
    root = ET.parse(str(path)).getroot()
    outcomes = {name: [] for name in selection}
    for classname, _tname, outcome, file_name in cases:
        probe = ET.Element("testcase", {"classname": classname})
        if file_name:
            probe.set("file", file_name)
        recovered = V._file_of(probe, selection)
        if recovered:
            outcomes.setdefault(recovered, []).append(outcome)
    if per_file:
        for file_name in sorted(
                name for name, values in outcomes.items() if values):
            rc = 1 if any(v in {"failed", "errored"}
                          for v in outcomes[file_name]) else 0
            name = f"{file_name}::process_exit"
            suite = ET.SubElement(root, "testsuite", {
                "name": name, "tests": "1", "failures": str(int(rc != 0)),
                "errors": "0", "skipped": "0",
            })
            tc = ET.SubElement(suite, "testcase", {
                "classname": "pytest_per_file_process", "name": name,
                "file": file_name,
            })
            props = ET.SubElement(tc, "properties")
            ET.SubElement(props, "property", {
                "name": "process_rc", "value": str(rc)})
            if rc:
                ET.SubElement(tc, "failure")
    if aggregate:
        ordinary = next(root.iter("testsuite"))
        aggregate_suite = ET.SubElement(root, "testsuite", {
            "name": "aggregate::pytest",
        })
        for original in list(ordinary.iter("testcase")):
            copied = ET.fromstring(ET.tostring(original, encoding="unicode"))
            recovered = V._file_of(original, selection)
            if recovered:
                copied.set("file", recovered)
            copied.set(
                "classname",
                "pytest_aggregate." + (copied.get("classname") or ""))
            aggregate_suite.append(copied)
        rc = 1 if any(outcome in {"failed", "errored"}
                      for _c, _n, outcome, _f in cases) else 0
        name = "whole_selection::process_exit"
        suite = ET.SubElement(root, "testsuite", {
            "name": name, "tests": "1", "failures": str(int(rc != 0)),
            "errors": "0", "skipped": "0",
        })
        tc = ET.SubElement(suite, "testcase", {
            "classname": "pytest_aggregate_process", "name": name,
            "file": "<aggregate>",
        })
        props = ET.SubElement(tc, "properties")
        ET.SubElement(props, "property", {
            "name": "process_rc", "value": str(rc)})
        if rc:
            ET.SubElement(tc, "failure")
    ET.ElementTree(root).write(str(path), encoding="utf-8",
                               xml_declaration=True)


def test_junit_outcomes_are_read_including_xfail(tmp_path):
    p = _junit(tmp_path, [
        ("m", "a", "passed", None), ("m", "b", "failed", None),
        ("m", "c", "errored", None), ("m", "d", "skipped", None),
        ("m", "e", "xfailed", None)])
    got = V.read_junit(p)
    assert got == {"m::a": V.PASSED, "m::b": V.FAILED, "m::c": V.ERRORED,
                   "m::d": V.SKIPPED, "m::e": V.XFAILED}


def test_the_worst_outcome_wins_for_a_duplicated_id(tmp_path):
    """A rerun plugin emits two entries for one id. Whichever order they arrive
    in, a failure must not be overwritten by a later pass."""
    p = _junit(tmp_path, [("m", "a", "failed", None), ("m", "a", "passed", None)])
    assert V.read_junit(p)["m::a"] == V.FAILED
    p2 = _junit(tmp_path, [("m", "a", "passed", None), ("m", "a", "failed", None)],
                name="r2.xml")
    assert V.read_junit(p2)["m::a"] == V.FAILED


def test_the_test_file_is_recovered_without_the_xunit1_file_attribute(tmp_path):
    """`xunit2` — pytest's default — drops `file`. The dotted classname still
    names the module, and class-based tests carry one component too many."""
    sel = ["programs/tests/test_thing.py"]
    p = _junit(tmp_path, [
        ("programs.tests.test_thing", "a", "passed", None),
        ("programs.tests.test_thing.TestKlass", "b", "passed", None)])
    assert V.junit_files(p, sel) == {"programs/tests/test_thing.py"}


def test_the_file_attribute_is_preferred_when_present(tmp_path):
    p = _junit(tmp_path, [("weird.classname", "a", "passed",
                           "programs/tests/test_thing.py")])
    assert V.junit_files(p, []) == {"programs/tests/test_thing.py"}


def test_subject_testcase_cannot_spoof_a_parent_process_suite(tmp_path):
    selected = "programs/tests/test_thing.py"
    p = tmp_path / "spoof.xml"
    p.write_text(
        '<?xml version="1.0"?><testsuites><testsuite name="' + selected + '">'
        '<testcase classname="pytest_per_file_process" '
        'name="' + selected + '::process_exit" file="' + selected + '">'
        '<properties><property name="process_rc" value="0"/></properties>'
        '</testcase></testsuite><testsuite name="pytest">'
        '<testcase classname="pytest_aggregate_process" '
        'name="whole_selection::process_exit" file="&lt;aggregate&gt;">'
        '<properties><property name="process_rc" value="0"/></properties>'
        '</testcase></testsuite></testsuites>')
    assert V.junit_per_file_process_files(p) == set()
    assert V.junit_has_aggregate_process(p) is False


def test_subject_process_attributes_cannot_turn_a_failure_green(tmp_path):
    p = tmp_path / "ordinary-failure.xml"
    p.write_text(
        '<?xml version="1.0"?><testsuites>'
        '<testsuite name="programs/tests/test_thing.py">'
        '<testcase classname="pytest_per_file_process" name="test_new_red" '
        'file="programs/tests/test_thing.py">'
        '<properties><property name="process_rc" value="0"/></properties>'
        '<failure>real candidate regression</failure>'
        '</testcase></testsuite></testsuites>')
    got = V.read_junit(p)
    assert got["pytest_per_file_process::test_new_red"] == V.FAILED
    assert V.junit_red_count(p) == 1


def test_per_file_diagnostics_cannot_fill_an_incomplete_aggregate(tmp_path):
    """The fallback channel cannot complete the authoritative question."""
    selected = ["programs/tests/test_alpha.py",
                "programs/tests/test_beta.py"]
    p = tmp_path / "mixed.xml"
    p.write_text(
        '<?xml version="1.0"?><testsuites>'
        '<testsuite name="aggregate::pytest">'
        '<testcase classname="pytest_aggregate.programs.tests.test_alpha" '
        'name="a" file="programs/tests/test_alpha.py"/>'
        '</testsuite>'
        '<testsuite name="programs/tests/test_beta.py">'
        '<testcase classname="programs.tests.test_beta" name="b" '
        'file="programs/tests/test_beta.py"/>'
        '</testsuite>'
        '<testsuite name="whole_selection::process_exit" tests="1" '
        'failures="0" errors="0" skipped="0">'
        '<testcase classname="pytest_aggregate_process" '
        'name="whole_selection::process_exit" file="&lt;aggregate&gt;">'
        '<properties><property name="process_rc" value="0"/></properties>'
        '</testcase></testsuite></testsuites>')

    assert set(selected).issubset(V.junit_files(p, selected))
    assert V.junit_aggregate_files(p, selected) == {selected[0]}


def test_report_lines_are_never_read_as_gates():
    """`gatekeeper-land.sh` prints REPORT for probes that are deliberately not
    landing bars. Counting one as a gate would make the gate a ban."""
    log = V.parse_land_log(_GOOD_LOG)
    assert log.reported == ["untracked scratch paths in this checkout"]
    assert log.blocking_failures == []
    assert log.stamped_sha == SHA[:9]


def test_a_selection_failure_is_not_the_test_tier():
    """`FAIL targeted test selection produced no files` is a SELECTION failure —
    a hard refusal. Only `FAIL targeted tests (...)` is deferred to the
    differential, and a prefix match would have swallowed both."""
    log = V.parse_land_log(
        "=== gatekeeper landing gates ===\n"
        "  FAIL  targeted test selection produced no files — not a clean result\n")
    assert log.blocking_failures == [
        "targeted test selection produced no files — not a clean result"]
    assert log.test_tier_failed is False


# ==================================================================== THE CLI


def _cli(tmp_path, land_text, base_cases, cand_cases, sel, extra=(),
         base_sel="derive", attest_candidate=True,
         candidate_aggregate=True, candidate_per_file=True,
         attest_base=True, base_aggregate=True, base_per_file=True,
         base_mutator=None, candidate_mutator=None):
    (tmp_path / "land.log").write_text(land_text)
    base_gate_args = ()
    if "--base-land-log" not in extra:
        baseline_log = tmp_path / "fixture_base_land.log"
        baseline_log.write_text(_GOOD_LOG)
        base_gate_args = ("--base-land-log", str(baseline_log))
    (tmp_path / "sel.txt").write_text("\n".join(sel) + "\n")
    bj = _junit(tmp_path, base_cases, "base.xml")
    cj = _junit(tmp_path, cand_cases, "cand.xml")
    if base_sel == "derive":
        base_sel = sorted(V.junit_files(bj, sel))
    import test_issue1498_hygiene_subset_rule_is_wired as H
    hyg_path = H._write(tmp_path, "clean-hygiene.json",
                        H._record([H._gate("neutral check", "PASS")]))
    if attest_candidate:
        _attest_junit(cj, cand_cases, sel, aggregate=candidate_aggregate,
                      per_file=candidate_per_file)
    base_sel_arg = ()
    if base_sel is not None:
        (tmp_path / "sel_base.txt").write_text("\n".join(base_sel) + "\n")
        base_sel_arg = ("--base-selection", str(tmp_path / "sel_base.txt"))
        if attest_base:
            _attest_junit(bj, base_cases, base_sel,
                          aggregate=base_aggregate,
                          per_file=base_per_file)
    if base_mutator:
        base_mutator(bj)
    if candidate_mutator:
        candidate_mutator(cj)
    cmd = [sys.executable, str(_PROG),
           "--base-sha", SHA, "--base-tree", TREE,
           "--head-sha", SHA, "--verified-sha", SHA,
           "--rebase-status", "ok", "--expected-tree", TREE,
           "--verified-tree", TREE, "--github-tree", TREE,
           "--land-log", str(tmp_path / "land.log"), *base_gate_args,
           "--selection", str(tmp_path / "sel.txt"), *base_sel_arg,
           "--base-junit", str(bj), "--candidate-junit", str(cj),
           "--base-hygiene", str(hyg_path), "--candidate-hygiene", str(hyg_path),
           "--base-hygiene-host", "test-host", "--candidate-hygiene-host", "test-host",
           "--json", str(tmp_path / "v.json"), *extra]
    r = _pr.run(cmd, capture_output=True, text=True)
    doc = json.loads((tmp_path / "v.json").read_text())
    return r, doc


_SEL = ["programs/tests/test_thing.py"]
_CASE_OK = [("programs.tests.test_thing", "a", "passed", None)]
_CASE_RED = [("programs.tests.test_thing", "a", "failed", None)]


def test_cli_returns_zero_and_names_the_verified_commit(tmp_path):
    r, doc = _cli(tmp_path, _GOOD_LOG, _CASE_OK, _CASE_OK, _SEL)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "LAND OK" in r.stdout
    assert doc["verdict"] == "LAND_OK"
    assert doc["verified_sha"] == SHA
    assert doc["receipt_schema"] == "vibeic.landing-acceptance.v1"
    assert doc["selected_files"] == _SEL
    claimed = doc.pop("receipt_sha256")
    assert claimed == hashlib.sha256(json.dumps(
        doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert not [key for key in doc if key.startswith("protected")], sorted(doc)


def test_candidate_aggregate_norecord_is_an_absolute_refusal(tmp_path):
    r, doc = _cli(
        tmp_path, _GOOD_LOG, _CASE_OK, _CASE_OK, _SEL,
        candidate_aggregate=False)
    assert r.returncode == 2, r.stdout + r.stderr
    assert doc["candidate_aggregate_process_present"] is False
    assert any("CANDIDATE AGGREGATE TEST SESSION" in reason
               for reason in doc["reasons"])


def test_base_aggregate_norecord_is_an_absolute_refusal(tmp_path):
    """A complete candidate cannot compensate for an unknown baseline."""
    r, doc = _cli(
        tmp_path, _GOOD_LOG, _CASE_OK, _CASE_OK, _SEL,
        base_sel=_SEL, base_aggregate=False)
    assert r.returncode == 2, r.stdout + r.stderr
    assert doc["admission"] == "INCOMPLETE"
    assert doc["base_aggregate_process_present"] is False
    assert doc["dropped_base_selected_files"] == _SEL
    assert any("BASE AGGREGATE TEST SESSION" in reason
               for reason in doc["reasons"])


def test_aggregate_only_attestations_are_sufficient_on_both_arms(tmp_path):
    r, doc = _cli(
        tmp_path, _GOOD_LOG, _CASE_OK, _CASE_OK, _SEL,
        base_sel=_SEL, candidate_per_file=False, base_per_file=False)
    assert r.returncode == 0, r.stdout + r.stderr
    assert doc["verdict"] == "LAND_OK"
    assert doc["test_evidence_mode"] == "aggregate"
    assert doc["missing_candidate_process_files"] == []
    assert doc["dropped_base_selected_files"] == []
    assert doc["missing_base_process_files"] == []
    # ...and the record says the per-file question was NOT PUT, rather than
    # leaving an empty list to be read as "asked and nothing was missing".
    assert doc["candidate_per_file_records_checked"] is False
    assert doc["base_per_file_records_checked"] is False


_SEL2 = ["programs/tests/test_alpha.py", "programs/tests/test_beta.py"]
# The candidate turned a base failure into a SKIP — the exact cheat the
# differential exists to catch.
_CASE_SILENCED_CAND = [
    ("programs.tests.test_alpha", "t_red", "skipped", "programs/tests/test_alpha.py"),
    ("programs.tests.test_beta", "t_ok", "passed", "programs/tests/test_beta.py"),
]
_CASE_BASE_WHOLE = [
    ("programs.tests.test_alpha", "t_red", "failed", "programs/tests/test_alpha.py"),
    ("programs.tests.test_beta", "t_ok", "passed", "programs/tests/test_beta.py"),
]
# The SAME base arm, stopped before `test_alpha.py` was reached.
_CASE_BASE_PARTIAL = [
    ("programs.tests.test_beta", "t_ok", "passed", "programs/tests/test_beta.py"),
]


# ============================ PER-FILE NORECORD, FROM THE REPORT (vibe-ic#1709)
#
# `pytest_per_file_junit.py` keeps a file whose session died ABSENT from the
# merged report and names it on stdout as NORECORD. Until #1709 the ONLY thing
# carrying that fact to this verdict was `gatekeeper-land.sh`'s
# `grep -qa '^NORECORD'` over the driver's combined driver/subject stdout —
# `missing_process_files` was declared in `decide`, initialised to `[]` in
# `main`, and never populated, and `junit_per_file_process_files` had no caller.
#
# These tests hold the structured path in BOTH directions: a complete candidate
# must LAND (the fix is not a ban) and an incomplete one must REFUSE and NAME
# the file (the fix is not a check that cannot fail).


def _drop_per_file_attestation(file_name):
    """A candidate report whose per-file record for *file_name* was LOST."""
    def mutate(path):
        root = ET.parse(str(path)).getroot()
        for suite in list(root):
            if suite.get("name") == f"{file_name}::process_exit":
                root.remove(suite)
        ET.ElementTree(root).write(str(path), encoding="utf-8",
                                   xml_declaration=True)
    return mutate


_PER_FILE_NORECORD_LOG = _GOOD_LOG.replace(
    "=== ALL GATES PASS",
    "  FAIL  targeted per-file session produced no complete record\n"
    "=== ALL GATES PASS")


def test_a_candidate_per_file_norecord_is_named_from_structured_junit(tmp_path):
    """THE PAIRED GUARD FOR #1709, as one test so neither half can rot alone.

    Same land log, same selection, same trees, same base arm. The ONE
    difference is whether the candidate report carries a per-file record for
    every selected file.

    MEASURED on 7c376e348, before the structured path was connected:

        complete   -> rc=0  LAND OK
        one lost   -> rc=0  LAND OK    <-- and `missing_candidate_process_files`
                                           was `[]`, so nothing named the file
    """
    complete_dir = tmp_path / "complete"
    complete_dir.mkdir()
    r_ok, doc_ok = _cli(complete_dir, _GOOD_LOG, _CASE_BASE_WHOLE,
                        _CASE_BASE_WHOLE, _SEL2, base_sel=_SEL2)
    assert r_ok.returncode == 0, r_ok.stdout + r_ok.stderr
    assert doc_ok["verdict"] == "LAND_OK"

    lost_dir = tmp_path / "lost"
    lost_dir.mkdir()
    r_bad, doc_bad = _cli(
        lost_dir, _GOOD_LOG, _CASE_BASE_WHOLE, _CASE_BASE_WHOLE, _SEL2,
        base_sel=_SEL2,
        candidate_mutator=_drop_per_file_attestation(_SEL2[0]))
    # THE DECISION FIRST. On a tree where the structured path is not connected
    # this is the assertion that fires, and it names the defect rather than a
    # missing record key.
    assert r_bad.returncode == 2, r_bad.stdout + r_bad.stderr
    assert doc_bad["admission"] == "INCOMPLETE"
    assert doc_bad["verdict"] == "REFUSE"
    # NAMED, not merely refused. A refusal that cannot say what is missing
    # sends the next reader looking in the wrong place.
    assert any(_SEL2[0] in reason and "PER-FILE SESSION RECORD" in reason
               for reason in doc_bad["reasons"]), doc_bad["reasons"]
    assert doc_bad["missing_candidate_process_files"] == [_SEL2[0]]
    # ...and the same evidence machine-readably, on both halves.
    assert doc_ok["candidate_per_file_records_checked"] is True
    assert doc_ok["missing_candidate_process_files"] == []
    assert doc_ok["test_evidence_mode"] == "aggregate+per-file"


def test_a_per_file_norecord_is_not_excused_by_the_same_gate_label_on_the_base(
        tmp_path):
    """THE WORSE HALF, and the reason this is a REASON and not a gate label.

    `gatekeeper-land.sh` prints `FAIL targeted per-file session produced no
    complete record` from a grep over the driver's stdout. That is a LABEL, so
    it goes through the per-label base differential — and a hang that fires on
    BOTH arms is exactly the shape `pytest_per_file_junit.py` was written for.

    MEASURED on 7c376e348 with that label on both land logs:

        rc=0  LAND OK  — "gate fails on the base too, so it is not this
                          branch's"

    which is the pre-existing/false-clean the driver's own docstring rejects a
    synthetic red testcase to avoid. The structured refusal is absolute.
    """
    (tmp_path / "base_land.log").write_text(_PER_FILE_NORECORD_LOG)
    r, doc = _cli(
        tmp_path, _PER_FILE_NORECORD_LOG, _CASE_BASE_WHOLE, _CASE_BASE_WHOLE,
        _SEL2, base_sel=_SEL2,
        candidate_mutator=_drop_per_file_attestation(_SEL2[0]),
        extra=("--base-land-log", str(tmp_path / "base_land.log")))
    assert r.returncode == 2, r.stdout + r.stderr
    assert doc["admission"] == "INCOMPLETE"
    assert doc["missing_candidate_process_files"] == [_SEL2[0]]
    assert any(_SEL2[0] in reason for reason in doc["reasons"]), doc["reasons"]
    # The label itself IS excused as pre-existing — that is the point. The
    # refusal must survive that, from evidence the console cannot forge.
    assert not any("targeted per-file session" in reason
                   for reason in doc["reasons"]), doc["reasons"]


def test_a_base_per_file_norecord_is_named_and_refused(tmp_path):
    """#1443's law, applied to the arm that is allowed to excuse things.

    `silenced` and `weakened` are read off what was RED (or passing) ON THE
    BASE, so a base file with no record is a base failure the branch may delete
    for free. The candidate here is complete: only the baseline lost a record.
    """
    r, doc = _cli(
        tmp_path, _GOOD_LOG, _CASE_BASE_WHOLE, _CASE_BASE_WHOLE, _SEL2,
        base_sel=_SEL2,
        base_mutator=_drop_per_file_attestation(_SEL2[1]))
    assert r.returncode == 2, r.stdout + r.stderr
    assert doc["admission"] == "INCOMPLETE"
    assert doc["missing_base_process_files"] == [_SEL2[1]]
    assert doc["missing_candidate_process_files"] == []
    assert any(_SEL2[1] in reason and "ON THE BASE" in reason
               for reason in doc["reasons"]), doc["reasons"]


def test_the_per_file_question_is_only_asked_of_a_report_that_claims_it(
        tmp_path):
    """THE FALSE-POSITIVE CONTROL. Per-file sessions are diagnostic recovery,
    so a healthy landing carries NO per-file evidence. Demanding one
    attestation per selected file unconditionally — which is what the
    superseded #1689 did, on a driver that ran per-file sessions every time —
    would refuse every landing on this driver. A gate that refuses every
    landing is a ban, and a ban teaches the operator to bypass it.
    """
    p = tmp_path / "aggregate-only.xml"
    _junit(tmp_path, _CASE_BASE_WHOLE, "aggregate-only.xml")
    _attest_junit(p, _CASE_BASE_WHOLE, _SEL2, per_file=False)
    assert V.per_file_record_gaps(p, _SEL2, True) is None

    complete = tmp_path / "both.xml"
    _junit(tmp_path, _CASE_BASE_WHOLE, "both.xml")
    _attest_junit(complete, _CASE_BASE_WHOLE, _SEL2)
    assert V.per_file_record_gaps(complete, _SEL2, True) == []

    _drop_per_file_attestation(_SEL2[0])(complete)
    assert V.per_file_record_gaps(complete, _SEL2, True) == [_SEL2[0]]
    # A LOST AGGREGATE ASKS TOO, even with no per-file evidence at all: that is
    # the recovery path, and it is the one that has files to name.
    assert V.per_file_record_gaps(p, _SEL2, False) == sorted(_SEL2)



def test_a_partial_base_arm_cannot_clear_a_silenced_failure(tmp_path):
    """THE #1443 REPRODUCTION, END TO END, AS A PAIR.

    Two runs. Same candidate report, same land logs, same selection, same trees.
    The ONLY difference is whether arm A ran both files it was asked for.

    Measured on `3d13e2c59` before this check existed:

        base COMPLETE -> rc=1  REFUSE  1 FAILING TEST(S) WERE SILENCED
        base PARTIAL  -> rc=0  LAND OK              <-- the branch lands the cheat

    Both must now refuse, and the partial arm must say WHY it could not answer
    rather than answering wrongly."""
    whole_dir = tmp_path / "whole"
    whole_dir.mkdir()
    r_whole, doc_whole = _cli(whole_dir, _RED_TEST_TIER_LOG, _CASE_BASE_WHOLE,
                              _CASE_SILENCED_CAND, _SEL2, base_sel=_SEL2)
    assert r_whole.returncode == 1, r_whole.stdout + r_whole.stderr
    assert doc_whole["delta"]["silenced"] == [
        "pytest_aggregate.programs.tests.test_alpha::t_red"]
    assert doc_whole["dropped_base_selected_files"] == []

    part_dir = tmp_path / "partial"
    part_dir.mkdir()
    r_part, doc_part = _cli(part_dir, _RED_TEST_TIER_LOG, _CASE_BASE_PARTIAL,
                            _CASE_SILENCED_CAND, _SEL2, base_sel=_SEL2)
    assert r_part.returncode != 0, (
        "a base arm that ran one of its two files still cleared a silenced "
        "failure: " + r_part.stdout + r_part.stderr)
    assert doc_part["verdict"] == "REFUSE"
    assert doc_part["dropped_base_selected_files"] == \
        ["programs/tests/test_alpha.py"]
    assert any("ON THE BASE" in r for r in doc_part["reasons"]), doc_part["reasons"]
    # The silencing itself is INVISIBLE to the partial arm — which is the whole
    # point. The refusal is the only thing standing between it and a landing.
    assert doc_part["delta"]["silenced"] == []


def test_per_file_base_diagnostics_cannot_fill_aggregate_coverage(tmp_path):
    """A fallback record for beta cannot make a partial base aggregate whole."""
    def drop_beta_from_aggregate(path):
        root = ET.parse(str(path)).getroot()
        for suite in root.iter("testsuite"):
            if not (suite.get("name") or "").startswith("aggregate::"):
                continue
            for tc in list(suite):
                if tc.get("file") == _SEL2[1]:
                    suite.remove(tc)
        ET.ElementTree(root).write(str(path), encoding="utf-8",
                                   xml_declaration=True)

    r, doc = _cli(
        tmp_path, _GOOD_LOG, _CASE_BASE_WHOLE, _CASE_SILENCED_CAND,
        _SEL2, base_sel=_SEL2, base_mutator=drop_beta_from_aggregate)

    assert r.returncode == 2, r.stdout + r.stderr
    assert doc["admission"] == "INCOMPLETE"
    assert doc["dropped_base_selected_files"] == [_SEL2[1]]
    assert any("ON THE BASE" in reason for reason in doc["reasons"])


def test_a_base_arm_asked_for_files_that_produced_no_report_is_refused(tmp_path):
    """The #1378 shape — a DEAD base arm — through the same door. `--timeout-
    method=thread` kills pytest outright, so the junit is never written at all.
    Asked for two files and producing no report is the partial case at N."""
    (tmp_path / "land.log").write_text(_RED_TEST_TIER_LOG)
    (tmp_path / "sel.txt").write_text("\n".join(_SEL2) + "\n")
    (tmp_path / "sel_base.txt").write_text("\n".join(_SEL2) + "\n")
    cj = _junit(tmp_path, _CASE_SILENCED_CAND, "cand.xml")
    r = _pr.run(
        [sys.executable, str(_PROG),
         "--base-sha", SHA, "--base-tree", TREE,
         "--head-sha", SHA, "--verified-sha", SHA,
         "--rebase-status", "ok", "--expected-tree", TREE,
         "--verified-tree", TREE, "--github-tree", TREE,
         "--land-log", str(tmp_path / "land.log"),
         "--selection", str(tmp_path / "sel.txt"),
         "--base-selection", str(tmp_path / "sel_base.txt"),
         "--base-junit", str(tmp_path / "never_written.xml"),
         "--candidate-junit", str(cj),
         "--json", str(tmp_path / "v.json")],
        capture_output=True, text=True)
    doc = json.loads((tmp_path / "v.json").read_text())
    assert r.returncode != 0, r.stdout + r.stderr
    assert doc["dropped_base_selected_files"] == sorted(_SEL2)
    assert any("ON THE BASE" in x for x in doc["reasons"]), doc["reasons"]


def test_a_test_file_the_pr_adds_is_not_read_as_a_partial_base_arm(tmp_path):
    """THE SECOND FALSE-POSITIVE CONTROL, and the reason the base arm gets its
    OWN list. `--selection` holds files the PR ADDS, which cannot exist at the
    base; asking about them here would refuse every PR that brings a test file.
    `--base-selection` is the selection already filtered to what exists there —
    the same file `gatekeeper-verify-merge.sh` builds for arm A1."""
    r, doc = _cli(tmp_path, _GOOD_LOG, _CASE_BASE_WHOLE, _CASE_BASE_WHOLE + [
        ("programs.tests.test_brand_new", "t_new", "passed",
         "programs/tests/test_brand_new.py")],
        _SEL2 + ["programs/tests/test_brand_new.py"], base_sel=_SEL2)
    assert doc["dropped_base_selected_files"] == [], doc["reasons"]
    assert not any("ON THE BASE" in x for x in doc["reasons"]), doc["reasons"]
    assert r.returncode == 0, r.stdout + r.stderr


def test_a_caller_supplying_no_base_selection_is_told_the_check_did_not_fire(
        tmp_path):
    """`base_selection_size == 0` and an empty dropped list are the SAME two
    values a clean base arm produces, so the record must be readable without
    guessing which one happened. Missing coverage is now an incomplete refusal."""
    r, doc = _cli(tmp_path, _GOOD_LOG, _CASE_OK, _CASE_OK, _SEL, base_sel=None)
    assert r.returncode == 2, r.stdout + r.stderr
    assert doc["admission"] == "INCOMPLETE"
    assert doc["base_selection_size"] == 0
    assert any("completeness was NOT checked" in n for n in doc["notes"]), \
        doc["notes"]


def test_the_verify_script_hands_the_verdict_arm_as_own_selection():
    """The wiring, asserted on the script rather than assumed. Arm A1 runs
    `selection_base.txt`; the verdict has to be told that is what was asked, or
    the check above can never fire in production."""
    body = "\n".join(l for l in _VERIFY.read_text(encoding="utf-8").splitlines()
                     if not l.lstrip().startswith("#"))
    assert "--base-selection" in body, \
        "the verdict is not told what arm A was asked to run"
    assert 'selection_base.txt' in body
    # ...and the file must exist even when the run short-circuits, or the flag
    # points at nothing and the disclosure is the one that fires.
    assert body.count(': > "$RUN/selection_base.txt"') >= 1
    assert "--candidate-test-worktree-status" in body
    assert "--base-test-worktree-status" in body
    assert 'materialize_hermetic_git_subject' in body
    assert '"$REPO" "$VERIFIED_SHA" "$CAND_SUBJECT"' in body
    assert '"$REPO" "$BASE_SHA" "$BASE_SUBJECT"' in body
    assert 'hermetic_landing_arm_receipt.py' in body
    assert 'validate_hermetic_arm_record "$B1_RUNNER_RC"' in body
    assert 'validate_hermetic_arm_record "$A1_RUNNER_RC"' in body
    assert 'publish_validated_arm_artifact "$B1_VALIDATION"' in body
    assert 'publish_validated_arm_artifact "$A1_VALIDATION"' in body
    assert 'gatekeeper-base-test-cache-schema=4-exact-tree' not in body
    assert 'B1_WORKTREE_STATUS=clean' in body
    assert 'A1_WORKTREE_STATUS=clean' in body
    assert body.index('A1_WORKTREE_STATUS=clean') > body.index(
        'validate_hermetic_arm_record "$A1_RUNNER_RC"'), \
        "unvalidated base-test evidence can still reach the verdict"


def test_cli_returns_one_on_a_new_failure(tmp_path):
    r, doc = _cli(tmp_path, _RED_TEST_TIER_LOG, _CASE_OK, _CASE_RED, _SEL)
    assert r.returncode == 1, r.stdout
    assert doc["verdict"] == "REFUSE"
    assert "pytest_aggregate.programs.tests.test_thing::a" in \
        doc["delta"]["new_failures"]
    assert any(key.startswith("pytest_aggregate_process::")
               for key in doc["delta"]["new_failures"])


def test_cli_returns_two_when_the_candidate_report_is_absent(tmp_path):
    (tmp_path / "land.log").write_text(_GOOD_LOG)
    (tmp_path / "sel.txt").write_text("programs/tests/test_thing.py\n")
    r = _pr.run(
        [sys.executable, str(_PROG), "--base-sha", SHA, "--base-tree", TREE,
         "--head-sha", SHA,
         "--verified-sha", SHA, "--rebase-status", "ok",
         "--expected-tree", TREE, "--verified-tree", TREE,
         "--land-log", str(tmp_path / "land.log"),
         "--selection", str(tmp_path / "sel.txt"),
         "--base-junit", str(tmp_path / "nope.xml"),
         "--candidate-junit", str(tmp_path / "nope.xml")],
        capture_output=True, text=True)
    assert r.returncode == 2, r.stdout + r.stderr


def test_cli_discloses_that_the_branch_edits_its_own_gate(tmp_path):
    r, doc = _cli(tmp_path, _GOOD_LOG, _CASE_OK, _CASE_OK, _SEL,
                  extra=("--gate-edited", "tools/gatekeeper-land.sh"))
    assert r.returncode == 0
    assert doc["gate_edited"] == ["tools/gatekeeper-land.sh"]
    assert any("edits the gate that judges it" in n for n in doc["notes"])


# ======================================= THE SHELL SCRIPT HAS NO OWN OPINION


def test_the_shell_script_defers_the_decision_to_the_program():
    src = _VERIFY.read_text(encoding="utf-8")
    assert "landing_merge_verdict.py" in src
    # It exits on the program's rc and does not compute a verdict of its own.
    assert 'exit "$RC"' in src
    body = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert "gatekeeper-land.sh" in body, "the existing gates must be INVOKED"


def test_the_judge_is_not_supplied_by_the_subject():
    """§4.05, one level up: the oracle may not be readable by the design. A PR can
    change what its GATES check — they ship with the tree and a PR that adds one
    should be covered by it — but it must not be able to change what counts as a
    REFUSAL. The verifier therefore rematerializes and raw-attests the exact
    BASE-owned judge after candidate process census reaches zero; no subject or
    mutable caller-worktree fallback is landing authority."""
    src = _VERIFY.read_text(encoding="utf-8")
    body = [l for l in src.splitlines()
            if "landing_merge_verdict.py" in l and not l.lstrip().startswith("#")]
    assert body, "the script never names the verdict program"
    assert any("TRUSTED_REPO" in l for l in body), \
        "the verdict program is not resolved from the raw-attested base snapshot"
    # ...and the disclosure exists for the case where the branch edits the gates.
    assert "--gate-edited" in src


def test_the_forge_cross_check_is_dropped_when_the_forge_merged_another_base():
    """A FALSE REFUSAL IS THE SAME DEFECT AS A FALSE PASS, and this one was found
    by running the script against a real open PR.

    `refs/pull/<n>/merge` is the merge of the PR head into the tip of the branch
    the PR TARGETS. Asked about any other base it is not a second opinion, it is a
    different question — and the first real run printed a confident
    `THE FORGE DISAGREES` about a PR that was fine. The cross-check now applies
    only when the forge's own first parent IS the base being verified, and says so
    when it does not."""
    src = _VERIFY.read_text(encoding="utf-8")
    body = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert 'rev-parse "$MERGE_REF^1"' in body, \
        "the forge's own base is never read, so it cannot be compared"
    assert '[ "$FORGE_BASE" = "$BASE_SHA" ]' in body, \
        "the forge tree is used without checking which base it is about"
    assert "answers a different question" in src, \
        "the drop is silent; a cross-check that did not happen must say so"


def test_a_range_scoped_gate_cannot_be_waived_by_a_vacuous_base_failure():
    """FOUND BY THE FIRST REAL LAND-OK RUN, in its own output. Arm A2 measures the
    base over an EMPTY range on purpose, and `landing_is_one_commit_check` answers
    `[FAIL] NOTHING to land` over `X..X` — so `landing is one commit` appeared in
    the base's FAILING set, which is the set that EXCUSES a candidate failure. A
    real one-commit violation would have been waived as pre-existing.

    Fixed at the source: the landing-shape gate now SKIPs over an empty range, the
    way the range-scoped block above it already did. The verdict additionally
    DISCLOSES the boundary rather than leaving the reader to trust it."""
    land = _LAND.read_text(encoding="utf-8")
    body = "\n".join(l for l in land.splitlines() if not l.lstrip().startswith("#"))
    assert 'GK_RANGE_N' in body, "the landing-shape gate does not look at the range size"
    assert 'if [ "$GK_RANGE_N" = "0" ]; then' in body, \
        "an empty range still reaches the one-commit checker, which FAILs vacuously"
    base = _gate_log(("SKIP", "landing shape — range is empty, so there is no "
                              "landing to shape"),
                     ("FAIL", "repo hygiene gates"))
    cand = _gate_log(("FAIL", "landing is one commit"),
                     ("FAIL", "repo hygiene gates"),
                     ("PASS", "targeted tests (3 file(s))"))
    v = _decide(land=cand, base_land=base)
    assert v.ok is False, "a range-scoped failure was waived"
    assert any("landing is one commit" in r for r in v.reasons)
    assert any("empty range" in n for n in v.notes), \
        "the boundary on what the base arm can excuse is not disclosed"


def test_the_base_gate_cache_is_disabled_at_the_adversarial_boundary():
    """A candidate that learns RUN must not plant baseline evidence in a cache.

    Reuse can return only after cache bundles are authenticated outside the
    subject's writable lifetime.  Until then the base is intentionally measured
    after both candidate containers have exited and been removal-proved.
    """
    src = _VERIFY.read_text(encoding="utf-8")
    body = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert 'base-gate cache disabled for adversarial differential ownership' in body
    assert 'BASE_GATE_CACHE=""' in body
    assert 'CACHED_MANIFEST' not in body
    assert 'A2_CACHE_LOCK_FD' not in body
    assert body.index('wait "$B2_PID"') < body.index('\n  prepare_base_wave\n')


def test_the_critical_path_does_not_run_targeted_tests_inside_a2_again():
    src = _VERIFY.read_text(encoding="utf-8")
    body = "\n".join(line for line in src.splitlines()
                     if not line.lstrip().startswith("#"))
    runner = (_REPO_ROOT / "tools/ci/hermetic_candidate_runner.py").read_text()
    assert '"GATEKEEPER_SKIP_TARGETED_TESTS": "1"' in runner
    assert '"GATEKEEPER_NO_STAMP": "1"' in runner
    assert body.count("launch_hermetic_test_arm") >= 3  # definition + A1/B1
    assert body.count("launch_hermetic_land_arm") >= 3  # definition + A2/B2


def test_the_gate_tier_is_compared_against_the_base_not_asserted():
    """The script must supply arm A2. Without `--base-land-log` the verdict
    degrades to absolute, and two hygiene gates are red on `main` — so the
    absolute rule is a ban and this wiring is what keeps it a check."""
    src = _VERIFY.read_text(encoding="utf-8")
    assert "--base-land-log" in src
    assert "base_land.log" in src


def test_neither_arm_can_read_the_others_scratch_file():
    """Running `gatekeeper-land.sh` for the BASE and the CANDIDATE at the same
    time made two pre-existing fixed `/tmp` names live: the targeted SELECTION
    and the commit-message dump. Two arms sharing either one would each have
    answered about the other's tree — a gate quietly measuring the wrong thing,
    which is the defect class this file is about."""
    land = _LAND.read_text(encoding="utf-8")
    body = "\n".join(l for l in land.splitlines() if not l.lstrip().startswith("#"))
    assert "/tmp/gk_sel.txt" not in body
    assert "/tmp/gk_commit_text.txt" not in body
    assert "mktemp" in body
    verify = _VERIFY.read_text(encoding="utf-8")
    vbody = "\n".join(l for l in verify.splitlines()
                      if not l.lstrip().startswith("#"))
    assert 'HEAD_REF="refs/gk-verify/$RUN_ID/head"' in vbody, \
        "two concurrent verifications would fetch over one another's head ref"


def _shell_function(source: str, name: str) -> str:
    """The exact text of one top-level `name() { ... }` shell function."""
    opening = f"{name}() {{\n"
    start = source.index(opening)
    end = source.index("\n}\n", start)
    return source[start:end + len("\n}\n")]


def test_a_missing_receipt_quotes_the_arms_own_refusal_not_only_the_symptom(
        tmp_path):
    """THREE DIFFERENT CAUSES REDUCED TO ONE SENTENCE, measured in one evening.

    When an arm writes no receipt, the validator can only say `cannot resolve
    runner receipt: [Errno 2] No such file or directory`, and that same line
    was what a reader saw for `subject would expose the host HOME to the
    candidate` (TMPDIR under $HOME), for `cannot start Docker CLI` (a runtime
    with no engine), and for `candidate ended without the exact semantic
    terminal record` (the progress-scan defect). The runner's own log holds the
    distinguishing line and is deleted with the run directory, so it has to be
    quoted at the refusal or it is gone.

    Asserted against the script's OWN function text, and both ways: a log that
    exists must be quoted, and a log that does not exist must be NAMED as
    absent -- "I could not run it" may not read the same as "I ran it and it
    failed"."""
    driver = tmp_path / "driver.sh"
    driver.write_text(
        "set -uo pipefail\n"
        'RUN="$1"\n'
        + _shell_function(_VERIFY.read_text(encoding="utf-8"),
                          "arm_norecord_diagnosis")
        + 'arm_norecord_diagnosis B1 "$2"\n')
    run = tmp_path / "run"
    run.mkdir()
    record_log = tmp_path / "record.log"
    record_log.write_text(
        "[NORECORD] hermetic landing arm receipt: cannot resolve runner "
        "receipt: [Errno 2] No such file or directory\n")

    absent = _pr.run(
        ["bash", str(driver), str(run), str(record_log)],
        capture_output=True, text=True)
    assert "b1-runner.log" in absent.stderr, absent.stderr
    assert "did not even start" in absent.stderr, absent.stderr

    (run / "b1-runner.log").write_text(
        "[NORECORD] hermetic candidate: subject would expose the host HOME "
        "to the candidate\n")
    quoted = _pr.run(
        ["bash", str(driver), str(run), str(record_log)],
        capture_output=True, text=True)
    assert "would expose the host HOME" in quoted.stderr, quoted.stderr
    assert "cannot resolve runner receipt" in quoted.stderr, quoted.stderr


def test_reading_one_arms_exit_code_cannot_byte_compile_the_shared_runtime(
        tmp_path):
    """THE INSTRUMENT WROTE INTO THE THING IT WAS MEASURING.

    `validated_arm_exit` imports the arm-receipt helper OUT OF the BASE
    runtime snapshot, and that snapshot's TREE DIGEST is what every later arm's
    receipt is re-checked against.  It is invoked with
    `PYTHONDONTWRITEBYTECODE=1 python3 -I`, which reads as belt and braces and
    is neither: `-I` implies `-E`, so the interpreter IGNORES every PYTHON*
    variable including that one.  The first call therefore byte-compiled the
    helper into `<runtime>/tools/ci/__pycache__/`, the runtime grew by a file,
    and the NEXT validation refused with "receipt runtime digest differs from
    the current input" -> "B2 arm receipt is NORECORD".  B1 validates first, so
    on main every branch lost its B2, A1 and A2 arms to the act of reading B1's
    exit code.  Measured on the fixture: runtime files 57 -> 58.

    Asserted BEHAVIOURALLY, against the script's own function text: a flag
    assertion would pass on `-B` written into a comment, and the property that
    matters is that the tree the reader imported from is byte-identical
    afterwards.  The call is expected to FAIL here (there is no valid record);
    the pollution happens during the import, before the record is ever read.
    """
    runtime = tmp_path / "runtime" / "tools" / "ci"
    runtime.mkdir(parents=True)
    for name in ("hermetic_landing_arm_receipt.py",
                 "landing_record_primitives.py"):
        shutil.copy2(_REPO_ROOT / "tools" / "ci" / name, runtime / name)
    before = sorted(path.name for path in runtime.iterdir())

    driver = tmp_path / "driver.sh"
    driver.write_text(
        "set -uo pipefail\n"
        + _shell_function(_VERIFY.read_text(encoding="utf-8"),
                          "validated_arm_exit")
        + 'validated_arm_exit "$1" "$2"\n')
    _pr.run(
        ["bash", str(driver), str(runtime / "hermetic_landing_arm_receipt.py"),
         str(tmp_path / "no-such-record.json")],
        capture_output=True, text=True)

    assert sorted(path.name for path in runtime.iterdir()) == before, \
        "reading an arm's exit code changed the runtime tree it read from"
    assert not list(runtime.rglob("__pycache__")), \
        "the arm-exit reader byte-compiled the BASE runtime snapshot"


def test_the_candidate_arm_runs_without_a_maxfail_bound():
    """FOUND BY RUNNING AGAINST A REAL OPEN PR. `--maxfail=10` is right for the
    push path — stop early, the answer is "go fix it" — and WRONG for a
    differential, which needs the whole failed set and not a prefix of one.

    Measured on PR #1028 (137 selected files, 3242 tests at the base, which is
    itself 47 red): the bound stopped the candidate at 1437 tests and the verdict
    correctly refused as unmeasurable. A landing gate that cannot answer for a
    wide PR is a landing gate nobody uses, so the verify script lifts the bound
    for its own arm and the push path keeps it."""
    land = _LAND.read_text(encoding="utf-8")
    lbody = "\n".join(l for l in land.splitlines() if not l.lstrip().startswith("#"))
    assert 'GATEKEEPER_PYTEST_MAXFAIL:-10' in lbody, \
        "the default is no longer 10, so the push path changed"
    assert '"${GATEKEEPER_PYTEST_MAXFAIL:-10}" = "0" ] && maxfail=()' in lbody
    entry = (_REPO_ROOT / "tools/ci/hermetic_test_arm_entry.sh").read_text()
    driver = (_PROGRAMS / "pytest_per_file_junit.py").read_text()
    assert "--aggregate-only" in entry
    assert "--stop-after-failures" not in entry
    assert 'add_argument("--stop-after-failures", type=int, default=0' in driver, \
        "the candidate aggregate arm still truncates, so the differential cannot be computed"
    # ...and a truncated run must remain a refusal, not a pass, for the cases the
    # bound cannot be lifted (a foreign land.sh that predates the hook).
    assert _decide(truncated=True, dropped_files=["programs/tests/test_x.py"]).ok \
        is False


def test_the_junit_hook_in_the_landing_script_changes_no_verdict():
    """`GATEKEEPER_PYTEST_JUNIT` may only ADD a report. If it ever gated
    anything, the merge path and the push path would stop agreeing."""
    src = _LAND.read_text(encoding="utf-8")
    assert "GATEKEEPER_PYTEST_JUNIT" in src
    for line in src.splitlines():
        if "GATEKEEPER_PYTEST_JUNIT" in line and not line.lstrip().startswith("#"):
            assert "FAILED=1" not in line, line


def test_the_version_deferral_still_refuses_a_backwards_version():
    """The deferral is `--version-by-gatekeeper`, which the program already
    ships: no-change PASSes, BACKWARDS still FAILs. Turning the gate OFF would
    have traded an unsatisfiable gate for an unguarded one."""
    src = _LAND.read_text(encoding="utf-8")
    assert "--version-by-gatekeeper" in src
    r = _pr.run(
        [sys.executable, str(_PROGRAMS / "version_bump_monotonic_check.py"),
         "--current", "1.0.0", "--previous", "2.0.0", "--version-by-gatekeeper"],
        capture_output=True, text=True)
    assert r.returncode != 0, r.stdout + r.stderr


# ============================================ END TO END, ON A REAL GIT REPO
#
# The negative control #1019 asks for by name: a branch whose DIFF is innocuous
# and which leaves a test red. That is the shape that got through five times —
# nothing in the diff looks like a test change, and no gate ran the tests.


_STUB_SELECT = """#!/usr/bin/env python3
MODE_IMPORT_EDGE = "import-edge"

def select_tests(changed_paths, plugin_root, plugin_rel, *, mode):
    assert mode == MODE_IMPORT_EDGE
    return ["programs/tests/test_thing.py"]

if __name__ == "__main__":
    print("programs/tests/test_thing.py")
"""

_STUB_LAND = r"""#!/usr/bin/env bash
# A minimal stand-in for gatekeeper-land.sh with the same OBSERVABLE contract:
# the sentinel, `  PASS  ` / `  FAIL  ` lines, a junit report when asked, and a
# stamp only when everything passed.
#
# SINCE v1.10.69 THAT CONTRACT INCLUDES THE SEMANTIC LANDING RECORD, and this
# stub carried none of it.  When the hermetic runner hands a landing arm
# VIBEIC_LANDING_PROGRESS/VIBEIC_LANDING_COMPLETION, the real
# `tools/gatekeeper-land.sh` publishes, in this exact order: one `start`
# progress row, then for each parent-owned `landing:<ARM>` unit one journal row
# AND one relayed checkpoint, then the completion record, then one `terminal`
# row — and it exits with its own FAILED flag so the receipt's exit code and
# the record's `returncode` agree.  A stub that emits none of that makes EVERY
# arm die inside the runner with "candidate ended without the exact semantic
# terminal record", which is a property of this fixture and not of the subject
# under test, so no test in this file could reach any arm at all.
#
# The unit population is READ FROM `/input/progress-plan.json`, the same
# parent-owned plan the runner validates the relay against, rather than
# hard-coded here: a stub with its own copy of the list would drift from the
# plan silently and fail as "differs from the parent-owned FSM".
set -uo pipefail
ROOT="$(git rev-parse --show-toplevel)"
PLUGIN="$ROOT/vibe-ic-marketplace/plugins/vibe-ic"
RUNTIME_ROOT="${GATEKEEPER_RUNTIME_ROOT:-$ROOT}"
FAILED=0
LANDING_RECORD_ENABLED=0
LANDING_RECORD_TOOL="$RUNTIME_ROOT/tools/ci/landing_completion_record.py"
LANDING_PROGRESS_TOOL="$RUNTIME_ROOT/tools/ci/hermetic_progress_emit.py"
LANDING_JOURNAL="${VIBEIC_LANDING_PROGRESS:-}"
LANDING_COMPLETION="${VIBEIC_LANDING_COMPLETION:-}"
LANDING_UNITS=()
if [ -n "$LANDING_JOURNAL" ] || [ -n "$LANDING_COMPLETION" ]; then
  if [ -z "$LANDING_JOURNAL" ] || [ -z "$LANDING_COMPLETION" ]; then
    echo "[NORECORD] stub landing completion environment is partial" >&2
    exit 2
  fi
  mapfile -t LANDING_UNITS < <(python3 -I -c '
import json
with open("/input/progress-plan.json", "rb") as handle:
    for unit in json.load(handle)["units"]:
        print(unit)
') || { echo "[NORECORD] stub cannot read the parent progress plan" >&2; exit 2; }
  [ "${#LANDING_UNITS[@]}" -gt 0 ] \
    || { echo "[NORECORD] parent progress plan declared no unit" >&2; exit 2; }
  python3 "$LANDING_PROGRESS_TOOL" start \
    || { echo "[NORECORD] stub landing progress could not start" >&2; exit 2; }
  LANDING_RECORD_ENABLED=1
fi

landing_record() {                  # landing_record <unit> <state> <rc>
  [ "$LANDING_RECORD_ENABLED" = "1" ] || return 0
  local unit="$1" state="$2" rc="$3" digest
  digest="$(printf 'stub-land:%s:%s:%s' "$unit" "$state" "$rc" \
            | sha256sum | awk '{print $1}')" \
    || { echo "[NORECORD] cannot digest stub landing stage $unit" >&2; exit 2; }
  python3 "$LANDING_RECORD_TOOL" append --journal "$LANDING_JOURNAL" \
    --label "$unit" --state "$state" --returncode "$rc" \
    --output-sha256 "$digest" \
    || { echo "[NORECORD] cannot attest stub landing stage $unit" >&2; exit 2; }
  python3 "$LANDING_PROGRESS_TOOL" checkpoint "$unit" \
    || { echo "[NORECORD] cannot relay stub landing stage $unit" >&2; exit 2; }
}

# The one unit whose state this stub actually MEASURES is the targeted-test
# tier; `full:repo-hygiene` follows the routed-transition branch below when it
# runs.  Everything else is a cheap gate this fixture does not model, recorded
# PASS so the journal carries the exact parent-owned population in order — the
# population is what the runner checks, and a partial journal is refused.
STUB_TARGETED_STATE=PASS
STUB_TARGETED_RC=0
STUB_HYGIENE_STATE=PASS
STUB_HYGIENE_RC=0

landing_publish() {
  [ "$LANDING_RECORD_ENABLED" = "1" ] || return 0
  local unit state rc
  for unit in "${LANDING_UNITS[@]}"; do
    state=PASS
    rc=0
    case "$unit" in
      full:targeted-tests) state="$STUB_TARGETED_STATE"; rc="$STUB_TARGETED_RC" ;;
      full:repo-hygiene)   state="$STUB_HYGIENE_STATE";  rc="$STUB_HYGIENE_RC" ;;
    esac
    [ "$state" = "FAIL" ] && FAILED=1
    landing_record "$unit" "$state" "$rc"
  done
  python3 "$LANDING_RECORD_TOOL" finish --journal "$LANDING_JOURNAL" \
    --record "$LANDING_COMPLETION" --failed "$FAILED" \
    || { echo "[NORECORD] stub landing completion is incomplete" >&2; exit 2; }
  python3 "$LANDING_PROGRESS_TOOL" terminal \
    || { echo "[NORECORD] stub landing terminal is incomplete" >&2; exit 2; }
}
# FOUR STIMULUS BRANCHES USED TO SIT HERE AND NONE OF THEM COULD EVER FIRE.
# They wrote `<ARM>.started` into GATEKEEPER_CONCURRENCY_PROBE_DIR, appended to
# the corpus under GATEKEEPER_MUTATE_BENCHMARK_ARM, pre-wrote the base wave
# under GATEKEEPER_PREWRITE_BASE_ARTIFACTS and relinked the selection under
# GATEKEEPER_RELINK_SELECTION.  MEASURED on a4caccefe: not one of those four
# names is on the hermetic launcher's `--env` allow-list, so inside an arm each
# is EMPTY and the branch is skipped; and the three that reach for the parent's
# run directory do it through GATEKEEPER_BENCHMARK_MEASUREMENT_RECORD, a name
# that occurs ZERO times in the verifier AND ZERO times in the real
# tools/gatekeeper-land.sh, so it expands to `.` — the container's read-only
# /subject.  Their four tests are rewritten against channels that exist; this
# code is deleted rather than left, because unreachable stimulus code reads to
# the next person exactly like coverage.  GATEKEEPER_STUB_ROUTED_TRANSITION
# below is NOT of that class: _routed_activation_repo rewrites that branch to
# key on committed subject content, which does reach an arm.
if [ "${GATEKEEPER_STUB_ROUTED_TRANSITION:-0}" = "1" ] \
   && { [ "${GATEKEEPER_VERIFY_ARM:-}" = "A2" ] \
        || [ "${GATEKEEPER_VERIFY_ARM:-}" = "B2" ]; }; then
  rm -f "${GATEKEEPER_HYGIENE_REPORT}.attest"
  export GATE_DISPATCH_ATTESTATION_HELPER="$PLUGIN/programs/gate_process_attestation.py"
  export GATE_DISPATCH_ATTESTATION_FILE="${GATEKEEPER_HYGIENE_REPORT}.attest"
  (
    . "$ROOT/tools/ci/_gate_dispatch.sh"
    gate_dispatch_init --summary-json "$GATEKEEPER_HYGIENE_REPORT"
    _per_routed() {
      local def="$1" cell design
      cell="${def%/phase3/stage3/pnr/routed.def}"
      verdir="$(basename "$cell")"
      design="$(basename "$(dirname "$cell")")/${verdir#*_}"
      uncheckable_until 2027-02-28 "fixture has no macro LEF"
      run_tolerating_uncheckable "macro OBS not crossed ($design)" \
        "$PLUGIN" python3 programs/macro_obs_geometry_intersect_check.py "$cell"
      uncheckable_until 2027-02-28 "fixture may have no DRC evidence"
      run_tolerating_uncheckable "DRC PASS is not vacuous ($design)" \
        "$ROOT" python3 "$PLUGIN/programs/drc_vacuous_pass_check.py" "$cell"
      uncheckable_until 2027-02-28 "fixture may have no step reports"
      run_tolerating_uncheckable "inner FAILs reach the verdict ($design)" \
        "$ROOT" python3 "$PLUGIN/programs/step_internal_fail_bubble_up_check.py" "$cell"
      uncheckable_until 2027-02-28 "fixture has no preceding same-PDK run"
      run_tolerating_uncheckable "new tool diagnostic id ($design)" \
        "$PLUGIN" python3 programs/tool_diagnostic_id_gate.py "$cell"
    }
    if [ "$GATEKEEPER_VERIFY_ARM" = "A2" ] \
       && [ "${GATEKEEPER_STUB_BASE_EXPANDED:-0}" != "1" ]; then
      gate_dispatch_over "published cells carrying a routed DEF" \
        _per_routed true
    else
      GATE_DISPATCH_ATTEST_POPULATION=1 \
      gate_dispatch_over "published cells carrying a routed DEF" \
        _per_routed python3 "$ROOT/tools/ci/routed_def_corpus.py" --repo "$ROOT"
    fi
    gate_dispatch_finish
  ) >/dev/null 2>&1 || true
  if [ ! -s "${GATEKEEPER_HYGIENE_REPORT:-}" ]; then
    echo "  FAIL  repo hygiene gates"
    echo "=== FAILURES ABOVE — no routed transition record ==="
    exit 2
  fi
  # The gate LINE is emitted with the others, after the opening sentinel: a
  # `  FAIL  ` line printed before the sentinel is outside the record the
  # verifier parses, and an arm whose log closes with ALL GATES PASS while it
  # exits 1 is refused as "no complete terminal record for rc=1".  Nothing had
  # ever run this branch under the semantic landing record to notice.
  STUB_HYGIENE_STATE=FAIL
  STUB_HYGIENE_RC=1
fi
# THE HYGIENE SUMMARY IS PART OF A LANDING ARM'S OUTPUT, always — the verifier
# seals `hygiene.json` out of both A2 and B2 with
# `publish_validated_arm_artifact`, requires `corpus_inputs.benchmark_data_sha`
# to bind the corpus it measured, and the completion record digests that exact
# file.  Only the routed-transition branch above ever wrote one, so every other
# arm had no hygiene artifact to seal.  Emit the ordinary one through the real
# dispatcher (never a hand-written JSON blob: the digest must come from the
# same emitter production uses) whenever that branch did not.
if [ -n "${GATEKEEPER_HYGIENE_REPORT:-}" ] \
   && [ ! -s "${GATEKEEPER_HYGIENE_REPORT}" ]; then
  rm -f "${GATEKEEPER_HYGIENE_REPORT}.attest"
  (
    export GATE_DISPATCH_ATTESTATION_HELPER="$PLUGIN/programs/gate_process_attestation.py"
    export GATE_DISPATCH_ATTESTATION_FILE="${GATEKEEPER_HYGIENE_REPORT}.attest"
    . "$ROOT/tools/ci/_gate_dispatch.sh"
    gate_dispatch_init --summary-json "$GATEKEEPER_HYGIENE_REPORT"
    # One real dispatched gate, not zero: `hygiene_finding_delta` requires an
    # exact bijection between the gates in PROCESS states and the process
    # attestations, so a summary with a gate and no attestation is REFUSED and
    # the verdict cannot compute the differential at all.
    run "a cheap gate" "$ROOT" true
    gate_dispatch_finish
  ) >/dev/null 2>&1 || true
  [ -s "${GATEKEEPER_HYGIENE_REPORT}" ] \
    || { echo "[NORECORD] stub hygiene summary was not produced" >&2; exit 2; }
fi
echo "=== gatekeeper landing gates — base=${GATEKEEPER_BASE:-origin/main} ==="
echo "  PASS  a cheap gate"
if [ "$STUB_HYGIENE_STATE" = "FAIL" ]; then
  echo "  FAIL  repo hygiene gates"
fi
SEL="$(mktemp -t stub_sel.XXXXXX)"
JOUT="${GATEKEEPER_PYTEST_JUNIT:-$(mktemp -t stub_junit.XXXXXX)}"
( cd "$PLUGIN" && python3 programs/ci_targeted_test_select.py --base "${GATEKEEPER_BASE:-HEAD}" ) > "$SEL"
STUB_STAMP=0
if [ "${GATEKEEPER_SKIP_TARGETED_TESTS:-0}" = "1" ]; then
  echo "  SKIP  targeted tests — measured by the independent aggregate test arm"
  STUB_TARGETED_STATE=SKIP
  STUB_TARGETED_RC=0
elif ( cd "$PLUGIN" && python3 programs/pytest_per_file_junit.py \
       --selection "$SEL" --junit "$JOUT" --stall-after 10 \
       --aggregate-check --aggregate-only --aggregate-stall-after 10 \
       -- python3 -m pytest -q --maxfail=10 >/dev/null 2>&1 ); then
  echo "  PASS  targeted tests (1 file(s))"
  echo "  REPORT  targeted test process verdicts embedded in junit"
  echo "  REPORT  targeted aggregate session completed"
  STUB_TARGETED_STATE=PASS
  STUB_TARGETED_RC=0
  STUB_STAMP=1
else
  echo "  FAIL  targeted tests (1 file(s))"
  echo "  REPORT  targeted test process verdicts embedded in junit"
  echo "  REPORT  targeted aggregate session completed"
  STUB_TARGETED_STATE=FAIL
  STUB_TARGETED_RC=1
fi
# BEFORE the closing sentinel and before any stamp, exactly where the real
# script publishes it: the journal, the completion record and the terminal
# progress row are what make this arm's evidence readable at all, and a stamp
# minted before them would claim a landing whose record does not exist.
# `landing_publish` also sets FAILED from the journal it wrote.
landing_publish
if [ "$STUB_TARGETED_STATE" = "SKIP" ] \
   && [ "${GATEKEEPER_NO_STAMP:-0}" = "1" ] \
   && [ "$FAILED" = "0" ]; then
  echo "  REPORT  merge verifier owns the independent targeted-test evidence"
  echo "=== ALL NON-TARGET GATES COMPLETE — stamp withheld for composite verdict ==="
elif [ "$FAILED" != "0" ]; then
  echo "=== FAILURES ABOVE — stamp removed; the pre-push hook will refuse ==="
else
  [ "$STUB_STAMP" = "1" ] \
    && git rev-parse HEAD > "$(git rev-parse --absolute-git-dir)/gatekeeper-stamp"
  echo "=== ALL GATES PASS — stamped $(git rev-parse --short HEAD) ==="
fi
rm -f "$SEL"
# The receipt binds the arm's natural exit code to the completion record's
# `returncode`, and the verifier refuses any pair other than 0:0 or 1:1.  The
# stub therefore has to exit with the same FAILED flag it just attested rather
# than always 0.
exit "$FAILED"
"""

# `thing.py` is ORDINARY SOURCE and `test_thing.py` pins it. The negative
# control's diff therefore touches no test file at all — which is the whole
# point: what got through five times looked like a normal source change.
_THING_SRC = "VALUE = {v}\n"
_THING_TEST = """import pathlib


# The cross-arm rendezvous that used to be here waited for `<ARM>.started`
# markers its siblings could not write: an arm is a container with network none
# and no shared writable surface, so it cannot observe another arm at all. The
# wave property is asserted host-side instead, in
# test_end_to_end_candidate_wave_precedes_parallel_isolated_base_wave.


def test_value_is_one():
    src = (pathlib.Path(__file__).resolve().parents[1] / "thing.py").read_text()
    assert "VALUE = 1" in src
"""








_BENCHMARK_TEST: dict[str, Path] = {}




# ── NORECORD HAS TO REACH THE VERDICT (rlmv) ────────────────────────────────
#
# The 23 end-to-end tests below DRIVE the container engine: they run
# `tools/gatekeeper-verify-merge.sh` for real, and it launches the B1/B2/A1/A2
# arms through `tools/ci/hermetic_candidate_runner.py`. Where there is no engine
# the runner says so, by name, in the verifier's own log:
#
#     [NORECORD] hermetic candidate: cannot execute Docker CLI:
#         [Errno 2] No such file or directory: 'docker'
#     gatekeeper-verify-merge: B1 arm receipt is NORECORD
#
# and the script exits 2. MEASURED on 88a8bcdf4d inside the digest-pinned
# runtime `ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2…`, which carries no Docker
# CLI: 23 failed, 115 passed. Every one of the 23 died on `assert
# r.returncode == 0` or `== 1` — that is, on a disclosure that said "I did not
# measure this" being read as "this code is broken". The gate was already
# honest; nothing downstream could hear it.
#
# `_judgeable` is that missing segment and NOTHING MORE. It is not a
# `which("docker")` guard: see `_hermetic_engine_capability` for why the marker
# alone is refused and why a run that blames an engine this process CAN start
# stays red. Where the engine is reachable this function does nothing at all,
# so the arms run, and a branch that deserves a refusal still gets one.








_ROUTED_GATE_MARKER = "routed-corpus-gate.enabled"
_ROUTED_ACTIVATION_MARKER = "routed-corpus-producer.activated"


















# ── waiting for the verifier by PROGRESS, not by a clock ────────────────────
#
# `proc.communicate(timeout=_T)` asked "has it been 55 seconds", which is a
# different question from "is it still working". This is an END-TO-END verifier
# driving four arms through a hermetic runner, on a host that routinely carries
# other work; a healthy wave outlives any constant somebody picks, and when it
# did, three tests called `pytest.fail("the verifier never finished")` — a red
# about the verifier, manufactured by the load on the machine.
#
# The verifier's own run directory IS the progress signal, and this file already
# relies on that: TMPDIR is pointed at a caller-owned directory, so the
# `mktemp -d -t gkverify.XXXXXX` tree and every arm artefact in it are visible
# under a known name WHILE the run is going. Files appearing, bytes growing and
# mtimes advancing are forward progress. A run that is still writing is never
# killed, however long it legitimately takes. A run that has written nothing for
# the whole grace, with its process still alive, is genuinely wedged — and that
# still FAILS these tests, which is the half that must not move.









_WAVE_ARTEFACTS = (
    "b1-runner.log", "b2-runner.log",
    "b1-hermetic-receipt.json", "b2-hermetic-receipt.json",
    "base-subject",
    "a1-runner.log", "a2-runner.log",
    "a1-hermetic-receipt.json", "a2-hermetic-receipt.json",
)














# Every A-only artefact `clear_base_wave_artifacts` names, in its own words.
_BASE_WAVE_ARTEFACTS = (
    "base.xml",
    "base_hygiene.json",
    "base_land.log",
    "base_tests.log",
    "base_hygiene_progress.jsonl",
    "selection_base.txt",
    "selection_base.after",
)
_FORGED = b"candidate planted this base artefact\n"


















    # `cleanup.reaped` IS the proof that the TERM-ignoring arm died, and it is a
    # stronger one than polling a pid the arm had to publish for itself: the
    # parent writes that event only after WAITING on every arm process group it
    # started. An arm that ignored TERM and was never escalated would leave that
    # wait outstanding for ever, the event would never appear, and this test
    # fails on the deadline above rather than passing quietly.




























# ================================================ THE TWO VERIFICATION TIERS
#
# `git merge-tree --write-tree` needs git >= 2.38. FOUR OF SIX HOSTS in this
# fleet run 2.34.1, INCLUDING the orchestrator where every `gh pr merge` is run,
# and on those the strong path never starts: `--write-tree` is read as a rev
# (`fatal: unknown rev --write-tree`), so the tree came back empty and the gate
# refused EVERY landing with THE MERGE TREE COULD NOT BE COMPUTED. Fail-closed
# and correct; a ban rather than a check.
#
# The fallback verifies the REBASE REPLAY and DISCLOSES that the squash-vs-rebase
# cross-check was not performed. What these tests refuse:
#
#   * a fallback that passes everything — worse than a gate that refuses
#     everything, so the negative control is re-run UNDER THE FALLBACK;
#   * a fallback that is disclosed only in prose — a downstream that cannot key
#     on the tier cannot act on the weakness;
#   * a fallback that is only exercised where it is needed. Forcing it with
#     `GATEKEEPER_FORCE_REBASE_REPLAY=1` runs this branch on EVERY host, so the
#     untested path is removed rather than moved;
#   * a tier that can change an answer rather than only report what it checked.


_FALLBACK = {"GATEKEEPER_FORCE_REBASE_REPLAY": "1"}




# ------------------------------------------------- the decision, both tiers


def test_an_unrecognised_tier_refuses_rather_than_inheriting_the_strong_silence():
    """A third tier arriving by typo must not be read as the strong one. If the
    gate cannot say WHAT was verified, nothing was."""
    v = _decide(verification_tier="merge_tree")      # underscore, not hyphen
    assert v.ok is False
    assert v.unmeasurable is True
    assert any("UNKNOWN VERIFICATION TIER" in r for r in v.reasons), v.reasons
    assert "VERIFICATION_TIER_UNKNOWN" in v.disclosures


def test_the_fallback_tier_discloses_the_cross_check_it_did_not_perform():
    v = _decide(verification_tier=V.TIER_REBASE_REPLAY, git_version="2.34.1",
                tier_reason="git 2.34.1 does not support `merge-tree --write-tree`")
    assert v.ok is True, v.reasons          # PAIRED: a clean candidate still lands
    assert "SQUASH_VS_REBASE_CROSS_CHECK_NOT_PERFORMED" in v.disclosures
    assert "VERIFICATION_TIER_REBASE_REPLAY" in v.disclosures
    # NAMES THE VERSION FOUND AND THE VERSION NEEDED, so the refusal/disclosure
    # is actionable rather than just true.
    prose = " ".join(v.notes)
    assert "2.34.1" in prose and V.MERGE_TREE_MIN_VERSION in prose, prose


def test_the_strong_tier_records_that_the_cross_check_was_performed():
    """The other side of the disclosure. Without this the fallback's code could
    be emitted unconditionally and nothing would notice."""
    v = _decide()
    assert v.ok is True
    assert "SQUASH_VS_REBASE_CROSS_CHECK_PERFORMED" in v.disclosures
    assert "VERIFICATION_TIER_MERGE_TREE" in v.disclosures
    assert "SQUASH_VS_REBASE_CROSS_CHECK_NOT_PERFORMED" not in v.disclosures


def test_the_fallback_still_refuses_a_new_failure_this_branch_owns():
    """The decision-level half of the paired guard. A FALLBACK THAT PASSES
    EVERYTHING IS WORSE THAN A GATE THAT REFUSES EVERYTHING."""
    v = _decide(verification_tier=V.TIER_REBASE_REPLAY,
                delta=_delta(new_failures=["m::t"]))
    assert v.ok is False
    assert any("NEW FAILURE" in r for r in v.reasons), v.reasons


def test_the_fallback_still_refuses_when_the_replay_itself_conflicted():
    """The fallback adopts the replay as the tree under test ONLY when the replay
    succeeded. A conflicted rebase leaves it empty and must still refuse as
    UNMEASURABLE — the fallback trades away a cross-check, never fail-closed."""
    v = _decide(verification_tier=V.TIER_REBASE_REPLAY,
                rebase_status="conflict", expected_tree="")
    assert v.ok is False and v.unmeasurable is True
    assert any("REBASE CONFLICT" in r for r in v.reasons), v.reasons
    assert any("COULD NOT BE COMPUTED" in r for r in v.reasons), v.reasons
    # The refusal still says which tier could not answer.
    assert "VERIFICATION_TIER_REBASE_REPLAY" in v.disclosures


@pytest.mark.parametrize("over,expected_ok", [
    ({}, True),
    ({"delta": _delta(new_failures=["m::t"])}, False),
    ({"delta": _delta(silenced=["m::t"])}, False),
    ({"rebase_status": "conflict"}, False),
    ({"verified_tree": OTHER_TREE}, False),
    ({"truncated": True}, False),
    ({"dropped_files": ("programs/tests/test_x.py",)}, False),
    ({"base_dropped_files": ("programs/tests/test_x.py",)}, False),
    ({"land": V.parse_land_log(_GOOD_LOG.replace("PASS  repo hygiene gates",
                                                 "FAIL  repo hygiene gates"))},
     False),
])
def test_the_tier_reports_what_it_checked_and_never_changes_the_answer(
        over, expected_ok):
    """THE PROPERTY THAT MAKES THE FALLBACK SAFE, stated as an assertion.

    For every fact the verdict turns on, BOTH tiers reach the SAME answer. The
    degraded tier is allowed to say what it could not check; it is not allowed to
    excuse anything it did check. If this ever fails, the fallback has become a
    way to land something the strong tier refuses."""
    strong = _decide(verification_tier=V.TIER_MERGE_TREE, **over)
    weak = _decide(verification_tier=V.TIER_REBASE_REPLAY, **over)
    assert strong.ok is expected_ok, strong.reasons
    assert weak.ok is strong.ok, (weak.reasons, strong.reasons)
    assert weak.reasons == strong.reasons, (weak.reasons, strong.reasons)


# ------------------------------------------------------ the record, both tiers


def test_the_cli_record_tells_the_two_tiers_apart_machine_readably(tmp_path):
    """DISCLOSED IN PROSE IS NOT ENOUGH. A downstream reader keys on these."""
    r, doc = _cli(tmp_path, _GOOD_LOG, _CASE_OK, _CASE_OK, _SEL,
                  extra=("--verification-tier", V.TIER_REBASE_REPLAY,
                         "--git-version", "2.34.1"))
    assert r.returncode == 0, r.stdout + r.stderr
    assert doc["verdict"] == "LAND_OK"
    assert doc["verification_tier"] == V.TIER_REBASE_REPLAY
    assert doc["tier_degraded"] is True
    assert doc["squash_vs_rebase_cross_check"] == "NOT_PERFORMED"
    assert "SQUASH_VS_REBASE_CROSS_CHECK_NOT_PERFORMED" in doc["disclosures"]
    assert doc["git_version"] == "2.34.1"
    assert doc["git_version_required_for_merge_tree"] == V.MERGE_TREE_MIN_VERSION
    # ...and PRINTED, with the same codes, so a terminal and a program are told
    # the same thing.
    assert "DISCLOSE  SQUASH_VS_REBASE_CROSS_CHECK_NOT_PERFORMED" in r.stdout
    assert f"[tier {V.TIER_REBASE_REPLAY}]" in r.stdout


def test_the_cli_record_marks_the_strong_tier_as_not_degraded(tmp_path):
    r, doc = _cli(tmp_path, _GOOD_LOG, _CASE_OK, _CASE_OK, _SEL)
    assert r.returncode == 0, r.stdout + r.stderr
    assert doc["verification_tier"] == V.TIER_MERGE_TREE
    assert doc["tier_degraded"] is False
    assert doc["squash_vs_rebase_cross_check"] == "PERFORMED"


def test_the_cli_refuses_an_unrecognised_tier_as_unmeasurable(tmp_path):
    r, doc = _cli(tmp_path, _GOOD_LOG, _CASE_OK, _CASE_OK, _SEL,
                  extra=("--verification-tier", "whatever"))
    assert r.returncode == 2, r.stdout + r.stderr
    assert doc["verdict"] == "REFUSE"
    assert doc["tier_degraded"] is True


# ------------------------------------------- the detection, on THIS host






# ------------------------------- THE PAIRED GUARD, end to end, UNDER THE FALLBACK









# Actual one-shot receipt consumer; no acceptance arm/forge/network in fixtures.
@pytest.fixture()
def ready_service(tmp_path):
    import os
    import shutil
    root = tmp_path / "ready-repo"
    root.mkdir()
    def git(*args):
        return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()
    git("init", "-q", "-b", "main")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "test")
    (root / "tools").mkdir()
    verifier = _VERIFY
    shutil.copyfile(verifier, root / "tools/gatekeeper-verify-merge.sh")
    (root / "dependency.py").write_text("initial dependency\n")
    git("add", "."); git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    git("checkout", "-qb", "candidate")
    (root / "feature.py").write_text("candidate\n")
    git("add", "."); git("commit", "-qm", "candidate")
    head = git("rev-parse", "HEAD")
    git("checkout", "-q", "main")
    receipt = tmp_path / "accepted.json"
    doc = {"receipt_schema": "vibeic.landing-acceptance.v1", "verdict": "LAND_OK",
           "base_sha": base, "head_sha": head,
           "selected_files": ["dependency.py"], "base_selected_files": [], "gate_edited": []}
    doc["receipt_sha256"] = hashlib.sha256(json.dumps(
        doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    receipt.write_text(json.dumps(doc))
    entry = {"id": "ready", "head": head, "receipt": str(receipt),
             "receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest()}
    manifest = tmp_path / "admission.json"
    final_marker = tmp_path / "final.json"
    program = _service_program()
    final = [sys.executable, "-c", "import os,json,pathlib; pathlib.Path(" + repr(str(final_marker))
             + ").write_text(json.dumps({'id':os.environ['GATEKEEPER_READY_ID'],"
               "'head':os.environ['GATEKEEPER_READY_HEAD']}))"]
    def run(entries=None, writer="root", final_command=None, base="main"):
        manifest.write_text(json.dumps({"writer": "root", "candidates": entries or [entry]}))
        result = subprocess.run([sys.executable, str(program), "--service-ready", str(manifest),
            "--repo", str(root), "--base", base, "--writer", writer,
            "--final-command", *(final if final_command is None else final_command)],
            capture_output=True, text=True)
        return result, json.loads(result.stdout)
    return root, git, entry, receipt, run, final_marker


def test_ready_service_skips_unrelated_conflict_and_reuses_without_acceptance(ready_service):
    root, git, entry, receipt, run, marker = ready_service
    first = dict(entry, id="earlier", shared_conflicts=["other live source owner"], number=1)
    entry.update(number=999, mergeable="UNKNOWN", author="another-owner", waited_days=30)
    rc, result = run([first, entry])
    assert rc.returncode == 0 and result["id"] == "ready"
    assert result["receipt_reused"] is True and result["impacted_checks"] == []
    assert json.loads(marker.read_text())["head"] == entry["head"]
    assert result["refused"][0]["id"] == "earlier"


def test_ready_service_unrelated_base_movement_does_not_rerun(ready_service):
    root, git, entry, receipt, run, marker = ready_service
    (root / "unrelated.txt").write_text("independent landing")
    git("add", "."); git("commit", "-qm", "unrelated")
    rc, result = run()
    assert rc.returncode == 0 and result["receipt_reused"] is True
    assert result["affected_paths"] == [] and result["impacted_checks"] == []


def test_ready_service_named_dependency_runs_only_impacted_check_outside_lock(ready_service):
    root, git, entry, receipt, run, marker = ready_service
    (root / "dependency.py").write_text("changed dependency\n")
    git("add", "."); git("commit", "-qm", "dependency")
    impacted = root.parent / "impacted"
    check = [sys.executable, "-c", "import fcntl,pathlib; "
             "f=open('.git/gatekeeper-final.lock','a'); "
             "fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB); "
             "pathlib.Path(" + repr(str(impacted)) + ").write_text('measured')"]
    entry["checks"] = {"dependency.py": [{"id": "dependency-consumer", "argv": check}],
                       "unrelated.txt": [{"id": "must-not-run", "argv": ["false"]}]}
    rc, result = run()
    assert rc.returncode == 0 and impacted.read_text() == "measured"
    assert result["impacted_checks"] == ["dependency-consumer"]
    assert result["affected_paths"] == ["dependency.py"]


@pytest.mark.parametrize("kind", ["missing", "tampered", "forged-resealed", "head-mismatch"])
def test_ready_service_invalid_receipt_refuses_without_final_write(ready_service, kind):
    root, git, entry, receipt, run, marker = ready_service
    if kind == "missing":
        receipt.unlink()
    elif kind == "head-mismatch":
        entry["head"] = "main"
    else:
        doc = json.loads(receipt.read_text())
        doc["selected_files"] = []
        if kind == "forged-resealed":
            doc.pop("receipt_sha256")
            doc["receipt_sha256"] = hashlib.sha256(json.dumps(
                doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        receipt.write_text(json.dumps(doc))
    rc, result = run()
    assert rc.returncode != 0 and result["status"] == "BLOCKED_NO_ACCEPTED_CANDIDATE"
    assert not marker.exists()


@pytest.mark.parametrize("blocker", ["holds", "shared_conflicts", "failed_gates", "dependencies"])
def test_ready_service_real_hold_dependency_or_shared_owner_still_blocks(ready_service, blocker):
    root, git, entry, receipt, run, marker = ready_service
    entry[blocker] = [entry["head"] if blocker == "dependencies" else "named actual blocker"]
    rc, result = run()
    assert rc.returncode != 0 and not marker.exists()
    assert result["status"] == "BLOCKED_NO_ACCEPTED_CANDIDATE"


def test_ready_service_missing_impacted_check_refuses_no_broad_fallback(ready_service):
    root, git, entry, receipt, run, marker = ready_service
    (root / "dependency.py").write_text("changed\n")
    git("add", "."); git("commit", "-qm", "dependency")
    rc, result = run()
    assert rc.returncode != 0 and not marker.exists()
    assert "no impacted check" in result["refused"][0]["reason"]


def test_ready_service_enforces_writer_and_short_serial_final_lock(ready_service):
    import fcntl
    root, git, entry, receipt, run, marker = ready_service
    rc, result = run(writer="source-prep")
    assert rc.returncode != 0 and result["status"] == "BLOCKED_ADMISSION_INPUT"
    with (root / ".git/gatekeeper-final.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        rc, result = run()
        assert rc.returncode != 0 and result["status"] == "BLOCKED_SOLE_WRITER_LOCK"
        assert not marker.exists()
    rc, result = run()
    assert rc.returncode == 0 and marker.exists()


def test_ready_service_prefers_reusable_receipt_before_unrelated_impacted_checks(ready_service):
    root, git, entry, receipt, run, marker = ready_service
    (root / "dependency.py").write_text("changed named input\n")
    git("add", "."); git("commit", "-qm", "changed input")
    current_base = git("rev-parse", "HEAD")
    impacted = root.parent / "earlier-impacted-marker"
    candidate_a = dict(entry, id="A", checks={"dependency.py": [{
        "id": "A-impacted", "argv": [sys.executable, "-c",
        "import pathlib; pathlib.Path(" + repr(str(impacted)) + ").write_text('ran')"]}]})
    git("checkout", "-qb", "independent")
    (root / "independent.py").write_text("independent candidate\n")
    git("add", "."); git("commit", "-qm", "independent candidate")
    independent_head = git("rev-parse", "HEAD")
    git("checkout", "-q", "main")
    doc = json.loads(receipt.read_text())
    doc.update(base_sha=current_base, head_sha=independent_head)
    doc.pop("receipt_sha256")
    doc["receipt_sha256"] = hashlib.sha256(json.dumps(
        doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    independent_receipt = root.parent / "independent-accepted.json"
    independent_receipt.write_text(json.dumps(doc))
    candidate_b = {"id": "B", "head": independent_head,
                   "receipt": str(independent_receipt),
                   "receipt_sha256": hashlib.sha256(independent_receipt.read_bytes()).hexdigest()}
    rc, result = run([candidate_a, candidate_b])
    assert rc.returncode == 0 and result["id"] == "B"
    assert result["receipt_reused"] is True and result["impacted_checks"] == []
    assert json.loads(marker.read_text())["head"] == independent_head
    assert not impacted.exists()


def _fake_gh(tmp_path, monkeypatch, *, number, head, base="main",
             base_oid=None, final_state="MERGED"):
    calls = tmp_path / "gh-calls.jsonl"
    bindir = tmp_path / "bin"
    bindir.mkdir()
    gh = bindir / "gh"
    gh.write_text("""#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
record = pathlib.Path(os.environ['FAKE_GH_CALLS'])
prior = record.read_text().splitlines() if record.exists() else []
with record.open('a') as stream:
    stream.write(json.dumps(args) + '\\n')
if args[:2] == ['pr', 'view']:
    merged = any(json.loads(line)[:2] == ['pr', 'merge'] for line in prior)
    state = os.environ['FAKE_GH_FINAL_STATE'] if merged else 'OPEN'
    print(json.dumps({'number': int(os.environ['FAKE_GH_NUMBER']),
                      'headRefOid': os.environ['FAKE_GH_HEAD'],
                      'baseRefName': os.environ['FAKE_GH_BASE'],
                      'baseRefOid': os.environ['FAKE_GH_BASE_OID'],
                      'isDraft': False, 'state': state,
                      'mergeCommit': {'oid': os.environ['FAKE_GH_MERGE_OID']}
                                     if state == 'MERGED' else None}))
    raise SystemExit(0)
if args[:2] == ['pr', 'merge']:
    raise SystemExit(0)
raise SystemExit(2)
""")
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("FAKE_GH_CALLS", str(calls))
    monkeypatch.setenv("FAKE_GH_NUMBER", str(number))
    monkeypatch.setenv("FAKE_GH_HEAD", head)
    monkeypatch.setenv("FAKE_GH_BASE", base)
    monkeypatch.setenv("FAKE_GH_BASE_OID", base_oid or head)
    monkeypatch.setenv("FAKE_GH_FINAL_STATE", final_state)
    monkeypatch.setenv("FAKE_GH_MERGE_OID", "a" * 40)
    return calls


def test_canonical_gatekeeper_loop_calls_service_and_bound_final_writer(
        ready_service, tmp_path, monkeypatch):
    skill = _GATEKEEPER_SKILL.read_text()
    cron = skill.split("## Cron-invocation template", 1)[1].split("## Reference", 1)[0]
    for required in (
            "gatekeeper-ready-receipts", "root-admission.json",
            "--writer repo-gatekeeper", "--receipt-root", "--candidates-json",
            "receipt_sha256", "os.fsync",
            "os.replace", "--service-ready", "--service-final-write",
            "GATEKEEPER_READY_ID", "GATEKEEPER_READY_HEAD",
            "GATEKEEPER_READY_BASE", "--match-head-commit"):
        assert required in skill, required
    assert not re.search(r"(?m)^\s*gh pr merge <num>", cron)
    assert "RE-RUN required checks" not in cron
    assert cron.index("--service-ready") < cron.index("bounded preparation")

    root, git, entry, receipt, run, marker = ready_service
    entry["id"] = "47"
    main = git("rev-parse", "main")
    git("update-ref", "refs/remotes/origin/main", main)
    calls = _fake_gh(tmp_path, monkeypatch, number=47, head=entry["head"],
                     base_oid=main)
    receipt_root = root / ".git" / "gatekeeper-ready-receipts"
    receipt_root.mkdir(mode=0o700)
    installed_receipt = receipt_root / "verify-47.json"
    shutil.copyfile(receipt, installed_receipt)
    entry.update(receipt=str(installed_receipt),
                 receipt_sha256=hashlib.sha256(
                     installed_receipt.read_bytes()).hexdigest())
    manifest = receipt_root / "root-admission.json"
    slow_marker = tmp_path / "unaccepted-preparation-ran"
    actionable = [{"id": "46", "accepted": False,
                   "prepare_argv": [sys.executable, "-c",
                       "import pathlib; pathlib.Path(" + repr(str(slow_marker))
                       + ").write_text('slow')"]}, entry]
    accepted = [row for row in actionable if row.get("accepted", True)]
    final = [sys.executable, str(_service_program()), "--service-final-write",
             "--repo", str(root), "--base", "origin/main"]
    rc = subprocess.run(
        [sys.executable, str(_service_program()), "--service-ready", str(manifest),
         "--repo", str(root), "--base", "origin/main",
         "--writer", "repo-gatekeeper", "--receipt-root", str(receipt_root),
         "--candidates-json", json.dumps(accepted),
         "--final-command", *final],
        cwd=root, capture_output=True, text=True)
    assert rc.returncode == 0, rc.stdout + rc.stderr
    result = json.loads(rc.stdout.splitlines()[-1])
    published = json.loads(manifest.read_text())

    assert result["status"] == "DELIVERED"
    if result["status"] != "DELIVERED":
        subprocess.run(actionable[0]["prepare_argv"], check=True)
    assert not slow_marker.exists()
    assert result["id"] == "47" and result["receipt_reused"] is True
    assert published == {"writer": "repo-gatekeeper",
                         "receipt_root": str(receipt_root),
                         "candidates": [entry]}
    assert manifest.stat().st_mode & 0o777 == 0o600
    bound = json.loads(result["stdout"])
    assert bound == {"base": main, "final_rc": 0, "head": entry["head"],
                     "id": "47", "status": "FINAL_WRITE_COMPLETE",
                     "merge_commit": "a" * 40, "stderr": "", "stdout": ""}
    observed = [json.loads(line) for line in calls.read_text().splitlines()]
    assert observed == [
        ["pr", "view", "47", "--json",
         "number,headRefOid,baseRefName,baseRefOid,isDraft,state,mergeCommit"],
        ["pr", "merge", "47", "--squash", "--delete-branch",
         "--match-head-commit", entry["head"]],
        ["pr", "view", "47", "--json",
         "number,headRefOid,baseRefName,baseRefOid,isDraft,state,mergeCommit"]]


def test_service_final_writer_refuses_a_different_pr_head_without_merge(
        ready_service, tmp_path, monkeypatch):
    root, git, entry, receipt, run, marker = ready_service
    entry["id"] = "48"
    main = git("rev-parse", "main")
    git("update-ref", "refs/remotes/origin/main", main)
    calls = _fake_gh(tmp_path, monkeypatch, number=48, head=main,
                     base_oid=main)
    final = [sys.executable, str(_service_program()), "--service-final-write",
             "--repo", str(root), "--base", "origin/main"]
    rc, result = run(final_command=final, base="origin/main")

    assert rc.returncode != 0 and result["status"] == "BLOCKED_FINAL_WRITE"
    bound = json.loads(result["stdout"])
    assert bound["status"] == "BLOCKED_FINAL_WRITE_BINDING"
    assert "id/head/base/state no longer match" in bound["reason"]
    observed = [json.loads(line) for line in calls.read_text().splitlines()]
    assert observed == [["pr", "view", "48", "--json",
                         "number,headRefOid,baseRefName,baseRefOid,isDraft,state,mergeCommit"]]


def test_service_final_writer_refuses_rc0_while_remote_is_still_open(
        ready_service, tmp_path, monkeypatch):
    root, git, entry, receipt, run, marker = ready_service
    entry["id"] = "49"
    main = git("rev-parse", "main")
    git("update-ref", "refs/remotes/origin/main", main)
    calls = _fake_gh(tmp_path, monkeypatch, number=49, head=entry["head"],
                     base_oid=main, final_state="OPEN")
    final = [sys.executable, str(_service_program()), "--service-final-write",
             "--repo", str(root), "--base", "origin/main"]
    rc, result = run(final_command=final, base="origin/main")

    assert rc.returncode != 0 and result["status"] == "BLOCKED_FINAL_WRITE"
    bound = json.loads(result["stdout"])
    assert bound["status"] == "BLOCKED_FINAL_WRITE"
    assert bound["final_rc"] == 0 and bound["merge_commit"] is None
    observed = [json.loads(line) for line in calls.read_text().splitlines()]
    assert [row[:2] for row in observed] == [
        ["pr", "view"], ["pr", "merge"], ["pr", "view"]]


def test_service_final_writer_refuses_a_moved_remote_base_without_merge(
        ready_service, tmp_path, monkeypatch):
    root, git, entry, receipt, run, marker = ready_service
    entry["id"] = "51"
    main = git("rev-parse", "main")
    git("update-ref", "refs/remotes/origin/main", main)
    calls = _fake_gh(tmp_path, monkeypatch, number=51, head=entry["head"],
                     base_oid="b" * 40)
    final = [sys.executable, str(_service_program()), "--service-final-write",
             "--repo", str(root), "--base", "origin/main"]
    rc, result = run(final_command=final, base="origin/main")

    assert rc.returncode != 0 and result["status"] == "BLOCKED_FINAL_WRITE"
    bound = json.loads(result["stdout"])
    assert bound["status"] == "BLOCKED_FINAL_WRITE_BINDING"
    assert "id/head/base/state no longer match" in bound["reason"]
    observed = [json.loads(line) for line in calls.read_text().splitlines()]
    assert observed == [["pr", "view", "51", "--json",
                         "number,headRefOid,baseRefName,baseRefOid,isDraft,state,mergeCommit"]]


def test_canonical_gatekeeper_entry_has_no_legacy_unbound_writer_or_rerun():
    skill = _GATEKEEPER_SKILL.read_text()
    frontmatter = skill.split("---", 2)[1]
    description = re.search(r"(?m)^description: (.*)$", frontmatter).group(1)
    top_loop = skill.split(
        "Every cron wake-up is a fresh, independent tick:", 1)[1].split(
            "The loop is **chip-AGNOSTIC**", 1)[0]
    cron = skill.split("## Cron-invocation template", 1)[1].split(
        "## Reference", 1)[0]
    historical = re.findall(
        r"<!-- HISTORICAL_NON_EXECUTABLE_START -->.*?"
        r"<!-- HISTORICAL_NON_EXECUTABLE_END -->", skill, re.DOTALL)
    assert len(historical) <= 1
    current_instructions = re.sub(
        r"<!-- HISTORICAL_NON_EXECUTABLE_START -->.*?"
        r"<!-- HISTORICAL_NON_EXECUTABLE_END -->", "", skill,
        flags=re.DOTALL)

    assert not re.search(r"(?m)^\s*gh pr merge\b", current_instructions)
    for stale in (".merge.lock", "serialized re-test-on-rebase",
                  "RE-RUN the required checks on the REBASED tree",
                  "RE-RUN gatekeeper_review.py", "rebased-tree re-run",
                  "rebase onto current origin/main", "on the rebased tree",
                  "rebase 到最新 origin/main", "在 rebase 樹上重跑"):
        assert stale not in current_instructions, stale
    assert len(historical) == 1
    for required in ("ready-first", "accepted receipt", "bounded",
                     "READY-bound", "holds", "dependencies",
                     "shared conflicts"):
        assert required in current_instructions, required
    top_order = {
        "service_ready": top_loop.index("--service-ready"),
        "machine_gates": top_loop.index("machine gates"),
    }
    assert top_order["service_ready"] < top_order["machine_gates"], top_order
    assert "BLOCKED_NO_ACCEPTED_CANDIDATE" in top_loop
    assert "no immediately deliverable READY candidate" in " ".join(
        top_loop.split())
    assert description in current_instructions
    assert "--service-ready" in cron
    assert "--service-final-write" in cron
    assert "BLOCKED_NO_ACCEPTED_CANDIDATE" in cron


@pytest.mark.parametrize("kind", ["missing-outer-pin", "forged-outer-pin"])
def test_actual_cli_publisher_refuses_invalid_outer_pin_before_final_writer(
        ready_service, tmp_path, monkeypatch, kind):
    root, git, entry, receipt, run, marker = ready_service
    entry["id"] = "50"
    receipt_root = root / ".git" / "gatekeeper-ready-receipts"
    receipt_root.mkdir(mode=0o700)
    installed_receipt = receipt_root / "verify-50.json"
    shutil.copyfile(receipt, installed_receipt)
    entry["receipt"] = str(installed_receipt)
    if kind == "missing-outer-pin":
        entry.pop("receipt_sha256")
    else:
        entry["receipt_sha256"] = "0" * 64
    manifest = receipt_root / "root-admission.json"
    calls = _fake_gh(tmp_path, monkeypatch, number=50, head=entry["head"])
    final = [sys.executable, str(_service_program()), "--service-final-write",
             "--repo", str(root), "--base", "origin/main"]
    result = subprocess.run(
        [sys.executable, str(_service_program()), "--service-ready", str(manifest),
         "--repo", str(root), "--base", "origin/main",
         "--writer", "repo-gatekeeper", "--receipt-root", str(receipt_root),
         "--candidates-json", json.dumps([entry]),
         "--final-command", *final],
        cwd=root, capture_output=True, text=True)

    report = json.loads(result.stdout)
    assert result.returncode != 0
    assert report["status"] == "BLOCKED_ADMISSION_INPUT"
    assert not manifest.exists() and not calls.exists()
