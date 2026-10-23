"""Reviewed Step33 controls only. All fixtures are SOURCE_FIXTURE_ONLY."""
import json
import re
from pathlib import Path
from types import SimpleNamespace
import pytest
import _plugin_tree  # noqa: F401
from _hostpaths import require_repo
import _default_backend_fixtures as BF
import librelane_contract as LC
import librelane_postroute as LP
import phase3_one_shot_runner as R
import power_report_check as PG
from _ppa import power
try:
    import _opensta_current as C
except ModuleNotFoundError:
    C = None  # Frozen-base public-caller value control still collects.


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


def project(tmp_path, *, voltage=1.8):
    p = tmp_path / 'p'
    nl = write(p / 'phase3/stage3/pnr/neutral_pnr.v', NETLIST)
    spef = write(p / 'phase3/stage3/extracted/neutral.spef', SPEF)
    sdc = write(nl.parent / 'constraint.sdc', 'create_clock -name c -period 10\nset_input_delay 1 -clock c [get_ports {x y}]\nset_output_delay 1 -clock c [get_ports z]\n')
    views = {'nl': str(nl), 'sdc': str(sdc), 'spef': {'*': str(spef)}, 'metrics': {}}
    folder, _ = BF.producer(p, 'OpenROAD.STAPostPNR', views, views,
                           lane='22-23/01-openroad-stapostpnr', config_folder='22-config', name='neutral')
    lib = write(p / 'fixture_pdk/neutral/neutral.lib', 'library(neutral_typ) {\n' + (f' nom_voltage : {voltage};\n' if voltage is not None else '') + ' default_operating_conditions: typ;\n}\n')
    corner = 'nom_typ'
    guest = '/pdk/neutral/neutral.lib'
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


def pdk(lib):
    return SimpleNamespace(name='neutral', liberty=str(lib), macro_libs=[], macro_lefs=[],
                           tech_lef='', cell_lef='')


def original_transport(tmp_path, monkeypatch, p, folder):
    """Neutral retained Default owner for the exact external readset seam."""
    import _physical_current as physical
    import librelane_fill_dfm as fill

    owner = tmp_path / 'original-owner'
    native = owner / 'phase3/librelane/34/01-openroad-fillinsertion'
    odb = write(native / 'neutral.odb', 'neutral immutable ODB\n')
    routed_def = write(native / 'neutral.def', 'VERSION 5.8 ;\nDESIGN neutral ;\nEND DESIGN\n')
    netlist = write(native / 'neutral.nl.v', NETLIST)
    sdc = write(native / 'neutral.sdc',
                'create_clock -name c -period 10 [get_ports x]\n')
    fill_state = put(native / 'state_out.json', {
        'odb': str(odb), 'def': str(routed_def)})
    fill_receipt = put(native / 'vibeic_receipt.json', {'source_control_only': True})
    fill_record = put(owner / fill.RECORD_REL, {'odb': {'tool': {
        'state': str(fill_state), 'state_sha256': LC.digest(fill_state),
        'filled_def_sha256': LC.digest(routed_def)}}})
    image = json.loads((folder / 'vibeic_receipt.json').read_text())['input']['image']
    real_validate = LC.validate_step_receipt

    def validate_step(where, step):
        if Path(where).resolve() == native.resolve():
            assert step == fill.ODB_FILL_STEP
            return {'input': {}, 'sha256': {}}
        return real_validate(where, step)

    monkeypatch.setattr(LC, 'validate_step_receipt', validate_step)
    monkeypatch.setattr(fill, 'validate_default_stream', lambda root: {
        'image': image, 'canonical': str(owner / 'neutral.gds')}
        if Path(root).resolve() == owner.resolve()
        else pytest.fail('unrelated original owner selected'))
    monkeypatch.setattr(physical, 'default_signoff_inputs', lambda root: {
        'netlist': netlist, 'sdc': sdc, 'def': routed_def,
        'gds': owner / 'neutral.gds'}
        if Path(root).resolve() == owner.resolve()
        else pytest.fail('unrelated original signoff owner selected'))
    return {'owner': owner, 'odb': odb, 'def': routed_def, 'netlist': netlist,
            'sdc': sdc, 'record': fill_record, 'receipt': fill_receipt,
            'image': image}


