"""Focused D06 producer/adapter controls."""
from __future__ import annotations

import json
import pytest
from pathlib import Path

import flow109_package_plan as d06
from programs.tests._hostpaths import require_repo


def _write(path: Path, value) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) if isinstance(value, dict) else value)
    return path


def _context():
    return {"requested_step": "D06", "native_step_id": "flow109.D06",
            "resolved_row": {"id": "D06"}, "context_sha256": "b" * 64,
            "resolved_features": {"requires_dft": False, "requires_scan": False,
                                  "package_interface": True,
                                  "package_model_required": True}}


def _producer(monkeypatch, verdict: str, rc: int):
    def run(argv):
        report = Path(argv[argv.index("--json") + 1])
        out = Path(argv[argv.index("--out") + 1])
        _write(report, {"program": "pad_assignment_gen", "verdict": verdict,
                        "reason": "controlled owner result"})
        if rc == 0:
            _write(out, {"PAD_SOUTH": ["u_pad_a"]})
        return rc
    monkeypatch.setattr(d06.pad_assignment_gen, "main", run)
    monkeypatch.setattr(d06, "_current_pdk", lambda project, **kwargs: "neutral_pdk")


def _early_docs(project: Path, *, dft=False):
    case = {"name": "functional", "kind": "functional_vector",
            "stimulus": "drive input", "expected": "observe output",
            "evidence": "input/docs/L7.md (table)"}
    _write(project / d06.L7_REPORT, {"schema_version": 2, "doc_class": "test_debug",
           "test_scenarios": [case], "source_documents": ["input/docs/L7.md"]})
    _write(project / d06.L10_REPORT, {"schema_version": 2, "test_cases": [case],
           "source_documents": ["input/docs/L7.md"]})
    _write(project / d06.L8_REPORT, {"clock_and_reset_waveform": {
        "clocks": [{"name": "clk"}], "resets": [{"name": "rst"}]}})
    chain = ({"name": "chain0", "scan_in": "sin", "scan_out": "sout",
              "scan_enable": "scan_en"} if dft else None)
    _write(project / d06.L20_REPORT, {"doc_id": "L20", "fields": {
        "dft_present": dft, "scan_chains": [chain] if chain else [],
        "bist_mbist": [], "jtag_tap": None, "test_compression": None}})


def _io(project: Path):
    return _write(project / d06.IO_REPORT, {
        "program": "io_pad_chip_top_gen", "verdict": "WROTE",
        "pad_instances": {
            "u_clk": {"port": "clk", "direction": "input"},
            "u_rst": {"port": "rst", "direction": "input"},
            "u_stim": {"port": "stim", "direction": "input"},
            "u_obs": {"port": "obs", "direction": "output"}},
        "scan_interface": {"selected_scan_netlist": False,
                           "selection": "current pre-DFT netlist"}})


def _bare_die_load(project: Path):
    import hashlib
    _write(project / d06.TAPEOUT_DECLARATION, {
        "schema": "vibe-ic/tapeout_declaration/1",
        "answers": {"deliverable": "DIE"},
        "answer_provenance": {"deliverable": {
            "answered_by": "owner", "citation": "operator --route ic"}}})
    _write(project / "phase1/generated_docs/L1_DATASHEET.json", {
        "no_package_in_input": True, "package_info": None})
    sdc = _write(project / "phase3/stage3/pnr/constraint.sdc",
                 "set_output_delay 2 -clock clk [all_outputs]\n"
                 "set_load 0.07 [all_outputs]\n")
    netlist = _write(project / "phase3/librelane/current/chip_top.nl.v",
                     "module chip_top (clk, rst, stim, obs);\n"
                     " input clk, rst, stim; output obs;\nendmodule\n")
    state = _write(project / "phase3/librelane/current/state_out.json", {
        "sdc": "/project/" + str(sdc.relative_to(project)),
        "nl": "/project/" + str(netlist.relative_to(project))})
    _write(state.parent / "config.json", {"DESIGN_NAME": "chip_top", "PDK": "neutral_pdk"})
    digest = hashlib.sha256(state.read_bytes()).hexdigest()
    _write(project / d06.CURRENT_REPAIR, {"verdict": "PASS", "final": {
        "sta_state": "/project/" + str(state.relative_to(project)),
        "sta_state_sha256": digest}})
    return state


