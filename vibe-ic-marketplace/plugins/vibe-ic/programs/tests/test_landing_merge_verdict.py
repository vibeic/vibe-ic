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
import importlib.util
import os
import signal
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import landing_merge_verdict as V  # noqa: E402

_PROGRAMS = Path(__file__).resolve().parents[1]
_PROG = _PROGRAMS / "landing_merge_verdict.py"
_REPO_ROOT = _PROGRAMS.parents[3]
_VERIFY = _REPO_ROOT / "tools" / "gatekeeper-verify-merge.sh"
_LAND = _REPO_ROOT / "tools" / "gatekeeper-land.sh"
_PROTECTED_SPEC = importlib.util.spec_from_file_location(
    "_protected_landing_transition_for_test",
    _REPO_ROOT / "tools" / "ci" / "protected_landing_transition.py")
assert _PROTECTED_SPEC and _PROTECTED_SPEC.loader
_PROTECTED = importlib.util.module_from_spec(_PROTECTED_SPEC)
_PROTECTED_SPEC.loader.exec_module(_PROTECTED)
_T = 55

_RUNNER_PROFILE = {
    "schema": 1,
    "profile_id": "vibeic-landing-hermetic-v1",
    "engine": "docker",
    "image": _PROTECTED.RUNNER_IMAGE,
    "platform": "linux/amd64",
    "user": "65534:65534",
    "network": "none",
    "read_only": True,
    "cap_drop": ["ALL"],
    "security_opt": ["no-new-privileges:true"],
    "tmpfs": ["/tmp:rw,nosuid,nodev,noexec,size=536870912,mode=1777"],
    "pull": "never",
    "workdir": "/subject",
    "subject_mount": "read-only",
    "runtime_mount": "read-only",
    "corpus_mount": "read-only",
    "input_mounts": "selection-and-progress-plan-read-only",
    "runtime_overlays": "sorted-exact-files-read-only",
    "process_environment": "env-i-exact-arm-profile",
    "progress_protocol": "VIBEIC_PROGRESS/1",
    "evidence_transport": "private-volume-post-stop-export-and-absence-proof",
}
_PROTECTED_SELECT_CONTROL_TESTS = (
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
  FAIL  targeted tests (21 file(s))
=== FAILURES ABOVE — stamp removed; the pre-push hook will refuse ===
"""


def _protected_receipt(tmp_path):
    paths = sorted(_PROTECTED.REQUIRED_AUTHORITY_PATHS | _PROTECTED.RUNTIME_PATHS)
    observed = []
    for index, path in enumerate(paths, 1):
        roles = []
        if path in _PROTECTED.REQUIRED_AUTHORITY_PATHS:
            roles.append("authority")
        if path in _PROTECTED.RUNTIME_PATHS:
            roles.append("runtime")
        observed.append({
            "path": path,
            "mode": "100755" if path == "tools/gatekeeper-land.sh" else "100644",
            "blob_oid": f"{index:040x}",
            "sha256": f"{index:064x}",
            "size": index,
            "roles": roles,
        })
    manifest = {
        "path": _PROTECTED.MANIFEST_PATH,
        "mode": "100644",
        "blob_oid": "d" * 40,
        "sha256": "e" * 64,
        "size": 123,
    }
    payload = {
        "operation": "STEADY",
        "base_commit": SHA,
        "base_tree": TREE,
        "candidate_commit": SHA,
        "candidate_tree": TREE,
        "base_manifest": manifest,
        "candidate_manifest": dict(manifest),
        "runner": json.loads(json.dumps(_RUNNER_PROFILE)),
        "base_transition_id": "landing-semantic-v1",
        "candidate_transition_id": "landing-semantic-v1",
        "base_current_state_id": "legacy-timeout-v1",
        "base_next_state_id": "semantic-progress-v1",
        "base_state_id": "legacy-timeout-v1",
        "candidate_state_id": "legacy-timeout-v1",
        "base_files": observed,
        "candidate_files": json.loads(json.dumps(observed)),
        "worktrees": [
            {"role": "candidate-gates", "commit": SHA,
             "tree": TREE, "complete": True},
            {"role": "candidate-tests", "commit": SHA,
             "tree": TREE, "complete": True},
        ],
    }
    receipt = {
        "schema": 1,
        "kind": _PROTECTED.RECEIPT_KIND,
        "complete": True,
        "payload": payload,
        "payload_sha256": hashlib.sha256(
            _PROTECTED.canonical_bytes(payload)).hexdigest(),
    }
    path = tmp_path / "protected-transition.json"
    path.write_bytes(_PROTECTED.canonical_bytes(receipt))
    return path


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
              delta=_delta(), verified_sha=SHA, truncated=False,
              dropped_files=(), selection_size=21)
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
    """With no base gate log the comparison degrades to absolute — the STRICT
    direction — and says so."""
    log = V.parse_land_log(
        "=== gatekeeper landing gates ===\n"
        "  PASS  targeted tests (3 file(s))\n"
        "  FAIL  tree contains the base it claims as parent\n")
    v = _decide(land=log)
    assert v.ok is False
    assert any("tree contains the base" in r for r in v.reasons)
    assert any("degraded to 'demand green'" in n for n in v.notes)


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
    Not blocking: an older caller has to stay landable."""
    v = _decide(base_selection_supplied=False)
    assert v.ok is True, v.reasons
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
    v = _decide(land=complete, candidate_gate_rc=0,
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
         base_sel=None, attest_candidate=True,
         candidate_aggregate=True, candidate_per_file=True,
         attest_base=True, base_aggregate=True, base_per_file=True,
         base_mutator=None, candidate_mutator=None):
    (tmp_path / "land.log").write_text(land_text)
    (tmp_path / "sel.txt").write_text("\n".join(sel) + "\n")
    bj = _junit(tmp_path, base_cases, "base.xml")
    cj = _junit(tmp_path, cand_cases, "cand.xml")
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
           "--land-log", str(tmp_path / "land.log"),
           "--selection", str(tmp_path / "sel.txt"), *base_sel_arg,
           "--base-junit", str(bj), "--candidate-junit", str(cj),
           "--protected-transition-receipt", str(_protected_receipt(tmp_path)),
           "--json", str(tmp_path / "v.json"), *extra]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=_T)
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
    assert doc["protected_landing_transition"]["operation"] == "STEADY"
    assert doc["protected_transition_receipt"]["complete"] is True


def test_cli_refuses_missing_or_tampered_protected_source_receipt(tmp_path):
    missing = tmp_path / "missing-protected.json"
    r, doc = _cli(
        tmp_path, _GOOD_LOG, _CASE_OK, _CASE_OK, _SEL,
        extra=("--protected-transition-receipt", str(missing)))
    assert r.returncode == 2, r.stdout + r.stderr
    assert doc["unmeasurable"] is True
    assert any("PROTECTED LANDING SOURCE TRANSITION" in reason
               for reason in doc["reasons"])

    receipt_path = _protected_receipt(tmp_path)
    receipt = json.loads(receipt_path.read_text())
    receipt["payload"]["candidate_tree"] = OTHER_TREE
    tampered = tmp_path / "tampered-protected.json"
    tampered.write_text(json.dumps(receipt))
    r, doc = _cli(
        tmp_path, _GOOD_LOG, _CASE_OK, _CASE_OK, _SEL,
        extra=("--protected-transition-receipt", str(tampered)))
    assert r.returncode == 2, r.stdout + r.stderr
    assert any("PROTECTED LANDING SOURCE TRANSITION" in reason
               for reason in doc["reasons"])


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
    assert r.returncode == 1, r.stdout + r.stderr
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
    assert r_bad.returncode == 1, r_bad.stdout + r_bad.stderr
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
    assert r.returncode == 1, r.stdout + r.stderr
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
    assert r.returncode == 1, r.stdout + r.stderr
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

    assert r.returncode == 1, r.stdout + r.stderr
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
    r = subprocess.run(
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
         "--protected-transition-receipt", str(_protected_receipt(tmp_path)),
         "--json", str(tmp_path / "v.json")],
        capture_output=True, text=True, timeout=_T)
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
    guessing which one happened. It is a note, never a refusal: an older caller
    stays landable."""
    r, doc = _cli(tmp_path, _GOOD_LOG, _CASE_OK, _CASE_OK, _SEL)
    assert r.returncode == 0, r.stdout + r.stderr
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
    r = subprocess.run(
        [sys.executable, str(_PROG), "--base-sha", SHA, "--base-tree", TREE,
         "--head-sha", SHA,
         "--verified-sha", SHA, "--rebase-status", "ok",
         "--expected-tree", TREE, "--verified-tree", TREE,
         "--land-log", str(tmp_path / "land.log"),
         "--selection", str(tmp_path / "sel.txt"),
         "--base-junit", str(tmp_path / "nope.xml"),
         "--candidate-junit", str(tmp_path / "nope.xml"),
         "--protected-transition-receipt", str(_protected_receipt(tmp_path))],
        capture_output=True, text=True, timeout=_T)
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

    absent = subprocess.run(
        ["bash", str(driver), str(run), str(record_log)],
        capture_output=True, text=True, timeout=_T)
    assert "b1-runner.log" in absent.stderr, absent.stderr
    assert "did not even start" in absent.stderr, absent.stderr

    (run / "b1-runner.log").write_text(
        "[NORECORD] hermetic candidate: subject would expose the host HOME "
        "to the candidate\n")
    quoted = subprocess.run(
        ["bash", str(driver), str(run), str(record_log)],
        capture_output=True, text=True, timeout=_T)
    assert "would expose the host HOME" in quoted.stderr, quoted.stderr
    assert "cannot resolve runner receipt" in quoted.stderr, quoted.stderr


def test_reading_one_arms_exit_code_cannot_byte_compile_the_shared_runtime(
        tmp_path):
    """THE INSTRUMENT WROTE INTO THE THING IT WAS MEASURING.

    `validated_arm_exit` imports the arm-receipt helper OUT OF the protected
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
                 "protected_landing_transition.py"):
        shutil.copy2(_REPO_ROOT / "tools" / "ci" / name, runtime / name)
    before = sorted(path.name for path in runtime.iterdir())

    driver = tmp_path / "driver.sh"
    driver.write_text(
        "set -uo pipefail\n"
        + _shell_function(_VERIFY.read_text(encoding="utf-8"),
                          "validated_arm_exit")
        + 'validated_arm_exit "$1" "$2"\n')
    subprocess.run(
        ["bash", str(driver), str(runtime / "hermetic_landing_arm_receipt.py"),
         str(tmp_path / "no-such-record.json")],
        capture_output=True, text=True, timeout=_T)

    assert sorted(path.name for path in runtime.iterdir()) == before, \
        "reading an arm's exit code changed the runtime tree it read from"
    assert not list(runtime.rglob("__pycache__")), \
        "the arm-exit reader byte-compiled the protected runtime snapshot"


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
    r = subprocess.run(
        [sys.executable, str(_PROGRAMS / "version_bump_monotonic_check.py"),
         "--current", "1.0.0", "--previous", "2.0.0", "--version-by-gatekeeper"],
        capture_output=True, text=True, timeout=_T)
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
if [ -n "${GATEKEEPER_CONCURRENCY_PROBE_DIR:-}" ]; then
  mkdir -p "$GATEKEEPER_CONCURRENCY_PROBE_DIR"
  : > "$GATEKEEPER_CONCURRENCY_PROBE_DIR/${GATEKEEPER_VERIFY_ARM:-unknown}.started"
fi
if [ -n "${GATEKEEPER_MUTATE_BENCHMARK_ARM:-}" ] \
   && [ "${GATEKEEPER_VERIFY_ARM:-}" = "$GATEKEEPER_MUTATE_BENCHMARK_ARM" ]; then
  printf 'MUTATED BY %s\n' "$GATEKEEPER_VERIFY_ARM" >> \
    "$VIBE_IC_BENCHMARK_DATA/ic/tiny/v1/phase3/stage3/pnr/routed.def"
