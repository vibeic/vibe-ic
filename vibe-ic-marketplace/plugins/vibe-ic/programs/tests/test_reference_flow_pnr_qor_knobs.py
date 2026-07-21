#!/usr/bin/env python3
"""Tests for the Phase-3 REFERENCE-FLOW QoR-KNOB INGEST — FLOORPLAN / PLACE /
CTS / TIMING side (issue #198 Branch 1) in phase3_one_shot_runner.py.

The synth-side knobs (SWAP_ARITH_OPERATORS / ADDER_MAP_FILE / REMOVE_ABC_BUFFERS
/ FASTROUTE_LAYER_ADJUST) are covered by test_reference_flow_qor_knobs.py. This
file covers the NUMERIC back-end knobs a design's staged ORFS reference flow
declares to close timing — the floorplan core-util, the global-placement
density, the CTS sink-clustering, and the repair_timing TNS budget — which
phase-3 previously ignored (ibex: our generic recipe −45.05 ns vs the ORFS
reference recipe −0.5 ns on identical RTL).

`_reference_flow_pnr_knobs(project)` ingests ONLY the ORFS knob NAMES the design
literally declares (chip-AGNOSTIC), `_reference_flow_pnr_mapping(knobs)` maps
each to the concrete OpenROAD parameter, and `_build_pnr_tcl_text` emits the
directive ONLY when the knob is present.

§4.05 NO-LEAK gates covered here (LOAD-BEARING):
  * No reference_flow staged → {} → the generated pnr.tcl is BYTE-IDENTICAL to
    the legacy flow and the placement `util` is unchanged.
  * A knob is applied ONLY when the design literally declares a VALID numeric
    value; a non-numeric / out-of-range declaration is dropped, never fabricated.
  * Only the ORFS knob NAMES are recognized — an arbitrary design var never
    leaks in.

Docker-free: the emit tests build the tcl string and (when tclsh is present)
parse it with all OpenROAD commands stubbed. No container is spawned.
"""
from __future__ import annotations

import importlib
import re
import shutil
import subprocess
from pathlib import Path

import pytest

mod = importlib.import_module("phase3_one_shot_runner")

tclsh = shutil.which("tclsh")
needs_tclsh = pytest.mark.skipif(tclsh is None, reason="tclsh not installed")


# The exact knobs ibex ships in input/reference_flow/orfs_config.mk.
_IBEX_MK = (
    "export DESIGN_NICKNAME = ibex\n"
    "export ADDER_MAP_FILE :=\n"
    "export CORE_UTILIZATION = 50\n"
    "export PLACE_DENSITY_LB_ADDON = 0.25\n"
    "export TNS_END_PERCENT = 100\n"
    "export REMOVE_ABC_BUFFERS = 1\n"
    "export CTS_CLUSTER_SIZE = 20\n"
    "export CTS_CLUSTER_DIAMETER = 50\n"
    "export SWAP_ARITH_OPERATORS = 1\n"
    "export OPENROAD_HIERARCHICAL = 1\n"
)


def _stage(project: Path, files: dict) -> Path:
    rf = project / "input" / "reference_flow"
    rf.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (rf / name).write_text(content)
    return rf


