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
        "verdict": "PASS", "all_proved": True,
        "property_denominator": 1,
        "authored_property_count": 1,
        "unresolved_obligations": [],
        "bounded_vs_unbounded_scope": ["unbounded safety prove"],
        "sby": "phase2/stage1/formal/p.sby",
        "elaborated_sby": "phase2/stage1/formal/p.sby",
        "evidence": "phase2/stage1/formal/p.log",
        "proof_transcript": "phase2/stage1/formal/p.log",
    }))
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


def test_check_step_unanswerable_authoring_is_incomplete(tmp_path):
    """#1974: applicable work with no sound property is a named INCOMPLETE
    row, never SKIPPED-CONDITION / MISSING_CAPABILITY."""
    f = _formal(tmp_path)
    (f / "formal_authoring_request.json").write_text(json.dumps({
        "verdict": "INCOMPLETE",
        "fallback_skill": "formal-verify",
        "property_denominator": 1,
        "unresolved_obligations": [{
            "id": "L6.fsm_state.IDLE",
            "layer": "L6",
            "description": "state signal encoding is not declared",
        }],
    }))
    sfs = tmp_path / "phase2" / "stage1" / "sim_full_stack"
    sfs.mkdir(parents=True)
    (sfs / "results.json").write_text(json.dumps({"verdict": "PASS"}))
    step = {
        "id": 5, "name": "Formal verification",
        "required_outputs": [
            "phase2/stage1/formal/results.json OR "
            "phase2/stage1/formal/formal_authoring_request.json",
            "phase2/stage1/sim_full_stack/results.json",
        ],
        "gate": _step5_gate(),
    }
    res = FCC.check_step(tmp_path, step, waivers={})
    assert res.status == "INCOMPLETE", (res.status, res.reasons)
    joined = " ".join(res.reasons)
    assert "L6.fsm_state.IDLE" in joined
    assert "SKIPPED-CONDITION" not in joined


def test_proved_subset_with_open_denominator_is_incomplete(tmp_path):
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
        "verdict": "INCOMPLETE", "all_proved": True,
        "property_denominator": 2, "authored_property_count": 1,
        "unresolved_obligations": [{"id": "L8.reset_release_cycles"}],
        "bounded_vs_unbounded_scope": ["unbounded safety prove"],
        "sby": "phase2/stage1/formal/p.sby",
        "elaborated_sby": "phase2/stage1/formal/p.sby",
        "evidence": "phase2/stage1/formal/p.log",
        "proof_transcript": "phase2/stage1/formal/p.log",
    }))
    rep = FPC.audit(tmp_path)
    assert rep["rc"] == 0 and rep["verdict"] == "INCOMPLETE", rep
    assert rep["unresolved_obligations"] == [{"id": "L8.reset_release_cycles"}]


# ── (4) v1.4.23 — EARLY required_outputs MISSING path honors a STRICT sibling ─
# self-skip. A step whose ONLY evidence is a required_output (empty
# `verification.commands`) early-returns at the required_outputs presence check
# and never reaches the `files_exist` gate path that carries the #675 acceptance.
# So an honestly-disclosed downstream cap-gap skip — post-DFT optimization when
# scan insertion was disclosed-skipped (post_dft_not_run.json), SDF gate-level
# sim (sdf_sim_skipped.json), post-layout SPICE correlation (spice_correlation_
# not_run.json) — fell through to a hard MISSING.
#
# CRITICAL (adversarial-review-driven): at the early return there is NO second
# sub-gate to backstop a false promotion, and output DIRECTORIES are SHARED
# between steps (phase2/stage2/synth/ holds both step-9 netlist.v and step-12's
# marker; reports/phase3/ holds many sign-off reports). A loose dir-level match
# would let one step's honest marker MASK a different step's genuinely-absent
# output (a real synth or DRC/LVS sign-off FAIL). So the promotion is STRICT: the
# sibling must OWN this step's output — self-skip verdict + a named
# capability_flag + a `skips_required_output` matching one of THIS step's missing
# patterns. A NEUTRAL step id (999) isolates the sibling logic from the #430
# hard-coded capability-gap step-id list.

def _synth(tmp_path):
    s = tmp_path / "phase2" / "stage2" / "synth"
    s.mkdir(parents=True)
    return s


def _own_marker(reason="no scan_netlist.v — post-DFT has nothing to optimise",
                out="phase2/stage2/synth/post_dft_netlist.v",
                flag="cap:post_dft_scan_optimization", verdict="SKIPPED-CONDITION"):
    """A well-formed OWNING skip-marker payload (what the runner now emits)."""
    return json.dumps({"verdict": verdict, "reason": reason,
                       "capability_flag": flag, "skips_required_output": out})


