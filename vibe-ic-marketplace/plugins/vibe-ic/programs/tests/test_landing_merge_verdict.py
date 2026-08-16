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
_T = 55

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
           "--base-sha", SHA, "--head-sha", SHA, "--verified-sha", SHA,
           "--rebase-status", "ok", "--expected-tree", TREE,
           "--verified-tree", TREE, "--github-tree", TREE,
           "--land-log", str(tmp_path / "land.log"),
           "--selection", str(tmp_path / "sel.txt"), *base_sel_arg,
           "--base-junit", str(bj), "--candidate-junit", str(cj),
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
         "--base-sha", SHA, "--head-sha", SHA, "--verified-sha", SHA,
         "--rebase-status", "ok", "--expected-tree", TREE,
         "--verified-tree", TREE, "--github-tree", TREE,
         "--land-log", str(tmp_path / "land.log"),
         "--selection", str(tmp_path / "sel.txt"),
         "--base-selection", str(tmp_path / "sel_base.txt"),
         "--base-junit", str(tmp_path / "never_written.xml"),
         "--candidate-junit", str(cj),
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
        [sys.executable, str(_PROG), "--base-sha", SHA, "--head-sha", SHA,
         "--verified-sha", SHA, "--rebase-status", "ok",
         "--expected-tree", TREE, "--verified-tree", TREE,
         "--land-log", str(tmp_path / "land.log"),
         "--selection", str(tmp_path / "sel.txt"),
         "--base-junit", str(tmp_path / "nope.xml"),
         "--candidate-junit", str(tmp_path / "nope.xml")],
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
    REFUSAL. So the verdict program is resolved from THIS repo first, with the
    candidate's copy only as the fallback for a foreign `--repo`."""
    src = _VERIFY.read_text(encoding="utf-8")
    body = [l for l in src.splitlines()
            if "landing_merge_verdict.py" in l and not l.lstrip().startswith("#")]
    assert body, "the script never names the verdict program"
    assert any("SELF_REPO" in l for l in body), \
        "the verdict program is not resolved from the gatekeeper's own repo"
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


def test_the_base_gate_cache_is_keyed_by_the_base_commit():
    """Measured on this host: one repo-hygiene pass is 19 min, and the gate
    differential needs two. In a serialized merge queue the base moves once per
    landing, so arm A2's answer is reusable — but only because the key is the base
    COMMIT. A cache keyed by anything else would answer a later verification with
    an earlier tree's gates, and it would answer it permissively."""
    src = _VERIFY.read_text(encoding="utf-8")
    body = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert '"base=$BASE_SHA"' in body, "the cache omits the base commit"
    assert 'gatekeeper-base-cache-schema=3-green-only' in body
    assert 'host=$THIS_HOST' in body
    assert 'CACHE_FINGERPRINT' in body
    assert 'CACHED_MANIFEST' in body
    # An empty, unterminated, or half-published log must never be cached: it
    # would read as "the base fails nothing", which is the permissive direction.
    assert "grep -q '^=== gatekeeper landing gates'" in body
    assert "grep -q '^=== ALL GATES PASS'" in body
    assert '! grep -q \'^  FAIL  \' "$CACHED"' in body
    assert 'flock -n "$A2_CACHE_LOCK_FD"' in body
    assert 'mv "$CACHE_TMP.manifest" "$CACHED_MANIFEST"' in body


def test_the_critical_path_does_not_run_targeted_tests_inside_a2_again():
    src = _VERIFY.read_text(encoding="utf-8")
    body = "\n".join(line for line in src.splitlines()
                     if not line.lstrip().startswith("#"))
    assert "GATEKEEPER_SKIP_TARGETED_TESTS=1" in body
    assert "GATEKEEPER_FAIL_FAST_NORECORD=1" in body


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
    verify = _VERIFY.read_text(encoding="utf-8")
    vbody = "\n".join(l for l in verify.splitlines()
                      if not l.lstrip().startswith("#"))
    assert "GATEKEEPER_PYTEST_MAXFAIL=0" in vbody, \
        "the candidate arm still truncates, so the differential cannot be computed"
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
import sys
print("programs/tests/test_thing.py")
"""

_STUB_LAND = r"""#!/usr/bin/env bash
# A minimal stand-in for gatekeeper-land.sh with the same OBSERVABLE contract:
# the sentinel, `  PASS  ` / `  FAIL  ` lines, a junit report when asked, and a
# stamp only when everything passed.
set -uo pipefail
ROOT="$(git rev-parse --show-toplevel)"
PLUGIN="$ROOT/vibe-ic-marketplace/plugins/vibe-ic"
if [ -n "${GATEKEEPER_CONCURRENCY_PROBE_DIR:-}" ]; then
  mkdir -p "$GATEKEEPER_CONCURRENCY_PROBE_DIR"
  : > "$GATEKEEPER_CONCURRENCY_PROBE_DIR/${GATEKEEPER_VERIFY_ARM:-unknown}.started"
