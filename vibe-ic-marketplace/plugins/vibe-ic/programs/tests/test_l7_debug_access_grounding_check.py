#!/usr/bin/env python3
"""Negative-control smoke tests for l7_debug_access_grounding_check.py.

EVERY fixture is SYNTHESIZED neutral data — no real design's files are
copied, and no design name / PDK name / vendor part number / pin literal
from any real project appears. The "design" is ``fixture_top`` with pins
``tck_i`` / ``tms_i`` / ``dbg_req_i``.

WHAT THIS FILE USED TO MISS, AND WHY THE SHAPE CHANGED
======================================================
It proved the gate could exit 1 — by passing ``--strict``. Nothing else
ever passed ``--strict``: the gate's ONLY invocation is the flow's
``advisory_program_exit_zero: "l7_debug_access_grounding_check ."``,
which carries neither that flag nor ``--json``. So the exit-1 verdict was
reachable from this file and from nowhere a real run could go, and the
advisory slot — which reads the exit code and NOTHING else, discarding
the program's stdout on the rc-0 path — could only ever record
``ADVISORY: ok:``. A gate with real findings was byte-identical in the
run record to a gate that found none.

So the assertions moved to where the verdict is actually consumed: the
tests below drive ``flow_compliance_check._evaluate_gate`` with the real
clause from the flow definition and assert on the reason it records.
BOTH directions are pinned, on the same channel:

  * findings           -> rc 1 -> ``ADVISORY: FINDING:``   (was unreachable)
  * examined & clean   -> rc 0 -> ``ADVISORY: ok:``        (still reachable)
  * examined nothing   -> rc 2 -> ``ADVISORY: n/a``        (was unreachable)

and, in every direction, that the STEP still passes — this gate is
advisory by SLOT, and making its verdict legible must not make a run red.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import flow_compliance_check as FCC  # noqa: E402

PROG = _PROGRAMS / "l7_debug_access_grounding_check.py"
_FLOW = _PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"
GATE = "l7_debug_access_grounding_check"


def _run(project: Path, *extra: str):
    rep = project / "rep.json"
    cmd = [sys.executable, str(PROG), str(project), "--json", str(rep), *extra]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    report = json.loads(rep.read_text()) if rep.is_file() else {}
    return proc, report


def _flow_clause() -> dict:
    """The gate clause EXACTLY as the flow definition states it — read from
    the shipped YAML, never retyped here, so a change to the wiring cannot
    leave these tests passing against a command nobody runs."""
    doc = yaml.safe_load(_FLOW.read_text())
    found: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "advisory_program_exit_zero":
                    cmd = v.get("command") if isinstance(v, dict) else v
                    if isinstance(cmd, str) and cmd.split()[:1] == [GATE]:
                        found.append(cmd)
                walk(v)
        elif isinstance(node, list):
            for i in node:
                walk(i)

    walk(doc)
    assert found, f"{GATE} is not wired into the flow at all"
    return {"advisory_program_exit_zero": found[0]}


def _advise(project: Path) -> tuple[bool, str]:
    """(step_passed, the ADVISORY reason the run record would carry)."""
    passed, reasons = FCC._evaluate_gate(project, _flow_clause())
    advisory = [r for r in reasons
                if r.startswith(FCC._ADVISORY_HINT_PREFIX) and GATE in r]
    assert advisory, (
        f"the advisory slot recorded nothing for {GATE}: {reasons}")
    return passed, advisory[0]


def _rules(report: dict) -> set[str]:
    return {f["rule"] for f in report.get("findings", [])}


def _gen(project: Path) -> Path:
    d = project / "phase1" / "generated_docs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write(project: Path, stem: str, doc: dict):
    (_gen(project) / f"{stem}.json").write_text(json.dumps(doc, indent=1))


def _l9(project: Path, ports=("tck_i", "tms_i", "dbg_req_i"), **kw):
    doc = {
        "doc_class": "integration_spec",
        "ic_name": "fixture_top",
        "top_module": "fixture_top",
        "top_module_pins": [{"name": p, "direction": "input"} for p in ports],
    }
    doc.update(kw)
    _write(project, "L9_INTEGRATION_SPEC", doc)


def _l1(project: Path, pins=("tck_i", "tms_i", "dbg_req_i")):
    _write(project, "L1_DATASHEET", {
        "doc_class": "datasheet",
        "pin_table": [{"name": p, "mode": "input", "aliases": []}
                      for p in pins],
    })


def _l7(project: Path, **kw):
    doc = {"schema_version": 2, "doc_class": "test_debug",
           "ic_name": "fixture_top"}
    doc.update(kw)
    _write(project, "L7_TEST_DEBUG", doc)


# ─────────────────────────── POSITIVE CONTROLS ───────────────────────────

def test_no_l7_skips(tmp_path):
    """Examined nothing => the VACUOUS tier (rc 2), never a plain pass."""
    _gen(tmp_path)
    proc, report = _run(tmp_path)
    assert proc.returncode == 2, proc.stdout
    assert report["verdict"] == "VACUOUS"
    assert report["summary"]["skipped"] is True
    assert report["summary"]["skipped_reason"]


def test_empty_l7_passes(tmp_path):
    """A design whose input genuinely has no test/debug content must NOT
    be pushed to fabricate any (§4.05)."""
    _l9(tmp_path)
    _l1(tmp_path)
    _l7(tmp_path, test_modes=[], debug_observability=[],
        no_test_modes_in_input=True)
    proc, report = _run(tmp_path)
    assert proc.returncode == 0, proc.stdout
    assert report["passed"] is True
    assert report["findings"] == []


def test_grounded_debug_signals_pass(tmp_path):
    _l9(tmp_path)
    _l1(tmp_path)
    _l7(tmp_path, debug_observability=[
        {"method": "tap", "signals": ["tck_i", "tms_i"]}])
    proc, report = _run(tmp_path)
    assert proc.returncode == 0, proc.stdout
    assert report["findings"] == []


def test_bus_subscript_and_case_are_tolerated(tmp_path):
    """``DBG_REQ_I[0]`` must ground against port ``dbg_req_i`` — a gate
    that fired here would be a false positive."""
    _l9(tmp_path)
    _l1(tmp_path)
    _l7(tmp_path, debug_observability=[
        {"method": "probe", "signals": ["DBG_REQ_I[0]"]}])
    proc, report = _run(tmp_path)
    assert proc.returncode == 0, proc.stdout
    assert report["findings"] == []


def test_signal_grounded_only_via_internal_wires_passes(tmp_path):
    _l9(tmp_path, internal_wires=[{"net": "dbg_bus_int",
                                   "child_module": "fixture_core"}])
    _l1(tmp_path)
    _l7(tmp_path, debug_observability=[
        {"method": "probe", "signals": ["dbg_bus_int"]}])
    proc, report = _run(tmp_path)
    assert proc.returncode == 0, proc.stdout
    assert report["findings"] == []


def test_no_pin_namespace_skips_grounding(tmp_path):
    """Nothing to ground against => the rule must not fire."""
    _l7(tmp_path, debug_observability=[
        {"method": "tap", "signals": ["some_signal"]}])
    proc, report = _run(tmp_path)
    assert proc.returncode == 0, proc.stdout
    assert "L7_DEBUG_SIGNAL_UNGROUNDED" not in _rules(report)
    assert [na["rule"] for na in report["summary"]["rules_not_applicable"]] \
        == ["L7_DEBUG_SIGNAL_UNGROUNDED"]


def test_debug_registers_skip_when_no_register_namespace(tmp_path):
    """L4 declares no registers => there is no namespace to ground
    against, so the rule must stay silent rather than guess."""
    _l9(tmp_path)
    _l1(tmp_path)
    _write(tmp_path, "L4_REGMAP", {"doc_class": "regmap", "registers": []})
    _l7(tmp_path, debug_registers=[{"name": "SOMETHING", "value": 1}])
    proc, report = _run(tmp_path)
    assert proc.returncode == 0, proc.stdout
    assert "L7_DEBUG_REGISTER_UNGROUNDED" not in _rules(report)


def test_grounded_debug_register_passes(tmp_path):
    _l9(tmp_path)
    _l1(tmp_path)
    _write(tmp_path, "L4_REGMAP", {"registers": [{"name": "DBG_CTRL"}]})
    _l7(tmp_path, debug_registers=[{"name": "DBG_CTRL", "value": 0}])
    proc, report = _run(tmp_path)
    assert proc.returncode == 0, proc.stdout
    assert report["findings"] == []


def test_enterable_test_mode_passes(tmp_path):
    _l9(tmp_path)
    _l1(tmp_path)
    _l7(tmp_path, test_modes=[{"name": "scan", "entry_pins": ["tms_i"]}])
    proc, report = _run(tmp_path)
    assert proc.returncode == 0, proc.stdout
    assert report["findings"] == []


def test_test_mode_entered_via_trigger_key_passes(tmp_path):
    """SWEEP-DRIVEN NARROWING: real docs state the entry in a ``trigger``
    key. Firing here was a measured false positive and must stay fixed."""
    _l9(tmp_path)
    _l1(tmp_path)
    _l7(tmp_path, test_modes=[
        {"name": "INIT", "trigger": "CTRL[0]=1", "effect": "start"}])
    proc, report = _run(tmp_path)
    assert proc.returncode == 0, proc.stdout
    assert "L7_TEST_MODE_NOT_ENTERABLE" not in _rules(report)


def test_test_mode_entered_via_register_bit_in_prose_passes(tmp_path):
    """SWEEP-DRIVEN NARROWING: the entry may live in the mode's own name
    as a register-bit reference. Also a measured false positive."""
    _l9(tmp_path)
    _l1(tmp_path)
    _l7(tmp_path, test_modes=[
        {"name": "Loopback (bit 0.14)",
         "purpose": "internal transmit-to-receive loopback"}])
    proc, report = _run(tmp_path)
    assert proc.returncode == 0, proc.stdout
    assert "L7_TEST_MODE_NOT_ENTERABLE" not in _rules(report)


# ───────────────────────── NEGATIVE CONTROLS ─────────────────────────────

def test_NEGATIVE_ungrounded_debug_signal_is_reported(tmp_path):
    """GUTTED LAYER: L1/L9 are missing the debug port L7 claims exists —
    the pin would never get a port or a pad."""
    _l9(tmp_path, ports=("tck_i", "tms_i"))
    _l1(tmp_path, pins=("tck_i", "tms_i"))
    _l7(tmp_path, debug_observability=[
        {"method": "tap", "signals": ["tck_i", "dbg_req_i"]}])
    proc, report = _run(tmp_path)
    assert proc.returncode == 1, proc.stdout
    assert report["passed"] is False
    assert report["verdict"] == "FINDINGS"
    assert "L7_DEBUG_SIGNAL_UNGROUNDED" in _rules(report)
    msg = next(f["message"] for f in report["findings"]
               if f["rule"] == "L7_DEBUG_SIGNAL_UNGROUNDED")
    assert "dbg_req_i" in msg


def test_NEGATIVE_ungrounded_debug_register_is_reported(tmp_path):
    _l9(tmp_path)
    _l1(tmp_path)
    _write(tmp_path, "L4_REGMAP", {"registers": [{"name": "DBG_CTRL"}]})
    _l7(tmp_path, debug_registers=[{"name": "NOT_A_REGISTER", "value": 0}])
    proc, report = _run(tmp_path)
    assert proc.returncode == 1, proc.stdout
    assert "L7_DEBUG_REGISTER_UNGROUNDED" in _rules(report)


def test_NEGATIVE_test_mode_with_no_entry_is_reported(tmp_path):
    _l9(tmp_path)
    _l1(tmp_path)
    _l7(tmp_path, test_modes=[{"name": "burn_in",
                               "description": "run the burn-in pattern"}])
    proc, report = _run(tmp_path)
    assert proc.returncode == 1, proc.stdout
    assert "L7_TEST_MODE_NOT_ENTERABLE" in _rules(report)


def test_NEGATIVE_a_rule_that_cannot_judge_does_not_swallow_the_others(
        tmp_path):
    """L7 names access points and NO layer declares a pin, so the grounding
    rule cannot judge — but a non-enterable test mode in the SAME document
    is still a finding.

    The old code wrote that per-rule condition into `skipped_reason`, and
    `main` printed `skipped:` and returned 0 on it BEFORE printing any
    finding. So this project reported a clean skip while carrying a finding
    the program had already computed and written into its own report.
    """
    _l7(tmp_path,
        debug_observability=[{"method": "tap", "signals": ["ghost_sig"]}],
        test_modes=[{"name": "burn_in",
                     "description": "run the burn-in pattern"}])
    proc, report = _run(tmp_path)
    assert proc.returncode == 1, proc.stdout
    assert report["summary"]["skipped"] is False
    assert "L7_TEST_MODE_NOT_ENTERABLE" in _rules(report)
    assert "L7_TEST_MODE_NOT_ENTERABLE" in proc.stdout


def test_NEGATIVE_formal_interface_signal_is_checked_too(tmp_path):
    _l9(tmp_path, ports=("tck_i",))
    _l1(tmp_path, pins=("tck_i",))
    _l7(tmp_path, formal_interfaces=[{"name": "fi", "signals": ["ghost_sig"]}])
    proc, report = _run(tmp_path)
    assert "L7_DEBUG_SIGNAL_UNGROUNDED" in _rules(report)


# ───────────────────── BLOCK / ADVISE + ESCAPE HATCHES ───────────────────

def test_waiver_suppresses(tmp_path):
    """A waived run judged nothing, so it lands in the VACUOUS tier — not
    in the same green as a design that was read and found correct."""
    _l9(tmp_path, ports=("tck_i",))
    _l1(tmp_path, pins=("tck_i",))
    _l7(tmp_path, debug_observability=[{"method": "tap",
                                        "signals": ["ghost_sig"]}])
    (tmp_path / "waivers.json").write_text(json.dumps({"waivers": [{
        "id": "l7_debug_access_grounding_override",
        "rationale": "synthesized fixture: debug access is provided by an "
                     "external harness outside this design's port list",
    }]}))
    proc, report = _run(tmp_path)
    assert proc.returncode == 2, proc.stdout
    assert report["verdict"] == "VACUOUS"
    assert report["findings"] == []


def test_deprecated_strict_flag_is_accepted_and_changes_nothing(tmp_path):
    """`--strict` was the flag no caller passed. Removing it outright would
    make a straggler invocation exit 2 from argparse — which the advisory
    slot reads as `n/a (input not present)`, i.e. it would fail silently.
    It is accepted and inert; asserted by running BOTH ways."""
    _l9(tmp_path, ports=("tck_i",))
    _l1(tmp_path, pins=("tck_i",))
    _l7(tmp_path, debug_observability=[{"method": "tap",
                                        "signals": ["ghost_sig"]}])
    plain, rep_a = _run(tmp_path)
    strict, rep_b = _run(tmp_path, "--strict")
    assert plain.returncode == strict.returncode == 1
    assert rep_a["findings"] == rep_b["findings"]
    assert rep_a["verdict"] == rep_b["verdict"] == "FINDINGS"


# ─────────── THE VERDICT CHANNEL THE REAL CALLER ACTUALLY READS ───────────
#
# `flow_compliance_check._evaluate_gate`'s advisory branch reads the exit
# code and nothing else, and DISCARDS the program's stdout when it is 0.
# These three drive the real clause from the shipped flow definition.

def test_umbrella_records_a_FINDING_when_the_gate_has_findings(tmp_path):
    """DIRECTION 1 — the verdict that was unreachable.

    Against the unfixed program this fails: it returned 0 without
    `--strict`, nothing passes `--strict`, and the slot recorded
    `ADVISORY: ok:` over a design carrying an ungrounded debug pin.
    """
    _l9(tmp_path, ports=("tck_i", "tms_i"))
    _l1(tmp_path, pins=("tck_i", "tms_i"))
    _l7(tmp_path, debug_observability=[
        {"method": "tap", "signals": ["dbg_req_i"]}])
    step_passed, reason = _advise(tmp_path)
    assert "FINDING" in reason, reason
    assert "L7_DEBUG_SIGNAL_UNGROUNDED" in reason, reason
    # BLAST RADIUS, asserted rather than asserted-about: a legible verdict
    # must not turn a run red. The advisory slot never fails a step.
    assert step_passed is True, reason


def test_umbrella_still_records_ok_when_the_gate_is_clean(tmp_path):
    """DIRECTION 2 — the OTHER verdict is still reachable.

    A gate that could only ever say FINDING would be exactly as useless as
    one that could only ever say ok.
    """
    _l9(tmp_path)
    _l1(tmp_path)
    _l7(tmp_path, debug_observability=[
        {"method": "tap", "signals": ["tck_i", "tms_i"]}],
        test_modes=[{"name": "scan", "entry_pins": ["tms_i"]}])
    step_passed, reason = _advise(tmp_path)
    assert "ok:" in reason, reason
    assert "FINDING" not in reason, reason
    assert step_passed is True, reason


def test_umbrella_records_n_a_when_the_gate_examined_nothing(tmp_path):
    """DIRECTION 3 — a project with no L7 at all must not be credited the
    same green as one that was examined and found correct."""
    _l9(tmp_path)
    _l1(tmp_path)
    _gen(tmp_path)
    step_passed, reason = _advise(tmp_path)
    assert "n/a" in reason, reason
    assert "ok:" not in reason, reason
    assert step_passed is True, reason
