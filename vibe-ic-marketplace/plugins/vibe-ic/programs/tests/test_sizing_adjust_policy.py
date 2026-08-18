#!/usr/bin/env python3
"""Tests for sizing_adjust_policy.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "sizing_adjust_policy.py"


def _run(*args):
    return subprocess.run([sys.executable, str(PROG), *args],
                          capture_output=True, text=True)


# -- list --
def test_list(tmp_path):
    out = tmp_path / "o.json"
    r = _run("list", "--json", str(out))
    assert r.returncode == 0
    rep = json.loads(out.read_text())
    assert "gain_low" in rep["table"]
    assert rep["table"]["power_high"]["Ibias"] == 0.7


# -- PASS: known failure mode, no sizing → just the delta --
def test_propose_known_mode(tmp_path):
    out = tmp_path / "o.json"
    r = _run("propose", "gain_low", "--json", str(out))
    assert r.returncode == 0
    rep = json.loads(out.read_text())
    assert rep["passed"] is True
    assert rep["delta"] == {"W_in": 1.5}


# -- PASS: apply delta to a sizing point --
def test_propose_applies_delta(tmp_path):
    out = tmp_path / "o.json"
    r = _run("propose", "power_high",
             "--sizing", json.dumps({"W_in": 20.0, "Ibias": 30.0}),
             "--json", str(out))
    assert r.returncode == 0
    rep = json.loads(out.read_text())
    assert rep["new_sizing"]["Ibias"] == 21.0  # 30 * 0.7
    assert rep["new_sizing"]["W_in"] == 20.0   # untouched


# -- PASS: alias resolves --
def test_propose_alias(tmp_path):
    out = tmp_path / "o.json"
    r = _run("propose", "pm", "--json", str(out))
    assert r.returncode == 0
    assert json.loads(out.read_text())["failure_mode"] == "phase_margin_low"


# -- FAIL: unknown failure mode → no vacuous "no change" --
def test_propose_unknown_mode(tmp_path):
    out = tmp_path / "o.json"
    r = _run("propose", "magic_pixie_dust", "--json", str(out))
    assert r.returncode == 1
    rep = json.loads(out.read_text())
    assert rep["passed"] is False
    assert rep["reason"] == "unknown_failure_mode"


# -- FAIL: delta touches a param absent from the sizing point --
def test_propose_param_not_in_sizing(tmp_path):
    out = tmp_path / "o.json"
    r = _run("propose", "phase_margin_low",   # needs Cc
             "--sizing", json.dumps({"W_in": 20.0}),
             "--json", str(out))
    assert r.returncode == 1
    rep = json.loads(out.read_text())
    assert rep["reason"] == "param_not_in_sizing"
    assert "Cc" in rep["missing_params"]


# -- bad input: --sizing not valid JSON → exit 2 --
def test_propose_bad_sizing_json():
    r = _run("propose", "gain_low", "--sizing", "{not json")
    assert r.returncode == 2
