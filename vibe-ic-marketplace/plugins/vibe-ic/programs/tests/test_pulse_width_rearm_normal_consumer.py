"""Issue #2856 normal-runner integration and receipt binding."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "pulse_width_rearm"
CONTRACT = FIXTURES / "contract.json"
GOOD = FIXTURES / "compliant.sv"
BAD = FIXTURES / "level_reacquire_bad.sv"

import sys
sys.path.insert(0, str(PROGRAMS))
import pulse_width_rearm_conformance_check as checker  # noqa: E402














def test_run_project_refuses_live_replacement_before_publishing_pass(tmp_path, monkeypatch):
    """A post-measurement source/RTL replacement must invalidate the receipt."""
    project = tmp_path / "project"
    (project / "phase1/input_prompt").mkdir(parents=True)
    rtl_dir = project / "phase2/stage1/rtl"
    rtl_dir.mkdir(parents=True)
    (project / "phase1/input_prompt/contract.json").write_bytes(CONTRACT.read_bytes())
    rtl = rtl_dir / "pulse_width_rearm_fixture.sv"
    rtl.write_bytes(GOOD.read_bytes())
    report_path = project / "reports/phase2/gates/pulse.json"
    source = project / "phase1/input_prompt/contract.json"
    original_source = source.read_bytes()
    original_source_hash = hashlib.sha256(original_source).hexdigest()
    original_hash = hashlib.sha256(rtl.read_bytes()).hexdigest()
    replacement_source = original_source.replace(b'"max_width_cycles": 4',
                                                  b'"max_width_cycles": 5')

    def replace_after_measurement(*args, **kwargs):
        source.write_bytes(replacement_source)
        rtl.write_bytes(BAD.read_bytes())
        return 0, {
            "verdict": "PASS", "measured": True,
            "source_file_sha256": original_source_hash,
            "rtl_sha256": original_hash,
            "context_sha256": {},
            "contract": {"source_sha256": original_source_hash},
            "stimulus": {"tb_sha256": "frozen-stimulus"},
        }

    monkeypatch.setattr(checker, "run_check", replace_after_measurement)
    rc, report = checker.run_project(
        project, [rtl], "pulse_width_rearm_fixture", report_path=report_path,
        runtime_identity={"container": "normal-test-image"})
    assert rc != 0
    assert report["verdict"] == "NOT_MEASURED"
    assert report["measured"] is False
    assert "changed" in report["reason"].lower() or "stable" in report["reason"].lower()
    assert report["source_file_sha256"] == original_source_hash
    assert report["source_contract_sha256"] == original_source_hash
    assert report["rtl_sha256"] == original_hash
    assert report["rtl_file_sha256"][str(rtl)] == original_hash
    assert report_path.is_file()
    published = json.loads(report_path.read_text())
    assert published["verdict"] == "NOT_MEASURED"
    assert published["source_contract_sha256"] == original_source_hash
    assert published["rtl_sha256"] == original_hash


def test_run_project_measured_fail_survives_publication_drift(tmp_path, monkeypatch):
    project = tmp_path / "project"
    (project / "phase1/input_prompt").mkdir(parents=True)
    rtl_dir = project / "phase2/stage1/rtl"
    rtl_dir.mkdir(parents=True)
    source = project / "phase1/input_prompt/contract.json"
    source.write_bytes(CONTRACT.read_bytes())
    rtl = rtl_dir / "pulse_width_rearm_fixture.sv"
    rtl.write_bytes(GOOD.read_bytes())
    original_source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    original_rtl_hash = hashlib.sha256(rtl.read_bytes()).hexdigest()
    replacement_source = source.read_bytes().replace(b'"max_width_cycles": 4',
                                                      b'"max_width_cycles": 5')

    def measured_fail_then_drift(*args, **kwargs):
        source.write_bytes(replacement_source)
        rtl.write_bytes(BAD.read_bytes())
        return 1, {
            "verdict": "FAIL", "measured": True, "reason": "measured pulse violation",
            "source_file_sha256": original_source_hash,
            "rtl_sha256": original_rtl_hash, "context_sha256": {},
            "contract": {"source_sha256": original_source_hash},
            "stimulus": {"tb_sha256": "frozen-stimulus"},
        }

    monkeypatch.setattr(checker, "run_check", measured_fail_then_drift)
    report_path = project / "reports/phase2/gates/pulse.json"
    rc, report = checker.run_project(
        project, [rtl], "pulse_width_rearm_fixture", report_path=report_path)
    assert rc == 1
    assert report["verdict"] == "FAIL"
    assert report["measured"] is True
    assert report["input_stability"]["stable"] is False
    assert "drift" in report["reason"]
    assert json.loads(report_path.read_text())["verdict"] == "FAIL"
