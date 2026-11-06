"""T89: the two-way state bridge, the resolved-image default and the 15/15.5ic switch.

The contract and the runner run for real; only an EDA tool's file writes are
substituted at the subprocess edge.
"""
import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
contract = importlib.import_module('librelane_contract')
import _eda_pin  # noqa: E402
from _stated_eda_image import STATED_DIGEST, stated_image, state_the_image  # noqa: E402

#: Verbatim probe output from the released 0.3.77 image
#: (ghcr.io/vibeic/vibeic-eda@sha256:b966901e...), openroad and openroad-python.
PROBE_077 = ('VIBEIC_TCL_MISSING est::check_corner_wire_cap ::est::check_corner_wire_caps\n' 'VIBEIC_TCL_MISSING sta::corners \n' 'VIBEIC_TCL_MISSING sta::find_corner \n' 'VIBEIC_TCL_MISSING sta::set_cmd_corner \n' 'VIBEIC_TCL_MISSING utl::metric_int ::utl::metric_integer\n' 'VIBEIC_TCL_MISSING est::check_corner_wire_cap ::est::check_corner_wire_caps\n' 'VIBEIC_TCL_MISSING sta::corners \n' 'VIBEIC_TCL_MISSING sta::find_corner \n' 'VIBEIC_TCL_MISSING sta::set_cmd_corner \n' 'VIBEIC_TCL_MISSING utl::metric_int ::utl::metric_integer\n')


def put(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj))
    return path


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.fixture(autouse=True)
def _fresh_capability_cache(monkeypatch):
    # raising=False: the pre-T89 contract has no cache, and must still run each test
    from _stated_eda_image import mock_docker_route
    mock_docker_route(monkeypatch)
    monkeypatch.setattr(contract, '_CAPABILITY', {}, raising=False)
    monkeypatch.delenv('VIBEIC_LIBRELANE_IMAGE', raising=False)
    monkeypatch.delenv('VIBEIC_LIBRELANE_PDK_ROOT', raising=False)
    state_the_image(monkeypatch)


# ---------------------------------------------------------------- image ---

def test_default_image_is_the_host_resolved_image_and_declarations_override(tmp_path, monkeypatch):
    # the fallback is the plugin's one runtime resolver, never a stored constant
    assert contract.resolve_image(tmp_path) == stated_image()
    monkeypatch.setattr(_eda_pin, 'resolved_image_digest',
                        lambda env=None, *, allow_pull=False: 'sha256:' + '9e' * 32)
    assert contract.resolve_image(tmp_path) == f"{_eda_pin.IMAGE_REPO_DEFAULT}@sha256:{'9e' * 32}"
    monkeypatch.setenv('VIBEIC_LIBRELANE_IMAGE', 'env-image')
    assert contract.resolve_image(tmp_path) == 'env-image'
    put(tmp_path / 'phase3/librelane_switch.json', {'image': 'declared-image'})
    assert contract.resolve_image(tmp_path) == 'declared-image'


def test_unresolvable_image_is_refused_by_name_never_guessed(tmp_path, monkeypatch):
    def unresolvable(env=None, *, allow_pull=False):
        raise _eda_pin.ImageNotResolvable(['this host: no vibeic-eda image carries a digest'])
    monkeypatch.setattr(_eda_pin, 'resolved_image_digest', unresolvable)
    with pytest.raises(contract.Refusal, match='LL_IMAGE_NOT_RESOLVABLE') as info:
        contract.resolve_image(tmp_path)
    assert info.value.code == 'LL_IMAGE_NOT_RESOLVABLE'
    assert 'no vibeic-eda image carries a digest' in str(info.value)
    # an explicit declaration still wins without asking the host
    monkeypatch.setenv('VIBEIC_LIBRELANE_IMAGE', 'env-image')
    assert contract.resolve_image(tmp_path) == 'env-image'


def test_capability_derives_only_unique_abbreviation_aliases(monkeypatch):
    def fake(cmd, **_):
        return SimpleNamespace(returncode=0, stdout=PROBE_077 if 'bash' in cmd else '', stderr='')
    monkeypatch.setattr(contract.subprocess, 'run', fake)
    cap = contract.image_capability('released')
    assert cap['openroad_aliases'] == {'est::check_corner_wire_cap': 'est::check_corner_wire_caps',
                                       'utl::metric_int': 'utl::metric_integer'}
    # guarded fallbacks with no expansion are recorded, not aliased, not refused
    assert cap['unresolved_guarded'] == ['sta::corners', 'sta::find_corner', 'sta::set_cmd_corner']


def test_ambiguous_abbreviation_is_an_api_skew_refusal(monkeypatch):
    skew = 'VIBEIC_TCL_MISSING utl::metric ::utl::metric_a ::utl::metric_b\n'
    monkeypatch.setattr(contract.subprocess, 'run', lambda cmd, **_: SimpleNamespace(
        returncode=0, stdout=skew if 'bash' in cmd else '', stderr=''))
    with pytest.raises(contract.Refusal, match='LL_IMAGE_TCL_API_SKEW'):
        contract.image_capability('skewed')


