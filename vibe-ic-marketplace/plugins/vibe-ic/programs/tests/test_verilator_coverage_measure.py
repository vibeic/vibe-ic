"""Unit tests for verilator_coverage_measure.py (v0.53 gate).

Tests focus on the `check` subcommand + parser + provenance heuristic —
NOT on actually running Verilator (that's environment-dependent and
covered by integration tests, not unit tests).
"""
import json
import shutil
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'verilator_coverage_measure.py'
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import verilator_coverage_measure as gate  # noqa: E402


# ---------------------------------------------------------------------------
# parse_coverage_dat — use a synthetic fixture that matches the regex
# ---------------------------------------------------------------------------
def test_parse_coverage_dat_counts_covered_vs_total(tmp_path):
    # Verilator coverage.dat format: `C '<tag>' <hits>` per point.
    # gate expects a `C '<tag>'` prefix with `\x02` header in the tag blob.
    dat = tmp_path / "cov.dat"
    dat.write_text(
        "C '\x02line\x01rtl/foo.v\x01' 5\n"
        "C '\x02line\x01rtl/foo.v\x01' 0\n"
        "C '\x02line\x01rtl/bar.v\x01' 3\n"
        "C '\x02toggle\x01rtl/foo.v\x01' 1\n"
        "C '\x02toggle\x01rtl/foo.v\x01' 0\n"
        "C '\x02branch\x01rtl/foo.v\x01' 2\n"
    )
    result = gate.parse_coverage_dat(str(dat))
    totals = result["totals"]
    # 3 line points, 2 covered
    assert totals["line"]["total"] == 3
    assert totals["line"]["covered"] == 2
    # 2 toggle points, 1 covered
    assert totals["toggle"]["total"] == 2
    assert totals["toggle"]["covered"] == 1
    # 1 branch, 1 covered
    assert totals["branch"]["total"] == 1
    assert totals["branch"]["covered"] == 1
    # Per-file aggregation
    assert "rtl/foo.v" in result["per_file"]
    assert result["per_file"]["rtl/foo.v"]["line"]["total"] == 2


def test_parse_coverage_dat_ignores_non_matching_lines(tmp_path):
    dat = tmp_path / "cov.dat"
    dat.write_text(
        "# preamble\n"
        "header garbage\n"
        "C '\x02line\x01a.v\x01' 1\n"
    )
    totals = gate.parse_coverage_dat(str(dat))["totals"]
    assert totals["line"]["total"] == 1


# ---------------------------------------------------------------------------
# artefact_looks_tool_generated
# ---------------------------------------------------------------------------
_GOOD_PAYLOAD = {
    "tool": "verilator",
    "totals": {
        "line": {"covered": 78, "total": 100, "pct": 78.0},
        "toggle": {"covered": 75, "total": 100, "pct": 75.5},
        "branch": {"covered": 82, "total": 100, "pct": 82.3},
    },
}


def test_good_payload_passes():
    ok, reason = gate.artefact_looks_tool_generated(_GOOD_PAYLOAD)
    assert ok is True, reason


def test_missing_category_fails():
    bad = {"totals": {"line": {"covered": 1, "total": 1, "pct": 100.0}}}
    ok, reason = gate.artefact_looks_tool_generated(bad)
    assert ok is False
    assert "toggle" in reason or "missing" in reason.lower()


def test_missing_subkey_fails():
    bad = {"totals": {"line": {"covered": 1},  # no total / pct
                       "toggle": {"covered": 0, "total": 0, "pct": 0.0},
                       "branch": {"covered": 0, "total": 0, "pct": 0.0}}}
    ok, reason = gate.artefact_looks_tool_generated(bad)
    assert ok is False


def test_estimation_keyword_in_note_flags(tmp_path):
    bad = dict(_GOOD_PAYLOAD)
    bad["note"] = "estimated from eyeballing the report"
    ok, reason = gate.artefact_looks_tool_generated(bad)
    assert ok is False
    assert "estimation" in reason.lower() or "estimated" in reason.lower()


