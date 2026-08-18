#!/usr/bin/env python3
"""Regression for ORGANIC #789 (GAP-B) — flow_compliance_check must FORWARD
--skip-analog into the per-step optional/required gate commands.

Bug (v1.1.0): flow_compliance_check honoured --skip-analog in two places
already — the P0 structural-RTL umbrella (#632, which suppresses the analog
sub-gates) and the final-audit aggregation (#609). But the per-step gate
evaluator `_evaluate_gate` ran each `optional_program_exit_zero` /
`program_exit_zero` command VERBATIM through `_check_program_exit_zero` and
never forwarded `skip_analog`. So when the runner is invoked --skip-analog,
an analog-aware optional gate that ITSELF knows how to defer its analog-only
cases under --skip-analog — the L10/L12 tb-conformance gates
(l10_tb_conformance_check, #773) — was invoked WITHOUT the flag. For any IC
class whose L10/L12 conformance items are analog-only `verification_intent`
cases, the gate reported every case as unevidenced and Step-4 Simulation
hard-FAILed under --strict, IDENTICALLY with and without --skip-analog.

Fix (WIRING, not gate-logic): thread `skip_analog` down through
`_evaluate_gate` to the program-running branches and, when set, append
`--skip-analog` (and a reviewable `--analog-anchor <sim/results.xml>`) to the
command IFF the gate's OWN program declares the flag in its `--help`. The
decision is a runtime capability probe of the program's argparse — never a
hard-coded program / chip / vendor / SKU allow-list — so it auto-extends to
any future analog-aware gate and never touches a gate that doesn't opt in.

§4.05 NO-LEAK (load-bearing):
  * NEG-1 — a DIGITAL `cmd_response` L10 with no TB evidence STILL FAILs even
    under --skip-analog (the gate program scopes the relaxation to ANALOG-only
    intents; this wiring only hands over the flag, it never weakens the
    digital floor).
  * NEG-2 — `skip_analog=False` leaves the command BYTE-IDENTICAL (no
    behaviour change on every non-deferred run).
  * NEG-3 — a non-analog optional gate whose program does NOT declare
    --skip-analog gets NO --skip-analog appended (fail-closed capability
    probe).
  * an already-authored --skip-analog is NOT duplicated.

chip-AGNOSTIC: synthetic generic fixtures only; the forwarding decision is a
structural argparse capability probe, never a chip / vendor / SKU literal.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import flow_compliance_check as F  # noqa: E402


# ───────────────────────── fixtures (synthetic, chip-agnostic) ─────────────

_ANALOG_L10 = {
    # 4 analog-only verification_intent cases (no chip literal). A digital
    # testbench can never carry an id-substring trace for any of these.
    "test_cases": [
        {"id": "tc_dc_regulation", "category": "verification_intent",
         "kind": "verification_intent", "description": "DC output regulation"},
        {"id": "tc_line_response", "category": "verification_intent",
         "kind": "verification_intent", "description": "line transient"},
        {"id": "tc_load_step", "category": "verification_intent",
         "kind": "verification_intent", "description": "load step settling"},
        {"id": "tc_psrr_sweep", "category": "verification_intent",
         "kind": "verification_intent", "description": "PSRR sweep"},
    ]
}

_DIGITAL_L10 = {
    # 1 genuine DIGITAL cmd_response case with no TB evidence — must NEVER be
    # waived even under --skip-analog.
    "test_cases": [
        {"id": "tc_read_reg", "category": "cmd_response",
         "kind": "cmd_response", "opcode": "0x12",
         "description": "digital register read"},
    ]
}

# reviewable capability-gap anchor (CONNECTIVITY_PASS verdict + capability_gap)
_RESULTS_XML = (
    "<results>\n"
    "  <verdict>CONNECTIVITY_PASS</verdict>\n"
    "  <capability_gap>analog verification intent deferred — open-source "
    "flow has no analog oracle</capability_gap>\n"
    "</results>\n"
)

# The canonical flow-YAML L10 optional gate command (no explicit --project;
# --project is inferred from --l10's project tree by l10_tb_conformance_check).
_L10_CMD = (
    "l10_tb_conformance_check "
    "--l10 phase1/generated_docs/L10_TEST_CASES.json "
    "--tb-dir phase2/stage1/sim/tb "
    "--out reports/phase2/gates/l10_tb_conformance.json"
)
_L10_GATE = {
    "optional_program_exit_zero": {
        "command": _L10_CMD,
        "condition_files_exist": ["phase1/generated_docs/L10_TEST_CASES.json"],
    }
}


def _make_project(tmp_path: Path, l10: dict, *, with_anchor: bool = True) -> Path:
    proj = tmp_path / "proj"
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    (proj / "phase2" / "stage1" / "sim" / "tb").mkdir(parents=True)
    (proj / "reports" / "phase2" / "gates").mkdir(parents=True)
    (proj / "phase1" / "generated_docs" / "L10_TEST_CASES.json").write_text(
        json.dumps(l10), encoding="utf-8")
    # empty TB dir → no digital trace
    if with_anchor:
        (proj / "phase2" / "stage1" / "sim" / "results.xml").write_text(
            _RESULTS_XML, encoding="utf-8")
    return proj


def _l10_step() -> dict:
    return {"id": 4, "name": "Simulation", "gate": dict(_L10_GATE)}


# ───────────────────────── POSITIVE — false-positive gone ──────────────────


def test_positive_evaluate_gate_skip_analog_waives_analog_l10(tmp_path):
    """POSITIVE: an analog-only L10 optional gate that hard-FAILed verbatim is
    PASSED (rc=3 WAIVED-DEFERRED bubbled up) once --skip-analog is forwarded."""
    proj = _make_project(tmp_path, _ANALOG_L10)
    # Pre-fix behaviour shape: WITHOUT skip_analog the gate FAILs.
    passed_noflag, _ = F._evaluate_gate(proj, dict(_L10_GATE), skip_analog=False)
    assert passed_noflag is False
    # WITH skip_analog forwarded the gate now PASSES (waiver hint bubbled).
    passed_flag, reasons = F._evaluate_gate(proj, dict(_L10_GATE),
                                            skip_analog=True)
    assert passed_flag is True, reasons


def test_positive_check_step_skip_analog_waived_not_fail(tmp_path):
    """POSITIVE end-to-end: check_step(skip_analog=True) → WAIVED status; the
    same step with skip_analog=False is FAIL (the flag had no effect pre-fix)."""
    proj = _make_project(tmp_path, _ANALOG_L10)
    r_flag = F.check_step(proj, _l10_step(), waivers={}, skip_analog=True)
    assert r_flag.status == "WAIVED", (r_flag.status, r_flag.reasons)
    r_noflag = F.check_step(proj, _l10_step(), waivers={}, skip_analog=False)
    assert r_noflag.status == "FAIL", (r_noflag.status, r_noflag.reasons)


def test_positive_artifact_written_with_waived_count(tmp_path):
    """The L10 gate artifact is produced and credits the analog cases as
    WAIVED (total=4, fail=0, waived=4) under forwarded --skip-analog."""
    proj = _make_project(tmp_path, _ANALOG_L10)
    F.check_step(proj, _l10_step(), waivers={}, skip_analog=True)
    art = proj / "reports" / "phase2" / "gates" / "l10_tb_conformance.json"
    assert art.is_file()
    d = json.loads(art.read_text())
    assert d["total"] == 4 and d["fail"] == 0 and d["waived"] == 4, d


# ───────────────────────── §4.05 NO-LEAK negatives ─────────────────────────


def test_neg1_digital_case_still_fails_even_under_skip_analog(tmp_path):
    """§4.05 NEG-1: a genuine DIGITAL cmd_response L10 with no TB evidence
    STILL FAILs even under --skip-analog. The forwarding only hands the flag
    over; the gate program refuses to waive a digital case, so the digital
    floor is intact."""
    proj = _make_project(tmp_path, _DIGITAL_L10)
    r = F.check_step(proj, _l10_step(), waivers={}, skip_analog=True)
    assert r.status == "FAIL", (r.status, r.reasons)


def test_neg2_skip_analog_false_is_byte_identical(tmp_path):
    """§4.05 NEG-2: skip_analog=False returns the command BYTE-IDENTICAL — no
    flag, no anchor, no behaviour change for non-deferred runs."""
    proj = _make_project(tmp_path, _ANALOG_L10)
    out = F._maybe_forward_skip_analog(proj, _L10_CMD, skip_analog=False)
    assert out == _L10_CMD


def test_neg3_nonanalog_gate_gets_no_skip_analog(tmp_path):
    """§4.05 NEG-3: an optional gate whose program does NOT declare
    --skip-analog gets NO --skip-analog appended (fail-closed capability
    probe). verilator_coverage_measure is a real non-analog gate program in
    the flow YAML."""
    proj = _make_project(tmp_path, _ANALOG_L10)
    cmd = ("verilator_coverage_measure check "
           "--coverage-json reports/phase2/coverage/coverage_actual.json")
    out = F._maybe_forward_skip_analog(proj, cmd, skip_analog=True)
    assert out == cmd
    assert "--skip-analog" not in out


def test_neg3b_unknown_program_fail_closed(tmp_path):
    """§4.05 NEG-3 (fail-closed): a non-resolvable program name returns the
    command unchanged — the capability probe never appends a flag it cannot
    confirm the program accepts."""
    proj = _make_project(tmp_path, _ANALOG_L10)
    cmd = "no_such_program_zzz . --json reports/x.json"
    out = F._maybe_forward_skip_analog(proj, cmd, skip_analog=True)
    assert out == cmd


# ───────────────────────── forwarding mechanics ────────────────────────────


def test_fwd_appends_skip_analog_and_anchor(tmp_path):
    """An analog-aware gate (l10) under skip_analog=True gets --skip-analog AND
    a reviewable --analog-anchor appended; the anchor is a RELATIVE path
    (resolved against cwd=project by the gate subprocess)."""
    proj = _make_project(tmp_path, _ANALOG_L10)
    out = F._maybe_forward_skip_analog(proj, _L10_CMD, skip_analog=True)
    assert "--skip-analog" in out
    assert "--analog-anchor" in out
    assert "phase2/stage1/sim/results.xml" in out
    # relative, not absolute (no leading '/')
    tail = out[len(_L10_CMD):]
    assert " --analog-anchor phase2/stage1/sim/results.xml" in tail


def test_fwd_no_anchor_when_results_xml_absent(tmp_path):
    """Without a reviewable sim/results.xml anchor, only --skip-analog is
    appended (no --analog-anchor). The gate program then re-FAILs the
    unanchored deferral, degrading safely to the pre-fix FAIL — no blanket
    pass. (Here the absent anchor → gate FAIL, proving the safe degrade.)"""
    proj = _make_project(tmp_path, _ANALOG_L10, with_anchor=False)
    out = F._maybe_forward_skip_analog(proj, _L10_CMD, skip_analog=True)
    assert "--skip-analog" in out
    assert "--analog-anchor" not in out
    # unanchored deferral re-FAILs (no blanket pass)
    r = F.check_step(proj, _l10_step(), waivers={}, skip_analog=True)
    assert r.status == "FAIL", (r.status, r.reasons)


def test_fwd_does_not_duplicate_existing_skip_analog(tmp_path):
    """An already-authored --skip-analog is not duplicated."""
    proj = _make_project(tmp_path, _ANALOG_L10)
    cmd_pre = _L10_CMD + " --skip-analog"
    out = F._maybe_forward_skip_analog(proj, cmd_pre, skip_analog=True)
    assert out.count("--skip-analog") == 1


def test_program_accepts_flag_capability_probe():
    """The capability probe is structural: l10_tb_conformance_check declares
    --skip-analog + --analog-anchor; a non-analog program does not."""
    assert F._program_accepts_flag("l10_tb_conformance_check", "--skip-analog")
    assert F._program_accepts_flag("l10_tb_conformance_check", "--analog-anchor")
    assert not F._program_accepts_flag("verilator_coverage_measure",
                                       "--skip-analog")
    assert not F._program_accepts_flag("no_such_program_zzz", "--skip-analog")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
