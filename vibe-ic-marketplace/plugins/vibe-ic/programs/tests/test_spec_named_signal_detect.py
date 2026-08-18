#!/usr/bin/env python3
"""Tests for spec_named_signal_detect — the named-signal-preservation advisory."""
import importlib.util
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
_spec = importlib.util.spec_from_file_location(
    "spec_named_signal_detect", _PROGRAMS / "spec_named_signal_detect.py")
_M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_M)
detect = _M.detect_named_signals


def test_fires_on_backtick_named_signals():
    # interrupt_controller shape: TB peeks internal `interrupt_idx`
    p = ("The controller drives `cpu_interrupt` and clears the serviced IRQ on "
         "`cpu_ack`. Internally, `interrupt_idx` holds the current index and "
         "`interrupt_mask` gates requests.")
    r = detect(p)
    assert r["has_named_signals"] is True
    assert "interrupt_idx" in r["named_signals"]
    assert r["requirement"] and "no child object" in r["requirement"]


def test_includes_internal_signals_not_just_ports():
    p = ("Compute `parity` from the data word. The `data_reg` shift register and "
         "the `bit_counter` track reception.")
    r = detect(p)
    assert set(r["named_signals"]) >= {"parity", "data_reg", "bit_counter"}


def test_keywords_and_clk_reset_excluded():
    p = ("A `module` with `input` `clk` and `reset`, plus `data_valid`, "
         "`frame_start`, `byte_count`.")
    r = detect(p)
    for kw in ("module", "input", "clk", "reset"):
        assert kw not in r["named_signals"]
    assert set(r["named_signals"]) >= {"data_valid", "frame_start", "byte_count"}


def test_fewer_than_three_does_not_fire():
    r = detect("Drive `foo` and `bar`.")
    assert r["has_named_signals"] is False
    assert r["requirement"] is None


def test_no_backticks_does_not_fire():
    r = detect("Design an 8-bit counter with synchronous reset and enable.")
    assert r["has_named_signals"] is False


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
