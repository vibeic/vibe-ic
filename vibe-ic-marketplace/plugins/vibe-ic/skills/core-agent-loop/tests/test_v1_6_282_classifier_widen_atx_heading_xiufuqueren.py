"""tests/test_v1_6_282_classifier_widen_atx_heading_xiufuqueren.py — v1.6.282

Closes a second-generation false-positive in the v1.6.276/279
classifier self-template suppression. Two real-world core-agent
fix-announcement templates were observed on issues #141 + #143:

  * ``## v1.6.281 修復 — round-N NOT VERIFIED feedback closed``
    (ATX-heading round-N self-acknowledgement form)
  * ``## 修復確認 — v1.6.X 已發佈``
    (ATX-heading initial fix confirmation form)

Both start with `##` ATX-heading markers that the v1.6.279 prefix
`\\s*\\*{0,2}\\s*` does NOT consume, so the body's quoted
`NOT VERIFIED` (often in the title itself) tripped the v1.6.268
feedback override and kept already-fixed issues falsely actionable.

Fix (v1.6.282):
  - Widen the prefix to ``[\\s#*]*`` so any combination of
    leading whitespace, `#`, and `*` markers is stripped.
  - Add ``v\\d+\\.\\d+\\.\\d+\\s+修復(?:摘要|\\s*[—\\-])`` variant
    (the new template doesn't require the literal 摘要 suffix —
    em-dash / hyphen separator after `修復` is enough).
  - Add ``修復確認`` variant for the initial-confirmation form.

Regression guard: genuine field-agent NOT VERIFIED comments still
trigger the override (they open with `## NOT VERIFIED` or
`**NOT VERIFIED**`, neither of which matches any self-template
variant after marker-stripping).
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
        "updated_at": "2026-05-18T00:00:00Z",
        "html_url": f"https://example/{number}",
    }


# ------------------------------------------------------------------
# v1.6.282 — ATX-heading + v<X>.<Y>.<Z> 修復 form
# ------------------------------------------------------------------

def test_v1_6_282_atx_h2_version_xiufu_emdash_round_template_match() -> None:
    """`## v1.6.281 修復 — round-2 NOT VERIFIED feedback closed`
    is a core-agent self-template (round-N self-acknowledgement
    form) and must be recognised."""
    body = (
        "## v1.6.281 修復 — round-2 NOT VERIFIED feedback closed\n\n"
        "### 修復摘要（commit ec34577c）\n"
        "- **根因**：v1.6.280 在每個檔案內部 ATX vs RST 競速..."
    )
    assert poll_mod._CORE_AGENT_SELF_SIGNATURE_RE.match(body) is not None


def test_v1_6_282_atx_h2_version_xiufu_hyphen_round_template_match() -> None:
    """Same template with ASCII hyphen `-` instead of em-dash `—`."""
    body = (
        "## v1.6.270 修復 - round-1 feedback addressed\n\n"
        "Some body text..."
    )
    assert poll_mod._CORE_AGENT_SELF_SIGNATURE_RE.match(body) is not None


def test_v1_6_282_atx_h3_version_xiufu_round_template_match() -> None:
    """ATX H3 (`###`) prefix should also be stripped."""
    body = "### v1.6.281 修復 — initial round\nbody"
    assert poll_mod._CORE_AGENT_SELF_SIGNATURE_RE.match(body) is not None


# ------------------------------------------------------------------
# v1.6.282 — 修復確認 (initial-confirmation) form
# ------------------------------------------------------------------

def test_v1_6_282_atx_h2_xiufuqueren_template_match() -> None:
    """`## 修復確認 — v1.6.280 已發佈` is the canonical initial-
    fix confirmation core-agent self-template."""
    body = (
        "## 修復確認 — v1.6.280 已發佈\n\n"
        "### 1. 問題確認\n"
        "field-agent 於 v1.6.279 回報：..."
    )
    assert poll_mod._CORE_AGENT_SELF_SIGNATURE_RE.match(body) is not None


def test_v1_6_282_bare_xiufuqueren_match() -> None:
    """Bare `修復確認` opener (no markdown markers)."""
    body = "修復確認 — v1.6.270 已發佈\n\nbody"
    assert poll_mod._CORE_AGENT_SELF_SIGNATURE_RE.match(body) is not None


# ------------------------------------------------------------------
# v1.6.282 — end-to-end classifier suppression
# ------------------------------------------------------------------

def test_v1_6_282_e2e_atx_h2_version_xiufu_with_quoted_not_verified() -> None:
    """End-to-end: label present + ATX-h2 `v<X>.<Y>.<Z> 修復` round
    template (whose TITLE quotes `NOT VERIFIED`) must NOT flip
    feedback_override."""
    issue = _make_issue(141, ["wait-for-verification"])
    body = (
        "## v1.6.281 修復 — round-2 NOT VERIFIED feedback closed\n\n"
        "### 修復摘要（commit ec34577c）\n"
        "- **根因**：v1.6.280 在每個檔案內部 ATX vs RST 競速...\n"
        "field-agent 之前回報 NOT VERIFIED ..."
    )
    out = poll_mod._classify(issue, latest_comment_body=body)
    assert out["actionable"] is False, (
        f"core-agent ATX-heading version-修復 template wrongly "
        f"triggered override: {out!r}"
    )
    assert out["feedback_override"] is False


def test_v1_6_282_e2e_atx_h2_xiufuqueren_with_quoted_not_verified() -> None:
    """End-to-end: label present + `## 修復確認 — v1.6.X 已發佈`
    template (whose body quotes prior NOT VERIFIED context) must
    NOT flip feedback_override."""
    issue = _make_issue(143, ["wait-for-verification"])
    body = (
        "## 修復確認 — v1.6.280 已發佈\n\n"
        "### 1. 問題確認\n"
        "field-agent 於 v1.6.279 回報 NOT VERIFIED：`gen_l1_datasheet` "
        "內無任何 extractor 走 README 的 `## Features`..."
    )
    out = poll_mod._classify(issue, latest_comment_body=body)
    assert out["actionable"] is False
    assert out["feedback_override"] is False


# ------------------------------------------------------------------
# v1.6.282 — regression guards: field-agent verdicts MUST still
# flip override
# ------------------------------------------------------------------

def test_v1_6_282_field_agent_atx_not_verified_still_triggers() -> None:
    """`## NOT VERIFIED — v1.6.280 (commit fde852f8)` is a
    field-agent verdict (ATX H2) and must NOT match any
    self-template variant after prefix-stripping. Override MUST
    flip."""
    issue = _make_issue(141, ["wait-for-verification"])
    body = (
        "## NOT VERIFIED — v1.6.280 (commit `fde852f8`)\n\n"
        "### 驗證結論\n"
        "真實 benchmark 4 顆 RST-source chip 全數呈現「非空 description」..."
    )
    out = poll_mod._classify(issue, latest_comment_body=body)
    assert out["actionable"] is True, (
        "field-agent ATX-h2 NOT VERIFIED verdict must still flip "
        "override"
    )
    assert out["feedback_override"] is True


def test_v1_6_282_field_agent_bold_not_verified_still_triggers() -> None:
    """`**NOT VERIFIED** — v1.6.280 (`fde852f8`)` is the bold form
    of the verdict; must still flip override."""
    issue = _make_issue(143, ["wait-for-verification"])
    body = (
        "**NOT VERIFIED** — v1.6.280 (`fde852f8`)\n\n"
        "### 單元測試\n所有 6 個 #143 測試通過..."
    )
    out = poll_mod._classify(issue, latest_comment_body=body)
    assert out["actionable"] is True
    assert out["feedback_override"] is True


def test_v1_6_282_negative_cases_regex_unit() -> None:
    """Direct check: field-agent verdict shapes do NOT match the
    widened regex."""
    neg_cases = (
        "## NOT VERIFIED — v1.6.280",
        "## NOT VERIFIED (round-5)",
        "**NOT VERIFIED** — v1.6.280",
        "## 驗證結果：NOT VERIFIED",
        "Round-2 verify NOT VERIFIED at v1.6.267",
        "Re-ran phase1; deltas: ZERO",
        "## 重新驗證 — round-3",
        "",
    )
    for body in neg_cases:
        assert poll_mod._CORE_AGENT_SELF_SIGNATURE_RE.match(body) is None, (
            f"v1.6.282 widened regex wrongly matched field-agent "
            f"verdict shape: {body!r}"
        )


def test_v1_6_282_positive_cases_regex_unit() -> None:
    """Direct check: all v1.6.282-supported new self-template
    shapes match (plus regression for v1.6.276/279 shapes)."""
    pos_cases = (
        # v1.6.282 — new ATX-heading shapes
        "## v1.6.281 修復 — round-2 NOT VERIFIED feedback closed",
        "### v1.6.270 修復 - round-1 fixed",
        "## 修復確認 — v1.6.280 已發佈",
        "修復確認 — v1.6.270",
        # v1.6.279 regression
        "**Fixed — v1.6.278 已 push**（core-agent, commit `92c16497`）",
        "**修復完成 v1.6.277（round-3）** — commit `0c848d31`",
        "Core-agent 已推送修復: abc1234",
        # v1.6.276 regression
        "Core agent 已推送修復：abc1234",
        "core agent 已推送修復：abc1234",  # lowercase
        "Core agent 已推送 round-3 修復：abc1234",
        "**v1.6.270 修復摘要（#123 round-3 — field-agent NOT VERIFIED）**",
        "v1.6.275 修復摘要",
        "  **Core agent 已推送...**",  # leading whitespace
    )
    for body in pos_cases:
        assert poll_mod._CORE_AGENT_SELF_SIGNATURE_RE.match(body), (
            f"v1.6.282 widened regex failed to match self-template "
            f"shape: {body!r}"
        )


def test_v1_6_282_label_absent_still_actionable() -> None:
    """Baseline rule unchanged: label absent → actionable,
    regardless of comment shape."""
    issue = _make_issue(200, [])
    out = poll_mod._classify(
        issue,
        latest_comment_body="## v1.6.281 修復 — round-2 feedback closed",
    )
    assert out["actionable"] is True