def test_cli_incapable_image_is_still_refused(monkeypatch):
    monkeypatch.setattr(contract.subprocess, 'run', lambda *a, **k: SimpleNamespace(
        returncode=1, stdout='', stderr=''))
    with pytest.raises(contract.Refusal, match='LL_IMAGE_INCAPABLE'):
        contract.image_capability('old-image')


def _chain_fixture(tmp_path):
    p = tmp_path / 'design'
    source = p / 'source'
    for name in ('a.odb', 'a.def', 'a.nl', 'a.sdc'):
        write(source / name, name)
    state = put(p / 'initial.json', {k: str(source / ('a.' + k)) for k in ('odb', 'def', 'nl', 'sdc')})
    cfg = put(p / 'config.json', {'meta': {'step': 'OpenROAD.STAMidPNR'}})
    return p, state, cfg


def _tool(calls):
    def fake(cmd, **_):
        calls.append(cmd)
        folder = Path(cmd[cmd.index('-o') + 1])
        views = {k: str(write(folder / ('b.' + k), k)) for k in ('odb', 'def', 'nl', 'sdc')}
        put(folder / 'state_out.json', views)
        return SimpleNamespace(returncode=0,
                               stdout='tool fixture wrote state_out.json\n', stderr='')
    return fake


def test_chain_runs_openroad_with_the_probed_aliases(tmp_path, monkeypatch):
    p, state, cfg = _chain_fixture(tmp_path)
    calls = []
    monkeypatch.setattr(contract, 'image_capability', lambda *a: {
        'openroad_aliases': {'utl::metric_int': 'utl::metric_integer'}})
    monkeypatch.setattr(contract.subprocess, 'run', _tool(calls))
    folder = contract.run_chain(p, 'released', [('OpenROAD.STAMidPNR', cfg, state)], pdk_root='/pdk')[0]
    home = p / 'phase3/librelane/.openroad_home'
    assert f'HOME={home.resolve()}' in calls[0]
    init = (home / '.openroad').read_text()
    assert 'proc ::utl::metric_int {args} { return [::utl::metric_integer {*}$args] }' in init
    fingerprint = json.loads((folder / 'input_fingerprint.json').read_text())
    assert fingerprint['openroad_aliases'] == {'utl::metric_int': 'utl::metric_integer'}


def test_chain_without_aliases_is_unchanged(tmp_path, monkeypatch):
    p, state, cfg = _chain_fixture(tmp_path)
    calls = []
    monkeypatch.setattr(contract, 'image_capability', lambda *a: None)
    monkeypatch.setattr(contract.subprocess, 'run', _tool(calls))
    folder = contract.run_chain(p, 'released', [('OpenROAD.STAMidPNR', cfg, state)], pdk_root='/pdk')[0]
    assert not any(str(x).startswith('HOME=') for x in calls[0])
    assert 'openroad_aliases' not in json.loads((folder / 'input_fingerprint.json').read_text())


# ------------------------------------------------------ direct -> LibreLane ---

DEF_TEXT = """VERSION 5.8 ;
DESIGN chip_top ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 100000 100000 ) ;
PINS 3 ;
    - VDD + NET VDD + SPECIAL + DIRECTION INOUT + USE POWER
      + PLACED ( 0 0 ) N ;
    - VSS + NET VSS + SPECIAL + DIRECTION INOUT + USE GROUND
      + PLACED ( 0 0 ) N ;
    - clk + NET clk + DIRECTION INPUT + USE SIGNAL
      + PLACED ( 5 5 ) N ;
END PINS
SPECIALNETS 3 ;
    - VDD ( * VDD ) + USE POWER
      + ROUTED Metal4 1600 + SHAPE STRIPE ( 100 0 ) ( 100 900 ) ;
    - VSS ( * VSS ) + USE GROUND
      + ROUTED Metal4 1600 + SHAPE STRIPE ( 300 0 ) ( 300 900 ) ;
    - clk_shield ( * clk_shield ) + USE SIGNAL ;
END SPECIALNETS
END DESIGN
"""


GEOMETRY = ['odb', 'def', 'sdc', 'nl', 'pnl']


def _resolved(tmp_path, step, inputs, outputs=()):
    """A config as resolve_step_configs writes it: LibreLane-loadable meta + views sidecar."""
    put(tmp_path / 'cfg' / f'{step}.views.json', {'step': step, 'inputs': inputs,
                                                   'outputs': list(outputs)})
    return put(tmp_path / 'cfg' / f'{step}.json', {
        'DESIGN_NAME': 'chip_top', 'TECH_LEFS': {'nom_*': '/pdk/tech.lef'},
        'CELL_LEFS': ['/pdk/cells.lef'], 'PAD_LEFS': ['/pdk/pads.lef'],
        'meta': {'step': step, 'librelane_version': '3.1.0.dev1'}})


