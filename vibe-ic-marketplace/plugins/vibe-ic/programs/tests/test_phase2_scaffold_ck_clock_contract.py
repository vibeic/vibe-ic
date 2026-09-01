"""Bidirectional contract for switched-capacitor clock spellings.

Set ``VIBEIC_PHASE2_SCAFFOLD_SUBJECT`` to run the same assertions against a
different checkout.  That makes the current-main negative control execute the
substantive assertions instead of passing because a candidate-only test module
is absent.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest


DEFAULT_PROGRAMS = Path(__file__).resolve().parents[1]
PROGRAMS = Path(os.environ.get(
    "VIBEIC_PHASE2_SCAFFOLD_SUBJECT", str(DEFAULT_PROGRAMS))).resolve()
sys.path.insert(0, str(PROGRAMS))
SPEC = importlib.util.spec_from_file_location(
    "phase2_scaffold_gen_subject", PROGRAMS / "phase2_scaffold_gen.py")
assert SPEC is not None and SPEC.loader is not None
SCAFFOLD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCAFFOLD)


@pytest.mark.parametrize("name", [
    "ck", "ck1", "ck4", "ck5", "ck6",
    "phi", "phi1", "phi2",
    "clk", "PCLK", "BusClock", "SCK_clk",
])
def test_sc_and_conventional_clock_names_are_recognised(name):
    assert SCAFFOLD._is_clock_name(name), name


@pytest.mark.parametrize("name", [
    "ack", "block_ready", "check_en", "ckt", "phase_out", "data",
])
def test_non_clocks_are_not_swept_in(name):
    assert not SCAFFOLD._is_clock_name(name), name


def test_ck_ports_do_not_cause_a_synthetic_clk():
    l9 = {"top_ports": [
        {"name": "ck4", "direction": "input"},
        {"name": "out1", "direction": "output"},
    ]}
    names = [item["name"] for item in SCAFFOLD.derive_signals({}, l9)]
    assert "ck4" in names
    assert "clk" not in names
