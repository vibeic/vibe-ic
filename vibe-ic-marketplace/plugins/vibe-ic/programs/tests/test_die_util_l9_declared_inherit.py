#!/usr/bin/env python3
"""L9 floorplan knobs: core utilization sizes the core; placement density
controls global placement. The two declarations are independent.

Empirical motivation (v1.2.72 live): the fixed 0.25 routing-headroom target won
for the CONGESTION-bound aes (dense converged) but a design may want more
timing/DRC headroom. Rather than a blind "prefer-sparser" heuristic (the ibex
"regression" was confounded + its residual DRC was cell-driven pin-access that a
sparser die does NOT fix), HONOR the design's own L9 declaration.

§4.05 (no-fabricate, TIGHT): only the UNAMBIGUOUS `| <key> | <value> |` adjacent
key-value-row form is parsed; a header-row/data-row table or a "plugin decides"
cell yields None → the validated default is kept (missing a declaration is SAFE;
mis-parsing a wrong number would fabricate a wrong die).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase3_one_shot_runner as P  # noqa: E402


def _mk_l9(tmp_path, body: str) -> Path:
    proj = tmp_path / "proj"
    docs = proj / "input" / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L9_constraints_floorplan.md").write_text(body)
    return proj


def _write_l19(proj: Path, value) -> None:
    path = proj / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"fields": {"constraint_declarations": [{
        "token": "FP_CORE_UTIL", "value": value, "scope": None,
        "source": "input/config.json", "line": 4}]}}))


def test_core_util_does_not_inherit_placement_density(tmp_path):
    proj = _mk_l9(tmp_path,
                  "| `FP_CORE_UTIL` | **20** | ref |\n"
                  "| `PL_TARGET_DENSITY` | **0.25** | ref |\n")
    assert P._l9_declared_die_util(proj) == 0.20
    assert P._l9_declared_place_density(proj) == 0.25


def test_derives_from_fp_core_util_percentage(tmp_path):
    proj = _mk_l9(tmp_path, "| `FP_CORE_UTIL` | **40** | ref |\n")
    assert P._l9_declared_die_util(proj) == 0.40   # 40% -> 0.40


def test_header_data_table_not_parsed_safe(tmp_path):
    # §4.05: value NOT adjacent to the key (header row / data row) → None,
    # NEVER a mis-parsed number → the validated default is kept.
    proj = _mk_l9(tmp_path,
                  "| PDK | `FP_CORE_UTIL` | `PL_TARGET_DENSITY` |\n"
                  "|---|---|---|\n"
                  "| SKY130 | 45% | tool-default |\n")
    assert P._l9_declared_die_util(proj) is None


def test_plugin_decides_cell_not_parsed(tmp_path):
    proj = _mk_l9(tmp_path,
                  "- 不指定。由 Plugin 依照 FP_CORE_UTIL 與 pad ring 推算決定。\n")
    assert P._l9_declared_die_util(proj) is None


def test_out_of_range_density_rejected(tmp_path):
    proj = _mk_l9(tmp_path, "| `PL_TARGET_DENSITY` | **1.5** | ref |\n")
    assert P._l9_declared_die_util(proj) is None   # >1 not a valid fraction


def test_no_l9_returns_none(tmp_path):
    proj = tmp_path / "empty"
    (proj / "input").mkdir(parents=True)
    assert P._l9_declared_die_util(proj) is None


def test_l19_core_util_reaches_direct_phase3_resolver(tmp_path):
    proj = tmp_path / "proj"
    _write_l19(proj, 25)
    assert P._l9_declared_die_util(proj) == 0.25


def test_l19_core_util_drives_direct_auto_die_target(tmp_path):
    proj = tmp_path / "proj"
    _write_l19(proj, 25)
    netlist = proj / "netlist.v"
    netlist.write_text("\n".join(
        f"neutral_inv u{i} (.A(a{i}),.Y(y{i}));" for i in range(5000)))

    class _Pdk:
        name = "processA"
        cell_lef = "/nonexistent.lef"

    metrics = {}
    die, note = P._resolve_auto_die_um(
        "auto", netlist, 0.77, _Pdk(), proj, metrics=metrics)
    assert "x" in die and "target_util=0.25" in (note or "")
    assert metrics["die_target_util"] == 0.25


def test_l19_core_util_never_becomes_placement_density(tmp_path):
    proj = _mk_l9(
        tmp_path, "| `PL_TARGET_DENSITY` | **0.61** | ref |\n")
    _write_l19(proj, 25)
    assert P._l9_declared_die_util(proj) == 0.25
    assert P._l9_declared_place_density(proj) == 0.61


def test_l19_and_l9_core_util_conflict_refuses(tmp_path):
    proj = _mk_l9(tmp_path, "| `FP_CORE_UTIL` | **35** | ref |\n")
    _write_l19(proj, 25)
    with pytest.raises(ValueError, match="FP_CORE_UTIL_AUTHORITY_CONFLICT"):
        P._l9_declared_die_util(proj)


def test_resolve_uses_declared_util_over_default(tmp_path):
    # Orchestrator ruling 2026-09-28: REPLACED the landed assertion that a
    # density-only declaration resizes the core. It conflated FP_CORE_UTIL
    # with PL_TARGET_DENSITY. A density-only declaration leaves core sizing at
    # the pinned flow's own FP_CORE_UTIL default.
    proj = _mk_l9(tmp_path, "| `PL_TARGET_DENSITY` | **0.10** | ref |\n")
    nl = proj / "netlist.v"
    nl.write_text("\n".join(f"sky130_fd_sc_hd__inv_1 u{i} (.A(a{i}),.Y(y{i}));"
                            for i in range(5000)))

    class _Pdk:
        cell_lef = "/nonexistent.lef"   # forces the fallback avg-cell
    from unittest.mock import patch
    with patch.object(P, "_flow_default_core_util", create=True,
                      return_value=(0.37, "pinned tool FP_CORE_UTIL")):
        die_density, note = P._resolve_auto_die_um(
            "auto", nl, 0.4, _Pdk(), proj)
        proj2 = _mk_l9(tmp_path / "other", "| `PL_TARGET_DENSITY` | **0.65** | ref |\n")
        die_other, _ = P._resolve_auto_die_um("auto", nl, 0.4, _Pdk(), proj2)
    assert die_density == die_other
    assert "pinned tool FP_CORE_UTIL" in (note or "")


def test_resolve_without_project_backward_compatible(tmp_path):
    # project=None (legacy callers) → uses the default target, never crashes.
    nl = tmp_path / "nl.v"
    nl.write_text("sky130_fd_sc_hd__inv_1 u0 (.A(a),.Y(y));")

    class _Pdk:
        cell_lef = "/nonexistent.lef"
    out, note = P._resolve_auto_die_um("auto", nl, 0.4, _Pdk())   # no project
    assert "x" in out and "routing-headroom-default" in (note or "")


def test_explicit_die_still_passthrough(tmp_path):
    proj = _mk_l9(tmp_path, "| `PL_TARGET_DENSITY` | **0.10** | ref |\n")
    out, note = P._resolve_auto_die_um("900x900", tmp_path / "nl.v", 0.4,
                                       None, proj)
    assert out == "900x900" and note is None   # declared util never resizes an explicit die
