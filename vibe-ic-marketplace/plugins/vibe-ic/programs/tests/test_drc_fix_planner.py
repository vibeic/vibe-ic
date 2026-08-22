"""Unit tests for `drc_fix_planner.py`."""
import importlib

from _shipped_version import shipped_plugin_version  # noqa: E402  (#800)
mod = importlib.import_module("drc_fix_planner")


class TestClassifyRule:
    def test_spacing(self):
        assert mod.classify_rule("met1.spacing") == "spacing"
        assert mod.classify_rule("M2.SP.1") == "spacing"

    def test_width(self):
        assert mod.classify_rule("met1.width") == "width"
        assert mod.classify_rule("min_width.5") == "width"

    def test_antenna(self):
        assert mod.classify_rule("ANTENNA.5") == "antenna"
        assert mod.classify_rule("ant.gate") == "antenna"

    def test_density(self):
        assert mod.classify_rule("met1.density") == "density"

    def test_unknown_default(self):
        assert mod.classify_rule("strange.rule") == "unknown"


class TestSeverityFor:
    def test_major(self):
        assert mod.severity_for(10000) == "MAJOR"
        assert mod.severity_for(50000) == "MAJOR"

    def test_significant(self):
        assert mod.severity_for(1000) == "SIGNIFICANT"
        assert mod.severity_for(9999) == "SIGNIFICANT"

    def test_notable(self):
        assert mod.severity_for(100) == "NOTABLE"
        assert mod.severity_for(999) == "NOTABLE"

    def test_minor(self):
        assert mod.severity_for(1) == "MINOR"
        assert mod.severity_for(99) == "MINOR"

    def test_none(self):
        assert mod.severity_for(0) == "NONE"


class TestBuildPlan:
    def test_empty(self):
        plan = mod.build_plan({})
        assert plan.total_violations == 0
        assert plan.ordered == []

    def test_orders_spacing_first(self):
        counts = {"met1.width": 5, "met1.spacing": 200,
                  "antenna.1": 10}
        plan = mod.build_plan(counts)
        # spacing comes first per FIX_ORDER
        assert plan.ordered[0].category == "spacing"
        # antenna comes last
        assert plan.ordered[-1].category == "antenna"

    def test_within_category_orders_by_count(self):
        counts = {"met1.spacing": 50, "met2.spacing": 100}
        plan = mod.build_plan(counts)
        assert plan.ordered[0].count == 100
        assert plan.ordered[1].count == 50

    def test_residual_estimate(self):
        counts = {"met1.spacing": 1000}
        plan = mod.build_plan(counts)
        assert plan.total_violations == 1000
        # ~20% residual
        assert 150 <= plan.expected_residual_after_plan <= 250

    def test_strategy_attached(self):
        counts = {"met1.spacing": 1}
        plan = mod.build_plan(counts)
        assert "jog" in plan.ordered[0].fix_strategy or "spacing" in plan.ordered[0].fix_strategy

    def test_unknown_rule_classifies_as_unknown(self):
        counts = {"weird.rule": 5}
        plan = mod.build_plan(counts)
        assert plan.ordered[0].category == "unknown"


class TestPlanMarkdown:
    def test_includes_total(self):
        plan = mod.build_plan({"m1.spacing": 100})
        md = mod.plan_to_markdown(plan)
        assert "Total violations: **100**" in md

    def test_has_table_headers(self):
        plan = mod.build_plan({"m1.spacing": 1})
        md = mod.plan_to_markdown(plan)
        assert "| # | Rule | Count" in md

    def test_attribution(self):
        plan = mod.build_plan({})
        md = mod.plan_to_markdown(plan)
        assert "drc_fix_planner.py" in md
        assert f"(v{shipped_plugin_version()})." in md

    def test_refuse_to_overclaim(self):
        plan = mod.build_plan({})
        md = mod.plan_to_markdown(plan)
        assert "Refuse to overclaim" in md