def test_bridge_requires_what_the_tool_declares(tmp_path):
    p = tmp_path / 'design'
    views = {k: write(p / 'pnr' / f'x.{k}', k) for k in ('odb', 'nl', 'sdc')}
    views['def'] = write(p / 'pnr' / 'routed.def', DEF_TEXT)
    cfg = _resolved(tmp_path, 'OpenROAD.STAPostPNR', ['nl', 'spef', 'odb'])
    with pytest.raises(contract.Refusal, match=r"LL_BRIDGE_VIEW_MISSING: OpenROAD.STAPostPNR: \['spef'\]"):
        contract.state_from_direct(p, 'img', cfg, views, p / 'bridge')
    with pytest.raises(contract.Refusal, match='LL_BRIDGE_SPEF_CORNERS_UNDECLARED'):
        contract.state_from_direct(p, 'img', cfg, {**views, 'spef': views['sdc']}, p / 'bridge')
    spef = write(p / 'pnr' / 'nom.spef', 'spef')
    state = contract.state_from_direct(p, 'img', cfg, {**views, 'spef': {'nom_*': spef}},
                                       p / 'bridge')
    doc = json.loads(state.read_text())
    assert doc['spef'] == {'nom_*': str(spef.resolve())} and doc['metrics'] == {}
    receipt = json.loads((p / 'bridge/bridge_receipt.json').read_text())
    assert receipt['views']['spef[nom_*]']['sha256'] == contract.digest(spef)
    assert receipt['state_sha256'] == contract.digest(state)


def test_bridge_refuses_undeclared_inputs_wrong_design_and_unsourced_metrics(tmp_path):
    p = tmp_path / 'design'
    views = {k: write(p / 'pnr' / f'x.{k}', k) for k in ('odb', 'nl', 'sdc')}
    views['def'] = write(p / 'pnr' / 'routed.def', DEF_TEXT)
    bare = put(tmp_path / 'bare.json', {'meta': {'step': 'Magic.StreamOut'}})
    with pytest.raises(contract.Refusal, match='LL_STEP_INPUTS_UNDECLARED'):
        contract.state_from_direct(p, 'img', bare, views, p / 'bridge')
    cfg = _resolved(tmp_path, 'Magic.StreamOut', ['def'])
    other = write(p / 'pnr' / 'other.def', DEF_TEXT.replace('DESIGN chip_top', 'DESIGN core'))
    with pytest.raises(contract.Refusal, match='LL_BRIDGE_DESIGN_MISMATCH'):
        contract.state_from_direct(p, 'img', cfg, {**views, 'def': other}, p / 'bridge')
    with pytest.raises(contract.Refusal, match='LL_BRIDGE_METRICS_UNSOURCED'):
        contract.state_from_direct(p, 'img', cfg, views, p / 'bridge', metrics={'x': 1})
    state = contract.state_from_direct(p, 'img', cfg, views, p / 'bridge', metrics={'x': 1},
                                       metrics_source='reports/phase3/drc.json')
    assert json.loads(state.read_text())['metrics'] == {'x': 1}


def test_bridge_builds_the_odb_with_the_step_configs_own_lefs(tmp_path, monkeypatch):
    p = tmp_path / 'design'
    routed = write(p / 'pnr' / 'routed.def', DEF_TEXT)
    core = write(p / 'pnr' / 'core.v', 'module core; endmodule')
    top = write(p / 'pnr' / 'chip_top_io.v', 'module chip_top; core u(); endmodule')
    sdc = write(p / 'pnr' / 'c.sdc', 'create_clock')
    cfg = _resolved(tmp_path, 'Magic.StreamOut', ['def'])
    seen = []

    def openroad_writes(cmd, **_):
        tcl = Path(cmd[-1]).read_text()
        seen.append((cmd, tcl))
        target = tcl.split('write_db {')[1].split('}')[0]
        Path(target).write_bytes(b'odb')
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr(contract.subprocess, 'run', openroad_writes)
    state = contract.state_from_direct(p, 'img', cfg, {'def': routed, 'nl': [core, top], 'sdc': sdc},
                                       p / 'bridge', mounts=[(tmp_path, '/pdk')])
    doc = json.loads(state.read_text())
    cmd, tcl = seen[0]
    assert tcl.splitlines()[:3] == ['read_lef {/pdk/tech.lef}', 'read_lef {/pdk/cells.lef}',
                                    'read_lef {/pdk/pads.lef}']
    assert f'read_def {{{routed.resolve()}}}' in tcl
    assert Path(doc['odb']).read_bytes() == b'odb'
    joined = Path(doc['nl']).read_text()
    assert joined.index('module core') < joined.index('module chip_top')
    receipt = json.loads((p / 'bridge/bridge_receipt.json').read_text())
    assert receipt['derived']['odb']['from'] == str(routed.resolve())
    assert receipt['views']['nl[1]']['sha256'] == contract.digest(top)


def test_bridge_never_synthesizes_a_view_the_tool_did_not_write(tmp_path, monkeypatch):
    p = tmp_path / 'design'
    routed = write(p / 'pnr' / 'routed.def', DEF_TEXT)
    cfg = _resolved(tmp_path, 'Magic.StreamOut', ['def'])
    monkeypatch.setattr(contract.subprocess, 'run', lambda *a, **k: SimpleNamespace(
        returncode=0, stdout='', stderr=''))
    with pytest.raises(contract.Refusal, match='LL_BRIDGE_CONVERSION_FAILED'):
        contract.state_from_direct(p, 'img', cfg, {'def': routed, 'nl': routed, 'sdc': routed},
                                   p / 'bridge')


