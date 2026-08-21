"""Unit tests for `mpw_precheck_result_gate.py` (TAPEOUT-SIGNOFF P0#2, parser).

Fixture-based: synthesise mpw_precheck run directories in tmp_path that mirror
the real efabless/mpw_precheck log conventions (both the older bare
`<Check> Check Passed` layout and the newer `{{SUCCESS}} <Check> Check Passed`
layout under `logs/`), then assert the aggregate gate verdict. The §4.05 core
is proven by (c) — an absent/empty run dir must NEVER produce a PASS.
"""
import importlib

mod = importlib.import_module("mpw_precheck_result_gate")

# Canonical human-ish log names for each required stage (newer layout style).
_STAGE_LOG_NAME = {
    "license": "License", "makefile": "Makefile", "default": "Default",
    "documentation": "Documentation", "consistency": "Consistency",
    "gpio_defines": "GPIO-Defines", "xor": "XOR", "magic_drc": "Magic DRC",
    "klayout_feol": "KLayout FEOL", "klayout_beol": "KLayout BEOL",
    "klayout_offgrid": "KLayout Offgrid", "lvs": "LVS", "oeb": "OEB",
}


def _write_precheck_log(rundir, passed, failed=(), summary=None,
                        marker=True, sub="logs"):
    """Write a synthetic precheck.log under `rundir/<sub>/`.

    passed/failed are iterables of canonical stage keys. `marker=True` uses the
    newer `{{SUCCESS}}/{{FAIL}}` prefix; False uses the older bare form.
    """
    log_dir = rundir / sub if sub else rundir
    log_dir.mkdir(parents=True, exist_ok=True)
    lines = []
    for k in passed:
        pre = "{{SUCCESS}} " if marker else ""
        lines.append(f"{pre}{_STAGE_LOG_NAME[k]} Check Passed")
    for k in failed:
        pre = "{{FAIL}} " if marker else ""
        lines.append(f"{pre}{_STAGE_LOG_NAME[k]} Check Failed")
    if summary == "PASS":
        lines.append("{{SUCCESS}} All Checks Passed!" if marker
                     else "All Checks Passed!")
    elif summary == "FAIL":
        n = len(list(failed)) or 1
        lines.append(f"{{{{FAIL}}}} {n} Check(s) Failed")
    (log_dir / "precheck.log").write_text("\n".join(lines) + "\n",
                                          encoding="utf-8")


ALL = list(mod.DEFAULT_REQUIRED)


class TestAllPassIsPass:
    """(a) synthetic all-pass precheck dir → PASS."""

    def test_newer_layout_all_pass(self, tmp_path):
        _write_precheck_log(tmp_path, passed=ALL, summary="PASS", marker=True)
        rep = mod.evaluate(tmp_path)
        assert rep.overall_verdict == "PASS"
        assert rep.failed_checks == []
        assert rep.missing_checks == []
        assert mod.main([str(tmp_path)]) == 0

    def test_older_layout_all_pass_toplevel(self, tmp_path):
        # Older layout: bare lines, log at the TOP LEVEL (not under logs/).
        _write_precheck_log(tmp_path, passed=ALL, summary="PASS",
                            marker=False, sub="")
        rep = mod.evaluate(tmp_path)
        assert rep.overall_verdict == "PASS"

    def test_pass_without_summary_line(self, tmp_path):
        # Per-check evidence alone is sufficient; no summary line present.
        _write_precheck_log(tmp_path, passed=ALL, summary=None, marker=True)
        rep = mod.evaluate(tmp_path)
        assert rep.overall_verdict == "PASS"


class TestOneFailedCheckIsFail:
    """(b) one failed check (LVS) → FAIL naming it."""

    def test_lvs_fail_named(self, tmp_path):
        passed = [k for k in ALL if k != "lvs"]
        _write_precheck_log(tmp_path, passed=passed, failed=["lvs"],
                            summary="FAIL", marker=True)
        rep = mod.evaluate(tmp_path)
        assert rep.overall_verdict == "FAIL"
        assert "lvs" in rep.failed_checks
        assert mod.main([str(tmp_path)]) == 1

    def test_fail_dominates_even_with_pass_summary(self, tmp_path):
        # A stray "All Checks Passed" must never override a real FAIL line.
        passed = [k for k in ALL if k != "consistency"]
        _write_precheck_log(tmp_path, passed=passed, failed=["consistency"],
                            summary="PASS", marker=True)
        rep = mod.evaluate(tmp_path)
        assert rep.overall_verdict == "FAIL"
        assert "consistency" in rep.failed_checks


