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


class TestAbsentReportIsDisclosedNotACrash:
    """WIRED ADVISORY ON FLOW STEP 31 (2026-08-25).

    `reports/phase3/lvs.rpt` is Step 31's OWN required_output, and whether it
    exists is already decided there by the blocking `lvs_report_check` and
    `lvs_signoff_guard` slots. A triage classifier that answers "the report you
    asked me to categorise is not there" with a `FileNotFoundError` traceback
    spends a second gate's FINDING channel on the first gate's question. rc 2
    is the disclosed-skip tier both consumer channels read.
    """

    def _main(self, argv, monkeypatch):
        import sys
        monkeypatch.setattr(sys, "argv", ["lvs_triage_classify.py"] + argv)
        return mod._cli()

    def test_absent_report_is_rc2_and_says_so(self, tmp_path, monkeypatch,
                                              capsys):
        missing = tmp_path / "lvs.rpt"
        assert self._main(["--report", str(missing)], monkeypatch) == 2
        cap = capsys.readouterr()
        # `_vacuous_exit.announce_vacuous` writes the machine sentinel to
        # stderr and `verdict_line` the human verdict to stdout — both
        # channels, which is the #528 repair this reuses rather than re-does.
        assert "VACUOUS_PASS" in cap.err      # the machine sentinel
        assert "[VACUOUS]" in cap.out         # the verdict line
        assert "NOT a pass over the design" in cap.out

    def test_present_report_is_rc0_and_classifies(self, tmp_path, monkeypatch,
                                                  capsys):
        """SAME denominator — a report either way; only the ANSWER differs."""
        rpt = tmp_path / "lvs.rpt"
        rpt.write_text("Net vdd unmatched\nCircuits match uniquely.\n")
        assert self._main(["--report", str(rpt)], monkeypatch) == 0
        out = capsys.readouterr().out
        assert "# LVS triage" in out
        assert "| unmatched_net | 1 |" in out
