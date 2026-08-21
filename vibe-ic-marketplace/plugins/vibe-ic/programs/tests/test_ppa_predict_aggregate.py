"""Unit tests for `ppa_predict_aggregate.py`."""
import importlib

from _shipped_version import shipped_plugin_version  # noqa: E402  (#800)
mod = importlib.import_module("ppa_predict_aggregate")


class TestAreaPower:
    def test_sky130_area(self):
        a = mod.estimate_area_um2(1000, "sky130A")
        assert a == 20000.0  # 1000 * 20

    def test_gf180_area_larger(self):
        # gf180mcuC uses larger per-cell area than sky130A
        assert mod.estimate_area_um2(1000, "gf180mcuC") > \
               mod.estimate_area_um2(1000, "sky130A")

    def test_unknown_pdk_defaults_to_sky130(self):
        a = mod.estimate_area_um2(100, "unknown")
        assert a == 100 * mod.AREA_PER_CELL_UM2["sky130A"]

    def test_zero_activity_zero_power(self):
        p = mod.estimate_power_uw(1000, "sky130A", activity_factor=0)
        assert p == 0

    def test_negative_activity_clamped(self):
        p = mod.estimate_power_uw(1000, "sky130A", activity_factor=-5)
        assert p == 0


class TestBuildEstimate:
    def test_pure_floor_when_no_declarations(self):
        e = mod.build_estimate(rtl_cell_count=100)
        assert e.estimate_floor is True

    def test_not_pure_floor_when_declared(self):
        e = mod.build_estimate(rtl_cell_count=100,
                                 declared_area_um2=1500)
        assert e.estimate_floor is False

    def test_overshoot_area_emits_note(self):
        # cell-count gives 2000 um^2; declared 1000 → 2x over (>20%)
        e = mod.build_estimate(rtl_cell_count=100,
                                 declared_area_um2=1000)
        assert any("exceeds declared area" in n for n in e.notes)

    def test_overshoot_power_emits_note(self):
        e = mod.build_estimate(rtl_cell_count=10000,
                                 declared_power_uw=100)
        assert any("Estimated power exceeds declared" in n for n in e.notes)

    def test_no_fmax_hint_emits_note(self):
        e = mod.build_estimate(rtl_cell_count=100)
        assert any("Fmax hint" in n for n in e.notes)


class TestMarkdownEmit:
    def test_includes_pdk(self):
        e = mod.build_estimate(rtl_cell_count=100, pdk="sky130A")
        md = mod.estimate_to_markdown(e)
        assert "sky130A" in md

    def test_refuses_to_overclaim_string(self):
        e = mod.build_estimate(rtl_cell_count=100)
        md = mod.estimate_to_markdown(e)
        assert "Refuse to overclaim" in md

    def test_attribution(self):
        e = mod.build_estimate(rtl_cell_count=100)
        d = e.as_dict()
        assert d["emitted_by"] == \
            f"ppa_predict_aggregate v{shipped_plugin_version()}"
