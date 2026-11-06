"""Reviewed Step33 controls only. All fixtures are SOURCE_FIXTURE_ONLY."""
import json
from pathlib import Path
import pytest
import _default_backend_fixtures as BF
import librelane_contract as LC
import librelane_postroute as LP
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




def original_transport(tmp_path, monkeypatch, p, folder):
    owner = tmp_path / 'original-owner'
    native = owner / 'phase3/librelane/34/01-openroad-fillinsertion'
    odb = write(native / 'neutral.odb', 'neutral immutable ODB\n')
    routed_def = write(native / 'neutral.def', 'VERSION 5.8 ;\nDESIGN neutral ;\nEND DESIGN\n')
    netlist = write(native / 'neutral.nl.v', NETLIST)
    sdc = write(native / 'neutral.sdc',
                'create_clock -name c -period 10 [get_ports x]\n')
    image = json.loads((folder / 'vibeic_receipt.json').read_text())['input']['image']
    real_resolve = LC.resolve_image

    def resolve(root, **kwargs):
        return image if Path(root).resolve() == owner.resolve() else real_resolve(root, **kwargs)

    monkeypatch.setattr(LC, 'resolve_image', resolve)
    state = put(owner / 'state_out.json', {
        'nl': str(netlist), 'sdc': str(sdc), 'def': str(routed_def),
        'odb': str(odb), 'gds': str(owner / 'neutral.gds')})
    return {'owner': owner, 'odb': odb, 'def': routed_def, 'netlist': netlist,
            'sdc': sdc, 'record': state, 'image': image}


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






def test_current_tool_mounts_fit_native_transport(tmp_path):
    p, _, _ = project(tmp_path)
    _, tool = C.tool_subject(p, 'neutral')
    assert tool['mounts']
    assert all(isinstance(host, Path) and host.is_dir() and guest.startswith('/pdk/')
               for host, guest in tool['mounts'])




def test_nine_corner_adoption_reuses_common_owner_and_validates_every_mapping(
        tmp_path, monkeypatch):
    p, folder, _, corners = nine_corner_transport(tmp_path, monkeypatch)
    corner_calls = []
    real_corner = C._tool_subject_from_common

    def observe_corner(common, **kwargs):
        corner_calls.append(kwargs.get('corner'))
        return real_corner(common, **kwargs)

    monkeypatch.setattr(C, '_tool_subject_from_common', observe_corner)
    notes = []
    report = p / 'reports/phase3/power.rpt'
    assert power.adopt_current_power_report(p, 'neutral', report, notes) is True
    values = power.stapostpnr_corner_power(folder)
    assert list(values) == corners
    assert len({row['total_w'] for row in values.values()}) == 9
    assert corner_calls[:9] == corners
    assert corner_calls[9:] == [corners[-1], corners[-1]]
    assert json.loads(report.with_suffix('.current.json').read_text())['tool_corner'] == corners[-1]
