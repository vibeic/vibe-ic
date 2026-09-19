"""Focused L24 DRC engine-set contract tests using neutral input prose."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path

from l24_signoff_evidence_backed_check import main as gate_main
from l24_signoff_requirements_extract import extract_signoff_requirements


_INPUT = (
    "# Physical Verification\n"
    "The design requires DRC clean with both Magic and KLayout; "
    "both engines must pass.\n"
)


def _write_audit(project: Path, engine: str, *, duplicate: bool = False,
                 wrong_producer: bool = False, stale_hash: bool = False) -> None:
    artifact = project / "reports" / "phase3" / f"native_{engine}.rpt"
    artifact.write_text(
        "<report-database><generator> drc: script = '/pdk/drc.deck'</generator>\n"
        if engine == "klayout" else "[INFO] COUNT: 0\n"
    )
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    producer = "openroad" if wrong_producer else engine
    entry = {"producer": producer, "file": f"reports/phase3/native_{engine}.rpt",
             "is_signoff_deck": not wrong_producer,
             "deck": "/pdk/drc.deck" if engine == "klayout" else None}
    producers = [entry, dict(entry)] if duplicate else [entry]
    if stale_hash:
        digest = "0" * 64
    report = {
        "program": "eda_report_audit:drc", "passed": True,
        "summary": {"producers": producers},
        "subject": {"basis": "content", "items": [
            {"path": f"reports/phase3/native_{engine}.rpt",
             "sha256": digest, "is_file": True}
        ]},
    }
    (project / "reports" / "phase3" / f"drc_{engine}.json").write_text(
        json.dumps(report)
    )


def _project(tmp_path: Path, *, klayout: bool, controls: dict | None = None) -> Path:
    project = tmp_path / "project"
    (project / "input" / "docs").mkdir(parents=True)
    (project / "phase1" / "generated_docs").mkdir(parents=True)
    (project / "reports" / "phase3").mkdir(parents=True)
    (project / "input" / "docs" / "spec.txt").write_text(_INPUT)
    payload = extract_signoff_requirements(project)
    (project / "phase1" / "generated_docs" / "L24_SIGNOFF.json").write_text(
        json.dumps({"doc_id": "L24_SIGNOFF", "fields": payload})
    )
    (project / "reports" / "orchestrator_phase3.json").write_text(
        '{"program":"phase3_one_shot","passed":true}'
    )
    _write_audit(project, "magic", **(controls or {}))
    if klayout:
        _write_audit(project, "klayout")
    return project


def test_producer_records_both_required_drc_engines(tmp_path: Path) -> None:
    project = _project(tmp_path, klayout=False)
    doc = json.loads(
        (project / "phase1" / "generated_docs" / "L24_SIGNOFF.json").read_text()
    )
    row = next(r for r in doc["fields"]["signoff_requirements"]
               if r["check"] == "DRC")
    assert row["engines"] == ["klayout", "magic"]


def test_consumer_rejects_missing_klayout_and_accepts_both(tmp_path: Path) -> None:
    missing = _project(tmp_path / "missing", klayout=False)
    assert gate_main(["gate", str(missing)]) == 1
    complete = _project(tmp_path / "complete", klayout=True)
    assert gate_main(["gate", str(complete)]) == 0


def test_consumer_refuses_untrusted_native_provenance(tmp_path: Path) -> None:
    for name, control in (
        ("duplicate", {"duplicate": True}),
        ("wrong_producer", {"wrong_producer": True}),
        ("stale_hash", {"stale_hash": True}),
    ):
        project = _project(tmp_path / name, klayout=True, controls=control)
        assert gate_main(["gate", str(project)]) == 1
