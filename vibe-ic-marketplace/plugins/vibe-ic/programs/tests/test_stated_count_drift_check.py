#!/usr/bin/env python3
"""`stated_count_drift_check.py` — regression gate.

THE FINDING IT EXISTS FOR. Measured at 397b3f25f on 2026-08-19: three generated
inventories shipped with drift guards proving each ARTEFACT matched the TREE,
and the two READMEs still stated 917 deterministic programs, 3,737 programs,
1608 test files and 60 skills — because nothing checked that the prose a reader
sees quotes the artefact. The tool count stayed right over the same period for
one reason: it had been re-typed out of a generated number.

The tests below hold three properties, in the order that matters:

  1. the SHIPPED tree is clean (the gate is live, not aspirational);
  2. a hand-edited count goes RED and NAMES THE FILE (the ACCEPT criterion);
  3. a REWORDED sentence goes RED too — this gate's failure mode is failing
     open, and a prose-anchored scanner that silently stops matching would
     certify exactly the state it can no longer see.
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent   # plugins/vibe-ic/
REPO = PLUGIN.parents[2]
GATE = PLUGIN / "programs" / "stated_count_drift_check.py"


def _load():
    spec = importlib.util.spec_from_file_location("stated_count_drift_check", GATE)
    mod = importlib.util.module_from_spec(spec)
    # @dataclass resolves annotations through sys.modules; a module executed
    # without being registered there raises on the decorator itself.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _mirror(root: Path, dst: Path) -> Path:
    """A writable copy of just the files the gate reads."""
    mod = _load()
    rels = [mod.PROGRAM_INVENTORY, mod.SKILL_INVENTORY, mod.MCP_TOOL_INVENTORY]
    rels += sorted({s.path for s in mod.SITES})
    for rel in rels:
        src, out = root / rel, dst / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(src.read_text())
    return dst


# ── 1. the shipped tree ──────────────────────────────────────────────────────
def test_shipped_tree_is_clean() -> None:
    r = subprocess.run([sys.executable, str(GATE)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout


def test_every_registered_key_resolves_to_an_inventory() -> None:
    mod = _load()
    inv = mod.load_inventory(REPO)
    for site in mod.SITES:
        assert site.key in inv, f"{site.path} names unbacked key {site.key}"
        assert site.key in mod.PATTERNS


# ── 2. a hand-edited count goes red, naming the file ─────────────────────────
@pytest.mark.parametrize("key", ["programs_top_level", "skills", "test_files"])
def test_hand_edited_count_fails_naming_the_file(tmp_path: Path, key: str) -> None:
    mod = _load()
    root = _mirror(REPO, tmp_path / "tree")
    inv = mod.load_inventory(root)
    site = next(s for s in mod.SITES if s.key == key)

    target = root / site.path
    text = target.read_text()
    m = re.search(mod.PATTERNS[key], text)
    assert m, f"no {key} statement to perturb in {site.path}"
    bumped = str(inv[key] + 1)
    target.write_text(text[:m.start("n")] + bumped + text[m.end("n"):])

    findings = mod.scan(root, inv)
    drift = [f for f in findings if f.kind == "stated-drift"]
    assert drift, f"perturbing {key} produced no finding"
    assert any(f.path == site.path and f.key == key and f.stated == bumped
               for f in drift), [f.render() for f in drift]

    r = subprocess.run([sys.executable, str(GATE), "--root", str(root)],
                       capture_output=True, text=True)
    assert r.returncode == 1
    assert site.path in r.stdout and "[FAIL]" in r.stdout


def test_a_drifted_inventory_number_also_fails(tmp_path: Path) -> None:
    """Symmetry: the prose is judged against the artefact, either side moving."""
    mod = _load()
    root = _mirror(REPO, tmp_path / "tree")
    p = root / mod.PROGRAM_INVENTORY
    inv_json = json.loads(p.read_text())
    inv_json["counts"]["programs_top_level"] += 7
    p.write_text(json.dumps(inv_json))

    r = subprocess.run([sys.executable, str(GATE), "--root", str(root)],
                       capture_output=True, text=True)
    assert r.returncode == 1
    assert "programs_top_level" in r.stdout


# ── 3. the fail-open failure mode ────────────────────────────────────────────
def test_reworded_sentence_fails_instead_of_passing_silently(tmp_path: Path) -> None:
    mod = _load()
    root = _mirror(REPO, tmp_path / "tree")
    inv = mod.load_inventory(root)
    site = next(s for s in mod.SITES if s.key == "programs_top_level")

    target = root / site.path
    text = target.read_text()
    m = re.search(mod.PATTERNS["programs_top_level"], text)
    assert m
    # drop the anchor words, keep a (still correct) number: the classic
    # silent-blind-spot edit.
    target.write_text(text[:m.start()] + f"{inv['programs_top_level']} programs "
                      + text[m.end():])

    findings = mod.scan(root, inv)
    assert any(f.kind == "site-count" and f.key == "programs_top_level"
               for f in findings), [f.render() for f in findings]

    r = subprocess.run([sys.executable, str(GATE), "--root", str(root)],
                       capture_output=True, text=True)
    assert r.returncode == 1
    assert "site-count" in r.stdout


def test_a_new_unregistered_claim_fails(tmp_path: Path) -> None:
    mod = _load()
    root = _mirror(REPO, tmp_path / "tree")
    inv = mod.load_inventory(root)
    site = next(s for s in mod.SITES if s.key == "skills")
    target = root / site.path
    target.write_text(target.read_text()
                      + f"\n\nThe plugin ships {inv['skills']} skills.\n")

    findings = mod.scan(root, inv)
    assert any(f.kind == "site-count" and f.key == "skills" for f in findings)


# ── the gate must never certify what it could not read ───────────────────────
def test_missing_inventory_is_a_failure_not_a_pass(tmp_path: Path) -> None:
    mod = _load()
    root = _mirror(REPO, tmp_path / "tree")
    (root / mod.PROGRAM_INVENTORY).unlink()

    with pytest.raises(mod.Unmeasurable):
        mod.load_inventory(root)

    r = subprocess.run([sys.executable, str(GATE), "--root", str(root)],
                       capture_output=True, text=True)
    assert r.returncode == 1
    assert "NOT CHECKED" in r.stdout


def test_missing_registered_file_is_a_failure(tmp_path: Path) -> None:
    mod = _load()
    root = _mirror(REPO, tmp_path / "tree")
    inv = mod.load_inventory(root)
    (root / mod.SITES[0].path).unlink()
    with pytest.raises(mod.Unmeasurable):
        mod.scan(root, inv)