# ------------------------------------------------------ LibreLane -> direct ---

def test_handoff_binds_every_file_by_sha_and_maps_container_paths(tmp_path):
    run = tmp_path / 'run'
    d = write(run / '22/chip_top.def', DEF_TEXT)
    o = write(run / '22/chip_top.odb', 'odb')
    s = write(run / '54/nom.spef', 'spef')
    state = put(tmp_path / 'state_out.json', {'def': '/work/22/chip_top.def', 'odb': str(o),
                                              'spef': {'nom_*': str(s)}})
    pnr = tmp_path / 'project/phase3/stage3/pnr'
    write(pnr / 'floorplan.def', 'old direct floorplan')
    receipt = contract.handoff_to_direct(
        state, {'def': pnr / 'floorplan.def', 'odb': pnr / 'll.odb',
                'spef:nom_*': pnr / 'x.spef'}, tmp_path / 'handoff.json',
        path_map={'/work': str(run)})
    assert (pnr / 'floorplan.def').read_text() == DEF_TEXT
    for view, row in receipt['views'].items():
        assert row['source_sha256'] == row['dest_sha256'] == contract.digest(Path(row['dest']))
    assert receipt['views']['def']['source'] == str(d)
    assert receipt['views']['def']['replaced_sha256'] is not None
    assert receipt['state_sha256'] == contract.digest(state)
    with pytest.raises(contract.Refusal, match='LL_HANDOFF_VIEW_MISSING: spef:max_\\*'):
        contract.handoff_to_direct(state, {'spef:max_*': pnr / 'y.spef'}, tmp_path / 'h2.json')
    with pytest.raises(contract.Refusal, match='LL_HANDOFF_VIEW_MISSING: def'):
        contract.handoff_to_direct(state, {'def': pnr / 'z.def'}, tmp_path / 'h3.json')


# ------------------------------------------------ runner: 15 / 15.5ic switch ---

runner = importlib.import_module('phase3_one_shot_runner')


def test_supply_nets_and_pins_come_only_from_the_defs_power_declarations():
    tcl = contract.def_supply_tcl(DEF_TEXT, runner._PNR_STAGE_MARKER)
    assert 'odb::dbNet_create $_ll_blk "VDD"]; $_ll_n setSpecial; $_ll_n setSigType POWER' in tcl
    assert 'odb::dbNet_create $_ll_blk "VSS"]; $_ll_n setSpecial; $_ll_n setSigType GROUND' in tcl
    assert 'dbBTerm_create [$_ll_blk findNet "VDD"] "VDD"]; $_ll_b setIoType INOUT' in tcl
    assert 'clk' not in tcl.replace('LIBRELANE', '')
    assert 'LIBRELANE_SUPPLY_NETS: 2 nets, 2 pins, 2 global-connect rules' in tcl
    # the DEF's own `( * <pin> )` terms become the deck's global-connect rules,
    # so instances created after the ingest reach a supply (spm: 21888 did not)
    assert 'add_global_connection -net {VDD} -pin_pattern {^VDD$} -power' in tcl
    assert 'add_global_connection -net {VSS} -pin_pattern {^VSS$} -ground' in tcl
    assert tcl.index('add_global_connection') < tcl.index('\nglobal_connect')


def _deck():
    m = runner._PNR_STAGE_MARKER
    return ("read_lef /pdk/core.lef\nread_verilog /work/netlist.v\nlink_design core\n"
            f'puts "{m} floorplan"\ninitialize_floorplan -die_area "0 0 100 100" \\\n'
            "  -core_area \"10 10 90 90\" -site unit\n"
            "write_def /work/phase3/stage3/pnr/floorplan.def\n"
            "tapcell -distance 15\npdngen\n"
            f'puts "{m} placement"\nglobal_placement\n'
            f'puts "{m} global_route"\nglobal_route\ndetailed_route\n')


def test_tap_and_pdn_region_is_elided_only_between_its_two_markers():
    out = contract.elide_tap_pdn_region(_deck(), runner._PNR_STAGE_MARKER)
    assert 'tapcell' not in out and 'pdngen' not in out
    assert out.index('write_def /work/phase3/stage3/pnr/floorplan.def') < out.index('global_placement')
    assert out.count('read_verilog') == 1
    with pytest.raises(ValueError, match='LL_FLOORPLAN_SEAM_AMBIGUOUS'):
        contract.elide_tap_pdn_region(_deck() + _deck(), runner._PNR_STAGE_MARKER)










