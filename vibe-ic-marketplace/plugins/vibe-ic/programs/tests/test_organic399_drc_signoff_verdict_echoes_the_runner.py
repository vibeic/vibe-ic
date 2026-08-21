#!/usr/bin/env python3
"""ORGANIC #399 — the final report said "(report missing)" for DRC on runs
where DRC ran.

`_gather_gds` looked up `drc_signoff.json`. Nothing in this tree writes one —
the producer stages a `.rpt`. Measured over every committed run carrying a
runner record: 16 of 16 with a GDS section reported "(report missing)" while
the runner had recorded PASS / FAIL / WAIVED with real violation counts.

THE CONSTRAINT THAT SHAPES THE FIX, and the reason the obvious one was
withdrawn: `step_drc`'s verdict is deliberately NOT the raw item count. The
runner re-tiers to WAIVED when every violation is a std-cell-library layer
rule, and substitutes the Magic count when a re-stream is authoritative. A
prototype that parsed the RDB produced `FAIL (N violations)` on five runs the
runner had recorded WAIVED. A summary that contradicts the run it summarises
is worse than one that under-reports, so this ECHOES and never derives —
pinned by `test_a_waived_run_with_a_huge_rpt_is_not_re_derived_to_FAIL`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from _published_corpus import corpus_root, needs_corpus

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import final_report_generate as F  # noqa: E402


def _run_dir(tmp_path: Path, *, drc_status=None, extras=None,
             sidecar=None, rpt=None) -> Path:
    (tmp_path / "phase3/stage4/gds").mkdir(parents=True, exist_ok=True)
    (tmp_path / "phase3/stage4/gds/top.gds").write_bytes(b"\x00\x06\x00\x02")
    rep = tmp_path / "reports"
    if drc_status is not None:
        d = rep / "orchestrator"
        d.mkdir(parents=True, exist_ok=True)
        (d / "phase3_one_shot.json").write_text(json.dumps(
            {"steps": [{"name": "synth", "status": "PASS"},
                       {"name": "drc", "status": drc_status,
                        "extras": extras or {}}]}))
    if sidecar is not None:
        d = rep / "phase3"
        d.mkdir(parents=True, exist_ok=True)
        (d / "drc_signoff.json").write_text(json.dumps(sidecar))
    if rpt is not None:
        d = rep / "phase3"
        d.mkdir(parents=True, exist_ok=True)
        (d / "drc_signoff.rpt").write_text(rpt)
    return tmp_path


def _verdict(project: Path):
    g = F._gather_gds(project)
    assert isinstance(g, dict), "no GDS section — fixture is wrong"
    return g["pv"]["drc_signoff"]


def test_the_runner_verdict_is_echoed(tmp_path):
    v = _verdict(_run_dir(tmp_path, drc_status="WAIVED", extras={
        "total_violations": 7459, "user_routing_violations": 0,
        "stdcell_library_violations": 7459}))
    assert v.startswith("WAIVED")
    assert "7459" in v and "user_routing_violations=0" in v


def test_the_substance_travels_with_the_verdict(tmp_path):
    """A bare "PASS" tells a reader nothing they can check. The counts the
    runner recorded are what make the verdict reviewable."""
    v = _verdict(_run_dir(tmp_path, drc_status="PASS",
                          extras={"streamout_engine": "klayout"}))
    assert v.startswith("PASS") and "klayout" in v


def test_no_record_and_no_sidecar_still_reads_report_missing(tmp_path):
    """The paired half. "I could not find a verdict" must stay sayable —
    filling it in from nothing is the failure this issue is about, inverted."""
    assert _verdict(_run_dir(tmp_path)) == "(report missing)"


def test_a_sidecar_json_wins_when_one_exists(tmp_path):
    v = _verdict(_run_dir(tmp_path, drc_status="WAIVED",
                          sidecar={"verdict": "PASS_FROM_SIDECAR"}))
    assert v == "PASS_FROM_SIDECAR"


def test_a_waived_run_with_a_huge_rpt_is_not_re_derived_to_FAIL(tmp_path):
    """THE constraint. The withdrawn prototype turned five WAIVED runs into
    `FAIL (N violations, klayout RDB)` by counting RDB items. The runner
    re-tiers to WAIVED when every violation is a std-cell-library rule, so a
    count-derived verdict contradicts the run."""
    big_rdb = "<report-database>\n" + ("<item/>\n" * 5000) + "</report-database>\n"
    v = _verdict(_run_dir(tmp_path, drc_status="WAIVED",
                          extras={"total_violations": 5000,
                                  "user_routing_violations": 0},
                          rpt=big_rdb))
    assert v.startswith("WAIVED"), v
    assert "FAIL" not in v


def test_a_truncated_report_cannot_manufacture_a_PASS(tmp_path):
    """#399(b): a truncated SVRF report whose header declares failures but
    whose body was cut before any FAIL line read as a flat PASS in the
    prototype. Echoing the runner cannot do that — the verdict comes from the
    runner, not from however much of the report survived."""
    truncated = "# tally {'PASS': 7138, 'FAIL': 3}\nrule_a PASS\nrule_b PASS\n"
    v = _verdict(_run_dir(tmp_path, drc_status="FAIL", rpt=truncated))
    assert v.startswith("FAIL"), v


@needs_corpus
def test_no_committed_run_is_contradicted():
    """Corpus sweep: for every committed run the echoed verdict must START
    with the runner's own status. Any re-derivation would show up here.

    WHERE THE RUNS ARE READ FROM (the 2026-08 split). The published runs moved
    to `vibeic/benchmark-data`, so the sweep asks `_published_corpus` for a
    corpus it can actually read — an in-tree `benchmark-data/` that still
    carries cells, or a clone named by `$VIBE_IC_BENCHMARK_DATA`.

    The old guard here was `if not (repo / "benchmark-data").is_dir(): skip`,
    and it stopped being the question at the split: `benchmark-data/` still
    exists in this checkout because it holds the DESIGN INPUTS the flow reads.
    So the guard never fired, the walk found no committed run, and the floor
    below failed with `checked == 0` — a FAILURE claims this repository
    contradicts its own runner, when the truth is only that the runs are not
    here to read. Absent data is "could not look", and the honest rendering of
    that is the skip this mark carries.
    """
    root = corpus_root()
    checked = 0
    for rec in root.rglob("reports/orchestrator/phase3_one_shot.json"):
        proj = rec.parents[2]
        try:
            g = F._gather_gds(proj)
            j = json.loads(rec.read_text())
        except Exception:
            continue
        if not isinstance(g, dict):
            continue
        st = next((s.get("status") for s in (j.get("steps") or [])
                   if isinstance(s, dict) and s.get("name") == "drc"), None)
        if not st:
            continue
        v = g["pv"]["drc_signoff"]
        checked += 1
        assert v == "(report missing)" or v.startswith(str(st)), (proj, st, v)
    assert checked >= 5, f"swept only {checked} runs — too few to mean anything"
