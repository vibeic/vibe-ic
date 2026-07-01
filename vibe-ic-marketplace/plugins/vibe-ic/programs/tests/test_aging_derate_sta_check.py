#!/usr/bin/env python3
"""Tests for aging_derate_sta_check.py — aging-corner STA sign-off gate.

Covers PASS (meets aged), FAIL (violates aged incl. the classic
meets-fresh-but-fails-aged catch), and the honest SKIP edges: absent /
unreadable report, no-aging-evidence (a fresh report mislabeled as aging),
no slack value, bad JSON. Exit codes: 0 PASS / 1 FAIL / 2 IO-or-arg / 3 SKIP.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "aging_derate_sta_check.py"


def _run(*args) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(PROG), *[str(a) for a in args]]
    return subprocess.run(cmd, capture_output=True, text=True)


def _write(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data))
    return path


# ----------------------------------------------------------------- PASS

def test_pass_aged_slack_positive(tmp_path):
    rpt = _write(tmp_path / "aging.json",
                 {"worst_slack_ns": 0.20, "aging_corner": "ss_aging_10yr"})
    r = _run(rpt, "--json", tmp_path / "out.json")
    assert r.returncode == 0
    rep = json.loads((tmp_path / "out.json").read_text())
    assert rep["verdict"] == "PASS"
    assert rep["measured"]["aging_worst_slack_ns"] == 0.20


def test_pass_aged_meets_and_fresh_meets(tmp_path):
    aged = _write(tmp_path / "aged.json", {"worst_slack_ns": 0.05, "is_aging": True})
    fresh = _write(tmp_path / "fresh.json", {"worst_slack_ns": 0.40})
    r = _run(aged, "--fresh", fresh)
    assert r.returncode == 0
    rep = json.loads(r.stdout)
    assert rep["measured"]["fresh_worst_slack_ns"] == 0.40
    assert rep["measured"]["aging_delta_ns"] == -0.35  # aged slower than fresh


def test_pass_text_report_worst_slack(tmp_path):
    rpt = _write(tmp_path / "aged.rpt",
                 "Aging corner ss_aging_10yr\nworst slack 0.133\n")
    assert _run(rpt).returncode == 0


def test_pass_assume_aging_bypasses_evidence(tmp_path):
    # No aging marker, but caller asserts it via --assume-aging.
    rpt = _write(tmp_path / "sta.json", {"worst_slack_ns": 0.10})
    assert _run(rpt).returncode == 3            # SKIP without the flag
    assert _run(rpt, "--assume-aging").returncode == 0  # PASS with it


def test_pass_ps_key_conversion(tmp_path):
    # 200 ps = 0.2 ns > 0
    rpt = _write(tmp_path / "aging.json",
                 {"worst_slack_ps": 200.0, "aging": True})
    assert _run(rpt).returncode == 0


def test_pass_directory_discovery(tmp_path):
    _write(tmp_path / "reports" / "sta" / "aging_10yr.rpt",
           "aging derate applied\nworst slack 0.08\n")
    assert _run(tmp_path).returncode == 0


# ----------------------------------------------------------------- FAIL

def test_fail_aged_slack_negative(tmp_path):
    rpt = _write(tmp_path / "aging.json",
                 {"worst_slack_ns": -0.12, "aging_corner": "ss_nbti_eol"})
    r = _run(rpt)
    assert r.returncode == 1
    rep = json.loads(r.stdout)
    assert rep["verdict"] == "FAIL"
    assert any(f["rule"] == "AGING_TIMING_VIOLATED" for f in rep["findings"])


def test_fail_meets_fresh_but_fails_aged(tmp_path):
    """The signature aging catch: fresh MET, aged VIOLATED."""
    aged = _write(tmp_path / "aged.json", {"worst_slack_ns": -0.15, "is_aging": True})
    fresh = _write(tmp_path / "fresh.json", {"worst_slack_ns": 0.30})
    r = _run(aged, "--fresh", fresh)
    assert r.returncode == 1
    rep = json.loads(r.stdout)
    msg = rep["findings"][-1]["message"]
    assert "MET timing fresh" in msg and "FAILS aged" in msg


def test_fail_tight_margin(tmp_path):
    # aged slack 0.05 ns passes margin 0 but fails a 0.1 ns house margin.
    rpt = _write(tmp_path / "aging.json",
                 {"worst_slack_ns": 0.05, "aging_corner": "aging_ss"})
    assert _run(rpt).returncode == 0
    assert _run(rpt, "--margin-ns", "0.1").returncode == 1


def test_fail_text_violated_tag(tmp_path):
    rpt = _write(tmp_path / "aged.rpt",
                 "ss_aging_10yr corner\n-0.42  slack (VIOLATED)\n")
    assert _run(rpt).returncode == 1


# --------------------------------------------------- HONEST SKIP / §4.05

def test_skip_no_aging_evidence_fresh_mislabeled(tmp_path):
    """§4.05: a fresh report with positive slack must NOT pass as aging."""
    rpt = _write(tmp_path / "sta.json", {"worst_slack_ns": 0.50})
    r = _run(rpt)
    assert r.returncode == 3           # SKIP, NOT 0/PASS
    rep = json.loads(r.stdout)
    assert rep["verdict"] == "SKIP"
    assert rep["skip_reason"] == "no_aging_evidence"


def test_skip_absent_report_in_dir(tmp_path):
    """A project dir with no aging report → honest SKIP (open-PDK case)."""
    (tmp_path / "reports").mkdir()
    _write(tmp_path / "reports" / "fresh_sta.rpt", "worst slack 0.9\n")
    r = _run(tmp_path)
    assert r.returncode == 3
    rep = json.loads(r.stdout)
    assert rep["skip_reason"] == "aging_report_absent"


def test_skip_no_slack_value(tmp_path):
    rpt = _write(tmp_path / "aging.json",
                 {"aging_corner": "ss_aging_10yr", "tool": "OpenSTA"})
    r = _run(rpt)
    assert r.returncode == 3
    assert json.loads(r.stdout)["skip_reason"] == "no_aging_slack_value"


def test_skip_bad_json(tmp_path):
    rpt = _write(tmp_path / "aging.json", "{not valid,,,}")
    r = _run(rpt)
    assert r.returncode == 3
    assert json.loads(r.stdout)["skip_reason"] == "aging_report_unparseable"


def test_skip_never_conflated_with_pass(tmp_path):
    """SKIP verdicts never carry a PASS/rc-0 — the whole §4.05 point."""
    for data in ({"worst_slack_ns": 0.5},                       # no evidence
                 {"aging_corner": "ss_aging_10yr"}):            # no slack
        rpt = _write(tmp_path / "x.json", data)
        r = _run(rpt)
        assert r.returncode == 3
        assert json.loads(r.stdout)["verdict"] == "SKIP"


# ------------------------------------------------------------ IO / arg (rc 2)

def test_exit2_missing_explicit_path(tmp_path):
    assert _run(tmp_path / "does_not_exist.json").returncode == 2


def test_exit2_fresh_path_missing(tmp_path):
    aged = _write(tmp_path / "aging.json",
                  {"worst_slack_ns": 0.1, "aging": True})
    assert _run(aged, "--fresh", tmp_path / "nope.json").returncode == 2
