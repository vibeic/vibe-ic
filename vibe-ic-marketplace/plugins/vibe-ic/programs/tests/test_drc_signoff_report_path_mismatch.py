#!/usr/bin/env python3
"""Bidirectional tests for DEFECT 1: producer/consumer filename mismatch.

DEFECT direction: when only drc_signoff.rpt (no .json) exists, the OLD
  code would look only for drc_signoff.json and report "(report missing)".
FIXED direction: the new _resolve_drc_signoff_verdict reads the .rpt and
  reports "PASS" for a zero-item KLayout XML report.
ABSENT direction: with no report at all, still reports "(report missing)".

LVS parallel:
DEFECT direction: lvs.json with eda_report_audit schema (passed/summary
  fields only) had verdict=None → "?".
FIXED direction: _resolve_lvs_verdict reads summary.terminal_verdict and
  returns the real result.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
import pytest

# Import the resolver functions directly so we test the logic,
# not a subprocess round-trip.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import final_report_generate as frg


# ---------------------------------------------------------------------------
# Helpers — build minimal synthetic project fixtures
# ---------------------------------------------------------------------------

_KLAYOUT_ZERO_VIO_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<report-database>
 <description>SKY130 DRC runset</description>
 <top-cell>spm</top-cell>
 <categories>
  <category><name>li.1</name></categories>
 </categories>
 <items>
 </items>
</report-database>
"""

_KLAYOUT_ONE_VIO_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<report-database>
 <description>SKY130 DRC runset</description>
 <top-cell>spm</top-cell>
 <items>
  <item><category>li.1</category><description>violation</description></item>
 </items>
