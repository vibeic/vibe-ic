"""Unit tests for the Phase-3-backend systematic fixes in
phase3_one_shot_runner.py (DRC stdcell classifier broadening, vacuous-
Magic detection, KLayout-streamout false-positive re-stream heuristic,
--util normalization, SV synth frontend selection).

All tests are docker-free: they exercise the pure-logic helpers with
synthetic inputs. They DO NOT spawn any container.

CRITICAL honesty-gate assertions live here too: a genuine met2+ routing
violation must still be classified user-routing (→ FAIL), and a vacuous
Magic 0-count must never be reported as a clean pass.
"""
import importlib
import json
import pathlib
import sys

import pytest

mod = importlib.import_module("phase3_one_shot_runner")


# ---------------------------------------------------------------------------
# Fix #4 — --util normalization
# ---------------------------------------------------------------------------
class TestUtilNormalization:
    def test_fraction_passthrough(self):
        u, warn = mod._normalize_util(0.45)
        assert u == 0.45
        assert warn is None

    def test_one_is_valid(self):
        u, warn = mod._normalize_util(1.0)
        assert u == 1.0
        assert warn is None

    def test_percent_20_normalizes_to_fraction(self):
        u, warn = mod._normalize_util(20)
        assert u == pytest.approx(0.20)
        assert warn is not None and "percentage" in warn.lower()

    def test_percent_25_normalizes(self):
        u, warn = mod._normalize_util(25)
        assert u == pytest.approx(0.25)
        assert warn

    def test_huge_percent_clamps_to_one(self):
        # 250 → 2.5 → still > 1 → clamp to 1.0
        u, warn = mod._normalize_util(250)
        assert u == 1.0
        assert warn

    def test_zero_or_negative_clamps_positive(self):
        u, warn = mod._normalize_util(0)
        assert 0.0 < u <= 1.0
        assert warn
        u2, warn2 = mod._normalize_util(-5)
        assert 0.0 < u2 <= 1.0
        assert warn2

    def test_nonnumeric_falls_back(self):
        # v0.1.44 spm pilot Tier 1.5: default fallback changed 0.45 → 0.30
        # (0.45 produced 1780 SKY130A DRC violations on spm 200x200 die;
        # 0.30 produces 0 violations same die).
        u, warn = mod._normalize_util("abc")
        assert u == 0.30
        assert warn

    def test_result_always_in_unit_interval(self):
        for v in (0.01, 0.5, 1, 5, 45, 95, 100, 150, 1000):
            u, _ = mod._normalize_util(v)
            assert 0.0 < u <= 1.0


# ---------------------------------------------------------------------------
# Fix #1 — DRC stdcell-library classifier broadening + honesty gate
# ---------------------------------------------------------------------------
class TestStdcellClassifier:
    def test_li_still_waivable(self):
        per = {"li.1": 97, "li.3": 2152, "li.5": 3}
        user, cell = mod._v1_6_604_classify_stdcell_violations(per, "sky130A")
        assert user == {}
        assert sum(cell.values()) == 97 + 2152 + 3

    def test_contact_licon_waivable_on_sky130(self):
        per = {"ct.1": 10, "licon.1": 5, "ct.3a": 2}
        user, cell = mod._v1_6_604_classify_stdcell_violations(per, "sky130A")
        assert user == {}
        assert sum(cell.values()) == 17

    def test_m1_met1_waivable_on_sky130(self):
        per = {"m1.1": 4, "m1.2": 8, "met1.3": 1}
        user, cell = mod._v1_6_604_classify_stdcell_violations(per, "sky130A")
        assert user == {}
        assert sum(cell.values()) == 13

    def test_met2_is_user_routing_FAIL(self):
        # HONESTY GATE: a met2 (user-routing) violation must NOT be waived.
        per = {"m2.1": 3}
        user, cell = mod._v1_6_604_classify_stdcell_violations(per, "sky130A")
        assert user == {"m2.1": 3}
        assert cell == {}

    def test_mixed_met1_and_met2_keeps_user_routing(self):
        # m1 stdcell-internal, m2 user-routing → user bucket non-empty → FAIL.
        per = {"m1.1": 100, "m2.2": 1}
        user, cell = mod._v1_6_604_classify_stdcell_violations(per, "sky130A")
        assert user == {"m2.2": 1}
        assert cell == {"m1.1": 100}

    def test_via2_and_above_is_user_routing(self):
        per = {"via2.1": 2, "via3.4": 1, "m3.2": 5}
        user, cell = mod._v1_6_604_classify_stdcell_violations(per, "sky130A")
        assert sum(user.values()) == 8
        assert cell == {}

    def test_user_routing_prefix_overrides_table(self):
        # Even if a met2 rule somehow matched a stdcell prefix, the
        # honesty gate takes precedence.
        assert mod._v1_6_604_rule_is_user_routing("met2.1")
        assert mod._v1_6_604_rule_is_user_routing("m3.7")
        assert not mod._v1_6_604_rule_is_user_routing("li.1")
        assert not mod._v1_6_604_rule_is_user_routing("ct.1")
        assert not mod._v1_6_604_rule_is_user_routing("m1.1")

    def test_unknown_pdk_no_autowaiver(self):
        # No table entry + no geometry hints → everything is user-routing.
        per = {"li.1": 5, "ct.1": 2}
        user, cell = mod._v1_6_604_classify_stdcell_violations(per, "unknownPDK")
        assert user == per
        assert cell == {}

    def test_gf180_li_only(self):
        # gf180 table only waives li.* (contact/m1 not yet characterised).
        per = {"li.1": 5, "ct.1": 2, "m1.1": 3}
        user, cell = mod._v1_6_604_classify_stdcell_violations(per, "gf180mcuD")
        assert cell == {"li.1": 5}
        assert user == {"ct.1": 2, "m1.1": 3}

    def test_geometry_inside_cells_classifies(self):
        per = {"someRule.1": 2}
        # both violations wholly inside a single cell bbox → geo waivable
        vios = [
            {"rule": "someRule.1", "x0": 1, "y0": 1, "x1": 2, "y1": 2},
            {"rule": "someRule.1", "x0": 3, "y0": 3, "x1": 4, "y1": 4},
        ]
        bboxes = [(0, 0, 10, 10)]
        geo = mod._classify_geometry_inside_cells(vios, bboxes)
        assert geo == {"someRule.1"}
        user, cell = mod._v1_6_604_classify_stdcell_violations(
            per, "sky130A", cell_internal_rules=geo)
        assert cell == {"someRule.1": 2}
        assert user == {}

    def test_geometry_one_outside_not_waived(self):
        vios = [
            {"rule": "r.1", "x0": 1, "y0": 1, "x1": 2, "y1": 2},
            {"rule": "r.1", "x0": 100, "y0": 100, "x1": 101, "y1": 101},
        ]
        bboxes = [(0, 0, 10, 10)]
        geo = mod._classify_geometry_inside_cells(vios, bboxes)
        assert "r.1" not in geo

    def test_geometry_never_overrides_honesty_gate(self):
        # Even if geometry says a met2 rule is inside a cell, the
        # user-routing gate must still keep it user-routing.
        geo = {"m2.1"}
        per = {"m2.1": 3}
        user, cell = mod._v1_6_604_classify_stdcell_violations(
            per, "sky130A", cell_internal_rules=geo)
        assert user == {"m2.1": 3}
        assert cell == {}


