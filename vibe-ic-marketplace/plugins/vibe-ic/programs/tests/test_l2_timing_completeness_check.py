#!/usr/bin/env python3
"""Tests for l2_timing_completeness_check.py (LL-32)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "l2_timing_completeness_check.py"


def _run(tmp_path: Path):
    return subprocess.run([sys.executable, str(PROG), str(tmp_path)],
                          capture_output=True, text=True)


def _put_doc(tmp_path: Path, name: str, body: str):
    docs = tmp_path / "input" / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / name).write_text(body)


def _put_l2(tmp_path: Path, data: dict):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L2_FRS.json").write_text(json.dumps(data))


# 1. Silent-skip: no input/docs/.
def test_no_docs_silent_pass(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "skipped" in r.stdout.lower()


# 2. Silent-skip: docs exist but no timing evidence.
def test_docs_without_timing_silent_pass(tmp_path):
    _put_doc(tmp_path, "spec.txt",
             "This is a chip with command set and 8 bytes of OTP.")
    r = _run(tmp_path)
    assert r.returncode == 0


# 3. PASS — docs measure timings AND L2 has timing keys.
def test_docs_and_l2_with_timing_pass(tmp_path):
    _put_doc(tmp_path, "timing.txt",
             "tITO_ms = 5\ntWFT_us: 20\nMIN  Max  us\n")
    _put_l2(tmp_path, {
        "timing_parameters": {
            "tSRS_us": [20, 80],
            "ibt_us": [8.5, 22],
        }
    })
    r = _run(tmp_path)
    assert r.returncode == 0


# 4. FAIL — docs measure timings but L2 has zero timing keys.
def test_docs_with_timing_but_l2_empty_fails(tmp_path):
    _put_doc(tmp_path, "timing.txt",
             "tITO_ms = 5\ntWFT_us: 20\n")
    _put_l2(tmp_path, {
        "functional_requirements": ["FR-1"],
        "non_functional_requirements": ["NFR-1"],
    })
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "ZERO timing keys" in r.stdout


# 5. Waiver allows empty L2.
def test_waiver_allows(tmp_path):
    _put_doc(tmp_path, "timing.txt", "tITO_ms = 5\n")
    _put_l2(tmp_path, {"functional_requirements": []})
    (tmp_path / "waivers.json").write_text(json.dumps({
        "l2_timing_externalized_to_other_doc":
            "All timings live in L8 only by project convention",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "PASS_WITH_WAIVER" in r.stdout


# 6. Vendor table-only evidence still triggers and detects missing L2.
def test_vendor_table_evidence_triggers(tmp_path):
    _put_doc(tmp_path, "20230103-3.txt",
             "H1_MIN[1] H1_MAX[192] BR_MIN[637] BR_MAX[1314]")
    _put_l2(tmp_path, {"x": 1})
    r = _run(tmp_path)
    assert r.returncode == 1


# 7. Edge case: L2 has timing key in nested structure (`bit_timing_internal`).
def test_l2_timing_in_nested_container_pass(tmp_path):
    _put_doc(tmp_path, "timing.txt", "tITO_ms = 5\n")
    _put_l2(tmp_path, {
        "bit_timing_internal": {
            "rx_detect": {"logic_1_max_cycles": 12, "break_min_cycles": 30}
        },
        "timeouts": {"safe_rx_timeout_us": {"value": 100, "kind": "TYP"}}
    })
    r = _run(tmp_path)
    assert r.returncode == 0


# 8. L2 missing entirely + evidence in docs → FAIL.
def test_l2_missing_with_evidence_fails(tmp_path):
    _put_doc(tmp_path, "timing.txt", "tITO_ms = 5\n")
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "missing" in r.stdout.lower()
