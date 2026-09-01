"""Tests for threshold_range_contiguity_check.py.

Generic gate — catches the v068 BENCH-A fresh-agent's range-gap bug
(H1_MAX 192 → H0_MIN 196, 3-tick gap) but applies to ANY IC with
discrete threshold classification (pulse widths, voltage bins, ADC
codes, etc.).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROGRAM = Path(__file__).parent.parent / "threshold_range_contiguity_check.py"


def _run(tmp_path, doc, extra_args=()):
    p = tmp_path / "L8.json"
    p.write_text(json.dumps(doc))
    cmd = [sys.executable, str(PROGRAM), str(p), "--json", *extra_args]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, json.loads(r.stdout) if r.stdout else {}


def test_v052_shape_passes(tmp_path):
    # v052 naming: H1_LOW_MIN / H1_LOW_MAX (infix _LOW), Verilog `8'd1` literals
    doc = {
        "thresholds": [
            {"name": "H1_LOW_MIN", "value": "8'd1"},
            {"name": "H1_LOW_MAX", "value": "8'd9"},
            {"name": "H0_LOW_MIN", "value": "8'd10"},
            {"name": "H0_LOW_MAX", "value": "8'd30"},
            {"name": "BR_LOW_MIN", "value": "8'd31"},
            {"name": "BR_LOW_MAX", "value": "8'd100"},
        ]
    }
    rc, out = _run(tmp_path, doc)
    assert rc == 0, out
    assert out["verdict"] == "PASS"


def test_v068_shape_flags_two_gaps(tmp_path):
    # v068 naming: H1_MIN_TICKS / H1_MAX_TICKS (no _LOW infix), value_dec int
    doc = {
        "thresholds": [
            {"name": "H1_MIN_TICKS",   "value_dec": 1},
            {"name": "H1_MAX_TICKS",   "value_dec": 192},
            {"name": "H0_MIN_TICKS",   "value_dec": 196},  # gap 3
            {"name": "H0_MAX_TICKS",   "value_dec": 612},
            {"name": "BR_MIN_TICKS",   "value_dec": 637},  # gap 24
            {"name": "BR_MAX_TICKS",   "value_dec": 1314},
        ]
    }
    rc, out = _run(tmp_path, doc)
    assert rc == 1
    rules = [f["rule"] for f in out["findings"]]
    assert rules.count("range_gap") == 2


def test_flat_dict_form(tmp_path):
    doc = {"H1_MIN": 1, "H1_MAX": 9, "H0_MIN": 10, "H0_MAX": 30,
           "BR_MIN": 31, "BR_MAX": 100}
    rc, out = _run(tmp_path, doc)
    assert rc == 0
    assert out["verdict"] == "PASS"


def test_overlap_flagged(tmp_path):
    doc = {"H1_MIN": 1, "H1_MAX": 15, "H0_MIN": 10, "H0_MAX": 30,
           "BR_MIN": 31, "BR_MAX": 100}
    rc, out = _run(tmp_path, doc)
    assert rc == 1
    assert any(f["rule"] == "range_overlap" for f in out["findings"])


def test_inverted_pair_flagged(tmp_path):
    doc = {"H1_MIN": 20, "H1_MAX": 9, "H0_MIN": 10, "H0_MAX": 30,
           "BR_MIN": 31, "BR_MAX": 100}
    rc, out = _run(tmp_path, doc)
    assert rc == 1
    assert any(f["rule"] == "inverted_threshold_pair" for f in out["findings"])


def test_incomplete_pair_in_chain_flagged(tmp_path):
    doc = {"H1_MIN": 1, "H0_MIN": 10, "H0_MAX": 30,
           "BR_MIN": 31, "BR_MAX": 100}
    rc, out = _run(tmp_path, doc)
    assert rc == 1
    assert any(f["rule"] == "incomplete_threshold_pair" for f in out["findings"])


def test_out_of_chain_class_not_complained(tmp_path):
    # IBT / WKP have only MIN → out-of-chain, gate should NOT complain.
    doc = {"H1_MIN": 1, "H1_MAX": 9, "H0_MIN": 10, "H0_MAX": 30,
           "BR_MIN": 31, "BR_MAX": 100,
           "IBT_MIN": 12, "WKP_MIN": 37}
    rc, out = _run(tmp_path, doc)
    assert rc == 0
    assert out["verdict"] == "PASS"


def test_user_can_include_ibt_in_chain(tmp_path):
    # Pass --order H1,H0,BR,IBT to put IBT in the contiguity chain
    doc = {"H1_MIN": 1, "H1_MAX": 9, "H0_MIN": 10, "H0_MAX": 30,
           "BR_MIN": 31, "BR_MAX": 100,
           "IBT_MIN": 101, "IBT_MAX": 200}
    rc, out = _run(tmp_path, doc, extra_args=("--order", "H1,H0,BR,IBT"))
    assert rc == 0
    assert out["verdict"] == "PASS"


def test_voltage_bins_use_case(tmp_path):
    # Generic non-BENCH-A use: ADC voltage bins must be contiguous.
    doc = {
        "bins": [
            {"name": "LOW_MIN",  "value_dec": 0},
            {"name": "LOW_MAX",  "value_dec": 341},
            {"name": "MID_MIN",  "value_dec": 342},
            {"name": "MID_MAX",  "value_dec": 682},
            {"name": "HIGH_MIN", "value_dec": 683},
            {"name": "HIGH_MAX", "value_dec": 1023},
        ]
    }
    rc, out = _run(tmp_path, doc, extra_args=("--order", "LOW,MID,HIGH"))
    assert rc == 0
    assert out["verdict"] == "PASS"


def test_voltage_bins_with_gap(tmp_path):
    doc = {
        "bins": [
            {"name": "LOW_MIN",  "value_dec": 0},
            {"name": "LOW_MAX",  "value_dec": 340},
            {"name": "MID_MIN",  "value_dec": 342},   # gap 1
            {"name": "MID_MAX",  "value_dec": 682},
            {"name": "HIGH_MIN", "value_dec": 683},
            {"name": "HIGH_MAX", "value_dec": 1023},
        ]
    }
    rc, out = _run(tmp_path, doc, extra_args=("--order", "LOW,MID,HIGH"))
    assert rc == 1
    assert any(f["rule"] == "range_gap" for f in out["findings"])


def test_no_threshold_classification_is_disclosed_not_applicable(tmp_path):
    """A document with no threshold classifier is outside this gate's scope."""
    rc, out = _run(tmp_path, {
        "no_rx_classifier_ticks_in_input": True,
        "clocks": [{"name": "sample", "hz": 1_000_000}],
    })
    assert rc == 0
    assert out["verdict"] == "SKIPPED-CONDITION"
    assert out["applicable"] is False
    assert out["reason_class"] == "DESIGN_DECLARED_NA"
    assert out["findings"] == []


def test_empty_threshold_domain_without_declaration_still_warns(tmp_path):
    rc, out = _run(tmp_path, {"clocks": [{"name": "sample", "hz": 1_000_000}]})
    assert rc == 0
    assert out["verdict"] == "PASS"
    assert out["applicable"] is None
    assert any(f["rule"] == "no_thresholds_found" for f in out["findings"])


def test_malformed_json_error(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{ not: json")
    r = subprocess.run([sys.executable, str(PROGRAM), str(p)], capture_output=True)
    assert r.returncode == 2


def test_missing_file_error(tmp_path):
    r = subprocess.run(
        [sys.executable, str(PROGRAM), str(tmp_path / "nope.json")],
        capture_output=True)
    assert r.returncode == 2
