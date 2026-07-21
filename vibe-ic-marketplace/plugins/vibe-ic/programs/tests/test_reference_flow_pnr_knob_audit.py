#!/usr/bin/env python3
"""Tests for the AUDIT TRAIL of the Phase-3 reference-flow QoR-knob ingest
(issue #198 Branch 1).

`test_reference_flow_pnr_qor_knobs.py` covers WHICH knobs are ingested and HOW
they map to OpenROAD parameters. This file covers whether the run is
AUDITABLE — because a silent behaviour change in the physical flow is worse
than no change. Someone reading a finished run must be able to answer:

  * which knobs did phase-3 adopt, with what values, and FROM WHICH FILE?
  * which knobs did the design declare that phase-3 did NOT apply, and why?
  * when the floorplan looks generic, was there no config, or was a staged
    config silently ignored?

The gaps these tests pin (all reproduced against ibex's real
`input/reference_flow/orfs_config.mk` before the fix):

  GAP-A  no note named the file a knob came from — `_reference_flow_pnr_knobs`
         returned bare {KNOB: value} with no provenance at all.
  GAP-B  a declared-but-unusable knob (non-numeric, or out of range) was
         dropped with ZERO disclosure — `mapping["notes"] == []`, identical to
         a design that declared nothing.
  GAP-C  nothing was written to the run's reports; the only audit trail was
         stderr + StepResult.extras, neither of which survives in the run dir
         as a readable artifact.

§4.05 fail-safe (LOAD-BEARING, negative control): an absent / unreadable /
unrecognised config must leave the applied parameters EXACTLY as they are
today (every value None → generic defaults) — and must SAY SO in the report
rather than be silently indistinguishable from "the mechanism never ran".

chip-AGNOSTIC throughout: the mechanism keys on the flow-config knob NAMES, so
the tests use ibex's real config as one instance plus a synthetic vendor flow
with different filenames / nesting to prove it is not an ibex special case.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

mod = importlib.import_module("phase3_one_shot_runner")
_pl = importlib.import_module("_path_layout")


# The exact knobs ibex ships in input/reference_flow/orfs_config.mk.
_IBEX_MK = (
    "export DESIGN_NICKNAME = ibex\n"
    "export ADDER_MAP_FILE :=\n"
    "export CORE_UTILIZATION = 50\n"
    "export PLACE_DENSITY_LB_ADDON = 0.25\n"
    "export TNS_END_PERCENT = 100\n"
    "export CTS_CLUSTER_SIZE = 20\n"
    "export CTS_CLUSTER_DIAMETER = 50\n"
    "export SWAP_ARITH_OPERATORS = 1\n"
)

_APPLIED_KEYS = ("place_density", "die_target_util", "repair_tns_percent",
                 "cts_cluster_size", "cts_cluster_diameter")


def _stage(project: Path, files: dict) -> Path:
    rf = project / "input" / "reference_flow"
    rf.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        p = rf / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return rf


# ---------------------------------------------------------------------------
# GAP-A — provenance: every adopted knob names the file that declared it
# ---------------------------------------------------------------------------
class TestKnobProvenance:
    def test_sources_map_names_declaring_file(self, tmp_path):
        _stage(tmp_path, {"orfs_config.mk": _IBEX_MK})
        src = mod._reference_flow_pnr_knob_sources(tmp_path)
        assert src["CORE_UTILIZATION"] == "input/reference_flow/orfs_config.mk"
        assert src["TNS_END_PERCENT"] == "input/reference_flow/orfs_config.mk"

    def test_sources_empty_without_config(self, tmp_path):
        assert mod._reference_flow_pnr_knob_sources(tmp_path) == {}

    def test_provenance_survives_multi_file_override(self, tmp_path):
        # z.tcl overrides a.mk → the SOURCE must follow the winning value.
        _stage(tmp_path, {
            "a.mk": "CORE_UTILIZATION = 50\n",
            "z.tcl": "set ::env(CORE_UTILIZATION) 40\n",
        })
        assert mod._reference_flow_pnr_knobs(tmp_path)["CORE_UTILIZATION"] == "40"
        assert (mod._reference_flow_pnr_knob_sources(tmp_path)["CORE_UTILIZATION"]
                == "input/reference_flow/z.tcl")

    def test_mapping_notes_carry_source_file(self, tmp_path):
        _stage(tmp_path, {"orfs_config.mk": _IBEX_MK})
        m = mod._reference_flow_pnr_mapping(
            mod._reference_flow_pnr_knobs(tmp_path),
            mod._reference_flow_pnr_knob_sources(tmp_path))
        # GAP-A: pre-fix NO note mentioned the source file.
        assert all("orfs_config.mk" in n for n in m["notes"])

    def test_mapping_without_sources_is_backward_compatible(self, tmp_path):
        # The landed 2-arg-less call site must keep working and emit no
        # bracketed provenance.
        _stage(tmp_path, {"orfs_config.mk": _IBEX_MK})
        m = mod._reference_flow_pnr_mapping(
            mod._reference_flow_pnr_knobs(tmp_path))
        assert m["place_density"] == 0.75
        assert all("[" not in n for n in m["notes"])

    def test_audit_adopted_entries_carry_value_and_source(self, tmp_path):
        _stage(tmp_path, {"orfs_config.mk": _IBEX_MK})
        a = mod._reference_flow_pnr_audit(tmp_path)
        adopted = {x["knob"]: x for x in a["adopted"]}
        assert adopted["CORE_UTILIZATION"]["value"] == "50"
        assert (adopted["CORE_UTILIZATION"]["source"]
                == "input/reference_flow/orfs_config.mk")
        assert adopted["CTS_CLUSTER_SIZE"]["value"] == "20"


# ---------------------------------------------------------------------------
# GAP-B — a declared-but-unusable knob is DROPPED and DISCLOSED
# ---------------------------------------------------------------------------
class TestRejectionIsDisclosed:
    def test_non_numeric_declaration_is_disclosed(self, tmp_path):
        _stage(tmp_path, {"c.mk": "TNS_END_PERCENT = notanumber\n"})
        a = mod._reference_flow_pnr_audit(tmp_path)
        # behaviour unchanged …
        assert all(a["applied"][k] is None for k in _APPLIED_KEYS)
        # … but the drop is STATED, with value + source + reason.
        r = [x for x in a["rejected"] if x["knob"] == "TNS_END_PERCENT"]
        assert len(r) == 1
        assert r[0]["value"] == "notanumber"
        assert r[0]["source"] == "input/reference_flow/c.mk"
        assert r[0]["reason"]

    def test_out_of_range_declaration_is_disclosed(self, tmp_path):
        _stage(tmp_path, {"c.mk": (
            "CORE_UTILIZATION = 400\n"
            "CTS_CLUSTER_SIZE = -5\n")})
        a = mod._reference_flow_pnr_audit(tmp_path)
        assert all(a["applied"][k] is None for k in _APPLIED_KEYS)
        knobs = {x["knob"] for x in a["rejected"]}
        # GAP-B: pre-fix these were dropped with notes == [].
        assert {"CORE_UTILIZATION", "CTS_CLUSTER_SIZE"} <= knobs
        assert any("REJECTED" in n for n in a["notes"])

    def test_rejected_knob_never_fabricates_a_value(self, tmp_path):
        _stage(tmp_path, {"c.mk": "PLACE_DENSITY = 1.4\n"})
        a = mod._reference_flow_pnr_audit(tmp_path)
        assert a["applied"]["place_density"] is None
        assert a["status"] == "knobs-rejected"

    def test_partial_rejection_keeps_the_valid_knob(self, tmp_path):
        # One good, one bad → the good one applies, the bad one is disclosed.
        _stage(tmp_path, {"c.mk": (
            "CORE_UTILIZATION = 50\n"
            "CTS_CLUSTER_SIZE = -5\n")})
        a = mod._reference_flow_pnr_audit(tmp_path)
        assert a["status"] == "knobs-adopted"
        assert a["applied"]["die_target_util"] == 0.5
        assert a["applied"]["cts_cluster_size"] is None
        assert any(x["knob"] == "CTS_CLUSTER_SIZE" for x in a["rejected"])

    def test_declared_but_inert_knob_is_not_claimed_as_adopted(self, tmp_path):
        # PLACE_DENSITY_LB_ADDON is an ADDEND: with no CORE_UTILIZATION to add
        # it to it feeds nothing. Reporting it as "adopted" would be precisely
        # the misleading audit trail this report exists to prevent.
        _stage(tmp_path, {"c.mk": "PLACE_DENSITY_LB_ADDON = 0.25\n"})
        a = mod._reference_flow_pnr_audit(tmp_path)
        assert all(a["applied"][k] is None for k in _APPLIED_KEYS)
        assert a["adopted"] == []
        assert a["status"] == "knobs-rejected"
        inert = [r for r in a["rejected"]
                 if r["knob"] == "PLACE_DENSITY_LB_ADDON"]
        assert len(inert) == 1 and inert[0]["reason"]

    def test_lb_addon_is_adopted_when_it_has_a_companion(self, tmp_path):
        # …and the same knob IS adopted when it actually contributes.
        _stage(tmp_path, {"c.mk": (
            "CORE_UTILIZATION = 50\nPLACE_DENSITY_LB_ADDON = 0.25\n")})
        a = mod._reference_flow_pnr_audit(tmp_path)
        assert a["applied"]["place_density"] == 0.75
        assert {x["knob"] for x in a["adopted"]} == {
            "CORE_UTILIZATION", "PLACE_DENSITY_LB_ADDON"}

    def test_fp_core_util_alias_named_by_its_declared_name(self, tmp_path):
        # The report must name the knob the DESIGN used, not the canonical
        # alias — otherwise a reader cannot find it in their own config.
        _stage(tmp_path, {"c.mk": "FP_CORE_UTIL = 45\n"})
        a = mod._reference_flow_pnr_audit(tmp_path)
        assert {x["knob"] for x in a["adopted"]} == {"FP_CORE_UTIL"}
        assert any("FP_CORE_UTIL=45%" in n for n in a["notes"])

    def test_unreadable_config_is_disclosed_not_silent(self, tmp_path):
        rf = _stage(tmp_path, {"good.mk": "CORE_UTILIZATION = 50\n"})
        bad = rf / "unreadable.mk"
        bad.write_text("CORE_UTILIZATION = 20\n")
        bad.chmod(0o000)
        try:
            a = mod._reference_flow_pnr_audit(tmp_path)
        finally:
            bad.chmod(0o644)
        if a["unreadable"]:            # skipped when running as root
            assert any("unreadable.mk" in u for u in a["unreadable"])
            # the readable file's knob still applies — fail SAFE, not fail shut
            assert a["applied"]["die_target_util"] == 0.5


# ---------------------------------------------------------------------------
# GAP-C — the audit lands in the run's REPORTS, on every run
# ---------------------------------------------------------------------------
class TestReportEmission:
    def test_report_written_into_phase3_reports_subfolder(self, tmp_path):
        _stage(tmp_path, {"orfs_config.mk": _IBEX_MK})
        a = mod._reference_flow_pnr_audit(tmp_path)
        written = mod._write_reference_flow_pnr_report(tmp_path, a)
        assert written
        md = _pl.report_path(tmp_path, "reference_flow_knobs.md")
        js = _pl.report_path(tmp_path, "reference_flow_knobs.json")
        # taxonomy: phase-3 artifacts live under reports/phase3/, not root
        assert md.parent.name == "phase3"
        assert md.is_file() and js.is_file()

    def test_report_lists_every_adopted_knob_value_and_source(self, tmp_path):
        _stage(tmp_path, {"orfs_config.mk": _IBEX_MK})
        a = mod._reference_flow_pnr_audit(tmp_path)
        mod._write_reference_flow_pnr_report(tmp_path, a)
        txt = _pl.report_path(tmp_path, "reference_flow_knobs.md").read_text()
        for knob, value in (("CORE_UTILIZATION", "50"),
                            ("TNS_END_PERCENT", "100"),
                            ("CTS_CLUSTER_SIZE", "20"),
                            ("CTS_CLUSTER_DIAMETER", "50")):
            assert knob in txt and value in txt
        assert "input/reference_flow/orfs_config.mk" in txt
        assert "knobs-adopted" in txt

    def test_report_json_is_machine_readable(self, tmp_path):
        _stage(tmp_path, {"orfs_config.mk": _IBEX_MK})
        a = mod._reference_flow_pnr_audit(tmp_path)
        mod._write_reference_flow_pnr_report(tmp_path, a)
        data = json.loads(
            _pl.report_path(tmp_path, "reference_flow_knobs.json").read_text())
        assert data["status"] == "knobs-adopted"
        assert data["applied"]["place_density"] == 0.75
        assert {x["knob"] for x in data["adopted"]} >= {"CORE_UTILIZATION"}

    def test_report_states_rejection_with_reason(self, tmp_path):
        _stage(tmp_path, {"c.mk": "CORE_UTILIZATION = 400\n"})
        a = mod._reference_flow_pnr_audit(tmp_path)
        mod._write_reference_flow_pnr_report(tmp_path, a)
        txt = _pl.report_path(tmp_path, "reference_flow_knobs.md").read_text()
        assert "Declared but NOT applied" in txt
        assert "400" in txt and "input/reference_flow/c.mk" in txt

    def test_report_write_failure_never_raises(self, tmp_path, monkeypatch):
        # Best-effort: a report-write failure must not fail the PnR step.
        _stage(tmp_path, {"orfs_config.mk": _IBEX_MK})
        a = mod._reference_flow_pnr_audit(tmp_path)
        monkeypatch.setattr(Path, "write_text",
                            lambda *_a, **_k: (_ for _ in ()).throw(OSError))
        assert mod._write_reference_flow_pnr_report(tmp_path, a) == []


# ---------------------------------------------------------------------------
# NEGATIVE CONTROL (§4.05) — absent / unrecognised config changes NOTHING,
# and the report says so
# ---------------------------------------------------------------------------
class TestFailSafeNegativeControl:
    def test_no_config_applies_nothing(self, tmp_path):
        a = mod._reference_flow_pnr_audit(tmp_path)
        assert a["status"] == "no-config"
        assert all(a["applied"][k] is None for k in _APPLIED_KEYS)
        assert a["adopted"] == [] and a["rejected"] == []
        assert a["notes"] == []

    def test_no_config_still_writes_a_report_that_says_so(self, tmp_path):
        # GAP-C / fail-safe: absence must be STATED, not left as silence that
        # reads the same as "the mechanism never ran".
        a = mod._reference_flow_pnr_audit(tmp_path)
        mod._write_reference_flow_pnr_report(tmp_path, a)
        txt = _pl.report_path(tmp_path, "reference_flow_knobs.md").read_text()
        assert "no-config" in txt
        assert "GENERIC defaults" in txt
        assert "byte-identical" in txt

    def test_config_without_recognised_knobs_says_so(self, tmp_path):
        _stage(tmp_path, {"config.mk": "PLATFORM = sky130hd\nDESIGN = x\n"})
        a = mod._reference_flow_pnr_audit(tmp_path)
        assert a["status"] == "no-knobs"
        assert all(a["applied"][k] is None for k in _APPLIED_KEYS)
        mod._write_reference_flow_pnr_report(tmp_path, a)
        txt = _pl.report_path(tmp_path, "reference_flow_knobs.md").read_text()
        assert "no-knobs" in txt
        assert "Nothing was silently ignored" in txt

    def test_unknown_design_var_never_leaks_in(self, tmp_path):
        _stage(tmp_path, {"c.mk": (
            "SOME_RANDOM_DESIGN_VAR = 42\n"
            "MY_VENDOR_UTIL = 90\n")})
        a = mod._reference_flow_pnr_audit(tmp_path)
        assert a["status"] == "no-knobs"
        assert a["adopted"] == []

    def test_no_config_tcl_is_byte_identical_to_legacy(self, tmp_path):
        # The load-bearing no-leak guarantee, restated at the emission layer:
        # a project with no reference_flow produces the legacy pnr.tcl.
        a = mod._reference_flow_pnr_audit(tmp_path)
        base = dict(
            tech_lef_c="t.lef", cell_lef_c="c.lef", macro_lefs_tcl="",
            liberty_c="l.lib", macro_libs_tcl="", netlist_c="n.v", top="top",
            sdc_c="c.sdc", dont_use_block="", metal_prefix="met", die_w=100,
            die_h=100, core_pad=10, core_w=80, core_h=80, site="unit",
            out_dir_c="/out", tapcell_block="", pdn_block="", util=0.30,
            spare_protection_tcl="", spare_postfix_tcl="", clk_buf="clkbuf_4",
            clk_buf_root="clkbuf_16", routing_constraint_tcl="",
            pg_cleanup_block="", spef_repair_block="", antenna_repair_block="",
            filler_block="")
        legacy = mod._build_pnr_tcl_text(**base)
        from_audit = mod._build_pnr_tcl_text(
            **base,
            repair_tns_percent=a["applied"]["repair_tns_percent"],
            cts_cluster_size=a["applied"]["cts_cluster_size"],
            cts_cluster_diameter=a["applied"]["cts_cluster_diameter"])
        assert legacy == from_audit


# ---------------------------------------------------------------------------
# GENERALISATION — the mechanism keys on DECLARED knob names, not on ibex
# ---------------------------------------------------------------------------
class TestGeneralisesBeyondIbex:
    def test_arbitrary_filename_and_nesting(self, tmp_path):
        # Not "orfs_config.mk", and nested a level down.
        _stage(tmp_path, {"nested/vendor_flow.tcl": (
            "set ::env(FP_CORE_UTIL) 35\n"
            "setenv CTS_CLUSTER_DIAMETER 80\n")})
        a = mod._reference_flow_pnr_audit(tmp_path)
        assert a["status"] == "knobs-adopted"
        assert a["applied"]["die_target_util"] == 0.35
        assert a["applied"]["cts_cluster_diameter"] == 80.0
        srcs = {x["source"] for x in a["adopted"]}
        assert srcs == {"input/reference_flow/nested/vendor_flow.tcl"}

    def test_a_design_declaring_a_different_knob_subset(self, tmp_path):
        # A design that names ONLY a placement density gets exactly that
        # knob — no ibex-shaped defaults come along for the ride.
        _stage(tmp_path, {"flow.mk": "PLACE_DENSITY := 0.60\n"})
        a = mod._reference_flow_pnr_audit(tmp_path)
        assert a["applied"]["place_density"] == 0.60
        assert a["applied"]["die_target_util"] is None
        assert a["applied"]["repair_tns_percent"] is None
        assert a["applied"]["cts_cluster_size"] is None

    def test_two_designs_same_flow_served_identically(self, tmp_path):
        # chip-AGNOSTIC: the same staged flow yields the same decisions
        # regardless of the surrounding project.
        a_dir = tmp_path / "designA"
        b_dir = tmp_path / "designB"
        for d in (a_dir, b_dir):
            _stage(d, {"orfs_config.mk": _IBEX_MK})
        (b_dir / "rtl").mkdir()
        (b_dir / "rtl" / "unrelated.v").write_text("module u(); endmodule\n")
        aa = mod._reference_flow_pnr_audit(a_dir)
        bb = mod._reference_flow_pnr_audit(b_dir)
        assert aa["applied"] == bb["applied"]
        assert aa["status"] == bb["status"] == "knobs-adopted"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
