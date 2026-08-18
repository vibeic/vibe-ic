#!/usr/bin/env python3
"""Negative-control smoke tests for l7_debug_access_grounding_check.py.

EVERY fixture is SYNTHESIZED neutral data — no real design's files are
copied, and no design name / PDK name / vendor part number / pin literal
from any real project appears. The "design" is ``fixture_top`` with pins
``tck_i`` / ``tms_i`` / ``dbg_req_i``.

This gate ADVISES by default (L7 has no downstream consumer), so the
negative control asserts on the FINDINGS, and additionally proves the
``--strict`` path really does exit 1 — i.e. the gate is capable of
blocking the day a consumer is wired to L7.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "l7_debug_access_grounding_check.py"


def _run(project: Path, *extra: str):
    rep = project / "rep.json"
    cmd = [sys.executable, str(PROG), str(project), "--json", str(rep), *extra]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    report = json.loads(rep.read_text()) if rep.is_file() else {}
    return proc, report


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
    _gen(tmp_path)
    proc, report = _run(tmp_path)
    # vibe-ic#1051 follow-up: an input-missing skip is the DISCLOSED tier, not a
    # plain pass. rc 2 is `_vacuous_exit.RC_VACUOUS`, which `flow_compliance_check`
    # records as VACUOUS_PASS; the `VACUOUS_PASS:` sentinel is the second,
    # rc-independent channel the same consumer reads. Asserting BOTH is the point —
    # either one alone can regress silently while the other keeps the test green.
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "VACUOUS_PASS:" in (proc.stdout + proc.stderr), proc.stdout + proc.stderr
    assert report["summary"]["skip_kind"] == "input-missing"
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
    # vibe-ic#1051 follow-up: an input-missing skip is the DISCLOSED tier, not a
    # plain pass. rc 2 is `_vacuous_exit.RC_VACUOUS`, which `flow_compliance_check`
    # records as VACUOUS_PASS; the `VACUOUS_PASS:` sentinel is the second,
    # rc-independent channel the same consumer reads. Asserting BOTH is the point —
    # either one alone can regress silently while the other keeps the test green.
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "VACUOUS_PASS:" in (proc.stdout + proc.stderr), proc.stdout + proc.stderr
    assert report["summary"]["skip_kind"] == "input-missing"
    assert "L7_DEBUG_SIGNAL_UNGROUNDED" not in _rules(report)


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
    assert proc.returncode == 0, proc.stdout          # advisory
    assert report["passed"] is False
    assert "L7_DEBUG_SIGNAL_UNGROUNDED" in _rules(report)
    msg = next(f["message"] for f in report["findings"]
               if f["rule"] == "L7_DEBUG_SIGNAL_UNGROUNDED")
    assert "dbg_req_i" in msg


def test_NEGATIVE_ungrounded_signal_blocks_under_strict(tmp_path):
    """Proves the gate CAN block — the one-flag change for the day a
    consumer is wired to L7."""
    _l9(tmp_path, ports=("tck_i",))
    _l1(tmp_path, pins=("tck_i",))
    _l7(tmp_path, test_modes=[{"name": "scan", "entry_pins": ["scan_en_i"]}])
    proc, report = _run(tmp_path, "--strict")
    assert proc.returncode == 1, proc.stdout
    assert report["blocks"] is True
    assert "L7_DEBUG_SIGNAL_UNGROUNDED" in _rules(report)


def test_NEGATIVE_ungrounded_debug_register_is_reported(tmp_path):
    _l9(tmp_path)
    _l1(tmp_path)
    _write(tmp_path, "L4_REGMAP", {"registers": [{"name": "DBG_CTRL"}]})
    _l7(tmp_path, debug_registers=[{"name": "NOT_A_REGISTER", "value": 0}])
    proc, report = _run(tmp_path)
    assert proc.returncode == 0, proc.stdout
    assert "L7_DEBUG_REGISTER_UNGROUNDED" in _rules(report)


def test_NEGATIVE_test_mode_with_no_entry_is_reported(tmp_path):
    _l9(tmp_path)
    _l1(tmp_path)
    _l7(tmp_path, test_modes=[{"name": "burn_in",
                               "description": "run the burn-in pattern"}])
    proc, report = _run(tmp_path)
    assert proc.returncode == 0, proc.stdout
    assert "L7_TEST_MODE_NOT_ENTERABLE" in _rules(report)


def test_NEGATIVE_formal_interface_signal_is_checked_too(tmp_path):
    _l9(tmp_path, ports=("tck_i",))
    _l1(tmp_path, pins=("tck_i",))
    _l7(tmp_path, formal_interfaces=[{"name": "fi", "signals": ["ghost_sig"]}])
    proc, report = _run(tmp_path)
    assert "L7_DEBUG_SIGNAL_UNGROUNDED" in _rules(report)


# ───────────────────── BLOCK / ADVISE + ESCAPE HATCHES ───────────────────

def test_default_run_declares_that_it_does_not_block(tmp_path):
    _l9(tmp_path)
    _l1(tmp_path)
    _l7(tmp_path)
    _proc, report = _run(tmp_path)
    assert report["blocks"] is False


def test_waiver_suppresses(tmp_path):
    _l9(tmp_path, ports=("tck_i",))
    _l1(tmp_path, pins=("tck_i",))
    _l7(tmp_path, debug_observability=[{"method": "tap",
                                        "signals": ["ghost_sig"]}])
    (tmp_path / "waivers.json").write_text(json.dumps({"waivers": [{
        "id": "l7_debug_access_grounding_override",
        "rationale": "synthesized fixture: debug access is provided by an "
                     "external harness outside this design's port list",
    }]}))
    proc, report = _run(tmp_path, "--strict")
    assert proc.returncode == 0, proc.stdout
    assert report["findings"] == []
