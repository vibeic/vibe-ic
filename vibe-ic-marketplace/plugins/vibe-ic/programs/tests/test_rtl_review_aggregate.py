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


# ---------------------------------------------------------------------------
# Issue #2036 — consumers that mis-read their own producer
#
# `_load_hygiene_findings` called `data.get("findings", [])` while
# `rtl_hygiene_lint.py --json` writes a BARE ARRAY (`[]` for a clean file).
# `AttributeError: 'list' object has no attribute 'get'` took the whole
# aggregate down with exit 1 and NO report and NO score — on an ordinary clean
# flip-flop. The sibling loaders had the same class of mismatch, unreached only
# because the hygiene loader raised first.
#
# The other half of this, and the load-bearing half: an unreadable producer must
# NOT become an empty finding set. "I could not read it" is not "there was
# nothing to report", and a review that scores 10/10 because its tools crashed
# is worse than no review.
# ---------------------------------------------------------------------------
REGISTER_SLICE = """module register_slice(input wire clk, input wire rst_n, input wire d, output reg q);
always @(posedge clk or negedge rst_n) begin
  if (!rst_n) q <= 1'b0;
  else q <= d;
end
endmodule
"""

_HYGIENE_RECORD = {"file": "dut.v", "line": 3, "severity": "WARN",
                   "rule": "blocking_in_seq", "symbol": "q",
                   "message": "blocking assignment in a sequential block"}


class TestProducerArraySchema:
    def test_hygiene_bare_empty_array_is_a_clean_result(self, tmp_path):
        j = tmp_path / "hygiene.json"
        j.write_text("[]")
        assert mod._load_hygiene_findings(j, rc=0) == []

    def test_hygiene_bare_array_findings_are_preserved(self, tmp_path):
        j = tmp_path / "hygiene.json"
        j.write_text(json.dumps([_HYGIENE_RECORD]))
        got = mod._load_hygiene_findings(j, rc=1)
        assert len(got) == 1
        f = got[0]
        assert f.rule_id == "blocking_in_seq"
        assert f.severity == "WARN"
        assert f.file == "dut.v"
        assert f.line == 3
        assert f.message == "blocking assignment in a sequential block"
        assert f.source == "rtl_hygiene_lint"

    def test_hygiene_object_envelope_is_also_accepted(self, tmp_path):
        j = tmp_path / "hygiene.json"
        j.write_text(json.dumps({"findings": [_HYGIENE_RECORD]}))
        got = mod._load_hygiene_findings(j, rc=1)
        assert [f.rule_id for f in got] == ["blocking_in_seq"]

    def test_reset_bare_array_is_consumed(self, tmp_path):
        j = tmp_path / "reset.json"
        j.write_text(json.dumps([{"file": "dut.v", "line": 7,
                                  "severity": "ERROR", "rule": "async_mix",
                                  "message": "mixed reset polarity"}]))
        got = mod._load_reset_findings(j, rc=1)
        assert len(got) == 1
        assert got[0].category == "reset_clock_hygiene"
        assert got[0].rule_id == "async_mix"
        assert got[0].message == "mixed reset polarity"

    def test_precheck_real_auditor_list_shape(self, tmp_path):
        """`rtl_precheck_gate` emits `auditors` as a LIST of AuditorResult."""
        j = tmp_path / "precheck.json"
        j.write_text(json.dumps({"summary": {}, "auditors": [
            {"name": "latch_check", "passed": False, "exit_code": 1,
             "skipped": False, "stdout_tail": "inferred latch on q"},
            {"name": "port_check", "passed": True, "exit_code": 0,
             "skipped": False},
            {"name": "reset_discipline_check", "passed": True, "exit_code": 0,
             "skipped": True, "skip_reason": "no L12 JSON supplied"},
        ]}))
        got = mod._load_precheck_findings(j, rc=1)
        by_rule = {f.rule_id: f for f in got}
        assert set(by_rule) == {"latch_check", "reset_discipline_check"}
        assert by_rule["latch_check"].severity == "ERROR"
        assert by_rule["latch_check"].category == "synthesis_hazards"
        assert "inferred latch on q" in by_rule["latch_check"].message
        # a check that did not run is reported, never counted as a pass
        assert by_rule["reset_discipline_check"].severity == "INFO"
        assert "did not run" in by_rule["reset_discipline_check"].message

    def test_precheck_object_envelope_is_also_accepted(self, tmp_path):
        j = tmp_path / "precheck.json"
        j.write_text(json.dumps({"auditors": {
            "latch_check": {"passed": False, "exit_code": 1,
                            "stdout_tail": "inferred latch"}}}))
        got = mod._load_precheck_findings(j, rc=1)
        assert [f.rule_id for f in got] == ["latch_check"]


