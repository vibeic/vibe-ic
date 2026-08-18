#!/usr/bin/env python3
"""test_v0_2_97_issue478_acceptance_gates.py — issue #478 regression gate.

ISSUE #478 (HIGH, Bucket A) — make acceptance-criterion execution
DETERMINISTIC in the core-agent loop. Two new programs:

  * programs/acceptance_evidence_in_fix_comment_check.py  (program 1)
  * programs/defect_artifact_fixture_check.py             (program 2)

ACCEPTANCE DOCTRINE FOLLOWED BY THIS TEST
-----------------------------------------
Per the binding doctrine, this test (a) builds a *defect-artifact fixture*
shaped like the issue's 現象 — the #460-shape pair of (issue body + fix
comment + regression test) that the field agent flipped on — and (b) asserts
the END STATE by INVOKING THE REAL PROGRAM/GATE via subprocess and asserting
its exit code (verdict), not just unit-level internals.

The issue's own ## 驗收 reads:
    重演 #460 形（只斷言 bridge 檔案存在的測試 + 不含 acceptance 指令的
    fix comment）→ program 1 exits 1 AND program 2 exits 1；合規 fix
    comment（逐字引用指令 + 端態輸出）+ 一個 subprocess-runs the real gate
    並斷言其 verdict 的測試 → 兩者皆 exit 0。

The tests below replay exactly that, end-to-end, against the real CLIs.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

# Plugin layout: this file is at programs/tests/, programs at parent.
_PROGRAMS = Path(__file__).resolve().parents[1]
_PROG1 = _PROGRAMS / "acceptance_evidence_in_fix_comment_check.py"
_PROG2 = _PROGRAMS / "defect_artifact_fixture_check.py"


# --------------------------------------------------------------------------
# Defect-artifact fixtures — the #460-SHAPE inputs (synthetic, chip-AGNOSTIC)
# --------------------------------------------------------------------------
# An issue body shaped like #460: a 現象 + a 根因 + a ## 驗收 section that
# names concrete end-to-end commands and an artifact the test must replay.
_ISSUE_BODY_WITH_ACCEPTANCE = textwrap.dedent(
    """\
    ## 現象（synthetic capture）
    The downstream gate only recognises `stage/out/results.json`, which the
    upstream step deliberately stopped writing — real evidence in
    `stage/out/oracle.log` earns nothing at the close step.

    ## 根因
    Two correct fixes with no bridge between them.

    ## 建議修法（chip-AGNOSTIC）
    Emit the canonical results.json when the oracle evidence is real.

    ## 驗收
    - run `python3 programs/widget_bridge_check.py --stage stage/out` →
      Step 4 = PASS and evidence resolves to oracle.log
    - skeleton-only run Step 4 must not PASS
    """
)

# A NON-COMPLIANT fix comment (the #460 failure mode): it has a 本機驗證
# section, but it only reports the NEW code's intermediate products and
# NEVER quotes / runs the acceptance command.
_COMMENT_NONCOMPLIANT = textwrap.dedent(
    """\
    Core agent 已推送修復：abc1234

    **問題**：downstream gate ignored real oracle evidence.

    **根因**：no bridge between the two fixes.

    **修法**：emit canonical results.json when oracle evidence is real.
    Files changed: programs/widget_bridge_check.py.

    **本機驗證**：新測試 3/3 PASS；full suite 4321/4321 綠。

    Core agent 已自行驗證並關閉此 issue（已加 core-closed 標籤）。field
    agent 複查若發現未完整，請 reopen 並補反證。
    """
)

# A COMPLIANT fix comment: quotes the acceptance command verbatim AND
# carries end-state output evidence next to it.
_COMMENT_COMPLIANT = textwrap.dedent(
    """\
    Core agent 已推送修復：abc1234

    **問題**：downstream gate ignored real oracle evidence.

    **根因**：no bridge between the two fixes.

    **修法**：emit canonical results.json when oracle evidence is real.
    Files changed: programs/widget_bridge_check.py.

    **本機驗證**：
    執行 issue 的 ## 驗收 端到端指令：
    ```
    $ python3 programs/widget_bridge_check.py --stage stage/out
    Step 4 = PASS
    evidence -> stage/out/oracle.log
    exit 0
    ```
    skeleton-only run：Step 4 = FAIL（未搭橋），符合預期。

    Core agent 已自行驗證並關閉此 issue（已加 core-closed 標籤）。field
    agent 複查若發現未完整，請 reopen 並補反證。
    """
)

# Issue body WITHOUT an acceptance section (vacuous case).
_ISSUE_BODY_NO_ACCEPTANCE = textwrap.dedent(
    """\
    ## 現象
    Something is slightly off in the report layout.

    ## 根因
    Cosmetic only.

    ## 建議修法
    Tweak the heading.
    """
)

# A regression test source that ONLY asserts file existence (#460 shape).
_TEST_SRC_EXISTS_ONLY = textwrap.dedent(
    """\
    from pathlib import Path

    def test_bridge_emits_results(tmp_path):
        out = tmp_path / "results.json"
        out.write_text("{}")
        assert out.exists()
        assert (tmp_path / "results.json").is_file()
    """
)

# A COMPLIANT regression test: builds a defect-artifact fixture (tmp_path
# write shaped like the issue's named artifact) AND asserts the END state
# by subprocess-running the real program and asserting its returncode.
_TEST_SRC_COMPLIANT = textwrap.dedent(
    """\
    import subprocess
    from pathlib import Path

    def test_bridge_end_state(tmp_path):
        # defect-artifact fixture shaped like the issue's 現象
        stage = tmp_path / "stage" / "out"
        stage.mkdir(parents=True)
        (stage / "oracle.log").write_text("ORACLE_TB_DONE pass=28/28")
        # END-STATE assertion via the real gate
        r = subprocess.run(
            ["python3", "programs/widget_bridge_check.py",
             "--stage", str(stage)],
            capture_output=True, text=True)
        assert r.returncode == 0
        assert "PASS" in r.stdout
    """
)


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def _run_prog1(issue_body: Path, comment: Path,
               json_out: Path | None = None) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(_PROG1),
            "--issue-body-file", str(issue_body),
            "--comment-file", str(comment)]
    if json_out:
        argv += ["--json", str(json_out)]
    return subprocess.run(argv, capture_output=True, text=True)


def _run_prog2(issue_body: Path, test_file: Path,
               json_out: Path | None = None) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(_PROG2),
            "--issue-body-file", str(issue_body),
            "--test-file", str(test_file)]
    if json_out:
        argv += ["--json", str(json_out)]
    return subprocess.run(argv, capture_output=True, text=True)


# ==========================================================================
# ## 驗收 — the headline end-to-end replay (both directions)
# ==========================================================================
def test_acceptance_460_shape_both_gates_reject(tmp_path):
    """Replay the #460 shape: non-compliant comment + file-existence-only
    test → program 1 exits 1 AND program 2 exits 1."""
    issue = _write(tmp_path, "issue.md", _ISSUE_BODY_WITH_ACCEPTANCE)
    comment = _write(tmp_path, "comment.md", _COMMENT_NONCOMPLIANT)
    test_file = _write(tmp_path, "test_bad.py", _TEST_SRC_EXISTS_ONLY)

    r1 = _run_prog1(issue, comment)
    r2 = _run_prog2(issue, test_file)

    assert r1.returncode == 1, (
        f"program 1 should reject; rc={r1.returncode}\n"
        f"stdout={r1.stdout}\nstderr={r1.stderr}")
    assert r2.returncode == 1, (
        f"program 2 should reject; rc={r2.returncode}\n"
        f"stdout={r2.stdout}\nstderr={r2.stderr}")


def test_acceptance_compliant_both_gates_pass(tmp_path):
    """Compliant comment (quotes commands + end-state output) + a test that
    subprocess-runs the real gate and asserts its verdict → both exit 0."""
    issue = _write(tmp_path, "issue.md", _ISSUE_BODY_WITH_ACCEPTANCE)
    comment = _write(tmp_path, "comment.md", _COMMENT_COMPLIANT)
    test_file = _write(tmp_path, "test_good.py", _TEST_SRC_COMPLIANT)

    r1 = _run_prog1(issue, comment)
    r2 = _run_prog2(issue, test_file)

    assert r1.returncode == 0, (
        f"program 1 should pass; rc={r1.returncode}\n"
        f"stdout={r1.stdout}\nstderr={r1.stderr}")
    assert r2.returncode == 0, (
        f"program 2 should pass; rc={r2.returncode}\n"
        f"stdout={r2.stdout}\nstderr={r2.stderr}")


# ==========================================================================
# program 1 — finer-grained regression guards
# ==========================================================================
def test_prog1_missing_evidence_only_quotes_command(tmp_path):
    """Quoting the command but pasting NO end-state output must FAIL
    (the precise #460/#466 failure mode)."""
    issue = _write(tmp_path, "issue.md", _ISSUE_BODY_WITH_ACCEPTANCE)
    comment_body = textwrap.dedent(
        """\
        **本機驗證**：執行了 `python3 programs/widget_bridge_check.py
        --stage stage/out`。

        Core agent 已自行驗證並關閉此 issue（已加 core-closed 標籤）。
        """
    )
    comment = _write(tmp_path, "comment.md", comment_body)
    r = _run_prog1(issue, comment)
    assert r.returncode == 1
    assert "end-state" in (r.stdout + r.stderr).lower()


def test_prog1_no_acceptance_section_skips(tmp_path):
    """An issue with no acceptance section is vacuous → exit 0 (SKIP)."""
    issue = _write(tmp_path, "issue.md", _ISSUE_BODY_NO_ACCEPTANCE)
    comment = _write(tmp_path, "comment.md", _COMMENT_NONCOMPLIANT)
    r = _run_prog1(issue, comment)
    assert r.returncode == 0
    assert "SKIP" in r.stdout


def test_prog1_no_local_verification_section_fails(tmp_path):
    """A comment with no 本機驗證 section fails when acceptance exists."""
    issue = _write(tmp_path, "issue.md", _ISSUE_BODY_WITH_ACCEPTANCE)
    comment = _write(tmp_path, "comment.md",
                     "**問題**：x\n**修法**：y\n")
    r = _run_prog1(issue, comment)
    assert r.returncode == 1


def test_prog1_json_report(tmp_path):
    """--json emits a parseable verdict report."""
    import json
    issue = _write(tmp_path, "issue.md", _ISSUE_BODY_WITH_ACCEPTANCE)
    comment = _write(tmp_path, "comment.md", _COMMENT_COMPLIANT)
    jout = tmp_path / "v.json"
    r = _run_prog1(issue, comment, json_out=jout)
    assert r.returncode == 0
    data = json.loads(jout.read_text())
    assert data["verdict"] == "PASS"
    assert data["has_acceptance"] is True
    assert data["end_state_evidence"] is True
    assert data["unquoted_commands"] == []


def test_prog1_offline_mode_needs_no_network(tmp_path):
    """Offline mode (--issue-body-file) must not touch the network."""
    issue = _write(tmp_path, "issue.md", _ISSUE_BODY_WITH_ACCEPTANCE)
    comment = _write(tmp_path, "comment.md", _COMMENT_COMPLIANT)
    # Force any accidental urllib use to fail loudly by clearing token env.
    import os
    env = dict(os.environ)
    env.pop("GITHUB_TOKEN", None)
    r = subprocess.run(
        [sys.executable, str(_PROG1),
         "--issue-body-file", str(issue),
         "--comment-file", str(comment)],
        capture_output=True, text=True, env=env)
    assert r.returncode == 0


def test_prog1_missing_comment_file_is_usage_error(tmp_path):
    """Missing --comment-file → exit 2 (usage/IO error)."""
    issue = _write(tmp_path, "issue.md", _ISSUE_BODY_WITH_ACCEPTANCE)
    r = subprocess.run(
        [sys.executable, str(_PROG1),
         "--issue-body-file", str(issue),
         "--comment-file", str(tmp_path / "nope.md")],
        capture_output=True, text=True)
    assert r.returncode == 2


# ==========================================================================
# program 2 — finer-grained regression guards
# ==========================================================================
def test_prog2_exists_only_test_fails(tmp_path):
    """A test asserting only file existence fails the end-state rule."""
    issue = _write(tmp_path, "issue.md", _ISSUE_BODY_WITH_ACCEPTANCE)
    test_file = _write(tmp_path, "test_bad.py", _TEST_SRC_EXISTS_ONLY)
    r = _run_prog2(issue, test_file)
    assert r.returncode == 1
    out = (r.stdout + r.stderr).lower()
    assert "end-state" in out or "existence" in out


def test_prog2_compliant_test_passes(tmp_path):
    """A test with a fixture + subprocess gate + verdict assert passes."""
    issue = _write(tmp_path, "issue.md", _ISSUE_BODY_WITH_ACCEPTANCE)
    test_file = _write(tmp_path, "test_good.py", _TEST_SRC_COMPLIANT)
    r = _run_prog2(issue, test_file)
    assert r.returncode == 0


def test_prog2_entrypoint_call_variant_passes(tmp_path):
    """A test that imports the program's main + asserts its rc also passes."""
    issue = _write(tmp_path, "issue.md", _ISSUE_BODY_WITH_ACCEPTANCE)
    src = textwrap.dedent(
        """\
        from pathlib import Path
        from widget_bridge_check import main

        def test_via_main(tmp_path):
            stage = tmp_path / "stage" / "out"
            stage.mkdir(parents=True)
            (stage / "oracle.log").write_text("pass=28/28")
            rc = main(["--stage", str(stage)])
            assert rc == 0
        """
    )
    test_file = _write(tmp_path, "test_entry.py", src)
    r = _run_prog2(issue, test_file)
    assert r.returncode == 0


def test_prog2_no_acceptance_section_skips(tmp_path):
    """Issue without acceptance section → exit 0 (vacuous)."""
    issue = _write(tmp_path, "issue.md", _ISSUE_BODY_NO_ACCEPTANCE)
    test_file = _write(tmp_path, "test_bad.py", _TEST_SRC_EXISTS_ONLY)
    r = _run_prog2(issue, test_file)
    assert r.returncode == 0
    assert "SKIP" in r.stdout


def test_prog2_fixture_present_but_no_end_state_fails(tmp_path):
    """A fixture-building test that still only asserts existence fails (b)."""
    issue = _write(tmp_path, "issue.md", _ISSUE_BODY_WITH_ACCEPTANCE)
    src = textwrap.dedent(
        """\
        from pathlib import Path

        def test_fixture_only(tmp_path):
            stage = tmp_path / "stage" / "out"
            stage.mkdir(parents=True)
            (stage / "oracle.log").write_text("pass=28/28")
            assert (stage / "oracle.log").exists()
        """
    )
    test_file = _write(tmp_path, "test_fx.py", src)
    r = _run_prog2(issue, test_file)
    assert r.returncode == 1
    assert "end-state" in (r.stdout + r.stderr).lower()


def test_prog2_unparseable_test_falls_back_to_regex(tmp_path):
    """A test source that does not parse as Python still gets a regex-based
    verdict (compliant content → PASS)."""
    issue = _write(tmp_path, "issue.md", _ISSUE_BODY_WITH_ACCEPTANCE)
    # Deliberate syntax error + compliant content.
    src = (
        "def test_x(tmp_path)\n"   # missing colon -> SyntaxError
        "    p = tmp_path / 'oracle.log'\n"
        "    p.write_text('x')\n"
        "    import subprocess\n"
        "    r = subprocess.run(['python3','programs/widget_bridge_check.py'])\n"
        "    assert r.returncode == 0\n"
    )
    test_file = _write(tmp_path, "test_broken.py", src)
    r = _run_prog2(issue, test_file)
    assert r.returncode == 0


def test_prog2_json_report(tmp_path):
    import json
    issue = _write(tmp_path, "issue.md", _ISSUE_BODY_WITH_ACCEPTANCE)
    test_file = _write(tmp_path, "test_bad.py", _TEST_SRC_EXISTS_ONLY)
    jout = tmp_path / "v.json"
    r = _run_prog2(issue, test_file, json_out=jout)
    assert r.returncode == 1
    data = json.loads(jout.read_text())
    assert data["verdict"] == "FAIL"
    assert data["end_state_ok"] is False
    assert any("end-state" in g for g in data["gaps"])


def test_prog2_missing_test_file_is_usage_error(tmp_path):
    issue = _write(tmp_path, "issue.md", _ISSUE_BODY_WITH_ACCEPTANCE)
    r = subprocess.run(
        [sys.executable, str(_PROG2),
         "--issue-body-file", str(issue),
         "--test-file", str(tmp_path / "nope.py")],
        capture_output=True, text=True)
    assert r.returncode == 2


# ==========================================================================
# Direct-import unit coverage of the helper functions (faster + precise)
# ==========================================================================
def test_extract_acceptance_section_unit():
    import acceptance_evidence_in_fix_comment_check as m
    sec = m.extract_acceptance_section(_ISSUE_BODY_WITH_ACCEPTANCE)
    assert sec is not None
    assert "widget_bridge_check.py" in sec
    assert m.extract_acceptance_section(_ISSUE_BODY_NO_ACCEPTANCE) is None


def test_extract_commands_unit():
    import acceptance_evidence_in_fix_comment_check as m
    sec = m.extract_acceptance_section(_ISSUE_BODY_WITH_ACCEPTANCE)
    cmds, _crit = m.extract_commands(sec)
    assert any("widget_bridge_check.py" in c for c in cmds)


def test_evaluate_prog1_compliant_unit():
    import acceptance_evidence_in_fix_comment_check as m
    v = m.evaluate(_ISSUE_BODY_WITH_ACCEPTANCE, _COMMENT_COMPLIANT)
    assert v.verdict == "PASS"
    v2 = m.evaluate(_ISSUE_BODY_WITH_ACCEPTANCE, _COMMENT_NONCOMPLIANT)
    assert v2.verdict == "FAIL"
    assert v2.unquoted_commands


def test_evaluate_prog2_units():
    import defect_artifact_fixture_check as m
    v_ok = m.evaluate(_ISSUE_BODY_WITH_ACCEPTANCE, _TEST_SRC_COMPLIANT)
    assert v_ok.verdict == "PASS"
    v_bad = m.evaluate(_ISSUE_BODY_WITH_ACCEPTANCE, _TEST_SRC_EXISTS_ONLY)
    assert v_bad.verdict == "FAIL"
    v_skip = m.evaluate(_ISSUE_BODY_NO_ACCEPTANCE, _TEST_SRC_EXISTS_ONLY)
    assert v_skip.verdict == "SKIP"
