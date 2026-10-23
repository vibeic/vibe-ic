"""Real Default finishing/readback; controlled native process writes, no IC claim."""
import json
import hashlib
import shutil
import shlex
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import execution_policy as policy
import librelane_contract as LC
import librelane_fill_dfm as LF
import librelane_step37 as native37
import phase3_one_shot_runner as R
import step_output_collector as versions
import _default_backend_fixtures as BF
from test_default_finishing import subject, density_recipe, refresh_receipt, neutral_declared_windows


def _geometry(path, number=0):
    import klayout.db as db
    layout = db.Layout(); layout.dbu = 0.0005
    top = layout.create_cell('cal_pg')
    for layer in range(1, 6):
        top.shapes(layout.layer(layer, 0)).insert(db.Box(0, 0, 10000 + number, 10000))
    for name, x in [('a', 1000), ('y', 2000)]:
        top.shapes(layout.layer(2, 0)).insert(db.Text(name, db.Trans(x, 2000)))
    layout.write(str(path))


def _transport(tmp_path, monkeypatch, *, finished_geometry=False, native_views=False):
    neutral_declared_windows.__wrapped__(tmp_path, monkeypatch)
    monkeypatch.setattr(policy, 'request', lambda: {'mode': 'default'})
    monkeypatch.setattr(policy, '_ordinary_runtime', None)
    p, old, _ = subject(tmp_path)
    pnr = p / 'phase3/stage3/pnr'
    text = (pnr / 'routed.def').read_text()
    for name, x, direction in [('a', 1000, 'INPUT'), ('y', 2000, 'OUTPUT')]:
        text = text.replace(f'- {name} + NET {name} + DIRECTION {direction} + USE SIGNAL ;',
            f'- {name} + NET {name} + DIRECTION {direction} + USE SIGNAL + PORT + LAYER Metal2 ( -100 -100 ) ( 100 100 ) + PLACED ( {x} 2000 ) N ;')
    for name in ('routed.def', 'top.def'):
        (pnr / name).write_text(text)
    fill = BF.fill_record(p)
    if native_views:
        state_path = Path(fill['state'])
        netlist = state_path.parent / 'cal_pg_pnr.v'
        netlist.write_text('module cal_pg; endmodule\n')
        sdc = state_path.parent / 'constraint.sdc'
        sdc.write_text('create_clock -period 10 [get_ports clk]\n')
        state = json.loads(state_path.read_text())
        state.update(nl=str(netlist), sdc=str(sdc))
        BF.put(state_path, state)
        refresh_receipt(state_path.parent)
        fill['state_sha256'] = LC.digest(state_path)
        fill['binding']['receipt_sha256'] = LC.digest(state_path.parent / 'vibeic_receipt.json')
    BF.consume_fill(p, fill)
    LF.update_record(p, 'odb', {'shipped': 'librelane', 'tool': fill,
                              'def_sha256': LC.digest(pnr / 'routed.def')})
    BF.put(p / 'input/submission_template/tapeout_declaration.json', {'answers': {'deliverable': 'DIE'}})
    BF.put(p / 'input/submission_template/slots/neutral.yaml', {})
    # Begin with no old promotion: the first successful call below is real.
    (p / LF.DEFAULT_STREAM_REL).unlink()
    doc = json.loads((p / LF.RECORD_REL).read_text()); doc.pop('default_stream')
    BF.put(p / LF.RECORD_REL, doc)
    root = p / 'fixture_pdk'
    files = {}
    for flag, name in [('--input-lef', 'stream.lef'), ('--lyt', 'stream.lyt'),
                       ('--lyp', 'stream.lyp'), ('--lym', 'stream.lym')]:
        f = root / 'neutral' / name; f.write_text('SOURCE_FIXTURE ' + name + '\n')
        files[flag] = '/pdk/neutral/' + name
    native_script = '/native/stream_out.py'
    recipe_text = '# SOURCE_FIXTURE controlled native stream process\n'
    calls = []
    failed = {'stream': False}
    monkeypatch.setattr(R, '_librelane_step_ctx', lambda *a: (BF.IMAGE, root))

    def configs(project, image, pdk, ids, **kwargs):
        return {sid: p / 'phase3/librelane/34-config' / (sid + '.json') for sid in ids}
    monkeypatch.setattr(LF, 'resolve_step_configs', configs)

    def image_transport(argv, **kwargs):
        if 'get_script_dir' in argv[-1]:
            payload = {'path': native_script, 'text': recipe_text}
        else:
            paths = json.loads(argv[-1])
            payload = {path: hashlib.sha256(recipe_text.encode()).hexdigest() if path == native_script
                       else LC.digest(root / Path(path).relative_to('/pdk')) for path in paths}
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload), '')
    monkeypatch.setattr(LF, 'run_container', image_transport)

    def stream(project, image, steps, **kwargs):
        calls.append('primary')
        if failed['stream']:
            raise LC.Refusal('LL_STEP_FAILED', 'controlled failed new native stream')
        assert [s[0] for s in steps] == ['KLayout.StreamOut']
        before = json.loads(Path(steps[0][2]).read_text())
        target = p / 'phase3/librelane/37-default-stream/01-klayout-streamout/top.gds'
        _geometry(target, len(calls))
        folder, _ = BF.producer(p, 'KLayout.StreamOut', before,
            {'def': before['def'], 'klayout_gds': str(target), 'metrics': {}},
            lane='37-default-stream/01-klayout-streamout', name='cal_pg')
        cfg = json.loads((folder / 'config.json').read_text())
        cfg.update(TECH_LEFS=[files['--input-lef']], KLAYOUT_TECH=files['--lyt'],
                   KLAYOUT_PROPERTIES=files['--lyp'], KLAYOUT_DEF_LAYER_MAP=files['--lym'])
        BF.put(folder / 'config.json', cfg); BF.put(steps[0][1], cfg)
        fp = json.loads((folder / 'input_fingerprint.json').read_text())
        fp.update(config=LC.digest(steps[0][1]), config_files=LC.config_file_hashes(cfg, [(root, '/pdk')]))
        BF.put(folder / 'input_fingerprint.json', fp)
        argv = ['python3', native_script, before['def'], '--output', str(target), '--top', 'cal_pg']
        for flag, value in files.items(): argv.extend([flag, value])
        (folder / 'COMMANDS').write_text(shlex.join(argv) + '\n')
        refresh_receipt(folder)
        return [folder]
    monkeypatch.setattr(LF, 'run_chain', stream)

    def seal(project, top, pdk, target, container):
        calls.append('seal')
        # This is the native process write seam. The original retained
        # finishing consumer, output contracts and report reader run below.
        BF.put(p / 'reports/phase3/die_finishing.json', {'producer': 'die_finishing_gen',
            'seal_ring': {'state': 'PASS', 'consumed_into': str(target.relative_to(p)),
                          'staged_sha256': LC.digest(target)},
            'die_id': {'state': 'NOT_APPLICABLE'}})
        (pnr / 'die_finished.def').write_bytes((pnr / 'routed.def').read_bytes())
        return True, 'controlled native seal measurement', 'PASS'
    monkeypatch.setattr(R, '_die_finishing_native', seal)

    def density(project, image, root, pdk, *, gds, lane, **kwargs):
        calls.append('filler-density')
        target = p / 'phase3/librelane/34-fill/01-klayout-filler/top.gds'
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(gds, target)
        if finished_geometry:
            _geometry(target, 100)
        folder, _ = BF.producer(p, 'KLayout.Filler', {'gds': str(gds), 'metrics': {}},
            {'gds': str(target), 'metrics': {}}, lane='34-fill/01-klayout-filler')
        arm = BF.density_record(p, target, 0)
        density_recipe(p, arm)
        arm['filler'] = {'state': str(folder / 'state_out.json'), 'state_sha256': LC.digest(folder / 'state_out.json'),
            'gds_in': str(gds), 'gds_in_sha256': LC.digest(gds), 'filled_gds': str(target),
            'filled_sha256': LC.digest(target), 'script': 'SOURCE_FIXTURE native filler'}
        return arm
    monkeypatch.setattr(LF, 'run_density', density)

    def gate_process(argv, **kwargs):
        # Same official-image Python process boundary, actual gate programs.
        command = argv[argv.index('--skip') + 1:]
        return subprocess.run(command, capture_output=True, text=True, check=False)
    monkeypatch.setattr(native37, 'run_container', gate_process)
    return p, SimpleNamespace(name='neutral'), calls, failed


