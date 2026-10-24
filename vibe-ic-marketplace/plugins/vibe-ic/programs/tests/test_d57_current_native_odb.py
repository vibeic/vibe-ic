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
import phase3_one_shot_runner as runner
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


def _step24_record_selection(project, pdk_root, monkeypatch):
    selected = {}
    binding = {}

    def capture(_project, _image, _root, _pdk, **kwargs):
        selected.update({name: str(Path(kwargs[name]).resolve())
                         for name in ('routed_def', 'netlist', 'sdc', 'spef')})
        binding.update(kwargs['expected_current_records'])
        raise Refusal('CONTROL_D57_ALL_VIEWS_SELECTED', json.dumps(selected, sort_keys=True))

    monkeypatch.setattr(runner, '_librelane_step_ctx',
                        lambda *_a, **_k: (IMAGE, pdk_root))
    monkeypatch.setattr(runner, '_discover_power_nets', lambda _path: (['P'], ['G']))
    monkeypatch.setattr(ir, 'run_ir', capture)
    written = []
    try:
        runner._librelane_step24_record(
            project, 'neutral', SimpleNamespace(name='neutral', ir_budget_pct=5.0),
            'librelane', project / 'phase3/stage3/extracted/neutral.spef', written)
        report = json.loads((project / 'reports/phase3/ir_drop_librelane.json').read_text())
    except Exception as exc:
        report = {'judgment': {'reasons': [f'escaped: {type(exc).__name__}: {exc}']}}
    return selected, binding, report, written


def test_step24_record_hands_all_exact_current_views_to_native_consumer(
        tmp_path, monkeypatch):
    project, pdk_root, paths, _ = _current_scene(tmp_path, monkeypatch)
    selected, binding, report, written = _step24_record_selection(
        project, pdk_root, monkeypatch)
    assert selected == {name: str(paths[key].resolve()) for name, key in (
        ('routed_def', 'def'), ('netlist', 'nl'), ('sdc', 'sdc'), ('spef', 'spef'))}
    assert 'CONTROL_D57_ALL_VIEWS_SELECTED' in report['judgment']['reasons'][0]
    assert set(binding) == {'odb', 'def', 'netlist', 'sdc', 'spef', 'sta_state',
                            'sta_receipt', 'sta_config', 'step23_record'}
    assert written == [str(project / 'reports/phase3/ir_drop_librelane.json')]
    assert not (project / 'phase3/stage3/pnr/neutral.def').exists()


@pytest.mark.parametrize('damage,reason', [
    ('missing', 'LL_IR_CURRENT_VIEW_MISSING'),
    ('changed', 'LL_IR_CURRENT_VIEW_CHANGED'),
    ('foreign_owner', 'LL_IR_CURRENT_STA_INVALID'),
])
def test_step24_record_refuses_invalid_current_view_without_legacy_fallback(
        tmp_path, monkeypatch, damage, reason):
    project, pdk_root, paths, _ = _current_scene(tmp_path, monkeypatch)
    legacy = {
        'def': _write(project / 'phase3/stage3/pnr/neutral.def', 'legacy def\n'),
        'nl': _write(project / 'phase3/stage3/pnr/neutral_pnr.v', 'module neutral; endmodule\n'),
        'sdc': _write(project / 'phase3/stage3/pnr/constraint.sdc', 'legacy sdc\n'),
        'spef': _write(project / 'phase3/stage3/extracted/neutral.spef', '*SPEF legacy\n'),
    }
    if damage == 'missing':
        paths['def'].unlink()
    elif damage == 'changed':
        paths['def'].write_text(paths['def'].read_text() + 'changed\n')
    else:
        monkeypatch.setattr(current, 'tool_subject', lambda *_a, **_k: (_ for _ in ()).throw(
            current.Refusal('CURRENT_DEF_FOREIGN_PATH')))
    selected, binding, report, _ = _step24_record_selection(project, pdk_root, monkeypatch)
    assert selected == {}
    assert binding == {}
    assert reason in report['judgment']['reasons'][0]
    assert all(path.is_file() for path in legacy.values())


