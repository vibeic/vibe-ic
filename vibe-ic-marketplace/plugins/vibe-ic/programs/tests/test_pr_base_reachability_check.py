"""A PR based on a closed-unmerged branch cannot reach main. vibe-ic#1364.

BOTH DIRECTIONS ARE ASSERTED, and the PASS direction is the one that matters.
A checker that reports "no orphans" is indistinguishable from one that looked at
nothing — which is the exact defect it exists to catch, one level up. So every
FAIL case here is paired with a case that must stay green, and the empty
population is a REFUSAL rather than either.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pr_base_reachability_check as G  # noqa: E402


def _pr(n, head, base="main", state="OPEN", merged=None):
    return {"number": n, "state": state, "headRefName": head,
            "baseRefName": base, "mergedAt": merged,
            "mergeable": "MERGEABLE", "mergeStateStatus": "CLEAN",
            "title": f"pr {n}"}


# --------------------------------------------------------------------------
# the population
# --------------------------------------------------------------------------
def test_a_pr_on_main_reaches_main():
    orphans, unresolved, healthy, blocked = G.audit([_pr(1, "feat/a")])
    assert (orphans, unresolved, blocked) == ([], [], set())
    assert healthy == [1]


def test_a_stack_on_an_OPEN_parent_is_healthy():
    """PAIRED with the orphan case: stacking is normal and must stay green."""
    prs = [_pr(1, "feat/parent"), _pr(2, "feat/child", base="feat/parent")]
    orphans, unresolved, _healthy, blocked = G.audit(prs)
    assert orphans == [] and unresolved == [] and blocked == set()


def test_a_stack_on_a_MERGED_parent_is_healthy():
    """A merged parent's commits are in main; the child is not orphaned."""
    prs = [_pr(1, "feat/parent", state="CLOSED", merged="2026-08-13T00:00:00Z"),
           _pr(2, "feat/child", base="feat/parent")]
    orphans, _u, _h, blocked = G.audit(prs)
    assert orphans == [] and blocked == set()


def test_a_stack_on_a_CLOSED_UNMERGED_parent_is_an_orphan():
    prs = [_pr(1, "feat/parent", state="CLOSED", merged=None),
           _pr(2, "feat/child", base="feat/parent")]
    orphans, _u, _h, blocked = G.audit(prs)
    assert [o["pr"]["number"] for o in orphans] == [2]
    assert blocked == {2}


def test_everything_ABOVE_an_orphan_is_blocked_too():
    """The stack inherits its root's fate — 2 -> 3 -> 4 all unreachable."""
    prs = [_pr(1, "feat/dead", state="CLOSED", merged=None),
           _pr(2, "feat/b", base="feat/dead"),
           _pr(3, "feat/c", base="feat/b"),
           _pr(4, "feat/d", base="feat/c")]
    orphans, _u, _h, blocked = G.audit(prs)
    assert [o["pr"]["number"] for o in orphans] == [2]
    assert blocked == {2, 3, 4}, "a stack above an orphan is equally unlandable"


def test_a_base_owned_by_no_pr_is_UNRESOLVED_not_clean():
    """The population is incomplete; that is a refusal, never a pass."""
    orphans, unresolved, _h, _b = G.audit([_pr(2, "feat/child", base="feat/ghost")])
    assert orphans == []
    assert [p["number"] for p in unresolved] == [2]


def test_a_closed_parent_does_not_orphan_a_CLOSED_child():
    """Only OPEN PRs are the subject; a closed child is nobody's problem."""
    prs = [_pr(1, "feat/dead", state="CLOSED", merged=None),
           _pr(2, "feat/b", base="feat/dead", state="CLOSED", merged=None)]
    orphans, _u, _h, blocked = G.audit(prs)
    assert orphans == [] and blocked == set()


def test_an_OPEN_owner_wins_over_a_closed_copy_of_the_same_branch():
    """Two PRs sharing a head must not resolve to the closed one and
    manufacture an orphan that is not one."""
    prs = [_pr(1, "feat/shared", state="CLOSED", merged=None),
           _pr(9, "feat/shared"),
           _pr(2, "feat/child", base="feat/shared")]
    orphans, _u, _h, blocked = G.audit(prs)
    assert orphans == [] and blocked == set()