@pytest.mark.parametrize('retry', ['success', 'native_fail'])
def test_real_default_stream_retries_a_changed_route_and_retains_prior_epoch(tmp_path, monkeypatch, retry):
    p, pdk, calls, failed = _transport(tmp_path, monkeypatch)
    first = LF.default_stream(p, 'top', pdk, '')
    first_bytes = (p / LF.DEFAULT_STREAM_REL).read_bytes()
    first_stream = Path(first['stream']).read_bytes()
    assert LF.validate_default_stream(p)['canonical_sha256'] == LC.digest(Path(first['canonical']))
    LF.default_stream(p, 'top', pdk, '')
    assert calls == ['primary', 'seal', 'filler-density'], calls
    routed = p / 'phase3/stage3/pnr/routed.def'
    routed.write_text(routed.read_text() + '\n# legitimate new route epoch\n')
    # The existing fill producer must bind the new route before streaming it.
    def refill(project, top, pdk, container, target, notes):
        record = BF.fill_record(p, subject=routed)
        BF.consume_fill(p, record)
        LF.update_record(p, 'odb', {'shipped': 'librelane', 'tool': record,
                                  'def_sha256': LC.digest(routed)})
        return True
    monkeypatch.setattr(R, '_emit_metal_fill', refill)
    failed['stream'] = retry == 'native_fail'
    if failed['stream']:
        with pytest.raises(LC.Refusal, match='controlled failed new native stream'):
            LF.default_stream(p, 'top', pdk, '')
        assert calls.count('primary') == 2
        assert (p / LF.DEFAULT_STREAM_REL).read_bytes() == first_bytes
        with pytest.raises((LC.Refusal, ValueError, KeyError)):
            LF.validate_default_stream(p)
    else:
        second = LF.default_stream(p, 'top', pdk, '')
        assert calls == ['primary', 'seal', 'filler-density'] * 2
        assert Path(second['stream']).read_bytes() != first_stream
        assert LF.validate_default_stream(p) == json.loads((p / LF.DEFAULT_STREAM_REL).read_text())
        assert versions.latest_pass(p, '26.5ic')['current_inputs']
    old = []
    for before in versions._versions_root(p).glob('*/*/*/before/outputs.json'):
        old.extend((before.parent / row['snapshot']).read_bytes()
                   for row in json.loads(before.read_text()).get('outputs', [])
                   if row['rel'] == LF.DEFAULT_STREAM_REL)
    assert first_bytes in old, 'prior promotion must remain in existing before history'


@pytest.mark.parametrize('damage', ['current', 'wrong_def', 'changed_filled',
                                    'changed_material', 'missing_readset', 'changed_recipe'])
