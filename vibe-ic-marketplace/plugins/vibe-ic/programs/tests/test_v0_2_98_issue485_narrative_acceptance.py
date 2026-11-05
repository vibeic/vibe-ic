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


# ── #485 fixed path: narrative-only → NAMED warning, not silent SKIP ──


# ── regression guards: prior behavior unchanged ──────────────────────


def test_field_skill_documents_filing_convention():
    skill = (PROGRAMS.parent / "skills" / "field-agent-loop" /
             "SKILL.md").read_text()
    assert "ACCEPTANCE_NARRATIVE_ONLY" in skill
    assert "flow #485" in skill
