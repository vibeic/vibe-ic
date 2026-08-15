"""tests/test_poll_false_zero.py — a 200 with `[]` is not an empty queue.

vibe-ic#1645. `_list_open_issues` used to enumerate with the REST listing

    GET /repos/{repo}/issues?state=open&per_page=100&page=N

and #1319 had already made a FAILED call raise rather than return `[]`.
What was left is the case where the call SUCCEEDS and the answer is
wrong. MEASURED 2026-08-15 against `vibeic/vibe-ic`, which had 33 open
issues at that moment over GraphQL:

    gh api 'repos/vibeic/vibe-ic/issues?state=open&per_page=100'  ->  []
    gh api 'repos/vibeic/vibe-ic/pulls?state=open&per_page=100'   ->  6
    gh api repos/vibeic/vibe-ic/issues/1645 --jq .state           -> "open"

HTTP 200, a well-formed empty array, for a repository whose issues are
intact over GraphQL and readable one at a time over REST. Run that day,
this program printed `total open: 0` / `(no actionable issues)` and
exited 0 — which the skill defines as "Core agent exits this tick".

The fake transport below answers exactly that way: REST listings `[]`,
GraphQL the truth. Every assertion here is about the OUTCOME (issues
found, exit code, refusal raised), never about which line of code runs,
so it holds for any implementation that gets the answer right.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

_HERE = Path(__file__).resolve()
_POLL_PATH = _HERE.parents[1] / "programs" / "poll.py"
_spec = importlib.util.spec_from_file_location("poll_mod_false_zero",
                                               _POLL_PATH)
poll_mod = importlib.util.module_from_spec(_spec)  # type: ignore
_spec.loader.exec_module(poll_mod)  # type: ignore


def _node(number: int, labels=()) -> Dict[str, Any]:
    return {
        "number": number,
        "title": f"open issue #{number}",
        "url": f"https://github.com/vibeic/vibe-ic/issues/{number}",
        "updatedAt": "2026-08-15T00:00:00Z",
        "labels": {"nodes": [{"name": n} for n in labels]},
    }


def _graphql_page(nodes: List[Dict[str, Any]], *, has_next: bool = False,
                  cursor: Optional[str] = None) -> Dict[str, Any]:
    return {"data": {"repository": {"issues": {
        "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
        "nodes": nodes}}}}


def _transport(pages: List[Dict[str, Any]], seen: Optional[list] = None):
    """A GitHub that behaves the way GitHub behaved on 2026-08-15."""
    calls = {"n": 0}

    def _fake(url: str, token: str, payload: Optional[dict] = None):
        if seen is not None:
            seen.append((url, (payload or {}).get("variables")))
        if url.endswith("/graphql"):
            page = pages[min(calls["n"], len(pages) - 1)]
            calls["n"] += 1
            return 200, page
        if "/rate_limit" in url:
            return 200, {"resources": {}}
        # Every REST *listing* on the affected repository: 200 and empty.
        return 200, []
    return _fake


def _install(monkeypatch, transport) -> None:
    monkeypatch.setattr(poll_mod, "_load_pat", lambda: "fake-token")
    monkeypatch.setattr(poll_mod, "_api_request", transport)


def test_open_issues_are_found_although_the_rest_listing_answers_empty(
        monkeypatch) -> None:
    """The regression: REST says nothing is open; three issues are."""
    seen: list = []
    _install(monkeypatch, _transport(
        [_graphql_page([_node(1645), _node(1636), _node(1215)])], seen))

    report = poll_mod.poll(repo="vibeic/vibe-ic")

    assert report["total_open"] == 3, (
        "the poll found %r open issues for a repository with 3 — a listing "
        "that answers [] is not a repository with an empty queue "
        "(vibe-ic#1645)" % report["total_open"])
    assert [e["number"] for e in report["actionable"]] == [1645, 1636, 1215]
    assert all(e["actionable"] is True for e in report["actionable"])
    assert any(url.endswith("/graphql") for url, _v in seen), seen


def test_the_exit_code_says_there_is_work(monkeypatch, capsys) -> None:
    """Exit 0 means 'core agent exits this tick'. With work open it must
    be 1, or the whole fleet stands down on a false zero."""
    _install(monkeypatch, _transport([_graphql_page([_node(1645)])]))

    rc = poll_mod.main(["--repo", "vibeic/vibe-ic"])
    out = capsys.readouterr().out

    assert rc == 1, f"an open queue reported 'nothing to do':\n{out}"
    assert "total open: 1" in out, out


def test_a_genuinely_empty_queue_still_exits_zero(monkeypatch, capsys) -> None:
    """The other direction: this must not become 'always report work'."""
    _install(monkeypatch, _transport([_graphql_page([])]))

    rc = poll_mod.main(["--repo", "vibeic/vibe-ic"])
    out = capsys.readouterr().out

    assert rc == 0, out
    assert "(no actionable issues)" in out, out


def test_graphql_errors_are_raised_not_read_as_an_empty_queue(
        monkeypatch) -> None:
    """GitHub rejects a GraphQL query with HTTP 200 + an `errors` array."""
    _install(monkeypatch, _transport(
        [{"data": None, "errors": [{"message": "rate limited"}]}]))

    with pytest.raises(RuntimeError) as exc:
        poll_mod.poll(repo="vibeic/vibe-ic")
    assert "errors" in str(exc.value).lower()


def test_a_null_repository_is_refused(monkeypatch) -> None:
    _install(monkeypatch, _transport([{"data": {"repository": None}}]))

    with pytest.raises(RuntimeError) as exc:
        poll_mod.poll(repo="vibeic/vibe-ic")
    assert "repository" in str(exc.value).lower()


def test_every_page_is_followed(monkeypatch) -> None:
    """A first page is a floor, not a count."""
    seen: list = []
    _install(monkeypatch, _transport([
        _graphql_page([_node(9), _node(8)], has_next=True, cursor="CUR1"),
        _graphql_page([_node(7)]),
    ], seen))

    report = poll_mod.poll(repo="vibeic/vibe-ic")

    assert report["total_open"] == 3, report
    afters = [v.get("after") for _u, v in seen if v is not None]
    assert afters == [None, "CUR1"], afters


def test_another_page_without_a_cursor_is_refused(monkeypatch) -> None:
    """hasNextPage with no cursor cannot be paged; refuse, never truncate."""
    _install(monkeypatch, _transport(
        [_graphql_page([_node(9)], has_next=True, cursor=None)]))

    with pytest.raises(RuntimeError) as exc:
        poll_mod.poll(repo="vibeic/vibe-ic")
    assert "cursor" in str(exc.value).lower()