def test_checked_in_registry_routes_d06_to_real_pad_producer():
    registry = json.loads(require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "flow", "flow109.json").read_text())
    row = next(item for item in registry["rows"] if item["id"] == "D06")
    dispatch = row["profiles"][0]["dispatch"]
    assert dispatch["adapter"] == "flow109_package_plan"
    assert dispatch["producer"] == "pad_assignment_gen.py:main"
    assert row["metric_acceptance_status"] == "IMPLEMENTED_BARE_DIE_NATIVE"


def test_functional_unscanned_route_uses_l7_l10_and_native_pad_map(tmp_path, monkeypatch):
    _producer(monkeypatch, "WROTE", 0)
    project = tmp_path / "project"
    _early_docs(project)
    _io(project)
    _bare_die_load(project)
    result = d06.execute(project, _context())
    assert result["native_started"] is True
    assert result["checks"][0]["status"] == "PASS"
    assert result["checks"][1]["pad_instances"] == 4
    assert result["checks"][2]["detail"]["mode"] == "functional_unscanned"
    assert {row["path"] for row in result["inputs"]} >= {
        str(d06.L7_REPORT), str(d06.L8_REPORT), str(d06.L10_REPORT), str(d06.L20_REPORT)}
    assert result["checks"][3]["check"] == "bare_die_external_load_interface"
    assert result["checks"][3]["detail"]["output_ports"] == ["obs"]
    assert result["checks"][3]["detail"]["capacitance_library_units"] == 0.07
    assert result["checks"][3]["profile_package_model_required"] is True
    assert result["checks"][3]["profile_flag_is_owner_scope_authority"] is False
    assert result["component_status"] == "PASS"
    assert result["reason"] == "D06_BARE_DIE_NATIVE_METRICS_PASS"
    assert result["flow109_acceptance"] == "PASS"
    assert result["completed"] is True
    assert set(result["metrics"]) == {"pad_bump_interface_constraints",
        "package_escape_feasibility", "test_access_plan"}
    assert result["metrics"]["package_escape_feasibility"]["physical_package_model_consumed"] is False
    assert result["delivery_accepted"] is False


def test_profile_package_flag_cannot_replace_owner_delivery_scope(tmp_path, monkeypatch):
    _producer(monkeypatch, "WROTE", 0)
    project = tmp_path / "project"
    _early_docs(project)
    _io(project)
    result = d06.execute(project, _context())
    assert result["component_status"] == "NOT_MEASURED"
    assert result["reason"] == "D06_DELIVERY_SCOPE_OWNER_FACT_MISSING"


def test_stale_current_sta_state_refuses_load_interface(tmp_path, monkeypatch):
    _producer(monkeypatch, "WROTE", 0)
    project = tmp_path / "project"
    _early_docs(project)
    _io(project)
    state = _bare_die_load(project)
    _write(state, {"changed": True})
    result = d06.execute(project, _context())
    assert result["component_status"] == "NOT_MEASURED"
    assert result["reason"] == "D06_CURRENT_STA_AUTHORITY_STALE"


def test_current_output_without_io_pad_refuses_load_coverage(tmp_path, monkeypatch):
    _producer(monkeypatch, "WROTE", 0)
    project = tmp_path / "project"
    _early_docs(project)
    _io(project)
    state = _bare_die_load(project)
    netlist = project / json.loads(state.read_text())["nl"].removeprefix("/project/")
    _write(netlist, "module chip_top (clk, rst, stim, obs, missing);\n"
                    " input clk, rst, stim; output obs, missing;\nendmodule\n")
    result = d06.execute(project, _context())
    assert result["component_status"] == "NOT_MEASURED"
    assert result["reason"] == "D06_OUTPUT_LOAD_PAD_COVERAGE_MISMATCH"


def test_missing_formal_load_refuses_bare_die_interface(tmp_path, monkeypatch):
    _producer(monkeypatch, "WROTE", 0)
    project = tmp_path / "project"
    _early_docs(project)
    _io(project)
    state = _bare_die_load(project)
    sdc = project / json.loads(state.read_text())["sdc"].removeprefix("/project/")
    _write(sdc, "set_output_delay 2 -clock clk [all_outputs]\n")
    result = d06.execute(project, _context())
    assert result["component_status"] == "NOT_MEASURED"
    assert result["reason"] == "D06_BARE_DIE_LOAD_INTERFACE_UNRESOLVED"


def test_unknown_dft_intent_refuses_before_functional_access(tmp_path, monkeypatch):
    _producer(monkeypatch, "WROTE", 0)
    project = tmp_path / "project"
    _early_docs(project)
    _io(project)
    context = _context()
    del context["resolved_features"]
    result = d06.execute(project, context)
    assert result["reason"] == "D06_DFT_INTENT_UNKNOWN"
    assert len(result["checks"]) == 2