# ---------------------------------------------------------------------------
# Ingest: _reference_flow_pnr_knobs
# ---------------------------------------------------------------------------
class TestPnrKnobIngest:
    def test_no_reference_flow_returns_empty(self, tmp_path):
        assert mod._reference_flow_pnr_knobs(tmp_path) == {}

    def test_dir_without_known_knobs_returns_empty(self, tmp_path):
        _stage(tmp_path, {"config.mk": "PLATFORM = sky130hd\nDESIGN = x\n"})
        assert mod._reference_flow_pnr_knobs(tmp_path) == {}

    def test_ibex_config_all_numeric_knobs(self, tmp_path):
        _stage(tmp_path, {"orfs_config.mk": _IBEX_MK})
        k = mod._reference_flow_pnr_knobs(tmp_path)
        assert k == {
            "CORE_UTILIZATION": "50",
            "PLACE_DENSITY_LB_ADDON": "0.25",
            "TNS_END_PERCENT": "100",
            "CTS_CLUSTER_SIZE": "20",
            "CTS_CLUSTER_DIAMETER": "50",
        }
        # a synth-side / non-numeric knob is NOT captured by the PnR ingest
        assert "SWAP_ARITH_OPERATORS" not in k
        assert "ADDER_MAP_FILE" not in k  # empty := is non-numeric → skipped

    def test_assignment_forms_mk(self, tmp_path):
        _stage(tmp_path, {"c.mk": (
            "CORE_UTILIZATION ?= 45   # tuned\n"
            "PLACE_DENSITY := 0.60\n"
            'TNS_END_PERCENT = "100"\n')})
        k = mod._reference_flow_pnr_knobs(tmp_path)
        assert k["CORE_UTILIZATION"] == "45"
        assert k["PLACE_DENSITY"] == "0.60"
        assert k["TNS_END_PERCENT"] == "100"

    def test_tcl_forms(self, tmp_path):
        _stage(tmp_path, {"flow.tcl": (
            "set ::env(CORE_UTILIZATION) 40\n"
            "setenv TNS_END_PERCENT 100\n"
            "set CTS_CLUSTER_SIZE 30\n")})
        k = mod._reference_flow_pnr_knobs(tmp_path)
        assert k["CORE_UTILIZATION"] == "40"
        assert k["TNS_END_PERCENT"] == "100"
        assert k["CTS_CLUSTER_SIZE"] == "30"

    def test_non_numeric_skipped_no_fabricate(self, tmp_path):
        # An unexpanded flow variable / non-numeric value is never ingested.
        _stage(tmp_path, {"c.mk": (
            "CORE_UTILIZATION = $(SOME_VAR)\n"
            "TNS_END_PERCENT = auto\n")})
        assert mod._reference_flow_pnr_knobs(tmp_path) == {}

    def test_last_valid_wins_non_numeric_does_not_clear(self, tmp_path):
        # .mk before .tcl (sorted); a later NON-numeric never clears an earlier
        # valid numeric (§4.05 — never lose a real declaration, never fabricate).
        _stage(tmp_path, {
            "a.mk": "CORE_UTILIZATION = 50\n",
            "z.tcl": "set ::env(CORE_UTILIZATION) $(OVERRIDE)\n",
        })
        assert mod._reference_flow_pnr_knobs(tmp_path)["CORE_UTILIZATION"] == "50"

    def test_later_valid_overrides_earlier(self, tmp_path):
        _stage(tmp_path, {
            "a.mk": "CORE_UTILIZATION = 50\n",
            "z.tcl": "set ::env(CORE_UTILIZATION) 40\n",
        })
        assert mod._reference_flow_pnr_knobs(tmp_path)["CORE_UTILIZATION"] == "40"

    def test_unknown_vars_ignored_chip_agnostic(self, tmp_path):
        _stage(tmp_path, {"c.mk": (
            "SOME_RANDOM_DESIGN_VAR = 42\n"
            "CORE_UTILIZATION = 50\n")})
        assert set(mod._reference_flow_pnr_knobs(tmp_path)) == {"CORE_UTILIZATION"}


