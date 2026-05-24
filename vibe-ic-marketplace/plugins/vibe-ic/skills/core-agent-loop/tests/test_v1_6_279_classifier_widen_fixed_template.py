"""tests/test_v1_6_279_classifier_widen_fixed_template.py — v1.6.279

Extends v1.6.276's `_CORE_AGENT_SELF_SIGNATURE_RE` to catch
additional canonical core-agent fix-announcement templates seen
in the wild:

  * `**Fixed — v1.6.278 已 push**（core-agent, commit ...）`
  * `**修復完成 v1.6.277（round-3）**` and the bilingual `**修復完成 vX.Y.Z**`
  * `core-agent` (with hyphen) in addition to `core agent`

Without this widening, the v1.6.276 classifier would still trip
on body text inside these templates that quotes the field-agent's
prior `NOT VERIFIED` verdict in the root-cause narrative — re-
introducing the false-positive that v1.6.276 was supposed to
close.
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
        "updated_at": "2026-05-17T22:50:00Z",
        "html_url": f"https://example/{number}",
    }


def test_v1_6_279_fixed_emdash_version_template_signature_match() -> None:
    """`**Fixed — v1.6.278 已 push**（core-agent, commit …）`
    must be recognised as a core-agent self-template."""
    body = (
        "**Fixed — v1.6.278 已 push**（core-agent, commit `92c16497`）\n\n"
        "## Root cause\n\nfield-agent 提供：v1.6.277 ... NOT VERIFIED ..."
    )
    assert poll_mod._CORE_AGENT_SELF_SIGNATURE_RE.match(body) is not None


def test_v1_6_279_fixed_hyphen_version_template_signature_match() -> None:
    """Same template but with ASCII hyphen `-` instead of em-dash `—`."""
    # was: historical example version string for regex-fixture purposes
    body = (
        "**Fixed - v1.6.270 已 push**（core-agent, commit `abc1234`）\n"
    )
    assert poll_mod._CORE_AGENT_SELF_SIGNATURE_RE.match(body) is not None


def test_v1_6_279_xiufu_wancheng_version_template_match() -> None:
    """`**修復完成 v1.6.277（round-3）**` opener (alternative
    bilingual round-N announcement) matches."""
    body = (
        "**修復完成 v1.6.277（round-3）** — commit `0c848d31`\n\n"
        "## 1. Root cause\n..."
    )
    assert poll_mod._CORE_AGENT_SELF_SIGNATURE_RE.match(body) is not None


def test_v1_6_279_fixed_template_suppresses_override_with_label() -> None:
    """End-to-end: label present + Fixed-template comment with
    quoted NOT VERIFIED in body => actionable False (override
    suppressed)."""
    issue = _make_issue(134, ["wait-for-verification"])
    body = (
        "**Fixed — v1.6.278 已 push**（core-agent, commit `92c16497`）\n\n"
        "## Root-cause（field-agent 提供）\n"
        "v1.6.277 的 prose-only whole-register synthesiser **無法觸發** "
        "real RV-class benchmark 上 24 個空 register... 結果 NOT VERIFIED."
    )
    out = poll_mod._classify(issue, latest_comment_body=body)
    assert out["actionable"] is False
    assert out["feedback_override"] is False


def test_v1_6_279_genuine_field_agent_verdict_still_triggers() -> None:
    """Regression guard: actual field-agent verdict comment that
    does NOT open with any self-template still flips override."""
    issue = _make_issue(134, ["wait-for-verification"])
    body = (
        "**驗證結果：NOT VERIFIED (round-5)** (field-agent v1.6.278 / "
        "commit `92c16497`)\n\nRe-ran phase1 on real benchmark..."
    )
    out = poll_mod._classify(issue, latest_comment_body=body)
    assert out["actionable"] is True
    assert out["feedback_override"] is True


def test_v1_6_279_core_dash_agent_variant_signature_match() -> None:
    """`Core-agent 已推送修復...` (with hyphen) must match the
    pre-existing `Core agent 已推送修復...` recogniser."""
    body = "Core-agent 已推送修復: abc1234\n\n**問題**：..."
    assert poll_mod._CORE_AGENT_SELF_SIGNATURE_RE.match(body) is not None
    # And in the classifier path:
    issue = _make_issue(134, ["wait-for-verification"])
    body_with_marker = body + "\n根因：之前 NOT VERIFIED 提到 ..."
    out = poll_mod._classify(issue, latest_comment_body=body_with_marker)
    assert out["actionable"] is False
