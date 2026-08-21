"""Unit tests for `sta_triage_classify.py`."""
import importlib

from _shipped_version import shipped_plugin_version  # noqa: E402  (#800)
mod = importlib.import_module("sta_triage_classify")


class TestClassifyEndpoint:
    def test_hold_violation(self):
        assert mod.classify_endpoint(50, 50, 1, is_hold=True) == "hold_violation"

    def test_skew_dominant(self):
        assert mod.classify_endpoint(50, 50, 10,
                                       skew_dominant=True) == "clock_skew_limited"

    def test_deep_logic(self):
        assert mod.classify_endpoint(30, 30, 50) == "logic_depth_limited"

    def test_net_dominant(self):
        assert mod.classify_endpoint(20, 70, 10) == "net_delay_limited"

    def test_cell_dominant(self):
        assert mod.classify_endpoint(70, 20, 10) == "cell_delay_limited"

    def test_default_picks_larger(self):
        # neither hits the 60% threshold, neither is deep — pick bigger
        assert mod.classify_endpoint(30, 40, 10) == "net_delay_limited"
        assert mod.classify_endpoint(40, 30, 10) == "cell_delay_limited"


class TestMakeFinding:
    def test_attaches_fix_strategy(self):
        f = mod.make_finding("rip_reg/D", -0.5, cell_delay_pct=80)
        assert f.category == "cell_delay_limited"
        assert "upsize" in f.fix_strategy.lower()

    def test_negative_slack_short_depth_is_hold(self):
        f = mod.make_finding("d/Q", -0.1, logic_depth=1, cell_delay_pct=30,
                              net_delay_pct=30)
        assert f.category == "hold_violation"


class TestParseStaSummary:
    def test_basic_summary(self):
        text = "report_wns\nwns -1.25\nreport_tns\ntns -42.0\n"
        wns, tns = mod.parse_sta_summary(text)
        assert wns == -1.25
        assert tns == -42.0

    def test_no_match_returns_none(self):
        wns, tns = mod.parse_sta_summary("nothing here")
        assert wns is None and tns is None


class TestBuildReport:
    def test_counts(self):
        ep = [mod.make_finding("a", -1, cell_delay_pct=80),
              mod.make_finding("b", -1, net_delay_pct=80),
              mod.make_finding("c", -1, net_delay_pct=80)]
        rep = mod.build_report(ep, wns=-1.0, tns=-3.0)
        assert rep.counts_by_category["net_delay_limited"] == 2
        assert rep.counts_by_category["cell_delay_limited"] == 1
        assert rep.total_violations == 3


class TestMarkdownEmit:
    def test_includes_wns(self):
        ep = [mod.make_finding("a", -1, cell_delay_pct=80)]
        rep = mod.build_report(ep, wns=-1.0, tns=-1.0)
        md = mod.report_to_markdown(rep)
        assert "WNS: -1.0" in md

    def test_attribution(self):
        rep = mod.build_report([], wns=0, tns=0)
        md = mod.report_to_markdown(rep)
        assert "sta_triage_classify.py" in md
        assert f"(v{shipped_plugin_version()})." in md