fi
echo "=== gatekeeper landing gates — base=${GATEKEEPER_BASE:-origin/main} ==="
echo "  PASS  a cheap gate"
SEL="$(mktemp -t stub_sel.XXXXXX)"
JOUT="${GATEKEEPER_PYTEST_JUNIT:-$(mktemp -t stub_junit.XXXXXX)}"
( cd "$PLUGIN" && python3 programs/ci_targeted_test_select.py --base "${GATEKEEPER_BASE:-HEAD}" ) > "$SEL"
if [ "${GATEKEEPER_SKIP_TARGETED_TESTS:-0}" = "1" ]; then
  echo "  SKIP  targeted tests — measured by the independent aggregate test arm"
  echo "=== ALL GATES PASS — stamped $(git rev-parse --short HEAD) ==="
elif ( cd "$PLUGIN" && python3 programs/pytest_per_file_junit.py \
       --selection "$SEL" --junit "$JOUT" --stall-after 10 \
       --aggregate-check --aggregate-only --aggregate-stall-after 10 \
       -- python3 -m pytest -q --maxfail=10 >/dev/null 2>&1 ); then
  echo "  PASS  targeted tests (1 file(s))"
  echo "  REPORT  targeted test process verdicts embedded in junit"
  echo "  REPORT  targeted aggregate session completed"
  git rev-parse HEAD > "$(git rev-parse --absolute-git-dir)/gatekeeper-stamp"
  echo "=== ALL GATES PASS — stamped $(git rev-parse --short HEAD) ==="
else
  echo "  FAIL  targeted tests (1 file(s))"
  echo "  REPORT  targeted test process verdicts embedded in junit"
  echo "  REPORT  targeted aggregate session completed"
  echo "=== FAILURES ABOVE — stamp removed; the pre-push hook will refuse ==="
fi
rm -f "$SEL"
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
    needed = [pathlib.Path(probe) / "A2.started", pathlib.Path(probe) / "B.started"]
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline and not all(path.is_file() for path in needed):
        time.sleep(0.02)
    assert all(path.is_file() for path in needed), "A1 completed before A2 and B started"


def test_value_is_one():
    _require_parallel_gate_arms()
    src = (pathlib.Path(__file__).resolve().parents[1] / "thing.py").read_text()
    assert "VALUE = 1" in src