</report-database>
"""

_LVS_JSON_EDA_AUDIT = {
    "program": "eda_report_audit:lvs",
    "passed": True,
    "findings": [],
    "summary": {
        "files_found": 2,
        "terminal_verdict": "MATCH",
        "tool_authentic": True,
    },
}

_LVS_JSON_EDA_AUDIT_FAIL = {
    "program": "eda_report_audit:lvs",
    "passed": False,
    "findings": ["mismatch"],
    "summary": {
        "files_found": 2,
        "terminal_verdict": "MISMATCH",
        "tool_authentic": True,
    },
}

_LVS_VERDICT_JSON = {
    "status": "PASS",
    "result": "PASS",
    "finding": "LVS_MATCH",
    "message": "netgen: matches",
    "generated_by": "phase3_one_shot_runner:_run_extraction_lvs (#477)",
}


def _make_phase3_dir(tmp_path: Path) -> Path:
    d = tmp_path / "reports" / "phase3"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# DEFECT 1-A: drc_signoff.rpt present (clean), no .json
#   DEFECT direction: old logic would return "(report missing)"
#   FIXED direction: new logic returns "PASS"
# ---------------------------------------------------------------------------

class TestDrcSignoffRptResolver:
    def test_defect_direction_old_code_finds_nothing(self, tmp_path):
        """OLD code: _find_report(project, "drc_signoff.json") returns None
        when only .rpt exists → pv["drc_signoff"] = "(report missing)".
        Verify the .rpt IS on disk (the defect precondition)."""
        d = _make_phase3_dir(tmp_path)
        (d / "drc_signoff.rpt").write_text(_KLAYOUT_ZERO_VIO_XML)
        # Old code path: _find_report for .json should return None
        found = frg._find_report(tmp_path, "drc_signoff.json")
        assert found is None, (
            "Precondition: no .json present; old code would see no file "
            "and return '(report missing)'"
        )

    def test_fixed_clean_rpt_returns_pass(self, tmp_path):
        """FIXED: .rpt with zero <item> elements → PASS."""
        d = _make_phase3_dir(tmp_path)
        (d / "drc_signoff.rpt").write_text(_KLAYOUT_ZERO_VIO_XML)
        verdict = frg._resolve_drc_signoff_verdict(tmp_path)
        assert verdict == "PASS", f"Expected PASS, got {verdict!r}"

    def test_fixed_violated_rpt_returns_fail(self, tmp_path):
        """FIXED: .rpt with one <item> → FAIL (not missing)."""
        d = _make_phase3_dir(tmp_path)
        (d / "drc_signoff.rpt").write_text(_KLAYOUT_ONE_VIO_XML)
        verdict = frg._resolve_drc_signoff_verdict(tmp_path)
        assert "FAIL" in verdict or "violation" in verdict.lower(), (
            f"Expected FAIL/violation, got {verdict!r}"
        )

    def test_absent_report_still_missing(self, tmp_path):
        """No .rpt and no .json → still '(report missing)'."""
        _make_phase3_dir(tmp_path)
        verdict = frg._resolve_drc_signoff_verdict(tmp_path)
        assert verdict == "(report missing)", (
            f"Expected '(report missing)' for absent report, got {verdict!r}"
        )

    def test_json_takes_priority_over_rpt(self, tmp_path):
        """When both .json and .rpt exist, .json wins."""
        d = _make_phase3_dir(tmp_path)
        (d / "drc_signoff.rpt").write_text(_KLAYOUT_ONE_VIO_XML)  # 1 violation
        (d / "drc_signoff.json").write_text(json.dumps({
            "verdict": "PASS", "violations": 0, "engines_run": ["klayout"]
        }))
        verdict = frg._resolve_drc_signoff_verdict(tmp_path)
        assert verdict == "PASS", (
            f"JSON sidecar should override .rpt; got {verdict!r}"
        )

    def test_rpt_with_header_comment_lines_parsed_correctly(self, tmp_path):
        """Runner-generated .rpt has comment header lines before the XML.
        The resolver must skip them and count <item> correctly."""
        d = _make_phase3_dir(tmp_path)
        header = (
            "# Sign-off DRC report (ORGANIC-20260531 Step 31 alias).\n"
            "# Source: phase3/reports/drc.rpt\n"
            "# Tool: klayout\n"
            "# engines_run: [klayout]\n"
            "#\n"
        )
        (d / "drc_signoff.rpt").write_text(header + _KLAYOUT_ZERO_VIO_XML)
        verdict = frg._resolve_drc_signoff_verdict(tmp_path)
        assert verdict == "PASS", (
            f"Header comments must not confuse item-count parser; got {verdict!r}"
        )


# ---------------------------------------------------------------------------
# DEFECT 1-B: lvs.json uses eda_report_audit schema (no "verdict"/"status")
#   DEFECT direction: old .get("verdict") or .get("status") → None → "?"
#   FIXED direction: new _resolve_lvs_verdict reads summary.terminal_verdict
# ---------------------------------------------------------------------------

class TestLvsVerdictResolver:
    def test_defect_direction_old_code_returns_question_mark(self, tmp_path):
        """OLD code: j.get('verdict') or j.get('status') on eda_report_audit
        JSON → None → '?'."""
        d = _make_phase3_dir(tmp_path)
        (d / "lvs.json").write_text(json.dumps(_LVS_JSON_EDA_AUDIT))
        j = frg._safe_json(d / "lvs.json")
        old_verdict = j.get("verdict") or j.get("status") or "?"
        assert old_verdict == "?", (
            f"Precondition: old code returns '?', got {old_verdict!r}"
        )

    def test_fixed_eda_audit_pass_returns_match(self, tmp_path):
        """FIXED: eda_report_audit JSON with terminal_verdict=MATCH → MATCH."""
        d = _make_phase3_dir(tmp_path)
        (d / "lvs.json").write_text(json.dumps(_LVS_JSON_EDA_AUDIT))
        verdict = frg._resolve_lvs_verdict(tmp_path)
        assert verdict in ("MATCH", "PASS"), (
            f"Expected MATCH or PASS for clean LVS, got {verdict!r}"
        )

    def test_fixed_eda_audit_fail_returns_mismatch(self, tmp_path):
        """FIXED: eda_report_audit JSON with terminal_verdict=MISMATCH → MISMATCH."""
        d = _make_phase3_dir(tmp_path)
        (d / "lvs.json").write_text(json.dumps(_LVS_JSON_EDA_AUDIT_FAIL))
        verdict = frg._resolve_lvs_verdict(tmp_path)
        assert verdict in ("MISMATCH", "FAIL"), (
            f"Expected MISMATCH or FAIL, got {verdict!r}"
        )

    def test_fallback_to_lvs_verdict_json(self, tmp_path):
        """When lvs.json absent, fall back to lvs_verdict.json."""
        d = _make_phase3_dir(tmp_path)
        (d / "lvs_verdict.json").write_text(json.dumps(_LVS_VERDICT_JSON))
        verdict = frg._resolve_lvs_verdict(tmp_path)
        assert verdict == "PASS", (
            f"Expected PASS from lvs_verdict.json fallback, got {verdict!r}"
        )

    def test_absent_lvs_report_missing(self, tmp_path):
        """No lvs.json and no lvs_verdict.json → '(report missing)'."""
        _make_phase3_dir(tmp_path)
        verdict = frg._resolve_lvs_verdict(tmp_path)
        assert verdict == "(report missing)", (
            f"Expected '(report missing)', got {verdict!r}"
        )

    def test_verdict_from_json_helper_all_field_variants(self):
        """_verdict_from_json handles all field-name variants."""
        assert frg._verdict_from_json({"verdict": "PASS"}) == "PASS"
        assert frg._verdict_from_json({"status": "FAIL"}) == "FAIL"
        assert frg._verdict_from_json({"result": "WAIVED"}) == "WAIVED"
        assert frg._verdict_from_json({"passed": True}) == "PASS"
        assert frg._verdict_from_json({"passed": False}) == "FAIL"
        assert frg._verdict_from_json(
            {"summary": {"terminal_verdict": "MATCH"}}) == "MATCH"
        assert frg._verdict_from_json({}) is None
        assert frg._verdict_from_json(None) is None
        assert frg._verdict_from_json("not a dict") is None
