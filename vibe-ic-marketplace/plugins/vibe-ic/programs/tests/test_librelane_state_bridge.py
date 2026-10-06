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
        return SimpleNamespace(returncode=0, stdout='', stderr='')
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


def test_switch_absent_or_for_another_step_keeps_the_floorplan_direct(tmp_path):
    assert runner._librelane_floorplan_modes(tmp_path) == {'15': 'direct', '15.5ic': 'direct'}
    put(tmp_path / 'phase3/librelane_switch.json', {'steps': {'9': 'librelane', '37': 'dual'}})
    assert runner._librelane_floorplan_modes(tmp_path) == {'15': 'direct', '15.5ic': 'direct'}


def _drive_step_pnr_to_the_deck_builder(tmp_path, monkeypatch, switch):
    """Run the REAL step_pnr up to `_build_pnr_tcl_text` and return what it is given.

    Only the process edge is substituted: no container (every docker call
    answers rc 1), a netlist and the two block builders whose output the switch
    decides.  Everything between (die, SDC, tap pitch, EM floor, filler spec)
    is the step's own code.
    """
    import test_pad_connected_pdn_ring as ring_fixture
    project = tmp_path / 'proj'
    project.mkdir(parents=True)
    if switch is not None:
        put(project / 'phase3/librelane_switch.json', {'steps': switch})
    pdk = ring_fixture._pdk(tmp_path, ring=None)
    netlist = write(tmp_path / 'dut.v', 'module dut(input clk, output q); assign q=clk; endmodule\n')
    for name, value in {
            'pnr_input_netlist': lambda *a: (netlist, 'test DUT', False),
            '_v1_6_599_check_wrapper_pin_order_cfg': lambda *a: None,
            '_stage_via_legalized_tech_lef': lambda *a: {'status': 'NOT_NEEDED'},
            'set_invocation_provenance_sink': lambda *a: None,
            '_macro_supply_preroute_decision': lambda *a, **k: None,
            '_resolve_staged_silicon_sdc': lambda *a: None,
            '_liberty_drv_limits': lambda *a: {},
            '_build_auto_silicon_sdc': lambda *a, **k: '',
            '_docker_exec': lambda *a, **k: (1, '', 'no container in this test'),
            '_docker_exec_raw': lambda *a, **k: (1, '', 'no container in this test'),
            '_build_tapcell_prune_tcl': lambda *a: 'DIRECT_TAP_PRUNE\n',
            '_build_welltie_coverage_repair_tcl': lambda *a: 'DIRECT_WELLTIE_REPAIR\n'}.items():
        monkeypatch.setattr(runner, name, value)

    class AtBuilder(Exception):
        pass

    seen = {}

    def builder(**kwargs):
        seen.update(kwargs)
        raise AtBuilder

    monkeypatch.setattr(runner, '_build_pnr_tcl_text', builder)
    with pytest.raises(AtBuilder):
        runner.step_pnr(project, 'dut', pdk, 'unused', '400x400', 0.4)
    # Two arms run in two directories; the paths are the only thing allowed to differ.
    text = json.dumps({k: v for k, v in seen.items()}, sort_keys=True, default=str)
    return json.loads(text.replace(str(tmp_path), '<ARM>'))


def test_no_switch_step_pnr_builds_byte_identical_blocks(tmp_path, monkeypatch):
    """No-op proof at the deck builder: absent switch == switch naming other steps."""
    absent = _drive_step_pnr_to_the_deck_builder(tmp_path / 'a', monkeypatch, None)
    other = _drive_step_pnr_to_the_deck_builder(tmp_path / 'b', monkeypatch,
                                                {'9': 'librelane', '37': 'dual', '25': 'librelane'})
    assert absent.keys() == other.keys() and len(absent) > 30
    differing = [k for k in absent if absent[k] != other[k]]
    assert differing == []
    assert absent['tapcell_prune_block'] == 'DIRECT_TAP_PRUNE\n'
    assert 'DIRECT_WELLTIE_REPAIR' in absent['filler_block']