def bind_original_transport(p, folder, original):
    state_path = folder / 'state_out.json'
    state = json.loads(state_path.read_text())
    state.update({'odb': str(original['odb']), 'def': str(original['def']),
                  'nl': str(original['netlist']), 'sdc': str(original['sdc'])})
    put(state_path, state)
    fp = json.loads((folder / 'input_fingerprint.json').read_text())
    fp['state_files'] = {str(path): LC.digest(path) for path in (
        original['odb'], original['def'], original['netlist'], original['sdc'],
        p / 'phase3/stage3/extracted/neutral.spef')}
    seal(folder, fp)
    marker = p / LP.STEP23_RECORD
    doc = json.loads(marker.read_text())
    doc['sta_state_sha256'] = LC.digest(state_path)
    put(marker, doc)
    return fp


def corner_power(index):
    internal = (index + 1) * 1e-3
    switching, leakage = 1e-3, 1e-6
    total = internal + switching + leakage
    row = (f'{internal:.9e} {switching:.9e} {leakage:.9e} '
           f'{total:.9e} 100.0%')
    zero = '0.000000000e+00 0.000000000e+00 0.000000000e+00 0.000000000e+00 0.0%'
    return ('OpenSTA report_power\n'
            'Group                    Internal    Switching      Leakage        Total\n'
            '                            Power        Power        Power        Power (Watts)\n'
            '------------------------------------------------------------------------\n'
            f'Sequential           {zero}\n'
            f'Combinational        {row}\n'
            f'Clock                {zero}\n'
            f'Macro                {zero}\n'
            f'Pad                  {zero}\n'
            '------------------------------------------------------------------------\n'
            f'Total                {row}\n')


def nine_corner_transport(tmp_path, monkeypatch):
    """Nine distinct executed mappings over one retained original owner."""
    p, folder, _ = project(tmp_path)
    original = original_transport(tmp_path, monkeypatch, p, folder)
    bind_original_transport(p, folder, original)
    (folder / 'nom_typ/sta.log').unlink()
    (folder / 'nom_typ/power.rpt').unlink()
    corners = [f'corner_{index}' for index in range(9)]
    state_path = folder / 'state_out.json'
    state = json.loads(state_path.read_text())
    config_path = p / 'phase3/librelane/22-config/OpenROAD.STAPostPNR.json'
    config = json.loads(config_path.read_text())
    state['spef'], config['CELL_LIBS'] = {}, {}
    libraries = {}
    for index, corner in enumerate(corners):
        spef = write(p / f'phase3/stage3/extracted/{corner}.spef',
                     SPEF + f'\n*COMMENT {corner}\n')
        state['spef'][corner] = str(spef)
        guest = f'/pdk/neutral/{corner}.lib'
        library = write(p / f'fixture_pdk/neutral/{corner}.lib',
                        f'library({corner}) {{ default_operating_conditions: typ; }}\n')
        config['CELL_LIBS'][corner] = [guest]
        libraries[guest] = LC.digest(library)
        write(folder / corner / 'sta.log',
              f"Reading cell library for the '{corner}' corner at '{guest}'\n")
        write(folder / corner / 'power.rpt', corner_power(index))
    put(state_path, state)
    put(config_path, config)
    put(folder / 'config.json', config)
    fp = json.loads((folder / 'input_fingerprint.json').read_text())
    fp['config'] = LC.digest(config_path)
    fp['config_files'] = dict(libraries)
    fp['liberty_files'] = dict(libraries)
    fp['state_files'] = {str(path): LC.digest(path) for path in (
        original['odb'], original['def'], original['netlist'], original['sdc'],
        *(p / f'phase3/stage3/extracted/{corner}.spef' for corner in corners))}
    seal(folder, fp)
    marker = p / LP.STEP23_RECORD
    record = json.loads(marker.read_text())
    record['sta_state_sha256'] = LC.digest(state_path)
    record['judgment']['worst_setup']['corner'] = corners[0]
    put(marker, record)
    return p, folder, original, corners


