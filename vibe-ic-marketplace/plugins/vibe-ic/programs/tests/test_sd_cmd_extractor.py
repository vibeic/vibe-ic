#!/usr/bin/env python3
"""Tests for sd_cmd_extractor.py — SD-spec CMD-table picker (#36 Bug 8).

Pins the REAL extraction behavior of extract_sd_cmds_from_readme:
  * PASS — a README with >=2 SD-CMD lines yields L3.opcodes-shaped dicts
    with correct hex (0x{idx:02X}), normalised name, raw_token, and the
    ACMD prefix preserved in the name.
  * FAIL/guard — the cluster floor (_MIN_HITS_PER_FILE=2): a single
    isolated CMDn line is rejected (returns []), the real defect this
    picker guards against (accidental CMD mention != a command list).
  * Edge — None / empty / no-CMD text returns []; idx>63 dropped.

Chip-AGNOSTIC: pure regex over markdown, no chip-class literal.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROG = _HERE.parent / "sd_cmd_extractor.py"

_spec = importlib.util.spec_from_file_location("sd_cmd_extractor", _PROG)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


# ----------------------------------------------------------------------
# PASS — a real SD-command list with >=2 hits
# ----------------------------------------------------------------------
def test_pass_capitalised_identifier_list():
    readme = (
        "## SD commands\n"
        "- CMD0 - GO_IDLE_STATE\n"
        "- CMD7 - SELECT_CARD\n"
        "- ACMD41 - SD_SEND_OP_COND\n"
    )
    out = mod.extract_sd_cmds_from_readme(readme)
    assert len(out) == 3
    by_token = {d["raw_token"]: d for d in out}
    # CMD0 → hex 0x00, name uppercased snake.
    assert by_token["CMD0"]["hex"] == "0x00"
    assert by_token["CMD0"]["name"] == "GO_IDLE_STATE"
    # CMD7 → 0x07.
    assert by_token["CMD7"]["hex"] == "0x07"
    assert by_token["CMD7"]["name"] == "SELECT_CARD"
    # ACMD41 → idx 41 = 0x29, ACMD_ prefix preserved in name.
    assert by_token["ACMD41"]["hex"] == "0x29"
    assert by_token["ACMD41"]["name"].startswith("ACMD_")
    # every hit carries an evidence line.
    assert all(isinstance(d["evidence_line"], int) for d in out)


def test_pass_lowercase_narrative_fallback():
    """Tier-2 lowercase narrative form (v1.6.116) slugified to snake."""
    readme = (
        "SD init\n"
        "CMD2     -identification\n"
        "CMD7     -select card\n"
    )
    out = mod.extract_sd_cmds_from_readme(readme)
    assert len(out) == 2
    names = {d["name"] for d in out}
    # slugified upper-snake-case from the narrative words.
    assert "IDENTIFICATION" in names
    assert "SELECT_CARD" in names


# ----------------------------------------------------------------------
# FAIL/guard — the cluster floor rejects a lone CMD mention
# ----------------------------------------------------------------------
def test_single_isolated_cmd_rejected():
    """One isolated CMDn line is below _MIN_HITS_PER_FILE (=2) and must
    be rejected as not-a-command-list (the real false-positive guard)."""
    readme = "Some prose mentioning CMD0 - reset once.\nNothing else.\n"
    assert mod.extract_sd_cmds_from_readme(readme) == []
    # confirm the floor constant is what we think it is.
    assert mod._MIN_HITS_PER_FILE == 2


def test_index_over_63_dropped():
    """CMD/ACMD index >63 is not a valid SD command and is dropped, so a
    file with two out-of-range indices falls below the floor → []."""
    readme = (
        "- CMD64 - BOGUS_ONE\n"
        "- CMD99 - BOGUS_TWO\n"
    )
    assert mod.extract_sd_cmds_from_readme(readme) == []


# ----------------------------------------------------------------------
# Edge / missing-data
# ----------------------------------------------------------------------
def test_none_and_empty_return_empty():
    assert mod.extract_sd_cmds_from_readme(None) == []
    assert mod.extract_sd_cmds_from_readme("") == []


def test_no_cmd_lines_return_empty():
    assert mod.extract_sd_cmds_from_readme(
        "# A README\nNo SD command table here at all.\n") == []


def test_dedup_same_cmd_listed_twice():
    """Same (prefix, idx, name) listed twice (TOC + body) → one entry,
    but two DISTINCT commands still clear the floor."""
    readme = (
        "- CMD0 - GO_IDLE_STATE\n"
        "- CMD0 - GO_IDLE_STATE\n"   # duplicate
        "- CMD7 - SELECT_CARD\n"
    )
    out = mod.extract_sd_cmds_from_readme(readme)
    tokens = sorted(d["raw_token"] for d in out)
    assert tokens == ["CMD0", "CMD7"]
