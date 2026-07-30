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
            "nodes": [{"number": i * 100 + k, "title": f"t{i}-{k}"}
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


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