# ---------------------------------------------------------------------------
# Fix #2 — vacuous Magic detection
# ---------------------------------------------------------------------------
class TestVacuousMagic:
    def test_unknown_layer_zero_drc_is_vacuous(self):
        t = ("Unknown layer/datatype in GDS file\n"
             "Unknown layer/datatype in GDS file\n"
             "MAGIC_DRC_COUNT 0\n")
        v = mod._detect_vacuous_magic(t, drc_count=0)
        assert v["vacuous"] is True
        assert v["geometry_loaded"] is False
        assert v["unknown_layer_errors"] == 2

    def test_zero_cells_loaded_is_vacuous(self):
        t = "Loaded 0 cells\nMAGIC_DRC_COUNT 0\n"
        v = mod._detect_vacuous_magic(t, drc_count=0)
        assert v["vacuous"] is True
        assert v["cells_loaded"] == 0

    def test_empty_bbox_is_vacuous(self):
        t = "box values 0 0 0 0\nMAGIC_DRC_COUNT 0\n"
        v = mod._detect_vacuous_magic(t, drc_count=0)
        assert v["vacuous"] is True
        assert v["empty_bbox"] is True

    def test_normal_load_zero_drc_is_NOT_vacuous(self):
        # Geometry loaded fine + 0 DRC → a real clean pass, not vacuous.
        t = "Loaded 1234 cells\nMAGIC_DRC_COUNT 0\n"
        v = mod._detect_vacuous_magic(t, drc_count=0)
        assert v["vacuous"] is False
        assert v["geometry_loaded"] is True

    def test_dropped_geometry_with_nonzero_drc_geometry_flag(self):
        # geometry not loaded but a count present (rare): geometry_loaded
        # must still be False so callers treat the count as suspect.
        t = "Unknown layer/datatype\nMAGIC_DRC_COUNT 5\n"
        v = mod._detect_vacuous_magic(t, drc_count=5)
        assert v["geometry_loaded"] is False
        # vacuous specifically tracks the 0/unknown count case
        assert v["vacuous"] is False


# ---------------------------------------------------------------------------
# Fix #3 — KLayout-streamout false-positive dominance + discrepancy
# ---------------------------------------------------------------------------
class TestStreamoutFalsePositive:
    def test_spacing_width_dominated(self):
        per = {"met1.2": 9500, "met1.1": 400, "li.1": 100}
        dominated, frac = mod._klayout_streamout_false_positive_dominated(per)
        assert dominated is True
        assert frac > 0.9

    def test_not_dominated_when_mixed(self):
        per = {"met1.2": 100, "antenna.1": 900}
        dominated, frac = mod._klayout_streamout_false_positive_dominated(per)
        assert dominated is False

    def test_empty_not_dominated(self):
        dominated, frac = mod._klayout_streamout_false_positive_dominated({})
        assert dominated is False
        assert frac == 0.0

    def test_rule_is_spacing_or_width(self):
        assert mod._rule_is_spacing_or_width("met1.spacing")
        assert mod._rule_is_spacing_or_width("met2.width")
        assert mod._rule_is_spacing_or_width("li.2")  # spacing index
        assert mod._rule_is_spacing_or_width("li.1")  # width index
        assert not mod._rule_is_spacing_or_width("antenna.5")

    def test_discrepancy_text_with_openroad(self):
        s = mod._format_drc_engine_discrepancy(0, 9000)
        assert "0" in s and "9000" in s and "gap=9000" in s

    def test_discrepancy_text_without_openroad(self):
        s = mod._format_drc_engine_discrepancy(None, 9000)
        assert "unavailable" in s and "9000" in s

    def test_extract_openroad_drt_violations(self):
        log = ("[INFO DRT-0199] iteration 1 had 50 violations\n"
               "[INFO DRT-0199] iteration 9 had 0 violations\n")
        assert mod._extract_openroad_drt_violations(log) == 0

    def test_extract_openroad_drt_violations_alt_form(self):
        log = "number of DRC violations = 3\n"
        assert mod._extract_openroad_drt_violations(log) == 3

    def test_extract_openroad_none(self):
        assert mod._extract_openroad_drt_violations("nothing here") is None


# ---------------------------------------------------------------------------
# Fix #5 — SV synth frontend selection
# ---------------------------------------------------------------------------
class TestSynthFrontendSelection:
    def test_default_success_no_fallback(self):
        files = ["a.sv", "b.v"]
        need, reason = mod._decide_synth_frontend(
            files, default_rc=0, default_netlist_exists=True,
            default_log="")
        assert need is False

    def test_sv_signature_triggers_fallback(self):
        files = ["a.v"]
        need, reason = mod._decide_synth_frontend(
            files, default_rc=1, default_netlist_exists=False,
            default_log="ERROR: syntax error in package import")
        assert need is True

    def test_sv_extension_triggers_fallback_on_failure(self):
        files = ["core.sv", "pkg.sv"]
        need, reason = mod._decide_synth_frontend(
            files, default_rc=1, default_netlist_exists=False,
            default_log="some unrelated error")
        assert need is True
        assert ".sv" in reason

    def test_no_sv_no_signature_no_fallback(self):
        files = ["plain.v"]
        need, reason = mod._decide_synth_frontend(
            files, default_rc=1, default_netlist_exists=False,
            default_log="ERROR: undefined module foo")
        assert need is False

    def test_tok_import_signature(self):
        files = ["a.v"]
        need, _ = mod._decide_synth_frontend(
            files, default_rc=1, default_netlist_exists=False,
            default_log="unexpected TOK_IMPORT")
        assert need is True


