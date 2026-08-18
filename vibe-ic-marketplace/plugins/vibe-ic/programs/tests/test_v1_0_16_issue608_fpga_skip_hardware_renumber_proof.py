"""ORGANIC #608 [LOW/P3] — flow_compliance_check hardcoded the FPGA-board steps
that --skip-hardware waives as the literal tuple `sid in (6, 37)`. A Wave 90 /
v1.6.14 flow renumber (+1 for every id >= 18) moved the FPGA-final on-board
sign-off step 37 -> 39 (and made id 37 = "GDSII output"), but the skip set was
never updated. So: (a) the real FPGA-final step (now 39) was NOT waived by
--skip-hardware, and (b) the non-FPGA GDSII step (now 37) WAS incorrectly
waived. Separately, the FPGA-final json gate evaluated UNCONDITIONALLY on a
default run and hard-FAILed "field not found: all_scenarios_passed" even when
on_board_pass.json honestly self-reported {"verdict":"SKIP"}.

Fix:
  Part 1 — derive the waived FPGA-board id set from the canonical name->id
  table (_FPGA_BOARD_STEP_IDS = {6, 39}); renumber-proof.
  Part 2 — a json_field_true gate whose evidence artifact self-reports
  verdict ∈ SKIP/SKIPPED/SKIPPED-CONDITION (and the success field is therefore
  absent) promotes the step to SKIPPED-CONDITION, not FAIL (#433c doctrine).

The FPGA-final step is referenced here by its CANONICAL NAME via the name->id
table — NOT a literal id — so a future renumber updates the table once and this
test follows, never silently re-breaking (per the issue's explicit ask).

NEGATIVE no-leak:
  - --skip-hardware must NOT waive the GDSII step (id 37) as an FPGA step.
  - a REAL fpga failure (all_scenarios_passed present and False) still FAILs.
  - a json gate whose artifact self-reports a NON-skip verdict (FAIL) with the
    field absent still FAILs.

chip-AGNOSTIC: keyed on canonical step roles + verdict tokens, no chip literal.
"""
import json
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import flow_compliance_check as F  # noqa: E402

# Resolve the step ids by CANONICAL NAME (renumber-proof), never a literal.
FPGA_FINAL_ID = F._ENV_UNAVAILABLE_STEP_NAME_TO_ID["fpga_final_signoff"]
FPGA_EARLY_ID = F._ENV_UNAVAILABLE_STEP_NAME_TO_ID["fpga_early_prototype"]
GATE = {"json_field_true": {
    "file": "reports/phase2/fpga/on_board_pass.json",
    "field": "all_scenarios_passed"}}


def _proj(tmp_path, obj):
    d = tmp_path / "reports" / "phase2" / "fpga"
    d.mkdir(parents=True, exist_ok=True)
    (d / "on_board_pass.json").write_text(json.dumps(obj))
    return tmp_path


def _step(sid, name):
    return {"id": sid, "name": name, "stage": "stage4", "gate": GATE}


def test_fpga_board_id_set_is_derived_and_current():
    # Part 1: the waived set follows the name->id table; 37 (GDSII) excluded.
    assert FPGA_FINAL_ID in F._FPGA_BOARD_STEP_IDS
    assert FPGA_EARLY_ID in F._FPGA_BOARD_STEP_IDS
    assert 37 not in F._FPGA_BOARD_STEP_IDS  # GDSII is NOT an FPGA-board step


def test_skip_hardware_waives_fpga_final_by_name(tmp_path):
    proj = _proj(tmp_path, {"verdict": "SKIP"})
    r = F.check_step(proj, _step(FPGA_FINAL_ID, "FPGA final sign-off"),
                     {}, skip_hardware=True)
    assert r.status == "WAIVED"


def test_skip_hardware_does_not_waive_gdsii_step(tmp_path):
    # NO-LEAK: a non-FPGA backend step at the OLD literal id (37) must not be
    # waived as an FPGA step.
    proj = _proj(tmp_path, {"all_scenarios_passed": True})
    r = F.check_step(proj, _step(37, "GDSII output"), {}, skip_hardware=True)
    assert r.status == "PASS"


def test_default_run_self_reported_skip_is_skipped_condition(tmp_path):
    # Part 2: default run (no --skip-hardware); on_board_pass.json self-reports
    # SKIP and lacks the success field → SKIPPED-CONDITION, not FAIL.
    proj = _proj(tmp_path, {"verdict": "SKIP", "evidence": "not run"})
    r = F.check_step(proj, _step(FPGA_FINAL_ID, "FPGA final sign-off"), {})
    assert r.status == "SKIPPED-CONDITION"


def test_real_fpga_failure_still_fails(tmp_path):
    # NO-LEAK: the success field present and False is a real FAIL.
    proj = _proj(tmp_path, {"verdict": "PASS", "all_scenarios_passed": False})
    r = F.check_step(proj, _step(FPGA_FINAL_ID, "FPGA final sign-off"), {})
    assert r.status == "FAIL"


def test_nonskip_verdict_absent_field_still_fails(tmp_path):
    # NO-LEAK: artifact self-reports a NON-skip verdict, field absent → FAIL.
    proj = _proj(tmp_path, {"verdict": "FAIL"})
    r = F.check_step(proj, _step(FPGA_FINAL_ID, "FPGA final sign-off"), {})
    assert r.status == "FAIL"


def test_genuine_pass(tmp_path):
    proj = _proj(tmp_path, {"all_scenarios_passed": True})
    r = F.check_step(proj, _step(FPGA_FINAL_ID, "FPGA final sign-off"), {})
    assert r.status == "PASS"
