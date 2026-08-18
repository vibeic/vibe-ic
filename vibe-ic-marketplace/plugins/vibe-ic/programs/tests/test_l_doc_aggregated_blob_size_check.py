#!/usr/bin/env python3
"""Tests for l_doc_aggregated_blob_size_check.py (Wave 31)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROG = Path(__file__).resolve().parent.parent / \
    "l_doc_aggregated_blob_size_check.py"


def _run(project: Path):
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _put(project: Path, name: str, data: dict):
    d = project / "phase1" / "generated_docs"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps(data, ensure_ascii=False))


def test_no_blob_pass(tmp_path):
    _put(tmp_path, "L1_DATASHEET.json", {"a": "x", "b": "y"})
    _put(tmp_path, "L2_FRS.json", {"timing": {"x": 1}})
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_large_blob_fail(tmp_path):
    big = "X" * (15 * 1024)  # 15 KB > 10 KB single-field limit
    _put(tmp_path, "L1_DATASHEET.json", {
        "all_input_literals_aggregated": big,
    })
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL" in r.stdout
    assert "all_input_literals_aggregated" in r.stdout


def test_per_doc_total_fail(tmp_path):
    # Several smaller blob fields each ≤10 KB but summing >50 KB.
    parts = {}
    for i in range(7):
        parts[f"chunk{i}_dump"] = "Y" * (8 * 1024)
    _put(tmp_path, "L3_CMD_PROTOCOL.json", parts)
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "L3" in r.stdout


def test_global_total_fail(tmp_path):
    # 9 KB per L doc * 30 docs = 270 KB > 200 KB global.
    for i in range(30):
        _put(tmp_path, f"L{i+1}_X.json", {
            "raw_text": "Z" * (9 * 1024),
        })
    r = _run(tmp_path)
    # Per-doc 9KB not over 50KB single, not over 50KB total per doc, but
    # over 200 KB globally. 9 * 30 = 270 KB.
    assert r.returncode == 1
    assert "global" in r.stdout.lower()


def test_with_waiver_FORBIDDEN(tmp_path):
    """Even if a waiver is added, this gate is non-waivable."""
    big = "X" * (15 * 1024)
    _put(tmp_path, "L1_DATASHEET.json", {
        "all_input_literals_aggregated": big,
    })
    (tmp_path / "waivers.json").write_text(json.dumps({
        "l_doc_aggregated_blob_size_acceptable":
            "Allow blob for testing — over 40 chars rationale.",
    }))
    r = _run(tmp_path)
    # Gate ignores waivers.json and still FAILs.
    assert r.returncode == 1
    assert "FAIL" in r.stdout


def test_wired_into_structural_rtl_gates():
    fcc = Path(__file__).resolve().parent.parent / \
        "flow_compliance_check.py"
    txt = fcc.read_text()
    assert "l_doc_aggregated_blob_size_check" in txt
