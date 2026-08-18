"""v0.2.101 — flow #489: standalone filing-time lint for ORGANIC-form
issue bodies (no network, no template assumption; stdin or file).

Pins (incl. the issue's verbatim ## 驗收):
  * narrative-only acceptance body via stdin → named
    ACCEPTANCE_NARRATIVE_ONLY warning, exit 0 (trace, advisory);
  * body with fenced acceptance command + named artifact → PASS, no
    findings;
  * MISSING_ACCEPTANCE / NO_DEFECT_ARTIFACT named findings;
  * --strict turns findings into exit 1 (automation hook);
  * extractors are REUSED from acceptance_evidence_in_fix_comment_check
    (single grammar source);
  * the filing wiring is documented in community-backlog-submit +
    field-agent-loop.
"""
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
PROG = PROGRAMS / "organic_issue_body_lint.py"

_BODY_NARRATIVE = """## 現象
某 gate 在 reports/phase2/gates/foo.json 上誤判。

## 驗收
- 兩份 json 餵進去 → 正確列出違規。
"""

_BODY_COMPLIANT = """## 現象
某 gate 在 `reports/phase2/gates/foo.json` 上誤判。

## 驗收
```bash
python3 programs/some_check.py reports/phase2/gates/foo.json
```
→ rc=1 並列出違規。
"""

_BODY_NO_ACCEPTANCE_NO_ARTIFACT = """## 現象
某 gate 偶發誤判。

## 建議修法
調整判斷分支。
"""


def _run(stdin_text=None, path=None, *extra):
    cmd = [sys.executable, str(PROG), path or "-", *extra]
    return subprocess.run(cmd, input=stdin_text, capture_output=True,
                          text=True, timeout=30)


def test_acceptance_verbatim_narrative_stdin_named_warning():
    # 驗收①: echo "<無 fenced 指令的 ORGANIC body>" | ... lint - →
    # 具名 ACCEPTANCE_NARRATIVE_ONLY WARNING（exit 0 留痕）
    r = _run(stdin_text=_BODY_NARRATIVE)
    assert r.returncode == 0
    assert "ACCEPTANCE_NARRATIVE_ONLY" in r.stdout


def test_acceptance_verbatim_compliant_passes():
    # 驗收②: 含 fenced 驗收指令＋artifact 的 body → PASS 無 findings
    r = _run(stdin_text=_BODY_COMPLIANT)
    assert r.returncode == 0
    assert "PASS" in r.stdout
    assert "WARNING" not in r.stdout


def test_missing_acceptance_and_artifact_named(tmp_path):
    p = tmp_path / "body.md"
    p.write_text(_BODY_NO_ACCEPTANCE_NO_ARTIFACT)
    r = _run(path=str(p))
    assert r.returncode == 0
    assert "MISSING_ACCEPTANCE" in r.stdout
    assert "NO_DEFECT_ARTIFACT" in r.stdout
    assert "defect_artifact_snapshot" in r.stdout   # #487 reminder travels


def test_strict_exits_one_on_findings():
    r = _run(stdin_text=_BODY_NARRATIVE, path=None) ; assert r.returncode == 0
    r2 = _run(_BODY_NARRATIVE, None, "--strict")
    assert r2.returncode == 1


def test_empty_body_is_io_error():
    r = _run(stdin_text="   \n")
    assert r.returncode == 2


def test_extractors_reused_not_duplicated():
    src = PROG.read_text()
    assert "from acceptance_evidence_in_fix_comment_check import" in src
    # no second copy of the section grammar
    assert "def extract_acceptance_section" not in src


def test_filing_wiring_documented():
    skills = PROGRAMS.parent / "skills"
    cbs = (skills / "community-backlog-submit" / "SKILL.md").read_text()
    fal = (skills / "field-agent-loop" / "SKILL.md").read_text()
    assert "organic_issue_body_lint" in cbs
    assert "organic_issue_body_lint" in fal
