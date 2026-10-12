#!/usr/bin/env python3
"""FX_P2 (3b) — a phase-3 record older than this run's phase-2 netlist is not
evidence that phase 3 ran FOR THIS DESIGN.

MEASURED on subservient (8HD-4, 2026-09-28): the tree carried an earlier
supplementary phase-3 attempt (`reports/orchestrator/phase3_one_shot.json`
2026-09-27 22:24, halted at pad_ring, plus 14 `reports/phase3` JSONs), and the
new run's phase 2 re-synthesised (`phase2/stage2/synth/*.v` 2026-09-28 00:27).
`l24_signoff_evidence_backed_check` read "phase 3 has run", booked the four
sign-off requirements the input states (DRC/LVS/antenna/STA) UNMET, and the
phase-2 final_audit halted the run -- so the phase that would measure them
could not start. That is the R-0915 deadlock `_phase3_has_run` exists to
prevent, re-opened by stale files.

Driven through the real gate as a subprocess; mtimes are set explicitly.
chip-AGNOSTIC: synthetic project.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import phase1_post_process as P  # noqa: E402
import pytest

GATE = PROGRAMS / "l24_signoff_evidence_backed_check.py"
T_OLD, T_NEW = 1_700_000_000, 1_700_100_000


def _project(tmp_path: Path) -> Path:
    d = tmp_path / "input" / "docs"
    d.mkdir(parents=True)
    (d / "spec.md").write_text("Sign-off requires DRC clean.\n")
    doc = P.emit_l_doc_skeleton("L24", "unknown", project_dir=tmp_path)
    doc.pop("evidence", None)
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L24_SIGNOFF.json").write_text(json.dumps(doc))
    return tmp_path


def _at(path: Path, text: str, t: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    os.utime(path, (t, t))
    return path


def _phase3_record(proj: Path, t: int) -> None:
    _at(proj / "reports" / "orchestrator" / "phase3_one_shot.json",
        json.dumps({"verdict": "FAIL"}), t)
    _at(proj / "reports" / "phase3" / "lvs_verdict.json",
        json.dumps({"status": "PASS"}), t)


def _netlist(proj: Path, t: int) -> None:
    _at(proj / "phase2" / "stage2" / "synth" / "top_synth.v",
        "module top; endmodule\n", t)


def _gate(proj: Path):
    r = subprocess.run([sys.executable, str(GATE), str(proj)],
                       capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout + r.stderr


def test_phase3_of_an_older_netlist_is_not_yet_measurable(tmp_path):
    proj = _project(tmp_path)
    _phase3_record(proj, T_OLD)
    _netlist(proj, T_NEW)
    rc, out = _gate(proj)
    assert rc == 0, out
    assert "not yet measurable" in out
    assert "REQUIRES" not in out


def test_phase3_of_this_netlist_still_fails_an_unmeasured_requirement(
        tmp_path):
    """THE CONTROL: phase 3 ran after this run's synthesis, with no DRC
    report — the requirement is UNMET and the gate FAILs, as before."""
    proj = _project(tmp_path)
    _netlist(proj, T_OLD)
    _phase3_record(proj, T_NEW)
    rc, out = _gate(proj)
    assert rc == 1, out
    assert "the input REQUIRES DRC clean" in out


def test_with_no_phase2_netlist_the_records_are_taken_as_they_are(tmp_path):
    """Nothing to date them against: today's behaviour, unchanged."""
    proj = _project(tmp_path)
    _phase3_record(proj, T_OLD)
    rc, out = _gate(proj)
    assert rc == 1, out


def test_the_audits_own_stage3_publication_is_not_phase3_evidence(tmp_path):
    """MEASURED in the same run: the phase-2 final audit writes
    `reports/phase3/gates/stage3_compliance.json` (program
    flow_compliance_check) AFTER this run's synthesis, and the gate read it as
    "phase 3 has run". The audit's own record is not a measurement."""
    proj = _project(tmp_path)
    _phase3_record(proj, T_OLD)
    _netlist(proj, T_OLD + 10)
    _at(proj / "reports" / "phase3" / "gates" / "stage3_compliance.json",
        json.dumps({"program": "flow_compliance_check", "phase": "all"}),
        T_NEW)
    rc, out = _gate(proj)
    assert rc == 0, out
    assert "not yet measurable" in out


def test_a_real_phase3_record_after_synthesis_still_counts(tmp_path):
    """THE CONTROL for the exclusion: a phase-3 PRODUCER's record newer than
    the netlist is phase 3 having run, and an unmeasured requirement FAILs."""
    proj = _project(tmp_path)
    _netlist(proj, T_OLD)
    _at(proj / "reports" / "phase3" / "gates" / "stage3_compliance.json",
        json.dumps({"program": "flow_compliance_check"}), T_NEW)
    _at(proj / "reports" / "phase3" / "lvs_verdict.json",
        json.dumps({"status": "PASS"}), T_NEW)
    rc, out = _gate(proj)
    assert rc == 1, out


@pytest.mark.parametrize("kind", ["corner", "legacy_corner", "prelayout", "legacy_prelayout"])
def test_prelayout_inventory_and_audit_do_not_assert_physical_execution(tmp_path, kind):
    import phase3_one_shot_runner as physical
    proj = _project(tmp_path)
    _netlist(proj, T_OLD)
    if "corner" in kind:
        path = physical.emit_step7_corner_disclosure(proj, {
            "corners": [{"name": "SS"}, {"name": "TT"}, {"name": "FF"}]})
        record = json.loads(path.read_text())
        if kind == "corner":
            assert record["record_role"] == "configuration"
        else:
            record.pop("record_role", None)
    else:
        path = proj / "reports/phase3/sta/pre_pnr_summary.json"
        record = {"program": "eda_report_audit:sta", "verdict": "PASS",
                  "summary": {"slack_measurement": "NOT_MEASURED"}}
        if kind == "prelayout":
            record["record_role"] = "prelayout_audit"
    _at(path, json.dumps(record), T_NEW)
    rc, out = _gate(proj)
    assert rc == 0 and "not yet measurable" in out, out
    # The same inventory cannot hide a real current physical attempt.
    _at(proj / "reports/phase3/lvs_verdict.json", '{"status":"PASS"}', T_NEW)
    rc, out = _gate(proj)
    assert rc == 1 and "the input REQUIRES DRC clean" in out, out

