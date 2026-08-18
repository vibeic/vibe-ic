#!/usr/bin/env python3
"""Tests for sata_command_extractor.py — SATA/ATA L3.commands picker.

Pins the real extraction behavior:
  * Literal ATA/SATA command names map to the canonical opcode hex.
  * The README shorthand `<BASE>(_EXT)` synthesises BOTH base + _EXT.
  * A cluster floor (>= 2 distinct commands) prevents a lone mention in
    unrelated prose from emitting a SATA command set.
  * Empty / None / non-SATA input -> [].

logic-pinned.
"""
from __future__ import annotations

from sata_command_extractor import extract_sata_commands_from_readme as ex


# ── PASS: canonical opcodes + (_EXT) shorthand expansion ─────────────
def test_extracts_canonical_opcodes_and_ext_shorthand():
    txt = (
        "Supports READ_DMA(_EXT) and WRITE_DMA(_EXT).\n"
        "Also IDENTIFY_DEVICE for discovery.\n"
    )
    out = ex(txt)
    by_name = {h["name"]: h for h in out}
    # base + EXT variants both synthesised from the (_EXT) shorthand
    assert by_name["READ_DMA"]["hex"] == "0xC8"
    assert by_name["READ_DMA_EXT"]["hex"] == "0x25"
    assert by_name["WRITE_DMA"]["hex"] == "0xCA"
    assert by_name["WRITE_DMA_EXT"]["hex"] == "0x35"
    assert by_name["IDENTIFY_DEVICE"]["hex"] == "0xEC"
    # evidence line is 1-indexed and points at the literal mention
    assert by_name["IDENTIFY_DEVICE"]["evidence_line"] == 2


def test_plain_command_names_match():
    txt = "The core issues READ_FPDMA_QUEUED and WRITE_FPDMA_QUEUED commands."
    out = ex(txt)
    names = {h["name"] for h in out}
    assert names == {"READ_FPDMA_QUEUED", "WRITE_FPDMA_QUEUED"}
    assert {h["hex"] for h in out} == {"0x60", "0x61"}


# ── FAIL/floor: below cluster threshold -> empty ─────────────────────
def test_single_command_below_floor_returns_empty():
    # A lone READ_DMA mention in unrelated context is NOT a SATA set.
    assert ex("Only READ_DMA appears here in passing.") == []


def test_non_sata_text_returns_empty():
    assert ex("This is a UART core with a 16-byte FIFO and parity.") == []


# ── edge: empty / None input ─────────────────────────────────────────
def test_empty_string_returns_empty():
    assert ex("") == []


def test_none_returns_empty():
    assert ex(None) == []


# ── no duplicate emission of the same command ────────────────────────
def test_repeated_command_emitted_once():
    txt = "READ_DMA_EXT here.\nWRITE_DMA_EXT here.\nREAD_DMA_EXT again."
    out = ex(txt)
    names = [h["name"] for h in out]
    assert names.count("READ_DMA_EXT") == 1
    assert set(names) == {"READ_DMA_EXT", "WRITE_DMA_EXT"}