def test_soft_threshold_in_tool_field_flags(tmp_path):
    bad = dict(_GOOD_PAYLOAD)
    bad["tool"] = "agent ≥ 95 % estimate"
    ok, _ = gate.artefact_looks_tool_generated(bad)
    assert ok is False


def test_coverage_dat_path_must_exist(tmp_path):
    bad = dict(_GOOD_PAYLOAD)
    bad["coverage_dat"] = str(tmp_path / "does_not_exist.dat")
    ok, reason = gate.artefact_looks_tool_generated(bad)
    assert ok is False
    assert "missing" in reason.lower()


def test_coverage_dat_path_exists_ok(tmp_path):
    dat = tmp_path / "real.dat"
    dat.write_text("dummy")
    good = dict(_GOOD_PAYLOAD)
    good["coverage_dat"] = str(dat)
    ok, _ = gate.artefact_looks_tool_generated(good)
    assert ok is True


# ---------------------------------------------------------------------------
# cmd_check (the "check" subcommand)
# ---------------------------------------------------------------------------
def test_check_passes_when_all_thresholds_met(tmp_path):
    cov_json = tmp_path / "cov.json"
    cov_json.write_text(json.dumps(_GOOD_PAYLOAD))
    rc = gate.main([
        "check", "--coverage-json", str(cov_json),
        "--min-line", "70", "--min-toggle", "70", "--min-branch", "70",
    ])
    assert rc == 0


def test_check_fails_below_line_threshold(tmp_path):
    cov_json = tmp_path / "cov.json"
    cov_json.write_text(json.dumps(_GOOD_PAYLOAD))
    rc = gate.main([
        "check", "--coverage-json", str(cov_json),
        "--min-line", "80",  # 78 < 80
        "--min-toggle", "70", "--min-branch", "70",
    ])
    assert rc == 1


# --- CORRECTED (coverage-credit split) --------------------------------------------------
# The three tests below used to assert `rc == 2` for a missing artefact, an
# estimation-keyword artefact and a malformed artefact. They ENCODED THE
# DEFECT: flow_compliance_check._check_program_exit_zero maps rc=2 onto
# VACUOUS_PASS ("input not applicable"), and VACUOUS_PASS is added into
# `pass_count`, so each of those three states bought the enclosing step PASS
# credit. Two of them are outright defects (a hand-edited "estimated" artefact
# is the exact forgery this gate was built to reject; a corrupt file is not an
# inapplicable input), and the third depends on whether the toolchain that
# would have taken the measurement was even installed. The assertions are
# CORRECTED, not relaxed — every one of them now demands a stricter verdict.

#: A `--verilator-bin` value guaranteed not to resolve on PATH, so the
#: capability branch is deterministic in tests.
_NO_TOOLCHAIN = ["--verilator-bin", "__vibeic_no_such_verilator__"]
#: A `--verilator-bin` value guaranteed to resolve on any POSIX host.
_HAS_TOOLCHAIN = ["--verilator-bin", "sh"]
_THRESH = ["--min-line", "70", "--min-toggle", "70", "--min-branch", "70"]


def test_check_missing_artefact_without_toolchain_is_a_disclosed_waiver(
        tmp_path, capsys):
    """WAS `assert rc == 2` (VACUOUS_PASS -> counted into pass_count).
    No measurement AND no Verilator to have taken one is a capability gap:
    it may be EXPLAINED (rc=3 + PASS_WITH_WAIVERS -> WAIVED-DEFERRED,
    review_required, removed from the executed-PASS numerator) but never
    counted as a pass."""
    rc = gate.main([
        "check", "--coverage-json", str(tmp_path / "missing.json"),
    ] + _THRESH + _NO_TOOLCHAIN)
    assert rc == gate.WAIVER_EXIT_CODE == 3
    out = capsys.readouterr().out
    assert any(ln.lstrip().startswith("PASS_WITH_WAIVERS")
               for ln in out.splitlines())
    assert gate.COVERAGE_CAPABILITY in out


