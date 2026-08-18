#!/usr/bin/env python3
"""Tests for backlog_severity_classify.py"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent
        / "backlog_severity_classify.py")


def _run(args, **kw):
    return subprocess.run([sys.executable, str(PROG)] + args,
                          capture_output=True, text=True, **kw)


def test_help():
    r = _run(["--help"])
    assert r.returncode == 0


def test_high_for_l4(tmp_path):
    out = tmp_path / "o.json"
    r = _run(["--layers", "L4", "--json", str(out)])
    assert r.returncode == 0
    rep = json.loads(out.read_text())
    assert rep["severity"] == "HIGH"
    assert rep["high_layers_present"] == ["L4"]


def test_high_when_any_high_layer_present(tmp_path):
    out = tmp_path / "o.json"
    r = _run(["--layers", "L2,L4", "--json", str(out)])
    assert r.returncode == 0
    rep = json.loads(out.read_text())
    assert rep["severity"] == "HIGH"


def test_medium_for_non_structural(tmp_path):
    out = tmp_path / "o.json"
    r = _run(["--layers", "L1,L5,L12", "--json", str(out)])
    assert r.returncode == 0
    rep = json.loads(out.read_text())
    assert rep["severity"] == "MEDIUM"
    assert rep["high_layers_present"] == []


def test_bare_number_accepted():
    r = _run(["--layers", "8"])
    assert r.returncode == 0
    assert "HIGH" in r.stdout  # L8 is structural


def test_fail_unrecognised_layer():
    # honest FAIL: garbage must not silently classify MEDIUM
    r = _run(["--layers", "L99,banana"])
    assert r.returncode == 1
    assert "FAIL" in r.stdout


def test_usage_error_no_args():
    r = _run([])
    assert r.returncode == 2


def test_file_input_affected_layers(tmp_path):
    bf = tmp_path / "b.yaml"
    bf.write_text("title: drop register-table rows\n"
                  "affected_layers:\n  - L4\n  - L2\n")
    out = tmp_path / "o.json"
    r = _run(["--file", str(bf), "--json", str(out)])
    assert r.returncode == 0
    rep = json.loads(out.read_text())
    assert rep["severity"] == "HIGH"


def test_file_input_scalar_layer_medium(tmp_path):
    bf = tmp_path / "b.yaml"
    bf.write_text("title: missing clock note\nlayer: L1\n")
    r = _run(["--file", str(bf)])
    assert r.returncode == 0
    assert "MEDIUM" in r.stdout


def test_file_missing_usage_error(tmp_path):
    r = _run(["--file", str(tmp_path / "nope.yaml")])
    assert r.returncode == 2


def test_file_with_no_layer_field_fails(tmp_path):
    bf = tmp_path / "b.yaml"
    bf.write_text("title: nothing here\npattern: vague\n")
    r = _run(["--file", str(bf)])
    assert r.returncode == 1
