"""Unit tests for `rtl_review_aggregate.py`.

Pin the scoring rubric + category taxonomy that today lives only in
`skills/rtl-review/SKILL.md` prose. The doctrine: the rule is in the
tool, not the prompt.
"""
import importlib
import json

import pytest

from _shipped_version import shipped_plugin_version  # noqa: E402  (#800)
mod = importlib.import_module("rtl_review_aggregate")


def _f(rule_id, severity, category="synthesis_hazards", source="test",
       file="dut.v", line=10, message="msg"):
    return mod.Finding(
        category=category, severity=severity, rule_id=rule_id,
        file=file, line=line, message=message, source=source,
    )


# ---------------------------------------------------------------------------
# Category taxonomy
# ---------------------------------------------------------------------------
class TestCategoryTaxonomy:
    def test_six_categories(self):
        assert len(mod.CATEGORY_NAMES) == 6

    def test_synthesis_hazards_present(self):
        assert "synthesis_hazards" in mod.CATEGORY_NAMES

    def test_port_fidelity_present(self):
        assert "port_fidelity" in mod.CATEGORY_NAMES

    def test_known_hygiene_rules_mapped(self):
        # Every hygiene rule must map into one of the 6 categories.
        for rule, cat in mod.HYGIENE_RULE_CATEGORY.items():
            assert cat in mod.CATEGORY_NAMES, (
                f"{rule} maps to unknown category {cat!r}")

    def test_latch_is_synth_hazard(self):
        assert mod.HYGIENE_RULE_CATEGORY["latch_inferred"] == "synthesis_hazards"

    def test_flop_no_reset_is_reset_hygiene(self):
        assert mod.HYGIENE_RULE_CATEGORY["flop_no_reset"] == "reset_clock_hygiene"

    def test_port_width_is_port_fidelity(self):
        assert mod.HYGIENE_RULE_CATEGORY["port_width_mismatch"] == "port_fidelity"


# ---------------------------------------------------------------------------
# Scoring rubric — pin every boundary
# ---------------------------------------------------------------------------
class TestComputeScore:
    def test_clean_returns_10(self):
        assert mod.compute_score(0, 0, 0) == 10

    def test_info_only_in_8_9_band(self):
        assert mod.compute_score(0, 0, 1) == 9
        assert mod.compute_score(0, 0, 3) == 9
        assert mod.compute_score(0, 0, 5) == 9
        assert mod.compute_score(0, 0, 10) == 8

    def test_one_warning_is_7(self):
        assert mod.compute_score(0, 1, 0) == 7

    def test_two_to_four_warns_is_6(self):
        assert mod.compute_score(0, 2, 0) == 6
        assert mod.compute_score(0, 4, 0) == 6

    def test_one_error_is_5(self):
        assert mod.compute_score(1, 0, 0) == 5

    def test_one_error_with_warns_still_5(self):
        assert mod.compute_score(1, 3, 0) == 5

    def test_multiple_errors_is_3_or_2(self):
        assert mod.compute_score(2, 0, 0) == 3
        assert mod.compute_score(3, 0, 0) == 3
        assert mod.compute_score(4, 0, 0) == 2
        assert mod.compute_score(10, 0, 0) == 2

    def test_not_synthesizable_is_0(self):
        # Honesty gate: not synthesizable → 0 regardless of count
        assert mod.compute_score(0, 0, 0, is_synthesizable=False) == 0
        assert mod.compute_score(99, 99, 99, is_synthesizable=False) == 0

    def test_many_warns_no_errors_is_4(self):
        assert mod.compute_score(0, 5, 0) == 4


class TestScoreToVerdict:
    def test_pass_band(self):
        assert mod.score_to_verdict(10) == "PASS"
        assert mod.score_to_verdict(9) == "PASS"
        assert mod.score_to_verdict(8) == "PASS"

    def test_warn_band(self):
        assert mod.score_to_verdict(7) == "WARN"
        assert mod.score_to_verdict(6) == "WARN"

    def test_fail_band(self):
        assert mod.score_to_verdict(5) == "FAIL"
        assert mod.score_to_verdict(0) == "FAIL"

    def test_no_overclaim(self):
        # Honesty gate: the function is monotone — higher count of errors
        # never produces a higher verdict.
        last = "PASS"
        for s in range(10, -1, -1):
            v = mod.score_to_verdict(s)
            assert v in ("PASS", "WARN", "FAIL")


class TestSeverityBand:
    def test_known_bands(self):
        assert "production-ready" in mod.severity_band(10)
        assert "clean" in mod.severity_band(9)
        assert "synthesizable" in mod.severity_band(0)


