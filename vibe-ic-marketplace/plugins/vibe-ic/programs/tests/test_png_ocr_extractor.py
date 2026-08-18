#!/usr/bin/env python3
"""Tests for png_ocr_extractor.py — Tier-2 PNG-OCR submodule fallback
(#36 Bug 3).

Pins the REAL decision logic without needing the Tesseract binary:
  * Feature-flag gate — is_ocr_feature_enabled() honours PHASE2A_ENABLE_OCR
    only for truthy values, and is otherwise INERT.
  * Graceful degradation — is_ocr_runtime_available() is False whenever
    the flag is off OR pytesseract/PIL are not importable; the top-level
    extractor then returns [] (the real "PNG-only ICs lose nothing worse
    than the existing behavior" contract).
  * Name-extraction floor — _extract_names_from_ocr_text applies the
    snake_case structural floor (>=1 underscore, >=4 chars) AND the
    generic-name deny list, and dedups.
  * Edge — project=None returns [].
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROG = _HERE.parent / "png_ocr_extractor.py"

_spec = importlib.util.spec_from_file_location("png_ocr_extractor", _PROG)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


# ----------------------------------------------------------------------
# feature-flag gate
# ----------------------------------------------------------------------
def test_feature_flag_off_by_default(monkeypatch):
    monkeypatch.delenv(mod.OCR_FEATURE_FLAG, raising=False)
    assert mod.is_ocr_feature_enabled() is False


def test_feature_flag_truthy_values(monkeypatch):
    for v in ("1", "true", "YES", "On"):
        monkeypatch.setenv(mod.OCR_FEATURE_FLAG, v)
        assert mod.is_ocr_feature_enabled() is True


def test_feature_flag_falsy_values(monkeypatch):
    for v in ("0", "false", "no", "", "  ", "maybe"):
        monkeypatch.setenv(mod.OCR_FEATURE_FLAG, v)
        assert mod.is_ocr_feature_enabled() is False


# ----------------------------------------------------------------------
# graceful degradation — runtime availability
# ----------------------------------------------------------------------
def test_runtime_unavailable_when_flag_off(monkeypatch):
    monkeypatch.delenv(mod.OCR_FEATURE_FLAG, raising=False)
    assert mod.is_ocr_runtime_available() is False


def test_extractor_noop_when_flag_off(monkeypatch, tmp_path):
    """The whole point of the gate: even with PNGs present, OCR is INERT
    (returns []) unless the operator opts in AND the deps exist."""
    monkeypatch.delenv(mod.OCR_FEATURE_FLAG, raising=False)
    docs = tmp_path / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "arch.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    assert mod.extract_submodules_from_png_diagrams(tmp_path) == []


def test_extractor_none_project_returns_empty():
    assert mod.extract_submodules_from_png_diagrams(None) == []


# ----------------------------------------------------------------------
# name-extraction floor + deny list (pure logic, no OCR binary)
# ----------------------------------------------------------------------
def test_name_floor_requires_underscore_and_length():
    text = "rx_classifier tx_phy ab x_y core dma_engine"
    names = mod._extract_names_from_ocr_text(text)
    # snake_case >=4 chars with an underscore.
    assert "rx_classifier" in names
    assert "tx_phy" in names
    assert "dma_engine" in names
    # 'ab' (no underscore, too short), 'core' (no underscore),
    # 'x_y' (only 3 chars) are all rejected.
    assert "ab" not in names
    assert "core" not in names
    assert "x_y" not in names


def test_generic_names_denied():
    text = "test_bench tb_top my_module real_block"
    names = mod._extract_names_from_ocr_text(text)
    assert "real_block" in names
    for denied in ("test_bench", "tb_top", "my_module"):
        assert denied not in names


def test_name_dedup():
    text = "alu_core alu_core alu_core other_unit"
    names = mod._extract_names_from_ocr_text(text)
    assert names.count("alu_core") == 1
    assert "other_unit" in names
