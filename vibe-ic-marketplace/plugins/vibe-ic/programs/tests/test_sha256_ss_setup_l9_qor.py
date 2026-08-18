#!/usr/bin/env python3
"""ORGANIC sha256×sky130A — Post-route STA sign-off at the SS slow corner.

Root cause (measured on the real routed netlist): the ss-corner setup WNS was
-19.75 ns at a 25.9 ns clock while the typ corner met — a single-corner-closure
blow-up. The worst path was NOT logic-depth bound; it was a slew-explosion
cascade from high-fanout nets driven by min-drive cells (fanout 12/21/55, one
pin's slew 12.2 ns vs a 1.5 ns limit). The DESIGN's OWN L9 floorplan/synthesis
spec DECLARES the reference recipe that avoids exactly this — `SYNTH_MAX_FANOUT`
and `PL_TARGET_DENSITY` / `FP_CORE_UTIL` — but Phase-3 ignored both:

  * `SYNTH_MAX_FANOUT` had NO effect anywhere (no `set_max_fanout` was emitted,
    so `repair_design` never split the high-fanout nets).
  * `PL_TARGET_DENSITY` fed only the die sizer, never `global_placement
    -density` (stuck at the dense generic default → congested nets → the routed
    parasitics that explode the ss slew, and no room for repair buffers).

These tests pin the two chip-AGNOSTIC fixes: the auto-silicon SDC now emits
`set_max_fanout` from an L9-declared cap, and the SDC/DRV block renders it. The
density-override wiring is a runner-internal (`step_pnr`) path; it is asserted
here at the unit level via `_l9_declared_die_util` (already covered) + the new
`_l9_declared_max_fanout`. §4.05 no-fabricate: a design that declares NEITHER
gets a byte-identical SDC (negative tests below)."""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

mod = importlib.import_module("phase3_one_shot_runner")


_L9_WITH_KNOBS = """---
layer: L9
ic: widget
---
# L9 — Constraints / Floorplan

## 9.1B Synthesis Constraints

| 參數 | 值 | 來源 |
|---|---|---|
| `SYNTH_MAX_FANOUT` | **8** | reference data/pdk.tcl |

## 9.2 Floorplan

| 設定 | 值 | 來源 |
|---|---|---|
| `FP_CORE_UTIL` | **20** | reference data/pdk.tcl |
| `PL_TARGET_DENSITY` | **0.25** | reference data/pdk.tcl |
"""

_L9_NO_KNOBS = """---
layer: L9
ic: widget
---
# L9 — Constraints / Floorplan

## 9.2 Floorplan
- Die size: 不指定。由 Plugin 依 cell count 推算。
- Placement density: 工具預設 / plugin decides。
"""


def _stage(tmp_path: Path, l9_text: str) -> Path:
    docs = tmp_path / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "L9_constraints_floorplan.md").write_text(l9_text)
    return tmp_path


# ── the new L9 SYNTH_MAX_FANOUT reader ─────────────────────────────────────
def test_l9_declared_max_fanout_parsed(tmp_path):
    proj = _stage(tmp_path, _L9_WITH_KNOBS)
    assert mod._l9_declared_max_fanout(proj) == 8


def test_l9_declared_max_fanout_absent_is_none(tmp_path):
    proj = _stage(tmp_path, _L9_NO_KNOBS)
    assert mod._l9_declared_max_fanout(proj) is None


def test_l9_declared_max_fanout_no_docs_is_none(tmp_path):
    # a project with no input/docs at all → None, never a fabricated cap
    assert mod._l9_declared_max_fanout(tmp_path) is None


def test_l9_density_still_read_for_reference_recipe(tmp_path):
    # the density override reuses the existing L9 density reader; confirm it
    # prefers the explicit PL_TARGET_DENSITY fraction the same design declares.
    proj = _stage(tmp_path, _L9_WITH_KNOBS)
    assert mod._l9_declared_die_util(proj) == pytest.approx(0.25)


# ── the DRV/SDC block renders set_max_fanout ───────────────────────────────
def test_drv_block_emits_set_max_fanout():
    txt = mod._drv_constraints_sdc_block(1.5, 5.0, "", max_fanout=8,
                                         fanout_note="cap note")
    assert "set_max_fanout 8 [current_design]" in txt
    assert "set_max_transition 1.5 [current_design]" in txt
    assert "# cap note" in txt


def test_drv_block_no_fanout_is_byte_identical():
    # No max_fanout → the block must not contain set_max_fanout at all, and must
    # match the legacy (slew+cap only) rendering byte-for-byte.
    legacy = mod._drv_constraints_sdc_block(1.5, 5.0, "")
    witharg = mod._drv_constraints_sdc_block(1.5, 5.0, "", max_fanout=None)
    assert "set_max_fanout" not in legacy
    assert legacy == witharg


def test_drv_block_only_fanout_still_emits():
    # A design that resolves NO liberty DRV limit but DOES declare a fanout cap
    # still gets the set_max_fanout line (the guard must not swallow it).
    txt = mod._drv_constraints_sdc_block(None, None, "", max_fanout=8)
    assert "set_max_fanout 8 [current_design]" in txt


def test_drv_block_all_none_returns_empty():
    assert mod._drv_constraints_sdc_block(None, None, "") == ""
    assert mod._drv_constraints_sdc_block(None, None, "", max_fanout=None) == ""


# ── end-to-end: the auto-silicon SDC carries the L9 cap ────────────────────
def test_auto_silicon_sdc_carries_l9_max_fanout(tmp_path):
    proj = _stage(tmp_path, _L9_WITH_KNOBS)
    sdc = mod._build_auto_silicon_sdc(
        proj, top="widget", drv_slew_ns=1.5, drv_cap_pf=5.0, liberty_path="")
    assert "set_max_fanout 8 [current_design]" in sdc


def test_auto_silicon_sdc_no_fanout_when_undeclared(tmp_path):
    proj = _stage(tmp_path, _L9_NO_KNOBS)
    sdc = mod._build_auto_silicon_sdc(
        proj, top="widget", drv_slew_ns=1.5, drv_cap_pf=5.0, liberty_path="")
    assert "set_max_fanout" not in sdc


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
