"""Named L7 scenarios reach the L10 consumer with source-bound expectations."""
import json
from pathlib import Path

import pytest
import phase1_doc_one_shot_runner as producer

FIXTURE = Path(__file__).parent / "fixtures/phase1_local/l7_named_scenarios/L7_verification_plan.md"


def emit(project, text, name="L7_verification_plan.md"):
    result = producer.gen_l10_test_cases(project, {name: text}, {})
    return json.loads(result.path.read_text())


def test_named_scenarios_reach_l10_with_complete_expectations_and_lines(tmp_path):
    text = FIXTURE.read_text()
    doc = emit(tmp_path, text)
    cases = doc["test_cases"]
    assert [row["name"] for row in cases] == ["reset_count", "read_back", "probe_override"]
    assert [row["expected"] for row in cases] == [
        "count_o == 0.", "read_data == write_data.", "observed_count mirrors supplied_count."]
    assert [row["source_line"] for row in cases] == [3, 5, 7]
    assert all(row["source"] == FIXTURE.name for row in cases)
    assert all(row["stimulus"] != row["expected"] for row in cases)
    assert doc["no_test_cases_in_input"] is False
    refused = doc["verification_intent_refusals"]
    assert [(row["name"], row["source_line"]) for row in refused] == [("masking", 9)]
    assert refused[0]["reason_code"] == "SCENARIO_EXPECTATION_NOT_STATED"
    assert "simultaneous masked writes and arbitration" in refused[0]["sentence"]


@pytest.mark.parametrize("body", [
    "exercise a transfer.",
    "drive request high; check TBD.",
    "drive request high; expected: PASS.",
    "check response == 1.",
])
def test_ambiguous_scenario_is_refused_with_its_source(tmp_path, body):
    doc = emit(tmp_path, f"# Verification\n\n1. **transfer** — {body}\n")
    assert doc["test_cases"] == []
    assert doc["no_test_cases_in_input"] is True
    refused = doc["verification_intent_refusals"]
    assert len(refused) == 1
    assert refused[0]["source"] == "L7_verification_plan.md"
    assert refused[0]["source_line"] == 3
    assert refused[0]["sentence"] == body


def test_source_scope_and_fences_do_not_lend_verification_authority(tmp_path):
    text = "1. **valid** — drive request high; check response == 1.\n"
    assert emit(tmp_path / "architecture", text, "L2_architecture.md")["test_cases"] == []
    assert emit(tmp_path / "example", "```text\n" + text + "```\n")["test_cases"] == []


def test_following_prose_cannot_supply_a_missing_expectation(tmp_path):
    text = ("1. **unfinished** — exercise the request path.\n"
            "Unrelated prose.\n  Check response == 1.\n")
    doc = emit(tmp_path, text)
    assert doc["test_cases"] == []
    assert len(doc["verification_intent_refusals"]) == 1


def test_conflicting_named_scenarios_are_refused_instead_of_first_wins(tmp_path):
    text = ("1. **duplicate** — drive request high; check response == 1.\n"
            "2. **duplicate** — drive request high; check response == 0.\n")
    doc = emit(tmp_path, text)
    assert doc["test_cases"] == []
    assert [row["source_line"] for row in doc["verification_intent_refusals"]] == [1, 2]
    assert all(row["reason_code"] == "AMBIGUOUS_SCENARIO_NAME"
               for row in doc["verification_intent_refusals"])


def test_expected_clause_is_consumed_as_a_functional_oracle(tmp_path):
    from l10_test_case_oracle_anchor_check import audit
    doc = emit(tmp_path, "1. **request_ack** — drive request high; check ack == 1.\n")
    assert len(doc["test_cases"]) == 1
    path = tmp_path / "phase1/generated_docs/L10_TEST_CASES.json"
    report = audit(path, path.parent)
    assert report["summary"]["cases_executable"] == 1, report
    assert report["summary"]["cases_anchored"] == 1, report
    assert not [row for row in report["findings"] if row["severity"] == "ERROR"], report
