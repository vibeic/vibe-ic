#!/usr/bin/env python3
"""Tests for fpga_sta_negative_slack_check.py — Wave 24 / v0.119.56."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent
        / "fpga_sta_negative_slack_check.py")


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


_GOOD_SUMMARY = (
    "------------------------------------------------------------\n"
    "Timing Analyzer Summary\n"
    "------------------------------------------------------------\n\n"
    "Type  : Slow 1200mV 85C Model Setup 'clk_50'\n"
    "Slack : 1.234\n"
    "TNS   : 0.000\n\n"
    "Type  : Slow 1200mV 85C Model Hold 'clk_50'\n"
    "Slack : 0.345\n"
    "TNS   : 0.000\n\n"
    "Type  : Slow 1200mV 0C Model Setup 'clk_50'\n"
    "Slack : 1.500\n\n"
    "Type  : Slow 1200mV 0C Model Hold 'clk_50'\n"
    "Slack : 0.300\n\n"
    "Type  : Fast 1200mV 0C Model Setup 'clk_50'\n"
    "Slack : 4.123\n"
    "Type  : Fast 1200mV 0C Model Hold 'clk_50'\n"
    "Slack : 0.150\n"
)


def _make_project(tmp_path: Path, sta_text: str | None) -> Path:
    proj = tmp_path / "proj"
    (proj / "phase2" / "stage1" / "fpga" / "output_files").mkdir(parents=True)
    if sta_text is not None:
        (proj / "phase2" / "stage1" / "fpga" / "output_files" / "design.sta.summary").write_text(sta_text)
    return proj


def test_help():
    r = subprocess.run([sys.executable, str(PROG), "--help"],
                       capture_output=True, text=True)
    assert r.returncode == 0
    assert "STA" in r.stdout or "slack" in r.stdout.lower()


def test_all_corners_positive_pass(tmp_path):
    proj = _make_project(tmp_path, _GOOD_SUMMARY)
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_setup_slack_negative_fail(tmp_path):
    bad = _GOOD_SUMMARY.replace("Slack : 1.500", "Slack : -5.5")
    proj = _make_project(tmp_path, bad)
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "STA_NEGATIVE_SLACK" in r.stdout
    assert "-5.5" in r.stdout
    assert "Setup" in r.stdout


def test_hold_slack_negative_fail(tmp_path):
    bad = _GOOD_SUMMARY.replace("Slack : 0.300", "Slack : -0.250")
    proj = _make_project(tmp_path, bad)
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "STA_NEGATIVE_SLACK" in r.stdout
    assert "Hold" in r.stdout


def test_no_sta_summary_skip(tmp_path):
    proj = _make_project(tmp_path, sta_text=None)
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SKIP" in r.stdout


def test_with_waiver_pass(tmp_path):
    bad = _GOOD_SUMMARY.replace("Slack : 1.500", "Slack : -5.5")
    proj = _make_project(tmp_path, bad)
    (proj / "waivers.json").write_text(json.dumps({
        "fpga_negative_slack_acceptable":
            "Lab bring-up build only; documented timing-violation "
            "exposure plan in TICKET-1234; not a tape-out candidate.",
    }))
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS_WITH_WAIVER" in r.stdout


def test_mpw_negative_does_not_fail(tmp_path):
    """Quartus MPW (Minimum Pulse Width) negative slack is benign."""
    s = (_GOOD_SUMMARY
         + "\nType  : Slow 1200mV 85C Model Minimum Pulse Width 'clk_50'\n"
           "Slack : -3.000\n")
    proj = _make_project(tmp_path, s)
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout
