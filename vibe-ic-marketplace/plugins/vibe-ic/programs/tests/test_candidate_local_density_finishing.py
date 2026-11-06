"""Candidate finishing data routing; native instruments are neutral file writers.

No EDA or IC acceptance is measured. Exercise the real density/top-up/keepout
composition and existing PV consumer, keeping their process outputs explicit.
"""
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
import librelane_fill_dfm as fill
import librelane_contract as lc
import librelane_pv_signoff as pv
from programs.tests.test_die_density_finish import _pdk, _put


def _packet(folder, step, cfg, before, after, image='neutral-image'):
    """The existing native receipt shape, with neutral instrument provenance."""
    folder.mkdir(parents=True, exist_ok=True)
    _put(folder / 'config.json', json.loads(cfg.read_text()))
    _put(folder / 'state_in.json', before)
    _put(folder / 'state_out.json', after)
    _put(folder / 'pdk_root.json', {'scope': 'unit instrument only'})
    (folder / 'invocation.log').write_text('neutral native instrument output\n')
    fp = {'image': image, 'config': lc.digest(cfg), 'step': step}
    _put(folder / 'input_fingerprint.json', fp)
    hashes = {p.name: lc.digest(p) for p in folder.iterdir() if p.is_file()
              and p.name != 'vibeic_receipt.json'}
    _put(folder / 'vibeic_receipt.json', {'input': fp, 'sha256': hashes})


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    project = tmp_path / 'project'
    base = project / 'phase3/librelane/candidate/01-openroad-repair'
    base.mkdir(parents=True)
    root, density_cfg = _pdk(tmp_path)
    cfg = json.loads(density_cfg.read_text())
    # Host paths make the recorded packet/config material independently readable.
    cfg['TECH_LEFS'] = {'nom_*': str(root / 'processA/tech/routing.tlef')}
    cfg['KLAYOUT_DEF_LAYER_MAP'] = str(root / 'processA/tech/layers.map')
    cfg['KLAYOUT_DENSITY_RUNSET'] = str(root / 'processA/tech/density.drc')
    script = root / 'processA/tech/fill_all.rb'
    script.write_text('# neutral PDK filler script\n')
    cfg['KLAYOUT_FILLER_SCRIPT'] = str(script)
    config = _put(base / 'candidate.json', {**cfg, 'meta': {'step': 'OpenROAD.RepairDesignPostGPL'}})
    routed = base / 'repaired.def'
    routed.write_text('DESIGN top ;\nUNITS DISTANCE MICRONS 1000 ;\n'
                      'DIEAREA ( 0 0 ) ( 100000 100000 ) ;\n')
    odb = base / 'repaired.odb'; odb.write_bytes(b'candidate OpenDB')
    state = base / 'state_out.json'
    _packet(base, 'OpenROAD.RepairDesignPostGPL', config, {},
            {'def': str(routed), 'odb': str(odb)})
    gds = base / 'stream.gds'; gds.write_bytes(b'candidate prefinishing')
    owners = [project / fill.RECORD_REL, project / fill.CELLS_REL,
              project / 'phase3/stage3/pnr/routed.def',
              project / 'reports/phase3/floorplan_rectangles.json']
    for path in owners:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('canonical owner must remain unchanged\n')
    original = {str(path): path.read_bytes() for path in [*owners, gds]}
    calls = []; damage = {'kind': None}

    def resolver(project, image, pdk, steps, *, folder, **kwargs):
        result = {}
        for step in steps:
            value = {**cfg, 'meta': {'step': step}}
            for key, (v, _) in (kwargs.get('overlay') or {}).items():
                value[key] = v
            if damage['kind'] == 'string_die' and 'DIE_AREA' in value:
                value['DIE_AREA'] = [str(item) for item in value['DIE_AREA']]
            if damage['kind'] == 'nonfinite_die' and 'DIE_AREA' in value:
                value['DIE_AREA'] = ['0', '0', 'NaN', '100']
            if damage['kind'] == 'missing_deck': value.pop('KLAYOUT_DENSITY_RUNSET')
            if damage['kind'] == 'missing_script': value.pop('KLAYOUT_FILLER_SCRIPT')
            path = _put(project / 'phase3/librelane' / folder / (step + '.json'), value)
            _put(lc.views_path(path), {'step': step, 'inputs': ['gds'],
                'outputs': (['gds'] if step == 'KLayout.Filler' else
                            ['spice'] if step == 'Magic.SpiceExtraction' else [])})
            result[step] = path
        return result

    def chain(project, image, steps, *, lane=None, namespace=None, **kwargs):
        assert not (lane and namespace)
        assert not lane or '/' not in lane  # real run_chain lane grammar
        parent = json.loads(Path(steps[0][2]).read_text()); folders = []
        for index, (step, config, _) in enumerate(steps, 1):
            folder = project / 'phase3/librelane' / (namespace or lane)
            folder /= f'{index:02d}-{step.lower().replace(".", "-")}'
            folder.mkdir(parents=True, exist_ok=True)
            before = json.loads(json.dumps(parent)); after = json.loads(json.dumps(parent))
            if step == 'KLayout.Filler':
                filled = folder / 'filled.gds'; filled.write_bytes(b'PDK filler output')
                after['gds'] = str(filled)
            if step == 'Magic.SpiceExtraction':
                spice = folder / 'extracted.spice'; spice.write_text('* neutral instrument\n')
                after['spice'] = str(spice)
            count = 3 if damage['kind'] == 'density' or b'TOPPED' not in Path(after['gds']).read_bytes() else 0
            if step == 'KLayout.Density':
                after.setdefault('metrics', {})[fill.DENSITY_METRIC] = count
            elif step in pv.PRODUCED:
                after.setdefault('metrics', {}).update({k: 0 for k in pv.PRODUCED[step]})
            _packet(folder, step, config, before, after, image)
            calls.append({'step': step, 'gds': after['gds'], 'density': count})
            parent = after; folders.append(folder)
            if step == 'Checker.KLayoutDensity' and count:
                raise lc.Refusal('LL_STEP_FAILED', 'Checker.KLayoutDensity: count=3')
        return folders

    def instrument(cmd, **kwargs):
        calls.append({'argv': cmd})
        if 'openroad' in cmd:
            tcl = Path(cmd[-1]); text = tcl.read_text()
            assert f'read_db {{{odb}}}' in text
            assert not re.search(r'^read_def ', text, re.M)
            assert str(owners[2]) not in text
            if damage['kind'] != 'keepouts':
                tcl.with_name('placed_keepouts.txt').write_text(
                    'DBU 1000\nTOTAL 1\nCORE 10000 10000 90000 90000\n'
                    'BOX PAD edge 0 0 5000 5000\nEND 1\n')
        elif str(cmd[cmd.index('python3') + 1]).endswith('metal_fill_emit.py'):
            out = Path(cmd[cmd.index('--out') + 1]); out.write_bytes(b'TOPPED candidate dummy metal')
            derived = json.loads(Path(cmd[cmd.index('--config') + 1]).read_text())
            assert derived['_derivation']['placed_instance_keepout']['source'] == str(odb)
            assert derived['keepout_edge_um'] == 10.0
            assert derived['keepout_boxes_um'] == [[-0.3, -0.3, 5.3, 5.3]]
            _put(Path(cmd[cmd.index('--report') + 1]), {
                'verdict': 'FAIL' if damage['kind'] == 'fill' else 'PASS',
                'keepout': {'declared': True},
                'gds_in': cmd[cmd.index('--gds') + 1],
                'gds_out': cmd[cmd.index('--out') + 1],
                'layers': [{'name': 'metal1'}]})
        else:
            specs = json.loads(Path(cmd[cmd.index('--specs') + 1]).read_text())
            _put(Path(cmd[cmd.index('--out') + 1]), {'status': 'MEASURED',
                 'layers': {key: {'ratio': .4} for key in specs}})
        return SimpleNamespace(returncode=0, stdout='neutral native output', stderr='')

    monkeypatch.setattr(fill, 'resolve_step_configs', resolver)
    monkeypatch.setattr(fill, 'run_chain', chain)
    monkeypatch.setattr(fill, 'run_container', instrument)
    monkeypatch.setattr(pv, 'resolve_step_configs', resolver)
    monkeypatch.setattr(pv, 'run_chain', chain)
    monkeypatch.setattr(pv, 'tech_lef_overlay', lambda p: None)
    return SimpleNamespace(project=project, root=root, cfg=density_cfg, config=config,
        state=state, odb=odb, routed=routed, gds=gds, calls=calls, damage=damage,
        original=original, resolver=resolver)


def test_candidate_finishes_then_full_pv_reads_exact_finished_bytes(candidate):
    c = candidate
    configs = c.resolver(c.project, 'neutral-image', 'processA', fill.GDS_FILL_STEPS,
                         folder='control-config')
    before = fill.run_density(c.project, 'neutral-image', c.root, 'processA',
        gds=c.gds, lane='unfilled-control', configs=configs,
        bridge_root=c.project / 'phase3/librelane/unfilled-control-bridges')
    assert before[fill.DENSITY_METRIC] == 3 and before['checker_error']


@pytest.mark.parametrize('die', [
    ['0', '0', 'NaN', '100'], ['0', '0', 'inf', '100'],
    ['0', '0', '0', '100'], ['100', '100', '0', '0'], ['0', '0', '100'],
])
def test_retained_finish_refuses_invalid_numeric_string_die(die):
    assert fill._finite_die_box(die) is None
