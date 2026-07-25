#!/usr/bin/env python3
"""final_report_generate: the DRC/LVS/ERC sign-off line of final_summary.md.

Two defect directions are pinned here, and EVERY assertion is written so
that it FAILS when the corresponding defect is present.

DEFECT A — producer/consumer mismatch (the original capture claim).
  _gather_gds looked up `<kind>.json` only, while phase3_one_shot_runner
  writes `reports/phase3/drc_signoff.rpt`, so a real DRC sign-off rendered
  as "(report missing)".  The `TestOriginalDefect*` tests below stage a
  report the producer actually writes and assert a real verdict comes
  back; they fail against the pre-fix consumer.

DEFECT B — a FABRICATED sign-off (what the first attempt at the fix
  introduced, and what these tests exist to keep out).  Deciding
  cleanliness with `text.count("<item>") == 0` reports PASS for EVERY
  report that is not KLayout RDB XML.  `drc_signoff.rpt` is a canonical
  alias staged by step_canonicalize_artefacts from THREE producers:

    # Tool: svrfdrc   plain text, per-rule `FAIL <rule>` — the
                      commercial-PDK sign-off, staged with force=True
                      (HIGHEST authority)
    # Tool: klayout   RDB XML, one <item> per violation
    # Tool: openroad  plain text detailed_route projection (router
                      self-check, NOT a foundry sign-off)

  so an `<item>`-count resolver signs off a foundry report with firing
  rules, an OpenROAD report that says "DRC clean: NO", a truncated RDB,
  a header-only report and a zero-byte report — all as "PASS".
  Every `TestNeverFabricates*` test below fails against that resolver.

The consumer under test is `_gather_gds` itself (the actual producer of
the `drc_signoff=… lvs=… erc=…` line), not only the helpers, so the
end-to-end claim is asserted rather than assumed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import final_report_generate as frg  # noqa: E402
import _path_layout as _pl  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture bodies — faithful miniatures of what each producer really writes
# ---------------------------------------------------------------------------

_KLAYOUT_RDB_CLEAN = """\
<?xml version="1.0" encoding="utf-8"?>
<report-database>
 <description>DRC runset</description>
 <top-cell>dut</top-cell>
 <items>
 </items>
</report-database>
"""

_KLAYOUT_RDB_DIRTY = """\
<?xml version="1.0" encoding="utf-8"?>
<report-database>
 <description>DRC runset</description>
 <top-cell>dut</top-cell>
 <items>
  <item><category>li.1</category><description>min space</description></item>
  <item><category>li.1</category><description>min space</description></item>
  <item><category>li.3</category><description>min width</description></item>
 </items>
</report-database>
"""

# A half-written RDB. phase3_one_shot_runner's own v1.3.47 comment: "a
# stall/ceiling kill must NOT be scored from a partial or stale report (a
# half-written RDB could parse as 0 violations = false DRC-clean)".
_KLAYOUT_RDB_TRUNCATED = """\
<?xml version="1.0" encoding="utf-8"?>
<report-database>
 <description>DRC runset</description>
 <top-cell>dut</top-cell>
 <items>
"""

# Shape proven by phase3_one_shot_runner._parse_svrf_tally and the existing
# programs/tests/test_svrf_native_drc.py fixture.
_SVRF_DIRTY = """\
# SVRF-native DRC via KLayout KLayout 0.30.9
# deck=/x/Calibre_commercial_pdk_DRC_D4.20.rule  layout=/x/dut.gds  dbu=0.001
# 224 layers, 17531 derivations, 7394 rules  |  {'PASS': 7138, 'FAIL': 3}

PASS  SPACE.M1.1         EXTERNAL M1 < 0.23 [metrics=euclidian] -> 0
FAIL  WIDTH.M2.1         INTERNAL M2 < 0.28 [metrics=euclidian] -> 5
FAIL  ENC.CO.1           ENCLOSURE CO M1 < 0.06 [metrics=euclidian] -> 3
FAIL  M1.S.2             EXTERNAL L72974 < 0.6 [metrics=euclidian] -> 176
SKIP  ANT.M3             COPY antenna -> antenna routed to its own checker