# ---------------------------------------------------------------------------
# v0.1.46 / v0.1.47 / v0.1.48 — silicon-critical PnR block presence gates
# ---------------------------------------------------------------------------
# Closed-loop regression tests for the 3 silicon-critical fixes shipped from
# the spm pilot (benchmark_clean/spm_pilot_v0144/RESULT_tier{2,5}*.md):
#   v0.1.46 — tapcell insertion (latch-up well-tie density; was 0 → 384 taps)
#   v0.1.47 — pdngen insertion (SPECIALNETS; was 0 → present → silicon-alive)
#   v0.1.48 — filler_placement (decap + fill; was 0 → 2079 decap + 150 fill)
# Each was a fresh "design ran clean PASS but silicon would be DOA" failure
# mode in a prior plugin version. These tests pin the block emit so any
# regression is caught by pytest (not by another full silicon handoff).
class TestSiliconCriticalPnrBlocks:
    @staticmethod
    def _sky130_pdk():
        # The minimal PdkConfig that exercises the "sky130-style" branch.
        # All path fields are placeholders — these tests are pure-logic.
        return mod.PdkConfig(
            name="sky130A",
            liberty="/placeholder/sky130_fd_sc_hd__tt_025C_1v80.lib",
            tech_lef="/placeholder/sky130_fd_sc_hd.tlef",
            cell_lef="/placeholder/sky130_fd_sc_hd.lef",
            cell_gds="/placeholder/sky130_fd_sc_hd.gds",
            site="unithd",
            drc_deck="/placeholder/sky130A_mr.drc",
            metal_prefix="met",
            tapcell_master="sky130_fd_sc_hd__tapvpwrvgnd_1",
            tapcell_distance_um=14.0,
        )

    @staticmethod
    def _no_tapcell_pdk():
        # A PDK that doesn't ship a tapcell master — the runner must
        # gracefully emit a SKIPPED line on each of the 3 blocks.
        return mod.PdkConfig(
            name="customPDK",
            liberty="/placeholder/lib.lib",
            tech_lef="/placeholder/tech.lef",
            cell_lef="/placeholder/cells.lef",
            cell_gds=None,
            site="sitename",
            drc_deck=None,
            metal_prefix="met",
            tapcell_master=None,
        )

    # ---- v0.1.46 tapcell -----------------------------------------------
    def test_tapcell_block_present_on_sky130(self):
        tcl = mod._build_tapcell_tcl(self._sky130_pdk())
        assert "tapcell -distance 14.0" in tcl
        assert "sky130_fd_sc_hd__tapvpwrvgnd_1" in tcl
        assert "TAPCELL_INSERTED" in tcl
        # NONFATAL guard prevents the whole flow from aborting if the
        # OpenROAD tapcell command errors on a future PDK update.
        assert "TAPCELL_NONFATAL" in tcl

    def test_tapcell_block_skipped_when_no_master(self):
        tcl = mod._build_tapcell_tcl(self._no_tapcell_pdk())
        assert "TAPCELL_SKIPPED" in tcl
        # SKIPPED branch MUST NOT silently pretend tapcell ran — the
        # message must surface the latch-up risk for the audit trail.
        assert "latch-up risk" in tcl
        # And it must NOT contain a real tapcell command (otherwise the
        # PDK-without-master case would error inside Tcl).
        assert "tapcell -distance" not in tcl

    def test_tapcell_block_obeys_custom_distance(self):
        pdk = self._sky130_pdk()
        pdk.tapcell_distance_um = 25.0
        tcl = mod._build_tapcell_tcl(pdk)
        assert "tapcell -distance 25.0" in tcl

    # ---- v0.1.47 pdngen ------------------------------------------------
    def test_pdn_block_present_on_sky130(self):
        tcl = mod._build_pdn_tcl(self._sky130_pdk())
        # Required PDN-flow commands. Any of these missing = floating
        # power pins = silicon DOA.
        for required in (
            "add_global_connection -net VPWR",
            "add_global_connection -net VGND",
            "set_voltage_domain",
            "define_pdn_grid",
            "add_pdn_stripe -grid grid -layer met1",
            "-followpins",                 # met1 follow-pins (cell-row power)
            "add_pdn_stripe -grid grid -layer met4",
            "add_pdn_connect",
            "pdngen",
            "PDN_INSERTED",
        ):
            assert required in tcl, f"PDN block missing required command: {required!r}"
        # NONFATAL guard
        assert "PDN_NONFATAL" in tcl

    def test_pdn_block_skipped_when_no_pdk(self):
        tcl = mod._build_pdn_tcl(self._no_tapcell_pdk())
        assert "PDN_SKIPPED" in tcl
        assert "silicon DOA" in tcl
        # MUST NOT silently emit a half-PDN
        assert "define_pdn_grid" not in tcl
        assert "pdngen" not in tcl

    # ---- PDK-adaptive PDN (commercial VDD/VSS) -------------------------
    _COMMERCIAL_LEF = (
        "MACRO INVD1\n"
        "  SIZE 1.32 BY 5.04 ;\n"
        "  PIN VDD\n    USE POWER ;\n    PORT\n      LAYER MET1 ;\n"
        "        RECT 0 4.64 1.32 5.44 ;\n    END\n  END VDD\n"
        "  PIN VSS\n    USE GROUND ;\n    PORT\n      LAYER MET1 ;\n"
        "        RECT 0 -0.4 1.32 0.4 ;\n    END\n  END VSS\n"
        "  PIN A\n    DIRECTION INPUT ;\n    PORT\n      LAYER MET1 ;\n"
        "        RECT 0.2 1.0 0.4 1.4 ;\n    END\n  END A\n"
        "END INVD1\n")

    # A minimal multi-metal stack so the adaptive PDN can derive its straps.
    # Names/values are generic — this fixture stands for ANY PDK reaching the
    # adaptive path, not a particular one.
    _STACK_TLEF = "".join(
        f"LAYER MET{i}\n  TYPE ROUTING ;\n  DIRECTION {d} ;\n"
        f"  PITCH 0.5 ;\n  WIDTH 0.2 ;\nEND MET{i}\n"
        for i, d in enumerate(
            ["HORIZONTAL", "VERTICAL", "HORIZONTAL", "VERTICAL"], 1))

    def _commercial_pdk(self, lef_path):
        # A non-sky130 PDK (VDD/VSS rails, no tapcell_master) — the commercial PDK
        # shape. tapcell_master None → adaptive PDN path. A real tech LEF is
        # written next to the cell LEF because the adaptive PDN now DERIVES its
        # upper-metal straps from the routing stack; a PDK that cannot be
        # strapped is reported PDN_NO_STRAPS rather than passing hollow, which
        # is covered separately below.
        tlef = pathlib.Path(lef_path).parent / "tech.lef"
        tlef.write_text(self._STACK_TLEF)
        return mod.PdkConfig(
            name="custom:commercial_pdk", liberty="/p/l.lib",
            tech_lef=str(tlef), cell_lef=str(lef_path), cell_gds=None,
            site="unit", drc_deck=None, metal_prefix="met",
            tapcell_master=None)

    def test_discover_pg_from_lef_commercial_vdd_vss(self, tmp_path):
        lef = tmp_path / "cells.lef"
        lef.write_text(self._COMMERCIAL_LEF)
        pg = mod._discover_pg_from_lef(str(lef))
        assert pg == ("VDD", "VSS", "MET1", 0.8), pg

    def test_discover_pg_from_lef_none_without_pg_pins(self, tmp_path):
        lef = tmp_path / "nopg.lef"
        lef.write_text("MACRO X\n  SIZE 1 BY 1 ;\n  PIN A\n    DIRECTION "
                       "INPUT ;\n  END A\nEND X\n")
        assert mod._discover_pg_from_lef(str(lef)) is None

    def test_pdn_adaptive_on_commercial_pdk(self, tmp_path):
        # The commercial PDK must get a REAL met1 follow-pins PDN using the
        # DISCOVERED rail names (VDD/VSS) — not the sky130 VPWR/VGND hardcode,
        # which matches nothing → no PDN → TritonRoute ignores the bare power
        # rails → signal routes land <min-space (commercial PDK M1.S.1). Follow-pins
        # turns each rail into routed PG geometry the router keeps clear of.
        lef = tmp_path / "cells.lef"
        lef.write_text(self._COMMERCIAL_LEF)
        tcl = mod._build_pdn_tcl(self._commercial_pdk(lef))
        assert "PDN_INSERTED_ADAPTIVE" in tcl
        assert 'add_global_connection -net VDD -pin_pattern "^VDD$" -power' in tcl
        assert 'add_global_connection -net VSS -pin_pattern "^VSS$" -ground' in tcl
        assert "add_pdn_stripe -grid grid -layer MET1 -width 0.8 -followpins" in tcl
        assert "pdngen" in tcl
        assert "PDN_NONFATAL" in tcl
        # Must NOT emit the sky130-only pin names (they match no commercial PDK pin).
        assert "VPWR" not in tcl and "VGND" not in tcl

    def test_pdn_block_pins_VPB_and_VNB_for_sky130(self):
        # SKY130 std cells expose well-tap pins as VPB / VNB (not VPWR/VGND).
        # If global_connect misses these, every cell's bulk floats →
        # latch-up + functional broken. Regression-pin both.
        tcl = mod._build_pdn_tcl(self._sky130_pdk())
        assert "VPB" in tcl
        assert "VNB" in tcl

    # ---- v0.1.48 filler_placement --------------------------------------
    def test_filler_masters_keep_the_decaps_for_a_normal_die(self):
        """The MASTER LIST is unchanged, and that is deliberate.

        An earlier revision of this fix dropped the decap family globally. It
        should not, and the reason is a measurement on the reference die: the
        published gf180mcuD `spm` cell that passes the shuttle operator's
        precheck end-to-end carries **968 `fillcap_*` decap instances** among
        9115 spacers (counted from its own shipped GDS). That die is dense, the
        #684 tap prune never fired on it, its decaps are fully tied, and they
        are the dynamic-IR decoupling it was signed off with. Deleting them
        globally would change a known-good result to buy nothing.

        The decap exclusion belongs to the ONE arm where it was measured -- a
        sparse die whose ties the prune has removed -- and it is applied there,
        in `_build_sparse_die_aware_filler_tcl`, not here.
        """
        masters = mod._filler_masters_for_pdk(self._sky130_pdk())
        decap = [m for m in masters if "decap" in m or "dcap" in m]
        fill = [m for m in masters if m.startswith("sky130_fd_sc_hd__fill_")]
        assert len(decap) >= 3, f"decap variants must survive: {decap}"
        assert len(fill) >= 3, f"fill variants too few: {fill}"
        # Largest-first ordering (OpenROAD convention), unchanged.
        assert masters.index("sky130_fd_sc_hd__decap_12") < masters.index(
            "sky130_fd_sc_hd__decap_3")
        assert masters.index("sky130_fd_sc_hd__fill_8") < masters.index(
            "sky130_fd_sc_hd__fill_1")

    def test_spacer_filter_drops_devices_and_keeps_order(self):
        """`_spacer_masters_of` is the device-free projection of that list."""
        masters = mod._filler_masters_for_pdk(self._sky130_pdk())
        spacers = mod._spacer_masters_of(masters)
        assert spacers, "a PDK with fill cells must yield spacers"
        assert not [m for m in spacers if "decap" in m or "dcap" in m]
        assert spacers == [m for m in masters if m in spacers], "order kept"

    def test_filler_masters_exclusion_is_pdk_agnostic(self):
        """The exclusion is by name SEGMENT, so it holds for any PDK's naming.

        The four families below are exactly the four the shuttle operator's own
        per-run `resolved.json` names: `FILL_CELLS` = `*__fill_*`,
        `DECAP_CELLS` = `*__fillcap_*`, `WELLTAP_CELL` = `*__filltie`,
        `ENDCAP_CELL` = `*__endcap`. A classifier that disagreed with the
        operator about which cells are fill would be wrong by their definition,
        not just by ours.
        """
        for name in ("DECAP8", "lib__decap_12", "sg13g2_dcap_4",
                     "gf_fd_sc__fillcap_64"):
            assert mod._FILLER_DECAP_RE.search(name), name
        for name in ("lib__fill_8", "sg13g2_fill_1", "FILL64",
                     "lib__filltie", "lib__endcap"):
            assert not mod._FILLER_DECAP_RE.search(name), name

    def test_filler_masters_empty_when_unknown_pdk(self):
        masters = mod._filler_masters_for_pdk(self._no_tapcell_pdk())
        assert masters == []

    # ---- Cross-block invariants ----------------------------------------
    def test_three_blocks_all_nonfatal_guarded(self):
        # HONESTY GATE: if any of the 3 silicon-critical Tcl blocks raises
        # an unguarded error, the entire OpenROAD invocation aborts and the
        # runner reports FAIL — instead of degrading to NONFATAL with a
        # surfaced log line. Pin the NONFATAL guard on each block.
        pdk = self._sky130_pdk()
        assert "catch" in mod._build_tapcell_tcl(pdk)
        assert "catch" in mod._build_pdn_tcl(pdk)
        # Filler is rendered inline (not from a pure builder), so probe
        # by ensuring _filler_masters_for_pdk returns a non-empty list
        # for sky130 (i.e. the caller WILL emit the catch'd block).
        assert mod._filler_masters_for_pdk(pdk)

    def test_sky130_PdkConfig_carries_v0146_settings(self):
        # The PdkConfig factory used by the runner must wire the v0.1.46
        # tapcell defaults for sky130A. If a future refactor drops these,
        # tapcell falls back to SKIPPED and silicon ships latch-up-prone.
        pdk = self._sky130_pdk()
        assert pdk.tapcell_master == "sky130_fd_sc_hd__tapvpwrvgnd_1"
        assert pdk.tapcell_distance_um == 14.0
        # site == unithd is the SKY130 std-cell row site.
        assert pdk.site == "unithd"

    def test_default_util_is_030_for_sky130(self):
        # v0.1.45 fix: bumped default 0.45 → 0.30 because 0.45 produced
        # 1780 DRC violations on the spm 200x200 die. The util-normalizer
        # falls back to 0.30 on nonnumeric input; pin that.
        u, _ = mod._normalize_util("default")
        assert u == 0.30


