"""Regression for #3467: L20 preserves planned/unmeasured intent."""
from __future__ import annotations

import json
from pathlib import Path

from programs import l20_dft_intent_emit as emit

INPUT = """The pre-DFT wrapper is functional only.
DFT remains planned and unmeasured.
Preserve any known scan/test-access interface.
The final producer must reconcile the actual mapped/DFT pad roster.
"""


def _project(tmp_path: Path, text: str = INPUT, *, extracted=False,
             present=False) -> tuple[Path, Path]:
    src = tmp_path / "input" / "docs" / "spec.md"
    src.parent.mkdir(parents=True)
    src.write_text(text)
    l20 = tmp_path / "phase1" / "generated_docs" / emit._L20
    l20.parent.mkdir(parents=True)
    l20.write_text(json.dumps({
        "doc_id": "L20",
        "fields": {"scan_chains": ([{"name": "c0"}] if present else []),
                   "bist_mbist": [], "jtag_tap": None,
                   "dft_present": present,
                   "notes": "Spec does not specify DFT/scan topology."},
        "extraction_status": "EXTRACTED" if extracted else "NOT_YET_EXTRACTED",
        "source_documents": [],
    }))
    return tmp_path, l20


def test_exact_intake_becomes_source_bound_planned_unmeasured(tmp_path):
    project, path = _project(tmp_path)
    rep = emit.run(project)
    doc = json.loads(path.read_text())
    fields = doc["fields"]
    assert rep["status"] == "OK"
    assert doc["extraction_status"] == "PARTIALLY_EXTRACTED"
    assert fields["dft_present"] is None
    assert fields["dft_intent_status"] == "PLANNED_UNMEASURED"
    assert len(fields["planned_obligations"]) == 2
    assert doc["source_documents"] == ["input/docs/spec.md"]


def test_emit_never_invents_topology_or_measurement(tmp_path):
    project, path = _project(tmp_path)
    emit.run(project)
    fields = json.loads(path.read_text())["fields"]
    assert fields["scan_chains"] == []
    for forbidden in ("frequency_mhz", "atpg_coverage", "completed"):
        assert forbidden not in fields


def test_extracted_text_mirror_does_not_duplicate_input_evidence(tmp_path):
    project, path = _project(tmp_path)
    mirror = project / "phase1" / "input_doc" / "spec.txt"
    mirror.parent.mkdir(parents=True)
    mirror.write_text(INPUT)
    emit.run(project)
    doc = json.loads(path.read_text())
    assert doc["source_documents"] == ["input/docs/spec.md"]
    assert len(doc["fields"]["planned_obligations"]) == 2


def test_absent_or_negated_intent_does_not_mutate_skeleton(tmp_path):
    for name, text in {
        "absent": "Functional wrapper only.\nNo implementation plan yet.\n",
        "negated": "No DFT is planned and it remains unmeasured.\n",
    }.items():
        project, path = _project(tmp_path / name, text)
        before = path.read_bytes()
        rep = emit.run(project)
        assert rep["status"] == "SKIPPED"
        assert path.read_bytes() == before


def test_existing_present_topology_is_refused_not_overwritten(tmp_path):
    project, path = _project(tmp_path, extracted=True, present=True)
    before = path.read_bytes()
    rep = emit.run(project)
    assert rep["status"] == "REFUSED"
    assert path.read_bytes() == before


def test_extracted_owner_absence_is_refused_not_reclassified(tmp_path):
    project, path = _project(tmp_path, extracted=True, present=False)
    before = path.read_bytes()
    rep = emit.run(project)
    assert rep["status"] == "REFUSED"
    assert path.read_bytes() == before
