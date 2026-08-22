#!/usr/bin/env python3
"""Tests for binary_doc_low_extraction_warn.py (LL-36)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "binary_doc_low_extraction_warn.py"


def _run(tmp_path: Path):
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path)],
        capture_output=True, text=True,
    )


def _put_manifest(tmp_path: Path, entries: list,
                  rel: str = "reports/pdf/INDEX.json"):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(entries), encoding="utf-8")


# ---------- 1. no manifest → silent-pass --------------------------
def test_no_manifest_silent_pass(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


# ---------- 2. all PDFs above threshold → PASS --------------------
def test_good_coverage_pass(tmp_path):
    _put_manifest(tmp_path, [
        {
            "input_path": "/x/spec.pdf",
            "format": "pdf",
            "char_count": 50000,
            "file_size": 200000,  # 25%
            "status": "PASS",
        },
    ])
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout
    assert "WARN" not in r.stderr


# ---------- 3. low-coverage PDF → WARN to stderr, exit 0 ----------
def test_low_coverage_warns(tmp_path):
    _put_manifest(tmp_path, [
        {
            "input_path": "/x/figureheavy.pdf",
            "format": "pdf",
            "char_count": 100,
            "file_size": 1000000,  # 0.01%
            "status": "PASS",
        },
    ])
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "WARN" in r.stderr
    assert "figureheavy.pdf" in r.stderr


# ---------- 4. waiver → PASS_WITH_WAIVER --------------------------
def test_waiver_accepted(tmp_path):
    _put_manifest(tmp_path, [
        {
            "input_path": "/x/scan.pdf",
            "format": "pdf",
            "char_count": 0,
            "file_size": 500000,
            "status": "PASS",
        },
    ])
    (tmp_path / "waivers.json").write_text(json.dumps({
        "binary_doc_low_extraction_acknowledged":
            "Vendor scan-only PDF acknowledged; relevant content "
            "transcribed into vendor.txt sidecar by hand.",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS_WITH_WAIVER" in r.stdout


# ---------- 5. xlsx / docx entries are ignored --------------------
def test_non_pdf_entries_ignored(tmp_path):
    _put_manifest(tmp_path, [
        {
            "input_path": "/x/sheet.xlsx",
            "format": "xlsx",
            "char_count": 0,
            "file_size": 200000,
            "status": "PASS",
        },
    ])
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "WARN" not in r.stderr