# ---------------------------------------------------------------------------
# Map: _reference_flow_pnr_mapping
# ---------------------------------------------------------------------------
class TestPnrKnobMapping:
    def test_ibex_full_mapping(self, tmp_path):
        _stage(tmp_path, {"orfs_config.mk": _IBEX_MK})
        m = mod._reference_flow_pnr_mapping(
            mod._reference_flow_pnr_knobs(tmp_path))
        # CORE_UTILIZATION=50 → die target 0.50; + LB_ADDON 0.25 → density 0.75
        assert m["die_target_util"] == 0.5
        assert m["place_density"] == 0.75
        assert m["repair_tns_percent"] == 100
        assert m["cts_cluster_size"] == 20
        assert m["cts_cluster_diameter"] == 50.0
        assert any("CORE_UTILIZATION=50%" in n for n in m["notes"])
        assert any("PLACE_DENSITY derivation" in n for n in m["notes"])
        assert any("repair_timing -repair_tns 100" in n for n in m["notes"])

    def test_explicit_place_density_wins_over_derivation(self):
        m = mod._reference_flow_pnr_mapping({
            "CORE_UTILIZATION": "50", "PLACE_DENSITY_LB_ADDON": "0.25",
            "PLACE_DENSITY": "0.60"})
        assert m["place_density"] == 0.60          # explicit, NOT 0.75 derived
        assert m["die_target_util"] == 0.5

    def test_fp_core_util_alias(self):
        m = mod._reference_flow_pnr_mapping({"FP_CORE_UTIL": "45"})
        assert m["die_target_util"] == 0.45
        assert m["place_density"] == 0.45          # derived, LB_ADDON absent → 0

    def test_out_of_range_dropped(self):
        # util > 100% / density > 1 / negative TNS → dropped, never applied.
        m = mod._reference_flow_pnr_mapping({
            "CORE_UTILIZATION": "150", "PLACE_DENSITY": "1.4",
            "TNS_END_PERCENT": "-5", "CTS_CLUSTER_SIZE": "0"})
        assert m["die_target_util"] is None
        assert m["place_density"] is None
        assert m["repair_tns_percent"] is None
        assert m["cts_cluster_size"] is None
        assert m["notes"] == []

    def test_empty_knobs_all_none(self):
        m = mod._reference_flow_pnr_mapping({})
        assert all(m[k] is None for k in
                   ("place_density", "die_target_util", "repair_tns_percent",
                    "cts_cluster_size", "cts_cluster_diameter"))
        assert m["notes"] == []

    def test_declared_die_util_helper(self, tmp_path):
        _stage(tmp_path, {"orfs_config.mk": _IBEX_MK})
        assert mod._reference_flow_declared_die_util(tmp_path) == 0.5
        # empty project → None (byte-identical guarantee for the die sizer)
        empty = tmp_path / "empty"
        empty.mkdir()
        assert mod._reference_flow_declared_die_util(empty) is None


# ---------------------------------------------------------------------------
# Auto-die precedence: reference_flow feeds the die-util target (below L9)
# ---------------------------------------------------------------------------
def _min_netlist(tmp_path: Path) -> Path:
    nl = tmp_path / "top_synth.v"
    body = "\n".join(f"  INV i{n} (.A(a{n}), .Y(y{n}));" for n in range(40))
    nl.write_text(f"module top();\n{body}\nendmodule\n")
    return nl


def _min_pdk():
    return mod.PdkConfig(
        name="sky130A", liberty="l.lib", tech_lef="t.lef", cell_lef="c.lef",
        cell_gds=None, site="unit", drc_deck=None)