class TestAbsentOrEmptyIsSkipped:
    """(c) THE §4.05 NEGATIVE: absent/empty rundir → SKIPPED_CONDITION, never PASS."""

    def test_absent_rundir(self, tmp_path):
        missing = tmp_path / "does_not_exist"
        rep = mod.evaluate(missing)
        assert rep.overall_verdict == "SKIPPED_CONDITION"
        assert rep.overall_verdict != "PASS"
        assert mod.main([str(missing)]) == 1  # hard gate: non-zero

    def test_empty_rundir(self, tmp_path):
        empty = tmp_path / "empty_run"
        empty.mkdir()
        rep = mod.evaluate(empty)
        assert rep.overall_verdict == "SKIPPED_CONDITION"
        assert rep.overall_verdict != "PASS"

    def test_logs_present_but_no_verdicts(self, tmp_path):
        # A log file exists but carries no parseable check line — still not PASS.
        (tmp_path / "logs").mkdir()
        (tmp_path / "logs" / "precheck.log").write_text(
            "Uncompressing GDS files\nStarting precheck run\n", encoding="utf-8")
        rep = mod.evaluate(tmp_path)
        assert rep.overall_verdict == "SKIPPED_CONDITION"
        assert rep.overall_verdict != "PASS"


class TestPartialRunIsIncomplete:
    """(d) partial run (some checks missing) → INCOMPLETE, not PASS."""

    def test_partial_run(self, tmp_path):
        # Only the first four checks ran; the rest never logged a verdict.
        partial = ALL[:4]
        _write_precheck_log(tmp_path, passed=partial, summary=None, marker=True)
        rep = mod.evaluate(tmp_path)
        assert rep.overall_verdict == "INCOMPLETE"
        assert rep.overall_verdict != "PASS"
        # The checks that ran are not listed as missing; the rest are.
        assert "lvs" in rep.missing_checks
        assert "license" not in rep.missing_checks
        assert mod.main([str(tmp_path)]) == 1

    def test_incomplete_not_masked_by_pass_summary(self, tmp_path):
        # Even a spurious "All Checks Passed" can't fill an un-run required check.
        partial = ALL[:6]
        _write_precheck_log(tmp_path, passed=partial, summary="PASS",
                            marker=True)
        rep = mod.evaluate(tmp_path)
        assert rep.overall_verdict == "INCOMPLETE"


class TestRequiredOverride:
    def test_narrow_required_set_can_pass(self, tmp_path):
        # If the caller only requires a subset, an all-pass on that subset PASSes
        # even though the full ladder didn't run.
        subset = ["license", "consistency", "xor"]
        _write_precheck_log(tmp_path, passed=subset, summary=None, marker=True)
        rep = mod.evaluate(tmp_path, required=subset)
        assert rep.overall_verdict == "PASS"
        assert rep.required_checks == subset

    def test_extra_failing_stage_still_fails(self, tmp_path):
        # A non-required stage that FAILED is still surfaced as a real failure.
        subset = ["license"]
        _write_precheck_log(tmp_path, passed=["license"], failed=["lvs"],
                            summary="FAIL", marker=True)
        rep = mod.evaluate(tmp_path, required=subset)
        assert rep.overall_verdict == "FAIL"
        assert "lvs" in rep.failed_checks


class TestParsingRobustness:
    def test_gpio_defines_name_variants(self, tmp_path):
        (tmp_path / "logs").mkdir()
        (tmp_path / "logs" / "precheck.log").write_text(
            "{{SUCCESS}} GPIO Defines Check Passed\n", encoding="utf-8")
        found = mod.parse_check_statuses(
            mod.collect_log_texts(tmp_path), tmp_path)
        assert "gpio_defines" in found
        assert found["gpio_defines"].verdict == "PASS"

    def test_per_check_subdir_logs_are_scanned(self, tmp_path):
        # Newer layout writes per-check logs into their own subdirs.
        d = tmp_path / "logs" / "lvs"
        d.mkdir(parents=True)
        (d / "lvs.log").write_text("LVS Check Failed\n", encoding="utf-8")
        found = mod.parse_check_statuses(
            mod.collect_log_texts(tmp_path), tmp_path)
        assert found["lvs"].verdict == "FAIL"

    def test_summary_failed_line_variants(self, tmp_path):
        texts = [(tmp_path / "x.log", "{{FAIL}} 3 Check(s) Failed\n")]
        verdict, line = mod.parse_summary(texts)
        assert verdict == "FAIL"

    def test_attribution_present(self, tmp_path):
        _write_precheck_log(tmp_path, passed=ALL, summary="PASS")
        rep = mod.evaluate(tmp_path)
        assert "mpw_precheck_result_gate" in rep.as_dict()["emitted_by"]

    def test_chip_agnostic_no_literal_source(self):
        # Guard the gate itself: no chip/project literal in the matching rules.
        import inspect
        from _source_pin import code_only
        # CODE only: a comment in the module stating this very property
        # would otherwise turn the test red (measured: 1 failed).
        src = code_only(inspect.getsource(mod))
        # The parser must key only on generic precheck stage names.
        assert "caravel_user_project" not in src
        assert "user_project_wrapper" not in src
