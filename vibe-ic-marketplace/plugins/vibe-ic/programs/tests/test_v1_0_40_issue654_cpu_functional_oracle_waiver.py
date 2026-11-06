"""ORGANIC #654/#1975 — connectivity evidence is preserved without granting
functional verification credit.

For verification_track=generic_full_stack (processor/SoC, no command/opcode
oracle, no L10 golden vectors), reference_tb is WAIVED and only a
connectivity-only TB writes sim_full_stack/results.json. The oracle-sim
bridge that writes the canonical phase2/stage1/sim/{results.xml,pass.flag}
fires ONLY when vectors_passed == vectors_total > 0 — unreachable for this
class — so the canonical sim/ dir stayed EMPTY and Step 4's gate
(files_exist sim/results.xml OR pass.flag) FAILed for ANY such IC,
independent of RTL quality.

Fix (class-driven): the runner now emits a CONNECTIVITY bridge
(_emit_connectivity_sim_bridge) carrying verdict CONNECTIVITY_PASS,
functional_verified=false, capability_gap cap:cpu_functional_oracle, and an
<evidence> backlink to the real full_stack.log transcript; a new gate program
cpu_functional_oracle_waiver_check validates it as connectivity-only evidence.
Issue #1975 supersedes the old waiver policy: a substantiated bridge is now
blocking INCOMPLETE (rc=1) until a non-vacuous professional functional JUnit
result exists. A forged record (no/empty evidence, or
functional_verified=true) also FAILs — NO-LEAK.
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import cpu_functional_oracle_waiver_check as G  # noqa: E402
import flow_compliance_check as F  # noqa: E402


def _mk_conn_run(tmp_path):
    """Build a project tree whose connectivity full-stack TB ran to
    FULL_STACK_TB_DONE; return (project, transcript)."""
    run = tmp_path / "phase2/stage1/sim_full_stack/generic_full_stack_run"
    run.mkdir(parents=True)
    log = run / "full_stack.log"
    log.write_text("FULL_STACK_TB_INIT\nFULL_STACK_TB_DONE bytes=0 bits=0\n")
    return tmp_path, log


# ── runner bridge emitter ───────────────────────────────────────────────────







# ── gate program verdicts ───────────────────────────────────────────────────



def test_gate_na_for_genuine_functional_pass(tmp_path):
    sim = tmp_path / "phase2/stage1/sim"
    sim.mkdir(parents=True)
    (sim / "results.xml").write_text(
        "<results><verdict>PASS</verdict><evidence>oracle.log</evidence>"
        "<vectors_passed>8</vectors_passed><vectors_total>8</vectors_total>"
        "<verification_track>oracle_tb</verification_track></results>\n")
    code, _ = G._evaluate(tmp_path)
    assert code == 0  # functional PASS owned by the functional gates


def test_gate_vacuous_when_no_results_xml(tmp_path):
    code, _ = G._evaluate(tmp_path)
    assert code == 2


def test_gate_fails_forged_functional_verified_true(tmp_path):
    # NO-LEAK: a connectivity verdict that ALSO asserts functional_verified
    # is a forgery — it must FAIL, never be waived.
    project, log = _mk_conn_run(tmp_path)
    sim = project / "phase2/stage1/sim"
    sim.mkdir(parents=True)
    (sim / "results.xml").write_text(
        "<results><verdict>CONNECTIVITY_PASS</verdict>"
        "<functional_verified>true</functional_verified>"
        "<capability_gap>cap:cpu_functional_oracle</capability_gap>"
        f"<evidence>{log.relative_to(project)}</evidence></results>\n")
    code, msg = G._evaluate(project)
    assert code == 1, msg
    assert "forged" in msg.lower() or "functional_verified=true" in msg


def test_gate_fails_broken_evidence_pointer(tmp_path):
    # NO-LEAK: a waiver with an unreviewable / dangling evidence pointer FAILs.
    sim = tmp_path / "phase2/stage1/sim"
    sim.mkdir(parents=True)
    (sim / "results.xml").write_text(
        "<results><verdict>CONNECTIVITY_PASS</verdict>"
        "<functional_verified>false</functional_verified>"
        "<capability_gap>cap:cpu_functional_oracle</capability_gap>"
        "<evidence>nope/missing.log</evidence></results>\n")
    code, msg = G._evaluate(tmp_path)
    assert code == 1, msg


def test_gate_fails_when_evidence_missing_done_marker(tmp_path):
    # NO-LEAK: evidence transcript exists but never reached FULL_STACK_TB_DONE
    # → connectivity binding was not demonstrated → FAIL.
    run = tmp_path / "phase2/stage1/sim_full_stack/generic_full_stack_run"
    run.mkdir(parents=True)
    log = run / "full_stack.log"
    log.write_text("FULL_STACK_TB_INIT\n(elaboration error)\n")
    sim = tmp_path / "phase2/stage1/sim"
    sim.mkdir(parents=True)
    (sim / "results.xml").write_text(
        "<results><verdict>CONNECTIVITY_PASS</verdict>"
        "<functional_verified>false</functional_verified>"
        "<capability_gap>cap:cpu_functional_oracle</capability_gap>"
        f"<evidence>{log.relative_to(tmp_path)}</evidence></results>\n")
    code, msg = G._evaluate(tmp_path)
    assert code == 1, msg


# ── gate program CLI / json ─────────────────────────────────────────────────



# ── end-to-end: flow_compliance_check Step-4 promotion ──────────────────────

def _step4_gate():
    """Minimal Step-4 gate spec mirroring the flow yaml all_of structure."""
    return {
        "id": 4, "name": "Simulation", "stage": "stage1",
        "gate": {"all_of": [
            {"files_exist": ["phase2/stage1/sim/results.xml",
                             "phase2/stage1/sim/pass.flag"],
             "any_of": True},
            {"optional_program_exit_zero": {
                "command": ("cpu_functional_oracle_waiver_check . "
                            "--json reports/phase2/gates/cfo_waiver.json"),
                "condition_files_exist": ["phase2/stage1/sim/results.xml"]}},
        ]},
    }




def test_step4_hard_fails_without_any_sim_artifact(tmp_path):
    # NO-LEAK: with NO sim artifact at all, Step 4 still FAILs (the fix does
    # not blanket-pass the class; it only credits a substantiated bridge).
    (tmp_path / "phase2/stage1/sim").mkdir(parents=True)
    res = F.check_step(tmp_path, _step4_gate(), waivers={})
    assert res.status != "WAIVED"
    assert res.status != "PASS"
