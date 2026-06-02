#!/usr/bin/env python3
"""Tests for l_doc_unique_content_check.py (Wave 31)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROG = Path(__file__).resolve().parent.parent / \
    "l_doc_unique_content_check.py"


def _run(project: Path):
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _put(project: Path, name: str, data: dict):
    d = project / "phase1" / "generated_docs"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps(data, ensure_ascii=False))


def test_distinct_l_docs_pass(tmp_path):
    _put(tmp_path, "L1_DATASHEET.json", {
        "vdd_min_volts": 1.65, "vdd_typ_volts": 3.30,
        "package_pins": 16, "die_size_mm": 1.2,
    })
    _put(tmp_path, "L2_FRS.json", {
        "tSRS_min_us": 9.0, "tSRS_max_us": 17.0,
        "ibt_min_us": 230, "frame_end_gap_us": 80,
    })
    _put(tmp_path, "L3_CMD_PROTOCOL.json", {
        "opcodes": [{"hex": "0x70", "name": "GET_STATE"}],
        "crc_parameters": {"polynomial_hex": "0x31"},
    })
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_shared_blob_fail(tmp_path):
    blob = (
        "vendor_doc_text alpha beta gamma delta epsilon zeta eta theta "
        "iota kappa lambda mu nu xi omicron pi rho sigma tau upsilon "
        "phi chi psi omega register opcode polynomial init reflected "
        "0x31 0x8C 0xFF lsb_first frame end gap rx classifier ticks"
    ) * 4
    for n in ("L1_DATASHEET.json", "L2_FRS.json", "L3_CMD_PROTOCOL.json"):
        _put(tmp_path, n, {"all_input_literals_aggregated": blob})
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL" in r.stdout
    assert "shared blob" in r.stdout.lower() or "jaccard" in r.stdout.lower()


def test_wired_into_structural_rtl_gates():
    fcc = Path(__file__).resolve().parent.parent / \
        "flow_compliance_check.py"
    txt = fcc.read_text()
    assert "l_doc_unique_content_check" in txt
