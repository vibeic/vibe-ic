#!/usr/bin/env python3
"""Tests for packaging_intake_check.py — Step 39 packaging intake gate.

Pins the SKIP / WAIVED / PASS / dir-error verdict logic:
  * missing required artefact + no waiver  → SKIP (rc 2)
  * missing required artefact + waiver      → WAIVED (rc 0)
  * required artefact present               → PASS (rc 0)
  * project dir absent                      → rc 2 (IO error)
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROG = _HERE.parent / "packaging_intake_check.py"

_spec = importlib.util.spec_from_file_location("packaging_intake_check", _PROG)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

_REQUIRED = "manufacturing/packaging_log.json"


def _run(project: Path):
    out = project / "report.json"
    rc = mod.main([str(project), "--json", str(out)])
    rep = json.loads(out.read_text()) if out.is_file() else None
    return rc, rep


# ----------------------------------------------------------------------
# SKIP — required artefact missing, no waiver
# ----------------------------------------------------------------------
def test_skip_when_required_file_missing(tmp_path):
    rc, rep = _run(tmp_path)
    assert rc == 2
    assert rep["verdict"] == "SKIP"
    assert _REQUIRED in rep["missing"]


# ----------------------------------------------------------------------
# PASS — required artefact present
# ----------------------------------------------------------------------
def test_pass_when_required_file_present(tmp_path):
    f = tmp_path / "manufacturing" / "packaging_log.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"lots": [1, 2, 3]}))
    rc, rep = _run(tmp_path)
    assert rc == 0
    assert rep["verdict"] == "PASS"
    assert rep["missing"] == []
    assert _REQUIRED in rep["found"]


# ----------------------------------------------------------------------
# WAIVED — missing file but waivers.json declares the step waived
# ----------------------------------------------------------------------
def test_waived_when_step_waived(tmp_path):
    (tmp_path / "waivers.json").write_text(json.dumps({
        "waived_steps": [{
            "id": "packaging_intake",
            "ticket": "TKT-101",
            "reason": "packaging deferred to assembly house",
        }]
    }))
    rc, rep = _run(tmp_path)
    assert rc == 0
    assert rep["verdict"] == "WAIVED"
    assert rep["waiver"]["ticket"] == "TKT-101"


def test_waiver_matched_by_ticket_substring(tmp_path):
    # _step_waived also matches if step_label appears in the ticket text.
    (tmp_path / "waivers.json").write_text(json.dumps({
        "waived_steps": [{
            "id": "something_else",
            "ticket": "covers packaging_intake too",
            "reason": "bundled waiver",
        }]
    }))
    rc, rep = _run(tmp_path)
    assert rc == 0
    assert rep["verdict"] == "WAIVED"


# ----------------------------------------------------------------------
# Edge — project dir absent → IO error rc 2
# ----------------------------------------------------------------------
def test_missing_project_dir(tmp_path):
    rc = mod.main([str(tmp_path / "nope")])
    assert rc == 2


def test_malformed_waivers_json_falls_back_to_skip(tmp_path):
    # Garbage waivers.json must not crash; _load_waivers swallows → SKIP.
    (tmp_path / "waivers.json").write_text("{ not valid json")
    rc, rep = _run(tmp_path)
    assert rc == 2
    assert rep["verdict"] == "SKIP"