# ---------------------------------------------------------------------------
# ORGANIC E2E (GAP-E2E-4/10) — die AUTO-SIZING from synth cell count
# Validated against the end-to-end campaign's empirical data points:
#   sha256 (22,786 cells) stranded at 4% util on a fixed 1500x1500 → route
#   plateau; aes (39,180 cells) converged only at 1400x1400 (~15% util).
# ---------------------------------------------------------------------------
class TestDieAutoSizing:
    _SITE_AREA = 1.2512  # sky130_fd_sc_hd unithd: 0.46 x 2.72

    def test_parse_site_area_from_lef(self):
        lef = ("SITE unithd\n  SYMMETRY Y ;\n  CLASS CORE ;\n"
               "  SIZE 0.46 BY 2.72 ;\nEND unithd\n")
        assert mod._parse_site_area_um2(lef) == pytest.approx(1.2512, rel=1e-3)

    def test_parse_site_area_missing_returns_none(self):
        assert mod._parse_site_area_um2("no site here") is None
        assert mod._parse_site_area_um2("") is None
        assert mod._parse_site_area_um2(None) is None

    def test_auto_die_sizes_to_target_util(self):
        avg = self._SITE_AREA * mod._AUTO_DIE_AVG_SITES_PER_CELL
        side = mod._auto_die_side_um(22786, 0.40, avg)
        # design lands near the requested 40% util (not the fixed-die 4%)
        util = 22786 * avg / (side * side)
        assert 0.30 <= util <= 0.50
        assert 500 <= side <= 800   # NOT 1500 (the stranding fixed default)

    def test_auto_die_matches_aes_empirical_converge(self):
        # aes converged at 1400x1400 (~15% util); the helper reproduces it.
        avg = self._SITE_AREA * mod._AUTO_DIE_AVG_SITES_PER_CELL
        side = mod._auto_die_side_um(39180, 0.15, avg)
        assert 1350 <= side <= 1450

    def test_auto_die_monotonic_in_cell_count(self):
        avg = self._SITE_AREA * mod._AUTO_DIE_AVG_SITES_PER_CELL
        assert (mod._auto_die_side_um(1000, 0.4, avg)
                < mod._auto_die_side_um(50000, 0.4, avg))

    def test_auto_die_clamps_tiny_to_floor(self):
        avg = self._SITE_AREA * mod._AUTO_DIE_AVG_SITES_PER_CELL
        assert mod._auto_die_side_um(1, 0.4, avg) == mod._AUTO_DIE_MIN_SIDE_UM

    def test_auto_die_clamps_huge_to_max(self):
        avg = self._SITE_AREA * mod._AUTO_DIE_AVG_SITES_PER_CELL
        assert (mod._auto_die_side_um(10_000_000, 0.4, avg)
                == mod._DEFAULT_DIE_MAX_UM)

    def test_auto_die_bad_util_falls_back(self):
        avg = self._SITE_AREA * mod._AUTO_DIE_AVG_SITES_PER_CELL
        # util 0 / >1 / negative → the default target util, never a crash
        assert mod._auto_die_side_um(1000, 0.0, avg) > 0
        assert mod._auto_die_side_um(1000, -1.0, avg) > 0

    def test_resolve_passes_explicit_die_through_unchanged(self):
        import pathlib
        out, note = mod._resolve_auto_die_um(
            "900x900", pathlib.Path("/nonexistent"), 0.4, None)
        assert out == "900x900" and note is None

    def test_resolve_auto_zero_cells_falls_back_safely(self, tmp_path):
        # 'auto' with an unreadable/empty netlist must not crash → safe fixed die
        nl = tmp_path / "empty_synth.v"
        nl.write_text("// no instances\n")

        class _Pdk:
            cell_lef = "/nonexistent.lef"
        out, note = mod._resolve_auto_die_um("auto", nl, 0.4, _Pdk())
        assert "x" in out and note is not None  # a real WxH + a disclosure note


