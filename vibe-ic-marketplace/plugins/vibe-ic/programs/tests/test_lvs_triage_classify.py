"""Unit tests for `lvs_triage_classify.py`."""
import importlib

from _shipped_version import shipped_plugin_version  # noqa: E402  (#800)
mod = importlib.import_module("lvs_triage_classify")


class TestClassifyLine:
    def test_unmatched_net_short(self):
        assert mod.classify_line("Net abc/d short") == "unmatched_net"

    def test_unmatched_net_mismatch(self):
        assert mod.classify_line(
            "net foo mismatch in circuit") == "unmatched_net"

    def test_unmatched_instance(self):
        assert mod.classify_line(
            "Unmatched instance: xyz") == "unmatched_instance"
        assert mod.classify_line(
            "missing cell: my_inv") == "unmatched_instance"

    def test_device_param(self):
        assert mod.classify_line(
            "W = 1.0 vs 1.5 mismatch") == "device_param_mismatch"

    def test_property_mismatch(self):
        assert mod.classify_line(
            "label foo missing on net") == "property_mismatch"

    def test_unrelated_returns_none(self):
        assert mod.classify_line("Compare cells DONE") is None


class TestClassifyReport:
    def test_empty_report(self):
        rep = mod.classify_report("")
        assert rep.total == 0
        assert rep.top_3_root_causes == {}

    def test_counts(self):
        text = (
            "Net foo short\n"
            "Net bar mismatch\n"
            "Unmatched instance baz\n"
            "Property W differ\n"
        )
        rep = mod.classify_report(text)
        assert rep.counts["unmatched_net"] >= 2
        assert rep.counts["unmatched_instance"] == 1
        # Property line should match property_mismatch OR device_param
        assert rep.total >= 4

    def test_top_3_includes_root_cause_hint(self):
        text = "Net foo short\n"
        rep = mod.classify_report(text)
        assert "unmatched_net" in rep.top_3_root_causes
        assert "TOP-3" in rep.top_3_root_causes["unmatched_net"]


class TestMarkdownEmit:
    def test_table_present(self):
        rep = mod.classify_report("Net foo short\n")
        md = mod.report_to_markdown(rep)
        assert "## Counts by category" in md
        assert "| unmatched_net |" in md

    def test_attribution(self):
        rep = mod.classify_report("")
        md = mod.report_to_markdown(rep)
        assert "lvs_triage_classify.py" in md
        assert f"(v{shipped_plugin_version()})." in md

    def test_top_3_section_when_findings(self):
        rep = mod.classify_report("Net foo short")
        md = mod.report_to_markdown(rep)
        assert "## Top-3 root-cause hints" in md
        assert "**unmatched_net**" in md
