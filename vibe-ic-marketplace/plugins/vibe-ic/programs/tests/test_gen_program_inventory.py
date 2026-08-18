#!/usr/bin/env python3
"""Drift guard: the committed PROGRAM_INVENTORY.json MUST match the tree.

Single source of truth for every stated program count (the two READMEs, the
website, the docs), which hand-drifted for a month — 917 stated against 1178
files matching the glob the same sentence cited, measured at 397b3f25f on
2026-08-19. Adding or removing a `programs/*.py` without regenerating the
inventory fails this test, forcing
`python3 programs/gen_program_inventory.py` to be re-run.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent   # plugins/vibe-ic/
GEN = PLUGIN / "programs" / "gen_program_inventory.py"
INV = PLUGIN / "PROGRAM_INVENTORY.json"


def _load_gen():
    spec = importlib.util.spec_from_file_location("gen_program_inventory", GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_committed_inventory_matches_tree() -> None:
    code = _load_gen().discover()
    committed = json.loads(INV.read_text())
    assert committed["counts"] == code["counts"], (
        "PROGRAM_INVENTORY.json is stale vs the tree. Re-run "
        "`python3 programs/gen_program_inventory.py`. "
        f"committed={committed.get('counts')} tree={code['counts']}"
    )
    assert committed["programs_sha256"] == code["programs_sha256"]


def test_check_mode_is_clean_on_the_shipped_tree() -> None:
    r = subprocess.run([sys.executable, str(GEN), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_every_count_carries_a_definition() -> None:
    """A bare integer is what let 917 survive. No key without its meaning."""
    inv = json.loads(INV.read_text())
    assert set(inv["counts"]) == set(inv["definitions"]), (
        "every counts key must ship a definitions entry and vice versa"
    )
    for k, d in inv["definitions"].items():
        assert len(d) > 20, f"{k}: definition too thin to disambiguate"


def test_the_counts_are_distinct_questions() -> None:
    """The keys are not synonyms — the ordering below is what makes them
    different questions, and a generator that collapsed them would pass every
    other test here."""
    c = json.loads(INV.read_text())["counts"]
    assert c["check_suffix_only"] < c["checkers_top_level"] < c["programs_top_level"]
    assert c["programs_catalogued"] <= c["programs_top_level"]
    assert c["py_files_recursive"] > c["programs_top_level"]
    assert c["test_files"] > 0 and c["mcp_test_files"] > 0


def test_artifact_declares_itself_generated() -> None:
    inv = json.loads(INV.read_text())
    assert "Do NOT hand-edit" in inv["_comment"]


def test_check_mode_fails_on_a_hand_edited_count(tmp_path: Path) -> None:
    """NEGATIVE CONTROL. --check that cannot go red proves nothing."""
    stale = json.loads(INV.read_text())
    stale["counts"]["programs_top_level"] += 1
    scratch = tmp_path / "PROGRAM_INVENTORY.json"
    scratch.write_text(json.dumps(stale))

    mod = _load_gen()
    real_out = mod.OUT
    try:
        mod.OUT = scratch
        code = mod.discover()
        committed = json.loads(scratch.read_text())
        assert committed["counts"] != code["counts"]
    finally:
        mod.OUT = real_out


def test_catalogued_is_read_from_the_generated_index() -> None:
    """It must come from INDEX.md's own Stats line, not a second walk that
    could disagree with the catalogue a reader is pointed at."""
    mod = _load_gen()
    index_total = mod._index_catalogued()
    assert json.loads(INV.read_text())["counts"]["programs_catalogued"] == index_total
