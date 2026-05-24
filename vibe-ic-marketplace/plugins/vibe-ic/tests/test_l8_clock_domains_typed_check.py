#!/usr/bin/env python3
"""Tests for l8_clock_domains_typed_check.py (Wave 38 / B4)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent
        / "programs" / "l8_clock_domains_typed_check.py")


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _make(tmp_path, l8=None, doc_text=None):
    proj = tmp_path / "p"
    (proj / "phase1" / "input_doc").mkdir(parents=True)
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    if doc_text is not None:
        (proj / "phase1" / "input_doc" / "frs.txt").write_text(doc_text)
    if l8 is not None:
        (proj / "phase1" / "generated_docs" / "L8_TIMING_WAVEFORM.json").write_text(
            json.dumps(l8)
        )
    return proj


def test_skip_when_single_clock(tmp_path):
    proj = _make(tmp_path, doc_text="core runs at 5 MHz")
    r = _run(proj)
    assert r.returncode == 2


def test_fail_when_multi_clock_but_no_typed_clocks(tmp_path):
    proj = _make(
        tmp_path,
        doc_text="master clock 5 MHz, derived 1.25 MHz, baud 312.5 kHz",
        l8={"timing": {"bit_period_ns": 800}},
    )
    r = _run(proj)
    assert r.returncode == 1
    assert "clock_domains" in r.stdout


def test_pass_with_typed_clocks(tmp_path):
    # v1.6.89 (#21 Bug 2): doc_text must carry clock-keyword context
    # in the ±50-char window around each freq mention so the gate-
    # side _is_real_clock_freq filter accepts both as real clock
    # frequencies. Legacy form `master 5 MHz, derived 1.25 MHz` is
    # not enough — `master` / `derived` are not in the clock-
    # keyword set. Add `clock` adjacency.
    proj = _make(
        tmp_path,
        doc_text="master clock 5 MHz, derived clock 1.25 MHz",
        l8={"clock_domains": [
            {"name": "clk_5m", "freq_mhz": 5.0, "role": "master"},
            {"name": "clk_1m25", "freq_mhz": 1.25,
             "source": "clk_5m", "divider": 4},
        ]},
    )
    r = _run(proj)
    assert r.returncode == 0
    assert "PASS" in r.stdout


def test_pass_with_dict_form_clocks(tmp_path):
    # v1.6.89 (#21 Bug 2): see test_pass_with_typed_clocks comment.
    proj = _make(
        tmp_path,
        doc_text="primary clock 50 MHz, derived clock 5 MHz",
        l8={"clocks": {
            "main_clk": {"freq_hz": 50_000_000, "role": "system"},
            "core_clk": {"freq_mhz": 5.0, "source": "main_clk"},
        }},
    )
    r = _run(proj)
    assert r.returncode == 0


def test_fail_when_clocks_too_shallow(tmp_path):
    # v1.6.89 (#21 Bug 2): see test_pass_with_typed_clocks comment.
    proj = _make(
        tmp_path,
        doc_text="primary clock 50 MHz and core clock 5 MHz",
        l8={"clocks": [{"name": "main_clk"}]},
    )
    r = _run(proj)
    assert r.returncode == 1


# Wave 43 (v0.119.75) — ic_class_profile SKIP case.
def test_skip_on_bare_fpga(tmp_path):
    """Bare-FPGA scaffolds use a single eval-board clock."""
    proj = tmp_path / "p"
    proj.mkdir(parents=True, exist_ok=True)
    # facts.yaml without L1/L2/L3 -> bare_fpga class.
    (proj / "facts.yaml").write_text("name: my_fpga_eval\n")
    r = _run(proj)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "SKIP" in r.stdout
    assert "ic_class=bare_fpga" in r.stdout
