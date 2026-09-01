"""Direct controls for the shared staged-PDK technology-LEF authority."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import _staged_pdk_tech_lef as T  # noqa: E402


def _touch(path: Path, text: str = "VERSION 5.8 ;\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_discovery_is_deterministic_and_excludes_standard_cell_lefs(tmp_path):
    pdk = tmp_path / "input/pdk"
    z = _touch(pdk / "z_stack.TLEF")
    a = _touch(pdk / "a_tech.lef")
    _touch(pdk / "cells/stdcells.lef")

    assert T.discover_staged_tech_lefs(pdk) == (a, z)


def test_bridge_declaration_is_the_first_authority(tmp_path):
    pdk = tmp_path / "input/pdk"
    selected = _touch(pdk / "stacks/declared.tlef")
    other = _touch(pdk / "stacks/other.tlef")
    cfg = pdk / "bridge/signoff_config.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"tech_lef": "stacks/declared.tlef"}))

    got = T.select_staged_tech_lef(pdk, (other, selected))
    assert got is not None
    assert got.path == selected
    assert got.authority == "bridge.signoff_config.tech_lef"


def test_missing_declared_stack_refuses_instead_of_falling_back(tmp_path):
    pdk = tmp_path / "input/pdk"
    only = _touch(pdk / "only.tlef")
    cfg = pdk / "bridge/signoff_config.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"tech_lef": "missing.tlef"}))

    with pytest.raises(T.TechLefResolutionError, match="does not exist"):
        T.select_staged_tech_lef(pdk, (only,))


def test_runner_evidence_basename_must_map_uniquely(tmp_path):
    pdk = tmp_path / "input/pdk"
    first = _touch(pdk / "a/stack.tlef")
    second = _touch(pdk / "b/stack.tlef")

    with pytest.raises(T.TechLefResolutionError, match="exactly one"):
        T.select_staged_tech_lef(
            pdk, (first, second), selected_path="/container/pdk/stack.tlef")

    got = T.select_staged_tech_lef(
        pdk, (first, second), selected_path="a/stack.tlef",
        selected_path_authority="phase3_run.tech_lef")
    assert got is not None
    assert got.path == first
    assert got.authority == "phase3_run.tech_lef"


def test_signoff_deck_narrows_multiple_stacks_structurally(tmp_path):
    pdk = tmp_path / "input/pdk"
    low = _touch(pdk / "stacks/low.tlef")
    high = _touch(pdk / "stacks/high.tlef")
    _touch(pdk / "calibre/foundry_DRC.rule", "#DEFINE TOPMETAL_6\n")
    tops = {low: "MET4", high: "MET6"}
    counts = {low: 4, high: 6}

    got = T.select_staged_tech_lef(
        pdk, (low, high), top_routing_layer=tops.get,
        routing_layer_count=counts.get)
    assert got is not None
    assert got.path == high
    assert got.authority == "staged_pdk.signoff_deck_topmetal"


def test_multiple_unnarrowed_stacks_refuse_sort_order_as_authority(tmp_path):
    pdk = tmp_path / "input/pdk"
    first = _touch(pdk / "a.tlef")
    second = _touch(pdk / "b.tlef")

    with pytest.raises(T.TechLefResolutionError, match="DESIGN CHOICE"):
        T.select_staged_tech_lef(pdk, (first, second))