def test_actual_373_owner_only_reaches_transport_with_current_bound_filled_def(
        tmp_path, monkeypatch, damage):
    import _native373_current as native
    import gds_xor_check as xor
    import librelane_pv_signoff as pv
    p, pdk, calls, _ = _transport(tmp_path, monkeypatch, native_views=True)
    record = LF.default_stream(p, 'top', pdk, '')
    pnr = p / 'phase3/stage3/pnr'
    filled = pnr / 'filled.def'
    (pnr / 'cal_pg_pnr.v').write_text('module cal_pg; endmodule\n')
    (pnr / 'constraint.sdc').write_text('create_clock -period 10 [get_ports clk]\n')
    BF.put(p / 'reports/phase3/technology_units.json', {'pdk': 'neutral'})
    root = p / 'fixture_pdk'
    monkeypatch.setattr(LC, 'pdk_root_resolution', lambda *a, **k: {'path': str(root)})
    monkeypatch.setattr(pv, 'tech_lef_overlay', lambda *a: {})
    observed = []
    class ReachedNativeTransport(Exception):
        pass
    def configurations(project, image, pdk, steps, **kwargs):
        return {step: p / 'phase3/librelane/34-config' / (step + '.json') for step in steps}
    def bridge(project, image, config, views, *args, **kwargs):
        observed.append({name: str(path) for name, path in views.items()})
        assert kwargs['mounts'] == [(root, '/pdk')]
        raise ReachedNativeTransport
    monkeypatch.setattr(LC, 'resolve_step_configs', configurations)
    monkeypatch.setattr(LC, 'state_from_direct', bridge)
    if damage == 'changed_filled': filled.write_text(filled.read_text() + '\n# changed current source\n')
    elif damage == 'changed_material': (root / 'neutral/stream.lef').write_text('changed actual native readset\n')
    elif damage == 'missing_readset': (pnr / 'top.stream_inputs.json').unlink()
    elif damage == 'changed_recipe': (pnr / 'stream_out.py').write_text('changed actual recipe\n')
    if damage == 'current':
        shipped, source, attestation = xor.shipped_and_source(p)
        assert source == filled and source != pnr / 'routed.def'
        assert shipped == Path(record['canonical'])
        with pytest.raises(ReachedNativeTransport): native.produce(p, source)
        consumed = json.loads((p / LF.RECORD_REL).read_text())['odb']['tool']
        state_path = Path(consumed['state'])
        state = json.loads(state_path.read_text())
        receipt = LC.validate_step_receipt(state_path.parent, LF.ODB_FILL_STEP)
        assert observed == [{'def': str(filled), 'nl': state['nl'], 'sdc': state['sdc']}]
        for role in ('nl', 'sdc'):
            output = Path(state[role])
            assert output.parent == state_path.parent
            assert receipt['sha256'][output.name] == LC.digest(output)
        assert Path(state['nl']) != pnr / 'cal_pg_pnr.v'
    else:
        with pytest.raises((LC.Refusal, OSError, ValueError, KeyError)):
            native.produce(p, pnr / 'routed.def' if damage == 'wrong_def' else filled)
        assert observed == []
    assert calls == ['primary', 'seal', 'filler-density']


@pytest.mark.parametrize('boundary', ['recipe', 'inputs'])
def test_default_stream_metadata_probes_reach_the_real_execution_contract(
        tmp_path, monkeypatch, boundary):
    """Real caller/guard/current reader; only the metadata process is controlled.

    Both queries precede publication of the bound stream readset. The actual
    stream/fill process seams retain the existing neutral fixture; no EDA runs.
    """
    p, pdk, calls, _ = _transport(tmp_path, monkeypatch)
    metadata_process = LF.run_container
    observed = []
    guarded = []

    def local_metadata(argv, *, probe_deadline_s, supervised, **kwargs):
        assert probe_deadline_s == LC.PROBE_DEADLINE_S
        assert supervised is False
        guarded.append(boundary)
        return metadata_process(argv)

    def metadata_boundary(argv, **kwargs):
        query = 'recipe' if 'get_script_dir' in argv[-1] else 'inputs'
        observed.append(query)
        if query == boundary:
            return LC.run_container(argv, **kwargs)
        return metadata_process(argv, **kwargs)

    monkeypatch.setattr(LC, '_provider_for_image', lambda image: object())
    monkeypatch.setattr(LC, '_provider_route_mismatch', lambda image: None)
    monkeypatch.setattr(LC, '_run_local', local_metadata)
    monkeypatch.setattr(LF, 'run_container', metadata_boundary)
    record = LF.default_stream(p, 'top', pdk, '')
    assert observed == ['recipe', 'inputs']
    assert guarded == [boundary]
    assert calls == ['primary', 'seal', 'filler-density']
    assert LF.validate_default_stream(p) == json.loads(
        (p / LF.DEFAULT_STREAM_REL).read_text())
    assert LC.digest(Path(record['canonical'])) == record['canonical_sha256']
    readset = json.loads((p / 'phase3/stage3/pnr/top.stream_inputs.json').read_text())
    assert readset['native_cli']['inputs']
    assert Path(record['canonical']).stat().st_size > 0