def produce(p, folder, lib, monkeypatch, step):
    assert step == '33'
    monkeypatch.setattr(R, '_docker_exec', lambda *a, **k: pytest.fail('parallel power producer ran'))
    return R._emit_power_report(p, 'neutral', pdk(lib), '', p / 'reports/phase3/power.rpt', [], basis='post_pnr')


def gate(p, step):
    assert step == '33'
    return PG.run([str(p), '--json', str(p / 'power-gate.json')])


def test_current_tool_mounts_fit_native_transport(tmp_path):
    p, _, _ = project(tmp_path)
    _, tool = C.tool_subject(p, 'neutral')
    assert tool['mounts']
    assert all(isinstance(host, Path) and host.is_dir() and guest.startswith('/pdk/')
               for host, guest in tool['mounts'])


def test_current_power_adopts_validated_original_owner_transport(tmp_path, monkeypatch):
    p, folder, lib = project(tmp_path)
    original = original_transport(tmp_path, monkeypatch, p, folder)
    bind_original_transport(p, folder, original)
    assert produce(p, folder, lib, monkeypatch, '33') is True
    assert gate(p, '33') == 0
    receipt = json.loads((p / 'reports/phase3/power.current.json').read_text())
    transport = receipt['input_transport']
    assert transport['kind'] == 'validated_default_fill_original'
    assert transport['source_project'] == str(original['owner'].resolve())
    assert set(transport['roles']) == {'netlist', 'sdc'}
    assert transport['source_record']['sha256'] == LC.digest(original['record'])
    original['netlist'].write_text(original['netlist'].read_text() + '\nchanged\n')
    assert gate(p, '33') == 1


def test_nine_corner_adoption_reuses_common_owner_and_validates_every_mapping(
        tmp_path, monkeypatch):
    p, folder, _, corners = nine_corner_transport(tmp_path, monkeypatch)
    common_calls, corner_calls = [], []
    real_common = C._validated_original_state_transport
    real_corner = C._tool_subject_from_common

    def observe_common(*args, **kwargs):
        common_calls.append(tuple(args))
        return real_common(*args, **kwargs)

    def observe_corner(common, **kwargs):
        corner_calls.append(kwargs.get('corner'))
        return real_corner(common, **kwargs)

    monkeypatch.setattr(C, '_validated_original_state_transport', observe_common)
    monkeypatch.setattr(C, '_tool_subject_from_common', observe_corner)
    notes = []
    report = p / 'reports/phase3/power.rpt'
    assert power.adopt_current_power_report(p, 'neutral', report, notes) is True
    values = power.stapostpnr_corner_power(folder)
    assert list(values) == corners
    assert len({row['total_w'] for row in values.values()}) == 9
    # One batch admission plus the existing receipt and signoff publication
    # consumers: bounded independently of the number of corners.
    assert len(common_calls) == 3
    assert corner_calls[:9] == corners
    assert corner_calls[9:] == [corners[-1], corners[-1]]
    assert json.loads(report.with_suffix('.current.json').read_text())['tool_corner'] == corners[-1]


def test_nine_corner_publication_revalidates_late_owner_change(tmp_path, monkeypatch):
    p, _, original, _ = nine_corner_transport(tmp_path, monkeypatch)
    real_binding = C.power_binding
    changed = False
    refusals = []

    def change_before_publication(project):
        nonlocal changed
        if not changed:
            original['netlist'].write_text(original['netlist'].read_text() + '\nlate change\n')
            changed = True
        try:
            return real_binding(project)
        except (OSError, ValueError, KeyError, TypeError, LC.Refusal) as exc:
            refusals.append(str(exc))
            raise

    monkeypatch.setattr(C, 'power_binding', change_before_publication)
    report = p / 'reports/phase3/power.rpt'
    notes = []
    assert power.adopt_current_power_report(p, 'neutral', report, notes) is False
    assert changed and not report.exists() and not report.with_suffix('.current.json').exists()
    assert any('LL_INPUT_CHANGED' in refusal for refusal in refusals), (refusals, notes)