def test_step15_on_librelane_leaves_the_tool_taps_alone(tmp_path, monkeypatch):
    """The direct prune and post-route well-tie repair would edit TapEndcapInsertion's taps."""
    ll = _drive_step_pnr_to_the_deck_builder(tmp_path, monkeypatch,
                                             {'15': 'librelane', '15.5ic': 'librelane'})
    assert ll['tapcell_prune_block'] == ''
    assert 'DIRECT_WELLTIE_REPAIR' not in ll['filler_block']


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


@pytest.mark.parametrize('modes,code', [
    ({'15': 'dual', '15.5ic': 'librelane'}, 'LL_DUAL_FLOORPLAN_NOT_READY'),
    ({'15': 'librelane', '15.5ic': 'direct'}, 'LL_FLOORPLAN_PADRING_SPLIT_UNSUPPORTED'),
    ({'15': 'librelane', '15.5ic': 'librelane'}, 'LL_PDK_ROOT_NOT_DECLARED'),
])
def test_floorplan_switch_refuses_by_name_and_never_runs_direct(tmp_path, monkeypatch, modes, code):
    def must_not(*_a, **_k):  # pragma: no cover
        raise AssertionError('direct producer or tool ran')
    monkeypatch.setattr(runner, '_docker_exec', must_not)
    monkeypatch.setattr(runner, 'step_pad_ring_gen', must_not)
    result, consumer = runner._prepare_librelane_floorplan_for_route(
        tmp_path, _pdk(tmp_path), 'c', tmp_path / 'phase3/stage3/pnr', _deck(), modes)
    assert result.status in ('FAIL', 'NOT_MEASURED') and code in result.detail
    assert consumer is None


def test_floorplan_with_no_resolvable_image_is_not_measured_by_name(tmp_path, monkeypatch):
    def must_not(*_a, **_k):  # pragma: no cover
        raise AssertionError('direct producer or tool ran')

    def unresolvable(env=None, *, allow_pull=False):
        raise _eda_pin.ImageNotResolvable(['this host: none'])
    monkeypatch.setattr(_eda_pin, 'resolved_image_digest', unresolvable)
    monkeypatch.setattr(runner, '_docker_exec', must_not)
    monkeypatch.setattr(runner, 'step_pad_ring_gen', must_not)
    monkeypatch.setenv('VIBEIC_LIBRELANE_PDK_ROOT', str(tmp_path / 'pdks'))
    result, consumer = runner._prepare_librelane_floorplan_for_route(
        tmp_path, _pdk(tmp_path), 'c', tmp_path / 'phase3/stage3/pnr', _deck(),
        {'15': 'librelane', '15.5ic': 'librelane'})
    assert result.status == 'NOT_MEASURED'
    assert result.detail.startswith('LL_IMAGE_NOT_RESOLVABLE')
    assert consumer is None