def _declared(tmp_path, step, pdk_root=None):
    """The views LibreLane 3.1.0.dev1 declares for the floorplan segment's steps.

    With ``pdk_root`` (the run's PDK root), an `OpenROAD.*` step also carries
    what the resolver gives every OpenROAD step and the CR4 run-wide cell
    policy reads: its CELL_LIBS (a PDK-mount path to a Liberty written under
    ``pdk_root``) and its EXTRA_EXCLUDED_CELLS -- the same shape
    test_t96_floorplan_cutover and test_mig97_placement_spares give them."""
    if step == 'Yosys.JsonHeader':
        cfg = _resolved(tmp_path, step, [], ['json_h'])
    elif step == 'OpenROAD.Floorplan':
        cfg = _resolved(tmp_path, step, ['nl'], GEOMETRY)
    elif step == 'Odb.SetPowerConnections':
        cfg = _resolved(tmp_path, step, ['odb', 'json_h'], ['odb', 'def'])
    else:
        cfg = _resolved(tmp_path, step, ['odb'], GEOMETRY)
    if pdk_root is not None and step.startswith('OpenROAD.'):
        write(Path(pdk_root) / 'probe_pdk/libs.ref/cells.lib',
              'library(x) {\n cell (probe__dly_1) { }\n}\n')
        doc = json.loads(cfg.read_text())
        doc.update(CELL_LIBS={'nom': ['/pdk/probe_pdk/libs.ref/cells.lib']},
                   EXTRA_EXCLUDED_CELLS=[])
        cfg = put(cfg, doc)
    return cfg


def _pdk(tmp_path):
    root = tmp_path / 'pdks' / 'probe_pdk'
    lef = root / 'libs.ref' / 'probe_tech' / 'lef'
    tech = write(lef / 'probe.tlef', 'VERSION 5.8 ;\nEND LIBRARY\n')
    cells = write(lef / 'probe_cells.lef', 'VERSION 5.8 ;\nEND LIBRARY\n')
    return runner.PdkConfig(name='probe_pdk', liberty=str(lef / 'probe.lib'), tech_lef=str(tech),
                            cell_lef=str(cells), cell_gds=None, site='unit', drc_deck=None)












# ------------------------------------------- chain-wide requirements, PDN ---

def test_a_view_needed_late_in_the_chain_is_refused_before_any_step(tmp_path):
    p = tmp_path / 'design'
    nl = write(p / 'core.v', 'module core; endmodule')
    floorplan = _resolved(tmp_path, 'OpenROAD.Floorplan', ['nl'], GEOMETRY)
    power = _resolved(tmp_path, 'Odb.SetPowerConnections', ['odb', 'json_h'], ['odb', 'def'])
    with pytest.raises(contract.Refusal, match=r"LL_BRIDGE_VIEW_MISSING: OpenROAD.Floorplan: \['json_h'\]"):
        contract.state_from_direct(p, 'img', floorplan, {'nl': nl}, p / 'bridge', chain=[power])
    header = _resolved(tmp_path, 'Yosys.JsonHeader', [], ['json_h'])
    state = contract.state_from_direct(p, 'img', header, {'nl': nl}, p / 'bridge',
                                       chain=[floorplan, power])
    assert set(json.loads(state.read_text())) == {'nl', 'metrics'}


