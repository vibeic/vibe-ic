"""Tests for rig_topology_disclosure_check.py (D3 gate)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


VALID_TOPOLOGY = {
    "fpga_board": "DE10-Lite",
    "fpga_pin_assignments": {"SIO": "PIN_V10", "CLK": "PIN_P11"},
    "dut_connection": "SIO directly to MAX10 GPIO via 100Ω series",
    "scope_channel_map": {"ch1": "CLK", "ch4": "SIO"},
    "tester_port": "USB-HID /dev/hidraw0",
}


# ── FPGA-skip disclosure exemption (#607 shared predicate) ─────────────
# Measured on the real spm x ihp-sg13g2 campaign: rig_topology.json never
# existed (no FPGA board was ever part of this ASIC PDK sign-off run), so
# this gate hard-FAILed a project whose OWN run already discloses, in the
# established #607 shape, that no hardware rig is involved at all. A
# requirement for hardware wiring is meaningless when there is no hardware.

def _write_fpga_audit(project: Path, verdict: str, sof_present,
                      skip_reason: str = "not_attempted") -> None:
    """GATEKEEPER NARROWING: the cause is now an explicit field. `verdict:
    SKIP` alone is emitted for every non-PASS cause alike — including an FPGA
    path that WAS attempted and was blocked by a missing prerequisite, which
    is 12 of the 32 published audits and is somebody's bug, not an absence of
    hardware. Fixtures that mean "no FPGA is part of this run" now say so."""
    d = project / "reports" / "phase2" / "fpga"
    d.mkdir(parents=True, exist_ok=True)
    (d / "quartus_map_audit.json").write_text(json.dumps(
        {"verdict": verdict, "sof_present": sof_present,
         "skip_reason": skip_reason}))


# ── GATEKEEPER ADDITION (Step-2.7 adversarial review of the PR) ─────────────
# The PR read `verdict: SKIP, sof_present: false` as "this run honestly
# discloses no FPGA board is part of it". MEASURED against the writer and the
# published corpus, that is not what the file means.
#
#   design_one_shot_runner:
#       sof_present = bool(step and step.status == "PASS" and step.detail)
#       "verdict": "PASS" if sof_present else "SKIP"
#
# so SKIP is emitted for EVERY non-PASS cause. Over the 32 published audits:
#
#       20  evidence "fpga_compile not run"                  never attempted
#       12  evidence "qsf missing — caller must produce it"   ATTEMPTED, blocked
#
# The second group is somebody's bug. Waiving the rig-topology requirement on
# it would waive a requirement on the strength of a defect — in 12 of 32
# published cells. The cause is now a FIELD, and the predicate reads it.
import json as _json                                            # noqa: E402
import sys as _sys                                              # noqa: E402
from pathlib import Path as _Path                               # noqa: E402

_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))


def _audit(tmp_path, **fields):
    p = tmp_path / "reports" / "phase2" / "fpga" / "quartus_map_audit.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_json.dumps(fields))
    return tmp_path


def test_the_writer_records_the_cause_it_actually_had():
    """The field is only worth reading if the producer sets it correctly, and
    it is derived from the SAME expression that decides `sof_present` — a step
    object that is absent means never attempted, one that exists and did not
    PASS means attempted."""
    src = (_Path(__file__).resolve().parent.parent
           / "design_one_shot_runner.py").read_text()
    assert '"skip_reason": (None if sof_present' in src, "writer not wired"
    assert 'else "not_attempted" if fpga_compile_step is None' in src
    assert 'else "attempted_incomplete")' in src
