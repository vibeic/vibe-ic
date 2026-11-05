"""Current ordinary Default source controls. Substituted processes are SOURCE_FIXTURE_ONLY."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_librelane_contract import local_image  # noqa: F401
import _default_backend_fixtures as BF
import librelane_contract as LC
import librelane_postroute as LP
import spice_correlation_check as SC
import path_spice_tool as PST

SPEF = '''*SPEF "IEEE 1481-1998"
*DESIGN "neutral"
*T_UNIT 1 NS
*C_UNIT 1 PF
*R_UNIT 1 OHM
*L_UNIT 1 HENRY
*DIVIDER /
*DELIMITER :
*BUS_DELIMITER [ ]
*D_NET a 0.02
*CONN
*I u0:Z O
*I u2:A I
*CAP
1 u0:Z 0.01
2 u0:Z u1:Z 0.01
*RES
1 u0:Z u2:A 10
*END
*D_NET b 0.02
*CONN
*I u1:Z O
*P z O
*CAP
1 u1:Z 0.01
2 u1:Z u0:Z 0.01
*RES
1 u1:Z z 10
*END
'''
NETLIST = 'module neutral(input x, y, output z); wire a,b; BUF u0(.A(x),.Z(a)); BUF u1(.A(y),.Z(b)); BUF u2(.A(a),.Z(z)); endmodule\n'
POWER = '''OpenSTA report_power
Group                    Internal    Switching      Leakage        Total
                            Power        Power        Power        Power (Watts)
------------------------------------------------------------------------
Sequential           0.000000e+00 0.000000e+00 0.000000e+00 0.000000e+00   0.0%
Combinational        1.000000e-03 1.000000e-03 1.000000e-06 2.001000e-03 100.0%
Clock                0.000000e+00 0.000000e+00 0.000000e+00 0.000000e+00   0.0%
Macro                0.000000e+00 0.000000e+00 0.000000e+00 0.000000e+00   0.0%
Pad                  0.000000e+00 0.000000e+00 0.000000e+00 0.000000e+00   0.0%
------------------------------------------------------------------------
Total                1.000000e-03 1.000000e-03 1.000000e-06 2.001000e-03 100.0%
'''


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return path

def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path

def seal(folder, fp):
    put(folder / 'input_fingerprint.json', fp)
    put(folder / 'vibeic_receipt.json', {'input': fp, 'sha256': {
        str(p.relative_to(folder)): LC.digest(p) for p in folder.rglob('*')
        if p.is_file() and p.name != 'vibeic_receipt.json'}})

def project(tmp_path, *, corner='nom_typ', liberty_name='neutral.lib'):
    p = tmp_path / 'p'
    nl = write(p / 'phase3/stage3/pnr/neutral_pnr.v', NETLIST)
    spef = write(p / 'phase3/stage3/extracted/neutral.spef', SPEF)
    sdc = write(nl.parent / 'constraint.sdc', 'create_clock -name c -period 10\nset_input_delay 1 -clock c [get_ports {x y}]\nset_output_delay 1 -clock c [get_ports z]\n')
    views = {'nl': str(nl), 'sdc': str(sdc), 'spef': {'*': str(spef)},
             'metrics': {f'timing__setup__ws__corner:{corner}': 1.0}}
    folder, _ = BF.producer(p, 'OpenROAD.STAPostPNR', views, views,
                           lane='22-23/01-openroad-stapostpnr', config_folder='22-config', name='neutral')
    library = 'neutral_typ' if liberty_name == 'neutral.lib' else 'neutral_' + Path(liberty_name).stem
    lib = write(p / 'fixture_pdk/neutral' / liberty_name,
                f'library({library}) {{\n nom_voltage : 1.8;\n default_operating_conditions: typ;\n}}\n')
    guest = '/pdk/neutral/' + liberty_name
    write(folder / corner / 'sta.log', f"SOURCE_FIXTURE_ONLY\nReading cell library for the '{corner}' corner at '{guest}'\n")
    write(folder / corner / 'power.rpt', POWER)
    config = p / 'phase3/librelane/22-config/OpenROAD.STAPostPNR.json'
    raw = json.loads(config.read_text())
    raw['CELL_LIBS'] = {'*': [guest]}
    put(config, raw)
    put(folder / 'config.json', raw)
    fp = json.loads((folder / 'input_fingerprint.json').read_text())
    fp['config'] = LC.digest(config)
    fp['config_files'] = {guest: LC.digest(lib)}
    fp['liberty_files'] = {guest: LC.digest(lib)}
    seal(folder, fp)
    put(p / LP.STEP23_RECORD, {'sta_state': str(folder / 'state_out.json'),
                              'sta_state_sha256': LC.digest(folder / 'state_out.json'),
                              'judgment': {'worst_setup': {'corner': corner}}})
    return p, folder, lib




def test_step30_copied_correlation_cannot_certify_without_execution(tmp_path):
    p, folder, lib = project(tmp_path)
    write(p / 'phase3/stage3/spice/correlation.spice', '* copied deck\n.end\n')
    put(p / 'reports/phase3/spice_correlation.json', {'correlation': {
        'liberty_spef_cone_delay_ns': 1, 'spice_path_delay_ns': 1,
        'pct_error': 0, 'tolerance_pct': 10, 'verdict': 'CORRELATED'}})
    assert SC.main([str(p), '--no-spice', '--json', str(p / 'spice-gate.json')]) == 1

def spice_produce(p, folder, lib, monkeypatch, *, verdict='PASS'):
    write(p / 'fixture_pdk/neutral/libs.tech/ngspice/model.sp', '.model neutral nmos level=1\n')
    write(p / 'fixture_pdk/neutral/libs.tech/magic/neutral.magicrc', '# SOURCE_FIXTURE_ONLY Magic rules\n')
    write(p / 'fixture_pdk/neutral/libs.tech/librelane/config.tcl', '# SOURCE_FIXTURE_ONLY PDK declaration\n')
    def run(project, image, root, pdk_name, **kwargs):
        detail = {}
        for variant in ('base', 'mutated'):
            directory = p / 'phase3/tool_arms/30/ngspice' / variant
            script = write(directory / 'arm.tcl', 'read_spef current\nwrite_path_spice\n')
            sta_log = write(directory / 'sta.log', 'SOURCE_FIXTURE_ONLY OpenSTA write_path_spice\n')
            deck = write(directory / 'path_1.sp', '* SOURCE_FIXTURE_ONLY tool deck\n.end\n')
            runnable = write(directory / 'path_1.run.sp', '* SOURCE_FIXTURE_ONLY simulator deck\n.end\n')
            sim_log = write(directory / 'path_1.log', 'SOURCE_FIXTURE_ONLY measured 1 ns\n')
            for name in ('path_1.wave', 'path_1.rpt', 'path_1.run.subckt', 'models_ngspice.sp'):
                write(directory / name, 'SOURCE_FIXTURE_ONLY ' + name + '\n')
            detail[variant] = {'sta_execution': {'tool': 'OpenSTA', 'rc': 0,
                'argv': ['sta', '-exit', str(script)], 'script': str(script), 'log': str(sta_log)},
                'paths': [{'deck': str(deck), 'status': 'MEASURED', 'spice_ns': 1,
                    'simulator_execution': {'tool': 'ngspice', 'rc': 0,
                        'argv': ['ngspice', '-b', str(runnable)],
                        'script': str(runnable), 'log': str(sim_log)}}]}
        doc = {'step': '30', 'corner': 'nom_typ', 'verdict': verdict,
               'arms': {'ngspice': {'verdict': 'CORRELATED' if verdict == 'PASS' else 'MISMATCH'}},
               'detail': {'ngspice': detail}}
        put(p / 'reports/phase3/spice_path_tool.json', doc)
        return doc
    monkeypatch.setattr(PST, 'run_step30', run)
    monkeypatch.setattr(LC, 'resolve_image', lambda *a, **k: BF.IMAGE)
    monkeypatch.setattr(LC, 'pdk_root_resolution', lambda *a, **k: {'path': str(p / 'fixture_pdk')})
    return SC.run_installed_pdk_path_correlation(p, str(lib))

def test_step30_ordinary_caller_adopts_the_existing_tool_product(tmp_path, monkeypatch):
    p, folder, lib = project(tmp_path)
    result = spice_produce(p, folder, lib, monkeypatch)
    assert result['status'] == 'RAN', result
    assert SC.main([str(p), '--json', str(p / 'spice-gate.json')]) == 0
    assert (p / 'phase3/stage3/spice/correlation.spice').read_bytes() == (p / 'phase3/tool_arms/30/ngspice/base/path_1.sp').read_bytes()

@pytest.mark.parametrize('mutation', ['netlist', 'spef', 'sdc', 'liberty', 'corner', 'models',
    'execution', 'report_replay', 'wrong_project', 'wrong_stage', 'wrong_path', 'consumption',
    'declared_result', 'waveform', 'path_report', 'subckt', 'generated_models',
    'magicrc', 'pdk_flow_config', 'execution_identity'])
def test_step30_gate_refuses_current_byte_and_consumer_mutations(tmp_path, monkeypatch, mutation):
    p, folder, lib = project(tmp_path)
    assert spice_produce(p, folder, lib, monkeypatch)['status'] == 'RAN'
    assert SC.main([str(p), '--no-spice', '--json', str(p / 'spice-gate.json')]) == 0
    if mutation == 'declared_result':
        (p / 'phase3/stage3/spice/correlation.json').unlink()
    elif mutation in ('netlist', 'spef', 'sdc', 'liberty', 'models'):
        path = {'netlist': p / 'phase3/stage3/pnr/neutral_pnr.v',
                'spef': p / 'phase3/stage3/extracted/neutral.spef',
                'sdc': p / 'phase3/stage3/pnr/constraint.sdc', 'liberty': lib,
                'models': p / 'fixture_pdk/neutral/libs.tech/ngspice/model.sp'}[mutation]
        path.write_text(path.read_text() + '\n ')
    elif mutation == 'corner':
        path = folder / 'state_out.json'
        doc = json.loads(path.read_text())
        doc['metrics']['timing__setup__ws__corner:nom_typ'] = -1.0
        put(path, doc)
    elif mutation == 'execution':
        (p / 'phase3/tool_arms/30/ngspice/base/path_1.log').unlink()
    elif mutation == 'report_replay':
        path = p / 'reports/phase3/spice_path_tool.json'
        path.write_text(path.read_text() + '\n ')
    elif mutation in ('waveform', 'path_report', 'subckt', 'generated_models'):
        name = {'waveform': 'path_1.wave', 'path_report': 'path_1.rpt',
                'subckt': 'path_1.run.subckt', 'generated_models': 'models_ngspice.sp'}[mutation]
        path = p / 'phase3/tool_arms/30/ngspice/base' / name
        path.write_text(path.read_text() + '\n ')
    elif mutation in ('magicrc', 'pdk_flow_config'):
        relative = 'magic/neutral.magicrc' if mutation == 'magicrc' else 'librelane/config.tcl'
        path = p / 'fixture_pdk/neutral/libs.tech' / relative
        path.write_text(path.read_text() + '\n ')
    else:
        path = p / 'reports/phase3/spice_correlation.current.json'
        doc = json.loads(path.read_text())
        if mutation == 'wrong_project':
            doc['project'] = str(tmp_path / 'other')
        elif mutation == 'wrong_stage':
            doc['stage'] = 'pre_layout'
        elif mutation == 'wrong_path':
            doc['outputs'][0]['path'] = str(tmp_path / 'outside.sp')
        elif mutation == 'execution_identity':
            doc['execution'][0]['argv'][0] = 'foreign_tool'
        else:
            doc['outputs'] = []
        put(path, doc)
    assert SC.main([str(p), '--no-spice', '--json', str(p / 'spice-gate.json')]) == 1

def test_step30_current_measured_fail_is_still_fail(tmp_path, monkeypatch):
    p, folder, lib = project(tmp_path)
    result = spice_produce(p, folder, lib, monkeypatch, verdict='FAIL')
    assert result['status'] == 'RAN'
    assert SC.main([str(p), '--json', str(p / 'spice-gate.json')]) == 1
    assert json.loads((p / 'spice-gate.json').read_text())['summary']['measurement'] == 'MEASURED'













































def _explicit_step30_subject(tmp_path):
    """SOURCE_FIXTURE_ONLY native inputs with independent module and filenames."""
    p, folder, lib = project(tmp_path)
    old_paths = {'nl': p / 'phase3/stage3/pnr/neutral_pnr.v',
                 'sdc': p / 'phase3/stage3/pnr/constraint.sdc',
                 'spef': p / 'phase3/stage3/extracted/neutral.spef'}
    paths = {'nl': p / 'phase3/stage3/pnr/retained_route_bytes.v',
             'sdc': p / 'phase3/stage3/pnr/selected_scene.sdc',
             'spef': p / 'phase3/stage3/extracted/selected.max.spef'}
    for role, old in old_paths.items():
        text = old.read_text()
        if role in ('nl', 'spef'):
            text = text.replace('neutral', 'package_shell')
        write(paths[role], text)
        old.unlink()
    for name in ('state_in.json', 'state_out.json'):
        state = json.loads((folder / name).read_text())
        state.update(nl=str(paths['nl']), sdc=str(paths['sdc']), spef={'*': str(paths['spef'])})
        put(folder / name, state)
    config = p / 'phase3/librelane/22-config/OpenROAD.STAPostPNR.json'
    data = json.loads(config.read_text())
    data['DESIGN_NAME'] = 'package_shell'
    put(config, data)
    put(folder / 'config.json', data)
    fp = json.loads((folder / 'input_fingerprint.json').read_text())
    fp.update(config=LC.digest(config), state_files={str(path): LC.digest(path) for path in paths.values()})
    # run_chain may declare the whole PDK root, not only one process subtree.
    put(folder / 'pdk_root.json', {'cli_pdk_root': '/pdk',
        'stated_by': 'run_chain(pdk_root=...)',
        'mounts_under_it': [[str(p / 'fixture_pdk'), '/pdk']]})
    seal(folder, fp)
    record = json.loads((p / LP.STEP23_RECORD).read_text())
    record['sta_state_sha256'] = LC.digest(folder / 'state_out.json')
    put(p / LP.STEP23_RECORD, record)
    return p, folder, lib, paths






def _step30_image_interop_subject(tmp_path, monkeypatch):
    """Real retained/current readers; only tool processes are SOFTWARE_FIXTURE."""
    import test_step30_r4_current_failures as current_fixture
    p, folder, lib, paths = _explicit_step30_subject(tmp_path)
    current_fixture.correlation_tool(p, folder, lib, monkeypatch,
                                     mismatch='CORRELATED', companion='success')
    root = p / 'fixture_pdk'
    gds = write(root / 'neutral/cells.gds', 'SOFTWARE_FIXTURE_ONLY layout bytes\n')
    model = write(root / 'neutral/cells.spice', '.subckt BUF A Z\nR1 A Z 1\n.ends\n')
    config_path = p / 'phase3/librelane/22-config/OpenROAD.STAPostPNR.json'
    config = json.loads(config_path.read_text())
    config.update(CELL_GDS=['/pdk/neutral/cells.gds'],
                  CELL_SPICE_MODELS=['/pdk/neutral/cells.spice'])
    put(config_path, config)
    put(folder / 'config.json', config)
    fp = json.loads((folder / 'input_fingerprint.json').read_text())
    fp['config'] = LC.digest(config_path)
    fp['config_files'].update({'/pdk/neutral/cells.gds': LC.digest(gds),
                             '/pdk/neutral/cells.spice': LC.digest(model)})
    seal(folder, fp)
    switch_path = p / 'phase3/librelane_switch.json'
    switch = json.loads(switch_path.read_text())
    switch.pop('image')
    put(switch_path, switch)
    put(p / 'phase3/librelane_pdk_root.provenance.json', {
        'source': 'resolved', 'path': str(root),
        'derivation': {'image': BF.IMAGE, 'pdk': 'neutral',
                       'host_path': str(root / 'neutral')}})
    return p, folder, lib, paths, gds, model


@pytest.mark.parametrize('consumer', ['same', 'updated'])
def test_step30_binds_native_inputs_with_current_consumer_image(tmp_path, monkeypatch, consumer):
    p, folder, lib, paths, gds, model = _step30_image_interop_subject(tmp_path, monkeypatch)
    image = BF.IMAGE if consumer == 'same' else 'ghcr.io/vibeic/vibeic-eda@sha256:' + 'b' * 64
    monkeypatch.setenv('VIBEIC_LIBRELANE_IMAGE', image)
    original_receipt = (folder / 'vibeic_receipt.json').read_bytes()
    doc = PST.run_current_step30(p, image, p / 'fixture_pdk', 'neutral')
    receipt = json.loads((p / 'reports/phase3/spice_correlation.current.json').read_text())
    assert doc['verdict'] == 'PASS'
    assert doc['current_subject']['inputs'] == receipt['inputs']
    assert 'tool_image' not in receipt
    assert receipt['context']['image'] == image
    assert (folder / 'vibeic_receipt.json').read_bytes() == original_receipt
    gate = SC.run_audit(p, run_spice=False)
    assert gate.summary['current_binding'] == 'CURRENT'
    assert gate.summary['measurement'] == 'MEASURED'
    assert gate.passed and gate.summary['verdict'] == 'PASS'


@pytest.mark.parametrize('damage', ['config_pdk', 'netlist', 'sdc', 'liberty',
                                    'cell_gds', 'model', 'pdk_root'])
def test_step30_consumer_update_preserves_producer_and_material_refusals(tmp_path, monkeypatch, damage):
    p, folder, lib, paths, gds, model = _step30_image_interop_subject(tmp_path, monkeypatch)
    monkeypatch.setenv('VIBEIC_LIBRELANE_IMAGE', BF.IMAGE)
    assert PST.run_current_step30(p, BF.IMAGE, p / 'fixture_pdk', 'neutral')['verdict'] == 'PASS'
    root = p / 'fixture_pdk'
    if damage == 'config_pdk':
        config = json.loads((folder / 'config.json').read_text())
        config['PDK'] = 'other'
        put(folder / 'config.json', config)
    elif damage == 'pdk_root':
        root = p / 'other_root'
        root.mkdir()
    else:
        path = {'netlist': paths['nl'], 'sdc': paths['sdc'], 'liberty': lib,
                'cell_gds': gds, 'model': model}[damage]
        path.write_bytes(path.read_bytes() + b'\n ')
    with pytest.raises((LC.Refusal, ValueError, OSError)):
        if damage == 'pdk_root':
            PST.current_context(p, BF.IMAGE, root, 'neutral')
        else:
            PST.validate_current_step30(p)



def test_step30_native_local_process_uses_its_declared_workdir(tmp_path, local_image):
    # A real LOCAL child runs inside the attested test image. This neutral
    # process control measures the native transport, not an IC or SPICE result.
    p = tmp_path / 'project'
    work = p / 'phase3/tool_arms/30/ngspice/base'
    work.mkdir(parents=True)
    program = ("import json,os; from pathlib import Path; "
               "Path('process.json').write_text(json.dumps({'cwd':os.getcwd(), "
               "'scope':'SOURCE_FIXTURE_ONLY'})); print('LOCAL_PROCESS_DONE')")
    result = PST._docker(local_image.image, p, [],
                         ['python3', '-c', program], work)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert 'LOCAL_PROCESS_DONE' in result.stdout
    assert json.loads((work / 'process.json').read_text()) == {
        'cwd': str(work), 'scope': 'SOURCE_FIXTURE_ONLY'}
    assert result._vibeic_lifecycle['rc'] == 0



@pytest.mark.parametrize('route', ['LOCAL', 'DOCKER'])
def test_step30_model_publication_matches_the_selected_execution_namespace(tmp_path, monkeypatch, route):
    p, folder, lib = project(tmp_path)
    root = p / 'fixture_pdk'
    nl = p / 'phase3/stage3/pnr/neutral_pnr.v'
    nl.write_text(nl.read_text().replace('BUF ', '\nBUF '))
    tech = root / 'neutral/libs.tech/ngspice'
    write(tech / 'design.ngspice', '.param neutral_scale=1\n')
    write(tech / 'models.ngspice', '.lib typ\n.model neutral nmos level=1\n.endl typ\n')
    write(root / 'neutral/cells.spice', '.subckt BUF A Z VDD VSS\nM0 Z A VSS VSS neutral W=1u L=1u\n.ends\n')
    write(lib, 'library(neutral_typ) {\n voltage_map(VDD, 1.8);\n voltage_map(VSS, 0);\n operating_conditions(typ) { voltage: 1.8; }\n}\n')
    gds = write(root / 'neutral/cells.gds', 'SOURCE_FIXTURE_ONLY original declared cell geometry\n')
    magicrc = write(root / 'neutral/libs.tech/magic/neutral.magicrc',
                    'SOURCE_FIXTURE_ONLY technology uses PDK_ROOT/neutral/libs.tech/magic/neutral.tech\n')
    technology = write(magicrc.with_suffix('.tech'), 'SOURCE_FIXTURE_ONLY unchanged technology\n')
    write(root / 'neutral/libs.tech/librelane/config.tcl',
          'set ::env(MAGICRC) "$::env(PDK_ROOT)/$::env(PDK)/libs.tech/magic/neutral.magicrc"\n')
    config = json.loads((folder / 'config.json').read_text())
    config.update(VDD_PIN='VDD', GND_PIN='VSS', CELL_SPICE_MODELS=['/pdk/neutral/cells.spice'],
                  CELL_GDS=[str(gds)])
    put(folder / 'config.json', config)
    original = p / 'phase3/librelane/22-config/OpenROAD.STAPostPNR.json'
    put(original, config)
    fp = json.loads((folder / 'input_fingerprint.json').read_text())
    fp.update(config=LC.digest(original), config_files=LC.config_file_hashes(config, [(root / 'neutral', '/pdk/neutral')]),
              liberty_files={'/pdk/neutral/neutral.lib': LC.digest(lib)})
    fp['state_files'][str(nl)] = LC.digest(nl)
    seal(folder, fp)
    # Only the tool process is substituted; the real normal prepare_arm and
    # model-section reader/publication execute in the selected namespace.
    monkeypatch.setattr(LC, '_provider_for_image', lambda *_: None)
    monkeypatch.setattr(LC, '_provider_route', lambda *_: route == 'LOCAL')
    calls, magic_calls = [], []
    def sta(image, project, mounts, argv, cwd, **kwargs):
        if argv[0] == 'magic':
            import _container_exec as ce
            translations = [(guest, str(host)) for host, guest in mounts]
            declared_root = kwargs['env']['PDK_ROOT']
            # LOCAL rewrites env values, not paths assembled inside the rcfile.
            # Docker has the declared guest view; emulate only its file lookup.
            loaded_root = ce.localise_mounted_paths(declared_root, translations) if route == 'LOCAL' else declared_root
            tech_path = str(Path(loaded_root) / 'neutral/libs.tech/magic/neutral.tech')
            if route == 'DOCKER':
                tech_path = ce.localise_mounted_paths(tech_path, translations)
            magic_calls.append({'argv': argv, 'env': kwargs['env'], 'tech': tech_path})
            if not Path(tech_path).is_file():
                return SimpleNamespace(returncode=1,
                    stdout=f'SOURCE_FIXTURE_ONLY: Could not find file {tech_path}\n', stderr='')
            assert Path(tech_path).read_bytes() == technology.read_bytes()
            assert f'gds read {gds}\n' in Path(argv[-1]).read_text()
            # This neutral process substitution emits only a source fixture;
            # production extract_cells must read this invocation's export.
            write(Path(cwd) / 'BUF.spice', '* SOURCE_FIXTURE_ONLY current export\n'
                  + (root / 'neutral/cells.spice').read_text())
            return SimpleNamespace(returncode=0, stdout='SOURCE_FIXTURE_ONLY extraction\n', stderr='')
        assert argv[0] == 'sta'
        calls.append(argv)
        return SimpleNamespace(returncode=0,
            stdout='VIBEIC_STA_DERATE set_timing_derate -late 1.0\nSOURCE_FIXTURE_ONLY STA transport\n', stderr='')
    monkeypatch.setattr(PST, '_docker', sta)
    arm = PST.prepare_arm(p, BF.IMAGE, folder / 'state_out.json', 'nom_typ',
                          pdk_root=root, pdk='neutral', out_dir=p / 'tool-fixture', paths=1)
    assert len(calls) == 1 and arm['prepared'] == []
    text = Path(arm['models']['path']).read_text()
    expected = str(tech) if route == 'LOCAL' else '/pdk/neutral/libs.tech/ngspice'
    assert f'.include {expected}/design.ngspice' in text
    assert f'.lib {expected}/models.ngspice typ' in text
    assert arm['models']['devices'] == ['neutral']
    if route == 'LOCAL':
        assert '/pdk/' not in text
        for line in text.splitlines():
            if line.startswith(('.include ', '.lib ')):
                assert Path(line.split()[1]).is_file()

    expected_root = str(root) if route == 'LOCAL' else '/pdk'
    assert len(magic_calls) == 1
    assert magic_calls[0]['env']['PDK_ROOT'] == expected_root
    assert magic_calls[0]['argv'][4] == expected_root + '/neutral/libs.tech/magic/neutral.magicrc'
    assert arm['cells']['cell_view']['extracted'] == ['BUF']
    assert arm['cells']['cell_view']['missing_exports'] == []
