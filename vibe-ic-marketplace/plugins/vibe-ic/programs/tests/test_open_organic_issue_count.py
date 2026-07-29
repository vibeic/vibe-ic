#!/usr/bin/env python3
"""vibe-ic#554 — a broken query and a finished job must not produce the same number.

The Phase-1 loop's STOP clause (2) is "zero open ORGANIC-phase1 issues", counted
via `gh issue list --search`. That routes through GitHub's search index, which
returns 0 for this repository regardless of content. Positive control, measured
on the live repo:

    --search "Actions in:title" --state open   ->  0    (#550 IS open, and has
                                                         "Actions" in its title)
    list + filter locally                      ->  1

N=0 satisfies the clause, so the loop concludes there is nothing left to do.
Same class as #550 itself — an empty listing standing in for a clean result —
one layer up.
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import open_organic_issue_count as C                          # noqa: E402


def _gh(monkeypatch, rc, out, err=""):
    monkeypatch.setattr(C, "_gh", lambda *a, **k: (rc, out, err))


def test_a_title_match_is_found_without_the_search_index(monkeypatch):
    _gh(monkeypatch, 0, json.dumps([
        {"number": 550, "title": "Account-level: Actions disabled"},
        {"number": 551, "title": "Three ordered OpenROAD faults"}]))
    r = C.count("Actions")
    assert r["count"] == 1 and r["numbers"] == [550]


def test_a_real_zero_is_a_zero(monkeypatch):
    _gh(monkeypatch, 0, json.dumps([{"number": 1, "title": "something else"}]))
    r = C.count("ORGANIC-phase1")
    assert r["count"] == 0 and "error" not in r


def test_a_failed_listing_is_never_zero(monkeypatch):
    """The whole defect. A caller passing 0 on a failed measurement satisfies
    the STOP clause, and the loop reports the work as finished."""
    _gh(monkeypatch, 1, "", "GraphQL: Could not resolve to a Repository")
    r = C.count("ORGANIC-phase1")
    assert "error" in r and "count" not in r


def test_unparsable_output_is_not_zero_either(monkeypatch):
    _gh(monkeypatch, 0, "not json at all")
    r = C.count("ORGANIC-phase1")
    assert "error" in r and "count" not in r


def test_a_listing_at_the_cap_refuses_rather_than_under_counting(monkeypatch):
    """`gh issue list` defaults to 30. Past the cap the extras read as absent —
    truncation standing in for absence, a third instance of the same shape."""
    _gh(monkeypatch, 0, json.dumps(
        [{"number": n, "title": "x"} for n in range(5)]))
    r = C.count("x", limit=5)
    assert "error" in r and "floor" in r["error"]


def test_the_exit_code_separates_zero_from_uncountable(monkeypatch, capsys):
    """rc 0 with a number on stdout, or rc 2 and NOTHING a shell would read as
    a count — `N=$(...)` must come back empty so `|| exit 1` fires."""
    _gh(monkeypatch, 0, json.dumps([{"number": 1, "title": "no match here"}]))
    assert C.main(["ORGANIC-phase1"]) == 0
    assert capsys.readouterr().out.strip() == "0"

    _gh(monkeypatch, 1, "", "boom")
    assert C.main(["ORGANIC-phase1"]) == 2
    assert capsys.readouterr().out.strip() == "", \
        "something reached stdout on a failed count; a shell would capture it"
