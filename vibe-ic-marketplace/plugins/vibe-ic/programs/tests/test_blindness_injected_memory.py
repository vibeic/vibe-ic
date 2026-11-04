import json
from pathlib import Path

import pytest

import blindness_audit as audit


MEMORY = (
    "You have access to a memory folder with guidance from prior runs.\n"
    "========= MEMORY_SUMMARY BEGINS =========\n"
    "A previous project used a different implementation.\n"
    "========= MEMORY_SUMMARY ENDS ========="
)


def message(role, content, native=True):
    body = {"type": "message", "role": role, "content": content}
    return {"type": "response_item", "payload": body} if native else body


@pytest.mark.parametrize("native", [True, False])
@pytest.mark.parametrize("content", [MEMORY, [{"type": "input_text", "text": MEMORY}]])
def test_injected_historical_memory_refuses(native, content):
    record = message("developer", content, native)
    findings = audit.audit_text(json.dumps(record), Path("/visible-inputs"), [], "actor.jsonl")
    assert len(findings) == 1
    assert findings[0]["kind"] == "injected-historical-memory"
    assert findings[0]["transcript"] == "actor.jsonl"
    assert findings[0]["line"] == 1


@pytest.mark.parametrize("record", [
    message("developer", "Use only the current visible design input."),
    message("developer", "The scanner recognizes MEMORY_SUMMARY BEGINS and MEMORY_SUMMARY ENDS."),
    message("developer", "You have access to a memory folder is a forbidden-history example."),
    message("user", MEMORY),
    message("assistant", MEMORY),
    {"type": "function_call_output", "call_id": "native-1", "output": MEMORY},
    {"type": "event_msg", "payload": {"role": "developer", "content": MEMORY}},
    message("developer", 'Documentation only: "You have access to a memory folder", '
            '"MEMORY_SUMMARY BEGINS", and "MEMORY_SUMMARY ENDS" are detector marker names.'),
    message("developer", 'Documentation only: "You have access to a memory folder", '
            '"MEMORY_SUMMARY BEGINS", and "MEMORY_SUMMARY ENDS" are detector marker names.', False),
    message("developer", [{"type": "input_text", "text": 'Documentation only: '
            '"You have access to a memory folder", "MEMORY_SUMMARY BEGINS", '
            'and "MEMORY_SUMMARY ENDS" are detector marker names.'}]),
    message("developer", "You have access to a memory folder is a marker name.\n"
            "========= MEMORY_SUMMARY ENDS =========\n"
            "This documentation intentionally reverses the marker order.\n"
            "========= MEMORY_SUMMARY BEGINS ========="),
    message("developer", [{"type": "input_text", "text": "Documentation: You have access to a memory folder"},
            {"type": "input_text", "text": "MEMORY_SUMMARY BEGINS"},
            {"type": "input_text", "text": "MEMORY_SUMMARY ENDS"}]),
])
def test_current_context_and_quoted_or_returned_examples_stay_clean(record):
    assert audit.audit_text(json.dumps(record), Path("/visible-inputs"), [], "actor.jsonl") == []


def test_memory_in_later_native_record_keeps_actual_line():
    clean = message("developer", "Current design instructions.")
    contaminated = message("developer", [{"type": "input_text", "text": MEMORY}])
    text = "\n".join(json.dumps(row) for row in [clean, contaminated])
    findings = audit.audit_text(text, Path("/visible-inputs"), [], "actor.jsonl")
    assert [row["line"] for row in findings] == [2]
