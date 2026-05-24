"""tests/test_v1_6_268_classifier_feedback_override.py — v1.6.268

Closes the shared-login blind spot the field-agent surfaced
during #123/#124/#125 round-2. The poll classifier was strictly
label-based: actionable iff `wait-for-verification` absent. That
fails the race where the field-agent posts counter-evidence
(`NOT VERIFIED`, `Removing wait-for-verification`, `Round-N
verify`) but the label removal step lags or is missed — and the
shared-login case where login-based classifiers cannot tell
core-agent and field-agent apart.

Fix: `_classify` accepts an optional `latest_comment_body` and
flips the issue actionable when canonical feedback markers are
present, even with the label still attached.
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
        "title": "ORGANIC: example",
        "labels": [{"name": l} for l in labels],
        "updated_at": "2026-05-14T01:39:00Z",
        "html_url": f"https://example/{number}",
    }


def test_v1_6_268_label_present_no_body_stays_waiting() -> None:
    """Baseline rule: label present + no comment body → waiting."""
    out = poll_mod._classify(_make_issue(1, ["wait-for-verification"]))
    assert out["actionable"] is False
    assert out["feedback_override"] is False


def test_v1_6_268_label_absent_stays_actionable() -> None:
    """Baseline rule: label absent → actionable."""
    out = poll_mod._classify(_make_issue(2))
    assert out["actionable"] is True
    assert out["feedback_override"] is False


def test_v1_6_268_not_verified_marker_overrides_label() -> None:
    """`NOT VERIFIED` in latest comment flips actionable even
    when the label is still attached."""
    issue = _make_issue(3, ["wait-for-verification"])
    body = ("**Round-2 verify NOT VERIFIED** (plugin v1.6.267 @ "
            "ae6ecad7)\n\nRe-ran phase1; deltas vs round-1: ZERO. "
            "Removing wait-for-verification.")
    out = poll_mod._classify(issue, latest_comment_body=body)
    assert out["actionable"] is True
    assert out["feedback_override"] is True


def test_v1_6_268_round_n_verify_marker_overrides_label() -> None:
    """`Round-N verify` phrasing (canonical field-agent comment
    opener) also overrides the label."""
    issue = _make_issue(4, ["wait-for-verification"])
    body = "Round-3 verify NOT VERIFIED — same SHA same numbers."
    out = poll_mod._classify(issue, latest_comment_body=body)
    assert out["actionable"] is True


def test_v1_6_268_self_acknowledgement_does_not_override() -> None:
    """A core-agent self-comment ('Core agent 已推送修復...')
    must NOT trigger the override — only field-agent's verdict
    markers do."""
    issue = _make_issue(5, ["wait-for-verification"])
    body = ("Core agent 已推送修復：deadbeef\n\n**問題**：…\n"
            "**根因**：…\n**修法**：…\n**本機驗證**：pytest OK")
    out = poll_mod._classify(issue, latest_comment_body=body)
    assert out["actionable"] is False
    assert out["feedback_override"] is False
