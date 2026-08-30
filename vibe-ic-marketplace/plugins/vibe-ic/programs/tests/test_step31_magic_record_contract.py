"""Step 31 validates the runner record's value before the independent audit."""
from __future__ import annotations

import json
from pathlib import Path

import flow_compliance_check as FCC
import magic_illegal_overlap_check as MIO
import test_magic_illegal_overlap_check as MIO_TEST


FLOW = Path(__file__).resolve().parents[2] / "flow" / "phase1_phase2_phase3.yaml"
RECORD_REL = "reports/phase3/magic_illegal_overlap.json"
RECORD_COMMAND = f"magic_illegal_overlap_record_check . --record {RECORD_REL}"


def _record_clause():
    import yaml

    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    step = next(s for s in doc["steps"] if s["id"] == 31)
    matches = [c for c in step["gate"]["all_of"]
               if isinstance(c, dict)
               and c.get("program_exit_zero") == RECORD_COMMAND]
    assert len(matches) == 1, (
        "Step 31 must carry exactly the executable runner-record contract "
        f"{RECORD_COMMAND!r}; a files_exist-only, missing, empty, or wrong "
        "program_exit_zero value is not that contract")
    return matches[0]


def _clean_record(project: Path) -> dict:
    report = MIO.check(project)
    assert report["passed"] is True and report["skipped"] is False, report
    return report


def _write_record(project: Path, value: str) -> None:
    path = project / RECORD_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def test_step31_record_clause_accepts_the_actual_runner_value(tmp_path):
    project = MIO_TEST._project(tmp_path / "clean", feedback="")
    _write_record(project, json.dumps(_clean_record(project)))
    passed, reasons = FCC._evaluate_gate(project, _record_clause())
    assert passed is True, reasons


def test_step31_record_clause_fails_when_the_actual_value_is_missing(tmp_path):
    project = MIO_TEST._project(tmp_path / "missing", feedback="")
    passed, reasons = FCC._evaluate_gate(project, _record_clause())
    assert passed is False
    assert any("program failed" in reason for reason in reasons), reasons


def test_step31_record_clause_fails_when_the_actual_value_is_empty(tmp_path):
    project = MIO_TEST._project(tmp_path / "empty", feedback="")
    _write_record(project, "")
    passed, reasons = FCC._evaluate_gate(project, _record_clause())
    assert passed is False
    assert any("program failed" in reason for reason in reasons), reasons


def test_step31_record_clause_fails_when_the_actual_value_is_wrong(tmp_path):
    project = MIO_TEST._project(tmp_path / "wrong", feedback="")
    report = _clean_record(project)
    report["passed"] = False
    _write_record(project, json.dumps(report))
    passed, reasons = FCC._evaluate_gate(project, _record_clause())
    assert passed is False
    assert any("program failed" in reason for reason in reasons), reasons


def test_phase3_runner_blocks_on_the_same_record_validator_before_lvs():
    runner = (Path(__file__).resolve().parents[1] /
              "phase3_one_shot_runner.py").read_text(encoding="utf-8")
    body = runner[runner.index("def _run_illegal_overlap_gate("):]
    body = body[:body.index("\ndef ", 10)]
    assert "magic_illegal_overlap_record_check.py" in body
    assert "checked = subprocess.run(" in body
    assert "if checked.returncode != 0:" in body


def test_step31_record_clause_fails_when_the_value_is_a_symlink(tmp_path):
    """Presence is not the producer contract. A record that is a SYMLINK is
    bytes some other tree owns; the clause must refuse it even when the target
    is a byte-perfect PASS, because the run did not write it."""
    project = MIO_TEST._project(tmp_path / "symlink", feedback="")
    elsewhere = tmp_path / "elsewhere.json"
    elsewhere.write_text(json.dumps(_clean_record(project)), encoding="utf-8")
    path = project / RECORD_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(elsewhere)
    assert json.loads(path.read_text(encoding="utf-8"))["passed"] is True, (
        "the control for this test: the symlink TARGET is a clean PASS, so a "
        "presence-or-content check alone would accept it")
    passed, reasons = FCC._evaluate_gate(project, _record_clause())
    assert passed is False
    assert any("program failed" in reason for reason in reasons), reasons
