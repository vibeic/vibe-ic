"""Unit tests for `hold_fix_planner.py`."""
import importlib

from _shipped_version import shipped_plugin_version  # noqa: E402  (#800)
mod = importlib.import_module("hold_fix_planner")


class TestPickStrategy:
    def test_small_violation_single_buffer(self):
        assert mod.pick_strategy(-30) == "single_buffer"

    def test_boundary_at_minus_50(self):
        # boundary: > -50 → single; -50 itself → chain
        assert mod.pick_strategy(-49) == "single_buffer"
        assert mod.pick_strategy(-50) == "buffer_chain"

    def test_mid_chain(self):
        assert mod.pick_strategy(-100) == "buffer_chain"
        assert mod.pick_strategy(-200) == "buffer_chain"

    def test_below_minus_200(self):
        assert mod.pick_strategy(-201) == "delay_cell_or_restructure"
        assert mod.pick_strategy(-1000) == "delay_cell_or_restructure"

    def test_positive_still_returns_single(self):
        # planner caller filters >=0 out; but the function itself returns
        # a valid label even for positive (defensive)
        assert mod.pick_strategy(0) == "single_buffer"


class TestBuildPlan:
    def test_skips_positive_slack(self):
        plan = mod.build_plan([
            {"endpoint": "a", "slack_ps": 100},  # not a violation
            {"endpoint": "b", "slack_ps": -75},
        ])
        assert plan["endpoint_count"] == 1
        assert plan["strategy_counts"]["buffer_chain"] == 1

    def test_aggregates_whs_ths(self):
        plan = mod.build_plan([
            {"endpoint": "a", "slack_ps": -30},
            {"endpoint": "b", "slack_ps": -250},
        ])
        assert plan["WHS_ps"] == -250
        assert plan["THS_ps"] == -280

    def test_attribution(self):
        plan = mod.build_plan([])
        assert plan["emitted_by"] == \
            f"hold_fix_planner v{shipped_plugin_version()}"


class TestMarkdownEmit:
    def test_strategy_table_present_when_violations(self):
        plan = mod.build_plan([{"endpoint": "a", "slack_ps": -75}])
        md = mod.plan_to_markdown(plan)
        assert "## Strategy distribution" in md
        assert "buffer_chain" in md

    def test_clean_design_no_table(self):
        plan = mod.build_plan([])
        md = mod.plan_to_markdown(plan)
        assert "Violating endpoints: **0**" in md
