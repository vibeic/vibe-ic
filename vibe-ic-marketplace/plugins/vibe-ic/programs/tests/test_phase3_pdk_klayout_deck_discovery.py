"""tests/test_phase3_pdk_klayout_deck_discovery.py — v1.6.53

When a custom PDK ships a KLayout DRC deck alongside a Calibre deck,
discovery should pick it up so step_drc can run an open-source
pre-flight rather than going straight to WAIVED.
"""
from __future__ import annotations

from pathlib import Path

from programs.phase3_one_shot_runner import _detect_pdk


def _setup_pdk_skeleton(pdk_dir: Path) -> None:
    """Lay down minimum files for `_detect_pdk` to recognise the PDK
    as a custom tree (liberty + tech.lef + cell.lef are required)."""
    pdk_dir.mkdir(parents=True, exist_ok=True)
    (pdk_dir / "liberty").mkdir(parents=True, exist_ok=True)
    (pdk_dir / "liberty" / "TT.lib").write_text("library(tt) {}")
    (pdk_dir / "lef").mkdir(parents=True, exist_ok=True)
    (pdk_dir / "lef" / "tech.lef").write_text("VERSION 5.8 ;")
    (pdk_dir / "lef" / "cells.lef").write_text("MACRO cell END cell")


def _project_with_pdk(tmp_path: Path) -> Path:
    p = tmp_path / "proj"
    pdk = p / "input" / "pdk"
    _setup_pdk_skeleton(pdk)
    return p


# ---------------------------------------------------------------------------
# KLayout deck discovery sub-paths.
# ---------------------------------------------------------------------------

def test_discovers_lydrc_in_klayout_drc(tmp_path: Path) -> None:
    p = _project_with_pdk(tmp_path)
    deck = p / "input" / "pdk" / "klayout" / "drc" / "rules.lydrc"
    deck.parent.mkdir(parents=True, exist_ok=True)
    deck.write_text("# klayout drc deck")
    cfg = _detect_pdk(p)
    assert cfg.drc_deck is not None
    assert cfg.drc_deck.endswith("rules.lydrc")


def test_discovers_drc_extension_in_klayout(tmp_path: Path) -> None:
    p = _project_with_pdk(tmp_path)
    deck = p / "input" / "pdk" / "klayout" / "rules.drc"
    deck.parent.mkdir(parents=True, exist_ok=True)
    deck.write_text("# klayout deck")
    cfg = _detect_pdk(p)
    assert cfg.drc_deck is not None
    assert cfg.drc_deck.endswith("rules.drc")


def test_discovers_lyt_in_drc(tmp_path: Path) -> None:
    p = _project_with_pdk(tmp_path)
    deck = p / "input" / "pdk" / "drc" / "tech.lyt"
    deck.parent.mkdir(parents=True, exist_ok=True)
    deck.write_text("<tech/>")
    cfg = _detect_pdk(p)
    assert cfg.drc_deck is not None
    assert cfg.drc_deck.endswith("tech.lyt")


def test_no_deck_yields_none(tmp_path: Path) -> None:
    p = _project_with_pdk(tmp_path)
    # No klayout/ or drc/ subdir
    cfg = _detect_pdk(p)
    assert cfg.drc_deck is None


def test_discovery_does_not_pick_calibre_deck(tmp_path: Path) -> None:
    """Calibre `.rule` deck must NOT be mis-detected as klayout."""
    p = _project_with_pdk(tmp_path)
    cd = p / "input" / "pdk" / "calibre"
    cd.mkdir(parents=True, exist_ok=True)
    (cd / "Calibre_commercial_pdk_DRC.rule").write_text("# calibre deck")
    cfg = _detect_pdk(p)
    assert cfg.drc_deck is None
    # But the Calibre deck IS surfaced separately for WAIVED messaging.
    assert cfg.calibre_drc is not None
    assert cfg.calibre_drc.endswith("Calibre_commercial_pdk_DRC.rule")


def test_klayout_and_calibre_decks_both_recognised(tmp_path: Path) -> None:
    """When both decks are present, klayout is picked for step_drc
    and calibre is recorded as the sign-off backup."""
    p = _project_with_pdk(tmp_path)
    kd = p / "input" / "pdk" / "klayout" / "rules.lydrc"
    kd.parent.mkdir(parents=True, exist_ok=True)
    kd.write_text("# klayout deck")
    cd = p / "input" / "pdk" / "calibre" / "Calibre_DRC.rule"
    cd.parent.mkdir(parents=True, exist_ok=True)
    cd.write_text("# calibre deck")
    cfg = _detect_pdk(p)
    assert cfg.drc_deck is not None and cfg.drc_deck.endswith("rules.lydrc")
    assert cfg.calibre_drc is not None and cfg.calibre_drc.endswith("Calibre_DRC.rule")
