"""Focused L24 DRC engine-set contract tests using neutral input prose."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path

from l24_signoff_requirements_extract import extract_signoff_requirements
import _path_layout as PL


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
    netlist = project / "phase2/stage2/synth/netlist_yosys.v"
    netlist.parent.mkdir(parents=True)
    netlist.write_text("module chip; endmodule\n")
    receipt = project / "reports/orchestrator/phase3_one_shot.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(json.dumps({
        "verdict": "PASS",
        "phase2_synth": PL.phase2_synth_input_identity(project),
        "phase3_inputs": PL.phase3_signoff_input_identity(project),
    }))
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
