"""v0.2.80 — #448: Step 5 never trusts the bare all_proved field.

Field-audit residual of #440: the runner no longer fabricates formal
results, but the flow gate was still `json_field_true: all_proved` — a
hand-planted `{"all_proved": true}` results.json passed with no .sby
and no SymbiYosys run anywhere.

Pins (acceptance criteria from the issue):
  * the OLD audited fake shape (`all_proved:true`, evidence =
    "iverilog reference TB scenarios", no sby artifacts) → FAIL;
  * a real proof chain (.sby whose referenced files exist + sby log
    with smtbmc signature and PASS status) → PASS;
  * broken chain variants (missing .sby refs / no PASS log / dangling
    evidence pointer) → FAIL;
  * #440's honest SKIPPED-CONDITION manifest → rc 2 (vacuous);
  * the yaml gate now invokes the chain check, not json_field_true.

chip-AGNOSTIC: structural artifact fixtures only.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import formal_proof_evidence_check as FPC  # noqa: E402

PLUGIN = Path(__file__).resolve().parent.parent.parent
_YAML = (PLUGIN / "flow" / "phase1_phase2_phase3.yaml").read_text()

_SBY_PASS_LOG = """\
SBY 12:00:00 [task] engine_0: starting process "smtbmc yices"
SBY 12:00:09 [task] summary: Elapsed clock time [H:MM:SS (secs)]: 0:00:09
SBY 12:00:09 [task] DONE (PASS, rc=0)
"""


def _formal(tmp_path):
    f = tmp_path / "phase2" / "stage1" / "formal"
    f.mkdir(parents=True)
    return f


def test_old_fake_all_proved_fails(tmp_path):
    f = _formal(tmp_path)
    (f / "results.json").write_text(json.dumps({
        "verdict": "PASS", "all_proved": True,
        "evidence": "iverilog reference TB scenarios"}))
    rep = FPC.audit(tmp_path)
    assert rep["rc"] == 1 and rep["verdict"] == "FAIL"
    joined = " ".join(rep["findings"])
    assert "SBY_CHAIN_BROKEN" in joined and "SBY_LOG_MISSING" in joined


def test_real_proof_chain_passes(tmp_path):
    f = _formal(tmp_path)
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "top.sv").write_text("module top; endmodule\n")
    (f / "assertions.sv").write_text("module asserts; endmodule\n")
    (f / "constraints.sby").write_text(
        "[options]\nmode prove\n[engines]\nsmtbmc\n[script]\n"
        "read -formal assertions.sv\n"
        "read -formal phase2/stage1/rtl/top.sv\nprep -top top\n")
    (f / "constraints.sby.log").write_text(_SBY_PASS_LOG)
    (f / "results.json").write_text(json.dumps({
        "verdict": "PASS", "all_proved": True,
        "property_denominator": 1, "authored_property_count": 1,
        "unresolved_obligations": [],
        "bounded_vs_unbounded_scope": ["unbounded prove"],
        "sby": "phase2/stage1/formal/constraints.sby",
        "elaborated_sby": "phase2/stage1/formal/constraints.sby",
        "evidence": "phase2/stage1/formal/constraints.sby.log",
        "proof_transcript": "phase2/stage1/formal/constraints.sby.log"}))
    rep = FPC.audit(tmp_path)
    assert rep["rc"] == 0 and rep["verdict"] == "PASS", rep


def test_completed_claim_without_property_denominator_fails(tmp_path):
    """#1974 pre-fix-compatible RED: proof evidence alone is a subset claim."""
    f = _formal(tmp_path)
    (f / "assertions.sv").write_text("module asserts; endmodule\n")
    (f / "constraints.sby").write_text(
        "[script]\nread -formal assertions.sv\nprep -top asserts\n")
    (f / "constraints.sby.log").write_text(_SBY_PASS_LOG)
    (f / "results.json").write_text(json.dumps({
        "verdict": "PASS", "all_proved": True,
        "evidence": "phase2/stage1/formal/constraints.sby.log"}))
    rep = FPC.audit(tmp_path)
    assert rep["rc"] == 1 and rep["verdict"] == "FAIL", rep
    assert any("PROPERTY_DENOMINATOR_MISSING" in row
               for row in rep["findings"]), rep


