#!/usr/bin/env python3
"""Tests for klayout_deck_mode_check.py (BACKLOG-v10 P0.1 enforcement)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent / "klayout_deck_mode_check.py")


def _run(project_dir: Path) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(PROG), str(project_dir),
           "--json", str(project_dir / "klayout_deck_mode_check.json")]
    return subprocess.run(cmd, capture_output=True, text=True)


def _load(project_dir: Path) -> dict:
    return json.loads(
        (project_dir / "klayout_deck_mode_check.json").read_text())


def _drc_manifest(project_dir: Path, body: dict):
    out = project_dir / "reports"
    out.mkdir(parents=True, exist_ok=True)
    (out / "drc_manifest.json").write_text(json.dumps(body))


def test_no_drc_artefacts_silent(tmp_path):
    """No KLayout DRC artefacts at all → silent."""
    r = _run(tmp_path)
    assert r.returncode == 2


def test_real_drc_pass_silent(tmp_path):
    """DRC manifest reports rules>0 (real deck) → PASS."""
    _drc_manifest(tmp_path, {
        "step": "drc",
        "tool": "KLayout (auto-deck from tech LEF)",
        "deck_mode": "auto_lef",
        "rules": 12,
        "violations": 0,
        "status": "PASS",
    })
    r = _run(tmp_path)
    assert r.returncode == 0


def test_structural_only_no_waiver_fails(tmp_path):
    """Structural-only fallback used + no waiver → ERROR."""
    _drc_manifest(tmp_path, {
        "step": "drc",
        "tool": "KLayout (structural-only fallback)",
        "deck_mode": "structural_only",
        "advisory": "Auto-deck synthesis from tech LEF produced 0 enforceable rules.",
        "status": "STRUCTURAL_PASS",
    })
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _load(tmp_path)
    assert any(f["rule"] == "KLAYOUT_STRUCTURAL_DRC_NEEDS_WAIVER"
               for f in rpt["findings"])


def test_structural_with_waiver_passes(tmp_path):
    """Structural-only + valid waiver → PASS."""
    _drc_manifest(tmp_path, {
        "step": "drc",
        "tool": "KLayout (structural-only fallback)",
        "deck_mode": "structural_only",
        "status": "STRUCTURAL_PASS",
    })
    (tmp_path / "waivers.json").write_text(json.dumps({
        "waivers": [{
            "id": "K01_klayout_structural_only_drc",
            "rationale": "commercial 180nm PDK ships no DRC deck — "
                         "tracking foundry closure ticket A1; production "
                         "tapeout uses Cadence Quantus full deck",
            "approver": "signoff_engineer",
            "review_required": True,
        }]
    }))
    r = _run(tmp_path)
    assert r.returncode == 0


def test_structural_advisory_in_log_caught(tmp_path):
    """Structural fallback evidence in plain *.log file is also caught."""
    log = tmp_path / "drc_klayout.log"
    log.write_text(
        "Auto-deck synthesis from tech LEF produced 0 enforceable rules.\n"
        "Falling back to structural-only deck.\n")
    r = _run(tmp_path)
    assert r.returncode == 1
