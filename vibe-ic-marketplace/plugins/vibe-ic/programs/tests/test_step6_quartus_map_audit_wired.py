#!/usr/bin/env python3
"""Step 6 — the Quartus map audit must actually RUN, not be restated.

DEFECT (measured on v1.7.36, HEAD 44259eac3)
--------------------------------------------
`flow/phase1_phase2_phase3.yaml` step 6 declares `quartus_map_audit` in its
`programs:` list, and a whole-plugin grep found no runner, gate or subprocess
that ever executed it — the four references were readers only.
`design_one_shot_runner.step_emit_phase2_manifests` HAND-WROTE the artefact as

    {"verdict": "PASS" if fpga_compile.status == "PASS" else "SKIP", ...}

i.e. a verdict restated from another step's status, on a `*.map.rpt` the
scanner never opened. Reproduced by calling the emitter with a PASSing
fpga_compile and a `.map.rpt` carrying two REAL silent-failure indicators:
the artefact said `verdict: PASS` while `quartus_map_audit.scan()` on the
very same file returned 2 findings. Step 6's gate could not contradict it —
it required only that the JSON EXIST.

These tests are behavioural discriminators: they call the real emitter and the
real gate. They FAIL against the pre-fix program files.

DIRECTION-1 GUARDS (must hold on BOTH trees)
--------------------------------------------
The board-absent disclosure shape `verdict=SKIP + sof_present=false +
skip_reason` is what four consumers key on (`fpga_board_capability`,
`flow_compliance_check._synthesise_fpga_skip_waivers`,
`rig_topology_disclosure_check`, and the #607/#663 tests). It must survive
byte-compatibly, and `fpga_skip_disclosed` must keep returning True for it.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import design_one_shot_runner as dr
import fpga_board_capability as fcap
import quartus_map_audit as qma

PROG = Path(__file__).resolve().parent.parent / "quartus_map_audit.py"

DIRTY_MAP_RPT = (
    "Analysis & Synthesis report\n"
    "; u_core|state_reg[3] ; Stuck at GND due to stuck port data_in ;\n"
    'Warning (10030): Net "rom_q" has no driver or initial value\n'
)
CLEAN_MAP_RPT = "Info: Quartus Prime Full Compilation was successful.\n"


def _project(tmp_path: Path, *, sof: bool, map_rpt: str | None) -> Path:
    proj = tmp_path / "proj"
    out = proj / "phase2/stage1/fpga/output_files"
    out.mkdir(parents=True)
    if sof:
        (out / "top.sof").write_bytes(b"\x00bitstream")
    if map_rpt is not None:
        (out / "top.map.rpt").write_text(map_rpt)
    return proj


def _emit(proj: Path, compile_status: str | None) -> dict:
    plan = []
    if compile_status is not None:
        plan.append(dr.StepResult("fpga_compile", compile_status, 1.0,
                                  "sof=top.sof size=10"))
    dr.step_emit_phase2_manifests(proj, plan, top_name="top")
    return json.loads(
        (proj / "reports/phase2/fpga/quartus_map_audit.json").read_text())


def _gate(proj: Path, out_json: Path | None = None):
    argv = ["--project", str(proj)]
    if out_json is not None:
        argv += ["--json", str(out_json)]
    return subprocess.run([sys.executable, str(PROG)] + argv,
                          capture_output=True, text=True)


# ---------------------------------------------------------------------------
# Producer — the scanner must actually run
# ---------------------------------------------------------------------------

def test_producer_reports_findings_from_the_real_map_rpt(tmp_path):
    """A compile that returned a .sof while its .map.rpt carries Stuck-at-GND
    and Warning(10030) must NOT be recorded as PASS."""
    proj = _project(tmp_path, sof=True, map_rpt=DIRTY_MAP_RPT)
    audit = _emit(proj, "PASS")
    assert audit["verdict"] == "FAIL", (
        "fpga_compile PASSed but its map report carries 2 silent-failure "
        f"indicators; audit said {audit['verdict']!r}")
    assert audit["audited"] is True
    assert audit["finding_count"] == 2
    assert {f["rule"] for f in audit["findings"]} == {"stuck-at-gnd", "no-driver"}
    assert audit["map_reports"] == ["phase2/stage1/fpga/output_files/top.map.rpt"]


def test_producer_pass_is_backed_by_an_actual_scan(tmp_path):
    """A clean map report still PASSes — but now says it was scanned."""
    proj = _project(tmp_path, sof=True, map_rpt=CLEAN_MAP_RPT)
    audit = _emit(proj, "PASS")
    assert audit["verdict"] == "PASS"
    assert audit["audited"] is True
    assert audit["finding_count"] == 0
    assert audit["map_reports"] == ["phase2/stage1/fpga/output_files/top.map.rpt"]


def test_producer_refuses_to_pass_an_unscanned_build(tmp_path):
    """A .sof with no .map.rpt was never scanned, so it cannot be certified."""
    proj = _project(tmp_path, sof=True, map_rpt=None)
    audit = _emit(proj, "PASS")
    assert audit["verdict"] != "PASS"
    assert audit["audited"] is False
    assert audit["skip_reason"] == "map_rpt_absent"
    assert audit["sof_present"] is True


def test_unscanned_build_is_not_mistaken_for_the_board_absent_disclosure(tmp_path):
    """The new `.sof present but unscanned` shape must never buy the #607/#663
    board-absent capability-gap waiver — that predicate requires sof_present
    to be False."""
    proj = _project(tmp_path, sof=True, map_rpt=None)
    _emit(proj, "PASS")
    assert fcap.fpga_skip_disclosed(proj) is False
    assert fcap.fpga_absent_from_run(proj) is False


# ---------------------------------------------------------------------------
# Gate — re-scans on disk, so a fabricated artefact cannot buy a PASS
# ---------------------------------------------------------------------------

def test_gate_fails_on_findings(tmp_path):
    proj = _project(tmp_path, sof=True, map_rpt=DIRTY_MAP_RPT)
    _emit(proj, "PASS")
    r = _gate(proj)
    assert r.returncode == 1, r.stdout + r.stderr


def test_gate_passes_a_genuinely_clean_build(tmp_path):
    proj = _project(tmp_path, sof=True, map_rpt=CLEAN_MAP_RPT)
    _emit(proj, "PASS")
    out = tmp_path / "gate.json"
    r = _gate(proj, out)
    assert r.returncode == 0, r.stdout + r.stderr
    payload = json.loads(out.read_text())
    assert payload["verdict"] == "PASS"
    assert payload["audited"] is True


def test_gate_rescans_disk_and_ignores_a_forged_clean_claim(tmp_path):
    """Hand-write `audited: true, findings: []` over a dirty .map.rpt: the gate
    re-scans the report itself, so the forgery does not buy a PASS."""
    proj = _project(tmp_path, sof=True, map_rpt=DIRTY_MAP_RPT)
    audit = proj / "reports/phase2/fpga/quartus_map_audit.json"
    audit.parent.mkdir(parents=True, exist_ok=True)
    audit.write_text(json.dumps({
        "verdict": "PASS", "sof_present": True, "audited": True,
        "findings": [], "finding_count": 0,
    }))
    r = _gate(proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "stuck-at-gnd" in (r.stdout + r.stderr)


def test_gate_fails_a_build_whose_audit_json_is_absent(tmp_path):
    proj = _project(tmp_path, sof=True, map_rpt=CLEAN_MAP_RPT)
    r = _gate(proj)
    assert r.returncode == 1, r.stdout + r.stderr


def test_gate_fails_a_status_restating_audit_json(tmp_path):
    """The exact pre-fix artefact shape — PASS with no `audited` claim — is
    rejected: a verdict copied from another step's status is not an audit."""
    proj = _project(tmp_path, sof=True, map_rpt=CLEAN_MAP_RPT)
    audit = proj / "reports/phase2/fpga/quartus_map_audit.json"
    audit.parent.mkdir(parents=True, exist_ok=True)
    audit.write_text(json.dumps({
        "verdict": "PASS", "sof_present": True, "skip_reason": None,
        "compile_log": "fpga/compile.log", "evidence": "sof=top.sof size=10",
    }))
    r = _gate(proj)
    assert r.returncode == 1, r.stdout + r.stderr


