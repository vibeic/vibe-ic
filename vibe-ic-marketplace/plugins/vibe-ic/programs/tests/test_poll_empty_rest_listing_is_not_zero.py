#!/usr/bin/env python3
"""vibe-ic#1384/#1645 — never infer the issue queue from REST's false zero.

#1384 originally cross-checked an empty REST listing with GraphQL.  #1645
removes the unreliable listing from the decision path entirely and enumerates
the issue-only GraphQL connection.  These integration tests keep #1384's two
load-bearing outcomes while pinning the new source of truth.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_PLUGIN = Path(__file__).resolve().parents[2]
_POLL_PATH = _PLUGIN / "skills" / "core-agent-loop" / "programs" / "poll.py"


def _load_poll():
    spec = importlib.util.spec_from_file_location("poll_mod_1384", _POLL_PATH)
    mod = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = previous
    return mod


@pytest.fixture()
def poll_mod():
    assert _POLL_PATH.is_file()
    return _load_poll()


def _page(numbers, *, has_next=False, cursor=None):
    nodes = [{
        "number": number,
        "title": f"issue #{number}",
        "labels": {"nodes": []},
        "updatedAt": "2026-08-15T00:00:00Z",
        "url": f"https://example/{number}",
    } for number in numbers]
    return {"data": {"repository": {
        "hasIssuesEnabled": True,
        "issues": {
            "nodes": nodes,
            "pageInfo": {
                "hasNextPage": has_next,
                "endCursor": cursor,
            },
        },
    }}}


def test_rest_false_zero_is_not_consulted(poll_mod, monkeypatch):
    """GraphQL reports work even when every hypothetical REST list is []."""
    seen = []

    def transport(url, token, payload=None):
        seen.append((url, payload))
        if url.endswith("/graphql"):
            return 200, _page([41, 40])
        return 200, []

    monkeypatch.setattr(poll_mod, "_api_request", transport)

    got = poll_mod._list_open_issues("vibeic/vibe-ic", "fake-token")

    assert [row["number"] for row in got] == [41, 40]
    assert all(url.endswith("/graphql") for url, _payload in seen)


def test_graphql_work_makes_cli_exit_one(poll_mod, monkeypatch, capsys):
    monkeypatch.setattr(poll_mod, "_load_pat", lambda: "fake-token")
    monkeypatch.setattr(
        poll_mod, "_api_request",
        lambda url, token, payload=None: (200, _page([41])))

    assert poll_mod.main(["--repo", "vibeic/vibe-ic"]) == 1
    assert "total open: 1" in capsys.readouterr().out


def test_a_genuine_graphql_zero_still_exits_zero(poll_mod, monkeypatch,
                                                  capsys):
    """The migration must not turn a quiet repository into an outage."""
    monkeypatch.setattr(poll_mod, "_load_pat", lambda: "fake-token")
    monkeypatch.setattr(
        poll_mod, "_api_request",
        lambda url, token, payload=None: (200, _page([])))

    assert poll_mod.main(["--repo", "vibeic/vibe-ic"]) == 0
    assert "(no actionable issues)" in capsys.readouterr().out


def test_failed_graphql_listing_is_unknown_not_zero(poll_mod, monkeypatch,
                                                    capsys):
    """A refused enumeration remains rc 2, never 'nothing to do'."""
    monkeypatch.setattr(poll_mod, "_load_pat", lambda: "fake-token")
    monkeypatch.setattr(
        poll_mod, "_api_request",
        lambda url, token, payload=None: (403, {"message": "blocked"}))
    monkeypatch.setattr(poll_mod, "_rate_limit_snapshot", lambda token: None)

    assert poll_mod.main(["--repo", "vibeic/vibe-ic"]) == 2
    assert "ERROR:" in capsys.readouterr().err


def test_graphql_pagination_is_complete(poll_mod, monkeypatch):
    pages = [_page([3, 2], has_next=True, cursor="next"), _page([1])]
    after = []

    def transport(url, token, payload=None):
        after.append(payload["variables"]["after"])
        return 200, pages.pop(0)

    monkeypatch.setattr(poll_mod, "_api_request", transport)

    got = poll_mod._list_open_issues("vibeic/vibe-ic", "fake-token")

    assert [row["number"] for row in got] == [3, 2, 1]
    assert after == [None, "next"]
