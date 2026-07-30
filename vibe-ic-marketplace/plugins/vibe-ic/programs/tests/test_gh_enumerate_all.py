#!/usr/bin/env python3
"""vibe-ic — the capped listing that reads as a complete one.

Six times on 2026-07-30 a conclusion was published from a listing the asker had
capped, and each capped result was byte-indistinguishable from a complete one.
The most expensive: `issues?state=all&labels=bug&per_page=100` returned 70
issues from a tracker holding 2303, and "no upstream issue names this crash" was
posted from it.

`org_open_work_poll` already refuses this shape for one org. These pin the
generalised version, and every test here is about a REFUSAL, because the passing
case was never the problem — a partial answer that looks whole is.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import gh_enumerate_all as G  # noqa: E402


def _pages(*specs, fail_on=None):
    """A `_gh_graphql` returning one page per spec: (n_nodes, has_next, total)."""
    state = {"i": 0}

    def fake(query, timeout=120):
        i = state["i"]
        state["i"] += 1
        if fail_on is not None and i == fail_on:
            return None, "HTTP 502"
        n, has_next, total = specs[i]
        return {"data": {"repository": {"issues": {
            "totalCount": total,
            "pageInfo": {"hasNextPage": has_next, "endCursor": f"c{i}"},
            "nodes": [{"number": i * 100 + k, "title": f"t{i}-{k}",
                       "body": f"body-{i}-{k}"}
                      for k in range(n)]}}}}, ""
    return fake


def test_every_page_is_followed(monkeypatch):
    """THE defect. One page of 100 out of 2303 read as the collection."""
    monkeypatch.setattr(G, "_gh_graphql",
                        _pages((100, True, 250), (100, True, 250), (50, False, 250)))
    res = G.enumerate_all("o", "r", "issues")
    assert res.get("count") == 250, f"stopped early: {res}"


def test_a_failed_page_is_not_the_end(monkeypatch):
    """Half a listing is not a listing. Returning what was collected so far is
    the exact shape this program exists to refuse."""
    monkeypatch.setattr(G, "_gh_graphql",
                        _pages((100, True, 250), (100, True, 250), fail_on=1))
    res = G.enumerate_all("o", "r", "issues")
    assert "error" in res and "page 2 failed" in res["error"]


def test_the_page_cap_is_an_error_not_a_result(monkeypatch):
    """Reaching the cap with more to come means the answer is unknown. A prefix
    returned as a collection is how every one of the six failures happened."""
    monkeypatch.setattr(G, "_gh_graphql", _pages(*[(100, True, 9999)] * 3))
    res = G.enumerate_all("o", "r", "issues", max_pages=3)
    assert "error" in res and "prefix is not a collection" in res["error"]


def test_a_count_disagreeing_with_the_declared_total_is_refused(monkeypatch):
    """Two sources disagreeing proves one is wrong, which is actionable where a
    lone number is not. Pagination saying 150 while the connection declares 250
    means something was dropped."""
    monkeypatch.setattr(G, "_gh_graphql",
                        _pages((100, True, 250), (50, False, 250)))
    res = G.enumerate_all("o", "r", "issues")
    assert "error" in res and "declares 250" in res["error"]


def test_an_unknown_collection_is_named(monkeypatch):
    assert "error" in G.enumerate_all("o", "r", "not_a_thing")


def test_gh_missing_is_not_an_empty_collection(monkeypatch):
    monkeypatch.setattr(G, "_gh_graphql", lambda q, timeout=120: (None, "gh is not installed"))
    res = G.enumerate_all("o", "r", "issues")
    assert "error" in res and "gh is not installed" in res["error"]


def test_the_refusal_puts_nothing_on_stdout(monkeypatch, capsys):
    """`N=$(prog) || exit 1` only fires if the failure is silent on stdout."""
    monkeypatch.setattr(G, "_gh_graphql", _pages((100, True, 9999)) )
    rc = G.main(["o/r", "issues", "--max-pages", "1"])
    out = capsys.readouterr()
    assert rc == G.RC_INCOMPLETE
    assert out.out == "", "a refusal printed a number anyway"
    assert "NOT an empty collection" in out.err


def test_grep_filters_but_the_denominator_stays_whole(monkeypatch, capsys):
    """The filter is applied AFTER complete enumeration. Filtering during it —
    `labels=bug` — is what produced 70 of 2303."""
    monkeypatch.setattr(G, "_gh_graphql", _pages((3, False, 3)))
    rc = G.main(["o/r", "issues", "--grep", "t0-1"])
    err = capsys.readouterr().err
    assert rc == G.RC_OK
    assert "3 issues enumerated" in err and "1 match" in err
    assert "denominator is the whole collection" in err


def test_a_complete_run_reports_both_numbers(monkeypatch, capsys):
    """…or every refusal above is satisfied by a program that never succeeds."""
    monkeypatch.setattr(G, "_gh_graphql", _pages((7, False, 7)))
    assert G.main(["o/r", "issues"]) == G.RC_OK
    assert "7 issues" in capsys.readouterr().err


# --------------------------------------------------------------------------
# the search scope — a title search reported as a tracker search
# --------------------------------------------------------------------------

def _one_page(nodes):
    def fake(query, timeout=120):
        return {"data": {"repository": {"issues": {
            "totalCount": len(nodes),
            "pageInfo": {"hasNextPage": False, "endCursor": "c"},
            "nodes": nodes}}}}, ""
    return fake


_MIXED = [
    {"number": 1, "title": "Data races in drt module",
     "body": "ThreadSanitizer detects races in drt::FlexPA and drt::FlexTA"},
    {"number": 2, "title": "unrelated", "body": "nothing here"},
]


def test_grep_searches_the_body_too(monkeypatch, capsys):
    """THE defect this half exists for. Asking the real tracker for `FlexPA`
    with a title-only search returned "2303 enumerated; 0 match" — which reads
    as proof and is a statement about 2303 TITLES. With bodies: 3 match, one of
    them a ThreadSanitizer race in `drt::FlexPA` on the same design this
    project's crash uses (vibe-ic#551).
    """
    monkeypatch.setattr(G, "_gh_graphql", _one_page(_MIXED))
    rc = G.main(["o/r", "issues", "--grep", "FlexPA"])
    err = capsys.readouterr().err
    assert rc == G.RC_OK
    assert "1 match" in err, "a body-only hit was missed"


def test_the_verdict_states_which_fields_were_searched(monkeypatch, capsys):
    """A zero is only as trustworthy as its scope, so the scope is in the line
    that carries the number — not in the help text nobody re-reads."""
    monkeypatch.setattr(G, "_gh_graphql", _one_page(_MIXED))
    G.main(["o/r", "issues", "--grep", "FlexPA"])
    assert "in title and body" in capsys.readouterr().err


def test_titles_only_is_available_and_says_so(monkeypatch, capsys):
    """Restricting the scope is legitimate; hiding that you did is not."""
    monkeypatch.setattr(G, "_gh_graphql", _one_page(_MIXED))
    G.main(["o/r", "issues", "--grep", "FlexPA", "--titles-only"])
    err = capsys.readouterr().err
    assert "0 match" in err and "in titles only" in err


def test_a_node_with_no_body_does_not_break_the_filter(monkeypatch):
    """`refs` carry `name` and no body at all."""
    monkeypatch.setattr(G, "_gh_graphql",
                        _one_page([{"number": 9, "title": "has FlexPA"}]))
    assert G.main(["o/r", "issues", "--grep", "flexpa"]) == G.RC_OK


def test_the_query_actually_requests_the_body(monkeypatch):
    """The stub supplies bodies, so every test above passes even if the GraphQL
    query never asks for one — and against the real API that yields nodes with
    no `body` key and a filter that silently degrades to titles.

    Mutation-checked: dropping `body` from COLLECTIONS left the whole suite
    green until this test existed.
    """
    seen = {}

    def spy(query, timeout=120):
        seen["q"] = query
        return {"data": {"repository": {"issues": {
            "totalCount": 0, "pageInfo": {"hasNextPage": False, "endCursor": "c"},
            "nodes": []}}}}, ""

    monkeypatch.setattr(G, "_gh_graphql", spy)
    G.enumerate_all("o", "r", "issues")
    assert "body" in seen.get("q", ""), \
        "the query does not request body; --grep would search titles only"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
