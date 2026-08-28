"""v0.2.98 — flow #485: narrative-only '## 驗收' sections get a NAMED
ACCEPTANCE_NARRATIVE_ONLY warning, never a silent vacuous SKIP, on BOTH
sides of the loop:

  * gate side — acceptance_evidence_in_fix_comment_check returns the
    named verdict (exit 0: does not block closing, but leaves an
    auditable trace + the manual-audit instruction);
  * filing side — a zero-command acceptance section is detectable via
    the same extractors (the intake check wires this as a non-fatal
    filing WARNING);
  * UNCHANGED behavior pins: a fenced-command acceptance section still
    bites (rc 1 unquoted / rc 0 compliant), and a no-acceptance issue
    is still a SKIP.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import acceptance_evidence_in_fix_comment_check as ACC  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_ISSUE_NARRATIVE = """## 現象
某 gate 在特定輸入下誤判。

## 建議修法
調整判斷分支。

## 驗收
- 兩份 triage json 餵進去 → 正確列出 4 筆違規。
- 合規 records → PASS。
"""

_ISSUE_FENCED = """## 現象
某 gate 在特定輸入下誤判。

## 驗收
```bash
python3 programs/triage_record_check.py /tmp/fixture.json
```
→ 必須 rc=1 並列出違規。
"""

_ISSUE_NO_ACCEPTANCE = """## 現象
某 gate 在特定輸入下誤判。

## 建議修法
調整判斷分支。
"""

_COMMENT_PLAIN = """Core agent 已推送修復：abc1234

**問題**：x
**根因**：y
**修法**：z

**本機驗證**：新測試 5/5 passed；全套 suite green。
"""

_COMMENT_QUOTED = """Core agent 已推送修復：abc1234

**問題**：x
**根因**：y
**修法**：z

**本機驗證**：執行 `python3 programs/triage_record_check.py /tmp/fixture.json`
→ rc=1，輸出：FAIL: 2 violation(s), 2 review finding(s) in 4 record(s)。
"""


def _run(tmp_path, issue_body, comment_body):
    ip = tmp_path / "issue.md"
    cp = tmp_path / "comment.md"
    ip.write_text(issue_body)
    cp.write_text(comment_body)
    return _pr.run(
        [sys.executable,
         str(PROGRAMS / "acceptance_evidence_in_fix_comment_check.py"),
         "--issue-body-file", str(ip), "--comment-file", str(cp)],
        capture_output=True, text=True)


# ── #485 fixed path: narrative-only → NAMED warning, not silent SKIP ──

def test_narrative_only_yields_named_warning(tmp_path):
    r = _run(tmp_path, _ISSUE_NARRATIVE, _COMMENT_PLAIN)
    assert r.returncode == 0          # does not block closing
    assert "ACCEPTANCE_NARRATIVE_ONLY" in r.stdout
    assert "SKIP (PASS)" not in r.stdout   # never the silent-skip wording


def test_narrative_only_verdict_object_named():
    v = ACC.evaluate(_ISSUE_NARRATIVE, _COMMENT_PLAIN)
    assert v.verdict == "ACCEPTANCE_NARRATIVE_ONLY"
    assert v.has_acceptance is True
    assert v.commands == []
    # the manual-audit instruction travels in the notes
    assert any("manually" in n for n in v.notes)


def test_filing_side_extractors_detect_zero_command():
    # the intake check wires exactly these two extractor calls (flow
    # #485 filing WARNING) — pin the underlying detection here, offline.
    sec = ACC.extract_acceptance_section(_ISSUE_NARRATIVE)
    assert sec is not None
    cmds, _ = ACC.extract_commands(sec)
    assert cmds == []
    sec2 = ACC.extract_acceptance_section(_ISSUE_FENCED)
    cmds2, _ = ACC.extract_commands(sec2)
    assert cmds2, "fenced command must be extracted"


def test_intake_check_carries_filing_warning_wiring():
    # the filing-side warning is wired into regression_issue_intake_check
    # (network tool — pin the source wiring offline).
    src = (PROGRAMS / "regression_issue_intake_check.py").read_text()
    assert "ACCEPTANCE_NARRATIVE_ONLY" in src
    assert "extract_acceptance_section" in src


# ── regression guards: prior behavior unchanged ──────────────────────

def test_fenced_command_unquoted_still_fails(tmp_path):
    r = _run(tmp_path, _ISSUE_FENCED, _COMMENT_PLAIN)
    assert r.returncode == 1


def test_fenced_command_quoted_with_endstate_passes(tmp_path):
    r = _run(tmp_path, _ISSUE_FENCED, _COMMENT_QUOTED)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_no_acceptance_section_still_skip(tmp_path):
    r = _run(tmp_path, _ISSUE_NO_ACCEPTANCE, _COMMENT_PLAIN)
    assert r.returncode == 0
    assert "SKIP" in r.stdout
    assert "ACCEPTANCE_NARRATIVE_ONLY" not in r.stdout


def test_field_skill_documents_filing_convention():
    skill = (PROGRAMS.parent / "skills" / "field-agent-loop" /
             "SKILL.md").read_text()
    assert "ACCEPTANCE_NARRATIVE_ONLY" in skill
    assert "flow #485" in skill
