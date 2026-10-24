"""The finishing GDS must be the one remeasured after a PDK-derived top-up."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import librelane_fill_dfm as fill
import librelane_step37 as step37
from metal_fill_config_gen import build_metal_fill_config
from librelane_contract import Refusal


def _put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return path


def _pdk(tmp_path):
    root = tmp_path / 'pdks'
    tech = root / 'processA/tech'
    tech.mkdir(parents=True)
    (tech / 'layers.map').write_text('Metal1 NET 61 0\nMetal2 NET 62 0\n')
    (tech / 'routing.tlef').write_text('''MANUFACTURINGGRID 0.01 ;
LAYER Metal1
 TYPE ROUTING ;
 WIDTH 0.2 ;
 SPACING 0.3 ;
END Metal1
LAYER Metal2
 TYPE ROUTING ;
 WIDTH 0.2 ;
 SPACING 0.3 ;
END Metal2
''')
    (tech / 'density.drc').write_text('''
chip_area = extent.sized(0.0).area
extract_single_layer_from_design.call(:metal1_drawn, 61, 0)
extract_single_layer_from_design.call(:metal1_dummy, 61, 7)
extract_single_layer_from_design.call(:metal2_drawn, 62, 0)
extract_single_layer_from_design.call(:metal2_dummy, 62, 7)
extract_single_layer_from_design.call(:poly2, 50, 0)
extract_single_layer_from_design.call(:poly2_dummy, 50, 4)
{ name: :poly2_result, calc: ->(ctx) { ctx[:poly2] + ctx[:poly2_dummy] } },
# Rule M1.4: Metal1 coverage over the entire die shall be >30%
if (metal1.area / chip_area) * 100 < 30
 extent.output('M1.4', '30%')
end
# Rule M2.4: Metal2 coverage over the entire die shall be >30%
if (metal2.area / chip_area) * 100 < 30
 extent.output('M2.4', '30%')
end
# Rule PL.8: Poly2 coverage over the entire die shall be 14%.
if (poly2_result.area / chip_area) * 100 < 14
 extent.output('PL.8', '14%')
end
''')
    cfg = _put(tmp_path / 'density.json', {
        'KLAYOUT_DEF_LAYER_MAP': '/pdk/processA/tech/layers.map',
        'KLAYOUT_DENSITY_RUNSET': '/pdk/processA/tech/density.drc',
        'TECH_LEFS': {'*': '/pdk/processA/tech/routing.tlef'},
        'DESIGN_NAME': 'top', 'DIE_AREA': [0, 0, 100, 100]})
    return root, cfg


def test_top_up_uses_pdk_rules_and_only_promotes_measured_change(tmp_path, monkeypatch):
    project = tmp_path / 'project'
    project.mkdir()
    gds = project / 'pdk_filled.gds'
    gds.write_bytes(b'PDK filler GDS')
    root, cfg = _pdk(tmp_path)
    routed = project / 'phase3/stage3/pnr/routed.def'
    routed.parent.mkdir(parents=True)
    routed.write_text('COMPONENTS 0 ; END COMPONENTS\n')
    calls = []

    def eda_write(cmd, **kwargs):
        calls.append(cmd)
        if 'openroad' in cmd:
            (Path(cmd[-1]).parent / 'placed_keepouts.txt').write_text(
                'DBU 1000\nTOTAL 0\nEND 0\n')
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        out = Path(cmd[cmd.index('--out') + 1])
        report = Path(cmd[cmd.index('--report') + 1])
        out.write_bytes(b'PDK filler GDS plus legal dummy metal')
        _put(report, {'verdict': 'PASS', 'layers': [
            {'name': 'metal1', 'density_before': .4, 'density_after': .4},
            {'name': 'metal2', 'density_before': .28, 'density_after': .36}]})
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr(fill, 'run_container', eda_write, raising=False)
    result = fill.top_up_density(project, 'image', root, 'processA', gds, cfg,
                                 '37-test-fill')
    assert Path(result['gds']).read_bytes().endswith(b'legal dummy metal')
    derived = json.loads(Path(result['config']).read_text())
    assert [(r['layer'], r['fill_datatype']) for r in derived['layers']] == [
        ([61, 0], 7), ([62, 0], 7)]
    assert derived['_derivation']['density_floor_pct'] == 30
    assert '--gds' in calls[1] and '--config' in calls[1]
    assert derived['keepout_boxes_um'] == []
    assert result['layers'][1]['density_after'] > .30


def test_pad_ring_stays_outside_declared_core_during_top_up(tmp_path, monkeypatch):
    project = tmp_path / 'project'
    project.mkdir()
    gds = project / 'pdk_filled.gds'
    gds.write_bytes(b'PDK filler GDS')
    root, config = _pdk(tmp_path)
    cfg = json.loads(config.read_text())
    (root / 'processA/tech/pad.lef').write_text(
        '# MACRO NEGATED_PAD does not declare a pad\n'
        'MACRO PAD_CELL\nEND PAD_CELL\n')
    cfg['PAD_LEFS'] = ['/pdk/processA/tech/pad.lef']
    _put(config, cfg)
    (project / 'phase3/stage3/pnr').mkdir(parents=True)
    (project / 'phase3/stage3/pnr/routed.def').write_text(
        'COMPONENTS 1 ;\n- PAD_0 PAD_CELL + FIXED ( 0 0 ) N ;\n'
        'END COMPONENTS\n')
    monkeypatch.setattr(fill, 'declaration_config', lambda project: (
        {'DIE_AREA': [0, 0, 100, 100], 'CORE_AREA': [10, 12, 88, 90]},
        {'CORE_AREA': 'reviewed die declaration'}))

    def eda_write(cmd, **kwargs):
        if 'openroad' in cmd:
            content = (project / 'phase3/stage3/pnr/routed.def').read_text()
            boxes = ('BOX PAD PAD_CELL 0 0 10000 8000\n'
                     if 'PAD_0 PAD_CELL' in content else '')
            (Path(cmd[-1]).parent / 'placed_keepouts.txt').write_text(
                f'DBU 1000\nTOTAL 1\n{boxes}END {int(bool(boxes))}\n')
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        Path(cmd[cmd.index('--out') + 1]).write_bytes(b'fill inside core only')
        _put(Path(cmd[cmd.index('--report') + 1]),
             {'verdict': 'PASS', 'layers': [{'name': 'metal2',
                                            'density_before': .28,
                                            'density_after': .34}]})
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr(fill, 'run_container', eda_write)
    result = fill.top_up_density(project, 'image', root, 'processA', gds,
                                 config, '37-pad-safe')
    derived = json.loads(Path(result['config']).read_text())
    assert derived['keepout_edge_um'] == 12
    assert derived['_derivation']['pad_ring_exclusion']['source'] == \
        'reviewed die declaration'
    assert derived['_derivation']['pad_ring_exclusion']['placed_pad_masters'] == \
        ['PAD_CELL']
    assert derived['keepout_boxes_um'] == [[-0.3, -0.3, 10.3, 8.3]]
    (project / 'phase3/stage3/pnr/routed.def').write_text(
        'COMPONENTS 1 ;\n- OTHER NEGATED_PAD + FIXED ( 0 0 ) N ;\n'
        'END COMPONENTS\n')
    absent = fill.top_up_density(project, 'image', root, 'processA', gds,
                                 config, '37-no-placed-pad')
    assert 'keepout_edge_um' not in json.loads(Path(absent['config']).read_text())
    cfg['MACROS'] = {'hardmacro': '/pdk/processA/hardmacro.lef'}
    _put(config, cfg)
    with pytest.raises(Refusal, match='LL_DENSITY_FILL_PLACEMENT_UNREADABLE'):
        fill.top_up_density(project, 'image', root, 'processA', gds, config,
                            '37-unresolved-obs')


def test_top_up_masks_every_placed_pad_and_macro_from_odb(tmp_path, monkeypatch):
    project = tmp_path / 'project'
    project.mkdir()
    _put(project / 'phase3/librelane_switch.json', {'execution_route': 'DOCKER'})
    gds = project / 'pdk_filled.gds'
    gds.write_bytes(b'PDK filler GDS')
    root, config = _pdk(tmp_path)
    tech = root / 'processA/tech'
    (tech / 'pad.lef').write_text('MACRO PAD_CELL\n CLASS PAD ;\nEND PAD_CELL\n')
    (tech / 'macro.lef').write_text('MACRO BLOCK_CELL\n CLASS BLOCK ;\nEND BLOCK_CELL\n')
    cfg = json.loads(config.read_text())
    cfg['PAD_LEFS'] = ['/pdk/processA/tech/pad.lef']
    cfg['MACROS'] = {'block': {'views': {'lef': [str(tech / 'macro.lef')]},
                               'halo_um': 1.5}}
    _put(config, cfg)
    routed = project / 'phase3/stage3/pnr/routed.def'
    routed.parent.mkdir(parents=True)
    routed.write_text('COMPONENTS 3 ; - PAD_IN PAD_CELL + FIXED ( 40000 40000 ) N ; '
                      '- PAD_EDGE PAD_CELL + FIXED ( 0 0 ) N ; '
                      '- MACRO_0 BLOCK_CELL + FIXED ( 20000 30000 ) FS ; '
                      'END COMPONENTS\n')
    monkeypatch.setattr(fill, 'declaration_config', lambda project: (
        {'CORE_AREA': [10, 12, 88, 90]}, {'CORE_AREA': 'reviewed core'}))
    calls = []

    def eda_write(cmd, **kwargs):
        calls.append(cmd)
        if 'openroad' in cmd:
            (Path(cmd[-1]).parent / 'placed_keepouts.txt').write_text(
                'DBU 1000\nTOTAL 3\nBOX PAD PAD_CELL 40000 40000 50000 48000\n'
                'BOX PAD PAD_CELL 0 0 10000 8000\n'
                'BOX BLOCK BLOCK_CELL 20000 30000 28000 37000\nEND 3\n')
        else:
            Path(cmd[cmd.index('--out') + 1]).write_bytes(b'protected fill')
            _put(Path(cmd[cmd.index('--report') + 1]),
                 {'verdict': 'PASS', 'layers': [{'name': 'metal1',
                                                'density_before': .28,
                                                'density_after': .34}]})
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr(fill, 'run_container', eda_write)
    result = fill.top_up_density(project, 'image', root, 'processA', gds,
                                 config, '37-placed-masks')
    derived = json.loads(Path(result['config']).read_text())
    assert len(calls) == 2 and 'openroad' in calls[0]
    script = Path(calls[0][-1]).read_text()
    assert 'read_lef {/pdk/processA/tech/macro.lef}' in script
    assert derived['keepout_boxes_um'] == [
        [-0.3, -0.3, 10.3, 8.3],
        [19.7, 29.7, 28.3, 37.3],
        [39.7, 39.7, 50.3, 48.3],
    ]
    assert derived['_derivation']['placed_instance_keepout']['protected_count'] == 3
    assert derived['_derivation']['placed_instance_keepout']['source'] == str(routed)


def test_compact_def_cannot_hide_a_pad_inside_the_core(tmp_path, monkeypatch):
    project = tmp_path / 'project'
    project.mkdir()
    gds = project / 'pdk_filled.gds'
    gds.write_bytes(b'PDK filler GDS')
    root, config = _pdk(tmp_path)
    tech = root / 'processA/tech'
    (tech / 'pad.lef').write_text(
        'MACRO PAD_CELL\n CLASS PAD ;\n SIZE 10 BY 8 ;\nEND PAD_CELL\n')
    cfg = json.loads(config.read_text())
    cfg['PAD_LEFS'] = ['/pdk/processA/tech/pad.lef']
    _put(config, cfg)
    routed = project / 'phase3/stage3/pnr/routed.def'
    routed.parent.mkdir(parents=True)
    routed.write_text('COMPONENTS 1 ; - PAD_CENTER PAD_CELL '
                      '+ FIXED ( 40000 40000 ) N ; END COMPONENTS\n')
    monkeypatch.setattr(fill, 'declaration_config', lambda project: (
        {'CORE_AREA': [10, 12, 88, 90]}, {'CORE_AREA': 'reviewed core'}))
    calls = []

    def eda_write(cmd, **kwargs):
        calls.append(cmd)
        if 'openroad' in cmd:
            (Path(cmd[-1]).parent / 'placed_keepouts.txt').write_text(
                'DBU 1000\nTOTAL 1\n'
                'BOX PAD PAD_CELL 40000 40000 50000 48000\nEND 1\n')
        else:
            Path(cmd[cmd.index('--out') + 1]).write_bytes(b'protected fill')
            _put(Path(cmd[cmd.index('--report') + 1]),
                 {'verdict': 'PASS', 'layers': [{'name': 'metal1',
                                                'density_before': .28,
                                                'density_after': .34}]})
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr(fill, 'run_container', eda_write)
    result = fill.top_up_density(project, 'image', root, 'processA', gds,
                                 config, '37-compact-pad')
    derived = json.loads(Path(result['config']).read_text())
    assert len(calls) == 2 and 'openroad' in calls[0]
    assert derived['keepout_boxes_um'] == [[39.7, 39.7, 50.3, 48.3]]
    assert derived['_derivation']['placed_instance_keepout']['protected_count'] == 1


def test_top_up_refuses_unreadable_placed_design_before_gds_promotion(tmp_path, monkeypatch):
    project = tmp_path / 'project'
    project.mkdir()
    gds = project / 'pdk_filled.gds'
    gds.write_bytes(b'PDK filler GDS')
    root, config = _pdk(tmp_path)
    calls = []

    def eda_write(cmd, **kwargs):
        calls.append(cmd)
        Path(cmd[cmd.index('--out') + 1]).write_bytes(b'unprotected fill')
        _put(Path(cmd[cmd.index('--report') + 1]),
             {'verdict': 'PASS', 'layers': [{'name': 'metal1',
                                            'density_before': .28,
                                            'density_after': .34}]})
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr(fill, 'run_container', eda_write)
    refusal = None
    try:
        fill.top_up_density(project, 'image', root, 'processA', gds,
                            config, '37-missing-placement')
    except Refusal as exc:
        refusal = str(exc)
    assert len(calls) == 0, 'unreadable placement must stop before the fill engine'
    assert refusal is not None and 'LL_DENSITY_FILL_PLACEMENT_UNREADABLE' in refusal
    assert not (project / 'phase3/librelane/37-missing-placement/'
                'pdk_filled.topped.gds').exists()


@pytest.mark.parametrize('odb_result', ['failed', 'truncated'])
def test_top_up_refuses_failed_odb_census_before_fill(tmp_path, monkeypatch,
                                                       odb_result):
    project = tmp_path / 'project'
    project.mkdir()
    gds = project / 'pdk_filled.gds'
    gds.write_bytes(b'PDK filler GDS')
    root, config = _pdk(tmp_path)
    routed = project / 'phase3/stage3/pnr/routed.def'
    routed.parent.mkdir(parents=True)
    routed.write_text('COMPONENTS 1 ; - P PAD_CELL + FIXED ( 0 0 ) N ; '
                      'END COMPONENTS\n')
    calls = []

    def eda_write(cmd, **kwargs):
        calls.append(cmd)
        if 'openroad' in cmd:
            if odb_result == 'truncated':
                (Path(cmd[-1]).parent / 'placed_keepouts.txt').write_text(
                    'DBU 1000\nTOTAL 1\nBOX PAD PAD_CELL 0 0 10000 8000\n'
                    'END 2\n')
            return SimpleNamespace(returncode=int(odb_result == 'failed'),
                                   stdout='', stderr='')
        Path(cmd[cmd.index('--out') + 1]).write_bytes(b'unprotected fill')
        _put(Path(cmd[cmd.index('--report') + 1]),
             {'verdict': 'PASS', 'layers': [{'name': 'metal1',
                                            'density_before': .28,
                                            'density_after': .34}]})
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr(fill, 'run_container', eda_write)
    refusal = None
    try:
        fill.top_up_density(project, 'image', root, 'processA', gds,
                            config, f'37-{odb_result}-odb')
    except Refusal as exc:
        refusal = str(exc)
    assert len(calls) == 1 and 'openroad' in calls[0]
    assert refusal is not None and 'LL_DENSITY_FILL_PLACEMENT_UNREADABLE' in refusal
    assert not (project / 'phase3/librelane' / f'37-{odb_result}-odb' /
                'pdk_filled.topped.gds').exists()


def test_density_ratios_require_every_deck_layer(tmp_path, monkeypatch):
    project = tmp_path / 'project'
    project.mkdir()
    gds = project / 'filled.gds'
    gds.write_bytes(b'tool GDS')
    root, cfg = _pdk(tmp_path)

    def eda_write(cmd, **kwargs):
        specs = json.loads(Path(cmd[cmd.index('--specs') + 1]).read_text())
        assert specs['PL.8']['layers'] == [[50, 0], [50, 4]]
        assert specs['M2.4']['layers'] == [[62, 0], [62, 7]]
        out = Path(cmd[cmd.index('--out') + 1])
        _put(out, {'status': 'NOT_MEASURED', 'layers': {
            key: {**row, 'ratio': .4 if key != 'M2.4' else None}
            for key, row in specs.items()}})
        return SimpleNamespace(returncode=2, stdout='', stderr='')

    monkeypatch.setattr(fill, 'run_container', eda_write, raising=False)
    with pytest.raises(Refusal, match='LL_DENSITY_RATIOS_NOT_MEASURED'):
        fill.measure_density_ratios(project, 'image', root, 'processA', gds, cfg,
                                    '37-test-ratios')


def test_density_specs_ignore_comment_claims_and_refuse_missing_layers(tmp_path):
    root, cfg = _pdk(tmp_path)
    _, layer_map, tech_lef, deck = fill._density_source(root, 'processA', cfg)
    derived = build_metal_fill_config(layer_map, tech_lef, deck)
    claimed = deck + '\n# extract_single_layer_from_design.call(:poly2_dummy, 99, 99)\n'
    specs = fill._density_ratio_specs(claimed, derived)
    assert specs['PL.8']['layers'] == [[50, 0], [50, 4]]
    missing = claimed.replace(
        'extract_single_layer_from_design.call(:poly2_dummy, 50, 4)', '')
    assert fill._density_ratio_specs(missing, derived)['PL.8']['status'] == 'NOT_MEASURED'


def test_step37_rechecks_topped_gds_before_selection(tmp_path, monkeypatch):
    import librelane_pv_signoff as pv

    project = tmp_path / 'project'
    project.mkdir()
    root, cfg = _pdk(tmp_path)
    configs = {step: cfg for step in step37.STEPS}
    source = project / 'source.gds'
    source.write_bytes(b'stream')
    sealed = project / 'sealed.gds'
    sealed.write_bytes(b'sealed')
    pdk_filled = project / 'pdk_filled.gds'
    pdk_filled.write_bytes(b'pdk fill')
    topped = project / 'topped.gds'
    topped.write_bytes(b'pdk fill plus metal2')
    state = _put(project / 'state.json', {'gds': str(source)})
    routed = project / 'routed.def'
    routed.write_text('DEF')
    netlist = project / 'routed.v'
    netlist.write_text('module top; endmodule')
    sdc = project / 'routed.sdc'
    sdc.write_text('create_clock')
    monkeypatch.setattr(step37, 'resolve_step_configs', lambda *a, **k: configs)
    monkeypatch.setattr(step37, 'declaration_config', lambda *a: (
        {'CORE_AREA': [10, 10, 90, 90]}, {'CORE_AREA': 'test declaration'}))
    monkeypatch.setattr(step37, '_routed_state', lambda *a: state)
    monkeypatch.setattr(step37, '_vibeic_gds_gates', lambda *a: {
        'substance': {'rc': 0, 'sha256': 'x'},
        'port_labels': {'rc': 0, 'sha256': 'x'}})
    monkeypatch.setattr(step37, '_measured_drc', lambda *a: {
        'magic': 0, 'klayout': 0, 'total': 0})
    monkeypatch.setattr(pv, 'tech_lef_overlay', lambda *a: None)
    monkeypatch.setattr(pv, 'run_finishing_xor', lambda *a, **k: {'verdict': 'PASS'})
    monkeypatch.setattr(fill, 'top_up_density', lambda *a: {'gds': str(topped)},
                        raising=False)
    monkeypatch.setattr(fill, 'measure_density_ratios', lambda *a: {
        'layers': {'M2.4': {'ratio': .36, 'status': 'MEASURED'}}}, raising=False)

    def eda_run(project, image, pdk_root, pdk, steps, incoming, lane, configs):
        parent = json.loads(Path(incoming).read_text())
        folders = []
        for index, name in enumerate(steps, 1):
            folder = project / 'phase3/librelane' / lane / f'{index:02d}-{name.lower().replace(".", "-")}'
            next_state = dict(parent)
            if name == 'KLayout.XOR':
                next_state.update({'mag_gds': str(source), 'klayout_gds': str(source)})
                next_state['metrics'] = {'design__xor_difference__count': 0}
            if name == 'KLayout.SealRing':
                next_state['gds'] = str(sealed)
            if name == 'KLayout.Filler':
                next_state['gds'] = str(pdk_filled)
            if name == 'KLayout.Density':
                next_state['metrics'] = {'klayout__density_error__count':
                                         0 if next_state['gds'] == str(topped) else 1}
            _put(folder / 'state_out.json', next_state)
            parent = next_state
            folders.append(folder)
        return folders

    monkeypatch.setattr(step37, '_run', eda_run)
    canonical = project / 'canonical.gds'
    result = step37.run(project, 'image', root, 'processA', routed, netlist,
                        sdc, canonical)
    assert canonical.read_bytes() == topped.read_bytes()
    assert json.loads(Path(result['state']).read_text())['gds'] == str(topped)
    promo = json.loads(Path(result['promotion']).read_text())
    assert promo['density'] == {'magic': 0, 'klayout': 0}
    assert promo['density_ratios']['magic']['layers']['M2.4']['ratio'] == .36
    # Mutation: send the PDK-only bytes through the new handoff.  The deck's
    # positive result must still prevent selection and canonical promotion.
    monkeypatch.setattr(fill, 'top_up_density', lambda *a: {'gds': str(pdk_filled)})
    with pytest.raises(Refusal, match='LL_NO_FEASIBLE_STREAM'):
        step37.run(project, 'image', root, 'processA', routed, netlist, sdc,
                   project / 'mutated_canonical.gds')
    assert not (project / 'mutated_canonical.gds').exists()


@pytest.mark.parametrize('case', [
    'measured-in-window', 'measured-below-window', 'unresolved-deck-layer',
    'measured-string-die',
])
def test_native_die_density_emitter_reaches_the_existing_consumer(
        tmp_path, monkeypatch, case):
    """#3098: actual KLayout emitter I/O, beyond the synthetic report mocks.

    The outer docker launch and authored rule map are SOURCE_CONTROL. The
    generated GDS, emitter CLI, ratio reader, publisher and threshold judge
    execute their real bodies in this test's pinned image.
    """
    import hashlib
    import os
    import subprocess
    import klayout.db as k
    import die_density_ratio_emit as emitter
    import metal_layer_density_check as checker

    project = tmp_path / 'native-project'
    project.mkdir()
    root, cfg = _pdk(tmp_path)
    if case == 'measured-string-die':
        config = json.loads(cfg.read_text())
        config['DIE_AREA'] = [str(v) for v in config['DIE_AREA']]
        _put(cfg, config)
    if case == 'unresolved-deck-layer':
        deck = root / 'processA/tech/density.drc'
        deck.write_text(deck.read_text().replace(
            'extract_single_layer_from_design.call(:poly2_dummy, 50, 4)', ''))
    layout = k.Layout()
    layout.dbu = .001
    top = layout.create_cell('top')
    top.shapes(layout.layer(99, 0)).insert(k.Box(0, 0, 100000, 100000))
    metal1 = layout.layer(61, 0)
    # Independent rectangle-union areas: 3000/10000=.30, or 1000/10000=.10.
    boxes = ([k.Box(0, 0, 40000, 50000), k.Box(20000, 0, 60000, 50000)]
             if case != 'measured-below-window' else
             [k.Box(0, 0, 10000, 50000), k.Box(5000, 0, 20000, 50000)])
    for box in boxes:
        top.shapes(metal1).insert(box)
    top.shapes(layout.layer(62, 0)).insert(k.Box(0, 0, 40000, 100000))
    top.shapes(layout.layer(50, 0)).insert(k.Box(0, 0, 20000, 100000))
    gds = project / 'neutral.gds'
    layout.write(str(gds))
    before = hashlib.sha256(gds.read_bytes()).hexdigest()
    calls = []

    def real_emitter_transport(cmd, **_kwargs):
        # Run the exact emitter argv in the already pinned test container;
        # no nested Docker, fabricated report or mocked native result.
        argv = cmd[cmd.index('--skip') + 1:]
        assert Path(argv[1]).resolve() == Path(emitter.__file__).resolve()
        done = subprocess.run(argv, capture_output=True, text=True)
        calls.append({'requested_argv': cmd, 'executed_argv': argv,
                      'returncode': done.returncode,
                      'stdout': done.stdout, 'stderr': done.stderr})
        return done

    monkeypatch.setattr(fill, 'run_container', real_emitter_transport)
    refusal = None
    ratios = None
    try:
        ratios = fill.measure_density_ratios(
            project, os.environ['VIBEIC_EDA_IMAGE'], root, 'processA', gds, cfg,
            '37-native-density')
    except Refusal as exc:
        refusal = str(exc)
    report = project / 'phase3/librelane/37-native-density/density_ratios.json'
    measured = json.loads(report.read_text())
    if case == 'measured-string-die':
        assert measured['declared_die'] == [0.0, 0.0, 100.0, 100.0]
        assert measured['extent_matches_declared_die'] is True
    published = fill.publish_metal_density(project, ratios, gds, 'processA') if ratios else None
    consumer_rc = None
    consumer = None
    if published:
        consumer_path = project / 'density-consumer.json'
        _, layer_map, tech_lef, deck = fill._density_source(root, 'processA', cfg)
        derived = build_metal_fill_config(layer_map, tech_lef, deck)
        floor = derived['_derivation']['density_floor_pct'] / 100
        # The authored deck states a 30% minimum. Supply that real rule plus
        # the consumer's disclosed generic ceiling; an unproved null ceiling
        # correctly stays UNCHECKED and is not a positive or threshold result.
        windows = _put(project / 'density-windows.json', {
            row['name']: [floor, None] for row in derived['layers']})
        consumer_rc = checker.main([str(published), '--windows', str(windows),
                                    '--default-max', str(checker._DEFAULT_MAX),
                                    '--json', str(consumer_path)])
        consumer = json.loads(consumer_path.read_text())
    values = {'case': case, 'scope': 'native neutral density emitter; launch/map SOURCE_CONTROL',
              'gds_sha256': before, 'calls': calls, 'report': measured,
              'ratios': ratios, 'refusal': refusal, 'published': str(published) if published else None,
              'consumer_rc': consumer_rc, 'consumer': consumer}
    (project / 'actual-density-values.json').write_text(json.dumps(values, indent=2) + '\n')
    assert hashlib.sha256(gds.read_bytes()).hexdigest() == before, values
    assert len(calls) == 1, values
    assert measured['layers']['M1.4']['ratio'] == (
        .1 if case == 'measured-below-window' else .3), values
    assert measured['layers']['M2.4']['ratio'] == .4, values
    if case == 'unresolved-deck-layer':
        assert calls[0]['returncode'] == 2, values
        assert measured['status'] == 'NOT_MEASURED', values
        assert measured['layers']['PL.8']['status'] == 'NOT_MEASURED', values
        assert refusal and 'LL_DENSITY_RATIOS_NOT_MEASURED' in refusal, values
        assert published is None and consumer is None, values
    else:
        assert calls[0]['returncode'] == 0 and refusal is None, values
        assert measured['status'] == 'MEASURED', values
        assert measured['layers']['PL.8']['ratio'] == .2, values
        assert ratios['subject_sha256'] == before, values
        assert json.loads(published.read_text())['gds_sha256'] == before, values
        assert consumer_rc == (1 if case == 'measured-below-window' else 0), values
        assert consumer['verdict'] == ('FAIL' if case == 'measured-below-window' else 'PASS'), values
        assert consumer['per_layer']['metal1']['status'] == (
            'FAIL' if case == 'measured-below-window' else 'PASS'), values
        assert consumer['per_layer']['metal2']['status'] == 'PASS', values
        assert consumer.get('unchecked_layers', []) == [], values
        assert 'max=generic-default' in consumer['per_layer']['metal1']['window_source'], values


@pytest.mark.parametrize('extent_from_deck', [False, True])
def test_density_declared_numeric_strings_match_numbers(tmp_path, extent_from_deck):
    import klayout.db as k
    import die_density_ratio_emit as emitter

    layout = k.Layout(); layout.dbu = .001
    top = layout.create_cell('top')
    top.shapes(layout.layer(99, 0)).insert(k.Box(0, 0, 100000, 100000))
    top.shapes(layout.layer(61, 0)).insert(k.Box(0, 0, 40000, 100000))
    gds = tmp_path / 'neutral.gds'; layout.write(str(gds))
    specs = {'M1.4': {'layers': [[61, 0]]}}
    before = fill.digest(gds)
    numeric = emitter.measure(gds, specs, [0, 0, 100, 100], extent_from_deck=extent_from_deck)
    strings = emitter.measure(gds, specs, ['0', '0.0', '1e2', '100.000'],
                              extent_from_deck=extent_from_deck)
    assert strings == numeric
    assert strings['status'] == 'MEASURED'
    assert strings['layers']['M1.4']['ratio'] == .4
    assert strings['extent_matches_declared_die'] is True
    assert fill.digest(gds) == before


@pytest.mark.parametrize('extent_from_deck', [False, True])
@pytest.mark.parametrize('coords', [
    ['0', '0', 'NaN', '100'], ['0', '0', 'inf', '100'],
    ['0', '0', '-Infinity', '100'], ['0', '0', 'not-a-number', '100'],
    ['0', '0', '0', '100'], ['100', '100', '0', '0'], ['0', '0', '100'],
])
def test_density_invalid_declared_coordinates_still_refuse(tmp_path, extent_from_deck, coords):
    import klayout.db as k
    import die_density_ratio_emit as emitter

    layout = k.Layout(); top = layout.create_cell('top')
    top.shapes(layout.layer(99, 0)).insert(k.Box(0, 0, 100000, 100000))
    gds = tmp_path / 'neutral.gds'; layout.write(str(gds))
    specs = _put(tmp_path / 'specs.json', {'M1.4': {'layers': [[61, 0]]}})
    out = tmp_path / 'ratios.json'
    argv = ['--gds', str(gds), '--specs', str(specs), '--die', json.dumps(coords), '--out', str(out)]
    if extent_from_deck: argv.append('--extent-from-deck')
    assert emitter.main(argv) == 2
    assert json.loads(out.read_text())['status'] == 'NOT_MEASURED'


def test_density_different_declared_extent_still_refuses(tmp_path):
    import klayout.db as k
    import die_density_ratio_emit as emitter

    layout = k.Layout(); layout.dbu = .001
    top = layout.create_cell('top')
    top.shapes(layout.layer(99, 0)).insert(k.Box(0, 0, 100000, 100000))
    gds = tmp_path / 'neutral.gds'; layout.write(str(gds))
    with pytest.raises(ValueError, match='DIE_AREA differs from KLayout density extent'):
        emitter.measure(gds, {'M1.4': {'layers': [[61, 0]]}}, ['0', '0', '101', '100'])


@pytest.mark.parametrize('route', ['provider', 'project-local', 'docker'])
def test_placed_keepout_tcl_uses_the_actual_execution_namespace(
        tmp_path, monkeypatch, route):
    """Real keepout caller and LOCAL mode guard; OpenDB process is neutral.

    No EDA runs here. The process boundary refuses missing literal Tcl inputs,
    reproducing the native LOCAL refusal without rewriting the generated Tcl.
    Docker retains guest paths and is checked through its declared mounts.
    """
    import re
    import librelane_contract as lc

    project = tmp_path / 'project'
    routed = project / 'phase3/stage3/pnr/routed.def'
    routed.parent.mkdir(parents=True)
    routed.write_text('COMPONENTS 2 ; END COMPONENTS\n')
    root, config = _pdk(tmp_path)
    cfg = json.loads(config.read_text())
    views = {}
    for role, name in [('CELL_LEFS', 'cells'), ('PAD_LEFS', 'pads'),
                       ('MACRO_LEFS', 'blocks')]:
        path = root / 'processA/tech' / (name + '.lef')
        path.write_text('MACRO ' + name + '\nEND ' + name + '\n')
        cfg[role] = ['/pdk/processA/tech/' + path.name]
        views[role] = path
    extra = tmp_path / 'external.lef'
    extra.write_text('MACRO extra\nEND extra\n')
    cfg['EXTRA_LEFS'] = [str(extra)]
    monkeypatch.delenv(lc.LOCAL_PROVIDER_ROUTE_ENV, raising=False)
    if route != 'provider':
        _put(project / 'phase3/librelane_switch.json', {
            'execution_route': 'DOCKER' if route == 'docker' else 'LOCAL'})
    monkeypatch.setattr(lc, '_provider_for_image',
                        lambda image: SimpleNamespace(network_mode='none', executable=sys.executable)
                        if route == 'provider' else None)
    monkeypatch.setattr(lc, '_provider_route_mismatch', lambda image: None)
    monkeypatch.setattr(lc._ce, 'no_container_route', lambda: route == 'project-local')
    observed = []

    def process(cmd, *, supervised, probe_deadline_s=None, **kwargs):
        assert supervised is True and probe_deadline_s is None
        script = Path(cmd[-1])
        text = script.read_text()
        paths = re.findall(r'^read_lef \{([^}]+)\}', text, re.M)
        assert len(paths) == 5
        observed.append(paths)
        mounts = [cmd[i + 1].split(':')[:2] for i, a in enumerate(cmd) if a == '-v']
        for path in paths:
            executed = path
            if route == 'docker':
                executed = lc._ce.localise_mounted_paths(
                    path, [(guest, host) for host, guest in mounts])
            if not Path(executed).is_file():
                return SimpleNamespace(returncode=1, stdout='',
                                       stderr=f'ORD-0001 {executed} does not exist')
        assert ('read_def {' + str(routed.resolve()) + '}') in text
        for role, kind in [('PAD_LEFS', 'PAD'), ('MACRO_LEFS', 'BLOCK')]:
            executed = ('/pdk/processA/tech/' + views[role].name
                        if route == 'docker' else str(views[role].resolve()))
            assert ('read_lef {' + executed + '}') in text
            assert f'getName] {kind}' in text
        script.with_name('placed_keepouts.txt').write_text(
            'DBU 2000\nTOTAL 2\nBOX PAD pads 0 0 2000 4000\n'
            'BOX BLOCK blocks 4000 6000 8000 10000\nEND 2\n')
        return SimpleNamespace(returncode=0, stdout='neutral OpenDB census', stderr='')

    monkeypatch.setattr(lc, '_run_local', process)
    monkeypatch.setattr(fill, 'run_container', process if route == 'docker'
                        else lc.run_container)
    placed = fill._placed_keepout_boxes(
        project, 'neutral-image', root, 'processA', cfg,
        project / 'phase3/librelane/37-keepout')
    assert placed['dbu'] == 2000 and placed['total'] == 2
    assert placed['boxes'] == [('PAD', 'pads', (0, 0, 2000, 4000)),
                               ('BLOCK', 'blocks', (4000, 6000, 8000, 10000))]
    assert len(observed) == 1
    assert observed[0][-1] == str(extra.resolve())
    assert observed[0][0] == ('/pdk/processA/tech/routing.tlef' if route == 'docker'
                              else str((root / 'processA/tech/routing.tlef').resolve()))
