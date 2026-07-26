#!/usr/bin/env python3
"""Tests for pdk_registry_selectable_check (vibe-ic#408, the #389 family).

#408 recorded a WITHDRAWN drift checker that returned CONSISTENT for two
states it advertised as findings. Both are real invariants of
`pdk_registry.json` that nothing on main enforced:

  * a declared asset that resolves to nothing — the old checker stat'ed only
    `container_path`;
  * an entry whose `name` differs from `basename(container_path)` — a
    complete PDK in the image that no operator can select, which is the #389
    incident condition verbatim.

Paired throughout. Both halves must also stay distinguishable from "I could
not look": folding an unreachable image into a PASS is the defect #408 is
about.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import pdk_registry_selectable_check as C  # noqa: E402

REGISTRY = _PROGRAMS / "pdk_registry.json"


def _reg(tmp_path: Path, mutate=None) -> Path:
    d = json.loads(REGISTRY.read_text())
    if mutate:
        mutate(d)
    p = tmp_path / "reg.json"
    p.write_text(json.dumps(d, indent=2))
    return p


def test_the_shipped_registry_is_selectable():
    """Main today: every entry that declares a directory is reachable by its
    own name. Measured 5 of 6 (the auto-detect sentinel declares none)."""
    rep = C.audit(REGISTRY, "no_such_container")
    assert rep["readable"] and rep["unselectable"] == []


def test_a_name_that_differs_from_its_directory_is_a_finding(tmp_path):
    """#408 finding 2. `--pdk` matches the NAME; the image ships the
    DIRECTORY. When they differ the PDK is present and unselectable."""
    def _typo(d):
        for e in d["pdks"]:
            if e.get("name") == "ihp-sg13g2":
                e["name"] = "ihp-sg13g2-TYPO"
    rep = C.audit(_reg(tmp_path, _typo), "no_such_container")
    assert len(rep["unselectable"]) == 1
    assert rep["unselectable"][0]["basename"] == "ihp-sg13g2"


def test_the_sentinel_without_a_directory_is_not_a_finding(tmp_path):
    """The paired half: `custom_auto_detect` declares no `container_path`
    because it is not a directory. Flagging it would make the gate fire on a
    correct registry from day one, which is how a gate gets ignored."""
    rep = C.audit(REGISTRY, "no_such_container")
    names = [u["name"] for u in rep["unselectable"]]
    assert "custom_auto_detect" not in names


def test_an_unreachable_image_skips_the_asset_half_explicitly(tmp_path):
    """It must NOT be folded into the PASS. "I could not look" and "I looked
    and it is clean" are different claims."""
    rep = C.audit(REGISTRY, "definitely_not_a_container")
    assert rep["asset_check"] == "SKIPPED"
    assert rep["assets_checked"] == 0
    r = subprocess.run(
        [sys.executable, str(_PROGRAMS / "pdk_registry_selectable_check.py"),
         "--container", "definitely_not_a_container"],
        capture_output=True, text=True)
    assert "SKIPPED" in r.stdout and "not a clean result" in r.stdout


def test_the_name_half_still_runs_without_an_image(tmp_path):
    """A gate that skipped entirely on a docker-less host would do nothing in
    CI. The name rule is pure registry data."""
    def _typo(d):
        for e in d["pdks"]:
            if e.get("name") == "asap7":
                e["name"] = "asap7-TYPO"
    rep = C.audit(_reg(tmp_path, _typo), "definitely_not_a_container")
    assert rep["asset_check"] == "SKIPPED"
    assert len(rep["unselectable"]) == 1


def test_asset_keys_cover_every_declared_path_kind():
    """#408 finding 1 was that only `container_path` was stat'ed. The key set
    must reach the globs and decks, or this gate repeats that defect."""
    d = json.loads(REGISTRY.read_text())
    entry = next(e for e in d["pdks"] if e.get("name") == "gf180mcuD")
    keys = set(C._asset_keys(entry))
    assert {"liberty_glob", "tech_lef_glob", "cell_lef_glob"} <= keys
    assert "container_path" not in keys, "the directory is not an asset glob"


def test_an_unreadable_registry_is_a_SKIP_not_a_PASS(tmp_path):
    p = tmp_path / "broken.json"
    p.write_text("{not json")
    rep = C.audit(p, "no_such_container")
    assert rep["readable"] is False
    r = subprocess.run(
        [sys.executable, str(_PROGRAMS / "pdk_registry_selectable_check.py"),
         "--registry", str(p)], capture_output=True, text=True)
    assert r.returncode == 2