def _native373_boundary_subject(tmp_path, monkeypatch):
    """Neutral process fixture; real whole-stream, receipt and material readers."""
    import klayout.db as db
    original_geometry = _geometry

    def geometry(path, number=0):
        original_geometry(path, 1)
        if number == 100:
            layout = db.Layout(); layout.read(str(path))
            fill = layout.create_cell('DECLARED_FILL')
            fill.shapes(layout.layer(34, 4)).insert(db.Box(0, 0, 100, 100))
            layout.top_cells()[0].insert(db.CellInstArray(fill.cell_index(), db.Trans()))
            layout.write(str(path))
    monkeypatch.setattr(sys.modules[__name__], '_geometry', geometry)
    p, _, calls, _ = _transport(tmp_path, monkeypatch, finished_geometry=True)
    root = p / 'fixture_pdk'
    tech = root / 'neutral/stream.lef'
    tech.write_text('UNITS\n DATABASE MICRONS 2000 ;\nEND UNITS\nMANUFACTURINGGRID 0.005 ;\n')
    script = root / 'neutral/filler.rb'
    script.write_text('Dummy = $ly.layer(34, 4)\nDesign = $ly.layer(32, 0)\n'
                      '$fill_cell = $ly.create_cell("DECLARED_FILL")\n')
    density = LF.run_density

    def native_density(*args, **kwargs):
        arm = density(*args, **kwargs)
        folder = Path(arm['filler']['state']).parent
        config = p / 'phase3/librelane/34-config/KLayout.Filler.json'
        cfg = json.loads(config.read_text())
        cfg['KLAYOUT_FILLER_SCRIPT'] = str(script)
        BF.put(config, cfg); BF.put(folder / 'config.json', cfg)
        fp = json.loads((folder / 'input_fingerprint.json').read_text())
        fp.update(config=LC.digest(config), config_files=LC.config_file_hashes(cfg, [(root, '/pdk')]))
        BF.put(folder / 'input_fingerprint.json', fp)
        refresh_receipt(folder)
        return arm
    monkeypatch.setattr(LF, 'run_density', native_density)
    odb = json.loads((p / LF.RECORD_REL).read_text())['odb']
    tool = odb['tool']; state_path = Path(tool['state']); state = json.loads(state_path.read_text())
    for role, name, text in [('nl', 'cal_pg.nl.v', 'module cal_pg; endmodule\n'),
                              ('sdc', 'cal_pg.sdc', 'create_clock -period 10 [get_ports clk]\n')]:
        path = state_path.parent / name; path.write_text(text); state[role] = str(path)
    BF.put(state_path, state); refresh_receipt(state_path.parent)
    tool['state_sha256'] = LC.digest(state_path)
    tool['binding']['receipt_sha256'] = LC.digest(state_path.parent / 'vibeic_receipt.json')
    BF.consume_fill(p, tool); LF.update_record(p, 'odb', odb)
    cell_gds = root / 'neutral/cells.gds'; original_geometry(cell_gds)
    pdk = SimpleNamespace(name='neutral', tech_lef=str(tech), cell_gds=str(cell_gds))
    stream = LF.default_stream(p, 'top', pdk, '')
    return p, pdk, root, stream, calls


@pytest.mark.parametrize('condition', ['current', 'thin', 'design_difference',
                                      'changed_material', 'missing_proof'])
def test_normal373_uses_real_die_and_same_boundary_with_owned_fill_only(
        tmp_path, monkeypatch, condition):
    """Original normal producer/public XOR/current judge, neutral native leaves.

    No physical XOR, independent stream or whole-IC PASS is claimed here.
    """
    import execution_backend_producers as EBP
    import _native373_current as native
    import librelane_pv_signoff as pv
    import _klayout_launch as KL
    import gds_xor_check as xor
    p, pdk, root, stream, calls = _native373_boundary_subject(tmp_path, monkeypatch)
    filled = Path(stream['filled_def'])
    declaration = p / 'input/submission_template/tapeout_declaration.json'
    original_declaration = declaration.read_bytes()
    monkeypatch.setattr(EBP, '_parameters', lambda *a: (R, LC, pdk, ''))
    monkeypatch.setattr(LC, 'pdk_root_resolution', lambda *a, **k: {'path': str(root)})
    monkeypatch.setattr(pv, 'tech_lef_overlay', lambda *a: {})
    reached = []

    def configs(project, image, name, steps, **kwargs):
        assert steps == list(native.STEPS), 'the independent Magic/KLayout chain must remain'
        assert kwargs['overlay'].get('DIE_AREA') == (
            LC._def_die_area(filled), f'{filled}: DIEAREA / UNITS DISTANCE MICRONS'), 'actual DEF/DBU DIE_AREA missing'
        reached.append('independent_config')
        return {step: p / 'phase3/librelane/34-config' / (step + '.json') for step in steps}
    monkeypatch.setattr(LC, 'resolve_step_configs', configs)

    def unavailable_native(*args, **kwargs):
        # Preserve the actual native producer until its process boundary. The
        # fallback's retained reference cannot manufacture connectivity credit.
        raise LC.Refusal('SOURCE_CONTROL', 'independent native process not executed')
    monkeypatch.setattr(LC, 'state_from_direct', unavailable_native)
    runs = []

    class NativeProcess:
        kind, detail = 'source_control', 'neutral native XOR transcript; no geometry measurement'
        def covers(self, path):
            return True
        def run(self, recipe, env, **kwargs):
            assert env['XOR_BOUNDARY'] == Path(stream['stream'])
            assert env['XOR_REFERENCE'] == Path(stream['stream'])
            assert recipe.read_text() == xor._XOR_RB
            runs.append(dict(env))
            ref = 1 if condition == 'thin' else 10
            design = 1 if condition == 'design_difference' else 0
            return 0, (f'XOR_TOOL klayout\nXOR_TOP shipped=cal_pg reference=cal_pg\n'
                f'XOR_CENSUS shipped_cells=20 shipped_shapes=1000 reference_cells=10 reference_shapes={ref}\n'
                'XOR_BOUNDARY_CENSUS cells=10 shapes=10\n'
                f'XOR_LAYER 32/0 {design}\nXOR_LAYER 34/4 600\nXOR_DONE\n'), ''
    monkeypatch.setattr(KL, 'find_runner', lambda *a, **k: NativeProcess())
    if condition == 'changed_material':
        (root / 'neutral/stream.lef').write_text('changed retained material\n')
    elif condition == 'missing_proof':
        (Path(stream['stream_state']).parent / 'vibeic_receipt.json').unlink()
    if condition in ('changed_material', 'missing_proof'):
        with pytest.raises(LC.Refusal):
            EBP.produce_signoff(p, {'step_id': '37.3', 'execution_mode': 'default',
                'top': 'cal_pg', 'pdk_root': str(root), 'image_id': BF.IMAGE})
        assert xor.main([str(p), '--json', str(p / xor.REPORT_REL)]) == 2
        assert xor.judge_receipt(p, xor.REPORT_REL)[0] == 2
        assert runs == reached == []
        assert declaration.read_bytes() == original_declaration
        return
    result = EBP.produce_signoff(p, {'step_id': '37.3', 'execution_mode': 'default',
        'top': 'cal_pg', 'pdk_root': str(root), 'image_id': BF.IMAGE})
    path = p / xor.REPORT_REL
    report = json.loads(path.read_text())
    rc, line, judged = xor.judge_receipt(p, xor.REPORT_REL)
    assert declaration.read_bytes() == original_declaration
    assert calls == ['primary', 'seal', 'filler-density']
    assert reached == ['independent_config'] and len(runs) == 1
    assert report['current']['inputs']['boundary']['sha256'] == stream['stream_sha256']
    assert judged['current'] == report['current']
    if condition == 'thin':
        assert report['rc'] == rc == 2 and result['verdict'] == 'NOT_MEASURED'
        assert 'refusing to compare' in report['reason']
    elif condition == 'design_difference':
        assert result['verdict'] == 'FAIL' and report['rc'] == rc == 1
        assert report['design_layer_differences'] == [{'layer': 32, 'datatype': 0, 'differences': 1}]
    else:
        assert result['verdict'] == report['verdict'] == 'PASS'
        assert report['rc'] == 0 and report['design__xor_difference__count'] == 0
        assert report['finishing_layer_differences'] == [
            {'layer': 34, 'datatype': 4, 'differences': 600, 'declared_by': 'density_fill'}]
        assert rc == 2 and report['connectivity']['verdict'] == 'NOT_DETERMINED', line
        assert report['declared_finishing_layers']['fill']['pairs'] == ['34/4']
        assert xor.reference_is_faithful((p / 'reports/phase3/gds_xor_native.log').read_text())[0] is False