def test_gate_does_not_certify_a_build_that_never_happened(tmp_path):
    """No .sof at all → exit 0 with an explicit `no-build` disclosure. This leg
    audits a build; step 6's own files_exist leg + the cap-gap waiver own the
    "was there a build" verdict. It must NOT return 2 (which
    flow_compliance_check would credit as VACUOUS_PASS)."""
    proj = _project(tmp_path, sof=False, map_rpt=None)
    out = tmp_path / "gate.json"
    r = _gate(proj, out)
    assert r.returncode == 0, r.stdout + r.stderr
    payload = json.loads(out.read_text())
    assert payload["verdict"] == "NO_BUILD"
    assert payload["sof_present"] is False


# ---------------------------------------------------------------------------
# DIRECTION-1 GUARDS — behaviour that must NOT change (pass on both trees)
# ---------------------------------------------------------------------------

def test_guard_board_absent_disclosure_shape_is_preserved(tmp_path):
    proj = _project(tmp_path, sof=False, map_rpt=None)
    audit = _emit(proj, None)
    assert audit["verdict"] == "SKIP"
    assert audit["sof_present"] is False
    assert audit["skip_reason"] == "not_attempted"
    # THE KEY STAYS — four consumers read this shape and fields are ADDED, never
    # removed. The VALUE no longer names a log that is not there. This assertion
    # used to read `== "fpga/compile.log"`, which is what made the defect
    # durable: a payload whose own `audited` is false still pointed a reader at
    # a proof the deliverable does not carry, and the published
    # caravel_user_project cell shipped exactly that until the evidence-citation
    # gate caught it.
    assert "compile_log" in audit
    assert audit["compile_log"] is None
    assert audit["evidence"] == "fpga_compile not run"
    assert "design_identity" in audit