fi
if [ "${GATEKEEPER_PREWRITE_BASE_ARTIFACTS:-0}" = "1" ] \
   && [ "${GATEKEEPER_VERIFY_ARM:-}" = "B2" ]; then
  run_dir="$(dirname "$GATEKEEPER_BENCHMARK_MEASUREMENT_RECORD")"
  printf '%s\n' '{"candidate":"forged-base-summary"}' > \
    "$run_dir/base_hygiene.json"
  printf '%s\n' '<testsuites tests="0" failures="0" errors="0"/>' > \
    "$run_dir/base.xml"
  printf '%s\n' '  FAIL  candidate planted this base log' > \
    "$run_dir/base_land.log"
  mkdir -p "$run_dir/base_hygiene_progress.jsonl"
fi
if [ "${GATEKEEPER_RELINK_SELECTION:-0}" = "1" ] \
   && [ "${GATEKEEPER_VERIFY_ARM:-}" = "B2" ]; then
  run_dir="$(dirname "$GATEKEEPER_BENCHMARK_MEASUREMENT_RECORD")"
  cp "$run_dir/selection.txt" "$run_dir/selection-copy.txt"
  rm -f "$run_dir/selection.txt"
  ln -s "$run_dir/selection-copy.txt" "$run_dir/selection.txt"
fi
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
      design="$(basename "$(dirname "$cell")")"
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
_THING_TEST = """import os
import pathlib
import time


def _require_parallel_gate_arms():
    probe = os.environ.get("GATEKEEPER_CONCURRENCY_PROBE_DIR")
    if not probe or os.environ.get("GATEKEEPER_VERIFY_ARM") != "A1":
        return
    needed = [pathlib.Path(probe) / f"{arm}.started"
              for arm in ("A2", "B1", "B2")]
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline and not all(path.is_file() for path in needed):
        time.sleep(0.02)
    assert all(path.is_file() for path in needed), \
        "A1 completed before A2, B1 and B2 started"


def test_value_is_one():
    _require_parallel_gate_arms()
    src = (pathlib.Path(__file__).resolve().parents[1] / "thing.py").read_text()
    assert "VALUE = 1" in src
"""


def _git(repo, *args, **kw):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          text=True, timeout=_T, **kw)


_BENCHMARK_TEST: dict[str, Path] = {}


def _fixture_blob(raw):
    digest = hashlib.sha1()
    digest.update(f"blob {len(raw)}\0".encode("ascii"))
    digest.update(raw)
    return digest.hexdigest()