from test_librelane_contract import local_image  # existing real attestation reader fixture


@pytest.mark.parametrize('condition', ['current', 'missing_receipt', 'changed_material', 'nonzero',
                                      'local_runner', 'local_runner_nonzero',
                                      'local_runner_retained_8g'])
def test_normal373_local_receipts_reach_original_connectivity_consumer(
        tmp_path, monkeypatch, local_image, condition):
    """Real normal producer/LOCAL runner/receipts/consumer; neutral EDA leaves.

    The controlled stream and XOR results qualify evidence plumbing only, not
    physical XOR, independent tool measurements or canonical IC PASS.
    """
    import execution_backend_producers as EBP
    import _native373_current as native
    import _physical_current as pc
    import _watchdog as watchdog
    import librelane_pv_signoff as pv
    import gds_xor_check as xor
    monkeypatch.setattr(BF, 'IMAGE', local_image.image)
    p, pdk, root, stream, calls = _native373_boundary_subject(tmp_path, monkeypatch)
    # The finishing fixture has a named-Docker process edge. This antecedent
    # explicitly chooses the actual attested LOCAL route for the three streams.
    monkeypatch.setattr(LC._ce, 'no_container_route', lambda: True)
    monkeypatch.setenv('VIBEIC_DOCKER_MEMORY', '4g')
    if condition.startswith('local_runner'):
        if getattr(local_image, 'readonly_attestation', False):
            # A real host launch receipt is immutable. Require the actual
            # test container to provide the same bounds as this fixture.
            identity = LC.local_image_attestation(local_image.image)
            assert identity['memory'] == identity['memory_swap'] == 32 * 1024**3
            assert identity['network_mode'] == 'none'
        else:
            launch = json.loads(local_image.receipt.read_text())
            launch['container_inspect']['HostConfig'].update(
                NanoCpus=8_000_000_000, Memory=32 * 1024**3, MemorySwap=32 * 1024**3)
            BF.put(local_image.receipt, launch)
        monkeypatch.setenv('VIBEIC_DOCKER_MEMORY', '32g')
    monkeypatch.setattr(EBP, '_parameters', lambda *a: (R, LC, pdk, ''))
    monkeypatch.setattr(LC, 'pdk_root_resolution', lambda *a, **k: {'path': str(root)})
    monkeypatch.setattr(LC, 'image_capability', lambda *a: None)
    monkeypatch.setattr(LC, 'openroad_home', lambda *a, **k: None)
    monkeypatch.setattr(pv, 'tech_lef_overlay', lambda *a: {})
    declaration = p / 'input/submission_template/tapeout_declaration.json'
    original_declaration = declaration.read_bytes()
    material = root / 'neutral/stream.lef'

    def configs(project, image, name, steps, **kwargs):
        assert steps == list(native.STEPS)
        assert kwargs['overlay']['DIE_AREA'][0] == LC._def_die_area(Path(stream['filled_def']))
        # Reuse the fixture's original canonical stream config/readset rather
        # than declaring a second list of its four native materials.
        source_config = json.loads((Path(stream['stream_state']).parent / 'config.json').read_text())
        paths = {step: BF.put(p / native.CONFIG / (step + '.json'), {
            **source_config, 'meta': {'step': step}}) for step in steps}
        for step, path in paths.items():
            inputs = ['mag_gds', 'klayout_gds'] if step == native.STEPS[-1] else ['odb', 'def', 'nl', 'sdc']
            BF.put(LC.views_path(path), {'step': step, 'inputs': inputs, 'outputs': []})
        return paths
    monkeypatch.setattr(LC, 'resolve_step_configs', configs)

    def neutral_db_conversion(project, image, config, lines, folder, name, *args):
        assert name == 'def_to_odb'
        # Only the EDA database conversion leaf is controlled. The original
        # state_from_direct bridge still binds all real source views.
        for line in lines:
            if line.startswith('write_db {'):
                Path(line[len('write_db {'):-1]).write_text('SOURCE_CONTROL neutral database')
        recipe = folder / (name + '.tcl'); recipe.write_text('\n'.join(lines))
        return recipe
    monkeypatch.setattr(LC, '_openroad_convert', neutral_db_conversion)
    executed, geometry_commands, requests = [], [], []
    geometry_text = ('XOR_TOOL klayout\nXOR_TOP shipped=cal_pg reference=cal_pg\n'
        'XOR_CENSUS shipped_cells=20 shipped_shapes=1000 reference_cells=10 reference_shapes=10\n'
        'XOR_BOUNDARY_CENSUS cells=10 shapes=10\n'
        'XOR_LAYER 32/0 0\nXOR_LAYER 34/4 600\nXOR_DONE\n')
    original_container = LC.run_container
    def observe_request(argv, **kwargs):
        requests.append(list(argv))
        return original_container(argv, **kwargs)
    monkeypatch.setattr(LC, 'run_container', observe_request)

    def neutral_process(argv, **kwargs):
        if argv[:2] == ['/usr/bin/time', '-v']:
            assert argv[2] == shutil.which('klayout')
            assert kwargs['env']['XOR_BOUNDARY'] == str(stream['stream'])
            geometry_commands.append(list(argv))
            return watchdog.SupervisedResult(0, geometry_text, '', 'natural')
        assert argv[:4] == ['python3', '-m', 'librelane.steps', 'run']
        step = argv[argv.index('--id') + 1]
        folder = Path(argv[argv.index('-o') + 1])
        state = json.loads(Path(argv[argv.index('-i') + 1]).read_text())
        if step in native.STEPS[:2]:
            role = 'mag_gds' if step == native.STEPS[0] else 'klayout_gds'
            # Two file encodings retain neutral equal geometry but distinct bytes.
            gds = folder / (role + ('.oas' if role == 'mag_gds' else '.gds'))
            _geometry(gds)
            state[role] = str(gds)
        else:
            count = 1 if condition in ('nonzero', 'local_runner_nonzero') else 0
            state['metrics'] = {native.KEY: count}
            (folder / 'xor.xml').write_text(
                '<report-database><top-cell>cal_pg</top-cell><description>'
                f"XOR {state['mag_gds']} vs. {state['klayout_gds']}"
                '</description><items>' + '<item/>' * count + '</items></report-database>')
        BF.put(folder / 'state_in.json', json.loads(Path(argv[argv.index('-i') + 1]).read_text()))
        BF.put(folder / 'state_out.json', state)
        BF.put(folder / 'config.json', json.loads(Path(argv[argv.index('-c') + 1]).read_text()))
        executed.append(step)
        # Match the real LOCAL log shape: neither Docker launch journal nor
        # the Docker /usr/bin/time 'Exit status: 0' wrapper exists.
        return watchdog.SupervisedResult(0, 'SOURCE_CONTROL neutral native ' + step, '', 'natural')
    monkeypatch.setattr(watchdog, 'run_host_supervised', neutral_process)

    def geometry_process(self, recipe, env, **kwargs):
        assert env['XOR_BOUNDARY'] == Path(stream['stream'])
        self.execution = {'rc': 0, 'argv': ['SOURCE_CONTROL', 'shipped_geometry']}
        return 0, geometry_text, ''
    if not condition.startswith('local_runner'):
        monkeypatch.setattr(native.ShippedXorRunner, 'run', geometry_process)
    # The current 37.3 contract has a distinct native dependency producer and
    # backend consumer.  Drive the producer first; produce_signoff now consumes
    # its retained receipt and must not be expected to launch these steps.
    R.publish_database_unit_declaration(
        p, pdk, '', native._source_def(p), publish_declaration=False)
    native.produce(p, Path(stream['filled_def']))
    assert executed == list(native.STEPS)
    result = EBP.produce_signoff(p, {'step_id': '37.3', 'execution_mode': 'default',
        'top': 'cal_pg', 'pdk_root': str(root), 'image_id': local_image.image})
    assert result['verdict'] == 'PASS', result
    assert not (p / 'phase3/librelane/37.3-launches.jsonl').exists()
    if condition == 'local_runner_retained_8g':
        launch = json.loads(local_image.receipt.read_text())
        launch['container_inspect']['HostConfig'].update(
            Memory=8 * 1024**3, MemorySwap=8 * 1024**3)
        BF.put(local_image.receipt, launch)
    dependency = native.read_current(p)
    assert dependency['count'] == (1 if condition in ('nonzero', 'local_runner_nonzero') else 0)
    assert 'launches' not in dependency['current']['outputs']
    assert dependency['current']['execution']['kind'] == 'retained_local_step_receipt'
    receipts = {}
    for rel in dependency['folders']:
        folder = p / rel
        receipts[str(folder)] = (folder / 'vibeic_receipt.json').read_bytes()
        assert json.loads((folder / 'pdk_root.json').read_text())['execution_route'] == 'LOCAL'
        assert 'Exit status: 0' not in (folder / 'invocation.log').read_text()
    if condition == 'missing_receipt':
        (p / dependency['folders'][0] / 'vibeic_receipt.json').unlink()
    elif condition == 'changed_material':
        material.write_text('changed original native material\n')
    expected = 2 if condition in ('missing_receipt', 'changed_material') else 1 if condition in ('nonzero', 'local_runner_nonzero') else 0
    rc, line, report = xor.judge_receipt(p, xor.REPORT_REL)
    assert rc == expected, line
    assert report['verdict'] == 'PASS'  # original geometry is a separate answer
    assert report['connectivity']['verdict'] == ('FAIL' if condition in ('nonzero', 'local_runner_nonzero') else 'PASS')
    if condition.startswith('local_runner'):
        assert len(geometry_commands) == 1
        assert report['runner'] == {'kind': 'host', 'detail': shutil.which('klayout') + ' -b -r'}
        assert report['current']['execution']['argv'] == geometry_commands[0]
        assert report['current']['execution']['argv'][0] == '/usr/bin/time'
        request = requests[-1]
        assert '--cpus' not in request
        assert request[request.index('--memory') + 1] == request[request.index('--memory-swap') + 1] == '32g'
        assert '--rm' in request and request[request.index('--network') + 1] == 'none'
        assert request[request.index(local_image.image) + 1] == '--skip'
    assert declaration.read_bytes() == original_declaration
    assert executed == list(native.STEPS), 'read-only consumer must not rerun any native step'
    assert all((Path(folder) / 'vibeic_receipt.json').read_bytes() == data
               for folder, data in receipts.items() if (Path(folder) / 'vibeic_receipt.json').exists())