def test_check_missing_artefact_with_toolchain_is_a_defect(tmp_path):
    """WAS `assert rc == 2`. When Verilator IS installed the capability to
    measure existed and the measurement was simply never taken — a defect,
    not an exemption."""
    if shutil.which("sh") is None:  # pragma: no cover - non-POSIX host
        pytest.skip("no /bin/sh to stand in for an installed toolchain")
    rc = gate.main([
        "check", "--coverage-json", str(tmp_path / "missing.json"),
    ] + _THRESH + _HAS_TOOLCHAIN)
    assert rc == 1


def test_check_estimation_keyword_is_a_defect_never_vacuous(tmp_path):
    """WAS `assert rc == 2`. A hand-edited "estimated" artefact is the exact
    forgery this gate exists to reject; it must FAIL even on a host with no
    Verilator, because no capability gap can excuse a fabricated number."""
    cov_json = tmp_path / "cov.json"
    bad = dict(_GOOD_PAYLOAD)
    bad["note"] = "estimated from summary"
    cov_json.write_text(json.dumps(bad))
    rc = gate.main([
        "check", "--coverage-json", str(cov_json),
    ] + _THRESH + _NO_TOOLCHAIN)
    assert rc == 1


def test_check_malformed_json_is_a_defect(tmp_path):
    """WAS `assert rc == 2`. A corrupt file at the declared coverage path is
    a broken artefact, not an inapplicable input — FAIL on both toolchain
    states."""
    cov_json = tmp_path / "cov.json"
    cov_json.write_text("{not json")
    assert gate.main(["check", "--coverage-json", str(cov_json)]
                     + _THRESH + _NO_TOOLCHAIN) == 1
    if shutil.which("sh") is not None:
        assert gate.main(["check", "--coverage-json", str(cov_json)]
                         + _THRESH + _HAS_TOOLCHAIN) == 1


# ---------------------------------------------------------------------------
# COVERAGE-CREDIT SPLIT — the two meanings that used to share exit 2
#
# MEASURED on ~/campaign_pr427/spm/converge_ihp-sg13g2 (main @ v1.7.36):
#   $ verilator_coverage_measure.py check --coverage-json \
#       reports/phase2/coverage/coverage_actual.json
#   [check] artefact not tool-generated: missing totals.line   rc=2
#   -> Step 4 = VACUOUS-PASS, counted into `35/39 executed PASS`
# (that last clause is the state AS MEASURED THEN. `flow_compliance_check`
# has since dropped VACUOUS_PASS from the executed-PASS numerator — the tier
# now leaves X and stays in Y — so the same run would read `35/39` with the
# vacuous step outside X. It does not change what this fixture is about: an
# unmeasured coverage step must not be credited either way.)
# on a project where `which verilator` is rc=1 and no coverage.dat exists
# anywhere. The file at the declared coverage path is a FUNCTIONAL verdict
# payload written by design_one_shot_runner, not a coverage measurement.
# ---------------------------------------------------------------------------

#: Byte-shape of the real run's coverage_actual.json (values generalised; no
#: chip literals). No `totals` container -> nothing was ever measured here.
_FOREIGN_FUNCTIONAL_PAYLOAD = {
    "verdict": "PASS",
    "evidence": "phase2/stage1/sim_full_stack/oracle_run/oracle.log",
    "verification_track": "oracle_tb",
    "scenarios_covered": [],
    "vectors_passed": 28,
    "vectors_total": 28,
    "note": ("scenarios/vector counts extracted from this project's own "
             "oracle-TB transcript"),
}


