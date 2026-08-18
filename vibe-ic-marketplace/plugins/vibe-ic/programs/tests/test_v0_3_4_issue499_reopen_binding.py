#!/usr/bin/env python3
"""test_v0_3_4_issue499_reopen_binding.py — issue #499 (HIGH) regression.

ISSUE #499 — reopened issues escape the deterministic close gate. The gate
only read the ORIGINAL issue body's ## 驗收, so a round-2+ close could pass
while the LATEST REOPEN COMMENT's fenced repro still exits 1 (one issue was
closed twice in exactly this state). The latest reopen comment's fenced
commands must become the BINDING acceptance for round-2+ closes.

FIX under test (programs/acceptance_evidence_in_fix_comment_check.py):
  (a) NEW offline input --reopen-comment-file (network mode: fetch comments
      + select the LATEST reopen/counter-evidence comment via the documented
      shape — contains 'REOPEN'/'複查'/'反證'/... + a fenced code block);
  (b) when a reopen comment exists, its fenced commands are UNIONED with
      (and take precedence over) the body acceptance — the fix comment must
      quote THOSE commands + end-state, else exit 1 naming them;
  (c) no reopen comment → behavior unchanged; narrative-only reopen comment
      → ACCEPTANCE_NARRATIVE_ONLY path as today (falls back to body).

ACCEPTANCE DOCTRINE
-------------------
The issue's own ## 驗收 (replay the failure class):
  an issue body + a round-2 reopen comment with a fenced repro + a fix
  comment that quotes only the ORIGINAL acceptance → exit 1 naming the
  reopen commands; a fix comment quoting the reopen repro + end-state →
  exit 0; no-reopen case unchanged (round-1 tests green).

Each headline replay below INVOKES the real CLI via subprocess and asserts
its exit code (verdict) — the END STATE — not just unit internals. All
fixtures are synthetic + chip-AGNOSTIC (structural / process vocabulary
only).
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

# Plugin layout: this file is at programs/tests/, program at parent.
_PROGRAMS = Path(__file__).resolve().parents[1]
_PROG = _PROGRAMS / "acceptance_evidence_in_fix_comment_check.py"
sys.path.insert(0, str(_PROGRAMS))
import acceptance_evidence_in_fix_comment_check as ACC  # noqa: E402


# --------------------------------------------------------------------------
# Synthetic, chip-AGNOSTIC fixtures
# --------------------------------------------------------------------------
# Original body acceptance — the round-1 binding command.
_ISSUE_BODY = textwrap.dedent(
    """\
    ## 現象（synthetic capture）
    A round-1 close passed on a synthetic-fixture test only.

    ## 根因
    The original body acceptance command was the only binding gate.

    ## 驗收
    ```
    python3 programs/round1_gate.py --stage stage/out
    ```
    → Step 4 = PASS
    """
)

# A round-2 REOPEN comment: a reopen marker in prose + a fenced repro that
# is DIFFERENT from the body acceptance (the clean-room repro the field
# agent ran), ending in its end-state output (exit 1).
_REOPEN_COMMENT = textwrap.dedent(
    """\
    複查（field-verify round-2）：reopening — counter-evidence below.

    clean-room repro on the real artifact through the installed cache:
    ```
    python3 programs/round2_repro.py --doc real/input --strict
    Step 7 = FAIL
    exit 1
    ```
    The round-1 fix's synthetic suite is green but THIS repro still fails.
    """
)

# A narrative-only reopen comment: a reopen marker, a fenced block, but the
# fenced block carries no command (only prose/output) → no binding command.
_REOPEN_COMMENT_NARRATIVE = textwrap.dedent(
    """\
    REOPEN: 複查發現修法未覆蓋真實 axis。counter-evidence：
    ```
    the extractor still returns an empty row set
    nothing in the output resolves to the named header
    ```
    No fenced command was pasted — see body acceptance for the gate.
    """
)

# A comment that is NOT a reopen comment (no marker) but has a fence — must
# NOT be selected as a reopen comment.
_PLAIN_COMMENT_WITH_FENCE = textwrap.dedent(
    """\
    For reference, the relevant config block is:
    ```
    python3 programs/unrelated.py --note
    ```
    Just an FYI follow-up, nothing actionable here.
    """
)

# A reopen comment with a marker but NO fence — not a reopen comment per the
# documented rule (needs BOTH marker AND fenced block).
_REOPEN_MARKER_NO_FENCE = (
    "REOPEN: 複查發現問題仍在，但我沒有貼 repro。請補。\n"
)

# Fix comment that quotes ONLY the original body acceptance (the #499 bug:
# round-2 close green while the reopen repro is untouched).
_FIX_QUOTES_ORIGINAL_ONLY = textwrap.dedent(
    """\
    Core agent 已推送修復：abc1234

    **問題**：x
    **根因**：y
    **修法**：z

    **本機驗證**：
    執行 issue 的 ## 驗收 端到端指令：
    ```
    python3 programs/round1_gate.py --stage stage/out
    Step 4 = PASS
    exit 0
    ```
    """
)

# Fix comment that quotes the REOPEN repro command + its end-state.
_FIX_QUOTES_REOPEN = textwrap.dedent(
    """\
    Core agent 已推送修復：def5678

    **問題**：x
    **根因**：y
    **修法**：z

    **本機驗證**：
    重跑 reopen 複查的 clean-room repro：
    ```
    python3 programs/round2_repro.py --doc real/input --strict
    Step 7 = PASS
    exit 0
    ```
    並重跑原始 body 驗收：
    ```
    python3 programs/round1_gate.py --stage stage/out
    Step 4 = PASS
    ```
    """
)


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def _run(issue_body: Path, comment: Path,
         reopen: Path | None = None,
         json_out: Path | None = None) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(_PROG),
            "--issue-body-file", str(issue_body),
            "--comment-file", str(comment)]
    if reopen is not None:
        argv += ["--reopen-comment-file", str(reopen)]
    if json_out is not None:
        argv += ["--json", str(json_out)]
    return subprocess.run(argv, capture_output=True, text=True, timeout=30)


# ==========================================================================
# ## 驗收 — the headline end-to-end replay (the failure class)
# ==========================================================================
def test_acceptance_round2_quotes_original_only_fails_naming_reopen(tmp_path):
    """Issue body + round-2 reopen comment with a fenced repro + a fix
    comment that quotes ONLY the original acceptance → exit 1 naming the
    reopen commands."""
    issue = _write(tmp_path, "issue.md", _ISSUE_BODY)
    reopen = _write(tmp_path, "reopen.md", _REOPEN_COMMENT)
    comment = _write(tmp_path, "comment.md", _FIX_QUOTES_ORIGINAL_ONLY)

    r = _run(issue, comment, reopen=reopen)
    assert r.returncode == 1, (
        f"round-2 close that ignores the reopen repro must FAIL; "
        f"rc={r.returncode}\nstdout={r.stdout}\nstderr={r.stderr}")
    out = r.stdout + r.stderr
    # The reopen repro command must be NAMED in the failure.
    assert "round2_repro.py" in out, out
    assert "reopen" in out.lower(), out


def test_acceptance_round2_quotes_reopen_repro_passes(tmp_path):
    """A fix comment quoting the reopen repro + its end-state → exit 0."""
    issue = _write(tmp_path, "issue.md", _ISSUE_BODY)
    reopen = _write(tmp_path, "reopen.md", _REOPEN_COMMENT)
    comment = _write(tmp_path, "comment.md", _FIX_QUOTES_REOPEN)

    r = _run(issue, comment, reopen=reopen)
    assert r.returncode == 0, (
        f"round-2 close quoting the reopen repro + end-state must PASS; "
        f"rc={r.returncode}\nstdout={r.stdout}\nstderr={r.stderr}")
    assert "PASS" in r.stdout


def test_acceptance_no_reopen_case_unchanged(tmp_path):
    """No reopen comment → behavior unchanged (round-1): quoting the body
    acceptance + end-state passes."""
    issue = _write(tmp_path, "issue.md", _ISSUE_BODY)
    comment = _write(tmp_path, "comment.md", _FIX_QUOTES_ORIGINAL_ONLY)

    r = _run(issue, comment)  # no --reopen-comment-file
    assert r.returncode == 0, (
        f"round-1 (no reopen) quoting the body acceptance must PASS; "
        f"rc={r.returncode}\nstdout={r.stdout}\nstderr={r.stderr}")
    assert "PASS" in r.stdout


# ==========================================================================
# Reopen-comment DETECTION rule (documented + auditable)
# ==========================================================================
def test_detect_reopen_comment_requires_marker_and_fence():
    assert ACC.is_reopen_comment(_REOPEN_COMMENT) is True
    assert ACC.is_reopen_comment(_REOPEN_COMMENT_NARRATIVE) is True
    # marker but no fence → not a reopen comment
    assert ACC.is_reopen_comment(_REOPEN_MARKER_NO_FENCE) is False
    # fence but no marker → not a reopen comment
    assert ACC.is_reopen_comment(_PLAIN_COMMENT_WITH_FENCE) is False
    assert ACC.is_reopen_comment("") is False


def test_select_latest_reopen_comment_picks_newest():
    older = "複查 round-2:\n```\npython3 programs/old_repro.py\n```\n"
    newer = "複查 round-3:\n```\npython3 programs/new_repro.py\n```\n"
    comments = [_PLAIN_COMMENT_WITH_FENCE, older,
                "some unrelated comment", newer]
    picked = ACC.select_latest_reopen_comment(comments)
    assert picked == newer
    assert ACC.select_latest_reopen_comment(
        [_PLAIN_COMMENT_WITH_FENCE, "nope"]) is None


def test_extract_reopen_commands_keeps_commands_drops_output():
    cmds = ACC.extract_reopen_commands(_REOPEN_COMMENT)
    assert any("round2_repro.py" in c for c in cmds)
    # The end-state output lines are NOT treated as commands.
    assert not any(c.strip() == "exit 1" for c in cmds)
    assert not any(c.strip().startswith("Step 7") for c in cmds)


# ==========================================================================
# UNION + precedence semantics
# ==========================================================================
def test_reopen_commands_union_with_body():
    v = ACC.evaluate(_ISSUE_BODY, _FIX_QUOTES_REOPEN,
                     reopen_comment=_REOPEN_COMMENT)
    assert v.has_reopen is True
    assert any("round2_repro.py" in c for c in v.reopen_commands)
    # Binding command set is the union (both body + reopen present).
    joined = " ".join(v.commands)
    assert "round2_repro.py" in joined
    assert "round1_gate.py" in joined
    assert v.verdict == "PASS"


def test_round2_unquoted_reopen_named_in_verdict():
    v = ACC.evaluate(_ISSUE_BODY, _FIX_QUOTES_ORIGINAL_ONLY,
                     reopen_comment=_REOPEN_COMMENT)
    assert v.verdict == "FAIL"
    assert v.unquoted_reopen_commands, (
        "the reopen repro command must be reported as unquoted")
    assert any("round2_repro.py" in c
               for c in v.unquoted_reopen_commands)


# ==========================================================================
# Narrative-only reopen comment → falls back to body acceptance
# ==========================================================================
def test_narrative_only_reopen_falls_back_to_body(tmp_path):
    """A reopen comment with no fenced command adds no binding command —
    behavior falls back to the body acceptance (which here is satisfied
    by quoting the body command)."""
    issue = _write(tmp_path, "issue.md", _ISSUE_BODY)
    reopen = _write(tmp_path, "reopen.md", _REOPEN_COMMENT_NARRATIVE)
    comment = _write(tmp_path, "comment.md", _FIX_QUOTES_ORIGINAL_ONLY)

    r = _run(issue, comment, reopen=reopen)
    assert r.returncode == 0, (
        f"narrative-only reopen must fall back to body acceptance; "
        f"rc={r.returncode}\nstdout={r.stdout}\nstderr={r.stderr}")


def test_narrative_only_reopen_no_body_command_yields_narrative_only():
    """Reopen narrative-only + a body acceptance section that also has no
    fenced command → ACCEPTANCE_NARRATIVE_ONLY (the body's own path)."""
    body_no_cmd = textwrap.dedent(
        """\
        ## 現象
        x

        ## 驗收
        - 修法後此情況不再發生。
        """
    )
    v = ACC.evaluate(body_no_cmd, _FIX_QUOTES_ORIGINAL_ONLY,
                     reopen_comment=_REOPEN_COMMENT_NARRATIVE)
    assert v.verdict == "ACCEPTANCE_NARRATIVE_ONLY"
    assert v.has_reopen is True


# ==========================================================================
# JSON report carries the new reopen fields
# ==========================================================================
def test_json_report_carries_reopen_fields(tmp_path):
    issue = _write(tmp_path, "issue.md", _ISSUE_BODY)
    reopen = _write(tmp_path, "reopen.md", _REOPEN_COMMENT)
    comment = _write(tmp_path, "comment.md", _FIX_QUOTES_ORIGINAL_ONLY)
    jout = tmp_path / "v.json"
    r = _run(issue, comment, reopen=reopen, json_out=jout)
    assert r.returncode == 1
    data = json.loads(jout.read_text())
    assert data["has_reopen"] is True
    assert any("round2_repro.py" in c for c in data["reopen_commands"])
    assert any("round2_repro.py" in c
               for c in data["unquoted_reopen_commands"])


def test_missing_reopen_file_is_usage_error(tmp_path):
    issue = _write(tmp_path, "issue.md", _ISSUE_BODY)
    comment = _write(tmp_path, "comment.md", _FIX_QUOTES_REOPEN)
    r = subprocess.run(
        [sys.executable, str(_PROG),
         "--issue-body-file", str(issue),
         "--comment-file", str(comment),
         "--reopen-comment-file", str(tmp_path / "nope.md")],
        capture_output=True, text=True, timeout=30)
    assert r.returncode == 2


# ==========================================================================
# Regression: no-reopen behavior is byte-for-byte the round-1 contract
# ==========================================================================
def test_no_reopen_unquoted_body_still_fails(tmp_path):
    """No reopen comment, fix comment quotes nothing of the body
    acceptance → FAIL (round-1 contract, unchanged)."""
    issue = _write(tmp_path, "issue.md", _ISSUE_BODY)
    plain = textwrap.dedent(
        """\
        **本機驗證**：新測試 5/5 passed；全套 suite green。
        """
    )
    comment = _write(tmp_path, "comment.md", plain)
    r = _run(issue, comment)
    assert r.returncode == 1
    # No reopen → no reopen-specific naming in the output.
    assert "round2_repro.py" not in (r.stdout + r.stderr)


def test_no_reopen_no_acceptance_still_skips(tmp_path):
    """No reopen comment + no body acceptance → SKIP (unchanged)."""
    body = "## 現象\nx\n\n## 建議修法\ny\n"
    issue = _write(tmp_path, "issue.md", body)
    comment = _write(tmp_path, "comment.md",
                     "**本機驗證**：suite green.\n")
    r = _run(issue, comment)
    assert r.returncode == 0
    assert "SKIP" in r.stdout
