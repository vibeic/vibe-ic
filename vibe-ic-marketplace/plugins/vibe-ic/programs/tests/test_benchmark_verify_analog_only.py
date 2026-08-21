"""tests/test_benchmark_verify_analog_only.py

Covers the analog-only N/A behaviour of benchmark_verify_report.py:
an IC that has analog blocks but NO synthesizable digital RTL and never
reached place-and-route must gate Pillar 3 (code coverage) + Pillar 4
(FPGA) as N/A (not PENDING/FAIL), and N/A the pure-DIGITAL 56-step steps,
mirroring how Pillar 6 already N/As without place-and-route. A DIGITAL IC
with a missing code_coverage.json must still be PENDING (no silent pass).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent / "benchmark_verify_report.py")
FLOW = (Path(__file__).resolve().parent.parent.parent
        / "flow" / "phase1_phase2_phase3.yaml")


def _analog_block(project: Path, block: str) -> None:
    """Make an analog-only IC: analog block list + a per-block GDS under
    phase3/analog/ (so _is_analog_ic is True) and NO digital RTL/DEF."""
    d = project / "phase3" / "analog" / block
    d.mkdir(parents=True, exist_ok=True)
    (project / "phase3" / "analog" / "analog_block_list.json").write_text(
        json.dumps({"blocks": [{"name": block, "type": block}]}))
    # a non-vacuous-ish gds (content irrelevant to detection — presence only)
    (d / f"{block}.gds").write_text("GDS-DATA" * 40)
    # the analog hardmacro behavioral wrapper .v must NOT count as digital RTL
    (d / f"{block}.v").write_text("// behavioral analog wrapper\nmodule m; endmodule\n")
    # A-track convergence evidence. Pillar 5 requires a non-FAIL A-track verdict
    # with every corner sweep FULLY measured; presence of blocks alone is not
    # evidence the analog loop closed. This test's subject is the Pillar 3 + 4
    # N/A behaviour, so the fixture supplies a genuinely converged A-track —
    # which is what a PRODUCTION-READY analog IC must have.
    (project / "reports" / "phase3").mkdir(parents=True, exist_ok=True)
    (project / "reports" / "phase3" / "analog_one_shot.json").write_text(
        json.dumps({"verdict": "PASS"}))
    # `_provenance: real_ngspice` is true of the SIMULATOR and says nothing
    # about the SUBJECT; `design_content` is where the sweep republishes what
    # the netlist it ran on contains. A PRODUCTION-READY analog IC has a loop
    # that closed on a design-bound netlist, so the fixture says so — without
    # it, this test would also be asserting that a sweep which will not name
    # its circuit can carry an IC to PRODUCTION-READY.
    (d / "corner_results.json").write_text(json.dumps({
        "partial_measurement": False, "_provenance": "real_ngspice",
        "design_content": "structure_and_geometry",
        "corners_executed": 9, "full_pvt_sweep_executed": True}))


def _func_cov_100(project: Path) -> None:
    (project / "reports").mkdir(parents=True, exist_ok=True)
    (project / "reports" / "functional_coverage.json").write_text(json.dumps(
        {"requirements": [
            {"id": "R1", "source": "L5", "desc": "x", "status": "PASS"},
        ]}))


def _crosschecks(project: Path) -> None:
    """Write a passing verdict for D1 + every analog A*/M* step so Pillar 2's
    applicable set (analog-only) is all-PASS."""
    cc = project / "cross_check" / "analog"
    cc.mkdir(parents=True, exist_ok=True)
    ids = ["D1"] + [f"A{i}" for i in range(1, 10)] + [f"M{i}" for i in range(1, 5)]
    for sid in ids:
        (cc / f"step_{sid}.md").write_text(
            f"# Step {sid}\nVerdict: PASS\n")


def _run(project: Path):
    cmd = [sys.executable, str(PROG), str(project)]
    if FLOW.is_file():
        cmd += ["--flow", str(FLOW)]
    return subprocess.run(cmd, capture_output=True, text=True)


def test_analog_only_pillars_3_4_are_na_and_overall_production_ready(tmp_path):
    _analog_block(tmp_path, "ldo")
    _func_cov_100(tmp_path)
    _crosschecks(tmp_path)
    # NOTE: deliberately NO code_coverage.json and NO hw_test.json.
    r = _run(tmp_path)
    report = (tmp_path / "BENCHMARK_VERIFICATION_REPORT.md").read_text()
    # Pillars 3 + 4 must show N/A, not FAIL/PENDING.
    assert "analog-only IC — no synthesizable digital RTL to measure code coverage" in report
    assert "analog-only IC — no synthesizable digital RTL for FPGA/BFM verification" in report
    assert "analog_only=True" in r.stdout
    assert "code_line=N/A" in r.stdout and "fpga=N/A" in r.stdout
    # With functional 100%, analog present, digital pillars N/A -> PRODUCTION-READY.
    assert "OVERALL=PRODUCTION-READY" in r.stdout, r.stdout
    assert r.returncode == 0


def test_digital_ic_missing_code_coverage_is_not_silently_passed(tmp_path):
    """Guard: a DIGITAL IC (synthesizable RTL present) with no code_coverage.json
    must NOT be N/A'd — it stays a real gate (PENDING/FAIL), no silent pass."""
    # digital RTL present (phase2 rtl) + a placed-and-routed DEF -> not analog-only
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "core.v").write_text("module core(input a, output y); assign y=a; endmodule\n")
    (tmp_path / "phase3").mkdir(parents=True, exist_ok=True)
    (tmp_path / "phase3" / "core.def").write_text("VERSION 5.8 ;\n")
    _func_cov_100(tmp_path)
    r = _run(tmp_path)
    report = (tmp_path / "BENCHMARK_VERIFICATION_REPORT.md").read_text()
    # code coverage must report MISSING (PENDING), not N/A.
    assert "code_coverage.json MISSING" in report
    assert "analog_only=False" in r.stdout
    assert "OVERALL=PRODUCTION-READY" not in r.stdout
    assert r.returncode != 0