# tally: {'PASS': 7138, 'FAIL': 3, 'SKIP': 1}
"""

_SVRF_CLEAN = """\
# SVRF-native DRC via KLayout KLayout 0.30.9
# 224 layers, 17531 derivations, 7394 rules  |  {'PASS': 7394}

PASS  SPACE.M1.1         EXTERNAL M1 < 0.23 [metrics=euclidian] -> 0
PASS  WIDTH.M2.1         INTERNAL M2 < 0.28 [metrics=euclidian] -> 0

# tally: {'PASS': 7394}
"""

_OPENROAD_DIRTY = """\
# OpenROAD detailed_route DRC summary -- emitted by
# phase3_one_shot_runner (canonicalize_artefacts step).
# Tool: openroad detailed_route (drt)
#
openroad / drt-pass: detailed_route invoked
violation report: 47
violation count summary: 47 violation(s) found
drc source: final [INFO DRT-0199] count
DRC clean: NO
tool: openroad
"""

_OPENROAD_CLEAN = """\
# OpenROAD detailed_route DRC summary -- emitted by
# phase3_one_shot_runner (canonicalize_artefacts step).
# Tool: openroad detailed_route (drt)
#
openroad / drt-pass: detailed_route invoked
violation report: 0
violation count summary: 0 violation(s) found
drc source: final [INFO DRT-0199] count
DRC clean: YES
tool: openroad
"""

_LVS_JSON_EDA_AUDIT_PASS = {
    "program": "eda_report_audit:lvs", "passed": True, "findings": [],
    "summary": {"files_found": 2, "terminal_verdict": "MATCH",
                "tool_authentic": True},
}
_LVS_JSON_EDA_AUDIT_FAIL = {
    "program": "eda_report_audit:lvs", "passed": False,
    "findings": ["mismatch"],
    "summary": {"files_found": 2, "terminal_verdict": "MISMATCH",
                "tool_authentic": True},
}
_LVS_VERDICT_JSON = {
    "status": "PASS", "result": "PASS", "finding": "LVS_MATCH",
    "generated_by": "phase3_one_shot_runner:_run_extraction_lvs (#477)",
}


def _canon_header(tool: str, src: str = "phase3/reports/x.rpt") -> str:
    """Exactly the header step_canonicalize_artefacts prepends when it
    stages a producer's report to reports/phase3/drc_signoff.rpt."""
    return ("# Sign-off DRC report (ORGANIC-20260531 Step 31 alias).\n"
            f"# Source: {src}\n"
            f"# Tool: {tool}\n"
            "#\n")


def _project(tmp_path: Path) -> Path:
    """A project skeleton _gather_gds will actually walk into: it returns
    None unless a *.gds exists in the canonical gds dir."""
    gds = _pl.gds_dir(tmp_path)
    gds.mkdir(parents=True, exist_ok=True)
    (gds / "dut.gds").write_bytes(b"\x00\x06\x00\x02\x00\x07")
    (tmp_path / "reports" / "phase3").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _stage_drc_rpt(project: Path, body: str) -> None:
    (project / "reports" / "phase3" / "drc_signoff.rpt").write_text(body)


def _pv(project: Path) -> dict:
    g = frg._gather_gds(project)
    assert g is not None, "_gather_gds must find the staged GDS"
    return g["pv"]


# ---------------------------------------------------------------------------
# DEFECT A — the original claim, asserted at the real consumer.
# Each of these FAILS against the pre-fix consumer (which read only
# drc_signoff.json and rendered "(report missing)").
# ---------------------------------------------------------------------------

