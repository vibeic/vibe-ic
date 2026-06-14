"""ORGANIC #675 — Step-5 Formal honest sibling self-skip must SKIPPED-CONDITION,
not hard-FAIL (same structural class as the shipped #673).

Root cause (traced in the issue): the phase2 runner (#440) emits ONLY
`formal/formal_not_run.json` (verdict=SKIPPED-CONDITION) and NEVER
`formal/results.json` when no SymbiYosys proof ran. Step-5's gate is an
`all_of` whose first sub-gate `files_exist:['formal/results.json']` and second
sub-gate `formal_proof_evidence_check` both hard-FAILed on the absent
results.json — even though the runner HONESTLY disclosed the skip in the
sibling manifest. The disclosed deferral was invisible to BOTH surfaces →
hard FAIL → cascade-blocked all 25 Phase-3 steps.

Two surfaces fixed (both chip-AGNOSTIC, structural-verdict reads):
  (1) `formal_proof_evidence_check` — when results.json is absent, honor a
      co-located sibling *.json self-reporting a self-skip verdict → rc=2
      (vacuous), instead of rc=1 (FAIL).
  (2) `flow_compliance_check._evaluate_gate` `files_exist` branch — when a
      required file is missing, consult a co-located sibling self-skip
      artifact and emit __SKIP_HINT__ so the step promotes to
      SKIPPED-CONDITION (mirrors _check_json_field_true's #608 promotion).
      The step-level handler now resolves SKIPPED-CONDITION ahead of
      VACUOUS_PASS so the disclosed deferral surfaces.

§4.05 NEGATIVE no-leak (critical):
  * a REAL authored proof (results.json present + .sby + sby PASS) gates
    normally — never defers;
  * a REAL formal FAIL (results.json present, all_proved:false) still FAILs;
  * a sibling whose verdict is NOT a self-skip verdict (a real FAIL manifest)
    does NOT leak a skip — stays FAIL.

chip-AGNOSTIC: structural-verdict / path-shape fixtures only, no chip literal.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import formal_proof_evidence_check as FPC  # noqa: E402
import flow_compliance_check as FCC  # noqa: E402


# ── helpers ──────────────────────────────────────────────────────────────
def _formal(tmp_path):
    f = tmp_path / "phase2" / "stage1" / "formal"
    f.mkdir(parents=True)
    return f


_SBY_PASS_LOG = """\
SBY 12:00:00 [task] engine_0: starting process "smtbmc yices"
SBY 12:00:09 [task] summary: Elapsed clock time [H:MM:SS (secs)]: 0:00:09
SBY 12:00:09 [task] DONE (PASS, rc=0)
"""


# ── (1) formal_proof_evidence_check program-level fix ───────────────────────
def test_absent_results_with_skip_sibling_is_vacuous(tmp_path):
    """The #440 runner shape: no results.json, only formal_not_run.json
    (verdict=SKIPPED-CONDITION). Must be rc=2 (vacuous), NOT rc=1."""
    f = _formal(tmp_path)
    (f / "formal_not_run.json").write_text(json.dumps({
        "verdict": "SKIPPED-CONDITION",
        "fallback_skill": "assertion-gen",
        "reason": "no formal proof tool ran in this chain"}))
    rep = FPC.audit(tmp_path)
    assert rep["rc"] == 2, rep
    assert rep["verdict"] == "SKIPPED-CONDITION"
    assert "#675" in " ".join(rep["findings"])


def test_absent_results_no_sibling_still_fails(tmp_path):
    """No results.json AND no sibling manifest at all → hard FAIL (rc=1)."""
    _formal(tmp_path)
    rep = FPC.audit(tmp_path)
    assert rep["rc"] == 1 and rep["verdict"] == "FAIL", rep


def test_absent_results_with_NONskip_sibling_still_fails(tmp_path):
    """§4.05 no-leak: a sibling whose verdict is a real FAIL (not a self-skip
    verdict) must NOT be promoted to a skip — stays hard FAIL (rc=1)."""
    f = _formal(tmp_path)
    (f / "formal_not_run.json").write_text(json.dumps({
        "verdict": "FAIL", "reason": "the proof failed"}))
    rep = FPC.audit(tmp_path)
    assert rep["rc"] == 1 and rep["verdict"] == "FAIL", rep


def test_real_formal_fail_still_fails(tmp_path):
    """§4.05 no-leak: results.json PRESENT with all_proved:false (a real formal
    FAIL) — the absent-results skip path is never taken, stays FAIL."""
    f = _formal(tmp_path)
    (f / "results.json").write_text(json.dumps({
        "verdict": "FAIL", "all_proved": False}))
    rep = FPC.audit(tmp_path)
    assert rep["rc"] == 1 and rep["verdict"] == "FAIL", rep


def test_real_proof_chain_still_passes(tmp_path):
    """§4.05 no-leak: a real authored proof (results.json + .sby whose refs
    exist + sby PASS log) gates normally to PASS — never defers."""
    f = _formal(tmp_path)
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "top.sv").write_text("module top; endmodule\n")
    (f / "asserts.sv").write_text("module a; endmodule\n")
    (f / "p.sby").write_text(
        "[script]\nread_verilog ../rtl/top.sv\nread_verilog asserts.sv\n"
        "[files]\nasserts.sv\n")
    (f / "p.log").write_text(_SBY_PASS_LOG)
    (f / "results.json").write_text(json.dumps({
        "verdict": "PASS", "all_proved": True}))
    rep = FPC.audit(tmp_path)
    assert rep["rc"] == 0 and rep["verdict"] == "PASS", rep


# ── (2) flow_compliance_check files_exist sibling-skip promotion ─────────────
def test_files_exist_gate_honors_sibling_skip(tmp_path):
    """The `files_exist:['formal/results.json']` sub-gate, when results.json is
    absent but formal_not_run.json self-reports SKIPPED-CONDITION, passes WITH a
    __SKIP_HINT__ marker (so the step promotes to SKIPPED-CONDITION)."""
    f = _formal(tmp_path)
    (f / "formal_not_run.json").write_text(json.dumps({
        "verdict": "SKIPPED-CONDITION", "reason": "no proof ran"}))
    gate = {"files_exist": ["phase2/stage1/formal/results.json"]}
    passed, reasons = FCC._evaluate_gate(tmp_path, gate)
    assert passed is True, reasons
    assert any(r.startswith(FCC._SKIP_HINT_PREFIX) for r in reasons), reasons


def test_files_exist_gate_no_sibling_still_fails(tmp_path):
    """§4.05 no-leak: absent file + no honest sibling → the files_exist gate
    still FAILs (no skip leak)."""
    _formal(tmp_path)
    gate = {"files_exist": ["phase2/stage1/formal/results.json"]}
    passed, reasons = FCC._evaluate_gate(tmp_path, gate)
    assert passed is False, reasons
    assert not any(r.startswith(FCC._SKIP_HINT_PREFIX) for r in reasons)


def test_files_exist_gate_present_file_passes_clean(tmp_path):
    """§4.05 no-leak: when the required file IS present, the gate passes WITHOUT
    any skip hint (the sibling path is never consulted)."""
    f = _formal(tmp_path)
    (f / "results.json").write_text(json.dumps({"verdict": "PASS"}))
    gate = {"files_exist": ["phase2/stage1/formal/results.json"]}
    passed, reasons = FCC._evaluate_gate(tmp_path, gate)
    assert passed is True
    assert not any(r.startswith(FCC._SKIP_HINT_PREFIX) for r in reasons)


def test_files_exist_gate_NONskip_sibling_does_not_leak(tmp_path):
    """§4.05 no-leak: absent file + sibling with a NON-skip verdict (real FAIL)
    → the files_exist gate still FAILs."""
    f = _formal(tmp_path)
    (f / "formal_not_run.json").write_text(json.dumps({
        "verdict": "FAIL", "reason": "real failure"}))
    gate = {"files_exist": ["phase2/stage1/formal/results.json"]}
    passed, reasons = FCC._evaluate_gate(tmp_path, gate)
    assert passed is False, reasons
    assert not any(r.startswith(FCC._SKIP_HINT_PREFIX) for r in reasons)


# ── (3) end-to-end check_step on the canonical Step-5 gate shape ─────────────
def _step5_gate():
    return {
        "all_of": [
            {"files_exist": ["phase2/stage1/formal/results.json"]},
            {"program_exit_zero":
                "formal_proof_evidence_check . "
                "--json reports/phase2/gates/formal_evidence.json"},
        ]
    }


def test_check_step_skipped_condition_on_honest_skip(tmp_path):
    """check_step over a Step-5-shaped all_of gate: absent results.json + honest
    formal_not_run.json → SKIPPED-CONDITION (not FAIL, not VACUOUS_PASS)."""
    f = _formal(tmp_path)
    (f / "formal_not_run.json").write_text(json.dumps({
        "verdict": "SKIPPED-CONDITION", "reason": "no proof ran"}))
    # sim_full_stack/results.json present so required_outputs is satisfied
    sfs = tmp_path / "phase2" / "stage1" / "sim_full_stack"
    sfs.mkdir(parents=True)
    (sfs / "results.json").write_text(json.dumps({"verdict": "PASS"}))
    step = {
        "id": 5, "name": "Formal verification",
        "required_outputs": [
            "phase2/stage1/formal/results.json",
            "phase2/stage1/sim_full_stack/results.json",
        ],
        "gate": _step5_gate(),
    }
    res = FCC.check_step(tmp_path, step, waivers={})
    assert res.status == "SKIPPED-CONDITION", (res.status, res.reasons)


def test_check_step_real_fail_still_fails(tmp_path):
    """§4.05 no-leak end-to-end: a real formal FAIL (results.json present,
    all_proved:false) over the Step-5 gate still FAILs."""
    f = _formal(tmp_path)
    (f / "results.json").write_text(json.dumps({
        "verdict": "FAIL", "all_proved": False}))
    sfs = tmp_path / "phase2" / "stage1" / "sim_full_stack"
    sfs.mkdir(parents=True)
    (sfs / "results.json").write_text(json.dumps({"verdict": "PASS"}))
    step = {
        "id": 5, "name": "Formal verification",
        "required_outputs": [
            "phase2/stage1/formal/results.json",
            "phase2/stage1/sim_full_stack/results.json",
        ],
        "gate": _step5_gate(),
    }
    res = FCC.check_step(tmp_path, step, waivers={})
    assert res.status == "FAIL", (res.status, res.reasons)
