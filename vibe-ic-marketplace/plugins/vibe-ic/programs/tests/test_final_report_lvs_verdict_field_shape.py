"""The final report rendered `lvs=?` for every run that HAS an LVS verdict.

THE DEFECT
==========
`final_report_generate._gather_gds` reads a PV artefact's verdict as

    j.get("verdict") or j.get("status") or "?"

but `lvs.json` is written by `eda_report_audit`, whose schema carries the
result under `summary.terminal_verdict` and `passed` — neither `verdict` nor
`status`. Measured on the committed corpus: every `lvs.json` on disk has the
key set `('findings', 'passed', 'program', 'summary')`, e.g.

    benchmark-data/ic/sha256/clean_run_v1461_0223/reports/phase3/lvs.json
      passed                     = False
      summary.terminal_verdict   = "MISMATCH"
      (sibling lvs_verdict.json)  status = "FAIL", finding = "LVS_MISMATCH"

so the sign-off summary a reader treats as the deliverable printed `lvs=?` for
a run whose LVS is a genuine MISMATCH. `?` is not "we could not tell" — the
verdict was on disk, in two files, and the consumer looked for the wrong keys.

THE FIX, AND WHAT IT DELIBERATELY DOES NOT DO
=============================================
This ECHOES the verdict the LVS auditor itself recorded — it reads the fields
that producer writes. It does NOT re-derive a verdict by parsing raw report
text, which is the constraint ORGANIC #399 established for the DRC half of the
same dict ("a summary that contradicts the run it summarises is worse than one
that under-reports"). The `drc_signoff` branch is untouched and pinned below.

Honesty contract, both directions:
  * genuinely absent               -> "(report missing)"
  * present but no known field     -> "?"  (a file that IS on disk must never
                                            be reported as absent)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import final_report_generate as F  # noqa: E402


def _run_dir(tmp_path: Path, *, lvs=None, lvs_verdict=None,
             drc_status=None, drc_extras=None, drc_rpt=None) -> Path:
    (tmp_path / "phase3/stage4/gds").mkdir(parents=True, exist_ok=True)
    (tmp_path / "phase3/stage4/gds/top.gds").write_bytes(b"\x00\x06\x00\x02")
    rep = tmp_path / "reports" / "phase3"
    rep.mkdir(parents=True, exist_ok=True)
    if lvs is not None:
        (rep / "lvs.json").write_text(json.dumps(lvs))
    if lvs_verdict is not None:
        (rep / "lvs_verdict.json").write_text(json.dumps(lvs_verdict))
    if drc_rpt is not None:
        (rep / "drc_signoff.rpt").write_text(drc_rpt)
    if drc_status is not None:
        d = tmp_path / "reports" / "orchestrator"
        d.mkdir(parents=True, exist_ok=True)
        (d / "phase3_one_shot.json").write_text(json.dumps(
            {"steps": [{"name": "drc", "status": drc_status,
                        "extras": drc_extras or {}}]}))
    return tmp_path


def _pv(project: Path):
    g = F._gather_gds(project)
    assert isinstance(g, dict), "no GDS section — fixture is wrong"
    return g["pv"]


# The exact shape eda_report_audit writes (measured on the committed corpus).
_AUDIT_MISMATCH = {"program": "eda_report_audit:lvs", "passed": False,
                   "findings": [{"rule": "LVS_NETLISTS_DO_NOT_MATCH"}],
                   "summary": {"files_found": 1, "categories_found": ["net"],
                               "terminal_verdict": "MISMATCH",
                               "tool_authentic": True}}
_AUDIT_MATCH = {"program": "eda_report_audit:lvs", "passed": True,
                "findings": [],
                "summary": {"files_found": 1, "categories_found": ["net"],
                            "terminal_verdict": "MATCH", "tool_authentic": True}}


# ── the defect ──────────────────────────────────────────────────────────
def test_a_real_lvs_mismatch_is_not_rendered_as_a_question_mark(tmp_path):
    v = _pv(_run_dir(tmp_path, lvs=_AUDIT_MISMATCH))["lvs"]
    assert v != "?", "an LVS MISMATCH on disk rendered as '?'"
    assert "MISMATCH" in v, v


def test_a_real_lvs_match_is_reported(tmp_path):
    v = _pv(_run_dir(tmp_path, lvs=_AUDIT_MATCH))["lvs"]
    assert v != "?" and "MATCH" in v and "MISMATCH" not in v, v


def test_the_passed_boolean_alone_is_enough(tmp_path):
    """A producer that recorded only `passed` still has a stated verdict."""
    assert _pv(_run_dir(tmp_path, lvs={"passed": True}))["lvs"] == "PASS"
    assert _pv(_run_dir(tmp_path, lvs={"passed": False}))["lvs"] == "FAIL"


def test_the_runner_sidecar_is_the_fallback(tmp_path):
    """No lvs.json, but the runner's own `lvs_verdict.json` states FAIL."""
    v = _pv(_run_dir(tmp_path, lvs_verdict={"status": "FAIL",
                                            "finding": "LVS_MISMATCH"}))["lvs"]
    assert v == "FAIL", v


# ── honesty contract ────────────────────────────────────────────────────
def test_a_genuinely_absent_report_still_reads_report_missing(tmp_path):
    assert _pv(_run_dir(tmp_path))["lvs"] == "(report missing)"


def test_a_present_but_unrecognised_report_is_a_question_mark_not_absent(tmp_path):
    """A file that IS on disk must never be reported as absent."""
    assert _pv(_run_dir(tmp_path, lvs={"note": "some future schema"}))["lvs"] == "?"


# ── no-leak: the pre-existing fields still win, in order ─────────────────
def test_an_explicit_verdict_field_still_wins(tmp_path):
    v = _pv(_run_dir(tmp_path, lvs={"verdict": "PASS",
                                    "summary": {"terminal_verdict": "MISMATCH"}}))
    assert v["lvs"] == "PASS", v


def test_an_explicit_status_field_still_wins(tmp_path):
    v = _pv(_run_dir(tmp_path, lvs={"status": "WAIVED", "passed": False}))
    assert v["lvs"] == "WAIVED", v


# ── ORGANIC #399 must be untouched by this change ───────────────────────
def test_the_drc_signoff_echo_is_not_disturbed(tmp_path):
    """The DRC half of the same dict deliberately ECHOES the runner and never
    re-derives from the report. A huge RDB beside a WAIVED run must still read
    WAIVED — pinning that this LVS change did not spill into it."""
    big_rdb = "<report-database>\n" + ("<item/>\n" * 5000) + "</report-database>\n"
    v = _pv(_run_dir(tmp_path, lvs=_AUDIT_MATCH, drc_status="WAIVED",
                     drc_extras={"total_violations": 5000,
                                 "user_routing_violations": 0},
                     drc_rpt=big_rdb))["drc_signoff"]
    assert v.startswith("WAIVED") and "FAIL" not in v, v