def test_wrong_l7_source_refuses(tmp_path, monkeypatch):
    _producer(monkeypatch, "WROTE", 0)
    project = tmp_path / "project"
    _early_docs(project)
    _io(project)
    l7 = json.loads((project / d06.L7_REPORT).read_text())
    l7["test_scenarios"][0]["evidence"] = "input/docs/other.md (table)"
    _write(project / d06.L7_REPORT, l7)
    result = d06.execute(project, _context())
    assert result["reason"] == "D06_EVIDENCE_WRONG_SOURCE"


def test_hash_record_is_for_exact_consumed_l10_bytes(tmp_path):
    project = tmp_path / "project"
    _early_docs(project)
    _, binding = d06._bound_json(project, d06.L10_REPORT)
    import hashlib
    assert binding["sha256"] == hashlib.sha256(
        (project / d06.L10_REPORT).read_bytes()).hexdigest()
    _write(project / d06.L10_REPORT, {"schema_version": 2, "test_cases": []})
    _, changed = d06._bound_json(project, d06.L10_REPORT)
    assert changed["sha256"] != binding["sha256"]


def test_l20_contradiction_refuses(tmp_path, monkeypatch):
    _producer(monkeypatch, "WROTE", 0)
    project = tmp_path / "project"
    _early_docs(project, dft=True)
    _io(project)
    result = d06.execute(project, _context())
    assert result["reason"] == "D06_DFT_INTENT_CONTRADICTION"


def test_selected_dft_requires_complete_l20_architecture(tmp_path, monkeypatch):
    _producer(monkeypatch, "WROTE", 0)
    project = tmp_path / "project"
    _early_docs(project, dft=True)
    _io(project)
    l20 = json.loads((project / d06.L20_REPORT).read_text())
    del l20["fields"]["scan_chains"][0]["scan_enable"]
    _write(project / d06.L20_REPORT, l20)
    context = _context()
    context["resolved_features"] = {"requires_dft": True, "requires_scan": True}
    result = d06.execute(project, context)
    assert result["reason"] == "D06_SELECTED_DFT_ARCHITECTURE_MISSING"


def test_current_pdk_uses_hash_bound_adopted_sta_state(tmp_path):
    state = _write(tmp_path / "phase3/librelane/candidate/sta/state_out.json", {})
    _write(state.parent / "config.json", {"PDK": "neutral_pdk"})
    import hashlib
    digest = hashlib.sha256(state.read_bytes()).hexdigest()
    report = {"verdict": "PASS", "final": {
        "sta_state": "/project/phase3/librelane/candidate/sta/state_out.json",
        "sta_state_sha256": digest}}
    _write(tmp_path / "reports/phase3/librelane_postroute_repair.json", report)
    assert d06._current_pdk(tmp_path) == "neutral_pdk"
    _write(state, {"changed": True})
    try:
        d06._current_pdk(tmp_path)
    except d06.D06Refusal as exc:
        assert exc.code == "D06_CURRENT_PDK_AUTHORITY_UNRESOLVED"
    else:
        raise AssertionError("stale current PDK state was accepted")


def test_pad_assignment_refusal_remains_fail(tmp_path, monkeypatch):
    _producer(monkeypatch, "REFUSE", 1)
    project = tmp_path / "project"
    project.mkdir()
    result = d06.execute(project, _context())
    assert result["component_status"] == "FAIL"
    assert result["reason"] == "D06_PAD_ASSIGNMENT_PRODUCER_REFUSED"


def test_pad_assignment_not_asked_remains_not_measured(tmp_path, monkeypatch):
    _producer(monkeypatch, "NOT_ASKED", 2)
    project = tmp_path / "project"
    project.mkdir()
    result = d06.execute(project, _context())
    assert result["component_status"] == "NOT_MEASURED"
    assert result["reason"] == "D06_PAD_ASSIGNMENT_OWNER_FACT_MISSING"



def test_selected_dft_cannot_inherit_functional_metric_completion(tmp_path, monkeypatch):
    _producer(monkeypatch, "WROTE", 0)
    project = tmp_path / "project"
    _early_docs(project, dft=True)
    _io(project)
    _bare_die_load(project)
    context = _context()
    context["resolved_features"].update(requires_dft=True, requires_scan=True)
    result = d06.execute(project, context)
    assert result["component_status"] == "NOT_MEASURED"
    assert result["reason"] == "D06_TEST_ACCESS_METRIC_SCOPE_UNRESOLVED"
    assert not result.get("completed")