def test_original_transport_refuses_unrelated_or_changed_outside_input(tmp_path, monkeypatch):
    p, folder, _ = project(tmp_path)
    original = original_transport(tmp_path, monkeypatch, p, folder)
    fp = bind_original_transport(p, folder, original)
    accepted = C._validated_original_state_transport(p, fp['state_files'], original['image'])
    assert accepted['source_project'] == str(original['owner'].resolve())
    with pytest.raises(C.Refusal, match='CURRENT_STAPOSTPNR_ORIGINAL_OWNER_INVALID'):
        C._validated_original_state_transport(p, fp['state_files'], 'changed-image')
    unrelated = write(tmp_path / 'unrelated/outside.sdc', 'create_clock\n')
    with pytest.raises(C.Refusal, match='CURRENT_STAPOSTPNR_FOREIGN_INPUT'):
        C._validated_original_state_transport(
            p, {**fp['state_files'], str(unrelated): LC.digest(unrelated)}, original['image'])
    original['odb'].write_text('changed original ODB\n')
    with pytest.raises(C.Refusal, match='CURRENT_STAPOSTPNR_ORIGINAL_INPUT_CHANGED'):
        C._validated_original_state_transport(p, fp['state_files'], original['image'])


@pytest.mark.parametrize('step', ['33'])
def test_ordinary_default_adopts_one_current_tool_subject(tmp_path, monkeypatch, step):
    p, folder, lib = project(tmp_path)
    assert produce(p, folder, lib, monkeypatch, step) is True
    assert gate(p, step) == 0
    if step == '33':
        data = json.loads((p / 'reports/phase3/power.json').read_text())
        assert data['total_power_w'] == pytest.approx(0.002001)
        assert (folder / 'nom_typ/power.rpt').read_text() in (p / 'reports/phase3/power.rpt').read_text()
    else:
        assert json.loads((p / 'reports/phase3/si_crosstalk.json').read_text())['verdict'] == 'ADVISORY_SCREEN_ONLY'


@pytest.mark.parametrize('step', ['33'])
@pytest.mark.parametrize('mutation', ['netlist', 'spef', 'sdc', 'liberty', 'corner', 'execution',
    'wrong_stage', 'wrong_project', 'wrong_path', 'report_replay', 'source_same_scalar', 'consumption'])
def test_current_gate_refuses_material_or_consumption_mutation(tmp_path, monkeypatch, step, mutation):
    p, folder, lib = project(tmp_path)
    assert produce(p, folder, lib, monkeypatch, step) is True
    assert gate(p, step) == 0
    if mutation in ('netlist', 'spef', 'sdc', 'liberty'):
        path = {'netlist': p / 'phase3/stage3/pnr/neutral_pnr.v',
                'spef': p / 'phase3/stage3/extracted/neutral.spef',
                'sdc': p / 'phase3/stage3/pnr/constraint.sdc', 'liberty': lib}[mutation]
        path.write_text(path.read_text() + '\n# substituted material\n')
    elif mutation == 'corner':
        path = p / LP.STEP23_RECORD
        doc = json.loads(path.read_text())
        doc['judgment']['worst_setup']['corner'] = 'different_corner'
        put(path, doc)
    elif mutation == 'execution':
        (folder / 'invocation.log').unlink()
    elif mutation == 'source_same_scalar':
        path = folder / 'nom_typ/power.rpt' if step == '33' else p / 'phase3/stage3/extracted/neutral_si_timing.json'
        path.write_text(path.read_text() + '\n ')
    else:
        name = 'power' if step == '33' else 'si_crosstalk'
        receipt = p / f'reports/phase3/{name}.current.json'
        doc = json.loads(receipt.read_text())
        if mutation == 'wrong_stage':
            doc['stage'] = 'pre_layout'
        elif mutation == 'wrong_project':
            doc['project'] = str(tmp_path / 'other')
        elif mutation == 'wrong_path':
            doc['outputs'][0]['path'] = str(tmp_path / 'other.rpt')
        elif mutation == 'consumption':
            doc['outputs'] = []
        else:
            target = p / f'reports/phase3/{name}.rpt'
            target.write_text(target.read_text() + '\n# replay from a different run\n')
        put(receipt, doc)
    assert gate(p, step) == 1