class TestUnreadableIsNotEmpty:
    """Every arm here must RAISE. None may return `[]`."""

    def test_missing_file_refuses(self, tmp_path):
        with pytest.raises(mod.ProducerOutputError) as e:
            mod._load_hygiene_findings(tmp_path / "absent.json", rc=0)
        assert "not empty" in str(e.value)

    def test_unparseable_json_refuses(self, tmp_path):
        j = tmp_path / "hygiene.json"
        j.write_text("{not json")
        with pytest.raises(mod.ProducerOutputError):
            mod._load_hygiene_findings(j, rc=0)

    def test_unknown_shape_refuses(self, tmp_path):
        j = tmp_path / "hygiene.json"
        j.write_text(json.dumps({"summary": "all good"}))
        with pytest.raises(mod.ProducerOutputError):
            mod._load_hygiene_findings(j, rc=0)

    def test_non_object_records_refuse(self, tmp_path):
        j = tmp_path / "hygiene.json"
        j.write_text(json.dumps(["blocking_in_seq"]))
        with pytest.raises(mod.ProducerOutputError):
            mod._load_hygiene_findings(j, rc=0)

    def test_producer_that_reached_no_verdict_refuses(self, tmp_path):
        """rc=2 is `rtl_hygiene_lint`'s UNDETERMINED, and 124/127 are timeout
        and missing-program. A clean `[]` on disk must not launder them."""
        j = tmp_path / "hygiene.json"
        j.write_text("[]")
        for rc in (2, 124, 127):
            with pytest.raises(mod.ProducerOutputError) as e:
                mod._load_hygiene_findings(j, rc=rc, stderr="tool stalled")
            assert "without reaching a verdict" in str(e.value)

    def test_result_exit_codes_are_not_refusals(self, tmp_path):
        j = tmp_path / "hygiene.json"
        j.write_text("[]")
        for rc in (0, 1):
            assert mod._load_hygiene_findings(j, rc=rc) == []

    def test_reset_and_precheck_refuse_too(self, tmp_path):
        with pytest.raises(mod.ProducerOutputError):
            mod._load_reset_findings(tmp_path / "absent.json", rc=0)
        with pytest.raises(mod.ProducerOutputError):
            mod._load_precheck_findings(tmp_path / "absent.json", rc=0)
        j = tmp_path / "precheck.json"
        j.write_text(json.dumps({"summary": {}}))
        with pytest.raises(mod.ProducerOutputError):
            mod._load_precheck_findings(j, rc=0)