def test_early_missing_honors_owning_sibling_self_skip(tmp_path):
    """Step-12 shape: sole required_output post_dft_netlist.v ABSENT, and a
    co-located post_dft_not_run.json OWNS that output (verdict + capability_flag +
    skips_required_output) → promotes to SKIPPED-CONDITION, not MISSING."""
    s = _synth(tmp_path)
    (s / "post_dft_not_run.json").write_text(_own_marker())
    step = {
        "id": 999, "name": "Post-DFT optimization (resynth / buffering)",
        "required_outputs": ["phase2/stage2/synth/post_dft_netlist.v"],
    }
    res = FCC.check_step(tmp_path, step, waivers={})
    assert res.status == "SKIPPED-CONDITION", (res.status, res.reasons)
    assert any("#675 strict" in r for r in res.reasons), res.reasons


def test_early_missing_no_sibling_stays_missing(tmp_path):
    """ANTI-GAMING: absent required_output AND no honest sibling → hard MISSING."""
    _synth(tmp_path)
    step = {"id": 999, "name": "Post-DFT optimization",
            "required_outputs": ["phase2/stage2/synth/post_dft_netlist.v"]}
    assert FCC.check_step(tmp_path, step, waivers={}).status == "MISSING"


def test_early_missing_nonskip_sibling_stays_missing(tmp_path):
    """§4.05 no-leak: absent output + a sibling whose verdict is a real FAIL (not
    a self-skip verdict) must NOT be promoted — stays MISSING."""
    s = _synth(tmp_path)
    (s / "post_dft_not_run.json").write_text(
        _own_marker(verdict="FAIL", reason="the resynth crashed"))
    step = {"id": 999, "name": "Post-DFT optimization",
            "required_outputs": ["phase2/stage2/synth/post_dft_netlist.v"]}
    assert FCC.check_step(tmp_path, step, waivers={}).status == "MISSING"


def test_early_missing_marker_without_ownership_stays_missing(tmp_path):
    """ANTI-MASK: a skip-marker that does NOT declare `skips_required_output`
    (the old loose shape) is IGNORED at the early return → stays MISSING. The
    runner must explicitly OWN the output to defer it."""
    s = _synth(tmp_path)
    (s / "post_dft_not_run.json").write_text(json.dumps({
        "verdict": "SKIPPED-CONDITION", "reason": "no scan netlist",
        "capability_flag": "cap:post_dft_scan_optimization"}))  # no skips_required_output
    step = {"id": 999, "name": "Post-DFT optimization",
            "required_outputs": ["phase2/stage2/synth/post_dft_netlist.v"]}
    assert FCC.check_step(tmp_path, step, waivers={}).status == "MISSING"


def test_early_missing_marker_without_capability_flag_stays_missing(tmp_path):
    """ANTI-MASK: a marker that owns the output but carries NO capability_flag
    (not a disclosed capability gap) is IGNORED → stays MISSING. Only a
    capability-AWARE disclosure defers."""
    s = _synth(tmp_path)
    (s / "post_dft_not_run.json").write_text(json.dumps({
        "verdict": "SKIPPED-CONDITION",
        "skips_required_output": "phase2/stage2/synth/post_dft_netlist.v"}))  # no flag
    step = {"id": 999, "name": "Post-DFT optimization",
            "required_outputs": ["phase2/stage2/synth/post_dft_netlist.v"]}
    assert FCC.check_step(tmp_path, step, waivers={}).status == "MISSING"


def test_early_missing_shared_dir_marker_cannot_mask_other_step(tmp_path):
    """ADVERSARIAL (skeptic 2): phase2/stage2/synth/ is SHARED by step-9 (synth,
    output netlist.v) and step-12's post_dft_not_run.json. If synthesis GENUINELY
    fails (no netlist.v), the step-12 marker — which owns post_dft_netlist.v, a
    DIFFERENT output — must NOT mask the real step-9 synth FAIL. Step 9 stays
    MISSING."""
    s = _synth(tmp_path)
    (s / "post_dft_not_run.json").write_text(_own_marker())  # owns post_dft_netlist.v
    step9 = {"id": 999, "name": "Synthesis (Yosys -> mapped netlist)",
             "required_outputs": ["phase2/stage2/synth/netlist.v"]}  # a DIFFERENT output
    res = FCC.check_step(tmp_path, step9, waivers={})
    assert res.status == "MISSING", (res.status, res.reasons)


