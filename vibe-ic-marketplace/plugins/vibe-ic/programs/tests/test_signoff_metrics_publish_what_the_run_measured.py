"""The sign-off summary publishes what the run measured, after it exists (icspm2).

TWO MEASURED FAILURES, ONE PROGRAM
==================================

1. THE SUMMARY WAS WRITTEN BEFORE ITS EVIDENCE. On a FIRST run of `spm` x
   gf180mcuD in a fresh project directory:

       phase3/final/metrics.json          05:12:48   <- the summary
       reports/phase3/drc_router.rpt      05:12:47   <- runner-written, in time
       reports/phase3/drc_signoff.rpt     05:11:47   <- runner-written, in time
       reports/phase3/drc_router.json     05:15:37   <- THREE MINUTES LATER
       reports/phase3/drc_signoff.json    05:15:39   <- THREE MINUTES LATER

   The two `.json` are written by `drc_report_check`, and the only thing that
   runs it is the FLOW's own gate clause inside the completion audit. So the
   summary recorded `route__drc_errors` / `klayout__drc_error__count` as
   NOT_MEASURED ("producers found: none"), the audit created the reports, and
   its own `--check` then reported the record stale. It passed on the
   predecessor lane only because that lane re-used ONE project directory, so a
   previous attempt's reports were already on disk.

2. FIVE AXES THE RUN MEASURED AND NEVER PUBLISHED.
   `every_required_metric_key_has_a_producer` reported

       axis 'drv' / 'antenna' / 'ir' / 'em' / 'equivalence' / 'eco_readiness'
       IS NOT PROVEN BY ANY RUN IN THIS CORPUS

   on a run that had measured every one of them — `SIGNOFF_DRV_CENSUS
   max_fanout violators=0`, `antenna.json net_violations 0 / pin_violations 0`,
   `ir_drop.json worst_ir_uv 1630.0`, `em_current_authority.json jmax_screen
   offender_count 0 / worst_utilization 0.449207`, `lec_post_layout.json
   verdict PROVEN_EQUIVALENT`, `spare_preservation.json survived 6`. Every
   record was on disk under a name the canonical vocabulary did not carry.

   And `_drv` returned `text.count("VIOLATED")` — the whole report's violated
   row count — for EVERY check, so max-slew and max-cap were the same number
   under two names.
"""
import json
import re
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))


STA_RPT = """\
SIGNOFF_CHECK_TYPES_REPORTED recovery removal max_slew min_pulse_width max_capacitance max_fanout
SIGNOFF_DRV_CENSUS_BEGIN the tool's own violator count for every check type requested above
SIGNOFF_DRV_CENSUS max_slew violators=3
SIGNOFF_DRV_CENSUS max_fanout violators=0
SIGNOFF_DRV_CENSUS max_capacitance violators=1
some row VIOLATED
another row VIOLATED
a third row VIOLATED
a fourth row VIOLATED
"""


def _proj(tmp_path, **files):
    p = tmp_path / "proj"
    for rel, payload in files.items():
        f = p / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(payload if isinstance(payload, str)
                     else json.dumps(payload))
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------
# 2a. the DRV census — per check, not one total under three names
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 2b. the five axes — each measured, each refusing honestly
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 1. the ordering — the evidence exists before the summary reads it
# ---------------------------------------------------------------------------
def test_the_runner_emits_the_drc_attribution_reports_before_aggregating(
        tmp_path):
    import phase3_one_shot_runner as r
    fn = getattr(r, "_emit_drc_attribution_reports", None)
    if fn is None:
        pytest.skip("pre-fix tree has no _emit_drc_attribution_reports")
    p = _proj(tmp_path, **{
        "reports/phase3/drc_router.rpt": "[INFO DRT-0199] Number of violations = 0\n",
        "reports/phase3/drc_signoff.rpt": "total DRC errors: 0\n"})
    rows = fn(p)
    drc = [row for row in rows if row.get("program", "drc_report_check")
           == "drc_report_check"]
    assert {row["json"] for row in drc} == {
        "reports/phase3/drc_router.json", "reports/phase3/drc_signoff.json"}
    for row in drc:
        assert row["status"] == "PRODUCED", row
        assert (p / row["json"]).is_file(), row


def test_an_absent_rpt_produces_nothing_and_says_why(tmp_path):
    import phase3_one_shot_runner as r
    fn = getattr(r, "_emit_drc_attribution_reports", None)
    if fn is None:
        pytest.skip("pre-fix tree has no _emit_drc_attribution_reports")
    p = _proj(tmp_path, **{"reports/keep": "x"})
    rows = fn(p)
    assert all(row["status"] == "NOT_APPLICABLE" for row in rows), rows
    assert all(not (p / row["json"]).is_file() for row in rows)
    assert all(row.get("reason") for row in rows)


def test_the_verdict_of_the_spawned_gate_is_recorded_not_discarded(tmp_path):
    """`drc_report_check` is a GATE; this call site wants only the attribution
    record. The status is bound and written down, so the decision is on the
    record rather than inferred from silence."""
    import phase3_one_shot_runner as r
    fn = getattr(r, "_emit_drc_attribution_reports", None)
    if fn is None:
        pytest.skip("pre-fix tree has no _emit_drc_attribution_reports")
    p = _proj(tmp_path, **{
        "reports/phase3/drc_signoff.rpt": "total DRC errors: 0\n"})
    rows = fn(p)
    produced = [row for row in rows if row["status"] == "PRODUCED"]
    assert produced, rows
    for row in produced:
        assert "rc" in row
        assert row["blocking_here"] is False
        assert row["why_advisory_here"]


def test_the_spare_record_is_produced_before_the_summary_reads_it(tmp_path):
    """`design_for_eco__spares__count` brought its OWN ordering dependency, and
    it is the same defect one report over. MEASURED on a run of `spm`:

        phase3/final/metrics.json          06:05:10   <- the summary
        reports/spare_preservation.json    06:07:45   <- TWO AND A HALF MINUTES LATER
        signoff_metrics_aggregate . --check -> rc 1
          "1 key(s) no longer state what this run's reports state:
           design_for_eco__spares__count"

    The only thing that runs the checker is the flow's own gate clause inside
    the completion audit. Its trigger is the artefact it READS, never one of
    its own outputs — a producer triggered by its own product can never run the
    first time."""
    import phase3_one_shot_runner as r
    jobs = getattr(r, "_DRC_ATTRIBUTION_JOBS", None)
    if jobs is None or len(jobs[0]) != 4:
        pytest.skip("pre-fix tree has no multi-program producer table")
    progs = {j[0] for j in jobs}
    assert "spare_cell_coverage_check" in progs, sorted(progs)
    row = next(j for j in jobs if j[0] == "spare_cell_coverage_check")
    assert row[1] == "reports/spare_cell_coverage.json", (
        "the declared artefact, not the conditional preservation record")
    assert row[2] == "phase3/stage3/pnr/spare_cells.json", (
        "the trigger must be the artefact it READS, not an output of its own")
    assert not any(j[1] == "reports/spare_preservation.json" for j in jobs), (
        "no producer here may target the path no step declares")
