#!/usr/bin/env python3
"""v0.1.86 — _is_real_port_token accepts legitimate 2-char control ports
(cs/we/oe/rd/wr/en/ce) — only 1-char tokens are rejected by length. The other
reject filters (power rails, reserved words, version codes) still screen noise.
Regression target: sha256 `cs`/`we` were dropped by the old ≥3 floor, breaking
l9_rtl_pin_consistency."""
from __future__ import annotations
import sys
from pathlib import Path
PROG_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG_DIR))
import phase1_doc_one_shot_runner as P  # noqa: E402


def test_two_char_control_ports_accepted():
    for tok in ("cs", "we", "oe", "rd", "wr", "en", "ce"):
        assert P._is_real_port_token(tok), f"{tok!r} should be a valid port"


def test_one_char_still_rejected():
    assert not P._is_real_port_token("a")
    assert not P._is_real_port_token("x")


def test_power_rails_still_rejected():
    for tok in ("VDD", "VSS", "GND", "VCC"):
        assert not P._is_real_port_token(tok)


def test_version_codes_still_rejected():
    # 2-char letter+digit version codes must still be screened
    assert not P._is_real_port_token("E4")


def test_normal_ports_still_accepted():
    for tok in ("clk", "reset_n", "address", "read_data"):
        assert P._is_real_port_token(tok)