def test_shipped_xor_named_docker_retains_its_original_launch_envelope(tmp_path, monkeypatch):
    """The real Docker parser retains its old resource flags; neutral exec leaf."""
    import _native373_current as native
    import _watchdog as watchdog
    from _stated_eda_image import mock_docker_route, stated_image
    mock_docker_route(monkeypatch)
    monkeypatch.setenv('VIBEIC_DOCKER_MEMORY', '4g')
    image = stated_image()
    commands = []
    def neutral_process(argv, **kwargs):
        commands.append(list(argv))
        return watchdog.SupervisedResult(0, 'SOURCE_CONTROL Docker exec leaf', '', 'natural')
    monkeypatch.setattr(watchdog, 'run_host_supervised', neutral_process)
    runner = native.ShippedXorRunner(tmp_path, image)
    assert runner.kind == 'docker_run' and runner.detail == image + ':klayout'
    rc, _, _ = runner.run(tmp_path / 'xor.rb', {})
    assert rc == 0 and len(commands) == 1
    argv = commands[0]
    assert argv[:2] == ['docker', 'run'] and '--name' in argv
    assert argv[argv.index('--cpus') + 1] == '2'
    assert argv[argv.index('--memory') + 1] == argv[argv.index('--memory-swap') + 1] == '4g'
    assert '--rm' in argv and argv[argv.index('--network') + 1] == 'none'
    assert argv[argv.index(image) + 1:argv.index(image) + 5] == ['--skip', '/usr/bin/time', '-v', 'klayout']
    assert runner.execution['argv'] == [v for i, v in enumerate(argv) if i not in (2, 3)]