# --------------------------------------------------------------------------
# exit codes — refusal is a verdict
# --------------------------------------------------------------------------
def _run(tmp_path, prs, extra=()):
    p = tmp_path / "prs.json"
    p.write_text(json.dumps(prs), encoding="utf-8")
    return G.main(["--from-json", str(p), *extra])


def test_clean_population_exits_0(tmp_path):
    assert _run(tmp_path, [_pr(1, "feat/a"), _pr(2, "feat/b")]) == G.RC_OK


def test_an_orphan_exits_1(tmp_path):
    assert _run(tmp_path, [_pr(1, "feat/dead", state="CLOSED", merged=None),
                           _pr(2, "feat/b", base="feat/dead")]) == G.RC_FAIL


def test_an_empty_population_REFUSES_rather_than_passing(tmp_path):
    """The whole point: 0 orphans over 0 PRs is not a pass."""
    assert _run(tmp_path, []) == G.RC_REFUSE


def test_an_unreadable_input_REFUSES(tmp_path):
    assert G.main(["--from-json", str(tmp_path / "nope.json")]) == G.RC_REFUSE


def test_an_unresolved_base_REFUSES_rather_than_passing(tmp_path):
    assert _run(tmp_path, [_pr(2, "feat/b", base="feat/ghost")]) == G.RC_REFUSE


def test_a_gh_failure_is_not_evidence_of_health(monkeypatch, capsys):
    """An API failure must never read as 'every base is healthy' (#1319)."""
    monkeypatch.setattr(G, "load_from_gh", lambda *a, **k: None)
    assert G.main([]) == G.RC_REFUSE
    assert "REFUSE" in capsys.readouterr().out


def test_the_json_report_names_the_blocked_set(tmp_path):
    out = tmp_path / "r.json"
    _run(tmp_path, [_pr(1, "feat/dead", state="CLOSED", merged=None),
                    _pr(2, "feat/b", base="feat/dead"),
                    _pr(3, "feat/c", base="feat/b")],
         extra=("--json", str(out)))
    doc = json.loads(out.read_text())
    assert doc["blocked"] == [2, 3]
    assert doc["orphans"] == [{"pr": 2, "base": "feat/dead", "parent": 1}]


# ---------------------------------------------------------------------------
# The CARRIED pass. Every test below builds a real throwaway git repository,
# because the defect being guarded is in the commit graph and a mocked graph
# would only prove the mock agrees with itself.
# ---------------------------------------------------------------------------

import subprocess


def _repo(tmp_path):
    """A repo with `origin/main` and a helper to branch off it."""
    d = tmp_path / "r"
    d.mkdir()

    def g(*a):
        subprocess.run(["git", "-C", str(d), *a], check=True,
                       capture_output=True, text=True)

    g("init", "-q", "-b", "main")
    g("config", "user.email", "t@t"); g("config", "user.name", "t")
    (d / "f").write_text("0\n")
    g("add", "f"); g("commit", "-qm", "base")
    g("update-ref", "refs/remotes/origin/main", "HEAD")

    def branch(ref, content, parent="refs/remotes/origin/main"):
        g("checkout", "-q", "--detach", parent)
        (d / "f").write_text(content)
        g("add", "f"); g("commit", "-qm", ref)
        g("update-ref", f"refs/remotes/origin/{ref}", "HEAD")

    return d, g, branch


def test_a_pr_declaring_MAIN_that_CARRIES_a_rejected_parent_is_CAUGHT(tmp_path):
    """THE REGRESSION. This is the case the first revision could not see.

    `baseRefName` reads `main`, so the DECLARED pass calls it healthy — which
    is exactly what happened to #1290 after it took this file's own (wrong)
    advice to retarget. Only the commit graph knows.
    """
    d, _, branch = _repo(tmp_path)
    branch("dead", "rejected\n")
    branch("live", "mine\n", parent="refs/remotes/origin/dead")

    prs = [_pr(1, "dead", state="CLOSED", merged=None), _pr(2, "live")]
    hits, refusal = G.carried_rejects(prs, str(d))
    assert refusal is None, refusal
    assert [h["pr"]["number"] for h in hits] == [2]
    assert hits[0]["parent"]["number"] == 1


