"""Step 39 with no board on the bench reads NOT_MEASURED, never PASS or FAIL.

Owner ruling (fleet ledger 2026-09-25 15:2x): steps 6 and 39 (FPGA on-board)
are excluded from the IC "truly PASS" goal and are reported separately as
NOT_MEASURED, never called PASS. review70 step 39 (migration 39): no LibreLane
or OpenROAD step compiles or programs an FPGA, the image has no Quartus, so the
attestation gate stays a vibe-ic gate and reports NOT_MEASURED "until a board
and Quartus host exist".

`fpga_on_board_attestation_check` reported `overall: FAIL` for a project that
never had a board test. It now reports NOT_MEASURED with the same rc 1 when
none of the physical evidence classes exists, and still FAILs a manifest that
claims a pass with nothing physical behind it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import fpga_on_board_attestation_check as F               # noqa: E402

MANIFEST = "reports/phase2/fpga/on_board_pass.json"


def _run(proj: Path):
    out = proj / "gate.json"
    rc = F.main([str(proj), "--json", str(out)])
    return rc, json.loads(out.read_text())


def _write(proj: Path, rel: str, data) -> None:
    p = proj / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(data if isinstance(data, str) else json.dumps(data))


def test_a_project_with_no_board_evidence_is_not_measured(tmp_path):
    rc, rep = _run(tmp_path)
    assert rep["overall"] == "NOT_MEASURED", rep
    assert rep["reason_class"] == "hardware_required", rep
    assert "never PASS" in rep["ruling"], rep
    assert rc == 1, "NOT_MEASURED must never exit like a pass"


def test_the_runners_skip_manifest_is_not_measured(tmp_path):
    """A pure-digital run writes a SKIP manifest and nothing physical."""
    _write(tmp_path, MANIFEST, {"verdict": "SKIP", "sof_present": False})
    rc, rep = _run(tmp_path)
    assert rep["overall"] == "NOT_MEASURED" and rc == 1, rep


def test_a_pass_claim_with_no_physical_evidence_still_fails(tmp_path):
    """Forged JSON is the case the gate exists for; it is not an absence."""
    _write(tmp_path, MANIFEST, {"all_scenarios_passed": True,
                                "scenarios": [{"name": "s", "result": "PASS"}]})
    rc, rep = _run(tmp_path)
    assert rep["overall"] == "FAIL" and rc == 1, rep


def test_partial_physical_evidence_is_a_fail_not_an_absence(tmp_path):
    """A programmer log on disk means a board session happened; its missing
    manifest is a defect of that session."""
    _write(tmp_path, "reports/phase2/fpga/quartus_pgm.log", "quartus_pgm ok\n")
    assert F.physical_evidence_files(tmp_path) == [
        "reports/phase2/fpga/quartus_pgm.log"]
    rc, rep = _run(tmp_path)
    assert rep["overall"] == "FAIL" and rc == 1, rep


def test_absent_board_reports_identify_each_inspected_project(tmp_path):
    reports = []
    for name in ('local_alpha', 'local_beta'):
        project = tmp_path / name
        project.mkdir()
        rc, report = _run(project)
        assert rc == 1 and report['overall'] == 'NOT_MEASURED'
        assert report['design_identity'] == {'design': name}
        reports.append(report)
    assert reports[0] != reports[1]
    assert reports[0]['findings'] == reports[1]['findings']
