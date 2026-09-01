#!/usr/bin/env python3
"""vibe-ic#1982 — Phase 1 owns synthesis-area budget authority.

Four contract states are exercised end to end: explicit limit/pass, explicit
limit/fail, explicit typed N/A, and unset. Fixtures are neutral and synthesized.
The tests call existing shipped entrypoints so the pre-fix arm observes wrong
values and verdicts rather than failing because a new module is absent.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

PROGRAMS = Path(__file__).resolve().parents[1]
PLUGIN = PROGRAMS.parent
sys.path.insert(0, str(PROGRAMS))

import _tapeout_declaration as TD  # noqa: E402
import _submission_template as ST  # noqa: E402
import flow_compliance_check as FCC  # noqa: E402
import phase1_doc_one_shot_runner as P1  # noqa: E402
import phase1_one_shot_runner as PHASE1  # noqa: E402

AREA_KEY = "synthesis_area_budget"
LIMIT = "LIMIT"
NOT_APPLICABLE = "NOT_APPLICABLE"
AREA_GATE = PROGRAMS / "area_total_vs_budget_check.py"
DECL_GATE = PROGRAMS / "tapeout_declaration_check.py"
FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"


def _write_json(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n")


def _project(tmp_path: Path, area_answer, *, chip_area=1000.0,
             l19_ceiling=None) -> Path:
    project = tmp_path / "neutral_project"
    declaration = TD.blank_declaration()
    declaration[AREA_KEY] = area_answer
    _write_json(project / "input/submission_template/tapeout_declaration.json",
                declaration)
    _write_json(project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json", {
        "doc_id": "L19",
        "doc_name": "L19_CONSTRAINTS_PDK",
        "fields": {
            "pdk_target": None,
            "die_area_budget_um": l19_ceiling,
            "power_budget_uw": None,
            "sdc_constraints_path": None,
            "floorplan_hints": [],
            "constraints_present": False,
        },
        "extraction_status": "PARTIALLY_EXTRACTED",
    })
    _write_json(project / "phase2/stage2/synth/stats.json", {
        "schema": "vibe-ic/synth-stats/1",
        "top_module": "neutral_top",
        "chip_area": chip_area,
        "chip_area_unit": "um^2",
        "cell_count": 42,
        "includes_submodules": False,
        "selection": {"rule": "SINGLE_MODULE_NO_HIERARCHY"},
    })
    return project


def _run(program: Path, project: Path, report_rel: str):
    report = project / report_rel
    cp = subprocess.run(
        [sys.executable, str(program), str(project), "--json", str(report)],
        capture_output=True, text=True)
    return cp, json.loads(report.read_text())


def _limit(w=40, h=50):
    return {"status": LIMIT, "max_die_dimensions_um": [w, h]}


def test_explicit_budget_reaches_l19_and_passes_with_units_and_sources(tmp_path):
    project = _project(tmp_path, _limit(), chip_area=1000.0)

    P1._post_emit_floorplan_contract(project)
    l19 = json.loads((project /
                      "phase1/generated_docs/L19_CONSTRAINTS_PDK.json").read_text())
    assert l19["fields"]["die_area_budget_um"] == "40x50"
    evidence = json.dumps(l19.get("extraction_evidence", {}))
    assert "tapeout_declaration.json#/synthesis_area_budget" in evidence

    decl_cp, decl = _run(
        DECL_GATE, project, "reports/phase1/tapeout_declaration.json")
    assert decl_cp.returncode == 0, decl_cp.stdout + decl_cp.stderr
    assert decl["area_budget_authority"]["status"] == LIMIT

    area_cp, area = _run(
        AREA_GATE, project, "reports/phase2/gates/area_budget.json")
    assert area_cp.returncode == 0, area_cp.stdout + area_cp.stderr
    assert area["verdict"] == "PASS"
    comparison = area["comparison"]
    assert comparison["cell_area_um2"] == 1000.0
    assert comparison["cell_area_unit"] == "um^2"
    assert comparison["die_area_um2"] == 2000.0
    assert comparison["die_area_unit"] == "um^2"
    assert comparison["ceiling_source"].endswith(
        "tapeout_declaration.json#/synthesis_area_budget")
    assert comparison["l19_sources"] == [
        "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"]


def test_design_extracted_l19_budget_does_not_need_a_duplicate_answer(tmp_path):
    project = _project(
        tmp_path, TD.NOT_DETERMINED, chip_area=1000.0,
        l19_ceiling="40x50")
    declaration_path = project / TD.DECLARATION_REL
    declaration = json.loads(declaration_path.read_text())
    declaration.pop(AREA_KEY)
    _write_json(declaration_path, declaration)

    decl_cp, decl = _run(
        DECL_GATE, project, "reports/phase1/tapeout_declaration.json")
    assert decl_cp.returncode == 0, decl_cp.stdout + decl_cp.stderr
    authority = decl["area_budget_authority"]
    assert authority["status"] == LIMIT
    assert authority["authority_kind"] == "L19_DESIGN_EXTRACTION"
    assert authority["source"].endswith(
        "L19_CONSTRAINTS_PDK.json#/fields/die_area_budget_um")

    area_cp, area = _run(
        AREA_GATE, project, "reports/phase2/gates/area_budget.json")
    assert area_cp.returncode == 0, area_cp.stdout + area_cp.stderr
    assert area["verdict"] == "PASS"
    assert area["area_budget_authority"]["authority_kind"] == \
        "L19_DESIGN_EXTRACTION"
    assert area["comparison"]["ceiling_source"].endswith(
        "L19_CONSTRAINTS_PDK.json#/fields/die_area_budget_um")


def test_explicit_budget_fails_when_measured_area_exceeds_it(tmp_path):
    project = _project(tmp_path, _limit(), chip_area=3000.0)
    P1._post_emit_floorplan_contract(project)
    cp, report = _run(
        AREA_GATE, project, "reports/phase2/gates/area_budget.json")
    assert cp.returncode == 1, cp.stdout + cp.stderr
    assert report["verdict"] == "FAIL"
    assert [f["rule"] for f in report["findings"]] == [
        "AREA_TOTAL_OVER_DECLARED_DIE"]


def test_explicit_not_applicable_is_typed_cited_and_not_a_pass(tmp_path):
    rationale = "Area is owned by the integrating parent, not this deliverable."
    project = _project(tmp_path, {
        "status": NOT_APPLICABLE,
        "rationale": rationale,
    })

    decl_cp, decl = _run(
        DECL_GATE, project, "reports/phase1/tapeout_declaration.json")
    assert decl_cp.returncode == 0, decl_cp.stdout + decl_cp.stderr
    assert decl["area_budget_authority"] == {
        "status": NOT_APPLICABLE,
        "raw": {"status": NOT_APPLICABLE, "rationale": rationale},
        "rationale": rationale,
    }

    area_cp, area = _run(
        AREA_GATE, project, "reports/phase2/gates/area_budget.json")
    assert area_cp.returncode == 0, area_cp.stdout + area_cp.stderr
    assert area["verdict"] == "NOT_APPLICABLE"
    assert area["area_budget_authority"]["status"] == NOT_APPLICABLE
    assert area["disposition"]["rationale"] == rationale
    assert area["disposition"]["source"].endswith(
        "tapeout_declaration.json#/synthesis_area_budget")
    assert "VACUOUS_PASS: [NOT_APPLICABLE]" in area_cp.stdout


def test_unset_authority_incompletes_phase1_and_blocks_the_comparison(tmp_path):
    project = _project(tmp_path, TD.NOT_DETERMINED)

    decl_cp, decl = _run(
        DECL_GATE, project, "reports/phase1/tapeout_declaration.json")
    assert decl_cp.returncode == 2, decl_cp.stdout + decl_cp.stderr
    assert decl["verdict"] == "INCOMPLETE"
    assert [d["rule"] for d in decl["incomplete_dependencies"]] == [
        "SYNTHESIS_AREA_BUDGET_AUTHORITY_UNSET"]

    area_cp, area = _run(
        AREA_GATE, project, "reports/phase2/gates/area_budget.json")
    assert area_cp.returncode == 2, area_cp.stdout + area_cp.stderr
    assert area["verdict"] == "INCOMPLETE"
    assert "step 0.5ic is INCOMPLETE" in area["missing_authority"]
    assert "L19_CONSTRAINTS_PDK.json fields.die_area_budget_um" in \
        area["missing_authority"]


def test_legacy_absent_field_is_unset_and_never_implicit_na(tmp_path):
    project = _project(tmp_path, TD.NOT_DETERMINED)
    path = project / TD.DECLARATION_REL
    declaration = json.loads(path.read_text())
    declaration.pop(AREA_KEY)
    _write_json(path, declaration)

    decl_cp, decl = _run(
        DECL_GATE, project, "reports/phase1/tapeout_declaration.json")
    assert decl_cp.returncode == 2, decl_cp.stdout + decl_cp.stderr
    assert decl["verdict"] == "INCOMPLETE"
    assert decl["refusals"] == []
    assert decl["area_budget_authority"]["status"] == "UNSET"

    area_cp, area = _run(
        AREA_GATE, project, "reports/phase2/gates/area_budget.json")
    assert area_cp.returncode == 2, area_cp.stdout + area_cp.stderr
    assert area["verdict"] == "INCOMPLETE"
    assert "NOT_APPLICABLE" not in json.dumps(area)


def test_unset_authority_is_executed_as_an_incomplete_flow_clause(tmp_path):
    project = tmp_path / "neutral_flow_project"
    project.mkdir()
    _write_json(project / ST.DESIGN_ANSWERS_REL, {
        "operator_template": {
            "absent_reason": (
                "This design targets no shuttle operator; it is a self "
                "tape-out. No operator project template exists to stage, so "
                "there is no slot geometry, no operator fixture, and no "
                "per-slot pad list for this step to ingest."),
        },
        "answers": {"deliverable": TD.DELIVERABLE_DIE},
        AREA_KEY: TD.NOT_DETERMINED,
    })

    assert PHASE1._run_step_0_5ic(project) == 0
    flow = yaml.safe_load(FLOW.read_text())
    step = next(s for s in flow["steps"] if str(s.get("id")) == "0.5ic")
    result = FCC.check_step(project, step, {})
    report = json.loads((project / TD.REPORT_REL).read_text())
    assert report["verdict"] == "INCOMPLETE"
    assert [d["rule"] for d in report["incomplete_dependencies"]] == [
        "SYNTHESIS_AREA_BUDGET_AUTHORITY_UNSET"]
    assert result.status != "PASS"
    assert any("tapeout_declaration_check" in reason
               for reason in result.reasons)


def test_a_declared_limit_and_a_different_l19_ceiling_conflict(tmp_path):
    project = _project(tmp_path, _limit(), l19_ceiling="50x50")
    cp, area = _run(
        AREA_GATE, project, "reports/phase2/gates/area_budget.json")
    assert cp.returncode == 2, cp.stdout + cp.stderr
    assert area["verdict"] == "INCOMPLETE"
    assert "Phase-1 propagation" in area["missing_authority"]
    assert "40x50" in area["missing_authority"]
    assert "50x50" in area["missing_authority"]


def test_step9_declares_blocks_on_for_the_phase1_authority():
    flow = yaml.safe_load(FLOW.read_text())
    step = next(s for s in flow["steps"] if str(s.get("id")) == "9")
    assert {str(v) for v in step["blocks_on"]} >= {"0.5ic", "2", "3", "8"}
    assert {
        (str(v.get("from")), v.get("path")) for v in step["required_inputs"]
    } >= {(
        "0.5ic", "input/submission_template/tapeout_declaration.json")}
