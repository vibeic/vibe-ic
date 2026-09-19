"""Focused L24 DRC engine-set contract tests using neutral input prose."""
from __future__ import annotations

import json
from pathlib import Path

from l24_signoff_evidence_backed_check import main as gate_main
from l24_signoff_requirements_extract import extract_signoff_requirements


_INPUT = (
    "# Physical Verification\n"
    "The design requires DRC clean with both Magic and KLayout; "
    "both engines must pass.\n"
)


def _project(tmp_path: Path, *, klayout: bool) -> Path:
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
    (project / "reports" / "phase3" / "drc_magic.json").write_text(
        '{"program":"magic_drc","passed":true}'
    )
    if klayout:
        (project / "reports" / "phase3" / "drc_klayout.json").write_text(
            '{"program":"klayout_drc","passed":true}'
        )
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
