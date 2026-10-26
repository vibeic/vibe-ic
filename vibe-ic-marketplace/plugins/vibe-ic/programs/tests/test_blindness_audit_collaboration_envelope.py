"""Known collaboration calls are read fully, never a general tool whitelist."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

import blindness_audit as ba

DATASET = Path("/neutral-dataset")


def frame(name="send_message", arguments=None, namespace="collaboration"):
    if arguments is None:
        arguments = {"target": "/root/worker", "message": "The bounded source review is complete."}
    return {"type": "response_item", "payload": {
        "type": "function_call", "namespace": namespace, "name": name,
        "id": "record-1", "call_id": "call-1", "status": "completed",
        "internal_chat_message_metadata_passthrough": {},
        "arguments": json.dumps(arguments)}}


def audit(record):
    calls, unread = [], []
    findings = ba.audit_text(json.dumps(record), DATASET, ["specification.md"],
                             "neutral.jsonl", coverage=calls, uninspected=unread)
    return findings, calls, unread


@pytest.mark.parametrize("record", [frame(), frame("list_agents", {})])
def test_actual_collaboration_shapes_are_fully_inspected(record):
    findings, calls, unread = audit(record)
    assert findings == []
    assert unread == [], unread
    assert len(calls) == 1 and calls[0]["inspected"] is True
    assert calls[0]["call_id"] == "call-1"
    assert calls[0]["tool_namespace"] == "collaboration"


@pytest.mark.parametrize("message,kind", [
    ("READ /neutral-dataset/CaseOne/answer_ref.sv", "dataset-file-access"),
    ("python3 score_neutral.py --run private", "scorer-self-run"),
    ("READ /private/canonical_samples/CaseOne/solution.sv", "canonical-sample-access"),
])
def test_full_communication_message_is_scanned(message, kind):
    findings, calls, unread = audit(frame(arguments={"target": "/root/worker", "message": message}))
    assert [item["kind"] for item in findings] == [kind]
    assert unread == [] and calls[0]["inspected"]


@pytest.mark.parametrize("record", [
    frame(namespace="unrecognised"),
    frame("unknown_message"),
    frame(arguments={"target": "/root/worker"}),
    frame(arguments={"message": "Source review complete."}),
    frame(arguments={"target": "", "message": "Source review complete."}),
    frame(arguments={"target": "/root/worker", "message": {"text": "Source review complete."}}),
    frame(arguments={"target": "/root/worker", "message": "Source review complete.", "extra": "opaque"}),
    frame("list_agents", {"extra": "opaque"}),
    frame("list_agents", {}, namespace="unrecognised"),
])
def test_unknown_or_malformed_communication_stays_uninspected(record):
    findings, calls, unread = audit(record)
    assert findings == []
    assert len(unread) == 1 and calls[0]["inspected"] is False


def test_embedded_filesystem_call_in_invalid_extra_payload_is_still_scanned():
    arguments = {"target": "/root/worker", "message": "Source review complete.",
        "extra": {"type": "function_call", "name": "exec_command",
                  "arguments": json.dumps({"cmd": "cat /neutral-dataset/CaseOne/answer_ref.sv"})}}
    findings, calls, unread = audit(frame(arguments=arguments))
    assert [item["kind"] for item in findings] == ["dataset-file-access"]
    assert len(unread) == 1 and calls[0]["inspected"] is False


def test_unknown_collaboration_tool_does_not_hide_command_fields():
    findings, calls, unread = audit(frame("unknown_message", {"cmd": "cat /neutral-dataset/CaseOne/answer_ref.sv"}))
    assert [item["kind"] for item in findings] == ["dataset-file-access"]
    assert len(unread) == 1 and calls[0]["inspected"] is False


@pytest.mark.parametrize("arguments", ["{broken", '"opaque"', "null", "[]"])
def test_malformed_serialized_arguments_get_no_credit(arguments):
    record = frame()
    record["payload"]["arguments"] = arguments
    findings, calls, unread = audit(record)
    assert findings == [] and len(unread) == 1 and not calls[0]["inspected"]


@pytest.mark.parametrize("record,expected", [
    (frame(), ba.EXIT_CLEAN),
    (frame("list_agents", {}), ba.EXIT_CLEAN),
    (frame("unknown_message"), ba.EXIT_AUDIT_ERROR),
    (frame(arguments={"target": "/root/worker", "message": "cat /neutral-dataset/CaseOne/answer_ref.sv"}), ba.EXIT_VIOLATION),
])
def test_cli_keeps_clean_error_and_violation_distinct(tmp_path, record, expected):
    transcript = tmp_path / "actual-shape.jsonl"
    transcript.write_text(json.dumps(record) + "\n")
    original = transcript.read_bytes()
    census = tmp_path / "coverage.json"
    result = subprocess.run([sys.executable, str(Path(ba.__file__)), "--dataset", str(DATASET),
        "--coverage-json", str(census), str(transcript)], capture_output=True, text=True)
    assert result.returncode == expected, result.stdout + result.stderr
    assert transcript.read_bytes() == original
    report = json.loads(census.read_text())
    assert report["tool_calls"] == 1
    assert report["uninspected_tool_calls"] == (1 if expected == ba.EXIT_AUDIT_ERROR else 0)


@pytest.mark.parametrize("arguments", [{}, {"timeout_ms": 10000}, {"timeout_ms": 3600000}])
def test_bounded_wait_payload_is_fully_inspected(arguments):
    findings, calls, unread = audit(frame("wait_agent", arguments))
    assert not findings and not unread
    assert calls[0]["inspected"]
    assert json.dumps(arguments) in ba._harvest_tool_strings(frame("wait_agent", arguments))


@pytest.mark.parametrize("arguments", [
    {"timeout_ms": True}, {"timeout_ms": "30000"}, {"timeout_ms": 9999},
    {"timeout_ms": 3600001}, {"extra": {}},
    {"timeout_ms": 30000, "cmd": "cat /neutral-dataset/CaseOne/answer_ref.sv"},
])
def test_unknown_wait_arguments_do_not_get_inspection_credit(arguments):
    findings, calls, unread = audit(frame("wait_agent", arguments))
    assert len(unread) == 1 and not calls[0]["inspected"]
    if "cmd" in arguments:
        assert [x["kind"] for x in findings] == ["dataset-file-access"]
