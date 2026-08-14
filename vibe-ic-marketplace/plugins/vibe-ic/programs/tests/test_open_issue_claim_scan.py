#!/usr/bin/env python3
"""vibe-ic#1464 — "0 unclaimed" must never be what a blocked scan looks like.

The hand-typed loop this program replaces was measured with a `gh` that fails
the way an exhausted GraphQL budget does, and with one that answers cleanly for
an empty repository. Both produced ZERO BYTES on stdout and rc 0 — the same
md5, d41d8cd98f00b204e9800998ecf8427e. The agent reading them cannot tell
"nobody has claimed anything" from "I was not allowed to ask", and the standing
brief routes the second one to STOP.

Three mechanisms produce that, and each has a test below:

    a failed call        `$c` is "" and `[ "" = "0" ]` is false, so nothing prints
    the default --limit  117 open issues on this repo, 30 returned, rc 0
    the per-issue cap    100 comments returned for #1241, which has 387

The tests come in pairs on purpose. A guard that refuses everything would pass
every "must refuse" test and be deleted the first week, because a genuinely
quiet queue has to keep reporting. So each refusal is paired with the reading
that must still succeed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import open_issue_claim_scan as P  # noqa: E402


_RATE_LIMITED = "GraphQL: API rate limit already exceeded for user ID 3784584."


def _issue(number, comments):
    return {"number": number, "title": f"issue {number}", "comments": comments}


def _claim(who="agent-a"):
    return {"body": f"CLAIMED: {who} on some-host"}


def _chatter(n=1):
    return [{"body": f"ordinary comment {i}"} for i in range(n)]


def _fake_gh(*, list_rc=0, list_out=None, list_err="",
             declared=None, view_rc=0, calls=None):
    """A `_gh` answering only the calls this program makes."""
    def gh(args, timeout=None):
        assert timeout is not None and timeout <= 60, (
            f"inner subprocess bound {timeout} exceeds the landing harness's "
            f"own 60s: a hang would take the whole session, not one test")
        if calls is not None:
            calls.append(list(args))
        if args[0] == "issue":
            return list_rc, ("" if list_out is None
                             else json.dumps(list_out)), list_err
        if args[0] == "repo":
            if view_rc:
                return view_rc, "", "boom"
            return 0, json.dumps({"issues": {"totalCount": declared}}), ""
        raise AssertionError(f"unexpected gh call: {args}")
    return gh


# --------------------------------------------------------------------------
# 1. a call that failed is not a count of zero
# --------------------------------------------------------------------------

def test_a_rate_limited_scan_is_refused_not_reported_as_zero(monkeypatch,
                                                             capsys):
    monkeypatch.setattr(P, "_gh", _fake_gh(list_rc=1, list_err=_RATE_LIMITED))
    rc = P.main([])
    cap = capsys.readouterr()
    assert rc == P.RC_CANNOT_SCAN, \
        f"a blocked scan resolved into an answer (rc={rc})"
    assert cap.out == "", \
        "a refusal printed something on stdout; a caller's $(...) reads it"
    assert "rate limit" in cap.err.lower(), \
        "the refusal did not say WHICH wall it hit"


def test_the_refusal_names_the_consequence(monkeypatch, capsys):
    """#1464's thesis in one string. Without it the operator sees a failed
    command and not the reason the queue looked empty."""
    monkeypatch.setattr(P, "_gh", _fake_gh(list_rc=1, list_err=_RATE_LIMITED))
    P.main([])
    assert "0 unclaimed" in capsys.readouterr().err


def test_an_unparsable_listing_is_refused(monkeypatch, capsys):
    def gh(args, timeout=None):
        return 0, "<html>not json</html>", ""
    monkeypatch.setattr(P, "_gh", gh)
    assert P.main([]) == P.RC_CANNOT_SCAN
    assert capsys.readouterr().out == ""


def test_a_real_scan_still_reports(monkeypatch, capsys):
    """The other direction. A guard that only ever refuses is a guard that
    gets removed."""
    monkeypatch.setattr(P, "_gh", _fake_gh(list_out=[
        _issue(101, [_claim()]),
        _issue(102, _chatter(3)),
    ]))
    rc = P.main([])
    cap = capsys.readouterr()
    assert rc == P.RC_OK, f"a healthy scan was refused (rc={rc})"
    assert json.loads(cap.out)["unclaimed"] == [102]
    assert json.loads(cap.out)["claimed"] == 1


# --------------------------------------------------------------------------
# 2. the default --limit 30, and the denominator that would have shown it
# --------------------------------------------------------------------------

def test_the_listing_limit_is_passed_explicitly(monkeypatch):
    """`gh issue list` defaults to 30. Measured on this repo the same day:
    30 of 117 open issues returned, rc 0, output a well-formed newest-first
    list. Leaving the flag off is mechanism (2) of #1464."""
    calls = []
    monkeypatch.setattr(P, "_gh", _fake_gh(list_out=[], declared=0,
                                           calls=calls))
    P.scan()
    listing = next(c for c in calls if c[0] == "issue")
    assert "--limit" in listing, "the scan inherited gh's default of 30"
    assert int(listing[listing.index("--limit") + 1]) > 200, \
        "the explicit limit is not above any plausible open-issue count"


def test_a_listing_at_the_cap_is_refused(monkeypatch, capsys):
    """At the cap a full page and a truncated one are the same bytes."""
    monkeypatch.setattr(P, "_gh", _fake_gh(
        list_out=[_issue(n, _chatter()) for n in range(5)]))
    rc = P.main(["--limit", "5"])
    cap = capsys.readouterr()
    assert rc == P.RC_CANNOT_SCAN, \
        f"a listing that may have been truncated produced a set (rc={rc})"
    assert cap.out == ""
    assert "floor" in cap.err