class TestAutoDiePrecedence:
    def test_reference_flow_feeds_die_util_when_no_l9(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        _stage(proj, {"orfs_config.mk": _IBEX_MK})
        nl = _min_netlist(tmp_path)
        _die, note = mod._resolve_auto_die_um(
            "auto", nl, 0.30, _min_pdk(), project=proj, top="top")
        assert note is not None
        assert "reference_flow-declared" in note
        assert "target_util=0.5" in note

    def test_l9_wins_over_reference_flow(self, tmp_path):
        proj = tmp_path / "proj"
        docs = proj / "input" / "docs"
        docs.mkdir(parents=True)
        # L9 declares FP_CORE_UTIL=20% (0.20) — must win over reference_flow 0.50
        (docs / "L9_constraints.md").write_text(
            "| Knob | Value |\n|---|---|\n| `FP_CORE_UTIL` | **20** |\n")
        _stage(proj, {"orfs_config.mk": _IBEX_MK})
        nl = _min_netlist(tmp_path)
        _die, note = mod._resolve_auto_die_um(
            "auto", nl, 0.30, _min_pdk(), project=proj, top="top")
        assert "L9-declared" in note
        assert "target_util=0.2" in note

    def test_no_declaration_keeps_default(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        nl = _min_netlist(tmp_path)
        _die, note = mod._resolve_auto_die_um(
            "auto", nl, 0.30, _min_pdk(), project=proj, top="top")
        assert "routing-headroom-default" in note


# ---------------------------------------------------------------------------
# Emission: _build_pnr_tcl_text — None byte-identical / knobs injected
# ---------------------------------------------------------------------------
_TCL_BASE = dict(
    tech_lef_c="t.lef", cell_lef_c="c.lef", macro_lefs_tcl="", liberty_c="l.lib",
    macro_libs_tcl="", netlist_c="n.v", top="top", sdc_c="c.sdc",
    dont_use_block="", metal_prefix="met", die_w=100, die_h=100, core_pad=10,
    core_w=80, core_h=80, site="unit", out_dir_c="/out", tapcell_block="",
    pdn_block="", util=0.30, spare_protection_tcl="", spare_postfix_tcl="",
    clk_buf="clkbuf_4", clk_buf_root="clkbuf_16", routing_constraint_tcl="",
    pg_cleanup_block="", spef_repair_block="", antenna_repair_block="",
    filler_block="",
)


class TestPnrTclEmission:
    def test_none_is_byte_identical_to_omitted(self):
        legacy = mod._build_pnr_tcl_text(**_TCL_BASE)
        with_none = mod._build_pnr_tcl_text(
            **_TCL_BASE, repair_tns_percent=None,
            cts_cluster_size=None, cts_cluster_diameter=None)
        assert legacy == with_none
        assert "-repair_tns" not in legacy
        assert "-sink_clustering" not in legacy

    def test_all_knobs_inject_directives(self):
        tcl = mod._build_pnr_tcl_text(
            **_TCL_BASE, repair_tns_percent=100,
            cts_cluster_size=20, cts_cluster_diameter=50.0)
        # BOTH executable setup-repair passes get -repair_tns (pre-CTS + post-GR)
        assert tcl.count("repair_timing -setup -repair_tns 100") == 2
        assert ("clock_tree_synthesis -buf_list {clkbuf_4} -root_buf clkbuf_16"
                " -sink_clustering_enable -sink_clustering_size 20"
                " -sink_clustering_max_diameter 50}") in tcl

    def test_hold_repair_never_gets_repair_tns(self):
        tcl = mod._build_pnr_tcl_text(**_TCL_BASE, repair_tns_percent=100)
        for m in re.findall(r"repair_timing -hold[^}]*", tcl):
            assert "-repair_tns" not in m

    def test_cts_size_only(self):
        tcl = mod._build_pnr_tcl_text(**_TCL_BASE, cts_cluster_size=20)
        assert "-sink_clustering_enable -sink_clustering_size 20}" in tcl
        assert "-sink_clustering_max_diameter" not in tcl

    def test_cts_diameter_only(self):
        tcl = mod._build_pnr_tcl_text(**_TCL_BASE, cts_cluster_diameter=50.0)
        assert ("-sink_clustering_enable -sink_clustering_max_diameter 50}"
                in tcl)
        assert "-sink_clustering_size" not in tcl

    @needs_tclsh
    def test_injected_tcl_parses_in_tclsh(self, tmp_path):
        tcl = mod._build_pnr_tcl_text(
            **{**_TCL_BASE, "util": 0.75}, repair_tns_percent=100,
            cts_cluster_size=20, cts_cluster_diameter=50.0)
        script = tmp_path / "pnr.tcl"
        script.write_text('proc unknown {args} { return "" }\n' + tcl)
        r = subprocess.run([tclsh, str(script)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
