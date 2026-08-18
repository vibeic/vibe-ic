#!/usr/bin/env python3
"""Tests for sata_state_extractor.py — SATA state-machine literal picker
(#36 Bug 9, L9 sub-portion).

Pins the REAL behavior of extract_sata_state_literals_from_readme:
  * PASS — README prose mentioning >=2 distinct SATA spec literals
    (OOB / COMINIT / COMWAKE / K28.5 / ALIGN inserter) yields
    L9.submodules-shaped dicts with the canonical name + role.
  * FAIL/guard — the cluster floor (_MIN_HITS_PER_FILE=2): a single
    distinct literal is rejected (returns []).
  * Edge — None / empty / no-literal text returns []; case-sensitive
    OOB tokens; dedup by canonical name.

Chip-AGNOSTIC: tokens are SATA-standard, not chip-specific.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROG = _HERE.parent / "sata_state_extractor.py"

_spec = importlib.util.spec_from_file_location("sata_state_extractor", _PROG)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


# ----------------------------------------------------------------------
# PASS — >=2 distinct SATA literals
# ----------------------------------------------------------------------
def test_pass_oob_and_special_char():
    readme = (
        "The OOB initiation sequence drives COMINIT then COMWAKE.\n"
        "Framing uses the K28.5 ALIGN comma character.\n"
    )
    out = mod.extract_sata_state_literals_from_readme(readme)
    names = {d["name"] for d in out}
    assert "oob_sequencer" in names
    assert "oob_cominit" in names
    assert "oob_comwake" in names
    assert "k28p5_special_char" in names
    # role + evidence_line + matched_token present on every hit.
    for d in out:
        assert d["role"]
        assert isinstance(d["evidence_line"], int)
        assert d["matched_token"]


def test_pass_primitive_inserters():
    readme = (
        "An ALIGN inserter emits ALIGN primitives onto the lane.\n"
        "A CONT inserter handles CONT primitives.\n"
    )
    out = mod.extract_sata_state_literals_from_readme(readme)
    names = {d["name"] for d in out}
    assert "align_inserter" in names
    assert "cont_inserter" in names


# ----------------------------------------------------------------------
# FAIL/guard — cluster floor
# ----------------------------------------------------------------------
def test_single_literal_rejected():
    """One distinct literal is below _MIN_HITS_PER_FILE (=2) → []."""
    readme = "There is an OOB sequence here and nothing else relevant.\n"
    assert mod.extract_sata_state_literals_from_readme(readme) == []
    assert mod._MIN_HITS_PER_FILE == 2


def test_oob_tokens_case_sensitive():
    """OOB-family tokens are ALL_CAPS spec terms; lowercase 'cominit' /
    'comwake' must NOT match, so this file has zero hits → []."""
    readme = "the cominit and comwake words are lowercase prose here.\n"
    assert mod.extract_sata_state_literals_from_readme(readme) == []


# ----------------------------------------------------------------------
# Edge / dedup
# ----------------------------------------------------------------------
def test_none_and_empty_return_empty():
    assert mod.extract_sata_state_literals_from_readme(None) == []
    assert mod.extract_sata_state_literals_from_readme("") == []


def test_no_literals_return_empty():
    assert mod.extract_sata_state_literals_from_readme(
        "Just generic README prose with no SATA spec tokens.\n") == []


def test_dedup_same_literal_repeated():
    """Same canonical literal repeated does NOT clear the floor by
    itself; it dedups to one name. Two distinct literals needed."""
    readme = "OOB ... OOB ... OOB appears thrice but is one submodule.\n"
    assert mod.extract_sata_state_literals_from_readme(readme) == []
    # but adding a distinct second literal clears the floor with 2 names.
    readme2 = readme + "Also K28.5 comma.\n"
    out = mod.extract_sata_state_literals_from_readme(readme2)
    assert sorted(d["name"] for d in out) == [
        "k28p5_special_char", "oob_sequencer"]