def test_carrying_a_MERGED_parent_is_not_a_finding(tmp_path):
    """PAIRED GUARD: the check must not fire on the normal case.

    A merged parent's commits are supposed to be there. If this fired, the
    check would flag most of the queue and be turned off.
    """
    d, _, branch = _repo(tmp_path)
    branch("done", "landed\n")
    branch("live", "mine\n", parent="refs/remotes/origin/done")

    prs = [_pr(1, "done", state="CLOSED", merged="2026-01-01T00:00:00Z"),
           _pr(2, "live")]
    hits, refusal = G.carried_rejects(prs, str(d))
    assert refusal is None and hits == []


def test_a_rejected_parent_whose_commits_ARE_in_main_is_not_a_finding(tmp_path):
    """Closed unmerged, but the commits reached `main` some other way. Carrying
    them resurrects nothing."""
    d, g, branch = _repo(tmp_path)
    branch("dead", "rejected\n")
    g("update-ref", "refs/remotes/origin/main", "refs/remotes/origin/dead")
    branch("live", "mine\n", parent="refs/remotes/origin/dead")

    prs = [_pr(1, "dead", state="CLOSED", merged=None), _pr(2, "live")]
    hits, refusal = G.carried_rejects(prs, str(d))
    assert refusal is None and hits == []


def test_a_clean_branch_is_not_a_finding(tmp_path):
    d, _, branch = _repo(tmp_path)
    branch("dead", "rejected\n")
    branch("live", "mine\n")

    prs = [_pr(1, "dead", state="CLOSED", merged=None), _pr(2, "live")]
    hits, refusal = G.carried_rejects(prs, str(d))
    assert refusal is None and hits == []


def test_an_unfetched_head_REFUSES_rather_than_reporting_clean(tmp_path):
    """Rule of the file: a pass this run could not perform is not a pass.

    Without this the check answers 0 over the branches it could not resolve —
    the exact shape it exists to catch, one level up.
    """
    d, _, branch = _repo(tmp_path)
    branch("dead", "rejected\n")

    prs = [_pr(1, "dead", state="CLOSED", merged=None), _pr(2, "never-fetched")]
    hits, refusal = G.carried_rejects(prs, str(d))
    assert hits == []
    assert refusal and "do not resolve" in refusal


def test_no_git_repo_REFUSES(tmp_path):
    hits, refusal = G.carried_rejects([_pr(1, "a")], str(tmp_path / "nope"))
    assert hits == [] and refusal


def test_a_run_without_repo_dir_SAYS_the_carried_pass_did_not_run(tmp_path, capsys):
    """A clean bill must state its own scope. `[PASS] ... base chain only` and
    `[PASS] ... AND carried commits` are different verdicts."""
    _run(tmp_path, [_pr(1, "feat/a")])
    out = capsys.readouterr().out
    assert "CARRIED pass NOT ESTABLISHED" in out
    assert "base chain only" in out


def test_require_carried_turns_a_missing_pass_into_a_REFUSAL(tmp_path):
    assert _run(tmp_path, [_pr(1, "feat/a")],
                extra=("--require-carried",)) == G.RC_REFUSE


def test_a_DELETED_parent_branch_is_skipped_not_a_refusal(tmp_path):
    """A closed PR whose branch is gone carries nothing into anybody.

    Added because a mutant that removed the `ref not in known` skip SURVIVED
    the suite: without this the deleted ref reaches `for-each-ref --contains`,
    which errors, and the whole pass degrades to a refusal — turning the most
    ordinary state in the queue (485 unmerged PRs here, most with the branch
    long deleted) into "could not establish".
    """
    d, _, branch = _repo(tmp_path)
    branch("live", "mine\n")

    prs = [_pr(1, "deleted-long-ago", state="CLOSED", merged=None),
           _pr(2, "live")]
    hits, refusal = G.carried_rejects(prs, str(d))
    assert refusal is None, refusal
    assert hits == []