def test_completed_claim_that_skipped_required_expert_receipt_fails(tmp_path):
    f = _formal(tmp_path)
    (f / "assertions.sv").write_text("module asserts; endmodule\n")
    (f / "constraints.sby").write_text(
        "[script]\nread -formal assertions.sv\nprep -top asserts\n")
    (f / "constraints.sby.log").write_text(_SBY_PASS_LOG)
    (f / "results.json").write_text(json.dumps({
        "verdict": "PASS", "all_proved": True,
        "property_denominator": 1, "authored_property_count": 1,
        "unresolved_obligations": [],
        "expert_fallback_required": True,
        "expert_fallback_invoked": False,
        "expert_fallback_receipt": None,
        "bounded_vs_unbounded_scope": ["unbounded prove"],
        "sby": "phase2/stage1/formal/constraints.sby",
        "elaborated_sby": "phase2/stage1/formal/constraints.sby",
        "evidence": "phase2/stage1/formal/constraints.sby.log",
        "proof_transcript": "phase2/stage1/formal/constraints.sby.log"}))
    rep = FPC.audit(tmp_path)
    assert rep["rc"] == 1 and rep["verdict"] == "FAIL", rep
    assert any("EXPERT_FALLBACK_NOT_INVOKED" in row
               for row in rep["findings"]), rep


def test_sby_referencing_missing_files_fails(tmp_path):
    f = _formal(tmp_path)
    (f / "constraints.sby").write_text(
        "[script]\nread -formal rtl/ghost.sv\nprep -top assertions_l3\n")
    (f / "constraints.sby.log").write_text(_SBY_PASS_LOG)
    (f / "results.json").write_text(json.dumps({"all_proved": True}))
    rep = FPC.audit(tmp_path)
    assert rep["rc"] == 1
    assert any("SBY_CHAIN_BROKEN" in x for x in rep["findings"])


def test_failing_sby_log_fails(tmp_path):
    f = _formal(tmp_path)
    (f / "a.sv").write_text("x")
    (f / "c.sby").write_text("[script]\nread -formal a.sv\n")
    (f / "c.sby.log").write_text(
        "SBY engine_0 smtbmc\nSBY DONE (FAIL, rc=2)\n")
    (f / "results.json").write_text(json.dumps({"all_proved": True}))
    rep = FPC.audit(tmp_path)
    assert rep["rc"] == 1


def test_dangling_evidence_pointer_fails(tmp_path):
    f = _formal(tmp_path)
    (f / "a.sv").write_text("x")
    (f / "c.sby").write_text("[script]\nread -formal a.sv\n")
    (f / "c.sby.log").write_text(_SBY_PASS_LOG)
    (f / "results.json").write_text(json.dumps({
        "all_proved": True, "evidence": "formal/ghost.log"}))
    rep = FPC.audit(tmp_path)
    assert rep["rc"] == 1
    assert any("EVIDENCE_MISSING" in x for x in rep["findings"])


def test_honest_skip_manifest_is_vacuous(tmp_path):
    f = _formal(tmp_path)
    (f / "results.json").write_text(json.dumps({
        "verdict": "SKIPPED-CONDITION", "reason": "no proof tool ran"}))
    rep = FPC.audit(tmp_path)
    assert rep["rc"] == 2 and rep["verdict"] == "SKIPPED-CONDITION"


def test_yaml_gate_uses_chain_check_not_field_trust():
    assert "formal_proof_evidence_check ." in _YAML
    assert 'json_field_true: {file: "phase2/stage1/formal/results.json"' \
        not in _YAML
