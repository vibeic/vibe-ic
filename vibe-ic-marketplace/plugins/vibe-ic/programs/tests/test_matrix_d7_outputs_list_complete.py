import json

import shutil

import subprocess

import sys

import pytest

def test_step30_actual_refusal_declaration_does_not_pass_its_consumer(tmp_path):
    import spice_correlation_check as producer
    path = "phase3/stage3/spice/spice_correlation_not_run.json"
    producer._write_declared_correlation_refusal(
        tmp_path, "SOURCE_FIXTURE_REFUSED", "Self-authored source refusal; no native execution")
    doc = json.loads((tmp_path / path).read_text())
    assert doc["verdict"] == "NOT_MEASURED" and doc["correlation_ran"] is False
    result = producer.run_audit(tmp_path, run_spice=False)
    assert result.passed is False and result.summary["pass"] is False
    assert result.findings, result

@pytest.mark.parametrize("variant", ("current", "missing-results", "failed-results", "missing-rtl"))
def test_step5_actual_report_writer_preserves_strict_evidence(tmp_path, variant):
    """Actual CLI over the existing public software fixture, without simulation."""
    import test_bit_level_full_stack_tb_check as fixture
    project, rtl, sim = fixture._make_project(tmp_path)
    if variant == "missing-results":
        (sim / "results.json").unlink()
    elif variant == "failed-results":
        data = json.loads((sim / "results.json").read_text())
        data["pass"] = False
        (sim / "results.json").write_text(json.dumps(data))
    elif variant == "missing-rtl":
        shutil.rmtree(rtl)
    path = "reports/phase2/gates/bit_level_full_stack.json"
    proc = subprocess.run([sys.executable, str(fixture.SCRIPT), str(project),
                           "--json", str(project / path)], capture_output=True, text=True)
    (tmp_path / "gate.stdout").write_text(proc.stdout)
    (tmp_path / "gate.stderr").write_text(proc.stderr)
    (tmp_path / "gate.invocation.json").write_text(json.dumps({
        "argv": proc.args, "rc": proc.returncode, "native_execution": False}, indent=2))
    doc = json.loads((project / path).read_text())
    expected = variant == "current"
    assert proc.returncode == (0 if expected else 1), proc.stdout + proc.stderr
    assert doc["pass"] is expected, doc