def test_librelane_floorplan_state_reaches_the_direct_routing_deck(tmp_path, monkeypatch):
    project = tmp_path / 'project'
    out_dir = project / 'phase3/stage3/pnr'
    wrapper = write(out_dir / 'chip_top_io.v', 'module chip_top(a);\n  input a;\n  core u_core (.a(a));\nendmodule\n')
    netlist = write(project / 'phase3/stage2/core.v', 'module core(a);\n  input a;\nendmodule\n')
    put(project / 'phase3/librelane_switch.json',
        {'steps': {'15': 'librelane', '15.5ic': 'librelane'}, 'pdk_root_host': str(tmp_path / 'pdkroot')})
    monkeypatch.setattr(runner, '_padring_chip_top_record', lambda p: {
        'core_module': 'core', 'chip_top_module': 'chip_top',
        'chip_top_verilog': str(wrapper.relative_to(project))})
    monkeypatch.setattr(runner, 'pnr_input_netlist', lambda p, core: (netlist, 'n', False))
    monkeypatch.setattr(runner, '_docker_exec', lambda *a, **k: (0, 'ok', ''))
    steps = ['OpenROAD.Floorplan', 'OpenROAD.PadRing', 'OpenROAD.CutRows',
             'OpenROAD.GeneratePDN', 'Odb.RemovePDNObstructions']
    monkeypatch.setattr(contract, 'flow_segment', lambda image, first, last, **k: (
        steps if last == 'Odb.RemovePDNObstructions' else steps[:2]))
    seen = {}

    def resolve(project, image, pdk, step_ids, **k):
        seen['image'], seen['folder'] = image, k['folder']
        seen['overlay'] = k.get('overlay')
        return {s: _declared(tmp_path, s, tmp_path / 'pdkroot') for s in step_ids}
    monkeypatch.setattr(contract, 'resolve_step_configs', resolve)
    monkeypatch.setattr(contract, 'emit_pdn_cfg', lambda image, pdk, out, **k: write(out, 'pdn\n'))

    def chain(project, image, triples, **k):
        seen['bridge'] = json.loads(Path(triples[0][2]).read_text())
        seen['steps'] = [t[0] for t in triples]
        seen['lane'] = k['lane']
        seen['mounts'] = k['mounts']
        folders = []
        for step, _cfg, _st in triples:
            f = project / 'phase3/librelane/15-floorplan' / step
            text = DEF_TEXT.replace('END DESIGN', f'# {step}\nEND DESIGN')
            views = {'def': str(write(f / 'chip_top.def', text)),
                     'odb': str(write(f / 'chip_top.odb', step))}
            put(f / 'state_out.json', views)
            folders.append(f)
        return folders
    monkeypatch.setattr(contract, 'run_chain', chain)
    gate_calls = []
    monkeypatch.setattr(runner._pr, 'run', lambda argv, **k: gate_calls.append(argv) or
                        SimpleNamespace(returncode=0, stdout='PASS', stderr=''))
    pdk = _pdk(tmp_path)
    pdk.macro_lefs, pdk.macro_gds = [], []
    expected_image = contract.resolve_image(project)
    result, consumer = runner._prepare_librelane_floorplan_for_route(
        project, pdk, 'c', out_dir, _deck(), {'15': 'librelane', '15.5ic': 'librelane'},
        io_view_discover=lambda *a: (['/pdk/io.lef'], ['/pdk/io.gds']))
    assert result.status == 'PASS', result.detail
    assert seen['image'] == expected_image and seen['folder'] == '15-config'
    assert seen['lane'] == '15-floorplan'
    assert seen['mounts'] == [(tmp_path / 'pdkroot', '/pdk')]
    # the declared PDN deck reaches the tool config with its provenance
    value, source = seen['overlay']['PDN_CFG']
    assert value.endswith('15-config/pdn_cfg.tcl') and 'pdn_ring.connects' in source
    # the json_h view is the TOOL's (Yosys.JsonHeader heads the chain), never bridged
    assert seen['steps'][0] == 'Yosys.JsonHeader' and 'json_h' not in seen['bridge']
    # the bridge's netlist is the direct deck's own load: core then chip top
    assert Path(seen['bridge']['nl']).read_text().index('module core') < \
        Path(seen['bridge']['nl']).read_text().index('module chip_top')
    # the direct gate audited the TOOL's PadRing state
    assert '--librelane-state' in gate_calls[0]
    assert gate_calls[0][gate_calls[0].index('--librelane-state') + 1].endswith(
        'OpenROAD.PadRing/state_out.json')
    # ...with the run's own (container-side) PDK tree, never the LibreLane host mount
    root_c, tree = runner._padring_pdk_root_and_tree(pdk, 'c')
    assert gate_calls[0][-4:] == ['--pdk-root', str(root_c), '--pdk', str(tree)]
    assert str(tmp_path / 'pdkroot') not in gate_calls[0]
    # handed views are the tool's bytes, receipts bind them
    assert '# Odb.RemovePDNObstructions' in (out_dir / 'floorplan.def').read_text()
    assert '# OpenROAD.PadRing' in (out_dir / 'padring.def').read_text()
    receipt = json.loads((project / 'reports/phase3/librelane_floorplan_handoff.json').read_text())
    assert receipt['views']['def']['dest_sha256'] == contract.digest(out_dir / 'floorplan.def')
    # the routing deck consumes it: supply nets first, direct tap/PDN gone
    assert 'tapcell -distance' not in consumer and 'pdngen' not in consumer
    assert 'read_def -floorplan_initialize' in consumer
    ingest = consumer.index('read_def -floorplan_initialize')
    assert consumer.index('LIBRELANE_SUPPLY_NETS') < ingest < consumer.index('\nglobal_placement')
    assert 'floorplan.def' in consumer[ingest:consumer.index('\n', ingest)]
    assert 'read_verilog' in consumer and 'link_design chip_top' in consumer
    assert pdk.macro_lefs == ['/pdk/io.lef']


