from __future__ import annotations

import json
from pathlib import Path

from programs import phase1_doc_one_shot_runner as producer
from programs import phase2_scaffold_gen as scaffold


FIXTURE = (Path(__file__).parent / "fixtures" / "phase1_local" /
           "opentitan_aes" / "l10_verification_shall.txt")


def _emit(tmp_path: Path, text: str) -> dict:
    result = producer.gen_l10_test_cases(
        tmp_path, {"verification_plan.md": text}, {"opcodes": []})
    return json.loads(result.path.read_text())


def test_intake_fixture_preserves_four_unresolved_obligations(tmp_path):
    doc = _emit(tmp_path, FIXTURE.read_text())
    obligations = doc["test_obligations"]
    assert [row["statement"] for row in obligations] == FIXTURE.read_text().splitlines()
    assert [row["source_line"] for row in obligations] == [1, 2, 3, 4]
    assert all(row["source"] == "verification_plan.md" for row in obligations)
    assert all(row["oracle_status"] == "UNRESOLVED_FROM_INPUT"
               for row in obligations)
    assert all(set(row).isdisjoint({"stimulus", "expected", "status",
                                    "coverage", "coverage_percent"})
               for row in obligations)
    assert doc["test_cases"] == []
    assert doc["no_test_cases_in_input"] is True
    assert doc["no_test_obligations_in_input"] is False


def test_imperative_shape_is_chip_agnostic(tmp_path):
    doc = _emit(tmp_path, "Tests must cover arbitration loss.\n")
    assert [row["statement"] for row in doc["test_obligations"]] == [
        "Tests must cover arbitration loss."]


def test_imperative_sentence_after_same_line_context_is_preserved(tmp_path):
    text = (
        "The endpoint returns to idle after reset. Verification shall exercise "
        "reset interruption, withheld clocks, and delayed responses.\n"
    )
    doc = _emit(tmp_path, text)
    assert [row["statement"] for row in doc["test_obligations"]] == [
        "Verification shall exercise reset interruption, withheld clocks, "
        "and delayed responses."]
    assert doc["test_obligations"][0]["source_line"] == 1


def test_descriptive_and_negated_prose_do_not_create_obligations(tmp_path):
    text = (
        "The verification team exercises reset weekly.\n"
        "Verification shall not exercise the retired debug path.\n"
        "Verification of delayed responses is not required.\n"
    )
    doc = _emit(tmp_path, text)
    assert doc["test_obligations"] == []
    assert doc["no_test_obligations_in_input"] is True


def test_negative_behavior_is_still_a_positive_test_obligation(tmp_path):
    sentence = "Verification must verify no response before wake-up."
    doc = _emit(tmp_path, sentence + "\n")
    assert [row["statement"] for row in doc["test_obligations"]] == [sentence]


def test_existing_oracled_table_stays_a_test_case_only(tmp_path):
    text = (
        "| Test | Input | Expected |\n"
        "|---|---|---|\n"
        "| transfer | req=1 | ack=1 |\n"
    )
    doc = _emit(tmp_path, text)
    assert len(doc["test_cases"]) == 1
    assert doc["test_obligations"] == []


def test_phase2_catalog_consumes_obligation_statement_without_execution_claim():
    statement = "Verification shall exercise withheld clocks."
    text = scaffold.emit_compliance_vectors(
        {"test_cases": [], "test_obligations": [{
            "statement": statement,
            "oracle_status": "UNRESOLVED_FROM_INPUT",
        }]}, {}, {})
    assert f"L10: {statement}" in text
    assert "PASS" not in text
