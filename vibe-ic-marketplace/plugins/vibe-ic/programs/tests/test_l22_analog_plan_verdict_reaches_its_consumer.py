"""The L22 analog projection declared an intent it was not wired for.

`flow_gate_enforcement_audit` on v1.14.75 (and on the v1.14.71 hygiene shard):

    ORPHANED — declare an intent, are NOT in the flow definition,
    and no repo-gate suite invokes them either:
      l22_analog_verification_plan_emit  (declared advisory)
    [FAIL] 1 NEW gate(s) declare an intent they are not wired for

The program IS reached — `phase1_doc_one_shot_runner` calls it at the tail of
Step D1 — but through `from <module> import run`, which is none of that audit's
five venues, and the adapter read only `emitted_count`. So there were TWO
consumers and NEITHER could read an outcome, which is what "declares an intent
it is not wired for" means here.

Issue #1980 classifies this correctly as a producer: the Phase-1 runner owns
execution, Step D1 declares the L22 output, and no gate denominator row is
created for the emitter itself.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

PROGRAMS = Path(__file__).resolve().parents[1]
PLUGIN = PROGRAMS.parent
FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import flow_compliance_check as FC               # noqa: E402
import phase1_doc_one_shot_runner as RUNNER      # noqa: E402
from l22_analog_verification_plan_emit import run as EMIT  # noqa: E402

COMMAND = "l22_analog_verification_plan_emit . --dry-run"


# ── fixtures ──────────────────────────────────────────────────────────────
def _write(path: Path, body: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def _l22(project: Path) -> Path:
    path = project / "phase1/generated_docs/L22_VERIFICATION_PLAN.json"
    _write(path, {"doc_id": "L22", "doc_name": "L22_VERIFICATION_PLAN",
                  "applicability": "APPLICABLE",
                  "extraction_status": "EXTRACTED",
                  "fields": {"coverage_goals": [], "formal_properties": [],
                             "regression_matrix": {},
                             "verification_plan_present": "implicit"}})
    return path


def _analog_project(project: Path, blocks) -> Path:
    gd = project / "phase1/generated_docs"
    _write(gd / "L1_DATASHEET.json", {
        "doc_id": "L1", "class": "mixed_signal_adc",
        "description": ("A data converter with an analog conversion core and "
                        "a digital serial output bitstream.")})
    _write(gd / "L5_ADI_SPEC.json", {
        "doc_id": "L5", "no_analog": False, "analog_blocks": blocks,
        "signaling_summary": "Digital serial output bitstream."})
    _write(gd / "L7_VERIFICATION.json", {
        "doc_id": "L7", "verification_strategy": [{
            "phase": "dc_operating_point",
            "method": "Run DC operating point sweeps for the regulator.",
            "evidence": "input/docs/L5_analog.md (Verification intent section)",
            "extraction_strategy": "verification_intent_bullet_v634"}]})
    return _l22(project)


_GOOD_BLOCK = {
    "name": "supply_regulator", "type": "ldo", "low_confidence": False,
    "spec": {"specs": [{"name": "Line regulation", "target_raw": "<= 1",
                        "unit": "mV/V",
                        "source": "input/docs/L5_analog.md"}]},
}
#: The SAME block with no name, block or type — an L5 harvester that lifted a
#: spec table and never found the heading it belongs to. The class is analog and
#: L5 declares a block, so the projection is OWED and cannot be made.
_NAMELESS_BLOCK = {"low_confidence": False, "spec": _GOOD_BLOCK["spec"]}


@pytest.fixture
def ok_project(tmp_path):
    p = tmp_path / "ok"
    _analog_project(p, [_GOOD_BLOCK])
    return p


@pytest.fixture
def refusing_project(tmp_path):
    p = tmp_path / "refuse"
    _analog_project(p, [_NAMELESS_BLOCK])
    return p


@pytest.fixture
def digital_project(tmp_path):
    p = tmp_path / "digital"
    gd = p / "phase1/generated_docs"
    _write(gd / "L1_DATASHEET.json", {
        "doc_id": "L1", "class": "digital_cmd_driven",
        "description": "A command-driven register block with a serial port."})
    _write(gd / "L5_ADI_SPEC.json",
           {"doc_id": "L5", "no_analog": True, "analog_blocks": []})
    _l22(p)
    return p


# ── the emitter's own verdict ─────────────────────────────────────────────
def test_the_three_outcomes_are_distinguishable_in_process(
        ok_project, refusing_project, digital_project):
    assert EMIT(ok_project, dry_run=True)["status"] == "OK"
    assert EMIT(refusing_project, dry_run=True)["status"] == "REFUSED"
    assert EMIT(digital_project, dry_run=True)["status"] == "NOT_APPLICABLE"


def _rc(project: Path) -> int:
    return subprocess.run(
        [sys.executable, str(PROGRAMS / "l22_analog_verification_plan_emit.py"),
         str(project), "--dry-run"],
        capture_output=True, text=True, timeout=300).returncode


def test_the_exit_code_is_not_a_constant(
        ok_project, refusing_project, digital_project):
    """PRE-FIX `main` returned `0 if status != "ERROR" else 1` and no path ever
    produced "ERROR", so the exit code was a CONSTANT and any exit-code wiring
    would have recorded PASS on every project alive — a gate that cannot
    refuse."""
    assert (_rc(ok_project), _rc(refusing_project), _rc(digital_project)) \
        == (0, 1, 2)


# ── the producer-output consumer ──────────────────────────────────────────
def _program_output_record(project: Path):
    step = next(s for s in yaml.safe_load(FLOW.read_text())["steps"]
                if s["id"] == "D1")
    return FC._collect_program_output_records(project, step)[0]


def test_a_green_emitter_output_is_recorded(ok_project):
    record = _program_output_record(ok_project)
    assert record["produced"] is True
    assert record["verdict"] == "EXTRACTED"
    assert record["enforcement"] == "NOT_A_GATE"


def test_a_refusal_is_runner_owned_not_flattened_by_a_gate(refusing_project):
    assert EMIT(refusing_project, dry_run=True)["status"] == "REFUSED"
    flow = yaml.safe_load(FLOW.read_text())
    assert COMMAND not in str([step.get("gate") for step in flow["steps"]])


def test_a_digital_project_keeps_the_declared_l22_output(digital_project):
    record = _program_output_record(digital_project)
    assert record["produced"] is True
    assert record["role"] == "PRODUCER_OUTPUT"


# ── the wiring itself ─────────────────────────────────────────────────────
def _clauses(node, out):
    if isinstance(node, dict):
        for key, val in node.items():
            if key == "advisory_program_exit_zero":
                out.append(val)
            _clauses(val, out)
    elif isinstance(node, list):
        for item in node:
            _clauses(item, out)
    return out


def test_the_flow_definition_declares_the_producer_and_output():
    step = next(s for s in yaml.safe_load(FLOW.read_text())["steps"]
                if s["id"] == "D1")
    assert "l22_analog_verification_plan_emit" in step["programs"]
    assert step["program_outputs"] == [{
        "program": "l22_analog_verification_plan_emit",
        "path": "phase1/generated_docs/L22_VERIFICATION_PLAN.json",
        "verdict_field": "extraction_status",
    }]
    assert COMMAND not in str(step["gate"])


def test_the_audit_does_not_execute_the_producer_again():
    assert COMMAND not in FLOW.read_text()


def test_the_enforcement_audit_no_longer_reports_it_orphaned():
    proc = subprocess.run(
        [sys.executable, str(PROGRAMS / "flow_gate_enforcement_audit.py")],
        capture_output=True, text=True, timeout=900)
    out = proc.stdout + proc.stderr
    assert "orphan::l22_analog_verification_plan_emit" not in out, out[-2000:]
    assert proc.returncode == 0, out[-2000:]


# ── the in-process consumer ───────────────────────────────────────────────
def test_the_runner_adapter_names_a_refusal(refusing_project, capsys):
    """PRE-FIX the adapter branched on SKIPPED only, and a REFUSED projection
    returned `emitted_count == 0` exactly like a digital no-op — so the one
    state worth naming was the silent one."""
    assert RUNNER._post_emit_l22_analog_verification_plan(refusing_project) == 0
    err = capsys.readouterr().err
    assert "L22 analog verification plan REFUSED" in err, err
    assert "no usable block identity" in err, err
