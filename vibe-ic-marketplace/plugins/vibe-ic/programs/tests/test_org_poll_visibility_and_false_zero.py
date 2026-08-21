#!/usr/bin/env python3
"""vibe-ic — the two ways this poll could be right and still leave the round blind.

The poll already refuses a capped listing and a failed query. Both of those are
about the poll being WRONG. On 2026-07-30 it was entirely RIGHT and the round was
still blind, twice over:

1. `vibeic/vibe-ic` had 205 issues and 353 PRs. Its `/issues` and `/pulls` pages
   rendered EMPTY to every visitor, because GitHub had flagged the account and
   the search index those pages are built from returns 200 with `total_count: 0`.
   Every listing here is GraphQL, which kept working, so no amount of care in
   the enumeration could have surfaced it. It has to be asked for directly.

2. A listing that returns zero was the one result the poll could not refuse.
   REST's `open_issues_count` said 0 for that same repository while #551 was
   open. Had the poll been built on REST, every round would have reported an
   empty queue and skipped the backlog in silence.

So: the visibility probe must not be inferred from a listing, "could not ask"
must not collapse into "the answer is fine", and a flagged account must not
fail the poll — the enumeration is still correct and the round must proceed, or
the check gets switched off the first time it blocks real work.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import org_open_work_poll as P  # noqa: E402


_SPAM_BODY = ('{"message":"User flagged as spammy.","resource":"Search",'
              '"field":"q","code":"invalid","status":"422"}')


def _fake_gh(*, spam=False, probe_rc=0, repos_json=None, issues=0, prs=0):
    """A `_gh` that answers the four calls the poll makes, and nothing else."""
    def gh(args, timeout=None):
        if args[0] == "api":                       # the visibility probe
            if spam:
                return 1, "", _SPAM_BODY
            if probe_rc:
                return probe_rc, "", "boom"
            return 0, '{"total_count":1}', ""
        if args[:2] == ["repo", "list"]:
            return 0, json.dumps(repos_json or []), ""
        if args[0] == "pr":
            return 0, json.dumps([{"number": i} for i in range(prs)]), ""
        if args[0] == "issue":
            return 0, json.dumps([{"number": i} for i in range(issues)]), ""
        raise AssertionError(f"unexpected gh call: {args}")
    return gh


_ONE_REPO = [{"name": "vibe-ic", "hasIssuesEnabled": True,
              "issues": {"totalCount": 0}}]


# --------------------------------------------------------------------------
# 1. the visibility probe
# --------------------------------------------------------------------------

def test_a_flagged_account_is_named_not_guessed(monkeypatch):
    monkeypatch.setattr(P, "_gh", _fake_gh(spam=True))
    v = P.search_index_health("vibeic")
    assert v["searchable"] is False
    assert "empty" in v["reason"].lower(), \
        "the report does not say what a visitor actually sees"


def test_a_probe_that_could_not_run_is_not_a_clean_bill(monkeypatch):
    """The distinction this repo keeps relearning: an absence of evidence read
    as evidence of absence. A failed probe must be None, never True."""
    monkeypatch.setattr(P, "_gh", _fake_gh(probe_rc=126))
    v = P.search_index_health("vibeic")
    assert v["searchable"] is None, \
        "a probe that could not run was reported as a healthy index"


def test_a_healthy_index_reports_searchable(monkeypatch):
    monkeypatch.setattr(P, "_gh", _fake_gh())
    assert P.search_index_health("vibeic")["searchable"] is True


def test_a_flagged_account_does_not_fail_the_poll(monkeypatch, capsys):
    """Load-bearing. GraphQL enumeration is unaffected by the flag, so the
    backlog is still knowable and the round must run. A check that halts the
    gatekeeper over a condition it cannot fix is a check that gets deleted."""
    monkeypatch.setattr(P, "_gh",
                        _fake_gh(spam=True, repos_json=_ONE_REPO, issues=3))
    rc = P.main(["vibeic"])
    err = capsys.readouterr().err
    assert rc == 0, f"a flagged account failed the poll (rc={rc})"
    assert "[VISIBILITY]" in err, "the flag was detected and never mentioned"
    assert "[OK]" in err, "the round did not proceed"


def test_the_visibility_verdict_reaches_the_json(monkeypatch, tmp_path):
    out = tmp_path / "poll.json"
    monkeypatch.setattr(P, "_gh",
                        _fake_gh(spam=True, repos_json=_ONE_REPO, issues=1))
    P.main(["vibeic", "--json", str(out)])
    assert json.loads(out.read_text())["visibility"]["searchable"] is False


# --------------------------------------------------------------------------
# 2. the false-zero cross-check
# --------------------------------------------------------------------------

def test_a_zero_listing_contradicting_the_repo_is_refused(monkeypatch, capsys):
    """Two sources agreeing is weak evidence. Two sources DISAGREEING proves one
    is wrong, and that is actionable where a lone zero is not."""
    repos = [{"name": "vibe-ic", "hasIssuesEnabled": True,
              "issues": {"totalCount": 7}}]
    monkeypatch.setattr(P, "_gh", _fake_gh(repos_json=repos, issues=0))
    rc = P.main(["vibeic"])
    err = capsys.readouterr().err
    assert rc == P.RC_CANNOT_COUNT, \
        f"a listing contradicting its own repo was accepted (rc={rc})"
    assert "UNKNOWN, not empty" in err


def test_an_agreed_zero_is_a_clean_empty_queue(monkeypatch, capsys):
    """The other direction, and the one that runs every round: a genuinely quiet
    org must not be turned into a permanent refusal."""
    monkeypatch.setattr(P, "_gh", _fake_gh(repos_json=_ONE_REPO, issues=0))
    assert P.main(["vibeic"]) == 0
    assert "[OK]" in capsys.readouterr().err


def test_a_repo_declaring_none_is_not_cross_checked(monkeypatch):
    """`issues` is absent for a repo with the tracker disabled; a missing count
    must not be read as a contradicting zero."""
    repos = [{"name": "f", "hasIssuesEnabled": True}]   # no `issues` key at all
    monkeypatch.setattr(P, "_gh", _fake_gh(repos_json=repos, issues=0))
    assert P.main(["vibeic"]) == 0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
