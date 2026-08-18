#!/usr/bin/env python3
"""Tests for phase1_rotation_state_advance.py"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent
        / "phase1_rotation_state_advance.py")


def _run(args, **kw):
    return subprocess.run([sys.executable, str(PROG)] + args,
                          capture_output=True, text=True, **kw)


def test_help():
    r = _run(["--help"])
    assert r.returncode == 0


# ---- build ----------------------------------------------------------

def test_build_pass_readme_and_prompt(tmp_path):
    (tmp_path / "ic_b").mkdir()
    (tmp_path / "ic_b" / "README.md").write_text("# b")
    (tmp_path / "ic_a").mkdir()
    (tmp_path / "ic_a" / "input").mkdir()
    (tmp_path / "ic_a" / "input" / "prompt.md").write_text("# a")
    # a dir with neither prompt is excluded
    (tmp_path / "_notes").mkdir()
    (tmp_path / "_notes" / "x.txt").write_text("ignore")
    out = tmp_path / "r.json"
    r = _run(["build", "--target", str(tmp_path), "--json", str(out)])
    assert r.returncode == 0, r.stdout + r.stderr
    rep = json.loads(out.read_text())
    # sorted: ic_a before ic_b; _notes excluded
    assert rep["ic_rotation"] == ["ic_a", "ic_b"]
    assert rep["rotation_length"] == 2
    assert rep["verdict"] == "PASS"


def test_build_fail_empty_folder(tmp_path):
    # honest FAIL: no IC subdir with a prompt
    (tmp_path / "_misc").mkdir()
    r = _run(["build", "--target", str(tmp_path)])
    assert r.returncode == 1
    assert "FAIL" in r.stdout


def test_build_usage_error_missing_dir(tmp_path):
    r = _run(["build", "--target", str(tmp_path / "nope")])
    assert r.returncode == 2


# ---- advance --------------------------------------------------------

def test_advance_normal_no_wrap(tmp_path):
    out = tmp_path / "a.json"
    r = _run(["advance", "--current-index", "0", "--count", "3",
              "--passes", "1", "--json", str(out)])
    assert r.returncode == 0
    rep = json.loads(out.read_text())
    assert rep["next_index"] == 1
    assert rep["wrapped"] is False
    assert rep["rotation_passes_completed"] == 1


def test_advance_wrap_increments_passes(tmp_path):
    out = tmp_path / "a.json"
    r = _run(["advance", "--current-index", "2", "--count", "3",
              "--passes", "1", "--json", str(out)])
    assert r.returncode == 0
    rep = json.loads(out.read_text())
    assert rep["next_index"] == 0
    assert rep["wrapped"] is True
    assert rep["rotation_passes_completed"] == 2


def test_advance_fail_count_zero():
    # honest FAIL: rotation of length 0 cannot advance
    r = _run(["advance", "--current-index", "0", "--count", "0"])
    assert r.returncode == 1
    assert "FAIL" in r.stdout


def test_advance_fail_index_out_of_range():
    r = _run(["advance", "--current-index", "5", "--count", "3"])
    assert r.returncode == 1
    assert "out of range" in r.stdout


def test_advance_garbage_numeric_arg_usage_error():
    r = _run(["advance", "--current-index", "x", "--count", "3"])
    assert r.returncode == 2
