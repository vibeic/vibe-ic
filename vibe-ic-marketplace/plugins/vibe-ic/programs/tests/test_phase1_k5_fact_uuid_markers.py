"""Tests for v0.74 Task-C Stage-C3: fact-UUID marker consumption in K5.

Exercises the new `check_fact_uuid_markers()` path in
phase1_k5_quality_check.py using synthetic RTL fixtures. spec-to-rtl
(Stage C2) doesn't emit markers yet, so we hand-author them here.
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent
        / "phase1_k5_quality_check.py")


def _make_index(tmp: Path, entries: dict) -> Path:
    p = tmp / "fact_index.json"
    p.write_text(json.dumps(entries, indent=2))
    return p


def _make_facts_yaml(tmp: Path, facts: list) -> Path:
    """Minimal facts.yaml shape matching FactGraph.save()."""
    import yaml
    p = tmp / "facts.yaml"
    p.write_text(yaml.safe_dump({
        "version": 1,
        "ic_name": "TEST_IC",
        "class_path": "any-ic",
        "facts": facts,
    }))
    return p


def _make_rtl(tmp: Path, text: str) -> Path:
    d = tmp / "phase2" / "stage1" / "rtl"
    d.mkdir(parents=True, exist_ok=True)
    (d / "top.v").write_text(text)
    return d


def _run(rtl: Path, index: Path, facts: Path | None = None):
    argv = [sys.executable, str(PROG),
            "--rtl", str(rtl), "--fact-index", str(index), "--json"]
    if facts:
        argv += ["--facts", str(facts)]
    r = subprocess.run(argv, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_clean_rtl_with_known_uuids_produces_no_issues(tmp_path):
    rtl = _make_rtl(tmp_path, """\
module top;
  // phase1-fact: abc123456789 path=L8R.bit_period_cycles source=derived
  localparam BIT_PERIOD_CYCLES = 200;
endmodule
""")
    idx = _make_index(tmp_path, {"L8R.bit_period_cycles": "abc123456789"})
    out = _run(rtl, idx)
    assert out == []


def test_unknown_uuid_emits_K5_T(tmp_path):
    rtl = _make_rtl(tmp_path, """\
// phase1-fact: deadbeef1234 path=L3.frame_format.crc.poly source=user_stated
localparam CRC_POLY = 8'h31;
""")
    idx = _make_index(tmp_path, {"L3.frame_format.crc.poly": "different-uuid"})
    out = _run(rtl, idx)
    ids = [i["id"] for i in out]
    assert "K5-T" in ids
    assert any("deadbeef1234" in i["msg"] for i in out)


def test_value_mismatch_emits_K5_U(tmp_path):
    rtl = _make_rtl(tmp_path, """\
// phase1-fact: abc123456789 path=L8R.bit_period_cycles source=derived
localparam BIT_PERIOD_CYCLES = 200;
""")
    idx = _make_index(tmp_path, {"L8R.bit_period_cycles": "abc123456789"})
    facts = _make_facts_yaml(tmp_path, [{
        "path": "L8R.bit_period_cycles",
        "value": 250,          # current fact says 250, RTL still has 200
        "views": ["L8R"],
        "provenance": {"source": "derived", "origin": "", "confidence": 1.0,
                       "reasoning": "", "auto_decided": False},
        "uuid": "abc123456789",
        "tags": [],
    }])
    out = _run(rtl, idx, facts)
    ids = [i["id"] for i in out]
    assert "K5-U" in ids


def test_value_match_emits_no_K5_U(tmp_path):
    rtl = _make_rtl(tmp_path, """\
// phase1-fact: abc123456789 path=L8R.bit_period_cycles source=derived
localparam BIT_PERIOD_CYCLES = 200;
""")
    idx = _make_index(tmp_path, {"L8R.bit_period_cycles": "abc123456789"})
    facts = _make_facts_yaml(tmp_path, [{
        "path": "L8R.bit_period_cycles",
        "value": 200,
        "views": ["L8R"],
        "provenance": {"source": "derived", "origin": "", "confidence": 1.0,
                       "reasoning": "", "auto_decided": False},
        "uuid": "abc123456789",
        "tags": [],
    }])
    out = _run(rtl, idx, facts)
    assert all(i["id"] != "K5-U" for i in out)


def test_verilog_hex_literal_compares_equal_to_fact_hex_string(tmp_path):
    rtl = _make_rtl(tmp_path, """\
// phase1-fact: crc12345678 path=L3.frame_format.crc.poly source=user_stated
localparam CRC_POLY = 8'h31;
""")
    idx = _make_index(tmp_path, {"L3.frame_format.crc.poly": "crc12345678"})
    facts = _make_facts_yaml(tmp_path, [{
        "path": "L3.frame_format.crc.poly",
        "value": "0x31",
        "views": ["L3"],
        "provenance": {"source": "user_stated", "origin": "", "confidence": 1.0,
                       "reasoning": "", "auto_decided": False},
        "uuid": "crc12345678",
        "tags": [],
    }])
    out = _run(rtl, idx, facts)
    assert all(i["id"] != "K5-U" for i in out), (
        "8'h31 should match fact value '0x31' after normalization")


def test_multi_fact_marker_group_with_conflict_emits_K5_V(tmp_path):
    rtl = _make_rtl(tmp_path, """\
// phase1-fact: deadbeef0001 path=L3.frame_format.crc.poly source=user_stated
// phase1-fact: deadbeef0002 path=L8R.crc8_polynomial source=derived
localparam CRC_POLY = 8'h31;
""")
    idx = _make_index(tmp_path, {
        "L3.frame_format.crc.poly": "deadbeef0001",
        "L8R.crc8_polynomial": "deadbeef0002",
    })
    # Facts disagree (L3 says 0x31, L8R says 0x07 — K4 mirror rule violation)
    facts = _make_facts_yaml(tmp_path, [
        {"path": "L3.frame_format.crc.poly", "value": "0x31", "views": ["L3"],
         "provenance": {"source": "user_stated", "origin": "", "confidence": 1.0,
                        "reasoning": "", "auto_decided": False},
         "uuid": "deadbeef0001", "tags": []},
        {"path": "L8R.crc8_polynomial", "value": "0x07", "views": ["L8R"],
         "provenance": {"source": "derived", "origin": "", "confidence": 1.0,
                        "reasoning": "", "auto_decided": False},
         "uuid": "deadbeef0002", "tags": []},
    ])
    out = _run(rtl, idx, facts)
    ids = [i["id"] for i in out]
    assert "K5-V" in ids


def test_missing_fact_index_emits_warn_not_crash(tmp_path):
    rtl = _make_rtl(tmp_path, "// phase1-fact: x path=L1.y source=user_stated\nwire z;")
    # fact_index.json doesn't exist
    out = _run(rtl, tmp_path / "does_not_exist.json")
    assert any(i["id"] == "K5-T" for i in out)
