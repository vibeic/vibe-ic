"""Tests for cmd_response_conformance_check.py (v0.50)."""
from __future__ import annotations
import json, subprocess, sys, tempfile
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "cmd_response_conformance_check.py"


def _run(proj: Path, vectors: Path, capture: Path):
    r = subprocess.run(
        [sys.executable, str(PROG), str(proj),
         "--vectors", str(vectors),
         "--capture-json", str(capture)],
        capture_output=True, text=True,
    )
    try:
        return r.returncode, json.loads(r.stdout)
    except Exception:
        return r.returncode, {"_raw": r.stdout, "_err": r.stderr}


def test_all_cases_match_pass(tmp_path):
    vecs = tmp_path / "v.json"
    vecs.write_text(json.dumps({
        "cases": [
            {"cmd_hex": "74 00 01 FD", "expected_rsp_hex": "75 AA BB CC DD EE FF C3"},
            {"cmd_hex": "72 71",       "expected_rsp_hex": "73 80 00 F8 00 DC"},
        ]
    }))
    cap = tmp_path / "cap.json"
    cap.write_text(json.dumps([
        "75 AA BB CC DD EE FF C3",
        "73 80 00 F8 00 DC",
    ]))
    code, out = _run(tmp_path, vecs, cap)
    assert out.get("pass") is True, out
    assert code == 0


def test_one_mismatch_fails(tmp_path):
    vecs = tmp_path / "v.json"
    vecs.write_text(json.dumps({
        "cases": [
            {"cmd_hex": "74 00 01 FD", "expected_rsp_hex": "75 AA BB CC DD EE FF C3"},
        ]
    }))
    cap = tmp_path / "cap.json"
    cap.write_text(json.dumps(["75 AA BB CC DD EE FF 00"]))  # last CRC wrong
    code, out = _run(tmp_path, vecs, cap)
    assert out.get("pass") is False
    assert out["cases_failed"] == 1
    assert "byte 7" in out["findings"][0]["message"]


def test_length_mismatch_fails(tmp_path):
    vecs = tmp_path / "v.json"
    vecs.write_text(json.dumps({"cases": [
        {"cmd_hex": "74 00 01 FD", "expected_rsp_hex": "75 AA BB C3"}
    ]}))
    cap = tmp_path / "cap.json"
    cap.write_text(json.dumps(["75 AA BB"]))
    code, out = _run(tmp_path, vecs, cap)
    assert out.get("pass") is False
    assert "length" in out["findings"][0]["message"]


def test_wildcard_xx_tokens_pass(tmp_path):
    vecs = tmp_path / "v.json"
    vecs.write_text(json.dumps({"cases": [
        {"cmd_hex": "74 00 01 FD", "expected_rsp_hex": "75 XX XX XX XX XX XX YY"}
    ]}))
    cap = tmp_path / "cap.json"
    cap.write_text(json.dumps(["75 01 02 03 04 05 06 99"]))
    code, out = _run(tmp_path, vecs, cap)
    assert out.get("pass") is True, out


def test_missing_capture_fails(tmp_path):
    vecs = tmp_path / "v.json"
    vecs.write_text(json.dumps({"cases": [
        {"cmd_hex": "74", "expected_rsp_hex": "75 00"},
        {"cmd_hex": "72", "expected_rsp_hex": "73 00"},
    ]}))
    cap = tmp_path / "cap.json"
    cap.write_text(json.dumps(["75 00"]))  # only 1 when 2 expected
    code, out = _run(tmp_path, vecs, cap)
    assert out.get("pass") is False
    # Second case gets length mismatch (empty vs 2 bytes)
    assert out["cases_failed"] == 1
