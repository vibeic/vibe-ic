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
