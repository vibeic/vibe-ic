#!/usr/bin/env python3
"""Tests for internal_vs_external_timing_check.py"""
from __future__ import annotations
import subprocess, sys, json
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "internal_vs_external_timing_check.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_with_waveform(tmp_path):
    # v0.2.55: an L8 with NO protocol/symbol timing content (empty waveforms,
    # no rx_*/tx_* group keys) is N/A for the RX/TX-split rule — a non-protocol
    # IC (e.g. a pure-digital arithmetic primitive) has nothing to split. The
    # gate VACUOUS_PASSes (rc=0) instead of FAILing. A genuinely half-duplex L8
    # that carries only the host-side half is still caught (see the rx_*/tx_*
    # fixtures in test_internal_vs_external_timing_check.py).
    wf = tmp_path / "L8_TIMING_WAVEFORM.json"
    wf.write_text(json.dumps({"waveforms": []}))
    r = _run([str(wf)])
    assert r.returncode == 0
    assert "VACUOUS_PASS" in r.stdout