def test_the_denominator_is_published(monkeypatch, capsys):
    """"The scan should state how many issues it examined" — a pass over 30 of
    117 must not print the same thing as a pass over all 117."""
    monkeypatch.setattr(P, "_gh", _fake_gh(list_out=[
        _issue(n, [_claim()]) for n in range(7)] + [_issue(99, _chatter())]))
    P.main([])
    cap = capsys.readouterr()
    assert json.loads(cap.out)["scanned"] == 8, \
        "the unclaimed set was published without the population it came from"
    assert "of 8 open issue(s) examined" in cap.err


# --------------------------------------------------------------------------
# 3. the per-issue comment cap — the truncation inside the remedy itself
# --------------------------------------------------------------------------

def test_a_capped_comment_list_with_no_claim_is_unmeasured(monkeypatch,
                                                           capsys):
    """MEASURED: `gh issue list --json comments` returned exactly 100 comments
    for #1241, which has 387. A claim past the cap is invisible, so the
    NEGATIVE answer is the one truncation can fabricate."""
    monkeypatch.setattr(P, "_gh", _fake_gh(list_out=[
        _issue(1241, _chatter(P.COMMENT_PAGE_CAP))]))
    rc = P.main([])
    cap = capsys.readouterr()
    assert rc == P.RC_CANNOT_SCAN, \
        f"a truncated comment list produced an 'unclaimed' verdict (rc={rc})"
    assert cap.out == ""
    assert "#1241" in cap.err, "the unmeasured issue was not named"


def test_a_capped_comment_list_with_a_claim_is_claimed(monkeypatch, capsys):
    """The asymmetry that keeps this usable: a claim FOUND is positive evidence
    and survives truncation. Only its absence is unproven."""
    monkeypatch.setattr(P, "_gh", _fake_gh(list_out=[
        _issue(1241, [_claim()] + _chatter(P.COMMENT_PAGE_CAP - 1))]))
    rc = P.main([])
    assert rc == P.RC_OK, f"a claim visible under truncation was ignored (rc={rc})"
    assert json.loads(capsys.readouterr().out)["claimed"] == 1


def test_a_missing_comments_field_is_not_no_claims(monkeypatch, capsys):
    """A 200 whose `comments` came back null. The issue was listed; its claims
    were never read."""
    monkeypatch.setattr(P, "_gh", _fake_gh(list_out=[
        {"number": 7, "title": "t", "comments": None}]))
    assert P.main([]) == P.RC_CANNOT_SCAN
    assert capsys.readouterr().out == ""


def test_a_claim_must_start_the_comment(monkeypatch):
    """Discussion of the protocol is not a claim on the issue. Every comment on
    #1464 mentions the word; one of them claims it."""
    monkeypatch.setattr(P, "_gh", _fake_gh(list_out=[
        _issue(5, [{"body": "the CLAIMED: comment has no scope and no expiry"}])
    ]))
    assert P.scan()["unclaimed"] == [5]


# --------------------------------------------------------------------------
# 4. the zero that no listing check can refuse
# --------------------------------------------------------------------------

def test_an_empty_listing_contradicting_the_repo_is_refused(monkeypatch,
                                                            capsys):
    """A successful, well-formed, empty listing was wrong about this exact
    repository on 2026-07-30 (#554) and again on 2026-08-13 (#1319)."""
    monkeypatch.setattr(P, "_gh", _fake_gh(list_out=[], declared=117))
    rc = P.main([])
    cap = capsys.readouterr()
    assert rc == P.RC_CANNOT_SCAN, f"a contradicted zero was accepted (rc={rc})"
    assert cap.out == ""
    assert "UNKNOWN, not empty" in cap.err


def test_a_witnessed_empty_queue_is_a_clean_answer(monkeypatch, capsys):
    """The direction that runs whenever the backlog is genuinely drained."""
    monkeypatch.setattr(P, "_gh", _fake_gh(list_out=[], declared=0))
    assert P.main([]) == P.RC_OK
    cap = capsys.readouterr()
    assert json.loads(cap.out)["unclaimed_count"] == 0
    assert "[OK]" in cap.err


def test_an_unreadable_witness_is_named_not_fatal(monkeypatch, capsys):
    """"I could not ask the second source" is not "the second source disagreed".
    The listing itself succeeded, so the round proceeds — and says so."""
    monkeypatch.setattr(P, "_gh", _fake_gh(list_out=[], view_rc=126))
    assert P.main([]) == P.RC_OK
    assert "[UNWITNESSED]" in capsys.readouterr().err


def test_the_witness_is_only_paid_for_when_the_answer_is_nothing(monkeypatch):
    """One call for the scan, not 1+N: 118 calls for the 117 open issues
    measured on this repo. The witness is the only extra, and only on a zero."""
    calls = []
    monkeypatch.setattr(P, "_gh", _fake_gh(
        list_out=[_issue(n, _chatter()) for n in range(40)], calls=calls))
    res = P.scan()
    assert res["calls"] == 1 and len(calls) == 1, \
        f"the scan cost {len(calls)} calls for 40 issues"


# --------------------------------------------------------------------------
# 5. the JSON side-channel carries the same refusal
# --------------------------------------------------------------------------

def test_the_json_report_carries_the_error_not_an_empty_set(monkeypatch,
                                                            tmp_path):
    """A downstream reader of the JSON must hit `error`, never an `unclaimed`
    key that happens to be absent and defaults to []."""
    out = tmp_path / "scan.json"
    monkeypatch.setattr(P, "_gh", _fake_gh(list_rc=1, list_err=_RATE_LIMITED))
    P.main(["--json", str(out)])
    payload = json.loads(out.read_text())
    assert "error" in payload
    assert "unclaimed" not in payload, \
        "a refused scan still published an unclaimed set"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
