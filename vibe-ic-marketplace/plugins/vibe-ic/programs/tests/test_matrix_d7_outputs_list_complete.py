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
