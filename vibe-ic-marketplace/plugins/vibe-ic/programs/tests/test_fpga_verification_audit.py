"""Unit tests for fpga_verification_audit.py (v0.53 gate).

Regression coverage for the v0.52 failure mode where the agent wrote
"1083/1083 PASS, ≥95% coverage (estimated)" in the verification report
while actual tool numbers were line=78%, toggle=75%, branch=82%.
"""
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'fpga_verification_audit.py'
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import fpga_verification_audit as gate  # noqa: E402


# ---------------------------------------------------------------------------
# load_summary
# ---------------------------------------------------------------------------
def test_load_summary_parses_tb_lines(tmp_path):
    p = tmp_path / "summary.txt"
    p.write_text(
        "tb_foo PASS=10 FAIL=0 ERR=0\n"
        "tb_bar PASS=23 FAIL=1 ERR=0\n"
        "GRAND_TOTAL PASS=33 FAIL=1\n"
    )
    s = gate.load_summary(str(p))
    assert s["tb_foo"] == 10
    assert s["tb_bar"] == 23
    assert s["GRAND_TOTAL"] == 33
    assert s["GRAND_TOTAL_fail"] == 1


def test_load_summary_missing_file_returns_empty():
    assert gate.load_summary("/no/such/file") == {}


# ---------------------------------------------------------------------------
# load_coverage
# ---------------------------------------------------------------------------
def test_load_coverage_missing_returns_none(tmp_path):
    assert gate.load_coverage(str(tmp_path / "no.json")) is None


def test_load_coverage_parseable(tmp_path):
    p = tmp_path / "cov.json"
    p.write_text(json.dumps({"totals": {"line": {"pct": 78.3}}}))
    assert gate.load_coverage(str(p))["totals"]["line"]["pct"] == 78.3


# ---------------------------------------------------------------------------
# claim extractors
# ---------------------------------------------------------------------------
def test_extract_pass_counts_bare_pass():
    md = "the suite reports 1083 PASS across 8 tbs"
    assert 1083 in gate.extract_pass_counts(md)


def test_extract_pass_counts_slash_total():
    md = "1083/1083 PASS, every case green"
    assert 1083 in gate.extract_pass_counts(md)


def test_extract_pass_counts_chinese():
    md = "最終共 1083 個 PASS，零失敗。"
    counts = gate.extract_pass_counts(md)
    assert 1083 in counts


def test_extract_coverage_claims_english():
    md = "line coverage: 78.3%. branch 82.3 %. toggle=75.5%"
    claims = dict(gate.extract_coverage_claims(md))
    # keys are lower-cased from the regex group
    assert claims.get("line") == pytest.approx(78.3)
    assert claims.get("branch") == pytest.approx(82.3)
    assert claims.get("toggle") == pytest.approx(75.5)


def test_find_estimation_flags_catches_estimated():
    md = "Coverage is estimated at 95%."
    hits = gate.find_estimation_flags(md)
    assert len(hits) >= 1


def test_find_estimation_flags_catches_soft_threshold():
    md = "coverage ≥ 95% overall"
    hits = gate.find_estimation_flags(md)
    assert len(hits) >= 1


def test_find_estimation_flags_catches_ge_95():
    md = "line >= 95%, branch >= 90%"
    hits = gate.find_estimation_flags(md)
    assert len(hits) >= 2


def test_find_estimation_flags_chinese():
    md = "覆蓋率大約 95%"
    assert len(gate.find_estimation_flags(md)) >= 1


# ---------------------------------------------------------------------------
# audit() — happy path
# ---------------------------------------------------------------------------
_GOOD_COV = {
    "totals": {
        "line": {"pct": 78.3},
        "toggle": {"pct": 75.5},
        "branch": {"pct": 82.3},
    }
}


def test_audit_happy_path_pass_counts_and_coverage_match():
    md = "Total 1083 PASS. line coverage 78.3%, branch 82.3%, toggle 75.5%"
    summary = {"GRAND_TOTAL": 1083}
    findings, ok = gate.audit(md, summary, _GOOD_COV)
    assert ok is True
    pass_count_finding = [f for f in findings if f["kind"] == "pass_count"][0]
    assert pass_count_finding["ok"] is True


def test_audit_fails_when_report_claims_more_pass_than_summary():
    md = "Report: 9999 PASS"
    summary = {"GRAND_TOTAL": 100}
    findings, ok = gate.audit(md, summary, _GOOD_COV)
    assert ok is False
    # Report didn't include the real GRAND_TOTAL (100)
    pass_findings = [f for f in findings if f["kind"] == "pass_count"]
    assert any(not f["ok"] for f in pass_findings)


def test_audit_fails_on_coverage_mismatch():
    md = "line coverage 95%"
    findings, ok = gate.audit(md, {}, _GOOD_COV)
    assert ok is False
    cov_findings = [f for f in findings if f["kind"] == "coverage"]
    assert any(not f["ok"] for f in cov_findings)
    assert any("78.3" in f["detail"] for f in cov_findings)


def test_audit_fails_on_estimation_language():
    md = "coverage estimated at 80%"
    findings, ok = gate.audit(md, {}, _GOOD_COV)
    assert ok is False
    est = [f for f in findings if f["kind"] == "estimation"]
    assert len(est) >= 1


def test_audit_fails_when_coverage_claimed_but_no_artefact():
    md = "line coverage 80%"
    findings, ok = gate.audit(md, {}, coverage=None)
    assert ok is False
    cov_findings = [f for f in findings if f["kind"] == "coverage"]
    assert any(not f["ok"] and "coverage_actual.json" in f["detail"]
               for f in cov_findings)


