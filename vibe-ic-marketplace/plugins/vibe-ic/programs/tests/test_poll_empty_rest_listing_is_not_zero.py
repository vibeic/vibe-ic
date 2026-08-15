#!/usr/bin/env python3
"""vibe-ic#1384 — an empty REST issue listing is not a count of zero issues.

`core-agent-loop/programs/poll.py` is the FIRST thing the core agent runs at
every cron wake-up, and its exit code decides whether the tick does anything:

    rc 0   no actionable issues -> the agent exits this tick
    rc 1   work to do
    rc 2   could not look -> retry next tick

`#1319` already made a FAILED call rc 2: `_list_open_issues` raises on any
non-200. What it could not refuse was a call that SUCCEEDS and is empty.
Measured 2026-08-15 on `vibeic/vibe-ic`, core quota healthy
(`X-Ratelimit-Remaining: 4751`, so not throttling):

    gh api -i repos/vibeic/vibe-ic/issues            HTTP 200, Content-Length: 2
    gh api repos/vibeic/vibe-ic/issues               []
    gh issue list --state open --limit 200 (GraphQL) 42
    gh repo view --json issues .issues.totalCount    42

Individual GETs worked; only the LIST was empty. `poll.py` reads that list, so
it printed `(no actionable issues)` and exited 0 with 42 issues open — the same
rc, the same stdout, for two opposite worlds.

WHAT THIS FILE PINS, IN BOTH DIRECTIONS
=======================================
The failing direction is easy to buy by making the program refuse every zero,
and that would be worse than the bug: a check that blocks a genuinely quiet
queue on every tick is a check somebody switches off. So both arms are pinned
here, and the second one is the load-bearing half:

    contradiction     listing 0, repository declares 41 open   -> RuntimeError,
                      rc 2, and the message names both numbers.
    agreement         listing 0, repository declares 0 open    -> rc 0, still a
                      zero. The quiet queue is not disturbed.
    unreadable        listing 0, witness unreachable           -> rc 0, but
                      [UNWITNESSED] on stderr. None is not zero; it is also not
                      grounds to halt, because the listing itself succeeded.
    not asked         listing non-empty                        -> the witness
                      call is never made. One extra call, only on the tick that
                      would otherwise go back to sleep.

The witness counts ISSUES ONLY, on purpose. REST's `open_issues_count` includes
pull requests, and this repository carries ~170 open PRs — a witness built on it
would read >0 on an empty issue queue and refuse forever. That substitution is
pinned too, because it is the exact mistake that turns this fix into an outage.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_PLUGIN = Path(__file__).resolve().parents[2]
_POLL_PATH = (_PLUGIN / "skills" / "core-agent-loop" / "programs" / "poll.py")


def _load_poll():
    """Fresh module per test — the program is a CLI script, and a shared import
    would let one test's monkeypatching leak into the next."""
    spec = importlib.util.spec_from_file_location("poll_mod_1384", _POLL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def poll_mod():
    assert _POLL_PATH.is_file(), f"poll.py not found at {_POLL_PATH}"
    return _load_poll()


def _issue(number: int) -> dict:
    return {"number": number, "title": f"example #{number}", "labels": [],
            "updated_at": "2026-08-15T00:00:00Z",
            "html_url": f"https://example/{number}"}


def _stub_listing(mod, monkeypatch, rows):
    """Make the REST enumeration return `rows` on page 1 and stop."""
    calls = []

    def fake_get(url, token):
        calls.append(url)
        return 200, rows

    monkeypatch.setattr(mod, "_api_get", fake_get)
    monkeypatch.setattr(mod, "_load_pat", lambda: "fake-token")
    return calls


def _stub_witness(mod, monkeypatch, value):
    """Replace the second source with a fixed answer; record that it was asked."""
    asked = []

    def fake(repo, token):
        asked.append(repo)
        return value

    monkeypatch.setattr(mod, "_declared_open_issue_count", fake)
    return asked


# --------------------------------------------------------------------------
# the failing direction: the measured #1384 shape
# --------------------------------------------------------------------------

def test_empty_listing_against_a_declared_backlog_is_refused(poll_mod,
                                                             monkeypatch):
    """HTTP 200 `[]` while the repository declares 41 open -> not a zero."""
    _stub_listing(poll_mod, monkeypatch, [])
    _stub_witness(poll_mod, monkeypatch, 41)

    with pytest.raises(RuntimeError) as exc:
        poll_mod._list_open_issues("vibeic/vibe-ic", "fake-token")

    msg = str(exc.value)
    assert "41" in msg, msg
    assert "UNKNOWN" in msg, msg
    assert "1384" in msg, msg


def test_cli_exits_2_not_0_on_the_contradiction(poll_mod, monkeypatch, capsys):
    """rc is the whole subject: 0 means 'exit this tick', 2 means 'retry'."""
    _stub_listing(poll_mod, monkeypatch, [])
    _stub_witness(poll_mod, monkeypatch, 41)

    rc = poll_mod.main(["--repo", "vibeic/vibe-ic"])

    assert rc == 2, "an unbelievable listing must not read as 'no work'"
    err = capsys.readouterr().err
    assert "41" in err, err


def test_all_pull_requests_and_a_declared_backlog_is_also_refused(poll_mod,
                                                                 monkeypatch):
    """The listing need not be `[]`. `/issues` returns PRs too, so a page of
    nothing but PRs yields zero ISSUES — the same false zero, one step in."""
    rows = [{"number": 9, "pull_request": {"url": "x"}}]
    _stub_listing(poll_mod, monkeypatch, rows)
    _stub_witness(poll_mod, monkeypatch, 7)

    with pytest.raises(RuntimeError):
        poll_mod._list_open_issues("vibeic/vibe-ic", "fake-token")


# --------------------------------------------------------------------------
# the passing direction: a real zero must survive, or the check gets removed
# --------------------------------------------------------------------------

def test_a_witnessed_zero_is_still_a_zero(poll_mod, monkeypatch):
    """Both sources say zero -> rc 0. The quiet queue is not disturbed."""
    _stub_listing(poll_mod, monkeypatch, [])
    asked = _stub_witness(poll_mod, monkeypatch, 0)

    assert poll_mod._list_open_issues("owner/name", "fake-token") == []
    assert asked == ["owner/name"]
    assert poll_mod.main(["--repo", "owner/name"]) == 0


def test_an_unreadable_witness_is_disclosed_but_not_fatal(poll_mod, monkeypatch,
                                                          capsys):
    """None is not zero — and it is not grounds to halt either, because the
    listing itself succeeded. Say so instead of deciding either way."""
    _stub_listing(poll_mod, monkeypatch, [])
    _stub_witness(poll_mod, monkeypatch, None)

    rc = poll_mod.main(["--repo", "owner/name"])

    assert rc == 0
    assert "[UNWITNESSED]" in capsys.readouterr().err


def test_the_witness_is_not_asked_when_the_listing_has_work(poll_mod,
                                                            monkeypatch):
    """One extra call, and only on the tick that would otherwise sleep."""
    _stub_listing(poll_mod, monkeypatch, [_issue(2), _issue(1)])
    asked = _stub_witness(poll_mod, monkeypatch, 0)

    got = poll_mod._list_open_issues("owner/name", "fake-token")

    assert [i["number"] for i in got] == [2, 1]
    assert asked == [], "the second source costs a call; do not spend it on a " \
                        "listing that already answered"
    assert poll_mod.main(["--repo", "owner/name"]) == 1


def test_a_failed_listing_still_raises_and_never_reaches_the_witness(poll_mod,
                                                                     monkeypatch):
    """#1319's guarantee is untouched: a non-200 is not evidence about the
    repository, and it must not be re-decided by a second source."""
    monkeypatch.setattr(poll_mod, "_api_get",
                        lambda url, token: (403, {"message": "blocked"}))
    asked = _stub_witness(poll_mod, monkeypatch, 0)

    with pytest.raises(RuntimeError):
        poll_mod._list_open_issues("owner/name", "fake-token")
    assert asked == []


# --------------------------------------------------------------------------
# the witness itself
# --------------------------------------------------------------------------

def test_witness_reads_the_issue_only_total(poll_mod, monkeypatch):
    """GraphQL `repository.issues.totalCount` — the same population the listing
    enumerates. Pinned because REST's `open_issues_count` includes PRs, and a
    witness built on it would refuse every quiet tick on a repo with open PRs."""
    seen = {}

    def fake_post(url, token, payload):
        seen["url"] = url
        seen["payload"] = payload
        return 200, {"data": {"repository": {"issues": {"totalCount": 41}}}}

    monkeypatch.setattr(poll_mod, "_api_post", fake_post)

    assert poll_mod._declared_open_issue_count("vibeic/vibe-ic", "t") == 41
    assert seen["url"].endswith("/graphql")
    assert seen["payload"]["variables"] == {"owner": "vibeic", "name": "vibe-ic"}
    q = seen["payload"]["query"]
    assert "issues(states:OPEN)" in q, q
    assert "pullRequests" not in q, q
    assert "open_issues_count" not in q, q


@pytest.mark.parametrize("status,body", [
    (403, {"message": "rate limited"}),
    (0, {"message": "network error"}),
    (200, {"errors": [{"message": "NOT_FOUND"}]}),
    (200, {"data": {"repository": None}}),
    (200, "not-a-dict"),
])
def test_an_unreachable_witness_is_none_never_zero(poll_mod, monkeypatch,
                                                   status, body):
    """Every way the witness can fail collapses to None, and None never becomes
    a number that could agree with a false zero."""
    monkeypatch.setattr(poll_mod, "_api_post",
                        lambda url, token, payload: (status, body))
    assert poll_mod._declared_open_issue_count("o/n", "t") is None


def test_witness_rejects_a_malformed_repo_without_calling_out(poll_mod,
                                                              monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no call should be made for a malformed repo")

    monkeypatch.setattr(poll_mod, "_api_post", boom)
    assert poll_mod._declared_open_issue_count("no-slash", "t") is None


def test_api_post_encodes_json_and_reports_transport_failure_as_status_0(
        poll_mod, monkeypatch):
    """Same error encoding as `_api_get`: a transport failure is status 0, never
    an empty success that a caller could mistake for data."""
    import urllib.error

    captured = {}

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"ok":true}'
        def getcode(self): return 200

    def fake_urlopen(req, timeout=None):
        captured["method"] = req.get_method()
        captured["data"] = json.loads(req.data.decode())
        return _Resp()

    monkeypatch.setattr(poll_mod.urllib.request, "urlopen", fake_urlopen)
    status, data = poll_mod._api_post("https://x/graphql", "t", {"query": "q"})
    assert (status, data) == (200, {"ok": True})
    assert captured["method"] == "POST"
    assert captured["data"] == {"query": "q"}

    def fake_boom(req, timeout=None):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(poll_mod.urllib.request, "urlopen", fake_boom)
    status, data = poll_mod._api_post("https://x/graphql", "t", {"query": "q"})
    assert status == 0
    assert "network error" in data["message"]

    class _Junk(_Resp):
        def read(self): return b"<html>not json</html>"

    monkeypatch.setattr(poll_mod.urllib.request,
                        "urlopen", lambda req, timeout=None: _Junk())
    status, data = poll_mod._api_post("https://x/graphql", "t", {"query": "q"})
    assert status == 0
    assert "unparsable" in data["message"], data
    assert "network error" not in data["message"], \
        "a 200 with a non-JSON body is not a network error; naming it one is " \
        "the same substitution this program exists to stop"