def test_changed_readset_cannot_complete_metrics(tmp_path, monkeypatch):
    _producer(monkeypatch, "WROTE", 0)
    project = tmp_path / "project"
    _early_docs(project)
    _io(project)
    _bare_die_load(project)
    original = d06._current_bare_die_load
    def changed(*args):
        answer = original(*args)
        (project / d06.L10_REPORT).write_text("{}")
        return answer
    monkeypatch.setattr(d06, "_current_bare_die_load", changed)
    result = d06.execute(project, _context())
    assert result["reason"] == "D06_EVIDENCE_CHANGED_DURING_CONSUMPTION"
    assert not result.get("completed")


def test_unbound_io_test_access_cannot_complete_metrics(tmp_path, monkeypatch):
    _producer(monkeypatch, "WROTE", 0)
    project = tmp_path / "project"
    _early_docs(project)
    path = _io(project)
    io = json.loads(path.read_text())
    io["test_access"] = {"mode": "functional_unscanned", "functional_cases": 1}
    _write(path, io)
    _bare_die_load(project)
    result = d06.execute(project, _context())
    assert result["reason"] == "D06_TEST_ACCESS_METRIC_SCOPE_UNRESOLVED"
    assert not result.get("completed")


def test_declared_physical_package_cannot_inherit_bare_die_metrics(tmp_path, monkeypatch):
    _producer(monkeypatch, "WROTE", 0)
    project = tmp_path / "project"
    _early_docs(project)
    _io(project)
    _bare_die_load(project)
    _write(project / "phase1/generated_docs/L1_DATASHEET.json", {
        "no_package_in_input": False, "package_info": {"kind": "declared package"}})
    result = d06.execute(project, _context())
    assert result["reason"] == "D06_PHYSICAL_PACKAGE_SCOPE_UNRESOLVED"
    assert not result.get("completed")


