"""Issue #3406: WARN producers may name their identifier `rule`."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROG = Path(__file__).resolve().parent.parent / "warn_acceptance_policy_check.py"
RULE = "CDC_UNSYNCED_DATA_QUALIFIED"


def _project(tmp_path: Path) -> Path:
    report = tmp_path / "reports" / "phase2" / "gates" / "cdc.json"
    report.parent.mkdir(parents=True)
    rtl = tmp_path / "rtl.sv"
    rtl.write_text("module rtl;\nendmodule\n")
    report.write_text(json.dumps({
        "program": "clock_domain_reg_crossing_check",
        "findings": [{
            "rule": RULE,
            "severity": "WARN",
            "file": "rtl.sv",
            "line": 1,
            "message": "qualified bundled-data crossing",
        }],
    }))
    return tmp_path


def _run(project: Path):
    return subprocess.run([sys.executable, str(PROG), "--project-dir",
                           str(project)], capture_output=True, text=True)


def _log(project: Path, rule: str, file_key: str = "rtl.sv:1"):
    (project / "WARN_ACCEPTANCE_LOG.md").write_text(
        "| gate | file | rule | resolution |\n"
        f"| clock_domain_reg_crossing_check | {file_key} | {rule} | reviewed |\n")


def test_rule_is_preserved_in_unaddressed_diagnostic(tmp_path):
    actual = _run(_project(tmp_path))
    assert actual.returncode == 1
    payload = json.loads(actual.stdout)
    assert f"clock_domain_reg_crossing_check/{RULE}" in payload["findings"][0]["message"]
    assert payload["summary"]["unaddressed_details"][0]["identifier"] == RULE


def test_only_the_exact_rule_row_accepts_the_warning(tmp_path):
    project = _project(tmp_path)
    for wrong in ("", "CDC_UNSYNCED_DATA", RULE + "_OTHER"):
        _log(project, wrong)
        actual = _run(project)
        assert actual.returncode == 1, (wrong, actual.stdout, actual.stderr)
    _log(project, RULE)
    actual = _run(project)
    assert actual.returncode == 0, actual.stdout + actual.stderr


def test_same_rule_for_a_different_file_does_not_accept(tmp_path):
    project = _project(tmp_path)
    _log(project, RULE, "other.sv:1")
    actual = _run(project)
    assert actual.returncode == 1, actual.stdout + actual.stderr


def test_rule_specific_silence_comment_accepts_the_warning(tmp_path):
    project = _project(tmp_path)
    (project / "rtl.sv").write_text(
        "// cdc-unsynced-data-qualified-ok\nmodule rtl;\nendmodule\n")
    actual = _run(project)
    assert actual.returncode == 0, actual.stdout + actual.stderr
