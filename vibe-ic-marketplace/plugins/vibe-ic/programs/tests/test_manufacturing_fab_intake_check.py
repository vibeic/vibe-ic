#!/usr/bin/env python3
"""Tests for manufacturing_fab_intake_check.py — Step 37 fab intake gate.

Pins the SKIP / WAIVED / PASS / dir-error verdict logic. This gate
requires TWO artefacts (mask set + wafer lot received) — PASS only when
BOTH are present; a single missing file still yields SKIP/WAIVED.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROG = _HERE.parent / "manufacturing_fab_intake_check.py"

_spec = importlib.util.spec_from_file_location(
    "manufacturing_fab_intake_check", _PROG)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

_REQUIRED = ["manufacturing/mask_set_received.json",
             "manufacturing/wafer_lot_received.json"]


def _run(project: Path):
    out = project / "report.json"
    rc = mod.main([str(project), "--json", str(out)])
    rep = json.loads(out.read_text()) if out.is_file() else None
    return rc, rep


def _write(project: Path, rel: str):
    f = project / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"received": True}))


# ----------------------------------------------------------------------
# SKIP — both artefacts missing, no waiver
# ----------------------------------------------------------------------
def test_skip_when_all_missing(tmp_path):
    rc, rep = _run(tmp_path)
    assert rc == 2
    assert rep["verdict"] == "SKIP"
    assert set(rep["missing"]) == set(_REQUIRED)


# ----------------------------------------------------------------------
# SKIP — only ONE of the two present → still missing → SKIP
# ----------------------------------------------------------------------
def test_skip_when_one_of_two_missing(tmp_path):
    _write(tmp_path, _REQUIRED[0])
    rc, rep = _run(tmp_path)
    assert rc == 2
    assert rep["verdict"] == "SKIP"
    assert _REQUIRED[0] in rep["found"]
    assert _REQUIRED[1] in rep["missing"]


# ----------------------------------------------------------------------
# PASS — both artefacts present
# ----------------------------------------------------------------------
def test_pass_when_both_present(tmp_path):
    _write(tmp_path, _REQUIRED[0])
    _write(tmp_path, _REQUIRED[1])
    rc, rep = _run(tmp_path)
    assert rc == 0
    assert rep["verdict"] == "PASS"
    assert rep["missing"] == []


# ----------------------------------------------------------------------
# WAIVED — missing files but step waived
# ----------------------------------------------------------------------
def test_waived_when_step_waived(tmp_path):
    (tmp_path / "waivers.json").write_text(json.dumps({
        "waived_steps": [{
            "id": "manufacturing_fab_intake",
            "ticket": "FAB-7",
            "reason": "fab handles intake tracking externally",
        }]
    }))
    rc, rep = _run(tmp_path)
    assert rc == 0
    assert rep["verdict"] == "WAIVED"
    assert rep["waiver"]["ticket"] == "FAB-7"


# ----------------------------------------------------------------------
# Edge — project dir absent → IO error rc 2
# ----------------------------------------------------------------------
def test_missing_project_dir(tmp_path):
    rc = mod.main([str(tmp_path / "nope")])
    assert rc == 2