def test_early_missing_signoff_not_masked_by_stray_skip(tmp_path):
    """ADVERSARIAL (skeptic 1): a DRC/LVS sign-off with all outputs absent must
    NOT be maskable by a stray skip-json in the shared reports/phase3/ dir. A
    marker owning a DIFFERENT sign-off output (lvs.rpt), or a bare skip-json,
    cannot promote the DRC step → stays MISSING (a real sign-off gap FAILs)."""
    p3 = tmp_path / "reports" / "phase3"
    p3.mkdir(parents=True)
    (p3 / "stray.json").write_text(json.dumps({"verdict": "SKIPPED"}))
    (p3 / "lvs_not_run.json").write_text(json.dumps({
        "verdict": "SKIPPED-CONDITION", "capability_flag": "cap:x",
        "skips_required_output": "reports/phase3/lvs.rpt"}))  # owns lvs, not drc
    step31 = {"id": 999, "name": "Physical Verification (DRC + LVS + ERC)",
              "required_outputs": ["reports/phase3/drc_signoff.rpt"]}
    assert FCC.check_step(tmp_path, step31, waivers={}).status == "MISSING"


def test_early_missing_broad_glob_declaration_cannot_mask_signoff(tmp_path):
    """ADVERSARIAL RESIDUAL (exact-match hardening): a marker declaring a BROAD
    GLOB `skips_required_output` like `reports/phase3/*` must NOT mask a sign-off
    whose exact output (drc_signoff.rpt) is absent. Ownership is EXACT-match only,
    so a wildcard declaration owns nothing → step stays MISSING."""
    p3 = tmp_path / "reports" / "phase3"
    p3.mkdir(parents=True)
    (p3 / "forged.json").write_text(json.dumps({
        "verdict": "SKIPPED-CONDITION", "capability_flag": "cap:forged",
        "skips_required_output": "reports/phase3/*"}))
    step31 = {"id": 999, "name": "Physical Verification (DRC + LVS + ERC)",
              "required_outputs": ["reports/phase3/drc_signoff.rpt"]}
    assert FCC.check_step(tmp_path, step31, waivers={}).status == "MISSING"


def test_early_missing_concrete_marker_cannot_glob_mask_glob_output(tmp_path):
    """ADVERSARIAL RESIDUAL (exact-match hardening): if a step has a GLOB
    required-output (`.../*.v`), a foreign concrete marker naming a `.v` file in
    the same dir must NOT own it (exact-match: `.../foo.v` != `.../*.v`). The step
    stays MISSING; only a marker declaring the literal `*.v` spec could own it."""
    s = _synth(tmp_path)
    (s / "post_dft_not_run.json").write_text(_own_marker(
        out="phase2/stage2/synth/post_dft_netlist.v"))  # concrete .v
    step = {"id": 999, "name": "some step with a glob output",
            "required_outputs": ["phase2/stage2/synth/*.v"]}  # glob spec
    assert FCC.check_step(tmp_path, step, waivers={}).status == "MISSING"


def test_early_missing_present_output_passes_no_sibling_consult(tmp_path):
    """§4.05 no-leak: when the required output IS present, the step is evidenced
    and the sibling path is never consulted — even if a stray owning skip sibling
    exists next to it, the real output governs (never a false SKIPPED-CONDITION)."""
    s = _synth(tmp_path)
    (s / "post_dft_netlist.v").write_text("module m; endmodule\n")
    (s / "post_dft_not_run.json").write_text(_own_marker(reason="stale marker"))
    step = {"id": 999, "name": "Post-DFT optimization",
            "required_outputs": ["phase2/stage2/synth/post_dft_netlist.v"]}
    res = FCC.check_step(tmp_path, step, waivers={})
    assert res.status not in ("MISSING", "SKIPPED-CONDITION"), (res.status, res.reasons)
    assert any("post_dft_netlist.v" in e for e in res.evidence), res.evidence


def test_early_missing_env_unavailable_waiver_takes_precedence(tmp_path):
    """An explicit ENV_UNAVAILABLE waiver still wins over the honest sibling: the
    step becomes WAIVED (the approved path), not SKIPPED-CONDITION."""
    s = _synth(tmp_path)
    (s / "post_dft_not_run.json").write_text(_own_marker())
    step = {"id": 999, "name": "Post-DFT optimization",
            "required_outputs": ["phase2/stage2/synth/post_dft_netlist.v"]}
    waivers = {999: {"_env_unavailable": True, "reason": "tool not on host",
                     "approver": "field-agent-attest"}}
    assert FCC.check_step(tmp_path, step, waivers=waivers).status == "WAIVED"


def test_early_missing_second_of_two_outputs_present_no_promotion(tmp_path):
    """When at least ONE required_output is present the step is evidenced and the
    early MISSING branch is not taken — an owning skip sibling for the OTHER
    output does not down-grade an evidenced step."""
    s = _synth(tmp_path)
    (s / "post_dft_netlist.v").write_text("module m; endmodule\n")
    (s / "post_dft_not_run.json").write_text(_own_marker(reason="stale"))
    step = {"id": 999, "name": "Post-DFT optimization",
            "required_outputs": ["phase2/stage2/synth/post_dft_netlist.v",
                                  "phase2/stage2/synth/never_made.v"]}
    assert FCC.check_step(tmp_path, step, waivers={}).status != "SKIPPED-CONDITION"