# ---------------------------------------------------------------------------
# Aggregator behavior
# ---------------------------------------------------------------------------
class TestAggregator:
    def test_clean_findings_score_10(self):
        rep = mod.aggregate([], rtl_dir="/x")
        assert rep.score == 10
        assert rep.verdict == "PASS"

    def test_one_error_routed_to_category(self):
        rep = mod.aggregate(
            [_f("latch_inferred", "ERROR", "synthesis_hazards")])
        assert rep.per_category["synthesis_hazards"].errors == 1
        assert rep.score == 5

    def test_unknown_category_routes_to_style(self):
        rep = mod.aggregate(
            [_f("?", "WARN", "_made_up_")])
        assert rep.per_category["style_readability"].warns == 1

    def test_per_category_total_matches_top_level(self):
        rep = mod.aggregate([
            _f("a", "ERROR", "synthesis_hazards"),
            _f("b", "WARN", "reset_clock_hygiene"),
            _f("c", "WARN", "port_fidelity"),
            _f("d", "INFO", "style_readability"),
        ])
        assert rep.total_errors == 1
        assert rep.total_warns == 2
        assert rep.total_infos == 1

    def test_emitted_by_carries_the_shipped_version(self):
        rep = mod.aggregate([])
        d = rep.as_dict()
        assert d["emitted_by"] == \
            f"rtl_review_aggregate v{shipped_plugin_version()}"

    def test_report_as_dict_round_trip(self):
        rep = mod.aggregate([_f("latch_inferred", "ERROR")])
        d = rep.as_dict()
        # Re-serialize and ensure stable
        assert json.dumps(d)


# ---------------------------------------------------------------------------
# Markdown emit shape
# ---------------------------------------------------------------------------
class TestReportToMarkdown:
    def test_includes_score_and_verdict(self):
        rep = mod.aggregate([_f("latch_inferred", "ERROR")])
        md = mod.report_to_markdown(rep)
        assert "Score" in md and "5/10" in md
        assert "FAIL" in md

    def test_clean_report_says_proceed(self):
        rep = mod.aggregate([])
        md = mod.report_to_markdown(rep)
        assert "Proceed to synthesis" in md

    def test_failed_report_says_fix(self):
        rep = mod.aggregate([_f("latch_inferred", "ERROR")])
        md = mod.report_to_markdown(rep)
        assert "Fix errors" in md

    def test_per_category_table_present(self):
        rep = mod.aggregate([_f("latch_inferred", "ERROR")])
        md = mod.report_to_markdown(rep)
        assert "## Per-category" in md
        assert "synthesis_hazards" in md

    def test_attributes_to_program_not_llm(self):
        rep = mod.aggregate([])
        md = mod.report_to_markdown(rep)
        # The doctrine line: refuse-to-overclaim
        assert "refuse to claim a higher score" in md
        assert "rtl_review_aggregate.py" in md

    def test_finding_appears_in_correct_severity_section(self):
        rep = mod.aggregate([
            _f("latch_inferred", "ERROR"),
            _f("magic_number", "WARN", "style_readability"),
            _f("verbose_name", "INFO", "style_readability"),
        ])
        md = mod.report_to_markdown(rep)
        idx_err = md.index("### Errors")
        idx_warn = md.index("### Warnings")
        idx_info = md.index("### Info")
        latch_pos = md.index("latch_inferred")
        magic_pos = md.index("magic_number")
        verbose_pos = md.index("verbose_name")
        assert idx_err < latch_pos < idx_warn
        assert idx_warn < magic_pos < idx_info
        assert idx_info < verbose_pos


# ---------------------------------------------------------------------------
# Honesty gate — Pattern-B doctrine compliance
# ---------------------------------------------------------------------------
class TestDoctrineCompliance:
    def test_aggregator_is_pure_no_io(self):
        # `aggregate()` itself must be pure — given a Finding list, it
        # MUST NOT touch the filesystem. This is the property that makes
        # the rubric testable.
        rep = mod.aggregate([_f("latch_inferred", "ERROR")])
        assert rep.score == 5

    def test_severity_counts_are_monotone(self):
        # Adding another error never raises the score.
        s1 = mod.aggregate([_f("a", "ERROR")]).score
        s2 = mod.aggregate([_f("a", "ERROR"), _f("b", "ERROR")]).score
        assert s2 <= s1

    def test_scoring_is_deterministic(self):
        for _ in range(5):
            assert mod.compute_score(0, 0, 0) == 10
            assert mod.compute_score(1, 0, 0) == 5
            assert mod.compute_score(0, 1, 0) == 7

    def test_categories_round_trip_through_dict(self):
        rep = mod.aggregate([_f("latch_inferred", "ERROR")])
        d = rep.as_dict()
        assert set(d["per_category"].keys()) == set(mod.CATEGORY_NAMES)
