"""Recognize only the supported metadata schema; still inspect invalid calls."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

import blindness_audit as audit


def _frame(arguments, envelope):
    call = {"type": "function_call", "namespace": "collaboration",
            "name": "list_agents", "arguments": json.dumps(arguments)}
    if envelope == "response":
        return {"type": "response_item", "payload": call}
    if envelope == "nested":
        return {"events": [{"record": call}]}
    return call


@pytest.mark.parametrize("envelope", ["direct", "response", "nested"])
@pytest.mark.parametrize("arguments,expected", [
    ({}, audit.EXIT_CLEAN),
    ({"path_prefix": "/root/neutral"}, audit.EXIT_CLEAN),
    ({"path_prefix": ""}, audit.EXIT_CLEAN),
    ({"path_prefix": 2}, audit.EXIT_AUDIT_ERROR),
    ({"path_prefix": None}, audit.EXIT_AUDIT_ERROR),
    ({"path_prefix": {}}, audit.EXIT_AUDIT_ERROR),
    ({"path_prefix": ["/root/neutral"]}, audit.EXIT_AUDIT_ERROR),
    ({"extra": "opaque"}, audit.EXIT_AUDIT_ERROR),
    ({"path_prefix": "/root/neutral", "extra": {}}, audit.EXIT_AUDIT_ERROR),
    ({"path_prefix": {"cmd": "python3 score_neutral.py"}}, audit.EXIT_VIOLATION),
    ({"path_prefix": "/root/neutral", "extra": {
        "cmd": "cat /neutral-dataset/CaseOne/answer_ref.sv"}}, audit.EXIT_VIOLATION),
])
def test_filtered_agent_list_actual_cli(tmp_path, envelope, arguments, expected):
    transcript = tmp_path / "neutral.jsonl"
    transcript.write_text(json.dumps(_frame(arguments, envelope)) + "\n")
    original = transcript.read_bytes()
    coverage = tmp_path / "coverage.json"
    findings = tmp_path / "findings.json"
    proc = subprocess.run([
        sys.executable, str(Path(audit.__file__)), str(transcript),
        "--dataset", "/neutral-dataset", "--json", str(findings),
        "--coverage-json", str(coverage),
    ], capture_output=True, text=True)
    assert proc.returncode == expected, proc.stdout + proc.stderr
    assert transcript.read_bytes() == original
    report = json.loads(coverage.read_text())
    assert report["tool_calls"] == 1
    valid = (arguments == {} or (set(arguments) == {"path_prefix"}
                                and isinstance(arguments["path_prefix"], str)))
    assert report["inspected_tool_calls"] == int(valid)
    assert report["uninspected_tool_calls"] == int(not valid)
    observed = json.loads(findings.read_text())
    if expected == audit.EXIT_VIOLATION:
        assert observed
    else:
        assert observed == []


def test_filtered_agent_list_requires_collaboration_namespace():
    record = _frame({"path_prefix": "/root/neutral"}, "direct")
    record["namespace"] = "unknown"
    assert audit._collaboration_inspection_credit(record) is False
