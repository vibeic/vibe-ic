"""Unit tests for verilator_coverage_measure.py (v0.53 gate).

Tests focus on the `check` subcommand + parser + provenance heuristic —
NOT on actually running Verilator (that's environment-dependent and
covered by integration tests, not unit tests).
"""
import json
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


def test_check_returns_2_on_missing_artefact(tmp_path):
    rc = gate.main([
        "check", "--coverage-json", str(tmp_path / "missing.json"),
        "--min-line", "70", "--min-toggle", "70", "--min-branch", "70",
    ])
    assert rc == 2


def test_check_returns_2_on_estimation_keyword(tmp_path):
    cov_json = tmp_path / "cov.json"
    bad = dict(_GOOD_PAYLOAD)
    bad["note"] = "estimated from summary"
    cov_json.write_text(json.dumps(bad))
    rc = gate.main([
        "check", "--coverage-json", str(cov_json),
        "--min-line", "70", "--min-toggle", "70", "--min-branch", "70",
    ])
    assert rc == 2


def test_check_returns_2_on_malformed_json(tmp_path):
    cov_json = tmp_path / "cov.json"
    cov_json.write_text("{not json")
    rc = gate.main([
        "check", "--coverage-json", str(cov_json),
        "--min-line", "70", "--min-toggle", "70", "--min-branch", "70",
    ])
    assert rc == 2


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
