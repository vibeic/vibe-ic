"""tests/test_v1_6_292_classifier_widen_xiufu_baogao.py — v1.6.292

Closes a v1.6.291 worktree-agent self-template variant that v1.6.282's
classifier widening missed: `## v1.6.291 修復報告（#161 round-2）`. The
`修復報告` (fix-report) template form is used by worktree agents for
detailed round-N fix narratives. v1.6.282 only knew about `修復摘要`
(fix-summary), `修復確認` (fix-confirmation), and `修復` + em-dash
continuation — `修復報告` fell through and the body's `NOT VERIFIED`
quote (from the round-2 承接 narrative) tripped the feedback override.

Fix (v1.6.292):
  * Added `修復報告` as a top-level alternative (mirrors `修復確認` /
    `修復摘要`).
  * Extended `v\\d+\\.\\d+\\.\\d+\\s+修復(?:摘要|報告|\\s*[—\\-（(])`
    continuation set with `報告` and the full-width `（` and ASCII
    `(` paren chars (matches `v1.6.291 修復報告（` and
    `v1.6.291 修復報告(`).

Regression guards preserved: field-agent NOT VERIFIED verdicts do not
match the widened regex.

Chip-AGNOSTIC.
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
        "updated_at": "2026-05-18T05:00:00Z",
        "html_url": f"https://example/{number}",
    }


# ------------------------------------------------------------------
# v1.6.292 — 修復報告 template variants
# ------------------------------------------------------------------

def test_v1_6_292_atx_h2_version_xiufu_baogao_round_template_match() -> None:
    """`## v1.6.291 修復報告（#161 round-2）` — the round-N
    detailed-report template emitted by v1.6.291 worktree agent."""
    body = (
        "## v1.6.291 修復報告（#161 round-2）\n\n"
        "**承接：** v1.6.289 / v1.6.290 NOT VERIFIED — 原本的 ..."
    )
    assert poll_mod._CORE_AGENT_SELF_SIGNATURE_RE.match(body) is not None


def test_v1_6_292_atx_h2_version_xiufu_baogao_no_paren_match() -> None:
    """`## v1.6.291 修復報告` (no following paren)."""
    body = "## v1.6.291 修復報告\n\nbody"
    assert poll_mod._CORE_AGENT_SELF_SIGNATURE_RE.match(body) is not None


def test_v1_6_292_bare_xiufu_baogao_match() -> None:
    """Bare `修復報告` opener (no markdown markers)."""
    body = "修復報告 — v1.6.270\n\nbody"
    assert poll_mod._CORE_AGENT_SELF_SIGNATURE_RE.match(body) is not None


def test_v1_6_292_ascii_paren_continuation_match() -> None:
    """`## v1.6.291 修復報告(#161)` with ASCII paren."""
    body = "## v1.6.291 修復報告(#161 round-2)\n\nbody"
    assert poll_mod._CORE_AGENT_SELF_SIGNATURE_RE.match(body) is not None


# ------------------------------------------------------------------
# v1.6.292 — end-to-end classifier suppression
# ------------------------------------------------------------------

def test_v1_6_292_e2e_xiufu_baogao_with_quoted_not_verified() -> None:
    """End-to-end: label present + `## vX.Y.Z 修復報告（#N round-2）`
    template whose 承接 narrative quotes NOT VERIFIED — must NOT
    flip feedback_override."""
    issue = _make_issue(161, ["wait-for-verification"])
    body = (
        "## v1.6.291 修復報告（#161 round-2）\n\n"
        "**承接：** v1.6.289 / v1.6.290 NOT VERIFIED — 原本的 "
        "`_extract_platform_perf_table` 只能解析 Markdown pipe-table..."
    )
    out = poll_mod._classify(issue, latest_comment_body=body)
    assert out["actionable"] is False, (
        f"v1.6.292 修復報告 self-template wrongly triggered override: "
        f"{out!r}"
    )
    assert out["feedback_override"] is False


# ------------------------------------------------------------------
# v1.6.292 — regression guards: field-agent verdicts MUST still flip
# ------------------------------------------------------------------

def test_v1_6_292_field_agent_not_verified_still_triggers() -> None:
    """`## NOT VERIFIED at v1.6.291` field-agent verdict MUST still
    trigger override."""
    issue = _make_issue(161, ["wait-for-verification"])
    body = (
        "## NOT VERIFIED at v1.6.291\n\n"
        "`fpga_platform_entries=0` across all 8 chips..."
    )
    out = poll_mod._classify(issue, latest_comment_body=body)
    assert out["actionable"] is True, (
        "field-agent NOT VERIFIED must still flip override"
    )
    assert out["feedback_override"] is True


def test_v1_6_292_field_agent_bold_not_verified_still_triggers() -> None:
    """`**NOT VERIFIED at v1.6.291**` bold-form field-agent verdict."""
    issue = _make_issue(161, ["wait-for-verification"])
    body = "**NOT VERIFIED at v1.6.291**\n\nbenchmark fail"
    out = poll_mod._classify(issue, latest_comment_body=body)
    assert out["actionable"] is True
    assert out["feedback_override"] is True


# ------------------------------------------------------------------
# v1.6.292 — direct regex assertions
# ------------------------------------------------------------------

def test_v1_6_292_positive_cases_regex_unit() -> None:
    """All v1.6.292-supported new self-template shapes match + all
    prior v1.6.276/279/282 shapes still match."""
    pos_cases = (
        # v1.6.292 — new 修復報告 shapes
        "## v1.6.291 修復報告（#161 round-2）",
        "## v1.6.291 修復報告(#161 round-2)",
        "### v1.6.291 修復報告",
        "修復報告 — v1.6.270",
        "**修復報告**",
        # v1.6.282 regression
        "## v1.6.281 修復 — round-2 NOT VERIFIED feedback closed",
        "## 修復確認 — v1.6.280 已發佈",
        # v1.6.279 regression
        "**Fixed — v1.6.278 已 push**（core-agent, commit `92c16497`）",
        "**修復完成 v1.6.277（round-3）**",
        # v1.6.276 regression
        "Core agent 已推送修復：abc1234",
        "**v1.6.270 修復摘要（#123 round-3 — field-agent NOT VERIFIED）**",
    )
    for body in pos_cases:
        assert poll_mod._CORE_AGENT_SELF_SIGNATURE_RE.match(body), (
            f"v1.6.292 widened regex failed to match self-template "
            f"shape: {body!r}"
        )


def test_v1_6_292_negative_cases_regex_unit() -> None:
    """Field-agent verdict shapes still do NOT match."""
    neg_cases = (
        "## NOT VERIFIED at v1.6.291",
        "**NOT VERIFIED at v1.6.291**",
        "## NOT VERIFIED — v1.6.280",
        "## 驗證結果：NOT VERIFIED",
        "Round-2 verify NOT VERIFIED at v1.6.267",
        "## 重新驗證 — round-3",
        "",
    )
    for body in neg_cases:
        assert poll_mod._CORE_AGENT_SELF_SIGNATURE_RE.match(body) is None, (
            f"v1.6.292 widened regex wrongly matched field-agent "
            f"verdict shape: {body!r}"
        )
