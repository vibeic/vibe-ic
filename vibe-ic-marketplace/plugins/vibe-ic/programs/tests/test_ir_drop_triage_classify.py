"""Unit tests for `ir_drop_triage_classify.py`."""
import importlib

from _shipped_version import shipped_plugin_version  # noqa: E402  (#800)
mod = importlib.import_module("ir_drop_triage_classify")


class TestClassifyCause:
    def test_weak_via_wins_first(self):
        # Even when other knobs suggest other causes, via_count < 4 dominates
        assert mod.classify_cause(
            strap_pitch_um=200, activity_density=0.9,
            metal_width_um=0.1, via_count=2) == "weak_via"

    def test_strap_sparse(self):
        assert mod.classify_cause(
            strap_pitch_um=150, activity_density=0.1,
            metal_width_um=1.0, via_count=10) == "strap_sparse"

    def test_switching_cluster(self):
        assert mod.classify_cause(
            strap_pitch_um=50, activity_density=0.8,
            metal_width_um=1.0, via_count=10) == "switching_cluster"

    def test_narrow_metal(self):
        assert mod.classify_cause(
            strap_pitch_um=50, activity_density=0.1,
            metal_width_um=0.3, via_count=10) == "narrow_metal"

    def test_default_strap_sparse(self):
        # Nothing crosses any threshold
        assert mod.classify_cause(
            strap_pitch_um=50, activity_density=0.1,
            metal_width_um=1.0, via_count=10) == "strap_sparse"


class TestCauseToFix:
    def test_one_to_one(self):
        for cause in mod.CAUSES:
            assert cause in mod.CAUSE_TO_FIX
            assert mod.CAUSE_TO_FIX[cause] in mod.FIX_DESC

    def test_strap_sparse_maps_to_add_straps(self):
        assert mod.CAUSE_TO_FIX["strap_sparse"] == "add_straps"


class TestBuildTriage:
    def test_counts_each_cause(self):
        t = mod.build_triage([
            {"cell": "a", "ir_uv": 50, "via_count": 2},   # weak_via
            {"cell": "b", "ir_uv": 10, "strap_pitch_um": 200},  # strap_sparse
            {"cell": "c", "ir_uv": 20, "activity_density": 0.9},  # switching
        ])
        assert t["cause_count"]["weak_via"] == 1
        assert t["cause_count"]["strap_sparse"] == 1
        assert t["cause_count"]["switching_cluster"] == 1

    def test_worst_ir(self):
        t = mod.build_triage([
            {"cell": "a", "ir_uv": 5},
            {"cell": "b", "ir_uv": 100},
        ])
        assert t["worst_ir_uv"] == 100

    def test_attribution(self):
        t = mod.build_triage([])
        assert t["emitted_by"] == \
            f"ir_drop_triage_classify v{shipped_plugin_version()}"


class TestMarkdownEmit:
    def test_cause_table(self):
        t = mod.build_triage([{"cell": "a", "ir_uv": 5, "via_count": 2}])
        md = mod.triage_to_markdown(t)
        assert "## Causes" in md
        assert "weak_via" in md
        assert "add_via_array" in md
