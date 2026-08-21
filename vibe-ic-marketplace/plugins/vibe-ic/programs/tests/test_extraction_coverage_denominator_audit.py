#!/usr/bin/env python3
"""Tests for extraction_coverage_denominator_audit.py (Wave 31)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROG = Path(__file__).resolve().parent.parent / \
    "extraction_coverage_denominator_audit.py"


def _run(project: Path):
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _put_extracted_doc(project: Path, name: str, n_tokens: int):
    d = project / "phase1" / "input_doc"
    d.mkdir(parents=True, exist_ok=True)
    # Generate distinct tokens like 0xAA01, 0xAA02 ... that match
    # hex_const regex (0x[0-9A-Fa-f]+).
    tokens = [f"0x{0xAA00 + i:04X}" for i in range(n_tokens)]
    (d / name).write_text(" ".join(tokens))


def _put_report(project: Path, hit: int, total: int):
    r = project / "reports" / "phase1"
    r.mkdir(parents=True, exist_ok=True)
    (r / "extraction_coverage_report.md").write_text(
        f"# Phase 2a Extraction Coverage Report\n\n"
        f"## Overall: {hit} / {total} = {(hit/total)*100:.1f}%\n")
    (r / "extraction_coverage_report.json").write_text(json.dumps({
        "overall": {"hit": hit, "total": total},
    }))


def test_legit_denominator_pass(tmp_path):
    _put_extracted_doc(tmp_path, "vendor_doc.txt", n_tokens=1100)
    _put_report(tmp_path, hit=1090, total=1090)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout or "WARN" in r.stdout


def test_shrunk_denominator_fail(tmp_path):
    _put_extracted_doc(tmp_path, "vendor_doc.txt", n_tokens=1100)
    _put_report(tmp_path, hit=38, total=38)
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL" in r.stdout


def test_no_extracted_skip(tmp_path):
    r = _run(tmp_path)
    # No extracted docs -> exit 2 silent-skip
    assert r.returncode == 2


def test_no_report_skip(tmp_path):
    _put_extracted_doc(tmp_path, "x.txt", n_tokens=100)
    r = _run(tmp_path)
    assert r.returncode == 2


def test_wired_into_structural_rtl_gates():
    fcc = Path(__file__).resolve().parent.parent / \
        "flow_compliance_check.py"
    txt = fcc.read_text()
    assert "extraction_coverage_denominator_audit" in txt
