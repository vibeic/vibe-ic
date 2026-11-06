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

#: The EXEMPLAR pair these cases are built on: a capability flag the registry
#: declares open, and the output that flag is bound to. The mechanism under
#: test is the STRICT sibling promotion, not any particular step, so any
#: registered pair serves.
#:
#: It used to be `cap:post_dft_scan_optimization` bound to
#: "phase2/stage2/synth/post_dft_netlist.v" — the step-12 shape. That flag was
#: REMOVED from the registry on 2026-09-16 (lane icspm5, R-0915-57): it claimed
#: the open-source container could not re-optimise a scan netlist, and
#: `design_one_shot_runner` does exactly that with yosys on every run that has
#: one, so no producer emits it any anymore. The exemplar moves to a pair that
#: is still registered; the cases below are unchanged, because none of them was
#: about post-DFT optimisation in particular. The step-9/step-12 SHARED
#: DIRECTORY case keeps its own concrete paths, since the directory sharing is
#: the thing it tests.
_EX_FLAG = "cap:atpg_signoff_coverage"
_EX_OUT = "phase2/stage2/dft/coverage.json"
_EX_DIR = "phase2/stage2/dft"


def _synth(tmp_path):
    """The exemplar's own output directory (named `_synth` historically)."""
    s = tmp_path / "phase2" / "stage2" / "dft"
    s.mkdir(parents=True)
    (tmp_path / "phase2" / "stage2" / "synth").mkdir(parents=True,
                                                     exist_ok=True)
    return s


def _own_marker(reason="the producer disclosed a gap and owns the output",
                out=_EX_OUT,
                flag=_EX_FLAG, verdict="NOT_APPLICABLE"):
    """A well-formed OWNING skip-marker payload (what the runner now emits)."""
    return json.dumps({"verdict": verdict, "reason": reason,
                       "capability_flag": flag, "skips_required_output": out})