def test_foreign_functional_payload_is_not_an_inapplicable_input(
        tmp_path, capsys):
    """The real-run reproducer. A functional-verdict payload sitting at the
    declared coverage path must NOT be read as "the input this gate audits
    does not apply". With no toolchain it is a disclosed, named capability
    gap (WAIVED-DEFERRED); it is never a PASS-counted VACUOUS_PASS."""
    cov_json = tmp_path / "coverage_actual.json"
    cov_json.write_text(json.dumps(_FOREIGN_FUNCTIONAL_PAYLOAD))
    rc = gate.main(["check", "--coverage-json", str(cov_json)]
                   + _THRESH + _NO_TOOLCHAIN)
    assert rc == 3, "a mislabelled artefact must not VACUOUS_PASS (rc=2)"
    out = capsys.readouterr().out
    assert "no `totals` container" in out
    assert any(ln.lstrip().startswith("PASS_WITH_WAIVERS")
               for ln in out.splitlines())


def test_foreign_functional_payload_fails_when_toolchain_present(tmp_path):
    if shutil.which("sh") is None:  # pragma: no cover - non-POSIX host
        pytest.skip("no /bin/sh to stand in for an installed toolchain")
    cov_json = tmp_path / "coverage_actual.json"
    cov_json.write_text(json.dumps(_FOREIGN_FUNCTIONAL_PAYLOAD))
    rc = gate.main(["check", "--coverage-json", str(cov_json)]
                   + _THRESH + _HAS_TOOLCHAIN)
    assert rc == 1


def test_bare_coverage_claim_without_totals_is_forged(tmp_path):
    """A payload that ASSERTS a coverage number with no `totals` container
    behind it is a claim, not a measurement — FAIL even with no toolchain,
    so the capability-gap tier cannot be used as a forgery escape hatch."""
    cov_json = tmp_path / "coverage_actual.json"
    cov_json.write_text(json.dumps({"line_coverage": 95.0, "verdict": "PASS"}))
    rc = gate.main(["check", "--coverage-json", str(cov_json)]
                   + _THRESH + _NO_TOOLCHAIN)
    assert rc == 1


def test_incomplete_totals_container_is_malformed_not_vacuous(tmp_path):
    """`totals` present but a category missing: something claimed to write
    coverage and wrote it wrong. Always a defect."""
    cov_json = tmp_path / "coverage_actual.json"
    cov_json.write_text(json.dumps(
        {"totals": {"line": {"covered": 1, "total": 1, "pct": 100.0}}}))
    rc = gate.main(["check", "--coverage-json", str(cov_json)]
                   + _THRESH + _NO_TOOLCHAIN)
    assert rc == 1


def test_dead_coverage_dat_backlink_is_malformed_not_vacuous(tmp_path):
    cov_json = tmp_path / "coverage_actual.json"
    bad = dict(_GOOD_PAYLOAD)
    bad["coverage_dat"] = str(tmp_path / "vanished.dat")
    cov_json.write_text(json.dumps(bad))
    rc = gate.main(["check", "--coverage-json", str(cov_json)]
                   + _THRESH + _NO_TOOLCHAIN)
    assert rc == 1


@pytest.mark.parametrize("payload,expected", [
    (None, "absent"),
    ("{not json", "corrupt"),
    (json.dumps([1, 2, 3]), "corrupt"),
    (json.dumps(_FOREIGN_FUNCTIONAL_PAYLOAD), "foreign"),
    (json.dumps({"line_coverage": 95.0}), "forged"),
    (json.dumps({"totals": {"line": {"covered": 1, "total": 1, "pct": 1.0}}}),
     "malformed"),
    (json.dumps(_GOOD_PAYLOAD), "measured"),
])
def test_classify_coverage_artefact_table(tmp_path, payload, expected):
    p = tmp_path / "cov.json"
    if payload is not None:
        p.write_text(payload)
    kind, detail, _ = gate.classify_coverage_artefact(p)
    assert kind == expected, detail


def test_estimation_language_classifies_as_forged_not_malformed(tmp_path):
    p = tmp_path / "cov.json"
    bad = dict(_GOOD_PAYLOAD)
    bad["source"] = "manually counted from the log"
    p.write_text(json.dumps(bad))
    kind, _, _ = gate.classify_coverage_artefact(p)
    assert kind == "forged"