def test_step24_record_without_current_owner_keeps_all_legacy_views(
        tmp_path, monkeypatch):
    project = tmp_path / 'legacy-project'
    paths = {
        'routed_def': _write(project / 'phase3/stage3/pnr/neutral.def', 'legacy def\n'),
        'netlist': _write(project / 'phase3/stage3/pnr/neutral_pnr.v',
                          'module neutral; endmodule\n'),
        'sdc': _write(project / 'phase3/stage3/pnr/constraint.sdc', 'legacy sdc\n'),
        'spef': _write(project / 'phase3/stage3/extracted/neutral.spef', '*SPEF legacy\n'),
    }
    pdk_root = tmp_path / 'pdk'
    (pdk_root / 'neutral').mkdir(parents=True)
    selected, binding, report, _ = _step24_record_selection(project, pdk_root, monkeypatch)
    assert selected == {name: str(path.resolve()) for name, path in paths.items()}
    assert binding == {}
    assert 'CONTROL_D57_ALL_VIEWS_SELECTED' in report['judgment']['reasons'][0]


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


def _run_ir_with_selection_binding(project, pdk_root, direct, actual, expected,
                                   monkeypatch):
    configs = {step: _write(project / 'bound-cfg' / (step + '.json'), json.dumps({
        'DESIGN_NAME': 'neutral', 'DEFAULT_CORNER': 'max_ss',
        'TECH_LEFS': {'max_*': '/pdk/neutral/tech.lef'},
        'VDD_NETS': ['P'], 'GND_NETS': ['G'],
        'meta': {'step': step, 'inputs': ['odb', 'def', 'nl', 'sdc', 'spef']}}))
        for step in ir.IR_STEPS}
    monkeypatch.setattr(ir, 'resolve_step_configs', lambda *_a, **_k: configs)
    monkeypatch.setattr(ir, '_current_stapostpnr_ir_inputs',
                        lambda *_a, **_k: actual)
    reached = {}

    def capture(_project, _image, _config, views, *_args, **_kwargs):
        reached.update(views)
        raise Refusal('CONTROL_STOP_BEFORE_NATIVE', 'selection binding accepted')

    monkeypatch.setattr(ir, 'state_from_direct', capture)
    with pytest.raises(Refusal) as caught:
        ir.run_ir(project, IMAGE, pdk_root, 'neutral',
                  routed_def=direct['def'], netlist=direct['nl'],
                  sdc=direct['sdc'], spef=direct['spef'],
                  budget_pct=5.0, budget_source='source control',
                  expected_current_records=expected)
    return str(caught.value), reached


def test_run_ir_accepts_only_the_record_callers_exact_current_selection(
        tmp_path, monkeypatch):
    project, pdk_root, paths, _ = _current_scene(tmp_path, monkeypatch)
    selected = ir._current_stapostpnr_ir_inputs(
        project, IMAGE, pdk_root, 'neutral', {'DESIGN_NAME': 'neutral'})
    reason, reached = _run_ir_with_selection_binding(
        project, pdk_root, {'def': paths['def'], 'nl': paths['nl'],
                            'sdc': paths['sdc'], 'spef': paths['spef']},
        selected, selected['records'], monkeypatch)
    assert 'CONTROL_STOP_BEFORE_NATIVE' in reason
    assert reached['odb'] == paths['odb']
    assert reached['def'] == paths['def']


