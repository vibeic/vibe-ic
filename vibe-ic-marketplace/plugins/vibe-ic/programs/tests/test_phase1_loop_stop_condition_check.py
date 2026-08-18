#!/usr/bin/env python3
"""Tests for phase1_loop_stop_condition_check.py"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent
        / "phase1_loop_stop_condition_check.py")


def _run(args, **kw):
    return subprocess.run([sys.executable, str(PROG)] + args,
                          capture_output=True, text=True, **kw)


def _state(tmp_path, **over):
    s = {
        "rotation_passes_completed": 2,
        "per_ic_last_verdict": {"ic_a": "PASS", "ic_b": "SKIP_REFERENCE"},
    }
    s.update(over)
    p = tmp_path / "state.json"
    p.write_text(json.dumps(s))
    return p


def test_help():
    r = _run(["--help"])
    assert r.returncode == 0


def test_stop_all_clauses(tmp_path):
    sp = _state(tmp_path)
    out = tmp_path / "o.json"
    r = _run(["--state", str(sp), "--open-organic-issues", "0",
              "--json", str(out)])
    assert r.returncode == 0, r.stdout
    rep = json.loads(out.read_text())
    assert rep["stop"] is True
    assert rep["decision"] == "STOP"


def test_continue_open_issue(tmp_path):
    sp = _state(tmp_path)
    r = _run(["--state", str(sp), "--open-organic-issues", "1"])
    assert r.returncode == 1
    assert "CONTINUE" in r.stdout
    assert "OPEN" in r.stdout


def test_continue_not_enough_passes(tmp_path):
    sp = _state(tmp_path, rotation_passes_completed=1)
    r = _run(["--state", str(sp), "--open-organic-issues", "0"])
    assert r.returncode == 1
    assert "passes" in r.stdout.lower()


def test_continue_dirty_verdict(tmp_path):
    sp = _state(tmp_path,
                per_ic_last_verdict={"ic_a": "PASS", "ic_b": "WARN"})
    r = _run(["--state", str(sp), "--open-organic-issues", "0"])
    assert r.returncode == 1
    assert "ic_b" in r.stdout


def test_continue_empty_verdict_map_is_not_clean(tmp_path):
    # edge: a never-audited rotation must NOT STOP
    sp = _state(tmp_path, per_ic_last_verdict={})
    r = _run(["--state", str(sp), "--open-organic-issues", "0"])
    assert r.returncode == 1


def test_skip_low_tokens_counts_as_clean(tmp_path):
    sp = _state(tmp_path,
                per_ic_last_verdict={"ic_a": "PASS",
                                     "ic_b": "SKIP_LOW_TOKENS"})
    r = _run(["--state", str(sp), "--open-organic-issues", "0"])
    assert r.returncode == 0


def test_missing_state_file_usage_error(tmp_path):
    r = _run(["--state", str(tmp_path / "nope.json"),
              "--open-organic-issues", "0"])
    assert r.returncode == 2


def test_garbage_state_file_usage_error(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("not json {{{")
    r = _run(["--state", str(bad), "--open-organic-issues", "0"])
    assert r.returncode == 2


def test_negative_issue_count_usage_error(tmp_path):
    sp = _state(tmp_path)
    r = _run(["--state", str(sp), "--open-organic-issues", "-1"])
    assert r.returncode == 2
