"""Tests for changelog_command_reproducibility_check.py (v1.6.43)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "programs"))

import changelog_command_reproducibility_check as g  # noqa: E402


def _make_plugin(tmp_path: Path, changelog_text: str) -> Path:
    p = tmp_path / "vibe-ic"
    (p / "programs").mkdir(parents=True)
    (p / ".claude-plugin").mkdir(parents=True)
    (p.parent / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (p / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "vibe-ic", "version": "1.6.43"}))
    (p.parent / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps({"name": "test-marketplace"}))
    (p / "CHANGELOG.md").write_text(changelog_text)
    return p


def test_pass_when_target_exists(tmp_path):
    p = _make_plugin(tmp_path,
                     "## v1\n\n```\n$ bash tools/ci/run.sh\n```\n")
    (p / "tools" / "ci").mkdir(parents=True)
    (p / "tools" / "ci" / "run.sh").write_text("#!/bin/bash\n")
    verdict, findings = g.audit(p)
    assert verdict == "PASS", findings


def test_fail_when_bash_target_missing(tmp_path):
    p = _make_plugin(tmp_path,
                     "## v1\n\n```\n$ bash tools/ci/missing.sh\n```\n")
    verdict, findings = g.audit(p)
    assert verdict == "FAIL"
    assert findings[0].rule == "MISSING_SCRIPT"
    assert "missing.sh" in findings[0].command


def test_fail_when_python_script_missing(tmp_path):
    p = _make_plugin(
        tmp_path,
        "## v1\n\n```\n$ python3 programs/ghost.py .\n```\n")
    verdict, findings = g.audit(p)
    assert verdict == "FAIL"
    assert findings[0].rule == "MISSING_SCRIPT"


def test_pass_when_python_script_exists(tmp_path):
    p = _make_plugin(
        tmp_path,
        "## v1\n\n```\n$ python3 programs/real.py .\n```\n")
    (p / "programs" / "real.py").write_text("print('ok')\n")
    verdict, findings = g.audit(p)
    assert verdict == "PASS", findings


def test_skip_unaudited_verbs(tmp_path):
    """`git status` / `docker ps` etc. are out of scope and don't fail."""
    p = _make_plugin(tmp_path,
                     "## v1\n\n```\n$ git status\n$ docker ps\n```\n")
    verdict, findings = g.audit(p)
    assert verdict == "PASS", findings


def test_python_module_invocation_skipped(tmp_path):
    """`python3 -m pytest` is a module run, not a path — out of scope."""
    p = _make_plugin(tmp_path,
                     "## v1\n\n```\n$ python3 -m pytest tests/\n```\n")
    verdict, findings = g.audit(p)
    assert verdict == "PASS", findings


def test_vacuous_pass_when_no_changelog(tmp_path):
    p = tmp_path / "empty"
    p.mkdir()
    verdict, findings = g.audit(p)
    assert verdict == "VACUOUS_PASS"
    assert findings == []