def test_waiver_signal_is_the_one_flow_compliance_check_recognises(
        tmp_path, capsys):
    """WIRING discriminator: the exit code + stdout sentinel this program
    emits for a capability gap must be exactly the pair
    `flow_compliance_check._check_program_exit_zero` promotes to
    WAIVED-DEFERRED. If either half drifts, the step silently reverts to a
    bare FAIL (or, worse, back to a counted PASS)."""
    import flow_compliance_check as F

    assert gate.WAIVER_EXIT_CODE == F._WAIVER_EXIT_CODE
    cov_json = tmp_path / "coverage_actual.json"
    cov_json.write_text(json.dumps(_FOREIGN_FUNCTIONAL_PAYLOAD))
    rc = gate.main(["check", "--coverage-json", str(cov_json)]
                   + _THRESH + _NO_TOOLCHAIN)
    out = capsys.readouterr().out
    assert rc == F._WAIVER_EXIT_CODE
    assert F._stdout_signals_waiver(out) is True


# ---------------------------------------------------------------------------
# DIRECTION-1 GUARDS — behaviour that must NOT change. These pass on BOTH the
# base tree and the fixed tree.
# ---------------------------------------------------------------------------
def test_direction1_measured_artefact_meeting_thresholds_still_passes(tmp_path):
    """The genuine measured PASS path is untouched — including on a host
    with no Verilator installed, because a stored measurement needs no
    toolchain to be re-read."""
    cov_json = tmp_path / "cov.json"
    cov_json.write_text(json.dumps(_GOOD_PAYLOAD))
    assert gate.main([
        "check", "--coverage-json", str(cov_json),
        "--min-line", "70", "--min-toggle", "70", "--min-branch", "70",
    ]) == 0


def test_direction1_below_threshold_is_still_rc1(tmp_path):
    cov_json = tmp_path / "cov.json"
    cov_json.write_text(json.dumps(_GOOD_PAYLOAD))
    assert gate.main([
        "check", "--coverage-json", str(cov_json),
        "--min-line", "99", "--min-toggle", "70", "--min-branch", "70",
    ]) == 1


def test_direction1_other_programs_keep_the_rc2_vacuous_convention(tmp_path):
    """The rc=2 -> VACUOUS_PASS convention is SHARED. This change is local to
    verilator_coverage_measure; the input-missing users of the convention
    (foundry_handoff_package_check here) must still reach VACUOUS_PASS."""
    import flow_compliance_check as F

    ok, snippet = F._check_program_exit_zero(
        tmp_path, "foundry_handoff_package_check .")
    assert ok is True
    assert snippet.startswith(F._VACUOUS_HINT_PREFIX), snippet


# ---------------------------------------------------------------------------
# Argparse / subcommand dispatch
# ---------------------------------------------------------------------------
def test_parser_rejects_no_subcommand():
    parser = gate.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_measure_subcommand_requires_core_args():
    parser = gate.build_parser()
    # Missing --rtl-dir / --top / --main / --out
    with pytest.raises(SystemExit):
        parser.parse_args(["measure"])


# ---------------------------------------------------------------------------
# v0.55.1: Verilator 5.x coverage.dat support
# ---------------------------------------------------------------------------
def test_parse_coverage_dat_v5_format(tmp_path):
    """Verilator 5.x records put category in the `page` field
    (`v_line/<mod>` / `v_toggle/<mod>` / `v_branch/<mod>`) rather than as
    a leading-byte tag. The parser must accept both formats."""
    dat = tmp_path / "v5_cov.dat"
    dat.write_text(
        "# Verilator 5.020 coverage report\n"
        "C 'page\x02v_line/foo\x01f\x02rtl/foo.v\x01l\x0210\x01' 7\n"
        "C 'page\x02v_line/foo\x01f\x02rtl/foo.v\x01l\x0211\x01' 0\n"
        "C 'page\x02v_toggle/foo\x01f\x02rtl/foo.v\x01' 3\n"
        "C 'page\x02v_branch/foo\x01f\x02rtl/foo.v\x01' 2\n"
        "C 'page\x02v_branch/foo\x01f\x02rtl/foo.v\x01' 0\n"
    )
    result = gate.parse_coverage_dat(str(dat))
    assert result["format_detected"] == "v5"
    assert result["totals"]["line"] == {"covered": 1, "total": 2, "pct": 50.0}
    assert result["totals"]["toggle"] == {"covered": 1, "total": 1, "pct": 100.0}
    assert result["totals"]["branch"] == {"covered": 1, "total": 2, "pct": 50.0}
    # Per-file aggregation works
    pf = result["per_file"]["rtl/foo.v"]
    assert pf["line"]["total"] == 2


