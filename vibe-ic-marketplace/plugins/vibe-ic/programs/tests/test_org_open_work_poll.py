#!/usr/bin/env python3
"""The gatekeeper poll was capped at 60 against an org of 63.

Three repositories — `vibe-ic-before-v1.0`, `vibeic.github.io`, `Xyce` — were
never looked at, across every round of a long session, because the shell
one-liner said `gh repo list vibeic --limit 60`. They happened to be empty, so
every "no open PRs" was correct. It was correct BY LUCK: a truncated listing and
a complete one print the same thing.

These pin the refusals, because a poll that cannot refuse is the bug it replaced.
Network is never touched — `_gh` is substituted.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import org_open_work_poll as P  # noqa: E402


def _fake(repo_rows, pr=0, issues=0, fail=(), spam=False):
    """A `_gh` stand-in driven by the sub-command."""
    def gh(args, timeout=60):
        if args[0] == "api":
            # The search-index visibility probe. These tests are about the
            # ENUMERATION refusals, and the probe must not disturb any of them —
            # a flagged org still has a knowable backlog over GraphQL, which is
            # why the probe warns rather than failing the poll.
            if spam:
                return 1, "", '{"message":"User flagged as spammy."}'
            return 0, '{"total_count":1}', ""
        if args[0] == "repo":
            return 0, json.dumps(repo_rows), ""
        full = args[args.index("--repo") + 1]
        if full in fail:
            return 1, "", "HTTP 500"
        n = pr if args[0] == "pr" else issues
        return 0, json.dumps([{"number": i} for i in range(n)]), ""
    return gh


def test_a_listing_at_the_cap_is_refused(monkeypatch):
    """THE defect. 60 rows against `--repo-limit 60` is a floor, not a count."""
    rows = [{"name": f"r{i}", "hasIssuesEnabled": True} for i in range(60)]
    monkeypatch.setattr(P, "_gh", _fake(rows))
    res = P.repos("vibeic", limit=60)
    assert "error" in res and "cap" in res["error"]


def test_the_refusal_puts_nothing_on_stdout(monkeypatch, capsys):
    """`N=$(prog) || exit 1` only fires if the failure is silent on stdout.
    A refusal that still prints a number is a refusal nobody notices."""
    rows = [{"name": f"r{i}", "hasIssuesEnabled": True} for i in range(60)]
    monkeypatch.setattr(P, "_gh", _fake(rows))
    assert P.main(["vibeic", "--repo-limit", "60"]) == P.RC_CANNOT_COUNT
    assert capsys.readouterr().out == ""


def test_a_listing_below_the_cap_counts(monkeypatch):
    """…or the test above is met by a program that always refuses."""
    rows = [{"name": f"r{i}", "hasIssuesEnabled": True} for i in range(63)]
    monkeypatch.setattr(P, "_gh", _fake(rows))
    res = P.poll("vibeic", repo_limit=500)
    assert res["repos_scanned"] == 63
    assert res["open_pr_total"] == 0 and res["open_issue_total"] == 0


def test_a_repository_that_could_not_be_queried_is_not_a_clean_one(monkeypatch):
    """rc 2, not a quiet zero: a query that failed says nothing about the queue."""
    rows = [{"name": "a", "hasIssuesEnabled": True},
            {"name": "b", "hasIssuesEnabled": True}]
    monkeypatch.setattr(P, "_gh", _fake(rows, fail={"vibeic/b"}))
    assert P.main(["vibeic"]) == P.RC_CANNOT_COUNT


def test_issues_disabled_is_reported_as_a_setting_not_a_zero(monkeypatch):
    """Forks default to `has_issues=false`. Counting that as "0 open issues"
    turns a settings fact into a backlog fact, which is how a real backlog
    would hide."""
    rows = [{"name": "fork", "hasIssuesEnabled": False},
            {"name": "main", "hasIssuesEnabled": True}]
    monkeypatch.setattr(P, "_gh", _fake(rows, issues=2))
    res = P.poll("vibeic")
    assert res["issues_disabled"] == ["vibeic/fork"]
    assert res["open_issues"] == {"vibeic/main": 2}


def test_open_work_is_actually_counted(monkeypatch):
    """…or every test above is satisfied by a program that finds nothing."""
    rows = [{"name": "a", "hasIssuesEnabled": True}]
    monkeypatch.setattr(P, "_gh", _fake(rows, pr=3, issues=5))
    res = P.poll("vibeic")
    assert res["open_pr_total"] == 3 and res["open_issue_total"] == 5


def test_a_flagged_org_still_refuses_a_failed_listing(monkeypatch, capsys):
    """The interaction the visibility probe could have broken.

    A flagged account is a warning — the enumeration is still correct and the
    round proceeds. A failed listing is a REFUSAL. When both are true the
    refusal must win, or the probe would have converted "I could not read this
    repository" into "heads-up, you are not searchable" and let the round run
    on a queue it never managed to read.
    """
    rows = [{"name": "a", "hasIssuesEnabled": True}]
    monkeypatch.setattr(P, "_gh",
                        _fake(rows, fail=("vibeic/a",), spam=True))
    assert P.main(["vibeic"]) == P.RC_CANNOT_COUNT
    err = capsys.readouterr().err
    assert "[NOT POLLED]" in err, "the refusal was downgraded to a warning"