class TestOriginalDefectReportPathMismatch:
    def test_klayout_clean_rdb_is_reported_pass_not_missing(self, tmp_path):
        p = _project(tmp_path)
        _stage_drc_rpt(p, _canon_header("klayout") + _KLAYOUT_RDB_CLEAN)
        assert _pv(p)["drc_signoff"] == "PASS"

    def test_klayout_dirty_rdb_is_reported_fail_with_count(self, tmp_path):
        p = _project(tmp_path)
        _stage_drc_rpt(p, _canon_header("klayout") + _KLAYOUT_RDB_DIRTY)
        v = _pv(p)["drc_signoff"]
        assert v.startswith("FAIL") and "3" in v, v

    def test_svrf_clean_report_is_reported_pass_not_missing(self, tmp_path):
        p = _project(tmp_path)
        _stage_drc_rpt(p, _canon_header("svrfdrc") + _SVRF_CLEAN)
        assert _pv(p)["drc_signoff"] == "PASS"

    def test_lvs_eda_report_audit_schema_resolves_not_question_mark(
            self, tmp_path):
        p = _project(tmp_path)
        (p / "reports" / "phase3" / "lvs.json").write_text(
            json.dumps(_LVS_JSON_EDA_AUDIT_PASS))
        assert _pv(p)["lvs"] == "MATCH"

    def test_lvs_eda_report_audit_mismatch_resolves(self, tmp_path):
        p = _project(tmp_path)
        (p / "reports" / "phase3" / "lvs.json").write_text(
            json.dumps(_LVS_JSON_EDA_AUDIT_FAIL))
        assert _pv(p)["lvs"] == "MISMATCH"

    def test_lvs_verdict_json_fallback_resolves(self, tmp_path):
        p = _project(tmp_path)
        (p / "reports" / "phase3" / "lvs_verdict.json").write_text(
            json.dumps(_LVS_VERDICT_JSON))
        assert _pv(p)["lvs"] == "PASS"


# ---------------------------------------------------------------------------
# DEFECT B — the fabricated sign-off. Every test here FAILS against a
# resolver that decides cleanliness by counting "<item>".
# ---------------------------------------------------------------------------

