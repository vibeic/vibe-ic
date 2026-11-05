#!/usr/bin/env python3
"""FX_P2 review wave 6 (MINOR, integrity) — the run-status readers treat the
pre-audit phase-2 record as NO verdict.

`design_one_shot_runner._publish_record_before_audit` writes
`reports/orchestrator/phase2_one_shot.json` BEFORE the final audit with
`verdict: "FAIL"` and `final_audit_pending: true`, so a crash during the audit
can never read as a pass; the tail overwrites it. Only the front door's
`_row_verdict` knew the pending flag. `run_status` -- the universal watchdog /
heartbeat the field-agent loop polls -- read the copy's verdict and answered
DONE (FAIL) for the whole audit, skipping its STUCK check; and
`ic_run_status_derive` took it as phase 2's verdict.

Driven through the real `run_status.status` and `ic_run_status_derive`;
the project tree is synthetic. chip-AGNOSTIC.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import run_status as RS               # noqa: E402


def _tree(tmp_path: Path, *, pending: bool, log_age_s: float = 5.0,
          pid=None) -> Path:
    orch = tmp_path / "reports" / "orchestrator"
    orch.mkdir(parents=True)
    rec = {"project": str(tmp_path), "verdict": "FAIL",
           "steps": [{"name": "lint", "status": "PASS"}]}
    if pending:
        rec.update(final_audit_pending=True,
                   verdict_reason="final audit pending: …")
    (orch / "phase2_one_shot.json").write_text(json.dumps(rec))
    log = tmp_path / "phase2" / "stage2" / "synth" / "yosys.log"
    log.parent.mkdir(parents=True)
    log.write_text("still auditing\n")
    old = time.time() - log_age_s
    os.utime(log, (old, old))
    if pid is not None:
        (tmp_path / "run.pid").write_text(str(pid))
    return tmp_path


def test_a_pending_record_with_a_live_runner_is_running(tmp_path):
    p = _tree(tmp_path, pending=True, pid=os.getpid())
    rep = RS.status(p, "phase2")
    assert rep["state"] != "DONE", rep
    assert rep["state"].startswith("RUNNING"), rep


def test_a_pending_record_that_went_silent_is_stuck(tmp_path):
    """The silence check the premature DONE skipped."""
    p = _tree(tmp_path, pending=True, log_age_s=40_000.0, pid=os.getpid())
    rep = RS.status(p, "phase2")
    assert rep["state"] == "STUCK", rep


def test_the_tails_record_is_done_as_before(tmp_path):
    """CONTROL: no pending flag -> the verdict is the run's, DONE."""
    p = _tree(tmp_path, pending=False, pid=os.getpid())
    rep = RS.status(p, "phase2")
    assert rep["state"] == "DONE" and rep["verdict"] == "FAIL", rep