def test_padring_only_keeps_the_direct_taps_and_pdn(tmp_path, monkeypatch):
    project = tmp_path / 'project'
    out_dir = project / 'phase3/stage3/pnr'
    wrapper = write(out_dir / 'chip_top_io.v', 'module chip_top(a);\n  input a;\n  core u_core (.a(a));\nendmodule\n')
    put(project / 'phase3/librelane_switch.json', {'pdk_root_host': str(tmp_path)})
    monkeypatch.setattr(runner, '_padring_chip_top_record', lambda p: {
        'core_module': 'core', 'chip_top_verilog': str(wrapper.relative_to(project))})
    netlist = write(project / 'phase3/stage2/core.v', 'module core(a);\n  input a;\nendmodule\n')
    monkeypatch.setattr(runner, 'pnr_input_netlist', lambda p, core: (netlist, 'n', False))
    monkeypatch.setattr(runner, '_docker_exec', lambda *a, **k: (0, 'ok', ''))
    monkeypatch.setattr(contract, 'flow_segment', lambda image, first, last, **k: [first, last])
    monkeypatch.setattr(contract, 'resolve_step_configs', lambda p, i, pdk, ids, **k: {
        s: _declared(tmp_path, s, tmp_path) for s in ids})
    monkeypatch.setattr(contract, 'emit_pdn_cfg', lambda *a, **k: None)

    def chain(project, image, triples, **k):
        out = []
        for step, _c, _s in triples:
            f = project / 'phase3/librelane/15-floorplan' / step
            put(f / 'state_out.json', {'def': str(write(f / 'x.def', DEF_TEXT)),
                                       'odb': str(write(f / 'x.odb', 'o'))})
            out.append(f)
        return out
    monkeypatch.setattr(contract, 'run_chain', chain)
    monkeypatch.setattr(runner._pr, 'run', lambda *a, **k: SimpleNamespace(returncode=0, stdout='', stderr=''))
    pdk = _pdk(tmp_path)
    result, consumer = runner._prepare_librelane_floorplan_for_route(
        project, pdk, 'c', out_dir, _deck(), {'15': 'direct', '15.5ic': 'librelane'},
        io_view_discover=lambda *a: ([], []))
    assert result.status == 'PASS', result.detail
    assert 'tapcell -distance' in consumer and 'pdngen' in consumer
    ingest = consumer.index('read_def -floorplan_initialize')
    assert 'padring.def' in consumer[ingest:consumer.index('\n', ingest)]