"""


def _git(repo, *args, **kw):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          text=True, timeout=_T, **kw)


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    """A real git repo with the shape `gatekeeper-verify-merge.sh` expects."""
    if shutil.which("git") is None:                       # pragma: no cover
        pytest.skip("no git")
    repo = tmp_path_factory.mktemp("gkverify_repo")
    plugin = repo / "vibe-ic-marketplace/plugins/vibe-ic"
    (plugin / "programs/tests").mkdir(parents=True)
    (repo / "tools").mkdir()
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
    (plugin / "programs/thing.py").write_text(_THING_SRC.format(v=1))
    (plugin / "programs/tests/test_thing.py").write_text(_THING_TEST)
    (plugin / "pytest.ini").write_text("[pytest]\ntestpaths = programs/tests\n")
    (repo / "contended.txt").write_text("base\n")
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
    _git(repo, "checkout", "-q", "main")
    return repo


def _verify(repo, ref, tmp_path, *extra, env_extra=None):
    out = tmp_path / f"v_{ref}.json"
    r = subprocess.run(
        ["bash", str(_VERIFY), "--ref", ref, "--base", "main",
         "--repo", str(repo), "--no-fetch", "--json", str(out), *extra],
        capture_output=True, text=True, timeout=_T,
        env={**os.environ, "GIT_DIR": "", "GIT_WORK_TREE": "",
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
    assert doc["land"]["stamped_sha"], "the landing gates never stamped"
    assert doc["base_land"] is not None, "arm A2 never ran, so the gate tier was asserted"
    assert any("targeted tests" in label
               for label in doc["base_land"]["skip"]), (
        "A2 duplicated the targeted suite already measured by A1")


def test_end_to_end_base_gate_cache_hits_exactly_and_misses_after_base_moves(
        sandbox, tmp_path):
    """A reusable baseline must prove both HIT and stale-key MISS."""
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
    old_base = first_doc["base_sha"]
    old_manifests = {
        p for p in cache.glob(f"{old_base}.*.manifest")
        if not p.name.endswith(".base-tests.manifest")}
    assert len(old_manifests) == 1

    hit_dir = tmp_path / "cache-hit"
    hit_dir.mkdir()
    hit, hit_doc = _verify(
        repo, "innocuous_green", hit_dir,
        "--base-gate-cache", str(cache))
    assert hit.returncode == 0, hit.stdout + hit.stderr
    assert hit_doc["base_sha"] == old_base
    assert "arm A2: reused the gate log" in hit.stdout
    assert "arm A1: reused aggregate test evidence" in hit.stdout

    _git(repo, "checkout", "-q", "main")
    (repo / "base_moved.txt").write_text("new base\n")
    _git(repo, "add", "base_moved.txt")
    assert _git(repo, "commit", "-qm", "move base").returncode == 0
    _git(repo, "checkout", "-q", "-b", "green_after_move")
    (repo / "green_after_move.txt").write_text("candidate\n")
    _git(repo, "add", "green_after_move.txt")
    assert _git(repo, "commit", "-qm", "green after move").returncode == 0

    miss_dir = tmp_path / "cache-miss"
    miss_dir.mkdir()
    probe = tmp_path / "cache-miss-probe"
    miss, miss_doc = _verify(
        repo, "green_after_move", miss_dir,
        "--base-gate-cache", str(cache),
        env_extra={"GATEKEEPER_CONCURRENCY_PROBE_DIR": str(probe)})
    assert miss.returncode == 0, miss.stdout + miss.stderr
    assert miss_doc["base_sha"] != old_base
    assert f"base {old_base[:12]}" not in miss.stdout
    assert (probe / "A2.started").is_file(), "moved base reused stale A2"
    assert list(cache.glob(f"{miss_doc['base_sha']}.*.manifest"))


def test_end_to_end_a1_a2_and_b_start_in_parallel_isolated_worktrees(
        sandbox, tmp_path):
    """The three expensive merge-verification arms are one critical path.

    A1's real test waits until the A2 and B landing wrappers have both started.
    The old serial implementation times out in A1 before either marker can
    exist; the concurrent implementation completes normally.  The ordinary
    end-to-end assertions also prove that concurrency did not change the
    verdict or lose either arm's evidence.
    """
    probe = tmp_path / "parallel-arms"
    r, doc = _verify(
        sandbox, "innocuous_green", tmp_path,
        env_extra={"GATEKEEPER_CONCURRENCY_PROBE_DIR": str(probe)},
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert doc["verdict"] == "LAND_OK"
    assert {p.name for p in probe.iterdir()} >= {"A2.started", "B.started"}
    assert doc["base_land"] is not None
    assert doc["delta"]["new_failures"] == []


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


@pytest.mark.parametrize(
    ("hung_arm", "pid_only_term"),
    [("A2", False), ("B", True)],
)
def test_interruption_kills_a_term_ignoring_parallel_arm_and_removes_worktrees(
        sandbox, tmp_path, hung_arm, pid_only_term):
    """Parallel speed must not trade an interrupt for leaked gate processes.

    A private clone's selected arm deliberately ignores TERM forever.  Both a
    process-group SIGINT and the common PID-only SIGTERM service-stop path must
    run bounded cleanup, escalate every dedicated group to KILL, reap it, and
    remove all three temporary worktrees.
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
    hang = r'''if [ -n "${GATEKEEPER_CONCURRENCY_PROBE_DIR:-}" ] \
   && [ "${GATEKEEPER_VERIFY_ARM:-}" = "__HUNG_ARM__" ]; then
  echo "$$" > "$GATEKEEPER_CONCURRENCY_PROBE_DIR/__HUNG_ARM__.pid"
  trap '' TERM
  while :; do sleep 30; done
fi
'''.replace("__HUNG_ARM__", hung_arm)
    assert needle in text
    land.write_text(text.replace(needle, hang + needle))
    _git(repo, "add", "tools/gatekeeper-land.sh")
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
        env={**os.environ, "GIT_DIR": "", "GIT_WORK_TREE": "",
             "GATEKEEPER_CONCURRENCY_PROBE_DIR": str(probe)},
    )
    pid_file = probe / f"{hung_arm}.pid"
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline and not pid_file.is_file():
        if proc.poll() is not None:
            break
        time.sleep(0.05)
    assert pid_file.is_file(), proc.communicate(timeout=2)
    arm_pid = int(pid_file.read_text().strip())

    if pid_only_term:
        os.kill(proc.pid, signal.SIGTERM)
    else:
        os.killpg(proc.pid, signal.SIGINT)
    # Wait on the cleanup protocol, not on a wall-clock estimate of how fast a
    # loaded host can remove three worktrees.  `_T` is only the suite's final
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
        for pgid in (proc.pid, arm_pid):
            try:
                os.killpg(pgid, signal.SIGKILL)
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
    with pytest.raises(ProcessLookupError):
        os.kill(arm_pid, 0)


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
    assert doc["land"]["stamped_sha"], "the landing gates never stamped"
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