class TestNeverFabricatesACleanSignoff:
    def test_svrf_report_with_firing_foundry_rules_is_not_pass(self, tmp_path):
        """The decisive case: the commercial-PDK sign-off is PLAIN TEXT and
        contains zero '<item>'. It must read FAIL, never PASS."""
        p = _project(tmp_path)
        _stage_drc_rpt(p, _canon_header("svrfdrc",
                                        "phase3/reports/drc_svrf_calibre.rpt")
                       + _SVRF_DIRTY)
        v = _pv(p)["drc_signoff"]
        assert v != "PASS", "a foundry report with 3 firing rules read PASS"
        assert v.startswith("FAIL"), v
        assert "3" in v, v

    def test_openroad_projection_with_47_violations_is_not_pass(self, tmp_path):
        p = _project(tmp_path)
        _stage_drc_rpt(p, _canon_header("openroad",
                                        "phase3/reports/routed.drc.rpt")
                       + _OPENROAD_DIRTY)
        v = _pv(p)["drc_signoff"]
        assert v != "PASS", "'DRC clean: NO' with 47 violations read PASS"
        assert v.startswith("FAIL") and "47" in v, v

    def test_clean_openroad_projection_is_not_a_signoff_pass(self, tmp_path):
        """A router self-check is not a foundry sign-off even when clean."""
        p = _project(tmp_path)
        _stage_drc_rpt(p, _canon_header("openroad",
                                        "phase3/reports/routed.drc.rpt")
                       + _OPENROAD_CLEAN)
        v = _pv(p)["drc_signoff"]
        assert v != "PASS", "a router projection was signed off as clean DRC"
        assert v.startswith(frg._DRC_UNKNOWN_PREFIX), v

    def test_zero_byte_report_is_not_pass(self, tmp_path):
        p = _project(tmp_path)
        _stage_drc_rpt(p, "")
        v = _pv(p)["drc_signoff"]
        assert v != "PASS", "a zero-byte report read PASS"
        assert v.startswith(frg._DRC_UNKNOWN_PREFIX), v

    def test_header_only_report_is_not_pass(self, tmp_path):
        """The canonicalizer wrote its header, then the copy died. The
        reason must say the body is not an RDB at all — that is a
        different thing for a reviewer to chase than a truncated one."""
        p = _project(tmp_path)
        _stage_drc_rpt(p, _canon_header("klayout"))
        v = _pv(p)["drc_signoff"]
        assert v != "PASS", "a header-only report read PASS"
        assert v.startswith(frg._DRC_UNKNOWN_PREFIX), v
        assert "not a KLayout RDB XML document" in v, v

    def test_truncated_klayout_rdb_is_not_pass(self, tmp_path):
        """v1.3.47 invariant: a half-written RDB parses as 0 violations.
        The reason must name TRUNCATION specifically: the document opened
        as a real RDB, so 'not an RDB' would misdirect the reviewer."""
        p = _project(tmp_path)
        _stage_drc_rpt(p, _canon_header("klayout") + _KLAYOUT_RDB_TRUNCATED)
        v = _pv(p)["drc_signoff"]
        assert v != "PASS", "a truncated RDB read PASS"
        assert v.startswith(frg._DRC_UNKNOWN_PREFIX), v
        assert "truncated" in v, v

    def test_unidentifiable_report_is_not_pass(self, tmp_path):
        p = _project(tmp_path)
        _stage_drc_rpt(p, "some future tool wrote this and we do not know it\n")
        v = _pv(p)["drc_signoff"]
        assert v != "PASS", "an unidentified report format read PASS"
        assert v.startswith(frg._DRC_UNKNOWN_PREFIX), v

    def test_svrf_rpt_outranks_a_clean_json_sidecar(self, tmp_path):
        """step_canonicalize_artefacts stages the svrfdrc report with
        force=True so a lower-authority artefact can never mask the
        commercial-PDK verdict. The consumer must honour the same order."""
        p = _project(tmp_path)
        _stage_drc_rpt(p, _canon_header("svrfdrc",
                                        "phase3/reports/drc_svrf_calibre.rpt")
                       + _SVRF_DIRTY)
        (p / "reports" / "phase3" / "drc_signoff.json").write_text(
            json.dumps({"verdict": "PASS", "violations": 0}))
        v = _pv(p)["drc_signoff"]
        assert v.startswith("FAIL"), (
            f"a clean sidecar masked a firing commercial-PDK sign-off: {v!r}")

    def test_klayout_item_count_ignores_the_items_container(self, tmp_path):
        """`<items>` must not be counted as a violation `<item>`."""
        p = _project(tmp_path)
        _stage_drc_rpt(p, _canon_header("klayout") + _KLAYOUT_RDB_CLEAN)
        assert _pv(p)["drc_signoff"] == "PASS"


# ---------------------------------------------------------------------------
# Absent-vs-present: a file ON DISK is never reported as missing, and a
# genuinely absent one is never reported as anything else.
# ---------------------------------------------------------------------------

class TestAbsentVersusPresent:
    def test_no_drc_artefact_at_all_is_report_missing(self, tmp_path):
        p = _project(tmp_path)
        assert _pv(p)["drc_signoff"] == "(report missing)"

    def test_no_lvs_artefact_at_all_is_report_missing(self, tmp_path):
        p = _project(tmp_path)
        assert _pv(p)["lvs"] == "(report missing)"

    def test_no_erc_artefact_at_all_is_report_missing(self, tmp_path):
        p = _project(tmp_path)
        assert _pv(p)["erc"] == "(report missing)"

    def test_present_but_unrecognised_lvs_json_is_not_reported_missing(
            self, tmp_path):
        """Overreach guard: lvs.json IS on disk; reporting it as absent
        sends a reviewer looking for a file that is right there."""
        p = _project(tmp_path)
        (p / "reports" / "phase3" / "lvs.json").write_text(
            json.dumps({"program": "eda_report_audit:lvs", "findings": []}))
        assert _pv(p)["lvs"] == "?"

    def test_present_but_unrecognised_erc_json_is_not_reported_missing(
            self, tmp_path):
        p = _project(tmp_path)
        (p / "reports" / "phase3" / "erc.json").write_text(
            json.dumps({"program": "erc", "floating_nets": 0}))
        assert _pv(p)["erc"] == "?"

    def test_erc_verdict_field_still_resolves(self, tmp_path):
        p = _project(tmp_path)
        (p / "reports" / "phase3" / "erc.json").write_text(
            json.dumps({"verdict": "PASS"}))
        assert _pv(p)["erc"] == "PASS"


