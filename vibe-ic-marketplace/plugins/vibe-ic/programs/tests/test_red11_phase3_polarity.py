"""Focused polarity controls for the Step-24/25 PSM transcript reader."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import _prose_polarity as PP  # noqa: E402
import mixed_signal_power_domain_run as M2  # noqa: E402
import phase3_one_shot_runner as R  # noqa: E402
import project_outputs_in_tree_check as OUTPUTS  # noqa: E402
import pulse_width_rearm_conformance_check as PWR  # noqa: E402
import pulse_width_rearm_contract as CONTRACT  # noqa: E402


TOKENS = ("not", "no", "none", "without", "never", "removed",
          "obsolete", "superseded", "n/a", "does not apply", "無")


def test_denied_psm_records_cannot_mint_ir_or_em_evidence():
    """A denial in the same tool record is not a measurement keyword."""
    log = "\n".join((
        "Supply voltage: 1.8 V",
        "IR drop: 0.012 V",
        "current: 0.25 A",
        "EM analysis complete",
        "IR drop: not measured",
        "current: no result",
        "PSM_NONFATAL VSS: no analysis",
    ))

    ir = R._polarity_accepted_tool_lines(
        log, r"voltage|IR drop|PSM-|Supply", PP.is_denied)
    em = R._polarity_accepted_tool_lines(
        log, r"current|EM analysis|EM lifetime", PP.is_denied)

    assert ir == ["Supply voltage: 1.8 V", "IR drop: 0.012 V"]
    assert em == ["current: 0.25 A", "EM analysis complete"]


def test_a_clean_psm_record_remains_evidence():
    """The negative control must move the result; clean records still survive."""
    assert R._polarity_accepted_tool_lines(
        "IR drop: 0.012 V\n", r"IR drop", PP.is_denied) == [
            "IR drop: 0.012 V"]


def test_m2_def_comment_denials_do_not_mint_components(tmp_path, monkeypatch):
    """DEF comments cannot become a placed component declaration."""
    upf = tmp_path / "top.upf"
    netlist = tmp_path / "top.v"
    routed = tmp_path / "top.def"
    gds = tmp_path / "top.gds"
    liberty = tmp_path / "cells.lib"
    for path in (upf, netlist, gds, liberty):
        path.write_text("fixture\n")
    base_def = ("VERSION 5.8 ;\nDESIGN top ;\nCOMPONENTS 1 ;\n"
                "- u0 plain + PLACED ( 0 0 ) N ;\nEND COMPONENTS\n")
    routed.write_text(base_def)
    paths = {"upf": upf, "netlist": netlist, "def": routed, "gds": gds}
    native = {"modules": {
        "top": {"cells": {"u0": {"type": "plain", "connections": {},
                                    "port_directions": {}}}, "ports": {}},
        "plain": {"attributes": {"blackbox": 1}},
    }}
    monkeypatch.setattr(M2, "power_model", lambda *_: (
        {"LIVE": {"elements": ["u0"], "voltage": 1.0,
                   "off_capable": False}}, set(), set()))
    monkeypatch.setattr(M2, "library_cells", lambda *_: {
        "plain": {"kinds": [], "data": None, "controls": [],
                   "conversion": None}})
    expected = M2.derive(paths, [liberty], "top", native)
    for token in TOKENS:
        routed.write_text(base_def.replace(
            "END COMPONENTS", f"# {token} - fake plain component;\nEND COMPONENTS"))
        assert M2.derive(paths, [liberty], "top", native) == expected
    routed.write_text(base_def.replace(
        "END COMPONENTS", "- fake plain + PLACED ( 1 1 ) N ;\nEND COMPONENTS"))
    with pytest.raises(M2.Refusal):
        M2.derive(paths, [liberty], "top", native)


def _audit_doc(flagged):
    return {
        "program": "flow_compliance_check",
        "invocation": "flow_compliance_check --stage 3",
        "scope": {"stage": 3},
        "gate_execution_ledger": [],
        "steps": [{"gate_records": [{
            "name": "project_outputs_in_tree_check",
            "evidence": {"flagged": list(flagged)},
        }]}],
    }


def test_auditor_diagnostics_do_not_treat_denial_prose_as_records():
    """Only the producer's complete diagnostic shape is projected."""
    for token in TOKENS:
        doc = _audit_doc([f"{token} this is not a diagnostic",
                          "tool → /outside/result (live)"])
        text, projected = OUTPUTS._auditor_diagnostic_text(
            json.dumps(doc), ["reports/audit/phase23_completion_audit.json"])
        got = json.loads(text)["steps"][0]["gate_records"][0]["evidence"]["flagged"]
        assert got == [f"{token} this is not a diagnostic"]
        assert projected


def test_suite_marker_denials_are_refused_or_ignored(tmp_path):
    """A denial cannot open a suite marker or create a usable path."""
    fixture = _PROGRAMS / "tests" / "pulse_width_rearm_regression.sv"
    source, positive, negative = PWR._suite_paths(fixture)
    clean = (f"// PWR_SOURCE: {source}\n"
             f"// PWR_POSITIVE_RTL: {positive}\n"
             f"// PWR_NEGATIVE_RTL: {negative}\n")
    for token in TOKENS:
        suite = tmp_path / f"suite_{len(token)}.sv"
        suite.write_text(f"// {token} PWR_SOURCE: {source}\n"
                         f"// PWR_POSITIVE_RTL: {positive}\n"
                         f"// PWR_NEGATIVE_RTL: {negative}\n")
        with pytest.raises(ValueError):
            PWR._suite_paths(suite)
    suite = tmp_path / "clean.sv"
    suite.write_text(clean)
    assert PWR._suite_paths(suite) == (source, positive, negative)


_MARKED = ("pulse_width_rearm_contract\n"
           "input_signal: pulse_i\n"
           "accept_output: accept_o\n"
           "clock_signal: clk\n"
           "max_width_cycles: 4\n"
           "start_edge: rising\n"
           "timeout_action: reject\n"
           "rearm_policy: inactive_then_new_start_edge\n"
           "source_quote: 'pulse_i is rejected after four cycles and rearms '
           "'after inactive then a new rising edge'\n")


def test_marked_contract_uses_shared_polarity_and_keeps_typed_no_values():
    """A denied field is refused, while a typed boolean ``no`` remains valid."""
    clean = CONTRACT._marked_contract(_MARKED)
    assert clean is not None and clean.contract is not None
    assert clean.contract.max_width_cycles == 4
    for token in TOKENS:
        denied = _MARKED.replace("input_signal: pulse_i",
                                 f"{token} input_signal: pulse_i")
        result = CONTRACT._marked_contract(denied)
        assert result is not None and result.contract is None
        assert result.declared is True
    typed_no = _MARKED.replace(
        "start_edge: rising", "reset_signal: reset_n\nreset_active_low: no\n"
        "start_edge: rising")
    reset = CONTRACT._marked_contract(typed_no)
    assert reset is not None and reset.contract is not None
    assert reset.contract.reset_active_low is False