def test_parse_coverage_dat_v4_format_still_works(tmp_path):
    """v4.x format (auto-detected) must continue to parse correctly."""
    dat = tmp_path / "v4_cov.dat"
    dat.write_text(
        "C '\x02line\x01rtl/foo.v\x01' 5\n"
        "C '\x02line\x01rtl/foo.v\x01' 0\n"
        "C '\x02toggle\x01rtl/bar.v\x01' 1\n"
    )
    result = gate.parse_coverage_dat(str(dat))
    assert result["format_detected"] == "v4"
    assert result["totals"]["line"] == {"covered": 1, "total": 2, "pct": 50.0}


def test_parse_coverage_dat_v5_unknown_page_classified_other(tmp_path):
    """Unrecognised `page` values land in 'other' bucket (don't crash)."""
    dat = tmp_path / "x.dat"
    dat.write_text(
        "C 'page\x02v_line/foo\x01f\x02rtl/x.v\x01' 1\n"
        "C 'page\x02v_user/foo\x01f\x02rtl/x.v\x01' 1\n"  # unknown bucket
    )
    result = gate.parse_coverage_dat(str(dat))
    assert result["format_detected"] == "v5"
    # 1 user-page record → "other" total = 1, but "other" isn't reported
    # in totals (only line/toggle/branch). Just check no crash + totals OK.
    assert result["totals"]["line"]["total"] == 1


def test_parse_coverage_dat_empty_file(tmp_path):
    dat = tmp_path / "empty.dat"
    dat.write_text("")
    result = gate.parse_coverage_dat(str(dat))
    assert result["totals"]["line"]["total"] == 0
    assert result["format_detected"] == "unknown"


def test_v5_classifier_pulls_page_field():
    blob = "page\x02v_line/foo\x01f\x02rtl/x.v\x01l\x0210\x01"
    assert gate._classify_v5(blob) == "line"
    blob_toggle = "page\x02v_toggle/foo\x01f\x02rtl/x.v\x01"
    assert gate._classify_v5(blob_toggle) == "toggle"
    blob_branch = "page\x02v_branch/foo\x01f\x02rtl/x.v\x01"
    assert gate._classify_v5(blob_branch) == "branch"


def test_v5_classifier_returns_none_for_unrecognised():
    blob = "page\x02v_user/foo\x01"
    assert gate._classify_v5(blob) is None
    blob_no_page = "f\x02rtl/x.v\x01"
    assert gate._classify_v5(blob_no_page) is None


def test_v4_classifier_handles_leading_byte():
    blob = "\x02line\x01rtl/foo.v\x01"
    assert gate._classify_v4(blob) == "line"
    blob_toggle = "\x02toggle\x01rtl/foo.v\x01"
    assert gate._classify_v4(blob_toggle) == "toggle"


def test_v5_file_extractor():
    blob = "page\x02v_line/foo\x01f\x02rtl/foo.v\x01l\x0210\x01"
    assert gate._file_v5(blob) == "rtl/foo.v"


def test_v4_file_extractor():
    blob = "\x02line\x01rtl/foo.v\x01"
    assert gate._file_v4(blob) == "rtl/foo.v"
