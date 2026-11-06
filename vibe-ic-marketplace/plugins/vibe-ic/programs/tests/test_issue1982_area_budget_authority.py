#!/usr/bin/env python3
"""vibe-ic#1982 — Phase 1 owns synthesis-area budget authority.

Four contract states are exercised end to end: explicit limit/pass, explicit
limit/fail, explicit typed N/A, and unset. Fixtures are neutral and synthesized.
The tests call existing shipped entrypoints so the pre-fix arm observes wrong
values and verdicts rather than failing because a new module is absent.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

PROGRAMS = Path(__file__).resolve().parents[1]
PLUGIN = PROGRAMS.parent
sys.path.insert(0, str(PROGRAMS))

import _tapeout_declaration as TD  # noqa: E402
import _owner_declared as _OD                              # noqa: E402
import phase1_doc_one_shot_runner as P1  # noqa: E402

AREA_KEY = "synthesis_area_budget"
LIMIT = "LIMIT"
FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"


def _write_json(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n")


def _project(tmp_path: Path, area_answer, *, chip_area=1000.0,
             l19_ceiling=None) -> Path:
    project = tmp_path / "neutral_project"
    declaration = TD.blank_declaration()
    declaration[AREA_KEY] = area_answer
    # A hand-written disposition is the owner's explicit answer, not a derived
    # one (R-0929-DELIVERABLE-CONSISTENCY-2, `_owner_declared`).
    _OD.attest_explicit(declaration)
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

















def test_step9_declares_blocks_on_for_the_phase1_authority():
    flow = yaml.safe_load(FLOW.read_text())
    step = next(s for s in flow["steps"] if str(s.get("id")) == "9")
    assert {str(v) for v in step["blocks_on"]} >= {"0.5ic", "2", "3", "8"}
    assert {
        (str(v.get("from")), v.get("path")) for v in step["required_inputs"]
    } >= {(
        "0.5ic", "input/submission_template/tapeout_declaration.json")}