@pytest.mark.parametrize('step', ['33'])
def test_missing_current_tool_refuses_even_with_copied_green_report(tmp_path, monkeypatch, step):
    p, folder, lib = project(tmp_path)
    write(p / 'reports/phase3/power.rpt', POWER * 6)
    write(p / 'phase3/stage3/pnr/sta.rpt', 'slack (MET) 3\n')
    (folder / 'invocation.log').unlink()
    assert produce(p, folder, lib, monkeypatch, step) is False
    assert gate(p, step) == 1


def test_power_audit_error_cannot_be_outvoted_by_current_numbers(tmp_path, monkeypatch):
    import eda_report_audit as audit
    p, folder, lib = project(tmp_path)
    assert produce(p, folder, lib, monkeypatch, '33')
    assert gate(p, '33') == 0
    real = audit._check_tool_authenticity
    def signature_error(files, mode, result):
        authentic = real(files, mode, result)
        result.findings.append(audit.Finding(rule='POWER_NO_TOOL_SIGNATURE',
            severity='ERROR', message='Reverse control: authenticated scalar cannot outvote an error'))
        return authentic
    monkeypatch.setattr(audit, '_check_tool_authenticity', signature_error)
    assert gate(p, '33') == 1
    doc = json.loads((p / 'power-gate.json').read_text())
    assert doc['passed'] is False
    assert any(f['severity'] == 'ERROR' for f in doc['findings'])


def test_native_shaped_short_power_source_is_checked_by_receipt(tmp_path, monkeypatch):
    p, folder, lib = project(tmp_path)
    source = folder / 'nom_typ/power.rpt'
    source.write_text(POWER.replace('# OpenSTA report_power', '# report_power'))
    assert source.stat().st_size < 2048
    seal(folder, json.loads((folder / 'input_fingerprint.json').read_text()))
    assert produce(p, folder, lib, monkeypatch, '33')
    assert gate(p, '33') == 0
    doc = json.loads((p / 'power-gate.json').read_text())
    assert doc['summary']['design_binding'] is True
    assert doc['summary']['current_binding'] == 'CURRENT'
    assert not any(f['severity'] == 'ERROR' for f in doc['findings'])
    source.write_text(source.read_text() + '\n ')
    assert gate(p, '33') == 1


def test_real_declared_row_gate_consumes_the_current_report(tmp_path, monkeypatch):
    import yaml
    import flow_compliance_check as FC
    flow = yaml.safe_load(require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic',
        'flow', 'phase1_phase2_phase3.yaml').read_text())
    row = next(row for row in flow['steps'] if str(row['id']) == '33')
    p, folder, lib = project(tmp_path)
    assert produce(p, folder, lib, monkeypatch, '33')
    assert any('power_report_check' in str(clause) for clause in row['gate']['all_of'])
    # Exercise the declared command through the real exit-zero evaluator.
    command = row['gate']['all_of'][0]['program_exit_zero']
    clause = FC._check_program_exit_zero(p, command)
    assert clause[0] is True, clause
    (folder / 'invocation.log').unlink()
    clause = FC._check_program_exit_zero(p, command)
    assert clause[0] is False, clause