def _chip_design(tmp_path, pdk='gf180mcuD', plan=True):
    p = tmp_path / 'design'
    put(p / 'phase1/generated_docs/L8_TIMING_WAVEFORM.json', {'clock_domains': [
        {'role': 'primary', 'period_ns': 24, 'source_pin': 'clk'}]})
    put(p / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json', {'top_module': 'core'})
    put(p / 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json', {'fields': {'pdk_target': pdk}})
    put(p / 'input/submission_template/tapeout_declaration.json', {'answers': {'top_cell': 'chip_top'}})
    put(p / 'phase3/stage3/pnr/pad_assignment.json', {'PAD_SOUTH': ['u_rst']})
    if plan:
        put(p / 'reports/phase3/io_pad_chip_top.json', {'power_pad_plan': {
            'power_net': 'VDD', 'ground_net': 'VSS'}})
    return p


def test_supply_nets_and_pad_connected_ring_are_emitted_only_from_declarations(tmp_path):
    p = _chip_design(tmp_path)
    out = contract.emit_config(p, 'gf180mcuD', p / 'cfg.json')
    src = json.loads((p / 'cfg.provenance.json').read_text())
    assert out['VDD_NETS'] == ['VDD'] and out['GND_NETS'] == ['VSS']
    assert src['VDD_NETS'] == 'reports/phase3/io_pad_chip_top.json.power_pad_plan.power_net'
    assert out['PDN_CORE_RING'] is True and out['PDN_CORE_RING_CONNECT_TO_PADS'] is True
    assert src['PDN_CORE_RING'] == 'programs/pdk_registry.json.pdks[name=gf180mcuD].pdn_ring'
    # a PDK whose registry entry declares no ring, and a design with no plan
    bare = _chip_design(tmp_path / 'b', pdk='sky130A', plan=False)
    out = contract.emit_config(bare, 'sky130A', bare / 'cfg.json')
    assert not {'VDD_NETS', 'GND_NETS', 'PDN_CORE_RING', 'PDN_CORE_RING_CONNECT_TO_PADS'} & set(out)


def test_pad_placement_consumes_selected_supplemental_supply_bonds(tmp_path):
    p = _chip_design(tmp_path, pdk='sky130A')
    put(p / 'reports/phase3/io_pad_chip_top.json', {
        'verdict': 'WROTE', 'power_pad_plan': {'instances': ['u_aux']},
        'pad_instances': {
            'u_rst': {'master': 'signal_pad', 'terminal': 'PAD', 'port': 'rst'},
            'u_aux': {'master': 'aux_supply_pad', 'terminal': 'BOND', 'port': 'AUX'},
            'u_unused': {'master': 'unused_pad', 'terminal': 'PAD', 'port': 'unused'},
        },
    })
    out = contract.emit_config(p, 'sky130A', p / 'cfg.json')
    assert out['PAD_PLACE_IO_TERMINALS'] == ['aux_supply_pad/BOND', 'signal_pad/PAD']
    source = json.loads((p / 'cfg.provenance.json').read_text())
    assert 'pad_instances' in source['PAD_PLACE_IO_TERMINALS']


@pytest.mark.parametrize('banner', ['', '[INFO] USER_ID: 1000\n[INFO] SKIPPING UI STARTUP\n'],
                         ids=['clean', 'startup_banner'])
def test_pdn_cfg_is_the_images_script_plus_declared_connects(tmp_path, monkeypatch, banner):
    # Return the native script for the old raw probe and a structured envelope
    # for the repaired probe.  The banner therefore makes the base control red
    # while the candidate still proves the same payload and registry bytes.
    default = ('# native script\nputs {[INFO] belongs to this Tcl payload}\n'
               'add_pdn_connect -grid stdcell_grid -layers {Metal4 Metal5}\n\n')
    native = tmp_path / 'native/scripts/openroad/common/pdn_cfg.tcl'
    write(native, default)
    calls = []

    def probe(cmd, **_):
        calls.append(cmd)
        script = cmd[cmd.index('-c') + 1]
        if contract._PDN_PAYLOAD_KEY in script:
            stdout = banner + json.dumps({contract._PDN_PAYLOAD_KEY: default}) + '\n'
        else:
            stdout = banner + default
        return SimpleNamespace(returncode=0, stdout=stdout, stderr='')

    monkeypatch.setattr(contract.subprocess, 'run', probe)
    out = contract.emit_pdn_cfg('img', 'gf180mcuD', tmp_path / 'pdn_cfg.tcl')
    text = out.read_text()
    assert text.startswith(default)
    assert text == default + (
        '# vibe-ic: pdk_registry.json pdks[name=gf180mcuD].pdn_ring.connects\n'
        'add_pdn_connect -grid stdcell_grid -layers {Metal2 Metal5}\n'
        'add_pdn_connect -grid stdcell_grid -layers {Metal2 Metal4}\n')
    assert text.rstrip().splitlines()[-2:] == [
        'add_pdn_connect -grid stdcell_grid -layers {Metal2 Metal5}',
        'add_pdn_connect -grid stdcell_grid -layers {Metal2 Metal4}']
    assert contract.emit_pdn_cfg('img', 'sky130A', tmp_path / 'none.tcl') is None
    assert len(calls) == 1


@pytest.mark.parametrize('payload,rc', [
    ('', 0),
    ('[INFO] startup only\n', 0),
    ('not JSON add_pdn_connect', 0),
    ('"truncated add_pdn_connect', 0),
    (json.dumps({'script': 'add_pdn_connect'}), 0),
    (json.dumps({contract._PDN_PAYLOAD_KEY: None}), 0),
    (json.dumps({contract._PDN_PAYLOAD_KEY: ''}), 0),
    (json.dumps({contract._PDN_PAYLOAD_KEY: 'puts {no connection command}\n'}), 0),
    (json.dumps({contract._PDN_PAYLOAD_KEY: 'add_pdn_connect\n'}) + '\n' +
     json.dumps({contract._PDN_PAYLOAD_KEY: 'add_pdn_connect\n'}), 0),
    (json.dumps({contract._PDN_PAYLOAD_KEY: 'add_pdn_connect\n'}), 1),
], ids=['missing', 'banner_only', 'invalid_json', 'truncated_json',
        'wrong_key', 'null_payload', 'empty_payload', 'missing_connect',
        'duplicate_payload', 'probe_failed'])
def test_pdn_cfg_refuses_invalid_or_missing_payload(tmp_path, monkeypatch, payload, rc):
    monkeypatch.setattr(contract.subprocess, 'run', lambda *a, **k: SimpleNamespace(
        returncode=rc, stdout=payload, stderr='probe failure' if rc else ''))
    target = tmp_path / 'bad.tcl'
    with pytest.raises(contract.Refusal, match='LL_PDN_CFG_UNREADABLE'):
        contract.emit_pdn_cfg('img', 'gf180mcuD', target)
    assert not target.exists()


def test_overlay_joins_the_design_config_with_its_source(tmp_path, monkeypatch):
    p = _chip_design(tmp_path)
    pdk_root = tmp_path / 'pdkroot'
    (pdk_root / 'gf180mcuD').mkdir(parents=True)
    monkeypatch.setattr(contract, 'image_capability', lambda *a: None)

    def resolver(cmd, **_):
        # Match the resolver's six explicit arguments, including image identity.
        values = cmd[cmd.index('-c') + 2:]
        assert len(values) == 6, values
        assert values[-1] == cmd[cmd.index('-c') - 1]
        design, requested, root = map(Path, values[:3])
        for step in json.loads(requested.read_text()):
            put(root / f'{step}.json', {**json.loads(design.read_text()), 'meta': {'step': step}})
            put(root / f'{step}.views.json', {'step': step, 'inputs': ['odb'], 'outputs': []})
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(contract.subprocess, 'run', resolver)
    configs = contract.resolve_step_configs(
        p, 'img', 'gf180mcuD', ['OpenROAD.GeneratePDN'], pdk_root=pdk_root, folder='15-config',
        overlay={'PDN_CFG': ('/x/pdn_cfg.tcl', 'declared source')})
    assert json.loads(configs['OpenROAD.GeneratePDN'].read_text())['PDN_CFG'] == '/x/pdn_cfg.tcl'
    prov = json.loads((p / 'phase3/librelane/15-config/design.provenance.json').read_text())
    assert prov['PDN_CFG'] == 'declared source'










def test_a_declared_input_the_previous_step_did_not_write_refuses_before_the_tool(tmp_path, monkeypatch):
    """A step's declared outputs are not a promise: KLayout.StreamOut DECLARES
    `gds` and writes only `klayout_gds` (measured, 0.3.77), and KLayout.DRC
    then died inside LibreLane with rc=255. Every step's declared inputs are
    checked on the state it actually receives, so the missing view is named
    before anything is invoked -- here STAPostPNR's `spef` (no RCX before it)."""
    p, state, _cfg = _chain_fixture(tmp_path)
    sta = _resolved(tmp_path, 'OpenROAD.STAPostPNR', ['nl', 'spef', 'odb'])
    calls = []
    monkeypatch.setattr(contract, 'image_capability', lambda *a: None)
    monkeypatch.setattr(contract.subprocess, 'run', _tool(calls))
    with pytest.raises(contract.Refusal, match=r"LL_STATE_MISSING: OpenROAD.STAPostPNR: \['spef'\]"):
        contract.run_chain(p, 'released', [('OpenROAD.STAPostPNR', sta, state)], pdk_root='/pdk')
    assert calls == []


def test_an_unrunnable_tcl_probe_adds_no_alias_and_is_not_a_capability_verdict(monkeypatch):
    """The CLI/yosys probe decides capability; the Tcl probe only derives aliases."""
    monkeypatch.setattr(contract.subprocess, 'run', lambda cmd, **_: SimpleNamespace(
        returncode=1 if 'bash' in cmd else 0, stdout='', stderr=''))
    cap = contract.image_capability('stubbed')
    assert cap['openroad_aliases'] == {} and cap['tcl_probe'].startswith('NOT_MEASURED')


@pytest.mark.parametrize("scheduled", [True, False], ids=["actual_core_supply_pair", "no_supply_instances"])
def test_native_ring_connects_produced_core_supply_pair_without_registry_ring(tmp_path, scheduled):
    p = _chip_design(tmp_path, pdk="sky130A")
    put(p / "reports/phase3/io_pad_chip_top.json", {
        "verdict": "WROTE",
        "power_pad_plan": {
            "power_net": "VCORE", "ground_net": "GCORE",
            "core_supply_pads": [
                {"kind": "power", "port": "VCORE", "master": "pdk_power_pad", "terminal": "V_BOND"},
                {"kind": "ground", "port": "GCORE", "master": "pdk_ground_pad", "terminal": "G_BOND"},
            ],
            "instances": ["u_supply_power", "u_supply_ground"] if scheduled else [],
        },
    })
    out = contract.emit_config(p, "sky130A", p / "cfg.json")
    src = json.loads((p / "cfg.provenance.json").read_text())
    if scheduled:
        assert out.get("PDN_CORE_RING") is True
        assert out.get("PDN_CORE_RING_CONNECT_TO_PADS") is True
        assert "power_pad_plan.core_supply_pads" in src["PDN_CORE_RING"]
        # Native PDK/runtime owns legal layers, widths, spacing and offsets.
        assert not {"PDN_CORE_RING_CONNECT_TO_PAD_LAYERS", "PDN_CORE_RING_HWIDTH",
                    "PDN_CORE_RING_HOFFSET"} & set(out)
    else:
        assert not {"PDN_CORE_RING", "PDN_CORE_RING_CONNECT_TO_PADS"} & set(out)


def test_resistive_supply_ports_do_not_become_core_grid_terminals(tmp_path):
    p = _chip_design(tmp_path, pdk='sky130A')
    put(p / 'reports/phase3/io_pad_chip_top.json', {
        'verdict': 'WROTE', 'power_pad_plan': {
            'power_net': 'VCORE', 'ground_net': 'GCORE',
            'instances': ['u_power', 'u_ground'],
            'core_supply_pads': [
                {'kind': 'power', 'port': 'V_BOND', 'grid_net': 'VCORE',
                 'master': 'pdk_power_pad', 'terminal': 'V_BOND'},
                {'kind': 'ground', 'port': 'G_BOND', 'grid_net': 'GCORE',
                 'master': 'pdk_ground_pad', 'terminal': 'G_BOND'},
            ],
        },
    })
    out = contract.emit_config(p, 'sky130A', p / 'cfg.json')
    assert out['VDD_NETS'] == ['VCORE'] and out['GND_NETS'] == ['GCORE']
    assert out['PDN_CORE_RING'] is True
    assert out['PDN_CORE_RING_CONNECT_TO_PADS'] is True
    assert out['PDN_ENABLE_PINS'] is False


@pytest.mark.parametrize('scheduled', [True, False])
@pytest.mark.parametrize('resistive', [True, False])
def test_internal_grid_check_uses_the_scheduled_resistor_pad(scheduled, resistive):
    pad = {'kind': 'power', 'is_supply_pad': True, 'master': 'pdk_power_pad',
           'terminal': 'V_BOND', 'port': 'V_BOND' if resistive else 'VCORE',
           'grid_net': 'VCORE', 'derivation': {'fed_rail': 'V_FED'},
           'supply_connections': {'V_FED': 'VCORE',
                                  'V_BOND': 'V_BOND' if resistive else 'VCORE'}}
    record = {'verdict': 'WROTE', 'pad_instances': {'u_power': pad},
              'power_pad_plan': {'power_net': 'VCORE', 'core_supply_pads': [pad],
                                 'instances': ['u_power'] if scheduled else []}}
    assert contract.internal_supply_grid_sources(record) == (
        [['u_power', 'pdk_power_pad', 'V_FED', 'V_BOND', 'V_BOND', 'VCORE']]
        if scheduled and resistive else [])


def test_internal_grid_recipe_preserves_native_pdn_and_connectivity(tmp_path, monkeypatch):
    native = 'add_pdn_connect -grid stdcell_grid -layers {met4 met5}\n'
    monkeypatch.setattr(contract.subprocess, 'run', lambda *a, **k: SimpleNamespace(
        returncode=0, stdout=json.dumps({contract._PDN_PAYLOAD_KEY: native}), stderr=''))
    row = ['u_power', 'pdk_power_pad', 'V_FED', 'V_BOND', 'V_BOND', 'VCORE']
    out = contract.emit_pdn_cfg('img', 'sky130A', tmp_path / 'pdn.tcl',
                                internal_supply_sources=[row])
    text = out.read_text()
    assert text.startswith(native)
    assert 'findInst $instance' in text and 'findBTerm $port' in text
    assert '$core_net eq $bond_net' in text
    assert 'set ::vibeic_internal_supply_grids [list "VCORE"]' in text
    assert 'lappend args -dont_require_terminals' in text
    assert 'return [::vibeic_native_check_power_grid {*}$args]' in text


@pytest.mark.parametrize('numeric', [float, str], ids=['numbers', 'native_decimal_strings'])
@pytest.mark.parametrize('with_ring_layer', [False, True], ids=['pad_layer', 'also_native_ring_layer'])
def test_native_supply_ring_geometry_reserves_its_real_ring_and_pad_straps(numeric, with_ring_layer):
    cfg = {"DIE_AREA": [0, 0, 1030, 1030], "CORE_AREA": [204, 204, 826, 826],
           "PDN_CORE_RING": True, "PDN_CORE_RING_CONNECT_TO_PADS": True,
           "PDN_VERTICAL_LAYER": "lv", "PDN_HORIZONTAL_LAYER": "lh",
           "PDN_CORE_RING_VOFFSET": 6, "PDN_CORE_RING_HOFFSET": 6,
           "PDN_CORE_RING_VWIDTH": 1.6, "PDN_CORE_RING_HWIDTH": 1.6,
           "PDN_CORE_RING_VSPACING": 1.7, "PDN_CORE_RING_HSPACING": 1.7}
    record = {"verdict": "WROTE", "die_required_um": {
        "ring_depth_um": 204, "pad_strap_reach_um": 17.1}, "power_pad_plan": {
        "pad_strap_reach": {"verdict": "MEASURED", "cells": {
            "pdk_supply": {"sides": {"S": {"straps": [{"layer": "lp"}]}}}}}}}
    cfg['DIE_AREA'] = list(map(numeric, cfg['DIE_AREA']))
    cfg['CORE_AREA'] = list(map(numeric, cfg['CORE_AREA']))
    if with_ring_layer:
        record['power_pad_plan']['pad_strap_reach']['cells']['pdk_supply']['sides']['S']['straps'].append(
            {'layer': 'lv'})
    adjusted, connects, details = contract.native_supply_pdn_geometry(cfg, record)
    assert adjusted["CORE_AREA"] == [233, 233, 797, 797]
    assert adjusted["DIE_AREA"] == cfg["DIE_AREA"]
    assert set(map(tuple, connects)) == {("lp", "lv"), ("lp", "lh")}
    assert details["core_inset_um"] == 233
    assert details['core_area_changed'] is True
    assert cfg["CORE_AREA"] == list(map(numeric, [204, 204, 826, 826]))
