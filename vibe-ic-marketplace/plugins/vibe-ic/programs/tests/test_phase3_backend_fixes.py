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
        u, warn = mod._normalize_util("abc")
        assert u == 0.45
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
