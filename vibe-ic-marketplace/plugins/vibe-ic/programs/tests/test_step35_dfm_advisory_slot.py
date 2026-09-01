"""Step 35 — the DFM screen is wired where its own declaration says it goes.

MEASURED DEFECT (today's main, real converged run ihp-sg13g2):
`dfm_screen_check.audit()` resolves two verdict tiers, PASS and
PASS_WITH_ADVISORIES, and then returned a hard-coded ``"rc": 0`` for BOTH.
Step 35 wired it into the BLOCKING `program_exit_zero` slot, where
`flow_compliance_check` maps rc 0 -> PASS and rc 2 -> VACUOUS_PASS — both
passing. So for any real project that sub-gate was structurally tautological
(nothing the program could compute could move it) and the PASS_WITH_ADVISORIES
tier never reached the flow report: the step line read

    35  PASS   reasons: []

with a screen that had raised a finding.

The fix is a PAIR, and neither half is correct alone:
  * the program stops collapsing its tiers onto one exit code (rc 1 =
    advisory);
  * the flow moves that sub-gate to `advisory_program_exit_zero` (#306), the
    slot built for a gate that declares itself advisory.

Doing only the first would turn every DFM optimisation finding into a hard
Step-35 FAIL — a duplicate of the Step-34 density gate, for a condition
OpenROAD has no repair pass for. Doing only the second would wire a slot that
still receives rc 0 for everything.

chip-AGNOSTIC: flow-definition + gate-evaluator assertions only.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

_PROGRAMS = Path(__file__).resolve().parent.parent
_PLUGIN = _PROGRAMS.parent
sys.path.insert(0, str(_PROGRAMS))

_spec = importlib.util.spec_from_file_location(
    "flow_compliance_check", _PROGRAMS / "flow_compliance_check.py")
_flow = importlib.util.module_from_spec(_spec)
sys.modules["flow_compliance_check"] = _flow
_spec.loader.exec_module(_flow)

_FLOW_YAML = _PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
_STEPS = {s["id"]: s for s in
          yaml.safe_load(_FLOW_YAML.read_text())["steps"]
          if isinstance(s, dict)}
_STEP35 = _STEPS[35]
_ARTEFACT = "reports/phase3/dfm_screen.json"


def _sub_gates():
    return [g for g in _STEP35["gate"]["all_of"] if isinstance(g, dict)]


def _slot_of(program: str):
    for sub in _sub_gates():
        for key, val in sub.items():
            cmd = val if isinstance(val, str) else (
                val.get("command") if isinstance(val, dict) else "")
            if isinstance(cmd, str) and cmd.split(" ")[0] == program:
                return key
    return None


# ── the declaration and the slot must agree ─────────────────────────────────

def test_dfm_screen_check_declares_itself_a_producer_not_a_gate():
    spec = importlib.util.spec_from_file_location(
        "flow_gate_enforcement_audit",
        _PROGRAMS / "flow_gate_enforcement_audit.py")
    fga = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fga)
    assert fga.declared_intent(_PROGRAMS, "dfm_screen_check") is None


def test_step35_declares_dfm_screen_as_a_program_output():
    assert _slot_of("dfm_screen_check") is None
    assert _STEP35["program_outputs"] == [{
        "program": "dfm_screen_check",
        "path": _ARTEFACT,
        "verdict_field": "verdict",
    }]


def test_step35_keeps_a_blocking_artefact_predicate():
    """DIRECTION-1 GUARD. Moving the program to the advisory slot must not
    leave Step 35 with nothing that can fail: a step whose screen never ran
    cannot be certified done."""
    blocking = [g for g in _sub_gates() if "files_exist" in g]
    assert blocking, "Step 35 lost its blocking half"
    assert any(_ARTEFACT in g["files_exist"] for g in blocking)


def test_step35_structure_is_otherwise_unchanged():
    """DIRECTION-1 GUARD on the surrounding declaration."""
    assert _STEP35["stage"] == "stage4"
    assert _STEP35["blocks_on"] == [34]
    assert _STEP35["required_outputs"] == [_ARTEFACT]
    assert _STEP35["programs"] == ["dfm_screen_check"]


def test_no_blocking_slot_still_names_dfm_screen_check():
    for sub in _sub_gates():
        assert "program_exit_zero" not in sub, (
            "the blocking slot is gone from Step 35; if it comes back it "
            "turns every advisory into a step FAIL")
        assert "optional_program_exit_zero" not in sub


# ── behaviour of the wired gate ─────────────────────────────────────────────

def _project(tmp_path, with_artefact: bool,
             verdict: str = "PASS_WITH_ADVISORIES"):
    if with_artefact:
        for rel in (_ARTEFACT, "reports/phase2/gates/dfm_screen.json"):
            art = tmp_path / rel
            art.parent.mkdir(parents=True, exist_ok=True)
            art.write_text('{"verdict": "' + verdict + '"}')
    return tmp_path


def test_an_advisory_finding_is_a_typed_non_gate_output(tmp_path):
    project = _project(tmp_path, True)
    records = _flow._collect_program_output_records(project, _STEP35)
    assert records[0]["verdict"] == "PASS_WITH_ADVISORIES"
    assert records[0]["enforcement"] == "NOT_A_GATE"


def test_a_missing_artefact_still_fails_step35(tmp_path):
    """DIRECTION-1 GUARD: blocking coverage was not traded away. A run whose
    screen produced nothing must not be certified."""
    passed, _ = _flow._evaluate_gate(
        _project(tmp_path, False), _STEP35["gate"])
    assert passed is False


def test_a_clean_screen_records_a_pass_output(tmp_path):
    project = _project(tmp_path, True, verdict="PASS")
    records = _flow._collect_program_output_records(project, _STEP35)
    assert records[0]["verdict"] == "PASS"
    assert records[0]["role"] == "PRODUCER_OUTPUT"