def test_an_open_pr_SHARING_a_head_with_a_closed_copy_does_not_carry_itself(tmp_path):
    """Every branch contains itself, so the self-exclusion is load-bearing.

    Two PRs on one head branch is irregular but real (a reopened/duplicated
    PR). Without the `head == ref` skip the OPEN one is reported as carrying
    the CLOSED one — a finding that is true of the graph and false of the
    world, and the author has no way to act on it. Added because a mutant that
    dropped the skip SURVIVED.
    """
    d, _, branch = _repo(tmp_path)
    branch("shared", "x\n")

    prs = [_pr(1, "shared", state="CLOSED", merged=None), _pr(2, "shared")]
    hits, refusal = G.carried_rejects(prs, str(d))
    assert refusal is None, refusal
    assert hits == [], f"a branch was reported as carrying itself: {hits}"


def test_EVERY_carrier_of_one_dead_branch_is_reported(tmp_path):
    """One rejected branch can be carried by several PRs, and each one has to
    be told — a per-PR remedy cannot be acted on by a PR that was not named.

    This is not hypothetical: in the live queue #1134
    (`fix/1043-vendored-attribution-retained`, closed unmerged) is carried by
    BOTH #1301 and #1309. Added because a mutant that reported only the first
    carrier SURVIVED the suite.
    """
    d, _, branch = _repo(tmp_path)
    branch("dead", "rejected\n")
    branch("live-a", "a\n", parent="refs/remotes/origin/dead")
    branch("live-b", "b\n", parent="refs/remotes/origin/dead")

    prs = [_pr(1, "dead", state="CLOSED", merged=None),
           _pr(2, "live-a"), _pr(3, "live-b")]
    hits, refusal = G.carried_rejects(prs, str(d))
    assert refusal is None, refusal
    assert sorted(h["pr"]["number"] for h in hits) == [2, 3], (
        f"only some carriers of the dead branch were reported: {hits}")


# ---------------------------------------------------------------------------
# --advisory (the wiring tier). It lowers the exit code and NOTHING else.
# ---------------------------------------------------------------------------

def _orphan_pop():
    return [_pr(1, "feat/dead", state="CLOSED", merged=None),
            _pr(2, "feat/b", base="feat/dead")]


def test_advisory_lowers_a_FAIL_to_zero(tmp_path):
    assert _run(tmp_path, _orphan_pop()) == G.RC_FAIL
    assert _run(tmp_path, _orphan_pop(), extra=("--advisory",)) == G.RC_OK


def test_advisory_still_PRINTS_every_finding_and_still_says_FAIL(tmp_path, capsys):
    """The whole risk of an advisory tier is that it becomes a mute button.

    A lowered exit code with the findings still on stdout is a disclosure; a
    lowered exit code with nothing printed is a waiver nobody voted for.
    """
    _run(tmp_path, _orphan_pop(), extra=("--advisory",))
    out = capsys.readouterr().out
    assert "[FAIL]" in out, "the advisory tier hid the verdict, not just the rc"
    assert "#2" in out and "#1" in out, "the finding itself stopped being named"
    assert "advisory" in out, "the rc was lowered without saying so"


def test_advisory_does_NOT_lower_a_REFUSAL(tmp_path):
    """`I could not look` must never share an exit code with `I looked and it
    was clean` — the rule this whole file is written around. An advisory flag
    that collapsed rc 2 would turn every offline CI run into a silent pass."""
    assert G.main(["--from-json", str(tmp_path / "absent.json"),
                   "--advisory"]) == G.RC_REFUSE
    assert _run(tmp_path, [_pr(2, "feat/b", base="feat/ghost")],
                extra=("--advisory",)) == G.RC_REFUSE
    assert _run(tmp_path, [_pr(1, "feat/a")],
                extra=("--advisory", "--require-carried")) == G.RC_REFUSE


def test_advisory_does_not_invent_a_pass_out_of_a_clean_run(tmp_path, capsys):
    """A clean population under --advisory must be indistinguishable from a
    clean population without it — no FAIL text, no advisory note."""
    assert _run(tmp_path, [_pr(1, "feat/a")], extra=("--advisory",)) == G.RC_OK
    out = capsys.readouterr().out
    assert "[FAIL]" not in out and "advisory" not in out
