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
        # #541 — the OPTIMIZATION class is applied verbatim…
        assert m["repair_tns_percent"] == 100
        assert m["cts_cluster_size"] == 20
        assert m["cts_cluster_diameter"] == 50.0
        assert any("repair_timing -repair_tns 100" in n for n in m["notes"])
        # …and the ROUTING-RESOURCE-SUPPLY class is withheld. This used to
        # assert die_target_util == 0.5 / place_density == 0.75, which is the
        # exact behaviour measured to take ibex from a converged detailed route
        # to one that never closed an optimization iteration.
        assert m["die_target_util"] is None
        assert m["place_density"] is None

    def test_supply_class_is_withheld_not_silently_dropped(self, tmp_path):
        """The withhold is a DECISION and must be on the record with the
        value, the source file and the parameter it would have fed. Silence
        here would be indistinguishable from never having read the config."""
        _stage(tmp_path, {"orfs_config.mk": _IBEX_MK})
        m = mod._reference_flow_pnr_mapping(
            mod._reference_flow_pnr_knobs(tmp_path),
            mod._reference_flow_pnr_knob_sources(tmp_path))
        w = {r["knob"]: r for r in m["withheld"]}
        assert set(w) == {"CORE_UTILIZATION", "PLACE_DENSITY_LB_ADDON"}
        assert w["CORE_UTILIZATION"]["value"] == "50"
        assert w["CORE_UTILIZATION"]["source"].endswith("orfs_config.mk")
        assert "die_target_util" in w["CORE_UTILIZATION"]["params"]
        assert "place_density" in w["PLACE_DENSITY_LB_ADDON"]["params"]
        assert all(r["reason"] for r in m["withheld"])
        # …and the mapping trace names each one.
        assert sum(n.startswith("WITHHELD") for n in m["notes"]) == 2

    def test_explicit_place_density_is_withheld_too(self):
        """An EXPLICIT PLACE_DENSITY is in the same class as a derived one —
        the risk is the density, not how it was arrived at."""
        m = mod._reference_flow_pnr_mapping({
            "CORE_UTILIZATION": "50", "PLACE_DENSITY_LB_ADDON": "0.25",
            "PLACE_DENSITY": "0.60"})
        assert m["place_density"] is None
        assert m["die_target_util"] is None
        assert {r["knob"] for r in m["withheld"]} == {
            "CORE_UTILIZATION", "PLACE_DENSITY_LB_ADDON", "PLACE_DENSITY"}

    def test_fp_core_util_alias_is_withheld_under_its_own_name(self):
        m = mod._reference_flow_pnr_mapping({"FP_CORE_UTIL": "45"})
        assert m["die_target_util"] is None
        assert m["place_density"] is None
        assert [r["knob"] for r in m["withheld"]] == ["FP_CORE_UTIL"]

    def test_withheld_class_is_derived_from_the_knob_vocabulary(self,
                                                                tmp_path):
        """The class is a property of the flow PARAMETER a knob feeds, read off
        the one vocabulary table — not a second hand-maintained knob list that
        could drift away from it.

        The parameter names are checked against the ones the PRODUCER actually
        emits, not against a literal restated here: a rename in the producer
        would otherwise leave `_RF_ROUTING_SUPPLY_PARAMS` matching nothing, and
        the whole class would silently empty out — a withhold that stops
        withholding while every other assertion in this file still passes."""
        assert mod._ORFS_WITHHELD_PNR_KNOBS == frozenset(
            k for k, params in mod._ORFS_PNR_KNOB_PARAMS.items()
            if mod._RF_ROUTING_SUPPLY_PARAMS.intersection(params))
        assert mod._ORFS_WITHHELD_PNR_KNOBS, "the class must not be empty"
        # every recognized PnR knob is in the vocabulary …
        assert set(mod._ORFS_NUM_PNR_KNOBS) == set(mod._ORFS_PNR_KNOB_PARAMS)
        # … and every parameter named in it is one the audit really reports.
        emitted = set(mod._reference_flow_pnr_audit(tmp_path)["applied"])
        for knob, params in mod._ORFS_PNR_KNOB_PARAMS.items():
            assert params, knob
            assert set(params) <= emitted, knob
        assert mod._RF_ROUTING_SUPPLY_PARAMS <= emitted

    def test_out_of_range_dropped(self):
        # negative TNS / zero cluster size → dropped, never applied.
        m = mod._reference_flow_pnr_mapping({
            "TNS_END_PERCENT": "-5", "CTS_CLUSTER_SIZE": "0"})
        assert m["repair_tns_percent"] is None
        assert m["cts_cluster_size"] is None
        # #198 Branch 1 audit trail: dropped is DISCLOSED, not silent. This
        # previously asserted `notes == []` — i.e. it pinned the exact silence
        # that makes a discarded knob indistinguishable from an undeclared one.
        # The values above must still never be applied (asserted); what changed
        # is that each drop now states knob + value + reason.
        assert {r["knob"] for r in m["rejected"]} == {
            "TNS_END_PERCENT", "CTS_CLUSTER_SIZE"}
        assert all(n.startswith("REJECTED") for n in m["notes"])
        assert all(r["reason"] for r in m["rejected"])

    def test_out_of_range_supply_knob_is_withheld_not_range_judged(self):
        """A knob this flow will not apply at ANY value must not be reported
        with a range verdict — that would tell the reader an in-range value
        would have been applied."""
        m = mod._reference_flow_pnr_mapping({
            "CORE_UTILIZATION": "150", "PLACE_DENSITY": "1.4"})
        assert m["die_target_util"] is None
        assert m["place_density"] is None
        assert {r["knob"] for r in m["withheld"]} == {
            "CORE_UTILIZATION", "PLACE_DENSITY"}
        assert m["rejected"] == []
        # the declared value is still carried verbatim, so a malformed
        # declaration stays visible
        assert {r["value"] for r in m["withheld"]} == {"150", "1.4"}

    def test_empty_knobs_all_none(self):
        m = mod._reference_flow_pnr_mapping({})
        assert all(m[k] is None for k in
                   ("place_density", "die_target_util", "repair_tns_percent",
                    "cts_cluster_size", "cts_cluster_diameter"))
        assert m["notes"] == []

    def test_declared_die_util_helper(self, tmp_path):
        # #541 — the die-util hook is single-sourced through the mapping, which
        # withholds the supply class, so a STAGED reference flow now yields the
        # same None an absent one does: the auto-die sizer keeps its own
        # routing-headroom calibration.
        _stage(tmp_path, {"orfs_config.mk": _IBEX_MK})
        assert mod._reference_flow_declared_die_util(tmp_path) is None
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
    def test_reference_flow_does_not_size_the_die(self, tmp_path):
        """#541 — a staged reference flow must NOT shrink the auto die. This
        used to assert `reference_flow-declared` / `target_util=0.5`, i.e. the
        exact substitution measured to take ibex from a converged detailed
        route to one that never closed an optimization iteration. The die the
        sizer produces must now be the same one it produces with no reference
        flow at all — measured as a DIE, not just as a label."""
        nl = _min_netlist(tmp_path)
        bare = tmp_path / "bare"
        bare.mkdir()
        die_bare, note_bare = mod._resolve_auto_die_um(
            "auto", nl, 0.30, _min_pdk(), project=bare, top="top")
        proj = tmp_path / "proj"
        proj.mkdir()
        _stage(proj, {"orfs_config.mk": _IBEX_MK})
        die_rf, note_rf = mod._resolve_auto_die_um(
            "auto", nl, 0.30, _min_pdk(), project=proj, top="top")
        assert die_rf == die_bare
        assert note_rf == note_bare
        assert "reference_flow-declared" not in note_rf
        assert "routing-headroom-default" in note_rf

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
        # -distance_between_buffers defaults to 10 whenever clustering is
        # active and no explicit CTS_DISTANCE_BETWEEN_BUFFERS knob overrides
        # it (spm x ihp-sg13g2, 2026-08-07 — sink_clustering alone can still
        # leave the CTS root buffer over its own fanout limit).
        assert ("clock_tree_synthesis -buf_list {clkbuf_4} -root_buf clkbuf_16"
                " -sink_clustering_enable -sink_clustering_size 20"
                " -sink_clustering_max_diameter 50"
                " -distance_between_buffers 10}") in tcl

    def test_hold_repair_never_gets_repair_tns(self):
        tcl = mod._build_pnr_tcl_text(**_TCL_BASE, repair_tns_percent=100)
        for m in re.findall(r"repair_timing -hold[^}]*", tcl):
            assert "-repair_tns" not in m

    def test_cts_size_only(self):
        tcl = mod._build_pnr_tcl_text(**_TCL_BASE, cts_cluster_size=20)
        assert ("-sink_clustering_enable -sink_clustering_size 20"
                " -distance_between_buffers 10}") in tcl
        assert "-sink_clustering_max_diameter" not in tcl

    def test_cts_diameter_only(self):
        tcl = mod._build_pnr_tcl_text(**_TCL_BASE, cts_cluster_diameter=50.0)
        assert ("-sink_clustering_enable -sink_clustering_max_diameter 50"
                " -distance_between_buffers 10}" in tcl)
        assert "-sink_clustering_size" not in tcl

    def test_cts_distance_between_buffers_explicit_overrides_default(self):
        """A reference-flow-declared CTS_DISTANCE_BETWEEN_BUFFERS must win
        outright over the built-in default (10) — same non-override
        guarantee every other reference-flow knob already has."""
        tcl = mod._build_pnr_tcl_text(
            **_TCL_BASE, cts_cluster_size=20,
            cts_distance_between_buffers=40.0)
        assert ("-sink_clustering_enable -sink_clustering_size 20"
                " -distance_between_buffers 40}") in tcl
        assert "-distance_between_buffers 10" not in tcl

    def test_cts_distance_between_buffers_absent_without_clustering(self):
        """No clustering knob at all -> no -distance_between_buffers either;
        the default only fires alongside sink clustering, since that is the
        specific scenario it closes (an ungated design gets byte-identical
        CTS behaviour to before this fix)."""
        tcl = mod._build_pnr_tcl_text(**_TCL_BASE)
        assert "-distance_between_buffers" not in tcl
        assert "-sink_clustering_enable" not in tcl

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