# ---------------------------------------------------------------------------
# Producer identification — the discriminator the whole resolver rests on.
# ---------------------------------------------------------------------------

class TestProducerIdentification:
    @pytest.mark.parametrize("tool,expect", [
        ("svrfdrc", "svrfdrc"),
        ("klayout", "klayout"),
        ("magic", "magic"),
        ("openroad", "openroad"),
    ])
    def test_canonicalizer_tool_header_wins(self, tool, expect):
        assert frg._drc_report_producer(_canon_header(tool)) == expect

    def test_unknown_tool_header_is_unknown(self):
        assert frg._drc_report_producer(
            _canon_header("some_future_drc_tool")) == "unknown"

    def test_svrf_signature_identifies_without_header(self):
        assert frg._drc_report_producer(_SVRF_DIRTY) == "svrfdrc"

    def test_rdb_signature_identifies_without_header(self):
        assert frg._drc_report_producer(_KLAYOUT_RDB_CLEAN) == "klayout"

    def test_openroad_signature_identifies_from_its_own_body(self):
        # The routed_drc body carries its own `# Tool: openroad
        # detailed_route (drt)` line.
        assert frg._drc_report_producer(_OPENROAD_DIRTY) == "openroad"

    def test_no_signature_at_all_is_unknown(self):
        assert frg._drc_report_producer("hello\nworld\n") == "unknown"


# ---------------------------------------------------------------------------
# Per-producer grammar, exercised directly.
# ---------------------------------------------------------------------------

class TestPerProducerGrammar:
    def test_svrf_clean_requires_at_least_one_graded_rule(self):
        assert frg._drc_verdict_from_svrf(_SVRF_CLEAN) == "PASS"
        # header/tally lines only → nothing was graded → not a verdict
        v = frg._drc_verdict_from_svrf(
            "# SVRF-native DRC via KLayout\n# tally: {}\n")
        assert v.startswith(frg._DRC_UNKNOWN_PREFIX), v

    def test_svrf_dirty_names_the_firing_rules(self):
        v = frg._drc_verdict_from_svrf(_SVRF_DIRTY)
        assert v.startswith("FAIL") and "WIDTH.M2.1" in v, v

    def test_klayout_body_that_is_not_rdb_is_unknown(self):
        v = frg._drc_verdict_from_klayout_rdb("FAIL WIDTH.M2.1 -> 5\n")
        assert v.startswith(frg._DRC_UNKNOWN_PREFIX), v
        assert "not a KLayout RDB XML document" in v, v

    def test_rdb_open_and_truncation_are_distinct_diagnoses(self):
        """The two UNKNOWN branches must stay separately observable —
        collapsing them hides which one fired from the reviewer."""
        not_rdb = frg._drc_verdict_from_klayout_rdb("no xml here\n")
        truncated = frg._drc_verdict_from_klayout_rdb(
            _KLAYOUT_RDB_TRUNCATED)
        assert "not a KLayout RDB XML document" in not_rdb, not_rdb
        assert "truncated" in truncated, truncated
        assert not_rdb != truncated

    def test_openroad_without_a_count_is_unknown(self):
        v = frg._drc_verdict_from_openroad(
            "openroad / drt-pass: detailed_route invoked\n"
            "drc source: final [INFO DRT-0199] count (ABSENT — no "
            "detailed_route count in log)\n"
            "violation report: 0\n"
            "DRC clean: NO\n")
        assert v.startswith(frg._DRC_UNKNOWN_PREFIX), v

    def test_verdict_from_json_field_variants(self):
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