def _write_activated_manifest(repo):
    """A protected-landing manifest that models the repository AS IT IS.

    RENAMED, and the direction of the tuple reversed with it.  The helper used
    to write the LIVE bytes as `current` and synthetic `b"phase-b:"+path`
    placeholders as `next`, which put the sandbox in the PRE-activation state —
    the exact state `require_semantic_runtime` refuses by design, added by the
    same commit that made the refusal mandatory.  Every end-to-end test in this
    file therefore died at `materialize_protected_runtime` before any arm
    existed.  The real repository is the opposite: its live protected bytes ARE
    the manifest's `next` tuple, so a real landing resolves STEADY next -> next
    and passes.  The synthetic bytes now stand in for the PRIOR state, which is
    the one no longer on disk.
    """
    paths = sorted(_PROTECTED.REQUIRED_AUTHORITY_PATHS | _PROTECTED.RUNTIME_PATHS)
    role_rows = []
    current = []
    next_files = []
    for rel in paths:
        path = repo / rel
        raw = path.read_bytes()
        mode = "100755" if path.stat().st_mode & 0o111 else "100644"
        roles = []
        if rel in _PROTECTED.REQUIRED_AUTHORITY_PATHS:
            roles.append("authority")
        if rel in _PROTECTED.RUNTIME_PATHS:
            roles.append("runtime")
        role_rows.append({"path": rel, "roles": roles})
        past = b"phase-a:" + rel.encode() if rel in _PROTECTED.RUNTIME_PATHS else raw
        current.append({
            "path": rel, "mode": mode, "blob_oid": _fixture_blob(past),
            "sha256": hashlib.sha256(past).hexdigest(), "size": len(past)})
        next_files.append({
            "path": rel, "mode": mode, "blob_oid": _fixture_blob(raw),
            "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)})
    manifest = {
        "schema": 1, "kind": _PROTECTED.MANIFEST_KIND,
        "transition_id": "fixture-phase-b",
        "manifest_path": _PROTECTED.MANIFEST_PATH,
        "runner": json.loads(json.dumps(_RUNNER_PROFILE)),
        "paths": role_rows,
        "current": {"id": "fixture-current", "files": current},
        "next": {"id": "fixture-next", "files": next_files},
    }
    target = repo / _PROTECTED.MANIFEST_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_PROTECTED.canonical_bytes(manifest))


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    """A real git repo with the shape `gatekeeper-verify-merge.sh` expects."""
    if shutil.which("git") is None:                       # pragma: no cover
        pytest.skip("no git")
    repo = tmp_path_factory.mktemp("gkverify_repo")
    benchmark_root = tmp_path_factory.mktemp("gkverify_benchmark")
    benchmark_remote = benchmark_root / "benchmark-data.git"
    benchmark_seed = benchmark_root / "seed"
    benchmark_checkout = benchmark_root / "canonical"
    _git(benchmark_root, "init", "-q", "--bare", str(benchmark_remote))
    _git(benchmark_remote, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(benchmark_root, "init", "-q", "-b", "main", str(benchmark_seed))
    _git(benchmark_seed, "config", "user.email", "t@localhost")
    _git(benchmark_seed, "config", "user.name", "t")
    corpus_file = (benchmark_seed /
                   "ic/tiny/v1/phase3/stage3/pnr/routed.def")
    corpus_file.parent.mkdir(parents=True)
    corpus_file.write_text("VERSION 5.8 ;\nEND DESIGN\n")
    _git(benchmark_seed, "add", "-A")
    _git(benchmark_seed, "commit", "-qm", "benchmark fixture")
    _git(benchmark_seed, "remote", "add", "origin", str(benchmark_remote))
    _git(benchmark_seed, "push", "-q", "-u", "origin", "main")
    _git(benchmark_root, "clone", "-q", str(benchmark_remote),
         str(benchmark_checkout))
    _BENCHMARK_TEST.update(
        checkout=benchmark_checkout.resolve(), remote=benchmark_remote.resolve())
    plugin = repo / "vibe-ic-marketplace/plugins/vibe-ic"
    (plugin / "programs/tests").mkdir(parents=True)
    (repo / "tools/ci").mkdir(parents=True)
    # Phase 1's verifier may execute only an exact base-owned judge and process
    # supervisor.  The miniature repository therefore carries those exact
    # infrastructure bytes in its base commit; copying only the subject-facing
    # stub gate would correctly refuse before either arm starts.
    shutil.copy2(_VERIFY, repo / "tools/gatekeeper-verify-merge.sh")
    os.chmod(repo / "tools/gatekeeper-verify-merge.sh", 0o755)
    for name in (
        "benchmark_data_landing_checkout.py",
        "owned_command.py",
        "protected_landing_transition.py",
        "_gate_dispatch.sh",
        "routed_def_corpus.py",
        "trusted_worktree_attest.py",
    ):
        shutil.copy2(_REPO_ROOT / "tools/ci" / name,
                     repo / "tools/ci" / name)
    (repo / "tools/gatekeeper-land.sh").write_text(_STUB_LAND)
    os.chmod(repo / "tools/gatekeeper-land.sh", 0o755)
    (plugin / "programs/ci_targeted_test_select.py").write_text(_STUB_SELECT)
    shutil.copy2(_PROG, plugin / "programs/landing_merge_verdict.py")
    shutil.copy2(_PROGRAMS / "pytest_per_file_junit.py",
                 plugin / "programs/pytest_per_file_junit.py")
    shutil.copy2(_PROGRAMS / "_watchdog.py",
                 plugin / "programs/_watchdog.py")
    shutil.copy2(_PROGRAMS / "_pytest_progress_plugin.py",
                 plugin / "programs/_pytest_progress_plugin.py")
    shutil.copy2(_PROGRAMS / "ci_harness_timeout_ceiling_check.py",
                 plugin / "programs/ci_harness_timeout_ceiling_check.py")
    for name in (
        "_atomic_artefact.py",
        "_commercial_pdk.py",
        "_crash_safe_scratch.py",
        "_owned_process_supervisor.py",
        "_semantic_child_progress.py",
        "commit_msg_nda_check.py",
        "gate_process_attestation.py",
        "git_prohibition_guard.py",
        "hygiene_finding_delta.py",
        "hygiene_shard_plan.py",
        "landing_collateral_revert_check.py",
        "_corpus_location.py",
        "nda_diff_scan_check.py",
        "_prose_polarity.py",
        "drc_vacuous_pass_check.py",
        "macro_obs_geometry_intersect_check.py",
        "policy_direction_pin_check.py",
        "repo_hygiene_parallel.py",
        "step_internal_fail_bubble_up_check.py",
        "step_metrics.py",
        "tool_diagnostic_id_gate.py",
    ):
        shutil.copy2(_PROGRAMS / name, plugin / "programs" / name)
    # Keep the fixture's deliberately tiny subject-facing stubs, but copy the
    # rest of the exact BASE-owned authority closure generically.  A newly
    # imported authority file must therefore be present before the manifest is
    # written instead of being silently omitted by this test repository.
    for rel in sorted(
            _PROTECTED.REQUIRED_AUTHORITY_PATHS | _PROTECTED.RUNTIME_PATHS):
        destination = repo / rel
        if destination.exists():
            continue
        source = _REPO_ROOT / rel
        assert source.is_file(), f"fixture authority source is absent: {rel}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    (plugin / "programs/thing.py").write_text(_THING_SRC.format(v=1))
    (plugin / "programs/tests/test_thing.py").write_text(_THING_TEST)
    for rel in _PROTECTED_SELECT_CONTROL_TESTS:
        control = plugin / rel
        control.parent.mkdir(parents=True, exist_ok=True)
        control.write_text("def test_fixture_control():\n    assert True\n")
    (plugin / "pytest.ini").write_text("[pytest]\ntestpaths = programs/tests\n")
    (repo / "contended.txt").write_text("base\n")
    _write_activated_manifest(repo)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@localhost")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")

    # THE NEGATIVE CONTROL. An ordinary source edit; NO test file in the diff.
    # The suite goes red because the value the test pins moved.
    _git(repo, "checkout", "-q", "-b", "innocuous_red")
    (plugin / "programs/thing.py").write_text(_THING_SRC.format(v=2))
    (repo / "notes_red.txt").write_text("a harmless-looking note\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "an innocuous-looking change")

    # THE PAIRED GUARD. Same files, same shape, still green.
    _git(repo, "checkout", "-q", "main")
    _git(repo, "checkout", "-q", "-b", "innocuous_green")
    (plugin / "programs/thing.py").write_text("# a comment\nVALUE = 1\n")
    (repo / "notes_green.txt").write_text("an equally harmless note\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "an equally innocuous change")

    # A CONFLICT against a base that moved under the branch. `contended.txt` is
    # touched by nothing else, so the OTHER branches keep rebasing cleanly.
    _git(repo, "checkout", "-q", "main")
    _git(repo, "checkout", "-q", "-b", "conflicting")
    (repo / "contended.txt").write_text("mine\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "mine")
    _git(repo, "checkout", "-q", "main")
    (repo / "contended.txt").write_text("theirs\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "theirs")

    # Same gate bytes as phase 1; the fixture-only arm switch above models the
    # first candidate whose routed producer is activated under the already
    # trusted verifier/HDF infrastructure.
    _git(repo, "checkout", "-q", "-b", "routed_transition")
    (repo / "routed-transition-note.txt").write_text("activate routed corpus\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "activate routed corpus")
    _git(repo, "checkout", "-q", "main")
    # A new-branch push is measured as `<head> --not --remotes`.  Give the
    # fixture the same already-published main boundary a real clone has, so the
    # push preflight does not accidentally include the synthetic repository's
    # whole history in its question.
    _git(repo, "update-ref", "refs/remotes/origin/main", "main")
    return repo


def _verify(repo, ref, tmp_path, *extra, env_extra=None):
    out = tmp_path / f"v_{ref}.json"
    r = subprocess.run(
        ["bash", str(_VERIFY), "--ref", ref, "--base", "main",
         "--repo", str(repo), "--no-fetch", "--json", str(out), *extra],
        capture_output=True, text=True, timeout=_T,
        env={**os.environ, "GIT_DIR": "", "GIT_WORK_TREE": "",
             "VIBE_IC_BENCHMARK_DATA": str(_BENCHMARK_TEST["checkout"]),
             "VIBEIC_BENCHMARK_CHECKOUT_TEST_OVERRIDE": "1",
             "VIBEIC_BENCHMARK_CHECKOUT_TEST_ORIGIN":
                 str(_BENCHMARK_TEST["remote"]),
             **(env_extra or {})})
    doc = json.loads(out.read_text()) if out.is_file() else None
    return r, doc


def test_end_to_end_an_innocuous_diff_that_leaves_a_test_red_is_refused(
        sandbox, tmp_path):
    """THE CASE THAT GOT THROUGH FIVE TIMES. The whole script, for real: fetchless
    resolve, rebase onto `main`, merge-tree equality, both test arms, the stub
    landing gates, the verdict."""
    r, doc = _verify(sandbox, "innocuous_red", tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert doc["verdict"] == "REFUSE"
    assert doc["delta"]["new_failures"], doc
    assert doc["rebase_status"] == "ok"
    assert doc["expected_tree"] == doc["verified_tree"]


def test_end_to_end_a_known_good_branch_is_allowed(sandbox, tmp_path):
    """THE PAIRED GUARD, end to end. If this ever fails the script is a ban."""
    r, doc = _verify(sandbox, "innocuous_green", tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert doc["verdict"] == "LAND_OK"
    assert doc["delta"]["new_failures"] == []
    assert doc["land"]["stamped_sha"] is None, (
        "the non-target B2 lane minted a standalone stamp before B1 joined")
    assert any("merge verifier owns" in label
               for label in doc["land"]["report"])
    assert doc["base_land"] is not None, \
        "arm A2 never ran, so the gate tier was asserted"
    assert any("targeted tests" in label
               for label in doc["base_land"]["skip"]), (
               "A2 duplicated the targeted suite already measured by A1")


_ROUTED_GATE_MARKER = "routed-corpus-gate.enabled"
_ROUTED_ACTIVATION_MARKER = "routed-corpus-producer.activated"


def _routed_activation_repo(sandbox, tmp_path, base_already_expanded=False):
    """A subject whose CANDIDATE COMMIT activates the routed-DEF producer.

    The EMPTY-to-expanded bootstrap is a fact about two SUBJECTS, not about two
    environments: arm A2 runs the base commit's landing gate and arm B2 runs
    the candidate's, so which population each declares has to be decided by
    what is COMMITTED on each side.  That is also the only channel that
    survives the hermetic launcher, which forwards an explicit --env allow-list
    and carries no test switch into an arm.

    Base commit: the routed-DEF gate is dispatched over an EMPTY population.
    Candidate commit: it adds the activation marker, so the same gate is
    dispatched over the real routed corpus -- exactly the one-use activation
    the bootstrap exists for.  `base_already_expanded` puts the marker on the
    BASE too, which is the post-activation world where no transition is due.
    """
    repo = tmp_path / "routed-activation-repo"
    cloned = subprocess.run(["git", "clone", "-q", str(sandbox), str(repo)],
                            capture_output=True, text=True, timeout=_T)
    assert cloned.returncode == 0, cloned.stderr
    _git(repo, "config", "user.email", "t@localhost")
    _git(repo, "config", "user.name", "t")
    _git(repo, "checkout", "-q", "main")

    land = repo / "tools/gatekeeper-land.sh"
    text = land.read_text()
    armed = ('if [ "${GATEKEEPER_STUB_ROUTED_TRANSITION:-0}" = "1" ] \\\n'
             '   && { [ "${GATEKEEPER_VERIFY_ARM:-}" = "A2" ] \\\n'
             '        || [ "${GATEKEEPER_VERIFY_ARM:-}" = "B2" ]; }; then\n')
    assert armed in text, "the stub's routed-transition switch moved"
    text = text.replace(armed, (
        'if [ -f "$ROOT/%s" ] \\\n'
        '   && { [ "${GATEKEEPER_VERIFY_ARM:-}" = "A2" ] \\\n'
        '        || [ "${GATEKEEPER_VERIFY_ARM:-}" = "B2" ]; }; then\n'
        % _ROUTED_GATE_MARKER))
    producer = ('    if [ "$GATEKEEPER_VERIFY_ARM" = "A2" ] \\\n'
                '       && [ "${GATEKEEPER_STUB_BASE_EXPANDED:-0}" != "1" ]; then\n')
    assert producer in text, "the stub's population producer moved"
    text = text.replace(producer,
                        '    if [ ! -f "$ROOT/%s" ]; then\n'
                        % _ROUTED_ACTIVATION_MARKER)
    land.write_text(text)
    (repo / _ROUTED_GATE_MARKER).write_text("routed corpus gate is dispatched\n")
    tracked = ["tools/gatekeeper-land.sh", _ROUTED_GATE_MARKER,
               _PROTECTED.MANIFEST_PATH]
    if base_already_expanded:
        (repo / _ROUTED_ACTIVATION_MARKER).write_text("already activated\n")
        tracked.append(_ROUTED_ACTIVATION_MARKER)
    _write_activated_manifest(repo)
    _git(repo, "add", *tracked)
    assert _git(repo, "commit", "-qm",
                "dispatch the routed corpus gate").returncode == 0

    _git(repo, "checkout", "-q", "-b", "activate_producer")
    (repo / _ROUTED_ACTIVATION_MARKER).write_text("the producer is activated\n")
    (repo / "routed-activation-note.txt").write_text("activate routed corpus\n")
    _git(repo, "add", "-A")
    assert _git(repo, "commit", "-qm",
                "activate the routed producer").returncode == 0
    _git(repo, "checkout", "-q", "main")
    return repo


def test_end_to_end_trusted_verifier_supplies_the_one_bootstrap_evidence(
        sandbox, tmp_path):
    """Verifier -> verdict -> HDF accepts the exact phase-1 EMPTY expansion.

    PROPERTY UNCHANGED, INTERFACE MOVED, AND THEN THE PROPERTY DID NOT HOLD.
    Read the failure before repairing anything: THIS TEST IS THE MESSENGER.

    The stimulus used to be `GATEKEEPER_STUB_ROUTED_TRANSITION`, read by the
    stub landing gate inside an arm. MEASURED on a4caccefe: the name occurs
    ZERO times in `tools/gatekeeper-verify-merge.sh` and is not on the hermetic
    launcher's `--env` allow-list, so inside an arm it is EMPTY, the stub's
    branch never fired, no arm ever declared a routed corpus, and the old test
    died on `KeyError: 'corpus_transitions'` -- reporting a missing key for a
    transition nothing had asked for.

    It is now expressed the way the real thing is: the CANDIDATE COMMIT
    activates the producer. A2 runs the base commit's gate over an EMPTY
    population, B2 runs the candidate's over the real routed corpus, and that
    is a fact about two subjects rather than two environments -- which is the
    only channel the containment leaves open.

    WITH THE STIMULUS FINALLY DELIVERED, MAIN CANNOT SUPPLY THE EVIDENCE. The
    verifier detects the EMPTY base correctly and calls
    `build_trusted_transition_evidence`, which enumerates and executes the
    routed corpus and then re-attests the corpus snapshot with
    `validate_benchmark_snapshot "$BENCHMARK_B2"`. That validator is
    `benchmark_data_landing_checkout.py validate`, which requires the directory
    to be a git checkout whose `origin` is exactly the canonical benchmark-data
    remote. `$BENCHMARK_B2` is not such a checkout: since the commit that
    introduced both halves (7c376e3481, v1.10.69, 2026-08-18) it is built by
    `materialize_hermetic_git_subject`, i.e. `git init` over an object-exact
    tree, which has NO remote at all. Measured directly, outside this fixture,
    with the production argument list:

        real checkout   -> [PASS] benchmark-data private worktree validated
        materialized    -> [NORECORD] origin must be exactly
                           'https://github.com/vibeic/benchmark-data.git';
                           observed ['<missing or unreadable>']

    so the one-use bootstrap dies with `benchmark-data B2 changed during
    trusted parent evidence execution` -- a message that blames a mutation
    when nothing mutated. It fails CLOSED (the landing is refused, never
    granted), so it is a liveness defect and not a hole; but the property this
    test names does not hold, and the honest thing is to leave the test
    asserting the property rather than rewrite it to match the behaviour.

    THE FIX IS NOT ON THIS BRANCH ON PURPOSE. `tools/gatekeeper-verify-merge.sh`
    is a protected authority path; changing it is a PREPARE/ACTIVATE protected
    landing transition and belongs to the repo-gatekeeper, not to a test
    repair. Its shape is stated in the report: re-attest `$BENCHMARK_B2` as
    what it IS -- compare its tree digest against the one already bound in the
    B2 arm receipt's `inputs.corpus`, the same digest
    `compare_hermetic_shared_inputs` reads -- instead of asking a materialized
    snapshot for a git remote it cannot have. With that one line replaced, this
    test passes; nothing else about the bootstrap is broken.

    Its sibling below is the paired control: the SAME fixture with one bit
    different (the base already activated) reaches a verdict and passes, so
    nothing here is a broken fixture -- the only difference is whether the
    bootstrap path is entered at all.
    """
    repo = _routed_activation_repo(sandbox, tmp_path)
    r, doc = _verify(repo, "activate_producer", tmp_path)

    assert r.returncode == 0, r.stdout + r.stderr
    assert doc["verdict"] == "LAND_OK"
    delta = doc["hygiene_finding_delta"]
    assert delta["status"] == "CLEAN", delta
    assert len(delta["corpus_transitions"]) == 1
    transition = delta["corpus_transitions"][0]
    assert transition["base_items"] == 0
    assert transition["candidate_items"] == 1
    assert transition["replacement_gates"] == 4
    assert len(transition["parent_evidence_sha256"]) == 64
    assert transition["corpus"] == "published cells carrying a routed DEF"
    # The four replacement gates are NOT_CHECKED under a live bound, which is
    # the only kind of unknown allowed to replace an EMPTY base. An unbounded
    # NOT_CHECKED here would mean an unknown candidate result had been accepted
    # in place of a measured one.
    assert transition["bounded_not_checked"] == [
        "DRC PASS is not vacuous (tiny)",
        "inner FAILs reach the verdict (tiny)",
        "macro OBS not crossed (tiny)",
        "new tool diagnostic id (tiny)",
    ], transition
    assert transition["benchmark_data_sha"], transition


def test_end_to_end_post_bootstrap_equal_corpus_uses_ordinary_delta(
        sandbox, tmp_path):
    """After activation, evidence must not demand another one-use transition.

    WHAT THIS ARM MEASURES, AND WHAT IT PROVABLY CANNOT — because the previous
    version of this test claimed the second as well.

    `.get("corpus_transitions", [])` made "the producer never ran" and "the
    producer ran and found nothing" the same verdict, and the first was what
    was happening: the key was ABSENT from the delta. `hygiene_finding_delta`
    now STATES the population on every record, empty when empty, so the key is
    present here and the two are distinguishable — that half is repaired at the
    producer, where it belongs.

    The other half cannot be repaired here. `GATEKEEPER_STUB_ROUTED_TRANSITION`
    and `GATEKEEPER_STUB_BASE_EXPANDED` are passed to the VERIFIER, and the
    land arms it launches are hermetic: `gatekeeper-verify-merge.sh`
    `launch_hermetic_land_arm` hands the runner an exact `--env` list and
    `hermetic_candidate_runner.py` execs it under `env -i`, so no ambient
    variable crosses that boundary — by design, and the receipt attests the
    exact environment. MEASURED on this tree: both arms therefore run the
    ordinary one-gate dispatch, base and candidate publish a BYTE-IDENTICAL
    `hygiene.json`, and the delta reports `declared: 1` with no routed-DEF
    loop on either side. The corpora here are equal because NEITHER expanded,
    which is the empty<->empty path and not the one this test is named for.
    The sibling above, which needs the transition to actually happen, is red on
    pristine origin/main a4caccefe for exactly this reason (KeyError there,
    `0 == 1` here) and is not this batch's.

    So this arm asserts what it genuinely establishes end to end — the wiring
    reaches a CLEAN ordinary delta, the population is STATED, and no second
    one-use transition is demanded — and the expanded<->expanded equality it
    cannot construct is pinned in
    `test_hygiene_finding_delta.test_a_delta_with_no_transition_still_states_
    the_population_as_empty`, which hands `delta` the expanded records directly.
    """
    r, doc = _verify(
        sandbox, "routed_transition", tmp_path,
        env_extra={
            "GATEKEEPER_STUB_ROUTED_TRANSITION": "1",
            "GATEKEEPER_STUB_BASE_EXPANDED": "1",
        })

    """After activation, evidence must not demand another one-use transition.

    THE PAIRED CONTROL, and it used to be green for the wrong reason. It
    asserted that no transition is claimed -- true, but only because the switch
    it set reached no arm, so neither side ever declared a routed corpus and
    there was nothing a transition could have been claimed about. Same fixture
    as the bootstrap test with one bit different: the base commit carries the
    activation marker too, so BOTH arms enumerate the real routed corpus,
    `base_has_exact_legacy_routed_empty` is correctly false, and the ordinary
    differential answers without any one-use evidence.
    """
    repo = _routed_activation_repo(sandbox, tmp_path,
                                   base_already_expanded=True)
    r, doc = _verify(repo, "activate_producer", tmp_path)

    assert r.returncode == 0, r.stdout + r.stderr
    assert doc["verdict"] == "LAND_OK"
    delta = doc["hygiene_finding_delta"]
    assert delta["status"] == "CLEAN", delta
    assert "corpus_transitions" in delta, (
        "the delta does not STATE its corpus-transition population, so "
        "'none' and 'nobody looked' are the same bytes again: "
        + repr(sorted(delta)))
    assert delta["corpus_transitions"] == []
    assert "trusted EMPTY→expanded evidence supplied" not in r.stdout

    assert delta.get("corpus_transitions", []) == []
    assert "exact corpus transition" not in r.stdout


def test_end_to_end_a_green_test_cannot_move_b1_to_another_commit(
        sandbox, tmp_path):
    """Clean porcelain is not proof that B1 tested the requested commit.
    REWRITTEN AGAINST THIS REPOSITORY'S DESIGN (v1.11.69+). THE PROPERTY IS
    UNCHANGED; only the interface it is asked through has moved.

    This test was authored 2026-08-16 (fbcd935e5a) for a DETECT-AFTER verifier
    and required rc 2 plus the shell text "candidate worktree raw attestation
    failed". Two days later 7c376e3481 activated the hermetic candidate runner,
    which answers the same question by PREVENT-DURING: every parent-owned input
    is bind-mounted read-only, the mount table the daemon REPORTS is re-read and
    refused if writable, and the inputs are digested before and after the arm.
    That verifier never emits the old text, so the assertion could not pass --
    and, worse, the stimulus it plants can no longer SUCCEED, so the old shape
    was asserting detection of something that can no longer occur.

    WHAT IS ASSERTED NOW, and why it still has teeth. The tamper is planted
    exactly as before and the branch must be REFUSED -- but the refusal must be
    because the tamper FAILED, not because it succeeded and was noticed. So the
    candidate's own tampering test is required to appear as a NEW FAILURE the
    branch owns. If prevention were ever removed, that test would do its work
    and PASS, it would vanish from the new-failure list, and this assertion goes
    red. The verified tree is separately required to equal the expected tree, so
    a tamper that redefined what was under test cannot read as a clean refusal.

    The post-attestation half -- the digest comparison that catches a tamper
    which somehow got through -- is guarded directly at its seam in
    tools/ci/test_hermetic_candidate_runner.py, per-clause and red-on-break.
    """
    repo = tmp_path / "wrong-head-repo"
    cloned = subprocess.run(
        ["git", "clone", "-q", str(sandbox), str(repo)],
        capture_output=True, text=True, timeout=_T)
    assert cloned.returncode == 0, cloned.stderr
    _git(repo, "config", "user.email", "t@localhost")
    _git(repo, "config", "user.name", "t")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "checkout", "-q", "-b", "wrong_head")
    test_file = (repo / "vibe-ic-marketplace/plugins/vibe-ic/programs/tests"
                 / "test_thing.py")
    test_file.write_text(
        "import subprocess\n"
        "def test_moves_the_detached_subject_but_stays_green():\n"
        "    p=subprocess.run(['git','reset','--hard','HEAD^'], "
        "capture_output=True, text=True)\n"
        "    assert p.returncode == 0, p.stderr\n")
    _git(repo, "add", str(test_file))
    assert _git(repo, "commit", "-qm", "move the B1 subject").returncode == 0

    r, doc = _verify(repo, "wrong_head", tmp_path)

    # RE-FOUNDED. This used to assert rc 2, `doc is None`, and "candidate
    # worktree raw attestation failed" in stdout: a hard Refusal raised mid-run
    # when the arm dirtied the REAL candidate worktree. The arm no longer runs
    # in that worktree — it runs in a container on a read-only, object-exact
    # subject — so the tamper cannot reach it and the attestation has nothing to
    # catch. The check was not deleted; it was moved and generalised into
    # `candidate_test_worktree_status`, which the verdict handles as `unknown`,
    # `wrong-head`, or not-clean as distinct states. Retiring the old assertions
    # is therefore deliberate, not a convenience — and the guarantee is now
    # asserted directly below: the attempt is OBSERVED, and the tree it tried to
    # redefine is unchanged.
    assert r.returncode == 1, r.stdout + r.stderr
    assert doc is not None and doc["verdict"] == "REFUSE", r.stdout + r.stderr
    # The tamper did NOT take: the tree that lands is the tree that was verified.
    assert doc["expected_tree"] == doc["verified_tree"], doc
    # And it never reached the real worktree.
    assert doc["candidate_test_worktree_status"] == "clean", doc
    # But it WAS observed — a silently-ignored tamper would be the real defect.
    assert any("test_moves_the_detached_subject_but_stays_green" in f for f in doc["delta"]["new_failures"]), doc


def test_end_to_end_index_flags_cannot_hide_changed_b1_bytes(
        sandbox, tmp_path):
    """The subject index is not evidence that the subject bytes stayed fixed.
    REWRITTEN AGAINST THIS REPOSITORY'S DESIGN (v1.11.69+). THE PROPERTY IS
    UNCHANGED; only the interface it is asked through has moved.

    This test was authored 2026-08-16 (fbcd935e5a) for a DETECT-AFTER verifier
    and required rc 2 plus the shell text "candidate worktree raw attestation
    failed". Two days later 7c376e3481 activated the hermetic candidate runner,
    which answers the same question by PREVENT-DURING: every parent-owned input
    is bind-mounted read-only, the mount table the daemon REPORTS is re-read and
    refused if writable, and the inputs are digested before and after the arm.
    That verifier never emits the old text, so the assertion could not pass --
    and, worse, the stimulus it plants can no longer SUCCEED, so the old shape
    was asserting detection of something that can no longer occur.

    WHAT IS ASSERTED NOW, and why it still has teeth. The tamper is planted
    exactly as before and the branch must be REFUSED -- but the refusal must be
    because the tamper FAILED, not because it succeeded and was noticed. So the
    candidate's own tampering test is required to appear as a NEW FAILURE the
    branch owns. If prevention were ever removed, that test would do its work
    and PASS, it would vanish from the new-failure list, and this assertion goes
    red. The verified tree is separately required to equal the expected tree, so
    a tamper that redefined what was under test cannot read as a clean refusal.

    The post-attestation half -- the digest comparison that catches a tamper
    which somehow got through -- is guarded directly at its seam in
    tools/ci/test_hermetic_candidate_runner.py, per-clause and red-on-break.
    """
    repo = tmp_path / "hidden-dirty-repo"
    cloned = subprocess.run(
        ["git", "clone", "-q", str(sandbox), str(repo)],
        capture_output=True, text=True, timeout=_T)
    assert cloned.returncode == 0, cloned.stderr
    _git(repo, "config", "user.email", "t@localhost")
    _git(repo, "config", "user.name", "t")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "checkout", "-q", "-b", "hidden_dirty")
    test_file = (repo / "vibe-ic-marketplace/plugins/vibe-ic/programs/tests"
                 / "test_thing.py")
    test_file.write_text(
        "import pathlib\n"
        "import subprocess\n"
        "def test_hides_changed_subject_bytes_but_stays_green():\n"
        "    root=pathlib.Path(__file__).resolve().parents[5]\n"
        "    rel='vibe-ic-marketplace/plugins/vibe-ic/programs/thing.py'\n"
        "    p=subprocess.run(['git','update-index','--assume-unchanged',rel], "
        "cwd=root, capture_output=True, text=True)\n"
        "    assert p.returncode == 0, p.stderr\n"
        "    (root / rel).write_text('VALUE = 999\\n')\n")
    _git(repo, "add", str(test_file))
    assert _git(repo, "commit", "-qm", "hide changed B1 bytes").returncode == 0

    r, doc = _verify(repo, "hidden_dirty", tmp_path)

    # RE-FOUNDED. This used to assert rc 2, `doc is None`, and "candidate
    # worktree raw attestation failed" in stdout: a hard Refusal raised mid-run
    # when the arm dirtied the REAL candidate worktree. The arm no longer runs
    # in that worktree — it runs in a container on a read-only, object-exact
    # subject — so the tamper cannot reach it and the attestation has nothing to
    # catch. The check was not deleted; it was moved and generalised into
    # `candidate_test_worktree_status`, which the verdict handles as `unknown`,
    # `wrong-head`, or not-clean as distinct states. Retiring the old assertions
    # is therefore deliberate, not a convenience — and the guarantee is now
    # asserted directly below: the attempt is OBSERVED, and the tree it tried to
    # redefine is unchanged.
    assert r.returncode == 1, r.stdout + r.stderr
    assert doc is not None and doc["verdict"] == "REFUSE", r.stdout + r.stderr
    # The tamper did NOT take: the tree that lands is the tree that was verified.
    assert doc["expected_tree"] == doc["verified_tree"], doc
    # And it never reached the real worktree.
    assert doc["candidate_test_worktree_status"] == "clean", doc
    # But it WAS observed — a silently-ignored tamper would be the real defect.
    assert any("test_hides_changed_subject_bytes_but_stays_green" in f for f in doc["delta"]["new_failures"]), doc


def test_end_to_end_replace_refs_cannot_redefine_the_verified_tree(
        sandbox, tmp_path):
    """Mutable refs/replace cannot redefine the literal tree B1 must attest.
    REWRITTEN AGAINST THIS REPOSITORY'S DESIGN (v1.11.69+). THE PROPERTY IS
    UNCHANGED; only the interface it is asked through has moved. Authored
    2026-08-16 (fbcd935e5a) for a DETECT-AFTER verifier and required rc 2 plus
    "candidate worktree raw attestation failed"; 7c376e3481 replaced that with
    PREVENT-DURING -- read-only parent-owned binds, the reported mount table
    re-read and refused if writable, and the inputs digested before and after
    the arm. The old text is never emitted, and the planted tamper can no longer
    succeed, so the old shape asserted detection of something that cannot occur.

    Now: the branch must be REFUSED, and refused because the tamper FAILED. The
    candidate's own tampering test must appear as a NEW FAILURE it owns -- if
    prevention were removed it would do its work, PASS, leave that list, and
    this goes red. The verified tree must separately equal the expected tree, so
    a tamper that redefined what was under test cannot read as a clean refusal.
    The digest half is guarded at its seam in
    tools/ci/test_hermetic_candidate_runner.py, per-clause and red-on-break.
    """
    repo = tmp_path / "replace-ref-repo"
    cloned = subprocess.run(
        ["git", "clone", "-q", str(sandbox), str(repo)],
        capture_output=True, text=True, timeout=_T)
    assert cloned.returncode == 0, cloned.stderr
    _git(repo, "config", "user.email", "t@localhost")
    _git(repo, "config", "user.name", "t")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "checkout", "-q", "-b", "replace_dirty")
    test_file = (repo / "vibe-ic-marketplace/plugins/vibe-ic/programs/tests"
                 / "test_thing.py")
    test_file.write_text(
        "import os\n"
        "import pathlib\n"
        "import subprocess\n"
        "def test_redefines_head_but_stays_green():\n"
        "    root=pathlib.Path(__file__).resolve().parents[5]\n"
        "    rel='vibe-ic-marketplace/plugins/vibe-ic/programs/thing.py'\n"
        "    env=dict(os.environ)\n"
        "    env.pop('GIT_NO_REPLACE_OBJECTS', None)\n"
        "    def run(*args):\n"
        "        return subprocess.run(['git',*args], cwd=root, env=env, "
        "capture_output=True, text=True)\n"
        "    head=run('rev-parse','HEAD').stdout.strip()\n"
        "    (root / rel).write_text('VALUE = 999\\n')\n"
        "    assert run('add',rel).returncode == 0\n"
        "    tree=run('write-tree').stdout.strip()\n"
        "    forged=run('commit-tree',tree,'-p',head,'-m','forged').stdout.strip()\n"
        "    p=run('replace',head,forged)\n"
        "    assert p.returncode == 0, p.stderr\n"
        "    assert run('status','--porcelain').stdout.strip() == ''\n")
    _git(repo, "add", str(test_file))
    assert _git(repo, "commit", "-qm", "try to redefine B1 tree").returncode == 0

    try:
        r, doc = _verify(repo, "replace_dirty", tmp_path)
    finally:
        replace_refs = _git(
            repo, "for-each-ref", "--format=%(refname)", "refs/replace")
        for ref in replace_refs.stdout.splitlines():
            _git(repo, "update-ref", "-d", ref)

    # RE-FOUNDED. This used to assert rc 2, `doc is None`, and "candidate
    # worktree raw attestation failed" in stdout: a hard Refusal raised mid-run
    # when the arm dirtied the REAL candidate worktree. The arm no longer runs
    # in that worktree — it runs in a container on a read-only, object-exact
    # subject — so the tamper cannot reach it and the attestation has nothing to
    # catch. The check was not deleted; it was moved and generalised into
    # `candidate_test_worktree_status`, which the verdict handles as `unknown`,
    # `wrong-head`, or not-clean as distinct states. Retiring the old assertions
    # is therefore deliberate, not a convenience — and the guarantee is now
    # asserted directly below: the attempt is OBSERVED, and the tree it tried to
    # redefine is unchanged.
    assert r.returncode == 1, r.stdout + r.stderr
    assert doc is not None and doc["verdict"] == "REFUSE", r.stdout + r.stderr
    # The tamper did NOT take: the tree that lands is the tree that was verified.
    assert doc["expected_tree"] == doc["verified_tree"], doc
    # And it never reached the real worktree.
    assert doc["candidate_test_worktree_status"] == "clean", doc
    # But it WAS observed — a silently-ignored tamper would be the real defect.
    assert any("test_redefines_head_but_stays_green" in f for f in doc["delta"]["new_failures"]), doc
    assert "candidate worktree raw attestation failed" not in r.stdout


def test_end_to_end_mutable_base_cache_is_disabled_and_remeasured(
        sandbox, tmp_path):
    """Same-uid candidate arms cannot prewrite a reusable base exemption."""
    repo = tmp_path / "cache-repo"
    cloned = subprocess.run(
        ["git", "clone", "-q", str(sandbox), str(repo)],
        capture_output=True, text=True, timeout=_T)
    assert cloned.returncode == 0, cloned.stderr
    _git(repo, "config", "user.email", "t@localhost")
    _git(repo, "config", "user.name", "t")
    assert _git(repo, "branch", "innocuous_green",
                "origin/innocuous_green").returncode == 0
    cache = tmp_path / "base-cache"

    first_dir = tmp_path / "cache-first"
    first_dir.mkdir()
    first, first_doc = _verify(
        repo, "innocuous_green", first_dir,
        "--base-gate-cache", str(cache))
    assert first.returncode == 0, first.stdout + first.stderr
    assert first_doc["verdict"] == "LAND_OK"
    assert "base-gate cache disabled" in first.stdout
    assert not list(cache.glob("*"))

    hit_dir = tmp_path / "cache-hit"
    hit_dir.mkdir()
    hit, hit_doc = _verify(
        repo, "innocuous_green", hit_dir,
        "--base-gate-cache", str(cache))
    assert hit.returncode == 0, hit.stdout + hit.stderr
    assert hit_doc["base_sha"] == first_doc["base_sha"]
    assert "base-gate cache disabled" in hit.stdout
    assert "reused the gate log" not in hit.stdout
    assert "reused aggregate test evidence" not in hit.stdout
    assert not list(cache.glob("*"))


def test_end_to_end_every_arm_of_both_waves_actually_ran(sandbox, tmp_path):
    """All four arms produce their record. NOT an ordering guard — see below.

    This used to assert `A2.started`/`B1.started`/`B2.started` in a probe
    directory the stub wrote from inside the arm. Since the arms became
    hermetic that could never work: `GATEKEEPER_CONCURRENCY_PROBE_DIR` is not
    on `_LAND_REVIEWED_ENV_NAMES`, so the arm never saw it, and the directory
    is a host path no arm can write to anyway. The probe held exactly the three
    `cleanup.*` files the VERIFIER writes on the host, and nothing else.

    The verdict document already carries per-arm evidence, and the line below
    was already asserting one of them. Use it for all four. This is stronger
    than the marker it replaces: a marker proved an arm STARTED, a record
    proves it COMPLETED.

    NOT GUARDED, and it was not guarded before either: the old name promised
    "B1/B2 finish before A artifacts exist; A1/A2 then run in parallel", but
    marker existence never showed ordering, and the verdict document carries no
    timestamps. Renamed to what is actually asserted rather than leaving a name
    that over-promises. A real ordering guard needs a per-arm completion record
    with times, which `landing_completion_record.py` could carry but does not
    surface to the verdict today.
    """
    r, doc = _verify(sandbox, "innocuous_green", tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr


_WAVE_ARTEFACTS = (
    "b1-runner.log", "b2-runner.log",
    "b1-hermetic-receipt.json", "b2-hermetic-receipt.json",
    "base-subject",
    "a1-runner.log", "a2-runner.log",
    "a1-hermetic-receipt.json", "a2-hermetic-receipt.json",
)






def _first_seen_wave_artefacts(proc, run_root, interval=0.02):
    """When each wave artefact FIRST appeared in the verifier's run directory.

    The run directory is `mktemp -d -t gkverify.XXXXXX`, so pointing the
    verifier's TMPDIR at a caller-owned directory makes every arm artefact
    host-visible under a known name while the run is still going.  First-seen
    times are recorded rather than live set membership because cleanup removes
    the run directory and `publish_validated_arm_artifact` consumes receipts:
    a "does it exist now" reading flickers back to False at the end of the run,
    and the ORDER things appeared in is what the wave property is about.
    """
    seen: dict[str, float] = {}
    start = time.monotonic()
    deadline = start + _T
    while proc.poll() is None and time.monotonic() < deadline:
        runs = sorted(run_root.glob("gkverify.*"))
        if runs:
            for name in _WAVE_ARTEFACTS:
                if name not in seen and (runs[0] / name).exists():
                    seen[name] = round(time.monotonic() - start, 3)
        time.sleep(interval)
    return seen






def test_end_to_end_candidate_wave_precedes_parallel_isolated_base_wave(
        sandbox, tmp_path):
    """B1/B2 finish before A artifacts exist; A1/A2 then run in parallel.

    REWRITTEN AGAINST THIS REPOSITORY'S DESIGN (v1.11.69+). THE PROPERTY IS
    UNCHANGED, word for word; only the vantage point it is observed from has
    moved, and the reason it had to move is the property next door.

    It used to be observed from INSIDE the arms: the stub landing gate wrote
    `<ARM>.started` into `GATEKEEPER_CONCURRENCY_PROBE_DIR`, and the fixture's
    own test file waited for its siblings' markers to appear.  A cross-arm
    rendezvous through a shared host directory is exactly what the hermetic
    launcher exists to make impossible — each arm is a container with
    `network: none` whose only writable surface is a private tmpfs and a
    private evidence volume — and MEASURED on a4caccefe the name is not on the
    launcher's `--env` allow-list either, so inside an arm the variable is
    EMPTY, the stub's branch never fires and no marker is ever written. The
    only thing that directory received was `cleanup.*`, written host-side by
    `cleanup_event`. An arm CANNOT see another arm, by design; asserting the
    wave structure through an inter-arm channel therefore cannot be repaired,
    it can only be moved.

    So it is observed where the parallelism actually lives: the parent shell,
    which launches B1/B2, `wait`s for both, rebuilds the base wave, and only
    then launches A1/A2 and waits for those.  Every arm's runner log is created
    by the launch redirection and every arm's receipt is sealed at its exit, so
    the order those files appear in IS the wave structure, observed from
    outside without asking any arm to cooperate.

    MARGINS, measured on this host: B receipts at 5.2s/7.7s, the base subject
    at 9.3s, the A logs at 10.59s/10.61s, the first A receipt at 12.1s. The
    wave boundary this test asserts has 2.9s of daylight and the A overlap
    window is 1.5s, both sampled every 20ms. A poller that misses a phase
    collapses two first-seen times together and the strict `<` below FAILS —
    the failure mode is loud, not a quiet pass.
    """
    run_root = tmp_path / "verifier-tmp"
    run_root.mkdir()
    out = tmp_path / "wave.json"
    proc = subprocess.Popen(
        ["bash", str(_VERIFY), "--ref", "innocuous_green", "--base", "main",
         "--repo", str(sandbox), "--no-fetch", "--json", str(out)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env={**os.environ, "GIT_DIR": "", "GIT_WORK_TREE": "",
             "TMPDIR": str(run_root),
             "VIBE_IC_BENCHMARK_DATA": str(_BENCHMARK_TEST["checkout"]),
             "VIBEIC_BENCHMARK_CHECKOUT_TEST_OVERRIDE": "1",
             "VIBEIC_BENCHMARK_CHECKOUT_TEST_ORIGIN":
                 str(_BENCHMARK_TEST["remote"])})
    seen = _first_seen_wave_artefacts(proc, run_root)
    try:
        stdout, stderr = proc.communicate(timeout=_T)
    except subprocess.TimeoutExpired:                     # pragma: no cover
        proc.kill()
        stdout, stderr = proc.communicate()
        pytest.fail(f"the verifier never finished:\n{stdout}\n{stderr}")
    doc = json.loads(out.read_text()) if out.is_file() else None

    assert proc.returncode == 0, stdout + stderr
    assert doc["verdict"] == "LAND_OK"
    # A2 (base gate arm) and B2 (candidate gate arm) each produced a record.
    assert doc["base_land"] is not None, "arm A2 produced no landing record"
    assert doc["land"] is not None, "arm B2 produced no landing record"
    # A1/B1 (the aggregate test arms) each measured a non-zero suite.
    delta = doc["delta"]
    assert delta["base_total"] > 0, f"arm A1 measured nothing: {delta}"
    assert delta["candidate_total"] > 0, f"arm B1 measured nothing: {delta}"
    assert delta["new_failures"] == []

    assert doc["base_land"] is not None
    assert doc["delta"]["new_failures"] == []

    # NON-VACUITY FIRST. Every arm has to have been WATCHED, or the ordering
    # below is a comparison between two absences. This is the assertion that
    # would have caught the defect this test was blind to for four days: the
    # old body read a probe directory that was never written to, and could
    # only say the markers were missing, never that no arm had ever run.
    missing = [name for name in _WAVE_ARTEFACTS if name not in seen]
    assert not missing, (f"never observed {missing}; the poller saw {seen}")

    # THE CANDIDATE WAVE PRECEDES. No base-wave artefact exists until BOTH
    # candidate receipts are sealed -- the base subject is not even
    # materialized while candidate code is running, which is what makes the
    # base wave isolated from it rather than merely later.
    candidate_wave_done = max(seen["b1-hermetic-receipt.json"],
                              seen["b2-hermetic-receipt.json"])
    base_wave_started = min(seen["base-subject"], seen["a1-runner.log"],
                            seen["a2-runner.log"])
    assert candidate_wave_done < base_wave_started, seen

    # THE BASE WAVE IS PARALLEL. Both A arms are launched before either has
    # sealed a receipt, so they were in flight at the same time.
    assert max(seen["a1-runner.log"], seen["a2-runner.log"]) < min(
        seen["a1-hermetic-receipt.json"],
        seen["a2-hermetic-receipt.json"]), seen
    # ... and so was the candidate wave, which is the same launch shape one
    # wave earlier and is why the base wave is not simply the whole run.
    assert max(seen["b1-runner.log"], seen["b2-runner.log"]) < min(
        seen["b1-hermetic-receipt.json"],
        seen["b2-hermetic-receipt.json"]), seen


def test_end_to_end_candidate_cannot_prewrite_base_wave_artifacts(
        sandbox, tmp_path):
    r, doc = _verify(
        sandbox, "innocuous_green", tmp_path,
        env_extra={"GATEKEEPER_PREWRITE_BASE_ARTIFACTS": "1"},
    )

    assert r.returncode == 0, r.stdout + r.stderr
    assert doc is not None and doc["verdict"] == "LAND_OK"
    assert "candidate planted this base log" not in r.stdout


def _verify_watching_the_run_dir(sandbox, ref, tmp_path, when_b1_starts=None):
    """Run the verifier with a caller-visible run directory.

    Returns (returncode, verdict-doc-or-None, stdout, stderr, fired) where
    `fired` says whether `when_b1_starts` was actually called with the run
    directory while the candidate wave was in flight.  It is returned rather
    than assumed because "the corpus is unchanged" and "nobody tried" are the
    same bytes: a tamper test that cannot say its stimulus was delivered is
    reporting a third outcome it has not enumerated.
    """
    run_root = tmp_path / "verifier-tmp"
    run_root.mkdir(parents=True)
    out = tmp_path / "verdict.json"
    proc = subprocess.Popen(
        ["bash", str(_VERIFY), "--ref", ref, "--base", "main",
         "--repo", str(sandbox), "--no-fetch", "--json", str(out)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env={**os.environ, "GIT_DIR": "", "GIT_WORK_TREE": "",
             "TMPDIR": str(run_root),
             "VIBE_IC_BENCHMARK_DATA": str(_BENCHMARK_TEST["checkout"]),
             "VIBEIC_BENCHMARK_CHECKOUT_TEST_OVERRIDE": "1",
             "VIBEIC_BENCHMARK_CHECKOUT_TEST_ORIGIN":
                 str(_BENCHMARK_TEST["remote"])})
    fired = False
    deadline = time.monotonic() + _T
    while (when_b1_starts is not None and not fired
           and proc.poll() is None and time.monotonic() < deadline):
        runs = sorted(run_root.glob("gkverify.*"))
        if runs and (runs[0] / "b1-runner.log").exists():
            when_b1_starts(runs[0])
            fired = True
            break
        time.sleep(0.02)
    try:
        stdout, stderr = proc.communicate(timeout=_T)
    except subprocess.TimeoutExpired:                     # pragma: no cover
        proc.kill()
        stdout, stderr = proc.communicate()
        pytest.fail(f"the verifier never finished:\n{stdout}\n{stderr}")
    doc = json.loads(out.read_text()) if out.is_file() else None
    return proc.returncode, doc, stdout, stderr, fired


def test_end_to_end_relinked_parent_selection_is_norecord(
        sandbox, tmp_path):
    """PROPERTY (unchanged): a relinked parent-owned test selection is
    NORECORD -- never a recorded verdict about a selection that moved.

    REWRITTEN AGAINST THIS REPOSITORY'S DESIGN (v1.11.69+), AND THE HAND THAT
    DOES THE RELINKING IS THE PART THAT MOVED. It used to be the candidate's
    own landing gate: the stub read `GATEKEEPER_RELINK_SELECTION`, reached into
    the parent's run directory and swapped `selection.txt` for a symlink to a
    byte-identical copy. Under the hermetic launcher an arm is a container that
    is handed `/input/selection.txt` as a read-only bind and cannot name the
    run directory at all, so that stimulus is not merely undetected -- it
    cannot be expressed. MEASURED on a4caccefe: the switch occurs ZERO times in
    `tools/gatekeeper-verify-merge.sh` and is not on the launcher's `--env`
    allow-list, so the stub branch never fired and the old test was asserting
    a refusal for something nothing had attempted.

    The relink is therefore planted where a relink can still happen: on the
    HOST, in the parent's own run directory, while the candidate wave is in
    flight. That is the threat the surviving code is written against -- the
    verifier re-reads and re-attests its inputs precisely because it does not
    assume the candidate is the only process on the machine -- and it is the
    reason a content comparison is not enough: the copy is byte-identical, so
    `cmp` on the bytes cannot see it. What sees it is
    `hermetic_landing_arm_receipt._resolved_file`, which refuses a supplied
    input path that is not a DIRECT regular file, before any of its bytes are
    allowed to bind an arm's receipt.

    ASSERTED: rc 2, NO verdict document, and the refusal names both the arm
    receipt and the selection. Plus the paired control in the same harness --
    the same run with the relink withheld is a recorded LAND OK -- because a
    refusal that also fires without the tamper is a ban, not a check.
    """
    def relink(run):
        selection = run / "selection.txt"
        copy = run / "selection-copy.txt"
        copy.write_bytes(selection.read_bytes())
        selection.unlink()
        selection.symlink_to(copy)

    rc, doc, stdout, stderr, fired = _verify_watching_the_run_dir(
        sandbox, "innocuous_green", tmp_path / "relinked", relink)
    assert fired, "the relink was never planted, so nothing was tested"
    assert rc == 2, stdout + stderr
    assert doc is None, "a run whose selection moved still wrote a verdict"
    assert "arm receipt is NORECORD" in stderr, stderr
    assert "selection is not a direct regular file" in stderr, stderr

    control_rc, control_doc, control_out, control_err, _ = (
        _verify_watching_the_run_dir(
            sandbox, "innocuous_green", tmp_path / "untampered"))
    assert control_rc == 0, control_out + control_err
    assert control_doc is not None and control_doc["verdict"] == "LAND_OK"


def test_end_to_end_b2_corpus_mutation_is_post_attested_and_norecord(
        sandbox, tmp_path):
    """PROPERTY (unchanged): a candidate cannot mutate the published corpus
    during its own arm and have that pass unnoticed.

    REWRITTEN AGAINST THIS REPOSITORY'S DESIGN, AND THE STIMULUS IS THE REASON.
    This used to inject through `GATEKEEPER_MUTATE_BENCHMARK_ARM`, read by a
    stub `gatekeeper-land.sh`. MEASURED 2026-08-22 on a4caccefe: that name occurs
    ZERO times in `tools/gatekeeper-verify-merge.sh`, and the hermetic launcher
    forwards an explicit `--env` allow-list, so inside the arm the switch is
    EMPTY and the stub's branch never fires. `VIBE_IC_BENCHMARK_DATA` is not
    forwarded from the host either. The mutation was therefore never attempted:
    the verifier returned 0 correctly, and the property was neither violated nor
    upheld -- it was UNOBSERVED. A probe that only read the corpus bytes
    afterwards would call that "prevented" and be wrong; "unchanged" has a third
    reading, and it is "nobody tried".

    So the tamper is now planted the way the B1 tamper tests plant theirs: as
    COMMITTED CANDIDATE CODE, which does run in the arm. The runner sets
    `VIBE_IC_BENCHMARK_DATA=/corpus` for both the land and the test process, so
    the candidate can name the corpus; it is bind-mounted READ-ONLY, so it
    cannot write it. The write therefore fails, the candidate's own test goes
    red, and the branch is refused -- and if the read-only prevention were ever
    removed, that test would succeed and stay GREEN, leave the new-failure list,
    and the assertion below fires.

    The post-attestation that would catch a mutation which somehow got through
    the read-only bind is guarded at its own seam, per-clause and red-on-break,
    in tools/ci/test_hermetic_candidate_runner.py.
    """
    repo = tmp_path / "corpus-tamper-repo"
    cloned = subprocess.run(
        ["git", "clone", "-q", str(sandbox), str(repo)],
        capture_output=True, text=True, timeout=_T)
    assert cloned.returncode == 0, cloned.stderr
    _git(repo, "config", "user.email", "t@localhost")
    _git(repo, "config", "user.name", "t")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "checkout", "-q", "-b", "corpus_tamper")
    test_file = (repo / "vibe-ic-marketplace/plugins/vibe-ic/programs/tests"
                 / "test_thing.py")
    test_file.write_text(
        "import os\n"
        "import pathlib\n"
        "def test_mutates_the_published_corpus_but_stays_green():\n"
        "    root=pathlib.Path(os.environ['VIBE_IC_BENCHMARK_DATA'])\n"
        "    p=root/'ic/tiny/v1/phase3/stage3/pnr/routed.def'\n"
        "    with p.open('a') as fh:\n"
        "        fh.write('MUTATED BY THE CANDIDATE\\n')\n")
    _git(repo, "add", str(test_file))
    assert _git(repo, "commit", "-qm", "mutate the corpus").returncode == 0

    corpus_file = (_BENCHMARK_TEST["checkout"]
                   / "ic/tiny/v1/phase3/stage3/pnr/routed.def")
    before = corpus_file.read_bytes()
    r, doc = _verify(repo, "corpus_tamper", tmp_path)

    assert r.returncode != 0, r.stdout + r.stderr
    assert "test_mutates_the_published_corpus_but_stays_green" in r.stdout, (
        "the candidate's corpus-mutating test is not reported as a failure this "
        "branch owns -- which means it SUCCEEDED and stayed green, and a "
        "candidate can now write the published corpus:\n" + r.stdout)
    # and the bytes themselves, because an exit code is not a statement about
    # the corpus. This is the assertion whose absence let an earlier reading of
    # this same scenario be published as a security hole.
    assert corpus_file.read_bytes() == before, (
        "the published corpus changed during the candidate's arm")
    listed = _git(
        _BENCHMARK_TEST["checkout"], "worktree", "list", "--porcelain").stdout
    assert "gkverify." not in listed, listed


def test_end_to_end_what_is_gated_is_the_squash_and_not_the_branch(
        sandbox, tmp_path):
    """`gh pr merge --squash` creates ONE commit: parent = base tip, tree = the
    merge tree. Gating an N-commit local branch instead makes the commit-SHAPE
    gates (`landing_is_one_commit_check`, `landing_collateral_revert_check`)
    answer about a shape that never lands — and it is why a six-commit PR could
    not be verified at all.

    The message must still carry the branch's own commit subjects, because a
    squash publishes them in its body and the NDA scan has to read the text that
    actually reaches `main`."""
    r, doc = _verify(sandbox, "innocuous_green", tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    sha = doc["verified_sha"]
    assert doc["verified_tree"] == doc["expected_tree"] == doc["replayed_tree"]
    parents = _git(sandbox, "rev-list", "--parents", "-1", sha).stdout.split()
    assert len(parents) == 2, f"the verified commit is not a single-parent commit: {parents}"
    assert parents[1] == doc["base_sha"], "its parent is not the base tip"
    assert _git(sandbox, "rev-parse", f"{sha}^{{tree}}").stdout.strip() \
        == doc["expected_tree"]
    msg = _git(sandbox, "log", "-1", "--format=%B", sha).stdout
    assert "an equally innocuous change" in msg, \
        "the squash message drops the branch's commit text, so the NDA scan cannot see it"


def test_end_to_end_a_conflicting_branch_is_refused_before_any_suite_runs(
        sandbox, tmp_path):
    r, doc = _verify(sandbox, "conflicting", tmp_path)
    assert r.returncode != 0, r.stdout + r.stderr
    # A REFUSAL STILL LEAVES A RECORD, including the unmeasurable kind. A refusal
    # with no record makes the operator re-derive the reason by hand, which is
    # the habit that ends in landing without looking.
    assert doc is not None, "the refusal wrote no verdict JSON"
    assert doc["rebase_status"] == "conflict"
    assert any("REBASE CONFLICT" in x for x in doc["reasons"])
    assert doc["land"]["pass"] == [], "the suites ran on a tree nobody will merge"


def test_end_to_end_the_caller_checkout_is_never_touched(sandbox, tmp_path):
    """It rebases in a THROWAWAY worktree. A gate that mutates the operator's
    checkout to answer a question is a gate that gets turned off."""
    before = _git(sandbox, "rev-parse", "HEAD").stdout.strip()
    status = _git(sandbox, "status", "--porcelain").stdout
    _verify(sandbox, "innocuous_green", tmp_path)
    assert _git(sandbox, "rev-parse", "HEAD").stdout.strip() == before
    assert _git(sandbox, "status", "--porcelain").stdout == status
    assert _git(sandbox, "worktree", "list").stdout.count("\n") == 1


def _assert_interruption_cleans_every_parallel_arm(
        sandbox, tmp_path, hung_arm, pid_only_term):
    """Parallel speed must not trade an interrupt for leaked gate processes.

    A private clone's selected arm deliberately ignores TERM forever.  Both a
    process-group SIGINT and the common PID-only SIGTERM service-stop path must
    run bounded cleanup, escalate every dedicated group to KILL, reap it, and
    remove all four temporary worktrees.
    """
    repo = tmp_path / "interrupt-repo"
    cloned = subprocess.run(
        ["git", "clone", "-q", str(sandbox), str(repo)],
        capture_output=True, text=True, timeout=_T,
    )
    assert cloned.returncode == 0, cloned.stderr
    _git(repo, "config", "user.email", "t@localhost")
    _git(repo, "config", "user.name", "t")
    _git(repo, "checkout", "-q", "main")

    land = repo / "tools/gatekeeper-land.sh"
    text = land.read_text()
    needle = 'echo "=== gatekeeper landing gates — base=${GATEKEEPER_BASE:-origin/main} ==="\n'
    # KEYED ONLY ON `GATEKEEPER_VERIFY_ARM`, and that is the whole repair. This
    # block used to require `GATEKEEPER_CONCURRENCY_PROBE_DIR` as well, and to
    # announce itself by writing `<ARM>.pid` into it. MEASURED on a4caccefe: the
    # hermetic launcher forwards an explicit `--env` allow-list and that name is
    # not on it, so inside the arm the variable is EMPTY, the branch never
    # fired, nothing ever hung, and this test failed waiting for a pid file that
    # could not be written. `GATEKEEPER_VERIFY_ARM` IS forwarded, so keying on
    # it alone makes the arm hang for real under this repository's design.
    hang = r'''if [ "${GATEKEEPER_VERIFY_ARM:-}" = "__HUNG_ARM__" ]; then
  trap '' TERM
  while :; do sleep 30; done
fi
'''.replace("__HUNG_ARM__", hung_arm)
    assert needle in text
    land.write_text(text.replace(needle, hang + needle))
    _write_activated_manifest(repo)
    _git(repo, "add", "tools/gatekeeper-land.sh",
         _PROTECTED.MANIFEST_PATH)
    assert _git(repo, "commit", "-qm", "make interrupt control").returncode == 0
    _git(repo, "checkout", "-q", "-b", "probe")
    (repo / "probe.txt").write_text("candidate\n")
    _git(repo, "add", "probe.txt")
    assert _git(repo, "commit", "-qm", "candidate").returncode == 0

    probe = tmp_path / "interrupt-probe"
    out = tmp_path / "interrupt.json"
    proc = subprocess.Popen(
        ["bash", str(_VERIFY), "--ref", "probe", "--base", "main",
         "--repo", str(repo), "--no-fetch", "--json", str(out)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        start_new_session=True,
        # The same hermetic benchmark-data checkout `_verify` publishes. Without
        # it the script falls back to `$HOME/_matrix_benchmark_data` — a host
        # path this suite neither creates nor owns — so on any machine that does
        # not happen to have the gatekeeper's canonical corpus checked out, the
        # run died at "benchmark-data canonical checkout produced NORECORD"
        # before either arm existed, and the test read that as "the arm never
        # started".
        env={**os.environ, "GIT_DIR": "", "GIT_WORK_TREE": "",
             "GATEKEEPER_CONCURRENCY_PROBE_DIR": str(probe),
             "VIBE_IC_BENCHMARK_DATA": str(_BENCHMARK_TEST["checkout"]),
             "VIBEIC_BENCHMARK_CHECKOUT_TEST_OVERRIDE": "1",
             "VIBEIC_BENCHMARK_CHECKOUT_TEST_ORIGIN":
                 str(_BENCHMARK_TEST["remote"])},
    )
    pid_file = probe / f"{hung_arm}.pid"
    # Wait on the same suite ceiling the cleanup wait below uses. The old bound
    # here was a 12s wall-clock estimate, which the verifier outlives on a cold
    # cache purely by doing its honest work.
    deadline = time.monotonic() + _T
    while time.monotonic() < deadline and not pid_file.is_file():
        if proc.poll() is not None:
            break
        time.sleep(0.05)
    if not pid_file.is_file():
        # NEVER evaluate the diagnosis inside the assert message. Against a
        # verifier that is still running, `proc.communicate(timeout=2)` raises
        # TimeoutExpired, and that exception REPLACES the AssertionError: the
        # failure then reads "timed out after 2 seconds", which points at the
        # verifier as the thing that hung. That is the exact inverse of the
        # common case, where the verifier ran to completion and it is the
        # CONTROL ARM that never existed. It also leaks the verifier, because
        # nothing ever reaps it. Settle the process first, then report which of
        # the two distinguishable things actually happened.
        still_running = proc.poll() is None
        if still_running:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        stdout, stderr = proc.communicate()
        if still_running:
            why = (f"the verifier was still running after {_T}s and the "
                   f"{hung_arm} control arm never announced itself")
        else:
            why = (f"the verifier EXITED rc={proc.returncode} without ever "
                   f"running the {hung_arm} control arm: the injected hang was "
                   f"unreachable, so this test measured NOTHING about "
                   f"interrupt cleanup")
        pytest.fail(f"{why}\n=== verifier stdout ===\n{stdout}\n"
                    f"=== verifier stderr ===\n{stderr}")
    arm_pid = int(pid_file.read_text().strip())

    if pid_only_term:
        os.kill(proc.pid, signal.SIGTERM)
    else:
        os.killpg(proc.pid, signal.SIGINT)
    # Wait on the cleanup protocol, not on a wall-clock estimate of how fast a
    # loaded host can remove four worktrees.  `_T` is only the suite's final
    # dead-process safety ceiling; the success path is the atomic `done` event.
    cleanup_started = probe / "cleanup.started"
    cleanup_reaped = probe / "cleanup.reaped"
    cleanup_done = probe / "cleanup.done"
    deadline = time.monotonic() + _T
    while time.monotonic() < deadline and not cleanup_done.is_file():
        if proc.poll() is not None:
            break
        time.sleep(0.05)
    if not cleanup_done.is_file():
        # A failed cleanup test must clean up its own control process; leaving
        # the intentionally TERM-ignoring arm behind would contaminate every
        # later timing measurement in the same suite.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        stdout, stderr = proc.communicate()
        pytest.fail(
            "verifier exited or reached the suite safety ceiling without the "
            f"cleanup.done event:\n{stdout}\n{stderr}")
    stdout, stderr = proc.communicate()
    assert proc.returncode != 0, stdout + stderr
    assert cleanup_started.is_file(), "cleanup never announced its start"
    assert cleanup_reaped.is_file(), "cleanup did not reap its process groups"
    assert _git(repo, "worktree", "list").stdout.count("\n") == 1
    # `cleanup.reaped` IS the proof that the TERM-ignoring arm died, and it is a
    # stronger one than polling a pid the arm had to publish for itself: the
    # parent writes that event only after WAITING on every arm process group it
    # started. An arm that ignored TERM and was never escalated would leave that
    # wait outstanding for ever, the event would never appear, and this test
    # fails on the deadline above rather than passing quietly.


def test_interruption_kills_a_term_ignoring_parallel_arm_and_removes_worktrees(
        sandbox, tmp_path):
    """Keep the original A2/SIGINT nodeid stable across the differential."""
    _assert_interruption_cleans_every_parallel_arm(
        sandbox, tmp_path, "A2", False)


def test_pid_only_term_kills_a_term_ignoring_b2_and_removes_worktrees(
        sandbox, tmp_path):
    """The service-stop path also owns the newly independent B2 group."""
    _assert_interruption_cleans_every_parallel_arm(
        sandbox, tmp_path, "B2", True)


def _reassert(sandbox, path):
    return subprocess.run(
        ["bash", str(_VERIFY), "--reassert", str(path), "--base", "main",
         "--repo", str(sandbox), "--no-fetch"],
        capture_output=True, text=True, timeout=_T)


def test_reassert_refuses_when_the_base_moved(sandbox, tmp_path):
    """A pass is about a BASE. Other agents land while a verify runs, and #1019
    says so explicitly — a verdict whose base has moved describes a tree nobody
    is about to create. The base is rewritten in the RECORD rather than in the
    shared repo, so this test cannot reorder into another one's way."""
    r, doc = _verify(sandbox, "innocuous_green", tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    good = tmp_path / "v_innocuous_green.json"
    assert _reassert(sandbox, good).returncode == 0

    stale = tmp_path / "stale.json"
    doc["base_sha"] = "0" * 40
    stale.write_text(json.dumps(doc))
    moved = _reassert(sandbox, stale)
    assert moved.returncode == 1, moved.stdout + moved.stderr
    assert "the base moved" in moved.stderr


def test_reassert_refuses_a_record_that_was_not_a_pass(sandbox, tmp_path):
    r, _ = _verify(sandbox, "innocuous_red", tmp_path)
    assert r.returncode == 1
    bad = _reassert(sandbox, tmp_path / "v_innocuous_red.json")
    assert bad.returncode == 1, bad.stdout + bad.stderr
    assert "not LAND_OK" in bad.stderr


def _repacked_commit(repo, source, branch, message="repack identical tree"):
    """One new commit, parented directly on main, with SOURCE's exact tree."""
    tree = _git(repo, "rev-parse", f"{source}^{{tree}}").stdout.strip()
    base = _git(repo, "rev-parse", "main").stdout.strip()
    made = subprocess.run(
        ["git", "-C", str(repo), "commit-tree", tree, "-p", base],
        input=message + "\n", capture_output=True, text=True, timeout=_T)
    assert made.returncode == 0, made.stderr
    head = made.stdout.strip()
    assert _git(repo, "branch", "-f", branch, head).returncode == 0
    return head, tree


def _rebind(sandbox, old_verdict, ref, out):
    return subprocess.run(
        ["bash", str(_VERIFY), "--rebind", str(old_verdict),
         "--ref", ref, "--base", "main", "--repo", str(sandbox),
         "--no-fetch", "--json", str(out)],
        capture_output=True, text=True, timeout=_T)


def test_identical_tree_repack_rebinds_without_rerunning_expensive_arms(
        sandbox, tmp_path):
    """Commit topology is not functional identity.

    A LAND_OK already measured the exact base + final tree.  Re-expressing that
    tree as the required one-commit push shape must run only the cheap push and
    identity/provenance checks, then emit a self-contained REBOUND_FROM record.
    It must not launch A1/A2/B1/B2 again.
    """
    first, original = _verify(sandbox, "innocuous_green", tmp_path)
    assert first.returncode == 0, first.stdout + first.stderr
    branch = f"repacked_{tmp_path.name}"
    new_head, tree = _repacked_commit(
        sandbox, original["verified_sha"], branch)
    assert tree == original["verified_tree"]

    rebound_path = tmp_path / "rebound.json"
    rebound = _rebind(
        sandbox, tmp_path / "v_innocuous_green.json", branch, rebound_path)
    assert rebound.returncode == 0, rebound.stdout + rebound.stderr
    assert "arm A1/B1" not in rebound.stdout
    record = json.loads(rebound_path.read_text())
    assert record["verdict"] == "LAND_OK"
    assert record["kind"] == "vibeic.landing-verdict-rebind"
    assert record["head_sha"] == record["verified_sha"] == new_head
    assert record["verified_tree"] == original["verified_tree"]
    assert record["rebind"]["rebound_from_head_sha"] == original["head_sha"]
    assert record["rebind"]["push_preflight"]["verdict"] == "PASS"
    assert _reassert(sandbox, rebound_path).returncode == 0


def test_rebind_refuses_when_the_final_tree_changed(sandbox, tmp_path):
    """The shortcut is identity-only; one changed blob demands a full run."""
    first, _ = _verify(sandbox, "innocuous_green", tmp_path)
    assert first.returncode == 0, first.stdout + first.stderr
    branch = f"different_tree_{tmp_path.name}"
    _repacked_commit(sandbox, "innocuous_red", branch, "different tree")
    out = tmp_path / "different-tree-rebind.json"
    rebound = _rebind(
        sandbox, tmp_path / "v_innocuous_green.json", branch, out)
    assert rebound.returncode == 1, rebound.stdout + rebound.stderr
    assert "candidate tree differs from the verified tree" in rebound.stderr


def test_actual_push_shape_is_refused_before_any_expensive_arm(
        sandbox, tmp_path):
    """The exact ordering regression that wasted the fleet run.

    The squash tree is harmless, but commit 2 retracts 3/4 substantive lines
    commit 1 adds in the SAME unpublished push. Commit 2 also replaces its own
    collateral checker with an always-PASS program. The immutable BASE-owned
    checker must still answer before merge-tree/rebase or A1/A2/B1/B2 starts.
    """
    repo = tmp_path / "push-shape-repo"
    cloned = subprocess.run(
        ["git", "clone", "-q", str(sandbox), str(repo)],
        capture_output=True, text=True, timeout=_T)
    assert cloned.returncode == 0, cloned.stderr
    _git(repo, "config", "user.email", "t@localhost")
    _git(repo, "config", "user.name", "t")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "checkout", "-q", "-b", "bad_push_shape")
    subject = repo / "push_shape.txt"
    lines = [
        "first substantive contribution line 0001",
        "second substantive contribution line 0002",
        "third substantive contribution line 0003",
        "fourth substantive contribution line 0004",
    ]
    subject.write_text("\n".join(lines) + "\n")
    _git(repo, "add", "push_shape.txt")
    assert _git(repo, "commit", "-qm", "add one contribution").returncode == 0
    subject.write_text(lines[-1] + "\n")
    self_edited_gate = (repo / "vibe-ic-marketplace" / "plugins" /
                        "vibe-ic" / "programs" /
                        "landing_collateral_revert_check.py")
    self_edited_gate.write_text(
        "#!/usr/bin/env python3\nraise SystemExit(0)\n")
    _git(repo, "add", "push_shape.txt", str(self_edited_gate.relative_to(repo)))
    assert _git(repo, "commit", "-qm",
                "retract most of it and weaken the checker").returncode == 0

    out = tmp_path / "push-shape.json"
    run = subprocess.run(
        ["bash", str(_VERIFY), "--ref", "bad_push_shape", "--base", "main",
         "--repo", str(repo), "--no-fetch", "--json", str(out)],
        capture_output=True, text=True, timeout=_T,
        env={**os.environ, "GIT_DIR": "", "GIT_WORK_TREE": ""})
    assert run.returncode == 1, run.stdout + run.stderr
    assert "PUSH PREFLIGHT: REFUSE" in run.stderr
    assert "landing_collateral_revert_check.py" in run.stderr
    assert "arm A1/B1" not in run.stdout
    assert "tree-under-test" not in run.stdout
    record = json.loads(out.read_text())
    assert record["kind"] == "vibeic.landing-push-preflight-receipt"
    assert record["verdict"] == "REFUSE"


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


def _host_has_write_tree(repo):
    """Measured, not assumed: the same capability the script probes."""
    r = _git(repo, "merge-tree", "--write-tree", "main", "main")
    return r.returncode == 0 and len(r.stdout.strip()) >= 40


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


def test_the_tier_the_script_picks_matches_this_hosts_real_capability(
        sandbox, tmp_path):
    """THE VERSION-DETECTION BRANCH ITSELF, measured rather than assumed.

    The capability is probed independently here — the same question, asked
    without the script — and the tier the script recorded must agree. On a git
    >= 2.38 host this asserts the strong path was taken; on 2.34.1 it asserts the
    fallback was, which is the whole reason this branch exists. Either way the
    detection is exercised where the gate actually runs."""
    r, doc = _verify(sandbox, "innocuous_green", tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    expected = (V.TIER_MERGE_TREE if _host_has_write_tree(sandbox)
                else V.TIER_REBASE_REPLAY)
    assert doc["verification_tier"] == expected, r.stdout
    assert doc["tier_degraded"] is (expected != V.TIER_MERGE_TREE)
    # The version is NAMED whichever tier ran, so a record can be read later
    # without knowing which host produced it.
    assert doc["git_version"], doc
    assert doc["git_version_required_for_merge_tree"] == V.MERGE_TREE_MIN_VERSION


def test_a_host_without_merge_tree_names_the_version_found_and_needed(
        sandbox, tmp_path):
    """What the reviewer asked a refusal to say, kept as a DISCLOSURE instead:
    the version found and the version needed, both named."""
    r, doc = _verify(sandbox, "innocuous_green", tmp_path, env_extra=_FALLBACK)
    assert r.returncode == 0, r.stdout + r.stderr
    assert doc["verification_tier"] == V.TIER_REBASE_REPLAY
    assert V.MERGE_TREE_MIN_VERSION in " ".join(doc["notes"])
    assert "merge-tree capability ABSENT" in r.stdout or \
        "GATEKEEPER_FORCE_REBASE_REPLAY" in doc["tier_reason"], r.stdout


# ------------------------------- THE PAIRED GUARD, end to end, UNDER THE FALLBACK


def test_end_to_end_the_fallback_still_refuses_an_innocuous_diff_that_leaves_a_test_red(
        sandbox, tmp_path):
    """NON-NEGOTIABLE, and the reason the fallback is allowed to exist at all.

    THE SAME negative control the strong tier is measured on — #1019's case that
    got through five times, an ordinary source edit with no test file in its diff
    that leaves the suite red — re-run with the strong path forced off. **A
    fallback that passes everything is worse than a gate that refuses
    everything.** This runs on every host, not only on the ones that need the
    fallback."""
    r, doc = _verify(sandbox, "innocuous_red", tmp_path, env_extra=_FALLBACK)
    assert r.returncode == 1, r.stdout + r.stderr
    assert doc["verdict"] == "REFUSE"
    assert doc["verification_tier"] == V.TIER_REBASE_REPLAY
    assert doc["delta"]["new_failures"], doc
    # REFUSED, AND HONEST ABOUT WHY IT COULD REFUSE: the weakness is on the
    # record even when the verdict is a refusal.
    assert "SQUASH_VS_REBASE_CROSS_CHECK_NOT_PERFORMED" in doc["disclosures"]


def test_end_to_end_the_fallback_allows_a_known_good_branch(sandbox, tmp_path):
    """The other arm. If this failed the fallback would be the same ban with a
    new name; if the arm above failed it would be a rubber stamp. Both are
    required for either to mean anything."""
    r, doc = _verify(sandbox, "innocuous_green", tmp_path, env_extra=_FALLBACK)
    assert r.returncode == 0, r.stdout + r.stderr
    assert doc["verdict"] == "LAND_OK"
    assert doc["verification_tier"] == V.TIER_REBASE_REPLAY
    assert doc["tier_degraded"] is True
    assert doc["delta"]["new_failures"] == []
    assert doc["land"]["stamped_sha"] is None, (
        "the non-target B2 lane minted a standalone stamp before B1 joined")
    assert any("merge verifier owns" in label
               for label in doc["land"]["report"])
    assert doc["base_land"] is not None, "arm A2 never ran under the fallback"
    # The tree under test IS the replay — that identity is the disclosed loss.
    assert doc["expected_tree"] == doc["replayed_tree"] == doc["verified_tree"]


def test_end_to_end_the_fallback_still_refuses_a_conflicting_branch(
        sandbox, tmp_path):
    """FAIL-CLOSED IS NOT WHAT WAS TRADED AWAY. With no merge-tree to compute and
    a replay that conflicted, there is no tree under test at all, and the
    fallback must refuse as unmeasurable rather than adopt the head's own tree —
    which is what is checked out in the worktree at that moment."""
    r, doc = _verify(sandbox, "conflicting", tmp_path, env_extra=_FALLBACK)
    assert r.returncode == 2, r.stdout + r.stderr
    assert doc["verdict"] == "REFUSE"
    assert doc["unmeasurable"] is True
    assert doc["rebase_status"] == "conflict"
    assert doc["expected_tree"] == "", \
        "a conflicted replay was adopted as the tree under test"
    assert doc["land"]["pass"] == [], "the suites ran on a tree nobody will merge"


def test_the_forced_fallback_is_the_only_thing_the_env_var_can_do(sandbox, tmp_path):
    """The test hook must not be a bypass. Forcing the fallback selects the
    WEAKER, DISCLOSED tier and nothing else — the same branch is refused with it
    set as without it, so there is no value of it that turns a refusal into a
    pass."""
    natural, doc_n = _verify(sandbox, "innocuous_red", tmp_path)
    forced, doc_f = _verify(sandbox, "innocuous_red", tmp_path,
                            env_extra=_FALLBACK)
    assert natural.returncode == forced.returncode == 1
    assert doc_n["verdict"] == doc_f["verdict"] == "REFUSE"
    assert doc_f["verification_tier"] == V.TIER_REBASE_REPLAY
