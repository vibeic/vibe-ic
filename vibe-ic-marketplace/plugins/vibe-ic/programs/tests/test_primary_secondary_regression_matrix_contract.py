"""Focused L22 producer/consumer contract tests.

The fixture is neutral prose: it carries no design, PDK, oracle, or harness.
"""
from __future__ import annotations

import json
from pathlib import Path

import phase1_post_process as producer
import l22_verification_plan_measurable_check as consumer
from l22_verification_plan_measurable_check import inspect


_INPUT = """
| Level | size | sign-off scope |
| Primary (required) | 32 | all corners + full quality metrics + functional 100% |
| Secondary (optional) | 8 / 16 | functional 100% only; does not block physical acceptance |
"""


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / "phase1" / "input_doc").mkdir(parents=True)
    (project / "phase1" / "generated_docs").mkdir(parents=True)
    (project / "phase1" / "input_doc" / "plan.txt").write_text(_INPUT)
    return project


def _emit(project: Path) -> Path:
    doc = producer.emit_l_doc_skeleton(
        "L22", "digital_arithmetic_primitive", project_dir=project)
    path = project / "phase1" / "generated_docs" / "L22_VERIFICATION_PLAN.json"
    path.write_text(json.dumps(doc))
    return path


def test_producer_projects_primary_and_optional_secondary(tmp_path: Path) -> None:
    project = _project(tmp_path)
    path = _emit(project)
    matrix = json.loads(path.read_text())["fields"]["regression_matrix"]
    rows = matrix["rows"]
    assert {r["width"] for r in rows if r["level"] == "primary"} == {32}
    secondary = [r for r in rows if r["level"] == "secondary"]
    assert {r["width"] for r in secondary} == {8, 16}
    assert all(r["required"] is False for r in secondary)
    assert all(r["physical_signoff_required"] is False for r in secondary)
    report = inspect(project)
    assert not any(f["id"].startswith("REGRESSION_")
                   for f in report["blocking_findings"])


def test_consumer_rejects_missing_primary_relation(tmp_path: Path) -> None:
    project = _project(tmp_path)
    path = _emit(project)
    doc = json.loads(path.read_text())
    doc["fields"]["regression_matrix"] = {}
    path.write_text(json.dumps(doc))
    report = inspect(project)
    assert any(f["id"] == "REGRESSION_MATRIX_MISSING"
               for f in report["blocking_findings"])


def test_consumer_rejects_secondary_physical_requirement(tmp_path: Path) -> None:
    project = _project(tmp_path)
    path = _emit(project)
    doc = json.loads(path.read_text())
    doc["fields"]["regression_matrix"]["rows"][1]["required"] = True
    path.write_text(json.dumps(doc))
    report = inspect(project)
    assert any(f["id"] == "REGRESSION_SECONDARY_BLOCKS_PHYSICAL"
               for f in report["blocking_findings"])


def test_matrix_ignores_historical_and_wrong_domain_rows(tmp_path: Path) -> None:
    project = _project(tmp_path)
    (project / "phase1" / "input_doc" / "plan.txt").write_text(
        _INPUT
        + "Historical primary baseline | 64 | archived only |\n"
        + "| Primary clock target | 48 | timing domain only |\n"
        + "Secondary is not required for physical sign-off.\n",
        encoding="utf-8",
    )
    doc = producer.emit_l_doc_skeleton("L22", "spm", project_dir=project)
    rows = doc["fields"]["regression_matrix"]["rows"]
    assert [(r["level"], r["width"]) for r in rows] == [
        ("primary", 32), ("secondary", 8), ("secondary", 16)
    ]
    assert consumer._input_width_regression_claims(project) == [
        {"level": "primary", "width": 32},
        {"level": "secondary", "width": 8},
        {"level": "secondary", "width": 16},
    ]