def test_fresh_typed_local373_reaches_native_and_current_connectivity(tmp_path, monkeypatch):
    """True typed LOCAL admission/three receipts/XOR runner; neutral EDA leaves."""
    import execution_backend_producers as EBP
    import _native373_current as native
    import _watchdog as watchdog
    import librelane_pv_signoff as pv
    import gds_xor_check as xor
    p, pdk, root, stream, calls = _native373_boundary_subject(tmp_path, monkeypatch)
    source = tmp_path / 'provider'
    (source / 'librelane').mkdir(parents=True)
    (source / 'librelane/__init__.py').write_text('# neutral provider source\n')
    BF.put(p / 'phase3/librelane_switch.json', {
        'execution_route': 'LOCAL', 'pdk_root_host': str(root), 'pdk': 'neutral',
        'librelane_root_host': str(source), 'librelane_executable': sys.executable,
        'local_network_mode': 'host'})
    monkeypatch.setenv(LC.LOCAL_PROVIDER_ROUTE_ENV, 'LOCAL')
    monkeypatch.setenv('VIBEIC_DOCKER_MEMORY', '4g')
    monkeypatch.setattr(EBP, '_parameters', lambda *a: (R, LC, pdk, ''))
    monkeypatch.setattr(LC, 'image_capability', lambda *a: None)
    monkeypatch.setattr(LC, 'openroad_home', lambda *a, **k: None)
    monkeypatch.setattr(pv, 'tech_lef_overlay', lambda *a: {})
    original_declaration = (p / 'input/submission_template/tapeout_declaration.json').read_bytes()
    image = LC.resolve_image(p)
    assert isinstance(image, LC.LocalProviderIdentity)
    # Rebuild the existing neutral antecedent under the selected provider.
    # Its prior OCI fill receipt cannot stand in for a typed LOCAL producer.
    monkeypatch.setattr(BF, 'IMAGE', image)
    previous = json.loads((p / LF.RECORD_REL).read_text())['odb']['tool']
    before = json.loads(Path(previous['state']).read_text())
    tool = BF.fill_record(p)
    state_path = Path(tool['state'])
    state = json.loads(state_path.read_text())
    state.update({key: before[key] for key in ('nl', 'sdc')})
    BF.put(state_path, state); refresh_receipt(state_path.parent)
    tool['state_sha256'] = LC.digest(state_path)
    tool['binding']['receipt_sha256'] = LC.digest(state_path.parent / 'vibeic_receipt.json')
    BF.consume_fill(p, tool)
    LF.update_record(p, 'odb', {'shipped': 'librelane', 'tool': tool,
        'def_sha256': LC.digest(p / 'phase3/stage3/pnr/routed.def')})
    calls.clear()
    stream = LF.default_stream(p, 'top', pdk, '')

    def configs(project, selected, name, steps, **kwargs):
        assert steps == list(native.STEPS) and selected == image
        assert kwargs['overlay']['DIE_AREA'][0] == LC._def_die_area(Path(stream['filled_def']))
        cfg = json.loads((Path(stream['stream_state']).parent / 'config.json').read_text())
        paths = {step: BF.put(p / native.CONFIG / (step + '.json'), {
            **cfg, 'meta': {'step': step}}) for step in steps}
        for step, path in paths.items():
            inputs = ['mag_gds', 'klayout_gds'] if step == native.STEPS[-1] else ['odb', 'def', 'nl', 'sdc']
            BF.put(LC.views_path(path), {'step': step, 'inputs': inputs, 'outputs': []})
        return paths
    monkeypatch.setattr(LC, 'resolve_step_configs', configs)

    def neutral_conversion(project, selected, config, lines, folder, name, *args):
        assert name == 'def_to_odb' and selected == image
        for line in lines:
            if line.startswith('write_db {'):
                Path(line[len('write_db {'):-1]).write_text('SOURCE_CONTROL neutral database')
        recipe = folder / (name + '.tcl'); recipe.write_text('\n'.join(lines))
        return recipe
    monkeypatch.setattr(LC, '_openroad_convert', neutral_conversion)
    executed, commands, requests = [], [], []
    original_container = LC.run_container
    def observe_request(argv, **kwargs):
        requests.append(list(argv))
        return original_container(argv, **kwargs)
    monkeypatch.setattr(LC, 'run_container', observe_request)
    transcript = ('XOR_TOOL klayout\nXOR_TOP shipped=cal_pg reference=cal_pg\n'
        'XOR_CENSUS shipped_cells=20 shipped_shapes=1000 reference_cells=10 reference_shapes=10\n'
        'XOR_BOUNDARY_CENSUS cells=10 shapes=10\nXOR_LAYER 32/0 0\nXOR_LAYER 34/4 600\nXOR_DONE\n')
    def neutral_process(argv, **kwargs):
        commands.append(list(argv))
        if '/usr/bin/time' in argv:
            at = argv.index('/usr/bin/time')
            assert argv[at + 1:at + 5] == ['-v', shutil.which('klayout'), '-b', '-r']
            assert kwargs['env']['XOR_BOUNDARY'] == str(stream['stream'])
            return watchdog.SupervisedResult(0, transcript, '', 'natural')
        at = argv.index('-m')
        assert argv[at:at + 3] == ['-m', 'librelane.steps', 'run']
        argv = argv[at - 1:]  # retain the actual LC launcher in commands above
        step = argv[argv.index('--id') + 1]
        folder = Path(argv[argv.index('-o') + 1])
        state = json.loads(Path(argv[argv.index('-i') + 1]).read_text())
        if step in native.STEPS[:2]:
            role = 'mag_gds' if step == native.STEPS[0] else 'klayout_gds'
            path = folder / (role + ('.oas' if role == 'mag_gds' else '.gds'))
            _geometry(path); state[role] = str(path)
        else:
            state['metrics'] = {native.KEY: 0}
            (folder / 'xor.xml').write_text('<report-database><top-cell>cal_pg</top-cell>'
                f"<description>XOR {state['mag_gds']} vs. {state['klayout_gds']}</description>"
                '<items></items></report-database>')
        BF.put(folder / 'state_in.json', json.loads(Path(argv[argv.index('-i') + 1]).read_text()))
        BF.put(folder / 'state_out.json', state)
        BF.put(folder / 'config.json', json.loads(Path(argv[argv.index('-c') + 1]).read_text()))
        executed.append(step)
        return watchdog.SupervisedResult(0, 'SOURCE_CONTROL native ' + step, '', 'natural')
    monkeypatch.setattr(watchdog, 'run_host_supervised', neutral_process)
    result = EBP.produce_signoff(p, {'step_id': '37.3', 'execution_mode': 'default',
        'top': 'cal_pg', 'pdk_root': str(root), 'image_id': str(image)})
    emitted = json.loads((p / xor.REPORT_REL).read_text())
    BF.put(tmp_path / 'TYPED_LOCAL373_PRODUCER_READBACK.json', {
        'result': result, 'executed': executed, 'requests': requests,
        'native_dependency_refusal': emitted.get('native_dependency_refusal'),
        'connectivity': emitted.get('connectivity')})
    assert executed == list(native.STEPS)
    assert result['verdict'] == 'PASS', result
    assert not emitted.get('native_dependency_refusal'), emitted.get('native_dependency_refusal')
    dependency = native.read_current(p)
    assert dependency['current']['execution']['local_provider'] == image.as_record()
    assert 'local_image' not in dependency['current']['execution']
    receipts = {rel: (p / rel / 'vibeic_receipt.json').read_bytes() for rel in dependency['folders']}
    assert all(json.loads(data)['input']['local_provider'] == image.as_record() for data in receipts.values())
    rc, line, report = xor.judge_receipt(p, xor.REPORT_REL)
    assert rc == 0 and report['connectivity']['verdict'] == 'PASS', line
    assert report['runner'] == {'kind': 'host', 'detail': shutil.which('klayout') + ' -b -r'}
    assert report['current']['execution']['argv'] == commands[-1]
    assert commands[-1][0] == image.executable and '/usr/bin/time' in commands[-1]
    assert requests[-1][requests[-1].index('--network') + 1] == 'host'
    assert '--cpus' not in requests[-1]
    assert not (p / 'phase3/librelane/37.3-launches.jsonl').exists()
    assert (p / 'input/submission_template/tapeout_declaration.json').read_bytes() == original_declaration
    assert all((p / rel / 'vibeic_receipt.json').read_bytes() == data for rel, data in receipts.items())
    assert calls == ['primary', 'seal', 'filler-density']
    (root / 'neutral/stream.lef').write_text('changed native material\n')
    with pytest.raises((LC.Refusal, ValueError)):
        native.read_current(p)
    assert xor.judge_receipt(p, xor.REPORT_REL)[0] == 2
    assert executed == list(native.STEPS)
    BF.put(tmp_path / 'TYPED_LOCAL373_OBSERVATION.json', {
        'result': result['verdict'], 'current_consumer_rc': rc,
        'executed': executed, 'requests': requests, 'actual_commands': commands,
        'execution': dependency['current']['execution'],
        'geometry_execution': report['current']['execution'],
        'receipts_unchanged': True, 'changed_material_refused': True,
        'scope': 'source/neutral native transport only; no physical or whole IC PASS'})