def _early_d03_binding(project):
    """SOFTWARE-only neutral publication; actual producer coverage is separate."""
    producer = Path(d06.__file__).with_name('flow109_technology_qualification.py')
    config = _write(project / 'phase3/librelane/config.json', {'PDK': 'neutral_pdk'})
    resolved = _write(project / 'reports/flow109/D03/resolved.json', {'PDK': 'neutral_pdk'})
    rtl = _write(project / 'neutral.v', 'module neutral; endmodule\n')
    import hashlib
    body = {'schema': 'vibeic.flow109.technology-qualification.v1',
            'program': 'flow109_technology_qualification', 'step_id': 'D03',
            'component_status': 'PASS', 'default_row_status': 'PASS', 'completed': True,
            'inputs': [{'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                       for p in (producer, config, resolved, rtl)]}
    return _write(project / 'reports/flow109/default_rows/D03.json', body), rtl


def test_current_pdk_uses_early_d03_without_later_sta_or_ir(tmp_path):
    _early_d03_binding(tmp_path)
    inputs = []
    assert d06._current_pdk(tmp_path, evidence=inputs) == 'neutral_pdk'
    assert any(x['path'] == 'reports/flow109/default_rows/D03.json' for x in inputs)
    assert any(x['path'].endswith('/neutral.v') for x in inputs)


def test_early_d03_cannot_hide_conflicting_later_pdk(tmp_path):
    _early_d03_binding(tmp_path)
    _bare_die_load(tmp_path)
    config = tmp_path / 'phase3/librelane/current/config.json'
    _write(config, {'PDK': 'other_pdk'})
    with pytest.raises(d06.D06Refusal, match='D06_CURRENT_PDK_AUTHORITY_UNRESOLVED'):
        d06._current_pdk(tmp_path)


@pytest.mark.parametrize('damage', ['stale_rtl', 'missing_rtl', 'failed_row',
                                    'missing_producer', 'missing_config_binding',
                                    'stale_resolved', 'empty_inputs', 'malformed_input'])
def test_early_d03_rejects_unbound_or_stale_authority(tmp_path, damage):
    receipt, rtl = _early_d03_binding(tmp_path)
    body = json.loads(receipt.read_text())
    if damage == 'stale_rtl':
        rtl.write_text('changed\n')
    elif damage == 'missing_rtl':
        rtl.unlink()
    elif damage == 'failed_row':
        body['component_status'] = 'FAIL'
    elif damage == 'missing_producer':
        body['inputs'] = body['inputs'][1:]
    elif damage == 'missing_config_binding':
        body['inputs'].pop(1)
    elif damage == 'stale_resolved':
        _write(tmp_path / 'reports/flow109/D03/resolved.json', {'PDK': 'other_pdk'})
    elif damage == 'empty_inputs':
        body['inputs'] = []
    else:
        body['inputs'] = ['bad']
    _write(receipt, body)
    with pytest.raises(d06.D06Refusal, match='D06_CURRENT_D03_AUTHORITY_(INVALID|STALE)'):
        d06._current_pdk(tmp_path)


def test_early_d03_entry_reaches_pad_producer_and_keeps_its_refusal(tmp_path, monkeypatch):
    _early_d03_binding(tmp_path)
    called = []
    def producer(argv):
        called.append(argv)
        report = Path(argv[argv.index('--json') + 1])
        _write(report, {'verdict': 'NOT_ASKED', 'reason': 'neutral owner pad intent absent'})
        return 2
    monkeypatch.setattr(d06.pad_assignment_gen, 'main', producer)
    result = d06.execute(tmp_path, _context())
    assert called and result['native_started']
    assert result['reason'] == 'D06_PAD_ASSIGNMENT_OWNER_FACT_MISSING'
    assert result['component_status'] == 'NOT_MEASURED'
    assert result['whole_flow_acceptance'] == 'NOT_MEASURED'


def _named_l7_plan(project):
    _early_docs(project)
    _io(project)
    _write(project / 'input/docs/L7.md', '- **Reference method**: documented input/output comparison\n')
    path = project / d06.L7_REPORT
    body = json.loads(path.read_text())
    named = {'name': 'Reference method', 'kind': 'named_scenario',
             'stimulus': 'documented input/output comparison',
             'expected': 'documented DV scenario reproduced',
             'evidence': 'L7.md', 'extraction_strategy': 'named_scenario_list'}
    body['test_scenarios'].append(named)
    _write(path, body)
    return named


def test_l7_named_prose_is_retained_without_fabricating_l10_case(tmp_path):
    named = _named_l7_plan(tmp_path)
    io = json.loads((tmp_path / d06.IO_REPORT).read_text())
    result, evidence = d06._early_test_access(tmp_path, _context(), io)
    assert result['functional_cases'] == 1
    assert result['additional_named_verification_scenarios'] == [named]
    assert any(item['path'] == 'input/docs/L7.md' for item in evidence)
    assert len(json.loads((tmp_path / d06.L10_REPORT).read_text())['test_cases']) == 1


@pytest.mark.parametrize('damage', ['missing_case', 'changed_expected', 'duplicate_case',
                                    'unknown_extra_kind', 'wrong_named_strategy',
                                    'wrong_named_source', 'missing_named_source',
                                    'empty_named_stimulus', 'ambiguous_named_source'])
def test_l7_additional_prose_does_not_hide_missing_or_unbound_cases(tmp_path, damage):
    _named_l7_plan(tmp_path)
    l7 = json.loads((tmp_path / d06.L7_REPORT).read_text())
    l10 = json.loads((tmp_path / d06.L10_REPORT).read_text())
    if damage == 'missing_case':
        l10['test_cases'] = []
    elif damage == 'changed_expected':
        l10['test_cases'][0]['expected'] = 'different outcome'
    elif damage == 'duplicate_case':
        l10['test_cases'].append(dict(l10['test_cases'][0]))
    elif damage == 'unknown_extra_kind':
        l7['test_scenarios'][-1]['kind'] = 'undeclared_role'
    elif damage == 'wrong_named_strategy':
        l7['test_scenarios'][-1]['extraction_strategy'] = 'invented'
    elif damage == 'wrong_named_source':
        l7['test_scenarios'][-1]['evidence'] = 'unrelated.md'
    elif damage == 'missing_named_source':
        (tmp_path / 'input/docs/L7.md').unlink()
    elif damage == 'empty_named_stimulus':
        l7['test_scenarios'][-1]['stimulus'] = ''
    else:
        l7['source_documents'].append('input/other/L7.md')
        l10['source_documents'].append('input/other/L7.md')
    _write(tmp_path / d06.L7_REPORT, l7)
    _write(tmp_path / d06.L10_REPORT, l10)
    io = json.loads((tmp_path / d06.IO_REPORT).read_text())
    with pytest.raises(d06.D06Refusal):
        d06._early_test_access(tmp_path, _context(), io)
