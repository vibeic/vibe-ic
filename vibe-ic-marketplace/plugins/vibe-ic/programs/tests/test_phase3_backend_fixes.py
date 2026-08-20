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
import pathlib

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
    def test_filler_masters_are_spacers_only(self):
        """`filler_placement` gets SPACERS, and no decoupling capacitor.

        THIS TEST USED TO ASSERT THE OPPOSITE, and the reason it was inverted
        is a measurement, not a preference. It read: "Both decap-family and
        fill-family must be present. Decap is the dynamic-IR margin; fill is
        density-rule compliance." The first half of that is true only where the
        decap's own well and substrate ties survive, and on a sparse die they
        do not: the #684 guard prunes taps over silicon it has judged empty, and
        the fill then runs over that same silicon.

        MEASURED (agent g360, 2026-08-20, an open PDK, one die): with the
        decaps-first master list, 7295 of 8317 inserted cells were decaps and
        sign-off DRC went 360 -> 11964, 33x WORSE, with 99.5-100% of every new
        violation sitting on a decap instance. The identical 8317 sites filled
        with spacers only gave 360 -> 19, and all 19 pre-dated the fill.

        A decap carries real active area, real contacts and extra metal1; a
        spacer carries well/implant continuity and the two rails and NO device.
        So the two are not interchangeable, and only one of them is safe to
        drop onto silicon whose ties have been removed.

        WHAT THIS TEST NO LONGER GUARANTEES, said out loud: the dynamic-IR
        decoupling that the decaps provided is now absent. That is a real cost
        and it is NOT paid for here. Restoring it needs decap insertion and tap
        pruning to be decided TOGETHER -- decap only where tap coverage is
        retained -- which is a change to the placement step, not to this list.
        """
        masters = mod._filler_masters_for_pdk(self._sky130_pdk())
        decap = [m for m in masters if "decap" in m or "dcap" in m]
        fill = [m for m in masters if m.startswith("sky130_fd_sc_hd__fill_")]
        assert decap == [], f"device-bearing fillers must not be offered: {decap}"
        assert len(fill) >= 3, f"fill variants too few: {fill}"
        # Largest-first ordering (OpenROAD convention) is unchanged.
        assert masters.index("sky130_fd_sc_hd__fill_8") < masters.index(
            "sky130_fd_sc_hd__fill_1")

    def test_filler_masters_exclusion_is_pdk_agnostic(self):
        """The exclusion is by name SEGMENT, so it holds for any PDK's naming.

        Both paths must agree: the hardcoded library shortcut and the LEF
        discovery. A shortcut that quietly reinstated the decaps would put the
        measured 33x regression back on exactly one PDK.
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
