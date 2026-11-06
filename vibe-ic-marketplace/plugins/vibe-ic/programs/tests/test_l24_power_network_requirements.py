"""Source requirements for power connectivity; no measured signoff claims."""
from pathlib import Path
import shutil
import json

import pytest

import l24_signoff_requirements_extract as X
import phase1_post_process as P


FIXTURE = (Path(__file__).parent / "fixtures" / "stage_phase1_on_pass_review"
           / "reject_spm" / "phase1" / "input_doc")


def _project(tmp_path, text):
    docs = tmp_path / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "spec.txt").write_text(text, encoding="utf-8")
    return tmp_path


def _power_row(project):
    payload = X.extract_signoff_requirements(project)
    row = next((r for r in payload["signoff_requirements"]
                if r["check"] == "power_network"), None)
    assert row is not None, payload
    return row


@pytest.mark.parametrize("name,line,text", [
    ("L7_verification_plan.txt", 83,
     "| Power network | 無 disconnected ports |"),
    ("L9_constraints_floorplan.txt", 97,
     "- ✅ Power network 無 disconnected port"),
], ids=["plan", "constraints"])
def test_power_network_source_requirement(tmp_path, name, line, text):
    docs = tmp_path / "input" / "docs"
    docs.mkdir(parents=True)
    shutil.copyfile(FIXTURE / name, docs / name)
    doc = P.emit_l_doc_skeleton("L24", "unknown", project_dir=tmp_path)
    assert doc["applicability"] == "APPLICABLE"
    assert doc["extraction_status"] == "EXTRACTED"
    rows = {r["check"]: r for r in doc["fields"]["signoff_requirements"]}
    row = rows.get("power_network")
    assert row is not None, rows
    assert row["stated"] is True
    assert row["requirement"] == "no_disconnected_ports", row
    assert row["corners"] == []
    assert row["threshold"] is None
    assert row["citation"]["document"] == f"input/docs/{name}"
    assert row["citation"]["line"] == line
    assert row["citation"]["text"] == text
    assert rows["LVS"]["engines"] == ["magic", "netgen"]
    for key in ("drc_status", "lvs_status", "sta_status", "ir_drop_status",
                "antenna_status"):
        assert doc["fields"][key] is None
    assert not {"status", "verdict", "result"}.intersection(row)
    observed = []
    reading = next(r for r in observed if r["check"] == "power_network")
    assert reading["requirement"] == "no_disconnected_ports"
    assert reading["outcome"] == "NOT_YET_MEASURABLE"
    assert reading["records_read"] == []


def test_absent_and_denied_power_network_are_not_requirements(tmp_path):
    for i, text in enumerate([
        "DRC clean is required.",
        "No power network requirement: no disconnected ports is an example.",
        "Power network is not required to have no disconnected ports.",
        "Power network 無 disconnected ports is not required.",
        "Power network clean is not required.",
        "Power network is not applicable.",
    ]):
        project = _project(tmp_path / str(i), "# Signoff\n" + text + "\n")
        row = _power_row(project)
        assert row["stated"] is False, (text, row)
        assert row["requirement"] is None
        assert row["threshold"] is None
        assert row["citation"] is None
        assert row["searched"]["documents"] == ["input/docs/spec.txt"]


def test_power_network_clause_preserves_neighbor_semantics(tmp_path):
    project = _project(tmp_path,
        "# Signoff\n"
        "No LVS check is required; power network shall have no disconnected "
        "ports; STA met. No EM requirement is stated.\n")
    payload = X.extract_signoff_requirements(project)
    rows = {r["check"]: r for r in payload["signoff_requirements"]}
    row = _power_row(project)
    assert row["stated"] is True
    assert row["requirement"] == "no_disconnected_ports", row
    assert "STA" not in row["citation"]["clause"]
    assert rows["STA"]["requirement"] == "met"
    assert X.report_tokens_for("power_network") == ("no_disconnected_ports",)
    unnamed = _project(tmp_path / "unnamed", "Power network is discussed.\n")
    assert _power_row(unnamed)["stated"] is True
    assert _power_row(unnamed)["requirement"] is None
    absent = _project(tmp_path / "absent", "An arithmetic pipeline is described.\n")
    assert P.emit_l_doc_skeleton("L24", "unknown", project_dir=absent)[
        "applicability"] == "NOT_APPLICABLE"


def test_generic_pdn_pass_is_unbacked_and_connectivity_evidence_is_eligible(tmp_path):
    project = _project(tmp_path,
        "Power network shall have no disconnected ports.\n")
    row = _power_row(project)
    report = project / "reports" / "phase3" / "pnr" / "floorplan_pdn.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({
        "program": "floorplan_pdn_check", "gate": "floorplan_pdn",
        "verdict": "PASS", "findings": [],
        "extra": {"pdn_evidence": "DEF POWER/GROUND stripes"},
    }))
    doc = {"fields": {"signoff_requirements": [row]}}
    observed = []
    assert observed[0]["outcome"] == "UNMET_NO_READING", observed
    assert observed[0]["records_read"] == []
    assert row["requirement"] == "no_disconnected_ports"

    # Exercise the existing semantic-name contract through a neutral path;
    # a report's explicit check identity can supply the eligible name.
    corresponding = report.parent / "connectivity.json"
    corresponding.write_text(json.dumps({
        "check": "no_disconnected_ports", "verdict": "PASS",
        "disconnected_ports": [],
    }))
    observed = []
    assert observed[0]["outcome"] == "BACKED", observed
    assert observed[0]["records_read"] == [{
        "path": "reports/phase3/pnr/connectivity.json", "verdict": "pass"}]
