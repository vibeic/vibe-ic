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

Both directions are proven through the CONSUMER — `flow_compliance_check`
evaluating the real clause — because a verdict nothing reads is not a verdict:

    rc 0  ->  ADVISORY ok
    rc 1  ->  ADVISORY FINDING        <- a red gate CHANGES what is recorded
    rc 2  ->  ADVISORY n/a (input not present)

and in all three the step still passes, because the declaration is ADVISORY and
this wiring does not change that.
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

#: The clause as this test drives it. Asserted EQUAL to the shipped flow
#: definition by `test_the_flow_definition_carries_this_exact_clause`, so the
#: behavioural tests below cannot pass against a wiring the flow does not have.
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


# ── the consumer, both directions ─────────────────────────────────────────
def _advisory_lines(project: Path):
    passed, reasons = FC._evaluate_gate(
        project, {"advisory_program_exit_zero": {"command": COMMAND}})
    hints = [r[len(FC._ADVISORY_HINT_PREFIX):] for r in reasons
             if r.startswith(FC._ADVISORY_HINT_PREFIX)]
    return passed, hints


def test_a_green_emitter_is_recorded_ok(ok_project):
    passed, hints = _advisory_lines(ok_project)
    assert passed is True
    assert len(hints) == 1 and hints[0].startswith("ok: "), hints


def test_a_red_emitter_changes_what_the_consumer_records(refusing_project):
    """THE DIRECTION THAT MATTERS. Same clause, same consumer, different
    verdict — and the step still passes, because advisory means advisory."""
    passed, hints = _advisory_lines(refusing_project)
    assert passed is True, "an advisory clause must never fail the step"
    assert len(hints) == 1 and hints[0].startswith("FINDING: "), hints
    assert "l22_analog_verification_plan_emit" in hints[0]


def test_nothing_to_project_is_recorded_as_not_applicable(digital_project):
    """rc 2 is NOT rc 0: a digital IC that projected nothing must not read as
    an analog verification plan that was made and found clean."""
    passed, hints = _advisory_lines(digital_project)
    assert passed is True
    assert len(hints) == 1 and hints[0].startswith("n/a (input not present)"), \
        hints


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


def test_the_flow_definition_carries_this_exact_clause():
    found = [c for c in _clauses(yaml.safe_load(FLOW.read_text()), [])
             if (c if isinstance(c, str) else (c or {}).get("command")) == COMMAND]
    assert len(found) == 1, (
        "the flow definition does not wire the L22 analog projection with "
        f"{COMMAND!r} — the behavioural tests above then measure a clause the "
        "flow does not have")
    reason = found[0]["advisory_reason"]
    assert len(reason) >= 40 and sum(c.isalpha() for c in reason) >= 24


def test_dry_run_is_in_the_command():
    """A PRODUCER wired into an audit must not rewrite the document it is
    judged on: the clause would otherwise be measuring its own side effect."""
    assert "--dry-run" in COMMAND


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