# ---------------------------------------------------------------------------
# ORGANIC E2E (GAP-E2E-2) — CONTAINER corner-liberty discovery
# The runner runs on the host but the built-in PDK's ss/tt/ff libs live in the
# container fs (invisible to a host glob) → a false single_corner_stance on
# every sky130A run (spm/aes/subservient/caravel/sha256). Discover via docker.
# ---------------------------------------------------------------------------
class TestContainerCornerDiscovery:
    _SKY130_LIBS = [
        ("sky130_fd_sc_hd__ss_100C_1v40",
         "/foss/pdks/sky130A/.../lib/sky130_fd_sc_hd__ss_100C_1v40.lib"),
        ("sky130_fd_sc_hd__ss_100C_1v60",
         "/foss/pdks/sky130A/.../lib/sky130_fd_sc_hd__ss_100C_1v60.lib"),
        ("sky130_fd_sc_hd__ss_n40C_1v28",
         "/foss/pdks/sky130A/.../lib/sky130_fd_sc_hd__ss_n40C_1v28.lib"),
        ("sky130_fd_sc_hd__tt_025C_1v80",
         "/foss/pdks/sky130A/.../lib/sky130_fd_sc_hd__tt_025C_1v80.lib"),
        ("sky130_fd_sc_hd__ff_n40C_1v95",
         "/foss/pdks/sky130A/.../lib/sky130_fd_sc_hd__ff_n40C_1v95.lib"),
        ("sky130_fd_sc_hd__ff_100C_1v65",
         "/foss/pdks/sky130A/.../lib/sky130_fd_sc_hd__ff_100C_1v65.lib"),
    ]

    def test_select_one_representative_per_label(self):
        corners = mod._select_signoff_corners(self._SKY130_LIBS)
        labels = [c["label"] for c in corners]
        assert labels == ["SS", "TT", "FF"]          # ordered, one each
        assert len(corners) == 3                      # ≥2 ⇒ multi-corner

    def test_select_prefers_canonical_signoff_names(self):
        corners = {c["label"]: c["name"]
                   for c in mod._select_signoff_corners(self._SKY130_LIBS)}
        assert corners["TT"] == "sky130_fd_sc_hd__tt_025C_1v80"
        assert corners["SS"] == "sky130_fd_sc_hd__ss_100C_1v60"   # sky130 ref slow (-10%)
        assert corners["FF"] == "sky130_fd_sc_hd__ff_n40C_1v95"   # fast-cold

    def test_select_falls_back_to_any_lib_of_label(self):
        # only an ss lib whose name is NOT the canonical preference → still picked
        corners = mod._select_signoff_corners(
            [("sky130_fd_sc_hd__ss_n40C_1v28",
              "/x/sky130_fd_sc_hd__ss_n40C_1v28.lib")])
        assert len(corners) == 1 and corners[0]["label"] == "SS"

    def test_select_empty_on_no_libs(self):
        assert mod._select_signoff_corners([]) == []

    def test_select_follows_pdk_reference_sta_corners(self, monkeypatch):
        """AUTHORITATIVE: the SS representative FOLLOWS the PDK's own librelane
        STA_CORNERS, not a hardcode. Differential control: a config declaring
        ss_100C_1v60 picks 1v60; a config declaring ss_100C_1v40 picks 1v40 —
        from the SAME lib list — proving the pick tracks the reference config."""
        libs = [
            ("sky130_fd_sc_hd__ss_100C_1v40", "/p/sky130_fd_sc_hd__ss_100C_1v40.lib"),
            ("sky130_fd_sc_hd__ss_100C_1v60", "/p/sky130_fd_sc_hd__ss_100C_1v60.lib"),
            ("sky130_fd_sc_hd__tt_025C_1v80", "/p/sky130_fd_sc_hd__tt_025C_1v80.lib"),
            ("sky130_fd_sc_hd__ff_n40C_1v95", "/p/sky130_fd_sc_hd__ff_n40C_1v95.lib"),
        ]
        mod._REF_SIGNOFF_CORNER_STEMS_CACHE.clear()

        def _cfg(text):
            return lambda c, cmd, timeout=60, **_: (0, text, "")

        libdir = "/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib"

        # reference declares ss_100C_1v60 -> pick 1v60
        monkeypatch.setattr(mod, "_docker_exec", _cfg(
            "set ::env(STA_CORNERS) nom_tt_025C_1v80 nom_ss_100C_1v60 "
            "nom_ff_n40C_1v95 max_ss_100C_1v60 max_tt_025C_1v80"))
        got = {c["label"]: c["name"]
               for c in mod._select_signoff_corners(libs, "ct60", libdir)}
        assert got["SS"] == "sky130_fd_sc_hd__ss_100C_1v60"

        # NEGATIVE CONTROL: reference declares ss_100C_1v40 -> pick 1v40
        # (the pick TRACKS the config, it is not hardcoded)
        mod._REF_SIGNOFF_CORNER_STEMS_CACHE.clear()
        monkeypatch.setattr(mod, "_docker_exec", _cfg(
            "set ::env(STA_CORNERS) nom_tt_025C_1v80 nom_ss_100C_1v40 "
            "nom_ff_n40C_1v95"))
        got2 = {c["label"]: c["name"]
                for c in mod._select_signoff_corners(libs, "ct40", libdir)}
        assert got2["SS"] == "sky130_fd_sc_hd__ss_100C_1v40"

    def test_reference_corner_stems_failsafe_empty(self, monkeypatch):
        """No container / docker failure -> empty stem set -> selection degrades
        to the hardcoded preference (byte-identical to pre-fix)."""
        mod._REF_SIGNOFF_CORNER_STEMS_CACHE.clear()
        assert mod._pdk_reference_signoff_corner_stems("", "/x/libs.ref/y/lib") == set()
        def _boom(c, cmd, timeout=60, **_):
            raise RuntimeError("docker down")
        monkeypatch.setattr(mod, "_docker_exec", _boom)
        mod._REF_SIGNOFF_CORNER_STEMS_CACHE.clear()
        assert mod._pdk_reference_signoff_corner_stems(
            "ct", "/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib") == set()

    def test_discover_parses_container_ls(self, monkeypatch):
        out = ("/foss/pdks/sky130A/.../lib/sky130_fd_sc_hd__ss_100C_1v40.lib\n"
               "/foss/pdks/sky130A/.../lib/sky130_fd_sc_hd__tt_025C_1v80.lib\n"
               "/foss/pdks/sky130A/.../lib/sky130_fd_sc_hd__ff_n40C_1v95.lib\n"
               "some_noise_line\n")
        monkeypatch.setattr(mod, "_docker_exec",
                            lambda c, cmd, timeout=60, **_: (0, out, ""))
        libs = mod._discover_container_corner_libs(
            "vibeic-eda", "/foss/pdks/sky130A/.../lib")
        assert len(libs) == 3                      # only *.lib lines
        assert all(p.endswith(".lib") for _, p in libs)
        corners = mod._select_signoff_corners(libs)
        assert [c["label"] for c in corners] == ["SS", "TT", "FF"]

    def test_discover_empty_on_no_container(self):
        assert mod._discover_container_corner_libs("", "/x/lib") == []
        assert mod._discover_container_corner_libs("iic", "") == []

    def test_discover_safe_on_docker_failure(self, monkeypatch):
        def _boom(c, cmd, timeout=60, **_):
            raise RuntimeError("docker down")
        monkeypatch.setattr(mod, "_docker_exec", _boom)
        assert mod._discover_container_corner_libs("iic", "/x/lib") == []


