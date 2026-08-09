"""Routing published on an illegal placement must be named, not swallowed.

The post-route DRV repair catches `detailed_placement`'s DPL-0701
non-convergence, prints a marker, then rips up thousands of nets and re-routes
on a placement that still holds overlapping cells. The residual then looks like
a routability problem and is not one.

These tests pin the gate's four states, and pin the message-accuracy bug the
reverse controls caught during authoring: "the repair did not run" and "the
repair ran and converged" are DIFFERENT facts and must not share a message.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
GATE = PROGRAMS / "postroute_legalization_convergence_check.py"

REPAIR_RAN = """PNR_STAGE: postroute_drv_repair
SDR_CRIT_WIRE_LEN_UM: 7937 (geometric seed 150 um)
SDR_DRV_PASS1_BEFORE: 585 (max_wire_length=7937)
[INFO RSZ-0039] Resized 317 instances.
"""

LEGALIZER_FAILED = """[WARNING DPL-0700] Negotiation phase 1: violations stuck at 5
[ERROR DPL-0701] NegotiationLegalizer did not fully converge. Violations remain: 1
SDR_DPL_NONFATAL: DPL-0701
"""

RIP_AND_REROUTE = """SDR_ROUTING_CLEARED: 6045 (spare_preserved=117)
[INFO DRT-0199]   Number of violations = 86.
Viol/Layer      Metal1
Metal Spacing       26
NS Metal             6
Short               54
[INFO DRT-0267] cpu time = 00:01:21
"""


def _proj(tmp_path: Path, log_text: str | None) -> Path:
    p = tmp_path / "proj"
    (p / "phase3" / "stage3" / "pnr").mkdir(parents=True)
    if log_text is not None:
        (p / "phase3" / "stage3" / "pnr" / "openroad.log").write_text(log_text)
    return p


def _run(project: Path):
    return subprocess.run([sys.executable, str(GATE), str(project)],
                          capture_output=True, text=True)


def _report(project: Path) -> dict:
    return json.loads((project / "reports" / "phase3"
                       / "postroute_legalization_convergence.json").read_text())


def test_vacuous_when_there_is_no_pnr_log(tmp_path):
    r = _run(_proj(tmp_path, None))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "VACUOUS" in r.stdout


def test_pass_when_the_repair_never_ran(tmp_path):
    proj = _proj(tmp_path, "[INFO DRT-0199]   Number of violations = 0.\n")
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "no post-route DRV repair" in r.stdout
    assert _report(proj)["postroute_drv_repair_ran"] is False


def test_pass_when_the_repair_ran_and_legalized(tmp_path):
    """The reverse control that caught the message bug: this is NOT the same
    fact as 'the repair did not run', and must not print the same sentence."""
    proj = _proj(tmp_path, REPAIR_RAN + RIP_AND_REROUTE)
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "legalized without raising" in r.stdout
    assert "did not run" not in r.stdout
    rep = _report(proj)
    assert rep["postroute_drv_repair_ran"] is True
    assert rep["repair_legalization_swallowed"] is False


def test_fail_when_a_legalization_non_convergence_was_swallowed(tmp_path):
    proj = _proj(tmp_path, REPAIR_RAN + LEGALIZER_FAILED + RIP_AND_REROUTE)
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr
    rep = _report(proj)
    assert rep["illegal_cells_remaining"] == 1
    assert rep["nets_ripped_up_after"] == 6045


def test_the_fail_message_is_actionable(tmp_path):
    """A FAIL that does not say WHERE the residual sits sends the next reader
    to die size, which cannot help."""
    proj = _proj(tmp_path, REPAIR_RAN + LEGALIZER_FAILED + RIP_AND_REROUTE)
    r = _run(proj)
    assert "Metal1" in r.stdout
    assert "54 short(s)" in r.stdout
    assert "die size" in r.stdout
    rep = _report(proj)
    assert rep["layers_with_residual"] == ["Metal1"]
    assert rep["final_short_count"] == 54


def test_a_converged_run_keeps_a_clean_layer_table_out_of_the_verdict(tmp_path):
    """No residual table must be reported as a failure signature on a PASS."""
    proj = _proj(tmp_path, REPAIR_RAN + RIP_AND_REROUTE)
    _run(proj)
    rep = _report(proj)
    assert "final_short_count" not in rep