@pytest.mark.parametrize('case,reason', [
    ('path_stable_hash_change', 'LL_IR_CURRENT_SELECTION_CHANGED'),
    ('state_config_swap', 'LL_IR_CURRENT_SELECTION_CHANGED'),
    ('owner_appeared', 'LL_IR_CURRENT_SELECTION_CHANGED'),
    ('owner_disappeared', 'LL_IR_CURRENT_SELECTION_CHANGED'),
    ('missing_required_record', 'LL_IR_EXPECTED_CURRENT_RECORDS_INVALID'),
    ('malformed_record', 'LL_IR_EXPECTED_CURRENT_RECORDS_INVALID'),
])
def test_run_ir_refuses_split_current_selection_before_state_or_native(
        tmp_path, monkeypatch, case, reason):
    project, pdk_root, paths, _ = _current_scene(tmp_path, monkeypatch)
    first = ir._current_stapostpnr_ir_inputs(
        project, IMAGE, pdk_root, 'neutral', {'DESIGN_NAME': 'neutral'})
    actual = {**first, 'records': json.loads(json.dumps(first['records']))}
    expected = json.loads(json.dumps(first['records']))
    if case == 'path_stable_hash_change':
        actual['records']['def']['sha256'] = '1' * 64
    elif case == 'state_config_swap':
        actual['records']['sta_state'] = {'path': 'phase3/other/state_out.json',
                                          'sha256': '2' * 64}
        actual['records']['sta_config'] = {'path': 'phase3/other/config.json',
                                           'sha256': '3' * 64}
    elif case == 'owner_appeared':
        expected = {}
    elif case == 'owner_disappeared':
        actual = None
    elif case == 'missing_required_record':
        expected.pop('sta_receipt')
    else:
        expected['sta_config'] = {'path': '', 'sha256': 'not-a-digest'}
    message, reached = _run_ir_with_selection_binding(
        project, pdk_root, {'def': paths['def'], 'nl': paths['nl'],
                            'sdc': paths['sdc'], 'spef': paths['spef']},
        actual, expected, monkeypatch)
    assert reason in message
    assert reached == {}


def test_run_ir_explicit_absent_owner_keeps_legacy_explicit_views(
        tmp_path, monkeypatch):
    project = tmp_path / 'bound-legacy'
    pdk_root = tmp_path / 'pdk'
    (pdk_root / 'neutral').mkdir(parents=True)
    direct = {'def': _write(project / 'direct/neutral.def', 'legacy def\n'),
              'nl': _write(project / 'direct/neutral.v', 'module neutral; endmodule\n'),
              'sdc': _write(project / 'direct/neutral.sdc', 'legacy sdc\n'),
              'spef': _write(project / 'direct/neutral.spef', '*SPEF legacy\n')}
    reason, reached = _run_ir_with_selection_binding(
        project, pdk_root, direct, None, {}, monkeypatch)
    assert 'CONTROL_STOP_BEFORE_NATIVE' in reason
    assert reached == {'def': direct['def'], 'nl': direct['nl'],
                       'sdc': direct['sdc'], 'spef': {'max_*': direct['spef']}}


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
        content = json.dumps({'DESIGN_NAME': 'neutral'}) if role == 'sta_config' else role + "\n"
        selected[role] = relative_record(_write(project / rel, content))
    doc["record"]["input_mode"] = "current_stapostpnr_odb"
    doc["record"]["selected_inputs"] = selected
    doc["record"]["input_source_chain"] = {
        "source": "current validated OpenROAD.STAPostPNR state",
        "image": IMAGE, "pdk_root": str(project / "fixture_pdk"), "pdk": "neutral"}
    receipt.write_text(json.dumps(doc))
    monkeypatch.setattr(ir, '_current_stapostpnr_ir_inputs',
                        lambda *_a, **_k: {'records': selected})
    checked = current_ir.validate_primary_ir(project)
    assert checked["valid"] is True
    assert checked["verdict"] == "FAIL"
    odb = project / selected["odb"]["path"]
    odb.write_text(odb.read_text() + "changed after measurement\n")
    refused = current_ir.validate_primary_ir(project)
    assert refused["valid"] is False
    assert refused["verdict"] == "NOT_MEASURED"
    assert "LibreLane IR current STA bytes changed: odb" in refused["reason"]