class TestShipSignoffSpefRepairPromotion:
    """#527 estimate-vs-SPEF — the SHIPPED post-route real-SPEF repair promotes the
    repaired route as sign-off ONLY when it reaches non-negative setup AND the
    reroute is DRC-clean; otherwise the base route is kept (no DRC regression)."""

    _CLEAN = ("SHIP_WNS_BEFORE: -16.65\nSHIP_WNS_AFTER_REPAIR: 0.027\n"
              "[INFO DRT-0199] Number of violations = 0.\nSHIP_SIGNOFF_REPAIR_DONE\n")

    def test_parse_extracts_markers_and_violations(self):
        p = mod._parse_ship_repair_log(self._CLEAN)
        assert p["wns_before"] == -16.65
        assert p["wns_after_repair"] == 0.027
        assert p["route_violations"] == 0
        assert p["done"] is True

    def test_promote_when_met_and_drc_clean(self):
        p = mod._parse_ship_repair_log(self._CLEAN)
        assert mod._ship_repair_should_promote(p, True, True) is True

    def test_no_promote_when_reroute_dirty(self):
        log = ("SHIP_WNS_AFTER_REPAIR: 0.5\nNumber of violations = 7000\n")
        assert mod._ship_repair_should_promote(
            mod._parse_ship_repair_log(log), True, True) is False

    def test_no_promote_when_setup_still_negative(self):
        log = ("SHIP_WNS_AFTER_REPAIR: -3.0\nNumber of violations = 0\n")
        assert mod._ship_repair_should_promote(
            mod._parse_ship_repair_log(log), True, True) is False

    def test_no_promote_when_no_violation_count_reported(self):
        # a reroute that never reported a violation count is NOT trusted clean
        log = ("SHIP_WNS_AFTER_REPAIR: 0.5\n")
        assert mod._ship_repair_should_promote(
            mod._parse_ship_repair_log(log), True, True) is False

    def test_no_promote_when_artifacts_missing(self):
        p = mod._parse_ship_repair_log(self._CLEAN)
        assert mod._ship_repair_should_promote(p, False, True) is False
        assert mod._ship_repair_should_promote(p, True, False) is False


