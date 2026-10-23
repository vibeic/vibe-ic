"""D57 consumes the current STAPostPNR ODB; fixtures are source controls only."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import _opensta_current as current
import em_current_density_check as current_ir
import execution_backend_producers as backend
import execution_modes as execution_modes
import librelane_ir_antenna as ir
from librelane_contract import Refusal


IMAGE = "ghcr.io/vibeic/vibeic-eda@sha256:" + "0" * 64


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)
    return path


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _record(path, role):
    path = Path(path).resolve()
    return {"role": role, "path": str(path), "resolved": str(path),
            "sha256": _sha(path)}


def _current_scene(tmp_path, monkeypatch):
    project = tmp_path / "project"
    folder = project / "phase3/librelane/final-sta/01-openroad-stapostpnr"
    paths = {
        "odb": _write(folder / "final.odb", "current adopted ODB bytes\n"),
        "def": _write(folder / "final.def", "VERSION 5.8 ;\nDESIGN neutral ;\nEND DESIGN\n"),
        "nl": _write(folder / "neutral.v", "module neutral; endmodule\n"),
        "sdc": _write(folder / "neutral.sdc", "set_propagated_clock [all_clocks]\n"),
        "spef": _write(folder / "neutral.max.spef", "*SPEF neutral\n"),
    }
    state = _write(folder / "state_out.json", json.dumps({
        "odb": str(paths["odb"]), "def": str(paths["def"]),
        "nl": str(paths["nl"]), "sdc": str(paths["sdc"]),
        "spef": {"max_*": str(paths["spef"])}, "metrics": {}}))
    config = _write(folder / "config.json", json.dumps({"DESIGN_NAME": "neutral"}))
    receipt = _write(folder / "vibeic_receipt.json", json.dumps({"input": {
        "state_files": {str(path): _sha(path) for path in paths.values()}}}))
    step23 = _write(project / ir.CURRENT_STA_RECORD,
                    json.dumps({"sta_state": str(state), "judgment": {}}))
    pdk_root = tmp_path / "pdk"
    (pdk_root / "neutral").mkdir(parents=True)
    inputs = [_record(paths["nl"], "netlist"), _record(paths["sdc"], "sdc"),
              _record(paths["spef"], "spef"), _record(state, "tool_state"),
              _record(config, "tool_config"), _record(receipt, "tool_receipt"),
              _record(step23, "step23_record")]
    subject = {"inputs": inputs}
    tool = {"state": state, "image": IMAGE,
            "mounts": [(pdk_root / "neutral", "/pdk/neutral")]}
    monkeypatch.setattr(current, "tool_subject", lambda *_args, **_kw: (subject, tool))
    return project, pdk_root, paths, state


def _step24_selection(project, tmp_path, monkeypatch):
    selected = {}

    def capture(_project, _top, _pdk, _mode, spef, _written):
        selected['path'] = str(Path(spef).resolve())
        selected['sha256'] = _sha(spef)
        raise execution_modes.Refusal('CONTROL_D57_SPEF_SELECTED', selected['path'])

    carrier = SimpleNamespace(_librelane_step24_record=capture)
    pdk = SimpleNamespace(name='neutral')
    monkeypatch.setattr(backend, '_parameters',
                        lambda *_a, **_k: (carrier, None, pdk, ''))
    params = {'step_id': '24', 'top': 'neutral', 'pdk_root': str(tmp_path),
              'image_id': IMAGE, 'execution_mode': 'default'}
    try:
        backend.produce_signoff(project, params)
    except execution_modes.Refusal as exc:
        observed = ({'status': 'SELECTED', **selected}
                    if 'CONTROL_D57_SPEF_SELECTED' in str(exc)
                    else {'status': 'REFUSED', 'reason': str(exc)})
    else:
        observed = {'status': 'UNEXPECTED_RETURN'}
    return observed


def test_default_step24_admits_current_native_spef_without_legacy_alias(
        tmp_path, monkeypatch):
    project, _, paths, _ = _current_scene(tmp_path, monkeypatch)
    legacy = project / 'phase3/stage3/extracted/neutral.spef'
    assert not legacy.exists()
    observed = _step24_selection(project, tmp_path, monkeypatch)
    assert observed == {'status': 'SELECTED', 'path': str(paths['spef'].resolve()),
                        'sha256': _sha(paths['spef'])}


@pytest.mark.parametrize('damage,reason', [
    ('missing', 'BACKEND_CURRENT_SPEF_MISSING'),
    ('changed', 'BACKEND_CURRENT_SPEF_CHANGED'),
    ('foreign', 'BACKEND_CURRENT_SPEF_FOREIGN'),
])
def test_default_step24_refuses_invalid_current_spef_without_legacy_fallback(
        tmp_path, monkeypatch, damage, reason):
    project, _, paths, state = _current_scene(tmp_path, monkeypatch)
    if damage == 'missing':
        paths['spef'].unlink()
    elif damage == 'changed':
        paths['spef'].write_text(paths['spef'].read_text() + 'changed\n')
    else:
        outside = _write(tmp_path / 'outside/current.spef', '*SPEF foreign\n').resolve()
        doc = json.loads(state.read_text())
        doc['spef'] = {'max_*': str(outside)}
        state.write_text(json.dumps(doc))
        subject, tool = current.tool_subject(project, 'neutral')
        subject['inputs'] = [row for row in subject['inputs'] if row['role'] != 'spef']
        subject['inputs'].append(_record(outside, 'spef'))
        monkeypatch.setattr(current, 'tool_subject', lambda *_a, **_k: (subject, tool))
    observed = _step24_selection(project, tmp_path, monkeypatch)
    assert observed['status'] == 'REFUSED'
    assert reason in observed['reason']
    assert not (project / 'phase3/stage3/extracted/neutral.spef').exists()


def test_default_step24_without_current_owner_keeps_legacy_spef(tmp_path, monkeypatch):
    project = tmp_path / 'legacy-project'
    legacy = _write(project / 'phase3/stage3/extracted/neutral.spef', '*SPEF legacy\n')
    observed = _step24_selection(project, tmp_path, monkeypatch)
    assert observed == {'status': 'SELECTED', 'path': str(legacy.resolve()),
                        'sha256': _sha(legacy)}


def test_current_native_state_selects_original_odb_and_source_chain(tmp_path, monkeypatch):
    project, pdk_root, paths, state = _current_scene(tmp_path, monkeypatch)
    selected = ir._current_stapostpnr_ir_inputs(
        project, IMAGE, pdk_root, "neutral", {"DESIGN_NAME": "neutral"})
    assert selected["views"] == paths
    assert selected["records"]["odb"] == {
        "path": str(paths["odb"].relative_to(project)), "sha256": _sha(paths["odb"])}
    assert selected["records"]["sta_state"]["sha256"] == _sha(state)
    assert selected["source"] == "current validated OpenROAD.STAPostPNR state"


def test_project_relative_current_state_rebinds_without_rewriting_bytes(tmp_path, monkeypatch):
    project, pdk_root, paths, state = _current_scene(tmp_path, monkeypatch)
    relative = {name: str(path.relative_to(project)) for name, path in paths.items()}
    state.write_text(json.dumps({"odb": relative["odb"], "def": relative["def"],
        "nl": relative["nl"], "sdc": relative["sdc"],
        "spef": {"max_*": relative["spef"]}, "metrics": {}}))
    receipt = state.parent / "vibeic_receipt.json"
    receipt.write_text(json.dumps({"input": {"state_files": {
        relative[name]: _sha(path) for name, path in paths.items()}}}))
    # The mocked owner rows are immutable receipt records and must follow only
    # the two files whose bytes changed above; view rows still name same bytes.
    subject, tool = current.tool_subject(project, "neutral")
    roles = {row["role"]: row for row in subject["inputs"]}
    roles["tool_state"].update(_record(state, "tool_state"))
    roles["tool_receipt"].update(_record(receipt, "tool_receipt"))
    monkeypatch.setattr(current, "tool_subject",
                        lambda *_args, **_kw: (subject, tool))
    selected = ir._current_stapostpnr_ir_inputs(
        project, IMAGE, pdk_root, "neutral", {"DESIGN_NAME": "neutral"})
    assert selected["views"]["odb"] == paths["odb"].resolve()
    assert selected["records"]["odb"]["sha256"] == _sha(paths["odb"])


def test_validated_original_external_odb_is_kept_not_aliased(tmp_path, monkeypatch):
    project, pdk_root, paths, state = _current_scene(tmp_path, monkeypatch)
    original = tmp_path / "adopted-original"
    external_odb = _write(original / "chip.odb", paths["odb"].read_text()).resolve()
    external_def = _write(original / "chip.def", paths["def"].read_text()).resolve()
    paths.update({"odb": external_odb, "def": external_def})
    state.write_text(json.dumps({"odb": str(external_odb), "def": str(external_def),
        "nl": str(paths["nl"]), "sdc": str(paths["sdc"]),
        "spef": {"max_*": str(paths["spef"])}, "metrics": {}}))
    receipt = state.parent / "vibeic_receipt.json"
    receipt.write_text(json.dumps({"input": {"state_files": {
        str(path): _sha(path) for path in paths.values()}}}))
    subject, tool = current.tool_subject(project, "neutral")
    roles = {row["role"]: row for row in subject["inputs"]}
    roles["tool_state"].update(_record(state, "tool_state"))
    roles["tool_receipt"].update(_record(receipt, "tool_receipt"))
    monkeypatch.setattr(current, "tool_subject",
                        lambda *_args, **_kw: (subject, tool))
    selected = ir._current_stapostpnr_ir_inputs(
        project, IMAGE, pdk_root, "neutral", {"DESIGN_NAME": "neutral"})
    assert selected["views"]["odb"] == external_odb
    assert selected["records"]["odb"]["path"] == str(external_odb)
    assert not (project / "chip.odb").exists()
    configs = {step: _write(project / "cfg" / (step + ".json"), json.dumps({
        "DESIGN_NAME": "neutral", "DEFAULT_CORNER": "max_ss",
        "TECH_LEFS": {"max_*": "/pdk/neutral/tech.lef"},
        "VDD_NETS": ["VDD"], "GND_NETS": ["VSS"],
        "meta": {"step": step, "inputs": ["odb", "def", "nl", "sdc", "spef"]}}))
        for step in ir.IR_STEPS}
    monkeypatch.setattr(ir, "resolve_step_configs", lambda *_a, **_k: configs)
    transport = {}

    def capture(_project, _image, _config, views, *_args, **kwargs):
        transport.update(views=views, mounts=kwargs["mounts"])
        raise Refusal("CONTROL_STOP_AFTER_STATE_SELECTION", "transport captured")

    monkeypatch.setattr(ir, "state_from_direct", capture)
    with pytest.raises(Refusal, match="CONTROL_STOP_AFTER_STATE_SELECTION"):
        ir.run_ir(project, IMAGE, pdk_root, "neutral", routed_def=project / "old.def",
                  netlist=project / "old.v", sdc=project / "old.sdc",
                  spef=project / "old.spef", budget_pct=10.0,
                  budget_source="source control")
    assert transport["views"]["odb"] == external_odb
    assert (external_odb, str(external_odb)) in transport["mounts"]
    assert (external_def, str(external_def)) in transport["mounts"]


def test_absent_current_state_keeps_legacy_bridge(tmp_path, monkeypatch):
    monkeypatch.setattr(current, "tool_subject",
                        lambda *_a, **_k: pytest.fail("legacy route queried current owner"))
    assert ir._current_stapostpnr_ir_inputs(
        tmp_path, IMAGE, tmp_path / "pdk", "neutral",
        {"DESIGN_NAME": "neutral"}) is None


@pytest.mark.parametrize("role,damage,reason", [
    ("odb", "missing", "LL_IR_CURRENT_VIEW_MISSING"),
    ("odb", "changed", "LL_IR_CURRENT_VIEW_CHANGED"),
    ("def", "missing", "LL_IR_CURRENT_VIEW_MISSING"),
    ("def", "changed", "LL_IR_CURRENT_VIEW_CHANGED"),
])
def test_present_current_state_never_falls_back_on_view_damage(
        tmp_path, monkeypatch, role, damage, reason):
    project, pdk_root, paths, _ = _current_scene(tmp_path, monkeypatch)
    if damage == "missing":
        paths[role].unlink()
    else:
        paths[role].write_text(paths[role].read_text() + "changed\n")
    with pytest.raises(Refusal, match=reason):
        ir._current_stapostpnr_ir_inputs(
            project, IMAGE, pdk_root, "neutral", {"DESIGN_NAME": "neutral"})


def test_present_current_state_refuses_pdk_or_model_mismatch(tmp_path, monkeypatch):
    project, pdk_root, _, _ = _current_scene(tmp_path, monkeypatch)
    with pytest.raises(Refusal, match="LL_IR_CURRENT_PDK_MISMATCH"):
        ir._current_stapostpnr_ir_inputs(
            project, IMAGE, tmp_path / "other-pdk", "neutral",
            {"DESIGN_NAME": "neutral"})
    monkeypatch.setattr(current, "tool_subject", lambda *_a, **_k: (_ for _ in ()).throw(
        current.Refusal("CURRENT_STAPOSTPNR_LIBERTY_BINDING_MISSING")))
    with pytest.raises(Refusal, match="LL_IR_CURRENT_STA_INVALID"):
        ir._current_stapostpnr_ir_inputs(
            project, IMAGE, pdk_root, "neutral", {"DESIGN_NAME": "neutral"})


def test_run_ir_hands_exact_current_odb_to_existing_state_builder(tmp_path, monkeypatch):
    project, pdk_root, paths, _ = _current_scene(tmp_path, monkeypatch)
    configs = {}
    for step in ir.IR_STEPS:
        configs[step] = _write(project / "cfg" / (step + ".json"), json.dumps({
            "DESIGN_NAME": "neutral", "DEFAULT_CORNER": "max_ss",
            "TECH_LEFS": {"max_*": "/pdk/neutral/tech.lef"},
            "VDD_NETS": ["VDD"], "GND_NETS": ["VSS"],
            "meta": {"step": step, "inputs": ["odb", "def", "nl", "sdc", "spef"]}}))
    monkeypatch.setattr(ir, "resolve_step_configs", lambda *_a, **_k: configs)
    seen = {}

    def capture(_project, _image, _config, views, *_args, **_kwargs):
        seen.update(views)
        raise Refusal("CONTROL_STOP_AFTER_STATE_SELECTION", "selected views captured")

    monkeypatch.setattr(ir, "state_from_direct", capture)
    with pytest.raises(Refusal, match="CONTROL_STOP_AFTER_STATE_SELECTION"):
        ir.run_ir(project, IMAGE, pdk_root, "neutral", routed_def=tmp_path / "old.def",
                  netlist=tmp_path / "old.v", sdc=tmp_path / "old.sdc",
                  spef=tmp_path / "old.spef", budget_pct=10.0,
                  budget_source="source control")
    assert seen["odb"] == paths["odb"]
    assert seen["def"] == paths["def"]
    assert seen["nl"] == paths["nl"]
    assert seen["sdc"] == paths["sdc"]
    assert seen["spef"] == {"max_*": paths["spef"]}


def test_run_ir_without_current_state_keeps_existing_def_bridge(tmp_path, monkeypatch):
    project = tmp_path / "project"
    pdk_root = tmp_path / "pdk"
    (pdk_root / "neutral").mkdir(parents=True)
    direct = {"def": _write(project / "direct/routed.def",
                             "VERSION 5.8 ;\nDESIGN neutral ;\nEND DESIGN\n"),
              "nl": _write(project / "direct/neutral.v", "module neutral; endmodule\n"),
              "sdc": _write(project / "direct/neutral.sdc", "create_clock\n"),
              "spef": _write(project / "direct/neutral.spef", "*SPEF neutral\n")}
    configs = {step: _write(project / "cfg" / (step + ".json"), json.dumps({
        "DESIGN_NAME": "neutral", "DEFAULT_CORNER": "max_ss",
        "TECH_LEFS": {"max_*": "/pdk/neutral/tech.lef"},
        "VDD_NETS": ["VDD"], "GND_NETS": ["VSS"],
        "meta": {"step": step, "inputs": ["odb", "def", "nl", "sdc", "spef"]}}))
        for step in ir.IR_STEPS}
    monkeypatch.setattr(ir, "resolve_step_configs", lambda *_a, **_k: configs)
    seen = {}

    def capture(_project, _image, _config, views, *_args, **_kwargs):
        seen.update(views)
        raise Refusal("CONTROL_STOP_AFTER_STATE_SELECTION", "legacy views captured")

    monkeypatch.setattr(ir, "state_from_direct", capture)
    with pytest.raises(Refusal, match="CONTROL_STOP_AFTER_STATE_SELECTION"):
        ir.run_ir(project, IMAGE, pdk_root, "neutral", routed_def=direct["def"],
                  netlist=direct["nl"], sdc=direct["sdc"], spef=direct["spef"],
                  budget_pct=10.0, budget_source="source control")
    assert "odb" not in seen
    assert seen == {"def": direct["def"], "nl": direct["nl"],
                    "sdc": direct["sdc"], "spef": {"max_*": direct["spef"]}}


def test_source_probe_argv_and_tcl_read_selected_native_odb(tmp_path, monkeypatch):
    project = tmp_path / "project"
    odb = _write(project / "final/current.odb", "selected ODB bytes\n").resolve()
    state = _write(project / "bridge/state_in.json", json.dumps({"odb": str(odb)}))
    seen = {}

    def container(argv, **kwargs):
        seen["argv"] = argv
        seen["log"] = kwargs["log"]
        return SimpleNamespace(returncode=1, stdout="", stderr="controlled stop")

    monkeypatch.setattr(ir, "run_container", container)
    monkeypatch.setattr(ir, "native_tool_command",
                        lambda _image, command: ("none", command))
    with pytest.raises(Refusal, match="LL_IR_SOURCE_PROBE_UNMEASURED"):
        ir.require_safe_default_sources(project, IMAGE, state, [])
    tcl = state.parent / "psm_source_probe.tcl"
    assert tcl.read_text().splitlines()[0] == f"read_db {{{odb}}}"
    assert seen["argv"][seen["argv"].index(IMAGE) + 1] == "-c"
    assert "/foss/tools/openroad/bin/openroad" in seen["argv"][-1]
    assert seen["argv"][-1].endswith(str(tcl))


def test_current_odb_consumer_keeps_measured_fail_then_refuses_changed_odb(
        tmp_path, monkeypatch):
    # Reuse the established Step-24 public producer/consumer fixture, then add
    # only the new current-STA selection envelope around its measured FAIL.
    from test_default_step24_current_adoption import (
        test_default_step24_adopts_its_current_native_primary as established_case)
    established_case(tmp_path, monkeypatch, "native_fail")
    project = tmp_path / "project"
    receipt = project / "reports/phase3/ir_drop_librelane.json"
    doc = json.loads(receipt.read_text())

    def relative_record(path):
        path = Path(path).resolve()
        return {"path": str(path.relative_to(project)), "sha256": _sha(path)}

    selected = {role: dict(doc["inputs"][role])
                for role in ("def", "netlist", "sdc", "spef")}
    selected["odb"] = relative_record(doc["native_basis"]["odb"]["path"])
    for role, rel in (("sta_state", "phase3/librelane/current/state_out.json"),
                      ("sta_receipt", "phase3/librelane/current/vibeic_receipt.json"),
                      ("sta_config", "phase3/librelane/current/config.json"),
                      ("step23_record", ir.CURRENT_STA_RECORD)):
        selected[role] = relative_record(_write(project / rel, role + "\n"))
    doc["record"]["input_mode"] = "current_stapostpnr_odb"
    doc["record"]["selected_inputs"] = selected
    doc["record"]["input_source_chain"] = {
        "source": "current validated OpenROAD.STAPostPNR state",
        "image": IMAGE, "pdk_root": str(project / "fixture_pdk"), "pdk": "neutral"}
    receipt.write_text(json.dumps(doc))
    checked = current_ir.validate_primary_ir(project)
    assert checked["valid"] is True
    assert checked["verdict"] == "FAIL"
    odb = project / selected["odb"]["path"]
    odb.write_text(odb.read_text() + "changed after measurement\n")
    refused = current_ir.validate_primary_ir(project)
    assert refused["valid"] is False
    assert refused["verdict"] == "NOT_MEASURED"
    assert "LibreLane IR current bytes changed" in refused["reason"]