def test_audit_tool_mentions_are_positive_findings():
    md = "Ran Verilator to compute coverage"
    findings, _ = gate.audit(md, {}, _GOOD_COV)
    tm = [f for f in findings if f["kind"] == "tool_mention"]
    assert any(f["ok"] and "Verilator" in f["detail"] for f in tm)


def test_audit_coverage_within_1pct_tolerance_passes():
    md = "line coverage 78.0%"  # tool says 78.3 — within 1.0
    findings, ok = gate.audit(md, {}, _GOOD_COV)
    cov = [f for f in findings if f["kind"] == "coverage"]
    # With tolerance 1.0, 78.0 vs 78.3 should match
    assert any(f["ok"] for f in cov)


# ---------------------------------------------------------------------------
# main() CLI
# ---------------------------------------------------------------------------
def _setup(tmp_path, report_md, summary_text="GRAND_TOTAL PASS=0 FAIL=0\n",
           coverage=None):
    report = tmp_path / "report.md"
    report.write_text(report_md)
    summary = tmp_path / "summary.txt"
    summary.write_text(summary_text)
    cov = tmp_path / "cov.json"
    if coverage is not None:
        cov.write_text(json.dumps(coverage))
    return report, summary, cov


def test_cli_pass(tmp_path):
    md = "1083 PASS. line 78.3%, branch 82.3%, toggle 75.5%. Verilator."
    summary_text = "GRAND_TOTAL PASS=1083 FAIL=0\n"
    report, summary, cov = _setup(tmp_path, md, summary_text, _GOOD_COV)
    out = tmp_path / "out.json"
    rc = gate.main([
        "--report", str(report),
        "--summary", str(summary),
        "--coverage", str(cov),
        "--out", str(out),
    ])
    assert rc == 0
    data = json.loads(out.read_text())
    assert data["ok"] is True


def test_cli_fail_on_estimation(tmp_path):
    md = "line coverage estimated ≥ 95%"
    report, summary, cov = _setup(tmp_path, md, coverage=_GOOD_COV)
    out = tmp_path / "out.json"
    rc = gate.main([
        "--report", str(report),
        "--summary", str(summary),
        "--coverage", str(cov),
        "--out", str(out),
    ])
    assert rc == 1


def test_cli_warn_only_returns_0_on_failures(tmp_path):
    md = "line coverage estimated ≥ 95%"
    report, summary, cov = _setup(tmp_path, md, coverage=_GOOD_COV)
    out = tmp_path / "out.json"
    rc = gate.main([
        "--report", str(report),
        "--summary", str(summary),
        "--coverage", str(cov),
        "--out", str(out),
        "--warn-only",
    ])
    assert rc == 0


def test_cli_missing_report_returns_2(tmp_path):
    rc = gate.main([
        "--report", str(tmp_path / "missing.md"),
        "--summary", str(tmp_path / "summary.txt"),
        "--out", str(tmp_path / "out.json"),
    ])
    assert rc == 2


# ---------------------------------------------------------------------------
# v0.54: estimation_keywords.yaml loader
# ---------------------------------------------------------------------------
def test_load_estimation_keywords_default_yaml_loaded():
    """The shipped data/estimation_keywords.yaml exists and provides a
    populated keyword + soft-threshold list."""
    kw, sft = gate.load_estimation_keywords()
    assert len(kw) >= 5, "default YAML should ship multi-language keywords"
    assert len(sft) >= 1
    # spot-check that Chinese is in there (regression for v0.54 motivation)
    assert any(p.search("大約 95%") for p in kw)


def test_load_estimation_keywords_falls_back_when_yaml_missing(tmp_path):
    kw, sft = gate.load_estimation_keywords(tmp_path / "absent.yaml")
    # Falls back to the built-in defaults — at least the en/zh basics
    assert len(kw) == 1  # the single ESTIMATION_RE
    assert kw[0].search("estimated")
    assert sft[0].search("≥ 95%")


def test_load_estimation_keywords_custom_yaml(tmp_path):
    """A user-provided YAML overrides the built-in list."""
    custom = tmp_path / "custom.yaml"
    custom.write_text(
        "keywords:\n"
        "  - 'eyeballed'\n"
        "  - 'guesstimate'\n"
        "soft_threshold_patterns:\n"
        "  - 'NEVER_USE_GE'\n"
    )
    kw, sft = gate.load_estimation_keywords(custom)
    assert any(p.search("just eyeballed it") for p in kw)
    assert any(p.search("just guesstimate") for p in kw)
    # "estimated" no longer matches because the custom list replaced
    # the defaults entirely
    assert not any(p.search("estimated") for p in kw)


def test_cli_keywords_yaml_override(tmp_path):
    """--keywords-yaml flag overrides the bundled list."""
    custom = tmp_path / "custom.yaml"
    custom.write_text("keywords:\n  - 'eyeballed'\n")
    md = "coverage was eyeballed at 95%"
    summary_text = "GRAND_TOTAL PASS=0 FAIL=0\n"
    report, summary, cov = _setup(tmp_path, md, summary_text, _GOOD_COV)
    out = tmp_path / "out.json"
    rc = gate.main([
        "--report", str(report),
        "--summary", str(summary),
        "--coverage", str(cov),
        "--out", str(out),
        "--keywords-yaml", str(custom),
    ])
    assert rc == 1  # 'eyeballed' caught


def test_simple_yaml_parser_handles_inline_comments(tmp_path):
    """Sanity-check the tiny YAML reader: inline `# ...` after a list
    entry is stripped (when the value isn't quoted)."""
    p = tmp_path / "x.yaml"
    p.write_text(
        "keywords:\n"
        "  - hello   # comment\n"
        "  - 'with # inside quotes'\n"
    )
    parsed = gate._parse_simple_yaml_lists(p)
    assert parsed["keywords"] == ["hello", "with # inside quotes"]
