#!/usr/bin/env python3
"""Unit tests for programs/_fpga_stub_waiver.py.

Pins the real decision logic of the shared FPGA-prototype-stage analog
stub waiver helper: the waiver is active iff the `--allow-fpga-stub`
CLI flag is set OR the PHASE23_ANALOG_FPGA_STUB env var is truthy.
Logic-pinned (it has a real OR/truthy decision, not a constant).
"""
from __future__ import annotations

import argparse

import _fpga_stub_waiver as mod


# ---------------------------------------------------------------------------
# env-var path
# ---------------------------------------------------------------------------
def test_default_off_when_no_env_no_args(monkeypatch):
    monkeypatch.delenv(mod._ENV_VAR, raising=False)
    assert mod.fpga_stub_waiver_active() is False


def test_env_truthy_values_activate(monkeypatch):
    for v in ("1", "true", "yes", "on", "TRUE", "Yes", " on "):
        monkeypatch.setenv(mod._ENV_VAR, v)
        assert mod.fpga_stub_waiver_active() is True, v


def test_env_falsy_values_stay_off(monkeypatch):
    for v in ("0", "false", "no", "off", ""):
        monkeypatch.setenv(mod._ENV_VAR, v)
        assert mod.fpga_stub_waiver_active() is False, v


# ---------------------------------------------------------------------------
# CLI-flag path
# ---------------------------------------------------------------------------
def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    mod.add_fpga_stub_argparse(ap)
    return ap


def test_add_argparse_registers_dest():
    ns = _parser().parse_args(["--allow-fpga-stub"])
    assert ns.allow_fpga_stub is True
    ns2 = _parser().parse_args([])
    assert ns2.allow_fpga_stub is False


def test_flag_set_activates_even_without_env(monkeypatch):
    monkeypatch.delenv(mod._ENV_VAR, raising=False)
    ns = _parser().parse_args(["--allow-fpga-stub"])
    assert mod.fpga_stub_waiver_active(ns) is True


def test_flag_unset_and_no_env_stays_off(monkeypatch):
    monkeypatch.delenv(mod._ENV_VAR, raising=False)
    ns = _parser().parse_args([])
    assert mod.fpga_stub_waiver_active(ns) is False


def test_env_overrides_missing_flag(monkeypatch):
    # args present but flag false, env truthy => still active (OR logic)
    monkeypatch.setenv(mod._ENV_VAR, "1")
    ns = _parser().parse_args([])
    assert mod.fpga_stub_waiver_active(ns) is True


# ---------------------------------------------------------------------------
# rationale string
# ---------------------------------------------------------------------------
def test_reason_mentions_fpga_prototype_and_signoff():
    r = mod.fpga_stub_reason()
    assert "FPGA prototype" in r
    assert "foundry_handoff" in r
    assert "--allow-fpga-stub" in r
