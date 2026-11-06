"""A completed zero DRC route has a real, receipt-bound empty output."""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

import eda_report_audit as audit


REPORT = "phase3/stage3/pnr/routed_router.drc.rpt"
LOG = ("[INFO DRT-0195] Start detail routing.\n"
       "[INFO DRT-0199] Number of violations = 0.\n"
       "[INFO DRT-0198] Complete detail routing.\n")
















def _dirty_router_report(count: int = 3) -> str:
    """A populated router DRC report (OpenROAD grammar, >2 KiB anti-stub)."""
    head = ("# OpenROAD detailed_route DRC summary\n"
            "# Tool: openroad detailed_route (drt)\n"
            f"violation report: {count}\ntotal violations: {count}\n"
            "categories: spacing width density antenna via enclosure\n")
    return head + f"    Completing 100% with {count} violations.\n" * 70


@pytest.mark.parametrize("order", ["sorted", "reverse"])
def test_an_identical_iteration_copy_cannot_evict_the_final_report(
        tmp_path, monkeypatch, order):
    """Review wave 57: the iteration exclusion ran AFTER the duplicate
    collapse, so a byte-identical last-rung copy walked first claimed the
    content key, the final report was dropped as its duplicate, and then the
    copy was deleted too -- 'No DRC report found' for a report that exists."""
    pnr = tmp_path / "phase3/stage3/pnr"
    pnr.mkdir(parents=True)
    body = _dirty_router_report()
    (pnr / "routed_router.drc.rpt").write_text(body)
    (pnr / "routed_router.drc.iter1.rpt").write_text(body)
    walk = pathlib.Path.rglob
    monkeypatch.setattr(pathlib.Path, "rglob", lambda self, pat: iter(sorted(
        walk(self, pat), key=str, reverse=order == "reverse")))
    subjects = sorted([pnr / "routed_router.drc.rpt",
                       pnr / "routed_router.drc.iter1.rpt"],
                      key=str, reverse=order == "reverse")
    with audit.named_subjects(subjects):
        result = audit._check_drc(tmp_path)
    assert result.summary["files_found"] == 1
    assert result.subject_files == [str(pnr / "routed_router.drc.rpt")]
    assert result.summary["ignored_intermediate_reports"] == [
        "phase3/stage3/pnr/routed_router.drc.iter1.rpt"]
    assert not any(f.rule == "DRC_REPORT_EXISTS" for f in result.findings)


def test_an_iteration_copy_votes_when_the_final_report_is_absent(tmp_path):
    """Review wave 57: the copies were dropped by name alone, so with no
    final report the only router-written evidence (here carrying violations)
    was discarded and a clean projection passed the gate (base rc 1 ->
    branch rc 0). A copy defers only to a final report that is discovered."""
    pnr = tmp_path / "phase3/stage3/pnr"
    pnr.mkdir(parents=True)
    (pnr / "routed_router.drc.iter0.rpt").write_text(_dirty_router_report())
    sibling = tmp_path / "reports/phase3/drc_router.rpt"
    sibling.parent.mkdir(parents=True)
    sibling.write_text(_dirty_router_report(0))
    out = tmp_path / "broad_audit.json"
    cmd = [sys.executable, str(Path(audit.__file__)), str(tmp_path),
           "--mode", "drc", "--under", "phase3/stage3/pnr",
           "--under", "reports/phase3/drc_router.rpt",
           "--subject", "phase3/stage3/pnr/routed_router.drc.iter0.rpt",
           "--subject", "reports/phase3/drc_router.rpt", "--json", str(out)]
    run = subprocess.run(cmd, capture_output=True, text=True)
    result = json.loads(out.read_text())
    assert run.returncode == 1, result
    assert result["passed"] is False
    assert result["summary"]["ignored_intermediate_reports"] == []
    # The iteration copy and the projection both vote.
    assert result["summary"]["files_found"] == 2
