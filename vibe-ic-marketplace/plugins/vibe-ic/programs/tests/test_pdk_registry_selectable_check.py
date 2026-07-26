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


def test_an_unreachable_image_skips_the_asset_half_explicitly(tmp_path,
                                                              monkeypatch):
    """It must NOT be folded into the PASS. "I could not look" and "I looked
    and it is clean" are different claims.

    #408: unreachable now means NEITHER a live container NOR the pinned
    image. A bogus container name alone no longer suffices, because the
    check falls back to `docker run --rm` on the image — that fallback is
    the fix for the asset half never running at all.
    """
    monkeypatch.setattr(C, "_resolve_target", lambda name: None)
    rep = C.audit(REGISTRY, "definitely_not_a_container")
    assert rep["asset_check"] == "SKIPPED"
    assert rep["assets_checked"] == 0
    # The subprocess half cannot see the monkeypatch, so make the IMAGE
    # unreachable the way a real docker-less host would: point the override
    # at a tag that does not exist.
    import os
    env = dict(os.environ, VIBEIC_EDA_IMAGE="ghcr.io/vibeic/no-such-image:0")
    r = subprocess.run(
        [sys.executable, str(_PROGRAMS / "pdk_registry_selectable_check.py"),
         "--container", "definitely_not_a_container"],
        capture_output=True, text=True, env=env)
    assert "SKIPPED" in r.stdout and "not a clean result" in r.stdout


def test_the_name_half_still_runs_without_an_image(tmp_path, monkeypatch):
    """A gate that skipped entirely on a docker-less host would do nothing in
    CI. The name rule is pure registry data."""
    monkeypatch.setattr(C, "_resolve_target", lambda name: None)
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


# ── #408 finding 3: the shipped-but-unregistered direction ──────────────────

def _stub_image(monkeypatch, trees, resolved_map):
    """Pretend an image is reachable and ships `trees`."""
    monkeypatch.setattr(C, "_container_alive", lambda n: True)
    monkeypatch.setattr(C, "_resolves", lambda c, p: True)
    monkeypatch.setattr(C, "shipped_trees", lambda c: trees)
    monkeypatch.setattr(C, "_resolved",
                        lambda c, p: resolved_map.get(p, p.rstrip("/")))


def test_a_shipped_pdk_the_registry_lacks_is_reported(monkeypatch):
    """#408 finding 3, and a LIVE instance on main: `ihp-sg13cmos5l` ships in
    vibeic-eda:0.2.30 and is not in the registry, so `--pdk` refuses it — a
    tree present and unselectable, which is the #389 condition."""
    _stub_image(monkeypatch,
                {"/foss/pdks/ihp-sg13cmos5l": "ihp-sg13cmos5l",
                 "/foss/pdks/asap7": "asap7"},
                {})
    rep = C.audit(REGISTRY, "stub")
    names = [u["basename"] for u in rep["shipped_unregistered"]]
    assert names == ["ihp-sg13cmos5l"], names


def test_a_symlink_target_is_not_a_second_finding(monkeypatch):
    """The paired half, and the reason a one-level scan was kept before: the
    image's REAL sky130A/gf180mcuD live under `ciel/.../`, reached by
    top-level symlinks. Comparing unresolved paths would report both as
    unregistered — two false findings on a correct image."""
    ciel = "/foss/pdks/ciel/sky130/versions/abc/sky130A"
    _stub_image(monkeypatch,
                {ciel: "sky130A"},
                {"/foss/pdks/sky130A": ciel})
    rep = C.audit(REGISTRY, "stub")
    assert rep["shipped_unregistered"] == [], rep["shipped_unregistered"]


def test_the_recorded_gap_does_not_fail_but_a_new_one_does(tmp_path,
                                                           monkeypatch):
    """Shrink-only register: failing main on a pre-existing gap makes a gate
    people route around; anything NEW fails."""
    _stub_image(monkeypatch,
                {"/foss/pdks/ihp-sg13cmos5l": "ihp-sg13cmos5l",
                 "/foss/pdks/brand_new": "brand_new"},
                {})
    bl = tmp_path / "bl.json"
    bl.write_text(json.dumps({"known": ["ihp-sg13cmos5l"]}))
    rc = C.main(["--registry", str(REGISTRY), "--container", "stub",
                 "--baseline", str(bl)])
    assert rc == 1, "a NEW shipped-but-unregistered PDK must fail"

    _stub_image(monkeypatch,
                {"/foss/pdks/ihp-sg13cmos5l": "ihp-sg13cmos5l"}, {})
    assert C.main(["--registry", str(REGISTRY), "--container", "stub",
                   "--baseline", str(bl)]) == 0, "the recorded one must not"


def test_the_register_may_only_shrink(tmp_path, monkeypatch):
    _stub_image(monkeypatch,
                {"/foss/pdks/a": "a", "/foss/pdks/b": "b"}, {})
    bl = tmp_path / "bl.json"
    bl.write_text(json.dumps({"known": ["a"]}))
    rc = C.main(["--registry", str(REGISTRY), "--container", "stub",
                 "--baseline", str(bl), "--write-baseline"])
    assert rc == 1


def test_no_image_means_no_shipped_direction_at_all(monkeypatch):
    """It must not report an empty shipped set as "nothing unregistered"."""
    monkeypatch.setattr(C, "_container_alive", lambda n: False)
    rep = C.audit(REGISTRY, "stub")
    assert rep["shipped_unregistered"] == []
    assert rep["asset_check"] == "SKIPPED"


def test_no_image_cannot_declare_a_recorded_gap_PAID(tmp_path, monkeypatch):
    """REGRESSION, caught by the shared gate script failing on a docker-less
    host. Without a reachable container the shipped set is EMPTY; subtracting
    it from the register reported every recorded entry as resolved — "I could
    not look" read as "it is fixed", the same error as the asset half, in the
    shrink direction."""
    monkeypatch.setattr(C, "_container_alive", lambda n: False)
    bl = tmp_path / "bl.json"
    bl.write_text(json.dumps({"known": ["ihp-sg13cmos5l"]}))
    rc = C.main(["--registry", str(REGISTRY), "--container", "unreachable",
                 "--baseline", str(bl)])
    assert rc == 0, "an unreachable image must not resolve a recorded gap"


def test_with_an_image_a_genuinely_gone_entry_still_forces_a_shrink(
        tmp_path, monkeypatch):
    """The paired half: when the image WAS enumerated, a recorded entry that
    no longer ships must still force the register to shrink, or it becomes
    standing permission."""
    _stub_image(monkeypatch, {"/foss/pdks/asap7": "asap7"}, {})
    bl = tmp_path / "bl.json"
    bl.write_text(json.dumps({"known": ["ihp-sg13cmos5l"]}))
    rc = C.main(["--registry", str(REGISTRY), "--container", "stub",
                 "--baseline", str(bl)])
    assert rc == 1