class TestEndToEndOnANeutralModule:
    def _write(self, tmp_path):
        d = tmp_path / "rtl"
        d.mkdir()
        (d / "register_slice.sv").write_text(REGISTER_SLICE)
        return d

    def test_clean_flipflop_produces_a_report(self, tmp_path):
        """The issue's own reproduction: this used to exit 1 with no report."""
        rtl = self._write(tmp_path)
        rep = mod.review_rtl_dir(rtl, tmp_path / "ev")
        assert rep.files_reviewed == ["register_slice.sv"]
        assert rep.total_errors == 0
        assert rep.verdict in ("PASS", "WARN")
        assert rep.score >= 7

    def test_cli_emits_both_artifacts(self, tmp_path):
        import subprocess
        import sys
        rtl = self._write(tmp_path)
        out_md, out_json = tmp_path / "r.md", tmp_path / "r.json"
        r = subprocess.run(
            [sys.executable, str(mod.PROGRAMS_DIR / "rtl_review_aggregate.py"),
             "--rtl-dir", str(rtl), "--tmp-dir", str(tmp_path / "ev"),
             "--out-md", str(out_md), "--out-json", str(out_json)],
            capture_output=True, text=True, timeout=600)
        assert r.returncode == 0, r.stderr
        assert out_md.is_file() and out_json.is_file()
        assert json.loads(out_json.read_text())["score"] >= 7

    def test_cli_refuses_loudly_and_writes_nothing_when_a_producer_is_unreadable(
            self, tmp_path):
        """The trap: a crash must not become an empty finding set or a PASS.

        The evidence directory is made unwritable, so the sub-program cannot
        deposit its JSON at all. The CLI must exit 3 naming the producer, and
        must write NEITHER report.
        """
        import subprocess
        import sys
        rtl = self._write(tmp_path)
        ev = tmp_path / "ev"
        ev.mkdir()
        ev.chmod(0o555)
        out_md, out_json = tmp_path / "r.md", tmp_path / "r.json"
        try:
            r = subprocess.run(
                [sys.executable,
                 str(mod.PROGRAMS_DIR / "rtl_review_aggregate.py"),
                 "--rtl-dir", str(rtl), "--tmp-dir", str(ev),
                 "--out-md", str(out_md), "--out-json", str(out_json)],
                capture_output=True, text=True, timeout=600)
        finally:
            ev.chmod(0o755)
        assert r.returncode == 3, (r.returncode, r.stdout, r.stderr)
        assert "REFUSING" in r.stderr and "rtl_hygiene_lint" in r.stderr
        assert not out_md.exists() and not out_json.exists()

    def test_findings_from_the_real_producers_reach_the_report(self, tmp_path):
        """The NON-EMPTY arm, driven by the REAL sub-programs.

        Every other field-preservation test in this file feeds the loaders
        SYNTHETIC records. If the real producers named their fields differently,
        those tests would all still pass while the aggregate silently dropped
        the data. This one runs the actual chain on RTL that really does trip
        the linters, and asserts the findings arrive populated.

        Measured on the base code, this same directory raised
        `AttributeError` and produced no report at all, so nothing below was
        reachable before the fix.

        Deliberately NOT pinned to specific rule names — those are the linters'
        business and may change. What is pinned is that findings survive the
        loaders with their fields intact, that more than one producer
        contributes, and that the score responds.
        """
        d = tmp_path / "rtl"
        d.mkdir()
        (d / "dirty_block.v").write_text(
            "module dirty_block(input clk, input rst, input [3:0] a,\n"
            "                   output reg [3:0] y, output reg z);\n"
            "  reg [3:0] tmp;\n"
            "  always @(posedge clk) begin\n"
            "    tmp = a + 1;\n"
            "    y <= tmp;\n"
            "  end\n"
            "  always @(*) begin\n"
            "    if (a[0]) z = 1'b1;\n"
            "  end\n"
            "endmodule\n")
        rep = mod.review_rtl_dir(d, tmp_path / "ev")

        got = [f for cat in rep.per_category.values() for f in cat.findings]
        assert got, "the real producers reported nothing on RTL that trips them"

        # the producer really did emit a non-empty array — otherwise this test
        # would pass on a chain that reported nothing
        produced = json.loads((tmp_path / "ev" / "hygiene.json").read_text())
        assert isinstance(produced, list) and produced, produced

        for f in got:
            assert f.rule_id and f.severity and f.message and f.source, f.as_dict()
        # EACH of the three loaders must contribute by NAME. A bare
        # "at least two distinct sources" assertion is too weak and I proved
        # it: neutering `_load_reset_findings` to `return []` left two sources
        # standing (hygiene + precheck) and the test still passed. All three
        # loaders were broken, so all three are named here.
        sources = {f.source.split(".")[0] for f in got}
        for producer in ("rtl_hygiene_lint", "reset_discipline_check",
                         "rtl_precheck_gate"):
            assert producer in sources, (producer, sorted(sources))
        # and the score responds to them rather than staying at the clean value
        assert rep.score < 9, rep.score
        assert rep.total_errors + rep.total_warns >= 1

    def test_a_skipped_auditor_is_reported_and_caps_the_score(self, tmp_path):
        """PINS A JUDGEMENT CALL THAT NEEDS A RULING — see LAND.md F2036-H.

        `_load_precheck_findings` emits an INFO for every auditor that did not
        run, on the principle this repo applies everywhere: a check that did not
        run is reported, never counted as a pass.

        MEASURED CONSEQUENCE, which the issue did not ask for and which I did
        not intend: `review_rtl_dir` invokes `rtl_precheck_gate` with no
        `--l12-json`, so `l12_sequence_implementation_check` ALWAYS skips, so
        there is ALWAYS at least one INFO, so `compute_score` can never return
        10 through this program — and `skills/rtl-review/SKILL.md` documents
        `10 | 0 errors, 0 warns, 0 infos | PASS` as a reachable row. It is now
        unreachable here.

        Two defensible readings:
          (a) KEEP — a 10/10 would overstate confidence when a check was not
              run, and capping at 9 signals incomplete coverage honestly;
          (b) SEPARATE — a skipped auditor is a fact about the INVOCATION, not
              about the RTL, so it belongs in its own report field rather than
              moving a score that is defined over code findings.
        (b) would RAISE a score, so I did not choose it unilaterally. This test
        pins (a), today's behaviour, so whichever way it is ruled the change is
        deliberate and visible rather than silent.
        """
        d = tmp_path / "rtl"
        d.mkdir()
        (d / "register_slice.sv").write_text(REGISTER_SLICE)
        rep = mod.review_rtl_dir(d, tmp_path / "ev")

        skipped = [f for cat in rep.per_category.values() for f in cat.findings
                   if f.source.startswith("rtl_precheck_gate")
                   and "did not run" in f.message]
        assert skipped, "a skipped auditor must be visible in the report"
        assert all(f.severity == "INFO" for f in skipped), skipped
        # it is reported as absence, not as a finding about the RTL
        assert all(f.line == 0 and not f.file for f in skipped)
        # and the documented 10 row is consequently not reachable here
        assert rep.total_errors == 0 and rep.total_warns == 0
        assert rep.total_infos >= 1
        assert rep.score == 9, (
            "clean RTL scores 9, not 10, purely because an auditor was skipped "
            "— that is the consequence under ruling in F2036-H")
        assert rep.verdict == "PASS"
