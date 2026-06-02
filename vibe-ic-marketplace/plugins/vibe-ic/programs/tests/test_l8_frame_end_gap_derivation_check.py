#!/usr/bin/env python3
"""Tests for l8_frame_end_gap_derivation_check.py (LL-3)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "l8_frame_end_gap_derivation_check.py"


def _run(tmp_path: Path, strict: bool = False):
    cmd = [sys.executable, str(PROG), str(tmp_path),
           "--json", str(tmp_path / "rep.json")]
    if strict:
        cmd.append("--strict")
    return subprocess.run(cmd, capture_output=True, text=True)


def _setup(tmp_path: Path, frame_end_us: float | None = None,
           ibt_max: float = 22.0):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L2_TIMING_WAVEFORM.json").write_text(json.dumps({
        "ibt_us": [20.0, ibt_max],
        "tSRS_min_us": 20.0,
    }))
    l8: dict = {"internal_clock_MHz": 50}
    if frame_end_us is not None:
        l8["frame_end_gap_us"] = frame_end_us
    (docs / "L8_RTL_CONSTANTS.json").write_text(json.dumps(l8))


def test_no_frame_end_gap_skipped(tmp_path):
    _setup(tmp_path, frame_end_us=None)
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0  # skipped


def test_too_wide_errors(tmp_path):
    _setup(tmp_path, frame_end_us=80.0)  # > 2*22 = 44
    r = _run(tmp_path, strict=True)
    assert r.returncode == 1
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert any(f["rule"] == "L8_FRAME_END_GAP_TOO_WIDE"
               for f in rep["findings"])


def test_too_tight_errors(tmp_path):
    _setup(tmp_path, frame_end_us=21.0)  # < 22 + 3 = 25
    r = _run(tmp_path, strict=True)
    assert r.returncode == 1
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert any(f["rule"] == "L8_FRAME_END_GAP_TOO_TIGHT"
               for f in rep["findings"])


def test_derived_correctly_passes(tmp_path):
    _setup(tmp_path, frame_end_us=27.0)  # in [25, 44]
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0


def test_l2_max_factor_override_passes_wider(tmp_path):
    """L2 may override max_factor to allow wider gap when spec demands."""
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L2_TIMING_WAVEFORM.json").write_text(json.dumps({
        "ibt_us": [20.0, 22.0],
        "tSRS_min_us": 20.0,
        "frame_end_gap_max_factor": 5.0,  # 5*22 = 110us upper bound
    }))
    (docs / "L8_RTL_CONSTANTS.json").write_text(json.dumps({
        "internal_clock_MHz": 50,
        "frame_end_gap_us": 80.0,  # was failing at default 2.0; passes at 5.0
    }))
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0


def test_waiver_skips(tmp_path):
    _setup(tmp_path, frame_end_us=80.0)  # would normally fail
    (tmp_path / "waivers.json").write_text(json.dumps({
        "waivers": [{
            "id": "frame_end_gap_derivation_override",
            "rationale": "EXAMPLE_TESTER-V2 tester tolerates 80us per vendor email",
        }],
    }))
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0


def test_ticks_field_at_50MHz(tmp_path):
    """Verify we can parse tick-form fields with rate suffix."""
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L2_TIMING_WAVEFORM.json").write_text(json.dumps({
        "ibt_us": [20.0, 22.0],
        "tSRS_min_us": 20.0,
    }))
    (docs / "L8_RTL_CONSTANTS.json").write_text(json.dumps({
        "internal_clock_MHz": 50,
        "frame_end_gap_ticks_50MHz": 4000,  # = 80us → too wide
    }))
    r = _run(tmp_path, strict=True)
    assert r.returncode == 1
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert any(f["rule"] == "L8_FRAME_END_GAP_TOO_WIDE"
               for f in rep["findings"])
