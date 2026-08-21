#!/usr/bin/env python3
"""Tests for eco_status_gen.py (v1.6.36 — Step 30 ECO status emitter)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "eco_status_gen.py"


def _run(project: Path):
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _write_sta(project: Path, content: str):
    sta_dir = project / "phase3/stage3/sta"
    sta_dir.mkdir(parents=True, exist_ok=True)
    (sta_dir / "post_route_timing.rpt").write_text(content)


def test_emits_no_eco_flag_when_tns_zero(tmp_path):
    """All-MET STA → no_eco_needed.flag emitted, verdict PASS."""
    _write_sta(tmp_path, "Endpoint reset_n\nslack (MET)\nslack (MET)\n")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert (tmp_path / "phase3/stage3/eco/no_eco_needed.flag").is_file()
    out = json.loads(r.stdout)
    assert out["verdict"] == "PASS"
    assert out["tns_zero"] is True


def test_emits_no_eco_flag_when_tns_explicit_zero(tmp_path):
    """Explicit `tns 0.00` → no_eco_needed.flag emitted."""
    _write_sta(tmp_path, "report_tns\ntns 0.00\nwns 0.05\n")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert (tmp_path / "phase3/stage3/eco/no_eco_needed.flag").is_file()


def test_emits_eco_log_when_tns_negative(tmp_path):
    """STA with VIOLATED + no MET → eco_log.json emitted."""
    _write_sta(tmp_path, "Endpoint clk\nslack VIOLATED\n-2.0 violation\n")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert (tmp_path / "phase3/stage3/eco/eco_log.json").is_file()
    log = json.loads((tmp_path / "phase3/stage3/eco/eco_log.json").read_text())
    assert log["verdict"] == "ECO_REQUIRED"


def test_vacuous_pass_when_no_sta(tmp_path):
    """No STA report → exit 2 (VACUOUS_PASS)."""
    r = _run(tmp_path)
    assert r.returncode == 2


def test_falls_back_to_pnr_sta_rpt(tmp_path):
    """No sta_dir, but pnr/sta.rpt → still parses + emits flag."""
    pnr_dir = tmp_path / "phase3/stage3/pnr"
    pnr_dir.mkdir(parents=True, exist_ok=True)
    (pnr_dir / "sta.rpt").write_text("Endpoint x\nslack (MET)\n")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert (tmp_path / "phase3/stage3/eco/no_eco_needed.flag").is_file()