def test_a_compile_log_that_exists_is_still_named(tmp_path):
    """THE OTHER DIRECTION, and the one that decides whether the change above is
    a fix or a deletion: when the log IS there, the field must still point at
    it — otherwise "never name a missing proof" quietly becomes "never name the
    proof"."""
    proj = _project(tmp_path, sof=False, map_rpt=None)
    (proj / "fpga").mkdir(parents=True, exist_ok=True)
    (proj / "fpga/compile.log").write_text("quartus_map ...\n")
    audit = _emit(proj, None)
    assert audit["compile_log"] == "fpga/compile.log"


def test_guard_board_absent_disclosure_still_grants_the_capgap_waiver(tmp_path):
    proj = _project(tmp_path, sof=False, map_rpt=None)
    _emit(proj, None)
    assert fcap.fpga_skip_disclosed(proj) is True
    assert fcap.fpga_absent_from_run(proj) is True


def test_guard_attempted_incomplete_skip_reason_is_preserved(tmp_path):
    proj = _project(tmp_path, sof=False, map_rpt=None)
    audit = _emit(proj, "SKIP")
    assert audit["verdict"] == "SKIP"
    assert audit["sof_present"] is False
    assert audit["skip_reason"] == "attempted_incomplete"
    assert fcap.fpga_skip_disclosed(proj) is True
    # ...but NOT the stronger never-attempted claim (#607 vs the narrower one).
    assert fcap.fpga_absent_from_run(proj) is False


def test_guard_report_positional_mode_is_unchanged(tmp_path):
    """The original CLI — a bare *.map.rpt positional — must keep working
    exactly as before (0 clean / 1 findings / 2 missing file)."""
    clean = tmp_path / "clean.map.rpt"
    clean.write_text(CLEAN_MAP_RPT)
    dirty = tmp_path / "dirty.map.rpt"
    dirty.write_text(DIRTY_MAP_RPT)

    def run(*a):
        return subprocess.run([sys.executable, str(PROG)] + list(a),
                              capture_output=True, text=True)

    assert run(str(clean)).returncode == 0
    assert run(str(dirty)).returncode == 1
    assert run(str(tmp_path / "nope.map.rpt")).returncode == 2


def test_guard_scan_helper_semantics_unchanged(tmp_path):
    rpt = tmp_path / "x.map.rpt"
    rpt.write_text(DIRTY_MAP_RPT)
    findings = qma.scan(rpt)
    assert [f.rule for f in findings] == ["stuck-at-gnd", "no-driver"]
    assert all(f.severity == "error" for f in findings)


def test_guard_step6_declares_quartus_map_audit_as_a_program():
    """The declaration this fix honours must stay in place."""
    import yaml
    flow = (Path(__file__).resolve().parents[2]
            / "flow" / "phase1_phase2_phase3.yaml")
    doc = yaml.safe_load(flow.read_text())
    step6 = [s for s in doc["steps"] if str(s["id"]) == "6"][0]
    assert "quartus_map_audit" in step6.get("programs", [])


def test_step6_gate_invokes_the_declared_program():
    """Discriminator on the DECLARATION side: step 6's gate must invoke the
    program it declares, not merely require its output file to exist."""
    import yaml
    flow = (Path(__file__).resolve().parents[2]
            / "flow" / "phase1_phase2_phase3.yaml")
    doc = yaml.safe_load(flow.read_text())
    step6 = [s for s in doc["steps"] if str(s["id"]) == "6"][0]
    legs = step6["gate"]["all_of"]
    cmds = []
    for leg in legs:
        for key in ("program_exit_zero", "optional_program_exit_zero"):
            spec = leg.get(key)
            if isinstance(spec, str):
                cmds.append(spec)
            elif isinstance(spec, dict) and spec.get("command"):
                cmds.append(spec["command"])
    assert any(c.split()[0] == "quartus_map_audit" for c in cmds), (
        "step 6 declares `quartus_map_audit` under programs: but its gate "
        f"never invokes it; gate commands = {cmds}")