def _absolute_owner_primary(tmp_path, monkeypatch, case='current'):
    from test_default_step24_current_adoption import (
        test_default_step24_adopts_its_current_native_primary as established_case)
    established_case(tmp_path, monkeypatch, case)
    project = tmp_path / 'project'
    receipt = project / 'reports/phase3/ir_drop_librelane.json'
    doc = json.loads(receipt.read_text())

    def relative_record(path):
        path = Path(path).resolve()
        return {'path': str(path.relative_to(project)), 'sha256': _sha(path)}

    selected = {role: dict(doc['inputs'][role])
                for role in ('def', 'netlist', 'sdc', 'spef')}
    selected['odb'] = {'path': doc['native_basis']['odb']['path'],
                       'sha256': doc['native_basis']['odb']['sha256']}
    for role, rel in (('sta_state', 'phase3/librelane/current/state_out.json'),
                      ('sta_receipt', 'phase3/librelane/current/vibeic_receipt.json'),
                      ('sta_config', 'phase3/librelane/current/config.json'),
                      ('step23_record', ir.CURRENT_STA_RECORD)):
        content = json.dumps({'DESIGN_NAME': 'neutral'}) if role == 'sta_config' else role + '\n'
        selected[role] = relative_record(_write(project / rel, content))
    absolute_def = (project / selected['def']['path']).resolve()
    selected['def'] = {'path': str(absolute_def), 'sha256': _sha(absolute_def)}
    doc['inputs']['def'] = dict(selected['def'])
    doc['record']['input_mode'] = 'current_stapostpnr_odb'
    doc['record']['selected_inputs'] = selected
    doc['record']['input_source_chain'] = {
        'source': 'current validated OpenROAD.STAPostPNR state',
        'image': IMAGE, 'pdk_root': str(project / 'fixture_pdk'), 'pdk': 'neutral'}
    receipt.write_text(json.dumps(doc))
    owner = {'records': json.loads(json.dumps(selected))}
    monkeypatch.setattr(ir, '_current_stapostpnr_ir_inputs',
                        lambda *_a, **_k: owner)
    return project, receipt, doc, selected, owner


def test_primary_ir_accepts_exact_absolute_current_original_owner(
        tmp_path, monkeypatch):
    project, _, _, selected, _ = _absolute_owner_primary(tmp_path, monkeypatch)
    observed = current_ir.validate_primary_ir(project)
    assert observed['valid'] is True
    assert observed['verdict'] == 'PASS'
    assert Path(selected['def']['path']).is_absolute()


@pytest.mark.parametrize('damage,reason', [
    ('wrong_owner', 'owner selection changed'),
    ('wrong_path', 'role binding changed'),
    ('wrong_role', 'role binding changed'),
    ('wrong_hash', 'current STA bytes changed'),
    ('missing', 'current STA bytes changed'),
    ('malformed', 'binding malformed'),
    ('contradictory', 'owner selection changed'),
])
def test_primary_ir_refuses_unbound_absolute_or_damaged_current_owner(
        tmp_path, monkeypatch, damage, reason):
    project, receipt, doc, selected, owner = _absolute_owner_primary(tmp_path, monkeypatch)
    original = Path(selected['def']['path'])
    if damage == 'wrong_owner':
        other = _write(tmp_path / 'other-owner/neutral.def', original.read_text())
        owner['records']['def'] = {'path': str(other.resolve()), 'sha256': _sha(other)}
    elif damage == 'wrong_path':
        other = _write(tmp_path / 'other-path/neutral.def', original.read_text())
        doc['inputs']['def'] = {'path': str(other.resolve()), 'sha256': _sha(other)}
    elif damage == 'wrong_role':
        doc['inputs']['def'] = dict(selected['netlist'])
    elif damage == 'wrong_hash':
        doc['inputs']['def']['sha256'] = '1' * 64
        selected['def']['sha256'] = '1' * 64
        owner['records']['def']['sha256'] = '1' * 64
    elif damage == 'missing':
        original.unlink()
    elif damage == 'malformed':
        doc['record']['selected_inputs']['def'] = {'path': str(original)}
    else:
        owner['records']['sta_receipt']['sha256'] = '2' * 64
    receipt.write_text(json.dumps(doc))
    observed = current_ir.validate_primary_ir(project)
    assert observed['valid'] is False
    assert observed['verdict'] == 'NOT_MEASURED'
    assert reason in observed['reason']


def test_primary_ir_exact_absolute_owner_preserves_measured_fail(
        tmp_path, monkeypatch):
    project, _, _, _, _ = _absolute_owner_primary(tmp_path, monkeypatch, 'native_fail')
    observed = current_ir.validate_primary_ir(project)
    assert observed['valid'] is True
    assert observed['verdict'] == 'FAIL'