# ---------------------------------------------------------------------------
# THE SLOT CONTRACT'S FLOORPLAN RECTANGLE, AND WHAT IT RESERVES AT THE DIE EDGE
#
# The three fixes below all decide what geometry lands at the die edge, so they
# are tested together. Each test states the RED it discriminates against — the
# behaviour on the revision before the fix — because a gate that cannot fail is
# not a gate.
# ---------------------------------------------------------------------------
class TestSlotPinnedFloorplanRectangle:
    #: The operator's own template shape, reduced to what `_slot_geometry`
    #: reads. Two slots, so a test can prove the DECLARED one is picked and not
    #: merely the first. Numbers are an open shuttle template's, and the point
    #: of them is only that die != core.
    @staticmethod
    def _template(declared="slot_A"):
        return {"ingest": {"declared_slot": declared, "slots": [
            {"slot": "slot_B",
             "die_area":  {"raw": [0, 0, 1936, 5122]},
             "core_area": {"raw": [442, 442, 1494, 4680]}},
            {"slot": "slot_A",
             "die_area":  {"raw": [0, 0, 1936, 2531]},
             "core_area": {"raw": [442, 442, 1494, 2089]},
             "source_relpath": "librelane/slots/slot_A.yaml",
             "source_sha256": "deadbeef"},
        ]}}

    @staticmethod
    def _write(tmp_path, doc):
        d = tmp_path / "reports" / "phase1"
        d.mkdir(parents=True, exist_ok=True)
        (d / "submission_template.json").write_text(json.dumps(doc))
        return tmp_path

    # ---- the declaration is READ, and it is the declared slot's ------------
    def test_reads_the_declared_slot_not_the_first_one(self, tmp_path):
        p = self._write(tmp_path, self._template())
        g = mod._slot_geometry(p)
        assert g is not None
        assert g["slot"] == "slot_A"
        assert g["core_rect"] == [442, 442, 1494, 2089]
        assert (g["die_w"], g["die_h"]) == (1936, 2531)
        # the reserved band is what the ring/pads stand in, on every side
        assert g["core_rect"][0] - g["die_rect"][0] == 442
        assert g["die_rect"][3] - g["core_rect"][3] == 442

    def test_absent_declaration_is_inert(self, tmp_path):
        """No template, no declared slot, and an unknown slot name must ALL
        return None — that is what keeps every non-shuttle design byte-for-byte
        on the historical `--die-um` + fixed-inset floorplan."""
        assert mod._slot_geometry(tmp_path) is None            # no file at all
        p = self._write(tmp_path, self._template(declared=None))
        assert mod._slot_geometry(p) is None                   # nothing declared
        p2 = self._write(tmp_path, self._template(declared="slot_MISSING"))
        assert mod._slot_geometry(p2) is None                  # declared, not present

    def test_degenerate_core_rect_is_refused(self, tmp_path):
        """An inverted / zero-area CORE_AREA must not become a floorplan. A
        silently-accepted empty rectangle would hand OpenROAD a die with no
        placeable area, which fails much later and much less legibly."""
        doc = self._template()
        doc["ingest"]["slots"][1]["core_area"] = {"raw": [1494, 2089, 442, 442]}
        assert mod._slot_geometry(self._write(tmp_path, doc)) is None

    # ---- the rectangle reaches BOTH initialize_floorplan arguments ---------
    def test_slot_rect_becomes_die_AND_core(self):
        """`ppl place_pins` puts pins on the DIE boundary and has no
        core-boundary mode, so `-core_area` alone leaves every pin on the saw
        street with the seal ring on top of it. Both arguments must move."""
        tcl = mod._floorplan_geometry_tcl(1936, 2531, 10, 1916, 2511,
                                          [442, 442, 1494, 2089])
        assert '-die_area "442 442 1494 2089"' in tcl
        assert '-core_area "442 442 1494 2089"' in tcl
        assert '"0 0 1936 2531"' not in tcl

    def test_without_a_slot_the_historical_geometry_is_unchanged(self):
        # FP-09: the upper right is a COORDINATE (origin + width), not the
        # width. 10+1916 = 1926 = 1936-10, and 10+2511 = 2521 = 2531-10.
        tcl = mod._floorplan_geometry_tcl(1936, 2531, 10, 1916, 2511, None)
        assert '-die_area "0 0 1936 2531"' in tcl
        assert '-core_area "10 10 1926 2521"' in tcl
        assert (1926, 2521) == (1936 - 10, 2531 - 10)

    def test_a_zero_pad_core_is_byte_identical_to_before_fp09(self):
        """THE CONTROL for FP-09: with no pad there is nothing to inset, so the
        corrected builder must emit exactly what it always did."""
        tcl = mod._floorplan_geometry_tcl(1000, 2000, 0, 1000, 2000, None)
        assert '-core_area "0 0 1000 2000"' in tcl

    def test_the_core_inset_is_symmetric_on_all_four_sides(self):
        """The defect in one sentence: a WIDTH printed as a COORDINATE inset the
        core by `core_pad` on the low sides and `2*core_pad` on the high ones —
        measured on spm as 381 um vs 762 um. Asserted here as a property, so it
        cannot come back under a different fixture."""
        for die_w, die_h, pad in ((3162, 3162, 381), (1936, 2531, 10),
                                  (5000, 4000, 250)):
            cw, ch = die_w - 2 * pad, die_h - 2 * pad
            line = mod._floorplan_geometry_tcl(
                die_w, die_h, pad, cw, ch, None).splitlines()[-1]
            llx, lly, urx, ury = [int(v) for v in line.split('"')[1].split()]
            assert (llx, lly) == (pad, pad), line
            assert (die_w - urx, die_h - ury) == (pad, pad), line

    # ---- the retry loop may not undo it -----------------------------------
    def test_resize_retry_reinstates_the_pinned_rect(self):
        """The PnR retry loop rewrites the floorplan line after every upsize /
        downsize / loosen. A slot die cannot be grown, so the rewrite must put
        the PINNED rectangle back, not the resized one."""
        base = mod._floorplan_geometry_tcl(1936, 2531, 10, 1916, 2511,
                                           [442, 442, 1494, 2089])
        text = base + "\n                      -site mysite\nmake_tracks\n"
        out = mod._rewrite_pnr_floorplan_die(text, 2200, 2900, 10, 2180, 2880,
                                             [442, 442, 1494, 2089])
        assert '-die_area "442 442 1494 2089"' in out
        assert "2200" not in out and "2900" not in out
        assert "-site mysite" in out          # the continuation survives
        # RED this discriminates: main's `_RE_PNR_FLOORPLAN_DIE` only matched a
        # die_area starting "0 0", so once the pinned rect is in the script the
        # substitution silently matches NOTHING and the rewrite is a no-op.
        # Rewriting twice proves the pattern still matches its own output.
        again = mod._rewrite_pnr_floorplan_die(out, 3000, 3000, 10, 2980, 2980,
                                               [442, 442, 1494, 2089])
        assert '-die_area "442 442 1494 2089"' in again
        assert "3000" not in again

    def test_resize_retry_without_a_slot_still_resizes(self):
        """The pinning must not disable the retry loop for everyone else."""
        text = mod._floorplan_geometry_tcl(1936, 2531, 10, 1916, 2511, None)
        out = mod._rewrite_pnr_floorplan_die(text, 2200, 2900, 10, 2180, 2880,
                                             None)
        # FP-09: a THIRD site pinning the width-as-coordinate form — the hunk
        # I was handed named two. 10+2180 = 2190 = 2200-10, 10+2880 = 2890 =
        # 2900-10. The property (the retry loop still resizes a no-slot die) is
        # unchanged; only the arithmetic it asserts was wrong.
        assert '-die_area "0 0 2200 2900"' in out
        assert '-core_area "10 10 2190 2890"' in out
        assert (2190, 2890) == (2200 - 10, 2900 - 10)


class TestSealRingBandKeepOut:
    """The fill engine's keep-out, and where its number comes from."""

    def test_the_number_is_read_out_of_the_PDK_not_chosen_by_us(self):
        """gf180mcu's own fill scripts carry
        `tp.var("space_to_scribe_line", 26 / $ly.dbu)` and then subtract that
        ring from the fill region. The regex must read exactly that."""
        m = mod._SCRIBE_KEEPOUT_RE.search(
            'tp.var("space_to_scribe_line", 26 / $ly.dbu)')
        assert m and float(m.group(1)) == 26.0
        # a fractional clearance, and a PDK that declares none
        assert float(mod._SCRIBE_KEEPOUT_RE.search(
            'space_to_scribe_line = 25.7').group(1)) == 25.7
        assert mod._SCRIBE_KEEPOUT_RE.search("no such variable here") is None

    def test_keepout_is_attached_to_the_derived_config(self, monkeypatch):
        pdk = mod.PdkConfig(
            name="p", liberty="/l.lib",
            tech_lef="/pdks/P/libs.ref/x/techlef/t.tlef",
            cell_lef="/c.lef", cell_gds="/c.gds", site="s",
            drc_deck="/d.drc", metal_prefix="Metal")
        monkeypatch.setattr(mod, "_docker_exec", lambda *a, **k: (
            0, 'tp.var("space_to_scribe_line", 26 / $ly.dbu)', ""))
        assert mod._pdk_scribe_keepout_um(pdk, "ctr") == 26.0
        # a PDK that ships no such declaration claims NO keep-out, rather than
        # inventing one — a wrong margin is worse than none (too small puts the
        # fill on the ring, too large makes the density target unreachable for
        # a reason no report explains).
        monkeypatch.setattr(mod, "_docker_exec", lambda *a, **k: (0, "", ""))
        assert mod._pdk_scribe_keepout_um(pdk, "ctr") is None


