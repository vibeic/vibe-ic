#!/usr/bin/env python3
"""Smoke tests for l24_signoff_evidence_backed_check.py — batch-8 / layergate-8.

NEGATIVE CONTROL IS THE POINT OF THIS FILE. Every rule is asserted in BOTH
directions: a deliberately-gutted layer must FAIL, and the well-formed
counterpart of the SAME layer must PASS. A test that cannot fail proves
nothing.

All fixtures are SYNTHESIZED neutral data — invented block names, invented
report text, invented gate names. No real design's files are copied and no
real design/PDK/vendor token appears anywhere in this file.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent
        / "l24_signoff_evidence_backed_check.py")

_FAIL = 1
_PASS = 0
_SKIP = 2


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _make(tmp_path, l24=None, reports=None, extra_docs=None) -> Path:
    """Synthesize a neutral project tree."""
    proj = tmp_path / "synthetic_project"
    (proj / "phase1" / "generated_docs").mkdir(parents=True, exist_ok=True)
    if l24 is not None:
        (proj / "phase1" / "generated_docs" / "L24_SIGNOFF.json").write_text(
            json.dumps(l24, indent=2))
    for rel, text in (reports or {}).items():
        p = proj / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    for name, doc in (extra_docs or {}).items():
        (proj / "phase1" / "generated_docs" / name).write_text(json.dumps(doc))
    return proj


# --- synthesized, neutral -------------------------------------------------
_SYNTH_CLASS = "synthetic_block_class_alpha"

_GOOD_REPORTS = {
    "reports/geometry_rule_summary.rpt":
        "synthetic geometry rule run\ntotal violations: 0\n",
    "reports/netlist_compare_summary.rpt":
        "synthetic netlist compare\ncompare result mismatches = 0\n",
    "reports/checklist_density.rpt":
        "synthetic checklist row\nfill_uniformity margin 3.10 pct\n",
}


def _good_l24() -> dict:
    """A well-formed L24: every verdict bound to a path + a read-back value."""
    return {
        "doc_id": "L24",
        "doc_name": "L24_SIGNOFF",
        "applicability": "APPLICABLE",
        "ic_class": _SYNTH_CLASS,
        "fields": {
            "geometry_status": "CLEAN",
            "netlist_status": "MATCHED",
            "tapeout_gates": [
                {"name": "fill_uniformity", "status": "MET"},
            ],
        },
        "extraction_status": "EXTRACTED",
        "extraction_evidence": {
            "reports/geometry_rule_summary.rpt": [
                {"literal": "total violations: 0",
                 "label": "geometry_status read-back"}],
            "reports/netlist_compare_summary.rpt": [
                {"literal": "compare result mismatches = 0",
                 "label": "netlist_status read-back"}],
            "reports/checklist_density.rpt": [
                {"literal": "fill_uniformity margin 3.10 pct",
                 "label": "fill_uniformity gate read-back"}],
        },
    }


def _inert_l24() -> dict:
    """The shape 24/24 sampled real Phase-1 runs actually emit."""
    return {
        "doc_id": "L24",
        "doc_name": "L24_SIGNOFF",
        "applicability": "APPLICABLE",
        "ic_class": _SYNTH_CLASS,
        "fields": {
            "geometry_status": None,
            "netlist_status": None,
            "tapeout_gates": [],
        },
        "extraction_status": "NOT_YET_EXTRACTED",
        "extraction_evidence": {},
    }


# ===========================================================================
# POSITIVE DIRECTION — the well-formed layer must PASS
# ===========================================================================
class TestWellFormedPasses:
    def test_fully_evidenced_layer_passes(self, tmp_path):
        proj = _make(tmp_path, l24=_good_l24(), reports=_GOOD_REPORTS)
        r = _run(proj)
        assert r.returncode == _PASS, r.stdout + r.stderr
        assert "[PASS]" in r.stdout

    def test_every_verdict_is_individually_verified(self, tmp_path):
        """PASS must not come from one lucky match — all three subjects
        (two status fields + one checklist row) are reported."""
        proj = _make(tmp_path, l24=_good_l24(), reports=_GOOD_REPORTS)
        r = _run(proj)
        assert r.returncode == _PASS
        assert "3 sign-off verdict(s)" in r.stdout


# ===========================================================================
# NEGATIVE CONTROL — each gutted variant of the SAME layer must FAIL
# ===========================================================================
class TestGuttedLayerFails:
    def test_verdict_asserted_with_no_evidence_at_all(self, tmp_path):
        """The exact false-certificate shape: drc-style status='PASS' with
        nothing behind it."""
        doc = _good_l24()
        doc["extraction_evidence"] = {}
        proj = _make(tmp_path, l24=doc, reports=_GOOD_REPORTS)
        r = _run(proj)
        assert r.returncode == _FAIL, r.stdout
        assert "NO evidence path" in r.stdout
        assert "false-certificate" in r.stdout

    def test_evidence_path_does_not_resolve(self, tmp_path):
        doc = _good_l24()
        doc["extraction_evidence"] = {
            "reports/geometry_rule_summary.rpt": [
                {"literal": "total violations: 0",
                 "label": "geometry_status read-back"}],
            "reports/netlist_compare_summary.rpt": [
                {"literal": "compare result mismatches = 0",
                 "label": "netlist_status read-back"}],
            "reports/checklist_density.rpt": [
                {"literal": "fill_uniformity margin 3.10 pct",
                 "label": "fill_uniformity gate read-back"}],
        }
        # gut it: the geometry report is simply not in the project
        reports = dict(_GOOD_REPORTS)
        reports.pop("reports/geometry_rule_summary.rpt")
        proj = _make(tmp_path, l24=doc, reports=reports)
        r = _run(proj)
        assert r.returncode == _FAIL, r.stdout
        assert "does not resolve" in r.stdout or "NO evidence path" in r.stdout

    def test_evidence_path_with_no_readback_value(self, tmp_path):
        """'I looked at the report' is not evidence of WHAT was read."""
        doc = _good_l24()
        doc["extraction_evidence"]["reports/geometry_rule_summary.rpt"] = [
            {"label": "geometry_status read-back"}]  # literal removed
        proj = _make(tmp_path, l24=doc, reports=_GOOD_REPORTS)
        r = _run(proj)
        assert r.returncode == _FAIL, r.stdout
        assert "no read-back value" in r.stdout

    def test_readback_value_not_present_in_the_cited_file(self, tmp_path):
        doc = _good_l24()
        doc["extraction_evidence"]["reports/geometry_rule_summary.rpt"] = [
            {"literal": "total violations: 7",
             "label": "geometry_status read-back"}]
        proj = _make(tmp_path, l24=doc, reports=_GOOD_REPORTS)
        r = _run(proj)
        assert r.returncode == _FAIL, r.stdout
        assert "does not occur in the file" in r.stdout

    def test_evidence_bound_to_a_different_subject_does_not_count(self, tmp_path):
        """Evidence proving one gate is not evidence for another — the
        'a token appears somewhere' fallacy, scoped to one layer."""
        doc = _good_l24()
        # keep only the netlist evidence; geometry + checklist now unbacked
        doc["extraction_evidence"] = {
            "reports/netlist_compare_summary.rpt": [
                {"literal": "compare result mismatches = 0",
                 "label": "netlist_status read-back"}],
        }
        proj = _make(tmp_path, l24=doc, reports=_GOOD_REPORTS)
        r = _run(proj)
        assert r.returncode == _FAIL, r.stdout
        assert "geometry" in r.stdout

    def test_checklist_row_verdict_needs_its_own_evidence(self, tmp_path):
        doc = _good_l24()
        doc["extraction_evidence"].pop("reports/checklist_density.rpt")
        proj = _make(tmp_path, l24=doc, reports=_GOOD_REPORTS)
        r = _run(proj)
        assert r.returncode == _FAIL, r.stdout
        assert "fill_uniformity" in r.stdout

    def test_certificate_from_a_layer_that_extracted_nothing(self, tmp_path):
        doc = _good_l24()
        doc["extraction_status"] = "NOT_YET_EXTRACTED"
        proj = _make(tmp_path, l24=doc, reports=_GOOD_REPORTS)
        r = _run(proj)
        assert r.returncode == _FAIL, r.stdout
        assert "cannot certify anything" in r.stdout

    def test_novel_verdict_word_is_not_whitelisted_through(self, tmp_path):
        """The gate enumerates only the ABSENCE of information, never the
        positive verdicts — so an invented verdict word still needs proof."""
        doc = _good_l24()
        doc["fields"]["geometry_status"] = "SIGNED_OFF_BY_REVIEW_BOARD"
        doc["extraction_evidence"].pop("reports/geometry_rule_summary.rpt")
        proj = _make(tmp_path, l24=doc, reports=_GOOD_REPORTS)
        r = _run(proj)
        assert r.returncode == _FAIL, r.stdout
        assert "NO evidence path" in r.stdout

    def test_evidence_outside_the_project_is_refused(self, tmp_path):
        outside = tmp_path / "outside_the_run.rpt"
        outside.write_text("total violations: 0\n")
        doc = _good_l24()
        doc["extraction_evidence"][str(outside)] = doc[
            "extraction_evidence"].pop("reports/geometry_rule_summary.rpt")
        doc["extraction_evidence"][str(outside)][0]["label"] = \
            "geometry_status read-back"
        reports = dict(_GOOD_REPORTS)
        reports.pop("reports/geometry_rule_summary.rpt")
        proj = _make(tmp_path, l24=doc, reports=reports)
        r = _run(proj)
        assert r.returncode == _FAIL, r.stdout

    def test_na_stub_without_rationale_fails(self, tmp_path):
        proj = _make(tmp_path, l24={
            "doc_id": "L24", "doc_name": "L24_SIGNOFF",
            "applicability": "N/A", "ic_class": _SYNTH_CLASS,
            "extraction_evidence": {},
        })
        r = _run(proj)
        assert r.returncode == _FAIL, r.stdout
        assert "rationale" in r.stdout


# ===========================================================================
# The gate must be SILENT on the state real runs are actually in.
# This is the no-false-positive direction, asserted as a test rather than
# only observed in the fleet sweep.
# ===========================================================================
class TestRealRunShapeIsSilent:
    def test_inert_layer_skips(self, tmp_path):
        proj = _make(tmp_path, l24=_inert_l24())
        r = _run(proj)
        assert r.returncode == _SKIP, r.stdout
        assert "assert no sign-off verdict" in r.stdout

    def test_missing_layer_skips(self, tmp_path):
        proj = _make(tmp_path)
        r = _run(proj)
        assert r.returncode == _SKIP

    def test_na_stub_with_rationale_skips(self, tmp_path):
        proj = _make(tmp_path, l24={
            "doc_id": "L24", "doc_name": "L24_SIGNOFF",
            "applicability": "N/A", "ic_class": _SYNTH_CLASS,
            "rationale": "Sign-off status is per-implementation, not "
                         "protocol-level",
            "extraction_evidence": {},
        })
        r = _run(proj)
        assert r.returncode == _SKIP, r.stdout

    def test_pending_and_tbd_statuses_are_not_claims(self, tmp_path):
        doc = _inert_l24()
        doc["fields"]["geometry_status"] = "PENDING"
        doc["fields"]["netlist_status"] = "TBD"
        proj = _make(tmp_path, l24=doc)
        r = _run(proj)
        assert r.returncode == _SKIP, r.stdout

    def test_nonexistent_project_dir_skips(self, tmp_path):
        r = _run(tmp_path / "no_such_dir")
        assert r.returncode == _SKIP


# ===========================================================================
# Both-directions assertion on ONE layer, in one test, so the negative
# control can never silently rot into an always-failing or always-passing
# check.
# ===========================================================================
def test_negative_control_both_directions_on_the_same_layer(tmp_path):
    good = _make(tmp_path / "good", l24=_good_l24(), reports=_GOOD_REPORTS)
    gutted_doc = _good_l24()
    gutted_doc["extraction_evidence"] = {}
    gutted = _make(tmp_path / "gutted", l24=gutted_doc, reports=_GOOD_REPORTS)

    r_good = _run(good)
    r_gutted = _run(gutted)

    assert r_good.returncode == _PASS, f"well-formed must PASS: {r_good.stdout}"
    assert r_gutted.returncode == _FAIL, \
        f"gutted must FAIL: {r_gutted.stdout}"
    assert r_good.returncode != r_gutted.returncode
