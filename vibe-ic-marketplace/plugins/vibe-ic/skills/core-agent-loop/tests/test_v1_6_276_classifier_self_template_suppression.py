"""tests/test_v1_6_276_classifier_self_template_suppression.py — v1.6.276

Closes the v1.6.268 classifier false-positive surfaced by #134
round-2: the core-agent's own 繁體中文 fix-summary template
routinely QUOTES the field-agent's prior `NOT VERIFIED` marker
(e.g. `**v1.6.274 修復摘要（#134 round-2 — field-agent NOT
VERIFIED 補強）**`) in its root-cause / round-N narrative. The
v1.6.268 feedback-override then tripped on the quoted marker
and kept the labelled issue falsely actionable every tick.

Fix: when the latest comment opens with the core-agent
self-signature (matched by `_CORE_AGENT_SELF_SIGNATURE_RE`),
SUPPRESS the feedback-override. The label state alone governs
actionability in that case.
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
        "updated_at": "2026-05-17T22:00:00Z",
        "html_url": f"https://example/{number}",
    }


def test_v1_6_276_core_agent_template_with_quoted_not_verified_no_override() -> None:
    """The canonical 繁體中文 round-N fix-summary template,
    even when it QUOTES `field-agent NOT VERIFIED` in the title /
    root-cause narrative, MUST NOT trigger the feedback override
    when the label is already present."""
    issue = _make_issue(134, ["wait-for-verification"])
    body = (
        "**v1.6.274 修復摘要（#134 round-2 — field-agent NOT "
        "VERIFIED 補強）**\n\n"
        "感謝 field-agent 的 round-1 verification + 反向證據。\n"
        "...\n"
        "請 field agent 在實機 benchmark 驗證..."
    )
    out = poll_mod._classify(issue, latest_comment_body=body)
    assert out["actionable"] is False, (
        f"core-agent self-template wrongly triggered override: "
        f"{out!r}"
    )
    assert out["feedback_override"] is False


def test_v1_6_276_canonical_5section_template_quoted_marker_no_override() -> None:
    """`Core agent 已推送修復: <sha>` 5-section template that
    quotes `NOT VERIFIED` in its 根因 narrative must also be
    suppressed."""
    issue = _make_issue(140, ["wait-for-verification"])
    body = (
        "Core agent 已推送修復：abc1234\n\n"
        "**問題**：field agent 之前回報 NOT VERIFIED ...\n"
        "**根因**：...\n"
        "**修法**：...\n"
        "**本機驗證**：pytest OK\n\n"
        "請 field agent 在實機 benchmark 驗證..."
    )
    out = poll_mod._classify(issue, latest_comment_body=body)
    assert out["actionable"] is False
    assert out["feedback_override"] is False


def test_v1_6_276_round_n_self_acknowledgement_no_override() -> None:
    """Round-N self-acknowledgement form (`Core agent 已推送 round-N`)
    also suppressed."""
    issue = _make_issue(123, ["wait-for-verification"])
    body = (
        "Core agent 已推送 round-3 修復：abc1234 (v1.6.270)\n\n"
        "**問題**：round-2 NOT VERIFIED feedback 提到 ..."
    )
    out = poll_mod._classify(issue, latest_comment_body=body)
    assert out["actionable"] is False


def test_v1_6_276_genuine_field_agent_not_verified_still_triggers() -> None:
    """Regression guard: a genuine field-agent NOT VERIFIED
    comment (does NOT start with the core-agent self-template
    signature) MUST still trigger the feedback override."""
    issue = _make_issue(123, ["wait-for-verification"])
    body = (
        "**Round-2 verify NOT VERIFIED** (plugin v1.6.267 @ "
        "ae6ecad7)\n\nRe-ran phase1; deltas vs round-1: ZERO."
    )
    out = poll_mod._classify(issue, latest_comment_body=body)
    assert out["actionable"] is True, (
        "genuine field-agent NOT VERIFIED must still flip override"
    )
    assert out["feedback_override"] is True


def test_v1_6_276_signature_regex_unit() -> None:
    """Direct check of the prefix regex against known shapes."""
    pos_cases = (
        "Core agent 已推送修復：abc1234",
        "core agent 已推送修復：abc1234",  # case-insensitive
        "Core agent 已推送 round-3 修復：abc1234",
        "**v1.6.270 修復摘要（#123 round-3 — field-agent NOT VERIFIED）**",
        "v1.6.275 修復摘要",
        "  **Core agent 已推送...**",  # leading whitespace
    )
    neg_cases = (
        "Round-3 verify NOT VERIFIED at v1.6.267",  # field-agent verdict
        "## 1. 根因確認",                              # bare prose
        "Re-ran phase1; deltas: ZERO",
        "",
    )
    for body in pos_cases:
        assert poll_mod._CORE_AGENT_SELF_SIGNATURE_RE.match(body), (
            f"positive case failed to match: {body!r}"
        )
    for body in neg_cases:
        assert poll_mod._CORE_AGENT_SELF_SIGNATURE_RE.match(body) is None, (
            f"negative case wrongly matched: {body!r}"
        )


def test_v1_6_276_label_absent_still_actionable() -> None:
    """Baseline rule: label absent → actionable, regardless of
    comment shape."""
    issue = _make_issue(200, [])
    out = poll_mod._classify(
        issue,
        latest_comment_body="Core agent 已推送修復：deadbeef",
    )
    assert out["actionable"] is True
