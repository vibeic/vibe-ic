"""tests/test_poll_actionable_is_open.py — new state-machine poll rule.

Pins the simplified poll predicate:

    ACTIONABLE = ANY open non-PR issue (new OR reopened).

The wait-for-verification classifier (label gating + comment
feedback override + core-agent self-template suppression) is RETIRED.
There is no longer any path by which an open issue becomes
"waiting" — CLOSED is the terminal state, applied by the core-agent
after self-verify. A reopened issue is just an open issue again, so
the same predicate makes it actionable with no special-casing.

This test injects a synthetic 2-open-issue input through the
program's only two seams — `_list_open_issues` and `_load_pat` — so
`poll()` runs without touching the network, and asserts the report
shape: both issues actionable, `waiting` empty, `waiting_count == 0`.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_HERE = Path(__file__).resolve()
_POLL_PATH = _HERE.parents[1] / "programs" / "poll.py"
_spec = importlib.util.spec_from_file_location("poll_mod", _POLL_PATH)
poll_mod = importlib.util.module_from_spec(_spec)  # type: ignore
_spec.loader.exec_module(poll_mod)  # type: ignore


def _make_issue(number: int, labels=()):
    return {
        "number": number,
        "title": f"ORGANIC: example #{number}",
        "labels": [{"name": l} for l in labels],
        "updated_at": "2026-06-01T00:00:00Z",
        "html_url": f"https://example/{number}",
    }


def test_two_open_issues_both_actionable_waiting_empty(monkeypatch):
    """Two open non-PR issues → both actionable, waiting empty."""
    issues = [_make_issue(2), _make_issue(1)]
    monkeypatch.setattr(poll_mod, "_load_pat", lambda: "fake-token")
    monkeypatch.setattr(poll_mod, "_list_open_issues",
                        lambda repo, token: issues)

    report = poll_mod.poll(repo="owner/name")

    assert report["repo"] == "owner/name"
    assert report["total_open"] == 2
    assert report["actionable_count"] == 2
    assert report["waiting_count"] == 0
    assert report["waiting"] == []
    nums = sorted(c["number"] for c in report["actionable"])
    assert nums == [1, 2]
    assert all(c["actionable"] is True for c in report["actionable"])


def test_reopened_issue_is_actionable_regardless_of_labels(monkeypatch):
    """A reopened issue (carrying a stale `core-closed` label) is just
    an open issue again — still actionable. No label gating."""
    issues = [_make_issue(7, labels=["core-closed"])]
    monkeypatch.setattr(poll_mod, "_load_pat", lambda: "fake-token")
    monkeypatch.setattr(poll_mod, "_list_open_issues",
                        lambda repo, token: issues)

    report = poll_mod.poll(repo="owner/name")

    assert report["actionable_count"] == 1
    assert report["waiting_count"] == 0
    entry = report["actionable"][0]
    assert entry["number"] == 7
    assert entry["actionable"] is True


def test_no_open_issues_is_empty_report(monkeypatch):
    """Healthy idle state: zero open issues → zero actionable."""
    monkeypatch.setattr(poll_mod, "_load_pat", lambda: "fake-token")
    monkeypatch.setattr(poll_mod, "_list_open_issues",
                        lambda repo, token: [])

    report = poll_mod.poll(repo="owner/name")

    assert report["total_open"] == 0
    assert report["actionable_count"] == 0
    assert report["waiting_count"] == 0
    assert report["actionable"] == []
    assert report["waiting"] == []