class TestSparseDieGuardIsNotApplicableToASlotPinnedCore:
    #: decaps first, then fills — the historical discovery order.
    _M = ["fillcap_64", "fillcap_16", "fill_64", "fill_8", "fill_1"]

    def test_sparse_slot_pinned_core_fills_with_SPACERS_ONLY(self):
        """The one arm whose behaviour changes.

        Below the sparse threshold the #684 tap prune has already removed the
        ties over this silicon. With the floorplan rectangle equal to the
        operator's CORE_AREA there is no empty fixed wrapper left INSIDE the die
        to flood -- the band the guard protects is outside it -- and the
        operator requires that same rectangle to meet implant / n-well /
        diffusion density rules. So the fill runs, and it runs DEVICE-FREE.
        """
        tcl = mod._build_sparse_die_aware_filler_tcl(self._M,
                                                     slot_pinned_core=True)
        below, _, above = tcl.partition("} else {")
        assert "SPARSE_DIE_FILL_NOT_APPLICABLE" in below
        assert "filler_placement {fill_64 fill_8 fill_1}" in below
        assert "fillcap" not in below, "a decap must not reach the sparse arm"
        # ...and the dense arm still gets the whole list, in the same file.
        assert "filler_placement {fillcap_64 fillcap_16 fill_64 fill_8 fill_1}" \
            in above

    def test_dense_arm_is_byte_identical_to_the_unpatched_flow(self):
        """A die at or above the threshold takes the else-arm, and that arm is
        the historical one: the same masters in the same order. This is what
        keeps the published reference die unchanged rather than merely
        untested."""
        tcl = mod._build_sparse_die_aware_filler_tcl(self._M,
                                                     slot_pinned_core=True)
        above = tcl.split("} else {", 1)[1]
        assert "filler_placement {" + " ".join(self._M) + "}" in above

    def test_without_a_slot_nothing_changes_at_all(self):
        """No slot -> the guard skips exactly as before, and the emitted Tcl is
        the unpatched text. (The byte-for-byte comparison against origin/main
        itself is in the run record; here we assert the shape.)"""
        tcl = mod._build_sparse_die_aware_filler_tcl(self._M,
                                                     slot_pinned_core=False)
        assert "SPARSE_DIE_FILL_SKIPPED" in tcl
        assert "SPARSE_DIE_FILL_NOT_APPLICABLE" not in tcl
        assert "filler_placement {" + " ".join(self._M) + "}" in tcl

    def test_a_pdk_with_no_spacer_family_is_not_silently_emptied(self):
        """If a PDK ships only decaps, the sparse arm has nothing device-free to
        place. It must fall back to the documented SKIP, not to an empty
        `filler_placement` that would look like it did something."""
        tcl = mod._build_sparse_die_aware_filler_tcl(["fillcap_64", "dcap_8"],
                                                     slot_pinned_core=True)
        assert "SPARSE_DIE_FILL_SKIPPED" in tcl
        assert "SPARSE_DIE_FILL_NOT_APPLICABLE" not in tcl

    def test_no_masters_still_skips_by_name(self):
        assert "FILLER_SKIPPED" in mod._build_sparse_die_aware_filler_tcl(
            [], slot_pinned_core=True)


class TestScribeKeepOutIsClaimedOnlyForAChipDie:
    """A scribe band belongs to the chip edge, not to an IP macro's outline.

    `space_to_scribe_line` is a clearance from the SAWING STREET. A macro is
    placed in the interior of a larger chip and has no sawing street at its own
    boundary, so subtracting the band there deletes fill area and protects
    nothing. MEASURED on the published gf180mcuD reference macro (240x240 um):
    ungated, the 26 um band removes 38.6% of the die and takes metal2 from
    density 0.3500 (target 0.35, reached) to 0.3499 (not reached).
    """

    def _cfg(self, monkeypatch, chip_die):
        calls = []

        class _Pdk:
            lefdef_layermap = "/x/lm.map"
            tech_lef = "/x/tech.lef"
            drc_deck = "/x/deck/main.rb"
            metal_prefix = "metal"

        monkeypatch.setattr(mod, "_docker_exec",
                            lambda *a, **k: (0, "nonempty", ""))
        monkeypatch.setattr(
            mod, "_pdk_scribe_keepout_um",
            lambda pdk, container: (calls.append(1), 26.0)[1])

        import types
        fake = types.ModuleType("metal_fill_config_gen")
        fake.build_metal_fill_config = (
            lambda *a, **k: {"layers": [{"name": "metal1"}]})
        monkeypatch.setitem(sys.modules, "metal_fill_config_gen", fake)

        return mod._derive_metal_fill_density(
            _Pdk(), "c", chip_die=chip_die), calls

    def test_an_IP_macro_gets_no_scribe_keepout(self, monkeypatch):
        cfg, calls = self._cfg(monkeypatch, chip_die=False)
        assert cfg is not None and cfg.get("layers")
        assert "keepout_edge_um" not in cfg
        # not merely absent from the config — never even asked for.
        assert calls == []

    def test_a_chip_die_does_get_it(self, monkeypatch):
        cfg, _ = self._cfg(monkeypatch, chip_die=True)
        assert cfg["keepout_edge_um"] == 26.0

    def test_the_default_is_the_safe_one(self):
        import inspect
        sig = inspect.signature(mod._derive_metal_fill_density)
        assert sig.parameters["chip_die"].default is False

    def test_behavioural_red_the_plain_two_arg_call_claims_no_band(
            self, monkeypatch):
        """A red that does NOT depend on the new keyword existing.

        Called exactly as the flow called it before this change --
        `_derive_metal_fill_density(pdk, container)` -- the returned config must
        carry no scribe band. Pre-gate this same two-argument call returns a
        config containing `keepout_edge_um: 26.0`, which is what put a 26 um
        band on the 240x240 um reference macro. So this assertion fails on the
        old code for a behavioural reason, not a missing-symbol one.
        """
        class _Pdk:
            lefdef_layermap = "/x/lm.map"
            tech_lef = "/x/tech.lef"
            drc_deck = "/x/deck/main.rb"
            metal_prefix = "metal"

        monkeypatch.setattr(mod, "_docker_exec",
                            lambda *a, **k: (0, "nonempty", ""))
        monkeypatch.setattr(mod, "_pdk_scribe_keepout_um",
                            lambda pdk, container: 26.0)
        import types
        fake = types.ModuleType("metal_fill_config_gen")
        fake.build_metal_fill_config = (
            lambda *a, **k: {"layers": [{"name": "metal1"}]})
        monkeypatch.setitem(sys.modules, "metal_fill_config_gen", fake)

        cfg = mod._derive_metal_fill_density(_Pdk(), "c")
        assert cfg is not None
        assert "keepout_edge_um" not in cfg
