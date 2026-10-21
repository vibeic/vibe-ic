"""Issue #3408: preserve explicit negative reliability facts in L25."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import phase1_post_process as post  # noqa: E402
import phase1_doc_one_shot_runner as runner  # noqa: E402


def _project(tmp_path: Path, text: str) -> Path:
    docs = tmp_path / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "reliability.md").write_text(text, encoding="utf-8")
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "ic_class.json").write_text(
        json.dumps({"ic_class": "crypto_accelerator"}), encoding="utf-8")
    return tmp_path


def _emit(project: Path) -> dict:
    return post.emit_l_doc_skeleton("L25", project_dir=project)


def _run_gate(project: Path) -> subprocess.CompletedProcess[str]:
    out = project / "phase1" / "generated_docs"
    out.mkdir(parents=True, exist_ok=True)
    (out / "L25_RELIABILITY_MISSION_PROFILE.json").write_text(
        json.dumps(_emit(project), indent=2), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(PROGRAMS / "l25_reliability_envelope_actionable_check.py"),
         str(project)], text=True, capture_output=True, check=False)


def test_explicit_negative_status_and_obligations_are_source_bound(tmp_path):
    project = _project(tmp_path, (
        "The TT/SS/FF points are discrete analysis points, not a qualification "
        "of a continuous voltage/temperature range.\n"
        "IR/EM/ESD verification and current-capacity acceptance remain "
        "unmeasured obligations.\n"))
    doc = _emit(project)
    assert doc["extraction_status"] == "EXTRACTED"
    fields = doc["fields"]
    assert fields["qualification_status"]["status"] == "NOT_ESTABLISHED"
    assert [r["subject"] for r in fields["unmeasured_obligations"]] == [
        "EM", "ESD", "current_capacity"]
    assert fields["temp_range"] is None
    assert fields["em_budget"] is None
    assert doc["source_documents"] == ["input/docs/reliability.md"]
    result = _run_gate(project)
    assert result.returncode == 0, result.stdout + result.stderr


def test_pvt_table_without_continuous_envelope_claim_stays_numerically_empty(tmp_path):
    project = _project(tmp_path, (
        "| point | voltage | temperature |\n"
        "| TT | 1.8 V | 25 C |\n"
        "| SS | 1.6 V | 100 C |\n"
        "| FF | 1.95 V | -40 C |\n"))
    doc = _emit(project)
    assert doc["extraction_status"] == "DECLARED_ABSENT_FROM_INPUT"
    assert doc["fields"]["temp_range"] is None
    assert doc["fields"]["qualification_status"] is None


def test_deleting_negative_words_yields_no_extracted_status(tmp_path):
    project = _project(tmp_path, (
        "The qualification programme discusses EM, ESD and current capacity.\n"))
    doc = _emit(project)
    assert doc["extraction_status"] == "NOT_YET_EXTRACTED"
    assert doc["fields"]["qualification_status"] is None
    assert doc["fields"]["unmeasured_obligations"] == []


def test_generic_reliability_sentence_is_not_a_measurement(tmp_path):
    project = _project(tmp_path, "Reliability is considered by the design.\n")
    doc = _emit(project)
    assert doc["extraction_status"] == "NOT_YET_EXTRACTED"
    assert all(doc["fields"][k] in (None, []) for k in (
        "mission_profile", "temp_range", "qual_standard", "em_budget",
        "aging_margin", "qualification_status", "unmeasured_obligations"))


def test_security_qualification_does_not_cross_into_l25(tmp_path):
    project = _project(tmp_path, (
        "This decision establishes no measured performance or security "
        "qualification.\nReliability is considered separately.\n"))
    doc = _emit(project)
    assert doc["extraction_status"] == "NOT_YET_EXTRACTED"
    assert doc["fields"]["qualification_status"] is None


def test_altered_cited_literal_fails_consumer(tmp_path):
    project = _project(tmp_path, (
        "These points are not a qualification of a continuous temperature range.\n"))
    doc = _emit(project)
    doc["extraction_evidence"]["input/docs/reliability.md"][0]["literal"] = (
        "These points are not a qualification of a different temperature range.")
    doc["evidence"] = doc["extraction_evidence"]
    out = project / "phase1" / "generated_docs"
    out.mkdir(parents=True)
    (out / "L25_RELIABILITY_MISSION_PROFILE.json").write_text(
        json.dumps(doc), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(PROGRAMS / "l25_reliability_envelope_actionable_check.py"),
         str(project)], text=True, capture_output=True, check=False)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "not occur in the file" in result.stdout


def test_real_l24_l27_bridge_preserves_negative_evidence_for_consumer(tmp_path):
    """The canonical producer bridge must not erase extractor evidence.

    ``emit_l_doc_skeleton`` returns both the negative L25 fields and their
    source map.  The L24-L27 bridge historically passed an empty evidence map
    to the common writer, so the final file kept the claims but lost the proof
    and the real structural consumer returned rc=1.  Exercise that bridge,
    then mutate the cited input to prove the consumer is reading it.
    """
    source = (
        "The TT/SS/FF points are discrete analysis points, not a qualification "
        "of a continuous voltage/temperature range.\n"
        "IR/EM/ESD verification and current-capacity acceptance remain "
        "unmeasured obligations.\n")
    project = _project(tmp_path, source)

    produced = runner._emit_l24_to_l27_docs(project)
    assert any(r.path.name == "L25_RELIABILITY_MISSION_PROFILE.json"
               for r in produced)
    final = json.loads((project / "phase1" / "generated_docs"
                        / "L25_RELIABILITY_MISSION_PROFILE.json").read_text())
    assert final["extraction_evidence"], final

    accepted = subprocess.run(
        [sys.executable,
         str(PROGRAMS / "l25_reliability_envelope_actionable_check.py"),
         str(project)], text=True, capture_output=True, check=False)
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr

    (project / "input" / "docs" / "reliability.md").write_text(
        "The source was replaced after extraction.\n", encoding="utf-8")
    stale = subprocess.run(
        [sys.executable,
         str(PROGRAMS / "l25_reliability_envelope_actionable_check.py"),
         str(project)], text=True, capture_output=True, check=False)
    assert stale.returncode == 1, stale.stdout + stale.stderr
    assert "not occur in the file" in stale.stdout

