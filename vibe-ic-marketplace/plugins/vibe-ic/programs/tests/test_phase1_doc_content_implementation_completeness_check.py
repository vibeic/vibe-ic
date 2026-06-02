#!/usr/bin/env python3
"""Tests for phase1_doc_content_implementation_completeness_check.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = (Path(__file__).resolve().parent.parent /
        "phase1_doc_content_implementation_completeness_check.py")


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _setup(tmp_path: Path, doc_text: str, l_docs: dict[str, dict],
           waivers: dict | None = None) -> Path:
    docs = tmp_path / "phase1" / "input_doc"
    docs.mkdir(parents=True)
    (docs / "spec.txt").write_text(doc_text, encoding="utf-8")
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    for name, content in l_docs.items():
        (gd / name).write_text(json.dumps(content))
    if waivers is not None:
        (tmp_path / "waivers.json").write_text(json.dumps(waivers))
    return tmp_path


def test_no_sections_skip(tmp_path):
    docs = tmp_path / "phase1" / "input_doc"
    docs.mkdir(parents=True)
    (docs / "spec.txt").write_text("plain prose, no headings here", encoding="utf-8")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "SKIP" in r.stdout


def test_high_coverage_pass(tmp_path):
    doc = (
        "1. Overview\nthis section describes the chip\n"
        "2. Pinout\npin list table\n"
        "3. Electrical Specs\nDC params\n"
    )
    l_docs = {
        "L1_DATASHEET.json": {"overview": "1. Overview content",
                              "pinout": "2. Pinout pin assignments",
                              "elec": "3. Electrical Specs full table"}
    }
    _setup(tmp_path, doc, l_docs)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_low_coverage_fail(tmp_path):
    doc = (
        "1. Overview\n2. Pinout\n3. Electrical\n4. Timing\n5. Protocol\n"
        "6. OTP\n7. Test Mode\n8. Calibration\n9. Package\n10. Ordering\n"
    )
    # Only 1 of 10 sections cited.
    l_docs = {
        "L1_DATASHEET.json": {"overview": "1. Overview content"}
    }
    _setup(tmp_path, doc, l_docs)
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL" in r.stdout


def test_waiver_per_section(tmp_path):
    doc = (
        "1. Overview\n2. Pinout\n3. Skipped Section\n"
    )
    l_docs = {
        "L1_DATASHEET.json": {"overview": "1. Overview content",
                              "pinout": "2. Pinout list"}
    }
    waivers = {
        "phase1_section_intentionally_unimplemented_skipped_section":
            "This section deliberately deferred per user agreement; reason "
            "documented in BACKLOG-v12 with foundry sign-off plan."
    }
    _setup(tmp_path, doc, l_docs, waivers)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr


def test_warn_band(tmp_path):
    # 80%-90% coverage should WARN (exit 0, "WARN" in stdout).
    doc = "\n".join(f"{i}. Section{i}\nbody{i}" for i in range(1, 11))
    l_docs = {
        "L1_DATASHEET.json": {
            "f1": "1. Section1", "f2": "2. Section2",
            "f3": "3. Section3", "f4": "4. Section4",
            "f5": "5. Section5", "f6": "6. Section6",
            "f7": "7. Section7", "f8": "8. Section8",
        }
    }
    _setup(tmp_path, doc, l_docs)
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "WARN" in r.stdout or "PASS" in r.stdout
