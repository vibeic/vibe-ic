#!/usr/bin/env python3
"""Tests for spef_extraction_check.py (G1: Parasitic Extraction)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "spef_extraction_check.py"


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(PROG), str(tmp_path), "--json", str(tmp_path / "out.json")]
    return subprocess.run(cmd, capture_output=True, text=True)


def _make_spef(path: Path, content: str = "", size: int = 0):
    path.parent.mkdir(parents=True, exist_ok=True)
    if content:
        path.write_text(content)
    else:
        path.write_bytes(b"\x00" * size)


_VALID_SPEF = (
    '*SPEF "IEEE 1481-1998"\n'
    '*DESIGN "top"\n'
    '*DATE "2026-04-29"\n'
    + "".join(f"*D_NET net_{i} {i * 0.001:.4f}\n*CONN\n*END\n"
              for i in range(80))
)


def test_pass_valid_spef(tmp_path):
    _make_spef(tmp_path / "phase3" / "stage3" / "extracted" / "top.spef", _VALID_SPEF)
    result = _run(tmp_path)
    assert result.returncode == 0
    report = json.loads((tmp_path / "out.json").read_text())
    assert report["summary"]["pass"] is True
    assert report["summary"]["spef_files"] == 1


def test_fail_no_extracted_dir(tmp_path):
    result = _run(tmp_path)
    assert result.returncode == 1


def test_fail_no_spef_files(tmp_path):
    (tmp_path / "phase3" / "stage3" / "extracted").mkdir(parents=True)
    result = _run(tmp_path)
    assert result.returncode == 1


def test_fail_empty_spef(tmp_path):
    _make_spef(tmp_path / "phase3" / "stage3" / "extracted" / "top.spef", "")
    result = _run(tmp_path)
    assert result.returncode == 1


def test_fail_too_small(tmp_path):
    _make_spef(tmp_path / "phase3" / "stage3" / "extracted" / "top.spef", size=500)
    result = _run(tmp_path)
    assert result.returncode == 1


def test_fail_no_header(tmp_path):
    _make_spef(tmp_path / "phase3" / "stage3" / "extracted" / "top.spef",
               "some random text\n" * 200)
    result = _run(tmp_path)
    assert result.returncode == 1


def test_exit2_bad_dir(tmp_path):
    cmd = [sys.executable, str(PROG), str(tmp_path / "nonexistent")]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 2


def test_pass_with_pdk_unavailable_waiver(tmp_path):
    """v0.119.21: custom open-source PDKs (KeyFoundry m18e80pm180su, etc.)
    have no Magic .tech for parasitic extraction. With a documented
    spef_extraction_unavailable_reason ≥20 chars, the gate accepts the
    deferral instead of blocking forever on a tool-unavailable wall."""
    (tmp_path / "waivers.json").write_text(json.dumps({
        "spef_extraction_unavailable_reason":
            "KeyFoundry 180nm PDK has no Magic tech file; SPEF extraction "
            "deferred until foundry sign-off uses commercial Calibre",
    }))
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout
    report = json.loads((tmp_path / "out.json").read_text())
    assert report["summary"].get("waived") is True


def test_short_reason_does_not_pass_waiver(tmp_path):
    """Anti-rubber-stamp: <20-char reason rejected just like the
    waivers_schema_check policy."""
    (tmp_path / "waivers.json").write_text(json.dumps({
        "spef_extraction_unavailable_reason": "tool busted",
    }))
    result = _run(tmp_path)
    assert result.returncode == 1, "rubber-stamp waiver must NOT pass"