def test_a_failing_tool_gate_blocks_routing(tmp_path, monkeypatch):
    project = tmp_path / 'project'
    out_dir = project / 'phase3/stage3/pnr'
    wrapper = write(out_dir / 'chip_top_io.v', 'module chip_top(a);\n  input a;\n  core u_core (.a(a));\nendmodule\n')
    put(project / 'phase3/librelane_switch.json', {'pdk_root_host': str(tmp_path)})
    monkeypatch.setattr(runner, '_padring_chip_top_record', lambda p: {
        'core_module': 'core', 'chip_top_verilog': str(wrapper.relative_to(project))})
    netlist = write(project / 'phase3/stage2/core.v', 'module core(a);\n  input a;\nendmodule\n')
    monkeypatch.setattr(runner, 'pnr_input_netlist', lambda p, core: (netlist, 'n', False))
    monkeypatch.setattr(runner, '_docker_exec', lambda *a, **k: (0, 'ok', ''))
    monkeypatch.setattr(contract, 'flow_segment', lambda image, first, last, **k: [first, last])
    monkeypatch.setattr(contract, 'resolve_step_configs', lambda p, i, pdk, ids, **k: {
        s: _declared(tmp_path, s, tmp_path) for s in ids})
    monkeypatch.setattr(contract, 'emit_pdn_cfg', lambda *a, **k: None)

    def chain(project, image, triples, **k):
        out = []
        for step, _c, _s in triples:
            f = project / 'phase3/librelane/15-floorplan' / step
            put(f / 'state_out.json', {'def': str(write(f / 'x.def', DEF_TEXT)),
                                       'odb': str(write(f / 'x.odb', 'o'))})
            out.append(f)
        return out
    monkeypatch.setattr(contract, 'run_chain', chain)
    monkeypatch.setattr(runner._pr, 'run', lambda *a, **k: SimpleNamespace(
        returncode=1, stdout='PAD_SIDE_MISMATCH', stderr=''))
    result, consumer = runner._prepare_librelane_floorplan_for_route(
        project, _pdk(tmp_path), 'c', out_dir, _deck(), {'15': 'direct', '15.5ic': 'librelane'},
        io_view_discover=lambda *a: ([], []))
    assert result.status == 'FAIL' and 'PADRING_TOOL_GATE_FAILED' in result.detail
    assert consumer is None


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
    put(p / 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json', {'fields': {}})
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
    bare = _chip_design(tmp_path / 'b', plan=False)
    out = contract.emit_config(bare, 'sky130A', bare / 'cfg.json')
    assert not {'VDD_NETS', 'GND_NETS', 'PDN_CORE_RING', 'PDN_CORE_RING_CONNECT_TO_PADS'} & set(out)


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


@pytest.mark.parametrize('switch,expected', [
    (None, 'direct'),
    ({'9': 'librelane'}, 'direct'),
    ({'15': 'librelane', '15.5ic': 'librelane'}, 'librelane'),
    ({'15.5ic': 'librelane'}, 'librelane'),
])
def test_the_install_seam_calls_the_producer_the_switch_selects(tmp_path, monkeypatch, switch, expected):
    """Drive the real step_pnr through `_install_route_deck` on the chip path."""
    import test_pad_connected_pdn_ring as ring_fixture
    project = tmp_path / 'proj'
    project.mkdir(parents=True)
    if switch is not None:
        put(project / 'phase3/librelane_switch.json', {'steps': switch})
    pdk = ring_fixture._pdk(tmp_path, ring=None)
    netlist = write(tmp_path / 'dut.v', 'module dut(input clk, output q); assign q=clk; endmodule\n')
    called = []

    def producer(name):
        def refuse(*a, **k):
            called.append(name)
            return runner.StepResult('pad_ring_gen', 'FAIL', 0.0, f'{name} refused in test'), None
        return refuse

    for name, value in {
            'pnr_input_netlist': lambda *a: (netlist, 'test DUT', False),
            '_v1_6_599_check_wrapper_pin_order_cfg': lambda *a: None,
            '_stage_via_legalized_tech_lef': lambda *a: {'status': 'NOT_NEEDED'},
            'set_invocation_provenance_sink': lambda *a: None,
            '_macro_supply_preroute_decision': lambda *a, **k: None,
            '_resolve_staged_silicon_sdc': lambda *a: None,
            '_liberty_drv_limits': lambda *a: {},
            '_build_auto_silicon_sdc': lambda *a, **k: '',
            '_docker_exec': lambda *a, **k: (1, '', 'no container in this test'),
            '_docker_exec_raw': lambda *a, **k: (1, '', 'no container in this test'),
            '_chip_path_requests_pad_ring': lambda *a: True,
            '_build_pnr_tcl_text': lambda **k: _deck(),
            '_prepare_padring_for_route': producer('direct'),
            '_prepare_librelane_floorplan_for_route': producer('librelane')}.items():
        monkeypatch.setattr(runner, name, value)
    result = runner.step_pnr(project, 'dut', pdk, 'unused', '400x400', 0.4)
    assert called == [expected]
    assert result.status == 'FAIL' and f'{expected} refused in test' in result.detail


def test_a_placement_retry_reaches_the_same_tool_floorplan_again(tmp_path, monkeypatch):
    """GPL-0305 retry (placement only) must not be refused as a die rewrite.

    MEASURED on the spm copy: the retry rewrites the deck's GPL command and
    re-installs; a guard that compared deck text refused it as
    LL_FLOORPLAN_RESIZE_REFUSED and PnR never retried.
    """
    import test_pad_connected_pdn_ring as ring_fixture
    project = tmp_path / 'proj'
    project.mkdir(parents=True)
    put(project / 'phase3/librelane_switch.json', {'steps': {'15': 'librelane', '15.5ic': 'librelane'}})
    pdk = ring_fixture._pdk(tmp_path, ring=None)
    netlist = write(tmp_path / 'dut.v', 'module dut(input clk, output q); assign q=clk; endmodule\n')
    calls = []

    def librelane_producer(*a, **k):
        calls.append(a[4])
        if len(calls) == 1:
            return runner.StepResult('pad_ring_gen', 'PASS', 0.0, 'tool floorplan'), a[4]
        return runner.StepResult('pad_ring_gen', 'FAIL', 0.0, 'second install reached'), None

    gpl_log = ('[INFO GPL-0015] Region area: 5633783.232\n'
               '[INFO GPL-0018] Movable instances area: 10181.947\n'
               '[ERROR GPL-0305] RePlAce diverged during gradient descent calculation\n')

    def docker(container, cmd, *a, **k):
        return (1, gpl_log, '') if 'openroad -no_init -exit -metrics' in cmd else (1, '', 'no container')

    deck = _deck().replace('global_placement\n', 'global_placement -routability_driven -timing_driven -density 0.4\n')
    for name, value in {
            'pnr_input_netlist': lambda *a: (netlist, 'test DUT', False),
            '_v1_6_599_check_wrapper_pin_order_cfg': lambda *a: None,
            '_stage_via_legalized_tech_lef': lambda *a: {'status': 'NOT_NEEDED'},
            'set_invocation_provenance_sink': lambda *a: None,
            '_macro_supply_preroute_decision': lambda *a, **k: None,
            '_resolve_staged_silicon_sdc': lambda *a: None,
            '_liberty_drv_limits': lambda *a: {},
            '_build_auto_silicon_sdc': lambda *a, **k: '',
            '_docker_exec': docker,
            '_docker_exec_raw': lambda *a, **k: (1, '', 'no container in this test'),
            '_chip_path_requests_pad_ring': lambda *a: True,
            '_build_pnr_tcl_text': lambda **k: deck,
            '_write_sdr_child_decks': lambda *a, **k: {},
            '_prepare_librelane_floorplan_for_route': librelane_producer}.items():
        monkeypatch.setattr(runner, name, value)
    result = runner.step_pnr(project, 'dut', pdk, 'unused', '400x400', 0.4)
    assert len(calls) == 2, result.detail
    assert '-timing_driven' in calls[0] and '-timing_driven' not in calls[1]
    assert 'LL_FLOORPLAN_RESIZE_REFUSED' not in result.detail
    assert 'second install reached' in result.detail


def test_a_die_upsize_cannot_silently_reuse_the_tool_floorplan(tmp_path, monkeypatch):
    """GPL-0301 over-utilization rewrites the die; the tool floorplan cannot follow."""
    import test_pad_connected_pdn_ring as ring_fixture
    project = tmp_path / 'proj'
    project.mkdir(parents=True)
    put(project / 'phase3/librelane_switch.json', {'steps': {'15': 'librelane', '15.5ic': 'librelane'}})
    pdk = ring_fixture._pdk(tmp_path, ring=None)
    netlist = write(tmp_path / 'dut.v', 'module dut(input clk, output q); assign q=clk; endmodule\n')
    calls = []

    def librelane_producer(*a, **k):
        calls.append(a[4])
        return runner.StepResult('pad_ring_gen', 'PASS', 0.0, 'tool floorplan'), a[4]

    def docker(container, cmd, *a, **k):
        if 'openroad -no_init -exit -metrics' in cmd:
            return 1, '[ERROR GPL-0301] Utilization 180.0 % exceeds 100%.\n', ''
        return 1, '', 'no container'

    for name, value in {
            'pnr_input_netlist': lambda *a: (netlist, 'test DUT', False),
            '_v1_6_599_check_wrapper_pin_order_cfg': lambda *a: None,
            '_stage_via_legalized_tech_lef': lambda *a: {'status': 'NOT_NEEDED'},
            'set_invocation_provenance_sink': lambda *a: None,
            '_macro_supply_preroute_decision': lambda *a, **k: None,
            '_resolve_staged_silicon_sdc': lambda *a: None,
            '_liberty_drv_limits': lambda *a: {},
            '_build_auto_silicon_sdc': lambda *a, **k: '',
            '_docker_exec': docker,
            '_docker_exec_raw': lambda *a, **k: (1, '', 'no container in this test'),
            '_chip_path_requests_pad_ring': lambda *a: True,
            '_build_pnr_tcl_text': lambda **k: _deck(),
            '_write_sdr_child_decks': lambda *a, **k: {},
            '_prepare_librelane_floorplan_for_route': librelane_producer}.items():
        monkeypatch.setattr(runner, name, value)
    result = runner.step_pnr(project, 'dut', pdk, 'unused', '400x400', 0.4)
    assert len(calls) == 1
    assert result.status == 'FAIL' and 'LL_FLOORPLAN_RESIZE_REFUSED' in result.detail


def test_a_declared_switch_is_part_of_the_admission_identity(tmp_path):
    """A switch changes the producer; the canonical admission must see it.

    Without it, a contract-only change or adding the switch to a project that
    already ran direct is refused DUPLICATE_NO_NEW_EVIDENCE (measured on the spm
    copy). With no switch nothing is added, so existing identities are unchanged.
    """
    import inspect
    assert runner._librelane_admission_facts(tmp_path) == {}
    put(tmp_path / 'phase3/librelane_switch.json', {'steps': {'15': 'librelane'}})
    facts = runner._librelane_admission_facts(tmp_path)
    assert facts['librelane_switch'] == {'steps': {'15': 'librelane'}}
    assert facts['librelane_contract_sha256'] == contract.digest(PROGRAMS / 'librelane_contract.py')
    put(tmp_path / 'phase3/librelane_switch.json', {'steps': {'15': 'dual'}})
    assert runner._librelane_admission_facts(tmp_path) != facts
    main_src = inspect.getsource(runner.main)
    assert '**_librelane_admission_facts(project)' in main_src


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
