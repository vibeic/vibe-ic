#!/usr/bin/env python3
"""Drift guard: the committed SKILL_INVENTORY.json MUST match the skills/ folders.
Single source of truth for the website skill count (vibeic.ai/#skills), which
hand-drifted (said 55 while 57 skills now exist). Adding/removing a skill without
regenerating the inventory fails this test, forcing
`python3 programs/gen_skill_inventory.py` to be re-run.
"""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent   # plugins/vibe-ic/
GEN = PLUGIN / "programs" / "gen_skill_inventory.py"
INV = PLUGIN / "SKILL_INVENTORY.json"


def _load_gen():
    spec = importlib.util.spec_from_file_location("gen_skill_inventory", GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_committed_skill_inventory_matches_folders() -> None:
    code = _load_gen().discover()
    committed = json.loads(INV.read_text())
    assert committed["skills"] == code["skills"], (
        "SKILL_INVENTORY.json is stale vs the skills/ folders. Re-run "
        "`python3 programs/gen_skill_inventory.py`. "
        f"committed total={committed.get('total')} folders total={code['total']}"
    )


def test_total_equals_enumeration() -> None:
    inv = json.loads(INV.read_text())
    assert inv["total"] == len(inv["skills"]) == len(set(inv["skills"]))
    assert inv["total"] == sum(inv["by_tier"].values())


def test_new_skills_counted() -> None:
    inv = json.loads(INV.read_text())
    # the two skills added this cycle must be in the count
    assert "benchmark-verify" in inv["skills"]
    assert "design-for-eco" in inv["skills"]
