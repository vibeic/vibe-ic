"""T97: steps 16/17/18 on the tool -- LibreLane placement, the spare-cell step,
and the clock-plan gate against the tool's clocks.

The contract, the runner, the gates and the custom step's odbpy body run for
real; only an EDA tool's file writes (the container, OpenROAD's database) are
substituted at the edge.
"""
import importlib
import json
import subprocess
import sys
import textwrap
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
contract = importlib.import_module('librelane_contract')
from _stated_eda_image import state_the_image  # noqa: E402
runner = importlib.import_module('phase3_one_shot_runner')
sp = importlib.import_module('_spare_plan')
import test_librelane_state_bridge as bridge  # noqa: E402  (T89 fixtures)
from _clock_plan_fixture import current_fixture  # noqa: E402

put, write = bridge.put, bridge.write
PLUGIN = PROGRAMS / 'librelane_plugins' / 'librelane_plugin_vibeic'
_REAL_RUN = subprocess.run      # `contract.subprocess` IS this module; patched per test


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(contract, '_CAPABILITY', {}, raising=False)
    monkeypatch.delenv('VIBEIC_LIBRELANE_IMAGE', raising=False)
    monkeypatch.delenv('VIBEIC_LIBRELANE_PDK_ROOT', raising=False)
    state_the_image(monkeypatch)   # the identity is stated, never asked of this host


# ============================================================ contract ====

def test_plugin_is_mounted_only_for_vibe_ic_steps():
    assert contract._plugin_args(['OpenROAD.DetailedPlacement', 'Odb.SetPowerConnections']) == []
    args = contract._plugin_args(['OpenROAD.DetailedPlacement', 'Vibeic.InsertSpareCells'])
    programs = str(PROGRAMS.resolve())
    assert args == ['-v', f'{programs}:{programs}:ro',
                    '-e', f'PYTHONPATH={PLUGIN.parent.resolve()}']
    assert contract._plugin_digests('OpenROAD.CTS') == {}
    code = contract._plugin_digests('Vibeic.InsertSpareCells')
    assert {'librelane_plugins/librelane_plugin_vibeic/__init__.py',
            'librelane_plugins/librelane_plugin_vibeic/insert_spare_cells.py',
            '_spare_plan.py'} <= set(code)


def test_the_custom_steps_code_is_part_of_its_fingerprint(tmp_path, monkeypatch):
    """Editing the step's code must re-run it, never resume a stale result."""
    p, state, _cfg = bridge._chain_fixture(tmp_path)
    cfg = put(p / 'spare.json', {'meta': {'step': 'Vibeic.InsertSpareCells'}})
    calls = []
    monkeypatch.setattr(contract, 'image_capability', lambda *a: None)
    monkeypatch.setattr(contract.subprocess, 'run', bridge._tool(calls))
    contract.run_chain(p, 'img', [('Vibeic.InsertSpareCells', cfg, state)], pdk_root='/pdk')
    cmd = calls[0]
    assert f'PYTHONPATH={PLUGIN.parent.resolve()}' in cmd
    folder = p / 'phase3/librelane/01-vibeic-insertsparecells'
    fp = json.loads((folder / 'input_fingerprint.json').read_text())
    assert fp['plugin'] == contract._plugin_digests('Vibeic.InsertSpareCells')
    contract.run_chain(p, 'img', [('Vibeic.InsertSpareCells', cfg, state)], pdk_root='/pdk')
    assert len(calls) == 1                        # unchanged code: resumed
    monkeypatch.setattr(contract, '_plugin_digests', lambda step: {'_spare_plan.py': 'edited'})
    contract.run_chain(p, 'img', [('Vibeic.InsertSpareCells', cfg, state)], pdk_root='/pdk')
    assert len(calls) == 2                        # edited code: re-run


def test_a_tool_step_invocation_is_unchanged_by_the_plugin(tmp_path, monkeypatch):
    p, state, cfg = bridge._chain_fixture(tmp_path)
    calls = []
    monkeypatch.setattr(contract, 'image_capability', lambda *a: None)
    monkeypatch.setattr(contract.subprocess, 'run', bridge._tool(calls))
    contract.run_chain(p, 'img', [('OpenROAD.STAMidPNR', cfg, state)], pdk_root='/pdk')
    assert not any('PYTHONPATH=' in str(a) for a in calls[0])
    fp = json.loads((p / 'phase3/librelane/01-openroad-stamidpnr/input_fingerprint.json').read_text())
    assert 'plugin' not in fp


def _fake_librelane(root: Path) -> Path:
    """A LibreLane whose Chip flow drops variables it does not know -- the
    measured behaviour that lost VIBEIC_SPARE_PLAN on the spm copy."""
    pkg = root / 'librelane'
    write(pkg / '__init__.py', '')
    write(pkg / '__version__.py', "__version__ = '3.1.0.dev1'\n")
    write(pkg / 'flows' / '__init__.py', '')
    write(pkg / 'flows' / 'chip.py', textwrap.dedent('''
        import json
        KNOWN = {"DESIGN_NAME", "PL_TARGET_DENSITY_PCT", "PL_TIMING_DRIVEN"}
        class _C:
            def __init__(self, raw): self.raw = raw
            def to_raw_dict(self): return dict(self.raw)
        class Chip:
            def __init__(self, config, pdk, pdk_root, design_dir):
                raw = json.load(open(config))
                if "PL_TARGET_DENSITY" in raw:
                    raw["PL_TARGET_DENSITY_PCT"] = raw.pop("PL_TARGET_DENSITY") * 100
                self.config = _C({k: v for k, v in raw.items() if k in KNOWN})
        '''))
    write(pkg / 'steps' / '__init__.py', textwrap.dedent('''
        class _V:
            def __init__(self, name): self.name = name
        class _F:
            def __init__(self, i): self.id = i
        def _cls(names):
            return type("S", (), {"get_all_config_variables": classmethod(
                lambda c: [_V(n) for n in names]), "inputs": [_F("odb")],
                "outputs": [_F("odb"), _F("def")]})
        _STEPS = {
            "OpenROAD.GlobalPlacement": _cls(["DESIGN_NAME", "PL_TARGET_DENSITY_PCT",
                                              "PL_TIMING_DRIVEN"]),
            "Vibeic.InsertSpareCells": _cls(["DESIGN_NAME", "VIBEIC_SPARE_PLAN",
                                             "VIBEIC_SPARE_TIELO_CELL"]),
        }
        class _Factory:
            @staticmethod
            def get(i): return _STEPS.get(i)
        class Step:
            factory = _Factory()
        '''))
    return root


def _run_resolver_locally(fake_root):
    """The resolver script executes for real, on the host, against the fake
    LibreLane; only `docker run` is replaced by a local python3."""
    def run(cmd, **_):
        i = cmd.index('-c')
        script, args = cmd[i + 1], cmd[i + 2:]
        return _REAL_RUN([sys.executable, '-c', script, *args], capture_output=True,
                         text=True, env={'PYTHONPATH': str(fake_root)})
    return run


def test_a_vibe_ic_steps_own_variables_survive_resolution(tmp_path, monkeypatch):
    p = bridge._chip_design(tmp_path)
    pdk_root = tmp_path / 'pdkroot'
    (pdk_root / 'gf180mcuD').mkdir(parents=True)
    monkeypatch.setattr(contract, 'image_capability', lambda *a: None)
    monkeypatch.setattr(contract.subprocess, 'run', _run_resolver_locally(
        _fake_librelane(tmp_path / 'fake')))
    configs = contract.resolve_step_configs(
        p, 'img', 'gf180mcuD', ['OpenROAD.GlobalPlacement', 'Vibeic.InsertSpareCells'],
        pdk_root=pdk_root, folder='15-config',
        overlay={'VIBEIC_SPARE_PLAN': ('/x/spare_plan.json', 'runner plan'),
                 'VIBEIC_SPARE_TIELO_CELL': ('tiel/ZN', 'runner tie discovery'),
                 'PL_TIMING_DRIVEN': (True, 'switch')})
    spare = json.loads(configs['Vibeic.InsertSpareCells'].read_text())
    assert spare['VIBEIC_SPARE_PLAN'] == '/x/spare_plan.json'
    assert spare['VIBEIC_SPARE_TIELO_CELL'] == 'tiel/ZN'
    gpl = json.loads(configs['OpenROAD.GlobalPlacement'].read_text())
    # a tool step takes only what the flow resolved, never a Vibeic key
    assert 'VIBEIC_SPARE_PLAN' not in gpl and gpl['PL_TIMING_DRIVEN'] is True


def test_placement_levers_come_only_from_the_switch_and_are_validated(tmp_path):
    assert contract.placement_levers(tmp_path) == {}
    put(tmp_path / 'phase3/librelane_switch.json', {'steps': {'17': 'librelane'},
        'placement_levers': {'PL_TIMING_DRIVEN': True, 'PL_TARGET_DENSITY_PCT': 55,
                             'GPL_CELL_PADDING': '2', 'PL_WIRE_LENGTH_COEF': 0.3}})
    got = contract.placement_levers(tmp_path)
    assert {k: v[0] for k, v in got.items()} == {
        'PL_TIMING_DRIVEN': True, 'PL_TARGET_DENSITY_PCT': 55.0,
        'GPL_CELL_PADDING': 2, 'PL_WIRE_LENGTH_COEF': 0.3}
    assert got['GPL_CELL_PADDING'][1] == \
        'phase3/librelane_switch.json placement_levers.GPL_CELL_PADDING'
    for bad, code in (({'PL_WHATEVER': 1}, 'LL_PLACEMENT_LEVER_UNKNOWN'),
                      ({'PL_TARGET_DENSITY_PCT': 0}, 'LL_PLACEMENT_LEVER_INVALID'),
                      ({'PL_TARGET_DENSITY_PCT': 101}, 'LL_PLACEMENT_LEVER_INVALID'),
                      ({'PL_TIMING_DRIVEN': 'yes'}, 'LL_PLACEMENT_LEVER_INVALID'),
                      ({'DPL_CELL_PADDING': -1}, 'LL_PLACEMENT_LEVER_INVALID'),
                      ({'PL_MAX_DISPLACEMENT_X': True}, 'LL_PLACEMENT_LEVER_INVALID')):
        put(tmp_path / 'phase3/librelane_switch.json', {'placement_levers': bad})
        with pytest.raises(contract.Refusal, match=code):
            contract.placement_levers(tmp_path)


def test_a_density_lever_supersedes_the_declared_fraction(tmp_path, monkeypatch):
    """L19's PL_TARGET_DENSITY (a fraction LibreLane translates) and a lever's
    PL_TARGET_DENSITY_PCT together are a conflict; the lever wins, on record."""
    p = bridge._chip_design(tmp_path)
    put(p / 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json', {'fields': {
        'constraint_declarations': [{'token': 'PL_TARGET_DENSITY', 'value': '0.5',
                                     'scope': 'GF180MCU', 'source': 'L9', 'line': 1}]}})
    pdk_root = tmp_path / 'pdkroot'
    (pdk_root / 'gf180mcuD').mkdir(parents=True)
    monkeypatch.setattr(contract, 'image_capability', lambda *a: None)
    monkeypatch.setattr(contract.subprocess, 'run', _run_resolver_locally(
        _fake_librelane(tmp_path / 'fake')))
    base = contract.resolve_step_configs(p, 'img', 'gf180mcuD', ['OpenROAD.GlobalPlacement'],
                                         pdk_root=pdk_root, folder='a')
    assert json.loads(base['OpenROAD.GlobalPlacement'].read_text())['PL_TARGET_DENSITY_PCT'] == 50
    lever = contract.resolve_step_configs(
        p, 'img', 'gf180mcuD', ['OpenROAD.GlobalPlacement'], pdk_root=pdk_root, folder='b',
        overlay={'PL_TARGET_DENSITY_PCT': (65.0, 'switch placement_levers')})
    assert json.loads(lever['OpenROAD.GlobalPlacement'].read_text())['PL_TARGET_DENSITY_PCT'] == 65.0
    prov = json.loads((p / 'phase3/librelane/b/design.provenance.json').read_text())
    assert prov['PL_TARGET_DENSITY'].startswith('superseded by PL_TARGET_DENSITY_PCT')


def _full_deck():
    """The direct deck's shape around the step-17 seam (runner template order)."""
    m = runner._PNR_STAGE_MARKER
    return (f"read_lef /pdk/tech.lef\nread_lef /pdk/cells.lef\nread_liberty /pdk/tt.lib\n"
            f"read_verilog /work/core.v\n# chip top\nread_verilog /work/chip_top_io.v\n\n"
            f"link_design chip_top\nread_sdc /work/constraint.sdc\nset_wire_rc -signal -layer M2\n"
            f"{runner._PNR_RESUME_ELIDE_BEGIN}\n# Everything between this sentinel and ...\n"
            f"# checkpoint.\n"
            f'puts "{m} padring_ingest"\nread_def -floorplan_initialize /work/padring.def\n'
            f'puts "{m} placement"\nglobal_placement -density 0.3\n'
            f"write_def /work/placed.def\nplace_inst -name spare_inverter_0 -cell inv\n"
            f"detailed_placement\nrepair_design\n"
            f'puts "{m} cts"\nclock_tree_synthesis\nwrite_def /work/post_cts.def\n'
            f'puts "{m} detailed_route"\ndetailed_route\n'
            f"{runner._PNR_RESUME_ELIDE_END}\n"
            f'puts "{m} postroute_spef_extract"\nwrite_def /work/routed.def\n')


def test_the_direct_deck_resumes_at_cts_on_the_tools_placed_def():
    out = contract.placement_consumer_tcl(_full_deck(), '/work/placed.def',
                                          runner._PNR_STAGE_MARKER, 'AFTER_LOAD_STATE\n')
    # the tech/cell LEFs stay: CTS and route use the direct flow's own tech
    assert out.count('read_lef ') == 2 and 'read_liberty /pdk/tt.lib' in out
    assert 'read_verilog' not in out and 'link_design' not in out
    load = out.index('read_def /work/placed.def')
    assert out.index('read_liberty') < load < out.index('read_sdc')
    # floorplan..pre-CTS work is gone; the session state is restored first
    for gone in ('floorplan_initialize', 'global_placement', 'place_inst', 'repair_design'):
        assert gone not in out
    assert out.index('AFTER_LOAD_STATE') < out.index('clock_tree_synthesis')
    assert out.count(runner._PNR_RESUME_ELIDE_BEGIN) == 1
    assert out.index(runner._PNR_RESUME_ELIDE_BEGIN) < out.index('librelane_placement_ingest')
    assert out.endswith('write_def /work/routed.def\n')
    with pytest.raises(ValueError, match='LL_PLACEMENT_SEAM_AMBIGUOUS'):
        contract.placement_consumer_tcl(_full_deck() + _full_deck(), '/w/p.def',
                                        runner._PNR_STAGE_MARKER)
    with pytest.raises(ValueError, match='LL_PLACEMENT_SEAM_AMBIGUOUS'):
        contract.placement_consumer_tcl(_full_deck().replace('link_design', 'foo'),
                                        '/w/p.def', runner._PNR_STAGE_MARKER)


@pytest.mark.parametrize('odb', ['', '/work/ckpt.odb'])
def test_resume_and_sdr_decks_still_derive_from_the_placement_consumer(odb):
    deck = contract.placement_consumer_tcl(_full_deck(), '/work/placed.def',
                                           runner._PNR_STAGE_MARKER)
    tail = runner._build_pnr_resume_tcl_text(deck, checkpoint_def_c='/work/ckpt.def',
                                             restore_odb_c=odb)
    assert 'read_def /work/placed.def' not in tail
    assert ('read_db /work/ckpt.odb' if odb else 'read_def /work/ckpt.def') in tail
    assert ('read_lef' in tail) == (not odb)
    assert 'clock_tree_synthesis' not in tail and 'write_def /work/routed.def' in tail


# ============================================================== runner ====

def test_step18_follows_step17_unless_named(tmp_path):
    assert runner._librelane_placement_modes(tmp_path) == {'17': 'direct', '18': 'direct'}
    put(tmp_path / 'phase3/librelane_switch.json', {'steps': {'17': 'librelane'}})
    assert runner._librelane_placement_modes(tmp_path) == {'17': 'librelane', '18': 'librelane'}
    put(tmp_path / 'phase3/librelane_switch.json', {'steps': {'17': 'librelane', '18': 'direct'}})
    assert runner._librelane_placement_modes(tmp_path) == {'17': 'librelane', '18': 'direct'}


def _neutral_step7_sdc(project):
    """Current Step-7 reader output for placement-switch seam controls."""
    path = project / 'phase2/stage2/constraints/dut.asic.sdc'
    path.parent.mkdir(parents=True, exist_ok=True)
    text = 'create_clock -period 10 [get_ports clk]\n'
    path.write_text(text)
    return {'text': text, 'path': str(path), 'step7_sha256': 'source-control',
            'deck_sha256': 'source-control', 'regenerated': None,
            'derivation': None}


@pytest.mark.parametrize('steps,code', [
    ({'17': 'librelane'}, 'LL_PLACEMENT_NEEDS_LIBRELANE_FLOORPLAN'),
    ({'15': 'librelane', '15.5ic': 'librelane', '17': 'librelane', '18': 'direct'},
     'LL_SPARE_PLACEMENT_SPLIT_UNSUPPORTED'),
    ({'17': 'dual'}, 'LL_PLACEMENT_NEEDS_LIBRELANE_FLOORPLAN'),
])
def test_the_placement_switch_refuses_by_name_and_never_runs_direct(tmp_path, monkeypatch,
                                                                     steps, code):
    import test_pad_connected_pdn_ring as ring_fixture
    project = tmp_path / 'proj'
    project.mkdir(parents=True)
    put(project / 'phase3/librelane_switch.json', {'steps': steps})
    pdk = ring_fixture._pdk(tmp_path, ring=None)
    netlist = write(tmp_path / 'dut.v', 'module dut(input clk, output q); assign q=clk; endmodule\n')

    def must_not(*_a, **_k):  # pragma: no cover
        raise AssertionError('a producer ran')
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
            '_build_pnr_tcl_text': lambda **k: bridge._deck(),
            '_prepare_padring_for_route': must_not,
            '_prepare_librelane_floorplan_for_route': must_not}.items():
        monkeypatch.setattr(runner, name, value)
    monkeypatch.setattr(runner._ppa_timing, 'asic_sdc_for_pnr',
                        lambda *_: _neutral_step7_sdc(project))
    result = runner.step_pnr(project, 'dut', pdk, 'unused', '400x400', 0.4)
    assert result.status == 'FAIL' and code in result.detail
    assert result.extras['finding'] == code


def test_step17_on_librelane_passes_the_step18_plan_to_the_producer(tmp_path, monkeypatch):
    import test_pad_connected_pdn_ring as ring_fixture
    project = tmp_path / 'proj'
    project.mkdir(parents=True)
    put(project / 'phase3/librelane_switch.json',
        {'steps': {'15': 'librelane', '15.5ic': 'librelane', '17': 'librelane'}})
    pdk = ring_fixture._pdk(tmp_path, ring=None)
    netlist = write(tmp_path / 'dut.v', 'module dut(input clk, output q); assign q=clk; endmodule\n')
    seen = {}

    def producer(*a, **k):
        seen['placement'] = k.get('placement')
        return runner.StepResult('pad_ring_gen', 'FAIL', 0.0, 'stop here'), None
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
            '_build_pnr_tcl_text': lambda **k: bridge._deck(),
            '_prepare_librelane_floorplan_for_route': producer}.items():
        monkeypatch.setattr(runner, name, value)
    monkeypatch.setattr(runner._ppa_timing, 'asic_sdc_for_pnr',
                        lambda *_: _neutral_step7_sdc(project))
    runner.step_pnr(project, 'dut', pdk, 'unused', '400x400', 0.4, spare_density=0.05)
    placement = seen['placement']
    assert placement is not None
    assert placement['spare_plan']['density'] == 0.05
    # direct: absent 17 -> no placement handed to the producer
    put(project / 'phase3/librelane_switch.json', {'steps': {'15': 'librelane', '15.5ic': 'librelane'}})
    runner.step_pnr(project, 'dut', pdk, 'unused', '400x400', 0.4)
    assert seen['placement'] is None


def _ll_deck():
    """The generic deck's order: load, sentinel, floorplan, taps/PDN, placement, CTS."""
    m = runner._PNR_STAGE_MARKER
    return ("read_lef /pdk/core.lef\nread_verilog /work/netlist.v\nlink_design core\n"
            f"read_sdc /work/c.sdc\n{runner._PNR_RESUME_ELIDE_BEGIN}\n# builds the design\n"
            f'puts "{m} floorplan"\ninitialize_floorplan -die_area "0 0 100 100" \\\n'
            "  -core_area \"10 10 90 90\" -site unit\n"
            "write_def /work/phase3/stage3/pnr/floorplan.def\n"
            "tapcell -distance 15\npdngen\n"
            f'puts "{m} placement"\nglobal_placement\nplace_inst -name spare_inverter_0\n'
            f'puts "{m} cts"\nclock_tree_synthesis\n'
            f'puts "{m} global_route"\nglobal_route\ndetailed_route\n'
            f"{runner._PNR_RESUME_ELIDE_END}\n")


def _placement_producer(tmp_path, monkeypatch, *, spare_record=True,
                        liberty_text='library(x) {\n cell (lib__buf_1) { }\n}\n'):
    project = tmp_path / 'project'
    out_dir = project / 'phase3/stage3/pnr'
    wrapper = write(out_dir / 'chip_top_io.v', 'module chip_top(a);\n  input a;\n  core u_core (.a(a));\nendmodule\n')
    netlist = write(project / 'phase3/stage2/core.v', 'module core(a);\n  input a;\nendmodule\n')
    put(project / 'phase3/librelane_switch.json', {
        'steps': {'15': 'librelane', '15.5ic': 'librelane', '17': 'librelane'},
        'pdk_root_host': str(tmp_path / 'pdkroot'),
        'placement_levers': {'PL_TIMING_DRIVEN': True}})
    write(tmp_path / 'pdkroot/probe_pdk/libs.ref/active.lib', liberty_text)
    monkeypatch.setattr(runner, '_padring_chip_top_record', lambda p: {
        'core_module': 'core', 'chip_top_module': 'chip_top',
        'chip_top_verilog': str(wrapper.relative_to(project))})
    monkeypatch.setattr(runner, 'pnr_input_netlist', lambda p, core: (netlist, 'n', False))
    monkeypatch.setattr(runner, '_docker_exec', lambda *a, **k: (0, 'ok', ''))
    segment = ['OpenROAD.Floorplan', 'OpenROAD.PadRing', 'Odb.RemovePDNObstructions',
               'OpenROAD.GlobalPlacement', 'OpenROAD.RepairDesignPostGPL',
               'OpenROAD.DetailedPlacement']
    monkeypatch.setattr(contract, 'flow_segment', lambda image, first, last, **k: (
        segment[:segment.index(last) + 1]))
    seen = {}

    def resolve(project, image, pdk, step_ids, **k):
        seen['overlay'] = k.get('overlay')
        out = {}
        for s in step_ids:
            path = bridge._declared(tmp_path, s)
            doc = json.loads(path.read_text())
            if s.startswith('OpenROAD.'):
                doc.update(CELL_LIBS={'nom': ['/pdk/probe_pdk/libs.ref/active.lib']},
                           EXTRA_EXCLUDED_CELLS=[])
            out[s] = put(path, doc)
        return out
    monkeypatch.setattr(contract, 'resolve_step_configs', resolve)
    monkeypatch.setattr(contract, 'emit_pdn_cfg', lambda image, pdk, out, **k: None)

    def chain(project, image, triples, **k):
        seen['steps'] = [t[0] for t in triples]
        seen['configs'] = {step: cfg for step, cfg, _ in triples}
        folders = []
        for step, _cfg, _st in triples:
            f = project / 'phase3/librelane/15-floorplan' / step
            text = bridge.DEF_TEXT.replace('END DESIGN', f'# {step}\nEND DESIGN')
            put(f / 'state_out.json', {'def': str(write(f / 'chip_top.def', text)),
                                       'odb': str(write(f / 'chip_top.odb', step))})
            write(f / f'{step}.log', f'{step} tool log\n')
            write(f / 'invocation.log', 'wrapper\n')
            if step == 'Vibeic.InsertSpareCells' and spare_record:
                write(f / f'{step}.log', 'SPARE_TIEOFF_CONNECTED 2 of 2\n'
                                         'SPARE_CHECK_PLACEMENT_VIOLATIONS 0\n')
                put(f / 'spare_cells.json', {'instances': [
                    {'name': 'spare_inverter_0', 'llx': 12.5, 'lly': 20.16,
                     'planned_llx': 12, 'planned_lly': 20}],
                    'measured': {'check_placement_violations': 0}})
            folders.append(f)
        return folders
    monkeypatch.setattr(contract, 'run_chain', chain)
    monkeypatch.setattr(runner._pr, 'run', lambda *a, **k: SimpleNamespace(
        returncode=0, stdout='PASS', stderr=''))
    pdk = bridge._pdk(tmp_path)
    pdk.macro_lefs, pdk.macro_gds = [], []
    plan = {'instances': [{'name': 'spare_inverter_0', 'cell': 'inv', 'llx': 12, 'lly': 20}]}
    result, consumer = runner._prepare_librelane_floorplan_for_route(
        project, pdk, 'c', out_dir, _ll_deck(),
        {'15': 'librelane', '15.5ic': 'librelane'},
        io_view_discover=lambda *a: ([], []),
        placement={'spare_plan': plan, 'tie_lo': 'tiel/ZN'})
    return project, out_dir, seen, result, consumer, plan


def test_step17_continues_the_step15_chain_through_the_spare_step(tmp_path, monkeypatch):
    project, out_dir, seen, result, consumer, plan = _placement_producer(tmp_path, monkeypatch)
    assert result.status == 'PASS', result.detail
    # The first placement repair can create over-limit first-level buffers.
    # Close those with the same SDC before the tool's final placement and spares.
    assert seen['steps'][-4:] == ['OpenROAD.RepairDesignPostGPL',
                                  'Vibeic.PostGPLFanoutClosure',
                                  'OpenROAD.DetailedPlacement',
                                  'Vibeic.InsertSpareCells']
    # declared inputs only: the runner's plan, its tie cell, the switch levers
    ov = seen['overlay']
    plan_path, plan_src = ov['VIBEIC_SPARE_PLAN']
    assert json.loads(Path(plan_path).read_text()) == plan and '--spare-density' in plan_src
    assert ov['VIBEIC_SPARE_TIELO_CELL'][0] == 'tiel/ZN'
    assert ov['PL_TIMING_DRIVEN'] == (True, 'phase3/librelane_switch.json placement_levers.PL_TIMING_DRIVEN')
    # handoff: floorplan from RemovePDNObstructions, placement from the final state
    assert '# Odb.RemovePDNObstructions' in (out_dir / 'floorplan.def').read_text()
    assert '# Vibeic.InsertSpareCells' in (out_dir / 'placed.def').read_text()
    receipt = json.loads((project / 'reports/phase3/librelane_placement_handoff.json').read_text())
    assert receipt['views']['def']['dest_sha256'] == contract.digest(out_dir / 'placed.def')
    # the tool verdicts land where the existing readers look
    assert 'OpenROAD.DetailedPlacement tool log' in (out_dir / 'librelane_placement.log').read_text()
    spare_log = (out_dir / 'librelane_spare_cells.log').read_text()
    assert 'SPARE_CHECK_PLACEMENT_VIOLATIONS 0' in spare_log and 'wrapper' not in spare_log
    assert (out_dir / 'librelane_spare_cells.json').is_file()
    # the deck: the tool's placed DEF, then CTS; no direct placement work
    assert 'read_def ' + str(out_dir / 'placed.def') in consumer
    assert 'global_placement' not in consumer and 'floorplan_initialize' not in consumer
    assert 'set_dont_touch spare_inverter_0' in consumer
    assert 'spare_tielo_spare_inverter_0' in consumer and 'setDoNotTouch true' in consumer
    assert 'librelane_placement_handoff.json' in result.detail


def test_the_spare_record_carries_what_the_step_measured(tmp_path):
    plan = {'instances': [{'name': 'spare_inverter_0', 'llx': 12, 'lly': 20},
                          {'name': 'spare_nand2_0', 'llx': 40, 'lly': 20}]}
    record = put(tmp_path / 'r.json', {'instances': [
        {'name': 'spare_inverter_0', 'llx': 12.5, 'lly': 20.16, 'planned_llx': 12,
         'planned_lly': 20}], 'measured': {'check_placement_violations': 0}})
    runner._merge_librelane_spare_record(plan, record)
    assert plan['instances'][0]['llx'] == 12.5 and plan['instances'][0]['planned_llx'] == 12
    assert plan['instances'][1] == {'name': 'spare_nand2_0', 'llx': 40, 'lly': 20}
    assert plan['librelane_measured'] == {'check_placement_violations': 0}
    assert plan['producer'] == 'Vibeic.InsertSpareCells'
    untouched = {'instances': [{'name': 'x', 'llx': 1}]}
    runner._merge_librelane_spare_record(untouched, tmp_path / 'absent.json')
    assert untouched == {'instances': [{'name': 'x', 'llx': 1}]}


def test_step18_evidence_is_read_from_the_custom_steps_log(tmp_path):
    """The spare markers live in the LibreLane step's log, not the direct session's."""
    out_dir = tmp_path / 'phase3/stage3/pnr'
    ll_log = write(out_dir / 'librelane_spare_cells.log',
                   'SPARE_TIEOFF_CONNECTED 2 of 2\nSPARE_FIRM_LOCKED: 1 instances\n'
                   'SPARE_CHECK_PLACEMENT_VIOLATIONS 0\n')
    plan = {'instances': [{'name': 'spare_inverter_0', 'cell': 'inv', 'llx': 1, 'lly': 1}]}
    note, written = runner._emit_step18_spare_record(tmp_path, out_dir, ll_log, plan, 50,
                                                     0.02, '')
    assert written, note
    doc = json.loads((out_dir / 'spare_cells.json').read_text())
    assert doc['tied_off'] is True and doc['insertion_observed']['observed'] is True


def test_the_step18_record_site_selects_the_librelane_log():
    src = Path(runner.__file__).read_text()
    site = src[src.index('spare_note, _spare_record_written = _emit_step18_spare_record('):]
    site = site[:site.index('except Exception as _s18_exc')]
    assert 'librelane_spare_cells.log' in site and '_ll_pl_modes["18"] != "direct"' in site
    assert 'LIBRELANE_PLACEMENT_CONSUMED' in site   # only when the tool's placement was consumed


def test_the_runner_and_the_custom_step_build_one_plan():
    """Ported, not copied: the runner's names bind to `_spare_plan`."""
    assert runner._compute_spare_density is sp.compute_spare_density
    assert runner._spare_grid_positions is sp.spare_grid_positions
    cells = ['lib__inv_1', 'lib__nand2_1', 'lib__nor2_1', 'lib__mux2_1', 'lib__a21oi_1',
             'lib__o21ai_1', 'lib__dffq_1', 'lib__dffrnq_1']
    cmap = sp.discover_spare_cells(cells, used_cells={'lib__dffq_1'})
    assert cmap['dff'] == 'lib__dffrnq_1'           # an unused variant is preferred
    plan = sp.build_spare_cells_plan(300, 0.02, (0, 0, 100, 100), cmap, has_pad_ring=True)
    assert plan['count'] == 6 and sum(plan['types'].values()) == 6
    assert plan['instances'][0]['name'] == 'spare_inverter_0'
    assert plan['spare_pads'] and plan['tied_off'] is False
    box = (0, 0, 100, 100)
    assert runner._build_spare_cells_plan(300, 0.02, box, has_pad_ring=True) == \
        sp.build_spare_cells_plan(300, 0.02, box, {}, has_pad_ring=True)


# ======================================================= the custom step ====

class _MTerm:
    def __init__(self, name, sig, io):
        self.name, self.sig, self.io = name, sig, io

    def getName(self):
        return self.name


class _ITerm:
    def __init__(self, inst, mterm):
        self.inst, self.mterm, self.net = inst, mterm, None

    def getMTerm(self):
        return self.mterm

    def getSigType(self):
        return self.mterm.sig

    def isInputSignal(self):
        return self.mterm.sig == 'SIGNAL' and self.mterm.io == 'INPUT'

    def getNet(self):
        return self.net

    def connect(self, net):
        if self.inst.dnt:
            raise RuntimeError('ODB-0369 dont_touch')
        self.net = net


_PINS = {'inv': [('I', 'SIGNAL', 'INPUT'), ('ZN', 'SIGNAL', 'OUTPUT'),
                 ('VDD', 'POWER', 'INOUT'), ('VSS', 'GROUND', 'INOUT')],
         'nand2': [('A1', 'SIGNAL', 'INPUT'), ('A2', 'SIGNAL', 'INPUT'),
                   ('ZN', 'SIGNAL', 'OUTPUT'), ('VDD', 'POWER', 'INOUT'),
                   ('VSS', 'GROUND', 'INOUT')],
         'tiel': [('ZN', 'SIGNAL', 'OUTPUT'), ('VDD', 'POWER', 'INOUT'),
                  ('VSS', 'GROUND', 'INOUT')],
         'tap': [('VDD', 'POWER', 'INOUT'), ('VSS', 'GROUND', 'INOUT')],
         'pad': [('PAD', 'SIGNAL', 'INOUT')]}
_TYPES = {'inv': 'CORE', 'nand2': 'CORE', 'tiel': 'CORE_TIELOW', 'tap': 'CORE_WELLTAP',
          'pad': 'PAD_INPUT'}


class _Master:
    def __init__(self, name):
        self.name = name

    def getName(self):
        return self.name

    def getType(self):
        return _TYPES[self.name]


class _Inst:
    def __init__(self, block, master, name):
        self.block, self.master, self.name = block, master, name
        self.loc, self.status, self.dnt, self.orient = (0, 0), 'NONE', False, None
        self.iterms = [_ITerm(self, _MTerm(*p)) for p in _PINS[master.name]]

    def getName(self):
        return self.name

    def getMaster(self):
        return self.master

    def getITerms(self):
        return self.iterms

    def findITerm(self, pin):
        return next((i for i in self.iterms if i.mterm.name == pin), None)

    def setOrient(self, o):
        self.orient = o

    def setLocation(self, x, y):
        self.loc = (x, y)

    def getLocation(self):
        return self.loc

    def setPlacementStatus(self, s):
        self.status = s

    def getPlacementStatus(self):
        return self.status

    def setDoNotTouch(self, v):
        self.dnt = v


class _Net:
    def __init__(self, name, sig='SIGNAL'):
        self.name, self.sig, self.dnt = name, sig, False

    def getName(self):
        return self.name

    def getSigType(self):
        return self.sig

    def setDoNotTouch(self, v):
        self.dnt = v


class _Rect:
    def xMin(self):
        return 0

    def yMin(self):
        return 0

    def xMax(self):
        return 100000

    def yMax(self):
        return 100000


class _Site:
    def getWidth(self):
        return 560

    def getHeight(self):
        return 3920


class _Block:
    def __init__(self, rules=()):
        self.insts, self.nets, self.rules = {}, {}, list(rules)

    def getInsts(self):
        return list(self.insts.values())

    def findInst(self, n):
        return self.insts.get(n)

    def findNet(self, n):
        return self.nets.get(n)

    def getDbUnitsPerMicron(self):
        return 1000

    def getCoreArea(self):
        return _Rect()

    def getRows(self):
        return [SimpleNamespace(getSite=lambda: _Site())]

    def getGlobalConnects(self):
        return [SimpleNamespace(getNet=lambda n=n: n, getInstPattern=lambda i=i: i,
                                getPinPattern=lambda p=p: p) for n, i, p in self.rules]


class _Dpl:
    def __init__(self, block):
        self.block, self.moved = block, []

    def setPaddingGlobal(self, *_):
        pass

    def detailedPlacement(self, *_):
        movable = [i.name for i in self.block.getInsts() if i.status != 'LOCKED']
        self.moved.append(movable)
        for i in self.block.getInsts():
            if i.name in movable:
                i.loc = (i.loc[0] + 60, i.loc[1])     # the legal site next door


def _odbpy(monkeypatch, *, check='0', rules=True):
    block = _Block()
    vdd, vss = _Net('VDD', 'POWER'), _Net('VSS', 'GROUND')
    block.nets.update(VDD=vdd, VSS=vss)
    if rules:
        block.rules = [(vdd, '.*', '^VDD$'), (vss, '.*', '^VSS$')]
    masters = {n: _Master(n) for n in _PINS}
    db = SimpleNamespace(findMaster=lambda n: masters.get(n),
                         getLibs=lambda: [SimpleNamespace(getMasters=lambda: list(masters.values()))])

    def create_inst(blk, master, name):
        blk.insts[name] = _Inst(blk, master, name)
        return blk.insts[name]

    def create_net(blk, name):
        blk.nets[name] = _Net(name)
        return blk.nets[name]
    odb = SimpleNamespace(dbInst=SimpleNamespace(create=create_inst),
                          dbNet=SimpleNamespace(create=create_net))
    for i, m in enumerate(('inv', 'tap', 'pad')):
        create_inst(block, masters[m], f'u{i}').status = 'PLACED'
    import click
    fake_reader = types.ModuleType('reader')
    fake_reader.click, fake_reader.odb = click, odb
    fake_reader.click_odb = lambda f: f
    monkeypatch.setitem(sys.modules, 'reader', fake_reader)
    monkeypatch.syspath_prepend(str(PLUGIN))
    monkeypatch.delitem(sys.modules, 'insert_spare_cells', raising=False)
    mod = importlib.import_module('insert_spare_cells')
    dpl = _Dpl(block)
    tcl = []
    design = SimpleNamespace(getOpendp=lambda: dpl,
                             evalTclString=lambda c: tcl.append(c) or (check if 'check' in c else ''))
    reader = SimpleNamespace(block=block, db=db, design=design, config=None)
    return mod, reader, dpl, tcl


def test_the_step_ties_protects_supplies_and_measures_each_spare(monkeypatch, capsys):
    mod, reader, dpl, tcl = _odbpy(monkeypatch)
    plan = {'instances': [{'name': 'spare_inverter_0', 'cell': 'inv', 'llx': 10, 'lly': 20},
                          {'name': 'spare_nand2_0', 'cell': 'nand2', 'llx': 50, 'lly': 20},
                          {'name': 'spare_mux2_0', 'cell': 'mux_absent', 'llx': 5, 'lly': 5}]}
    measured = mod.insert(reader, {'VIBEIC_SPARE_TIELO_CELL': 'tiel/ZN'}, plan)
    out = capsys.readouterr().out
    blk = reader.block
    inv, nand = blk.findInst('spare_inverter_0'), blk.findInst('spare_nand2_0')
    # legalization moved ONLY the spares, then only the tie drivers
    assert dpl.moved == [['spare_inverter_0', 'spare_nand2_0'],
                         ['spare_tielo_spare_inverter_0_drv', 'spare_tielo_spare_nand2_0_drv']]
    assert blk.findInst('u0').status == 'PLACED'          # restored after the lock
    # one tie driver per spare, on that spare's own net
    assert {i.getNet().getName() for i in nand.iterms if i.isInputSignal()} == \
        {'spare_tielo_spare_nand2_0'}
    assert blk.findInst('spare_tielo_spare_nand2_0_drv').findITerm('ZN').getNet() is \
        blk.findNet('spare_tielo_spare_nand2_0')
    assert measured['tieoff_candidates'] == 3 and measured['tieoff_connected'] == 3
    # supplies connected explicitly, BEFORE dont_touch (odb refuses after)
    for inst in (inv, nand, blk.findInst('spare_tielo_spare_inverter_0_drv')):
        assert {i.mterm.name: i.getNet().getName() for i in inst.iterms
                if i.getSigType() != 'SIGNAL'} == {'VDD': 'VDD', 'VSS': 'VSS'}
    assert measured['pg_unconnected'] == 0 and measured['pg_connected'] == 8
    assert inv.dnt and inv.status == 'FIRM' and blk.findNet('spare_tielo_spare_inverter_0').dnt
    assert measured['check_placement_violations'] == 0
    assert tcl == ['check_placement -no_abort']
    # the runner's readers consume exactly these markers
    for marker in ('SPARE_INSERT_NONFATAL spare_mux2_0', 'SPARE_TIEOFF_CONNECTED 3 of 3',
                   'SPARE_TIEOFF_DRIVERS 2', 'SPARE_FIRM_LOCKED: 2 instances',
                   'SPARE_CHECK_PLACEMENT_VIOLATIONS 0', 'SPARE_PG_CONNECTED 8 of 8'):
        assert marker in out
    # where each spare actually legalized, beside where it was planned
    assert plan['instances'][0]['llx'] == 10.06 and plan['instances'][0]['planned_llx'] == 10


def test_without_global_connect_rules_the_configs_scl_pins_decide(monkeypatch):
    mod, reader, _dpl, _tcl = _odbpy(monkeypatch, rules=False)
    plan = {'instances': [{'name': 'spare_inverter_0', 'cell': 'inv', 'llx': 1, 'lly': 1}]}
    m = mod.insert(reader, {'SYNTH_TIELO_CELL': 'tiel/ZN', 'SCL_POWER_PINS': ['VDD'],
                            'SCL_GROUND_PINS': ['VSS'], 'VDD_NETS': ['VDD'],
                            'GND_NETS': ['VSS']}, plan)
    assert m['pg_unconnected'] == 0 and m['pg_connected'] == 4
    bare_mod, bare, _d, _t = _odbpy(monkeypatch, rules=False)
    m = bare_mod.insert(bare, {'SYNTH_TIELO_CELL': 'tiel/ZN'}, {'instances': [
        {'name': 'spare_inverter_0', 'cell': 'inv', 'llx': 1, 'lly': 1}]})
    assert m['pg_unconnected'] == 4                     # nothing invented


def test_no_tie_cell_and_an_unreadable_count_are_said_not_guessed(monkeypatch, capsys):
    mod, reader, _dpl, _tcl = _odbpy(monkeypatch, check='oops')
    m = mod.insert(reader, {}, {'instances': [
        {'name': 'spare_inverter_0', 'cell': 'inv', 'llx': 1, 'lly': 1}]})
    out = capsys.readouterr().out
    assert 'SPARE_TIEOFF_SKIPPED: no tie-low cell' in out
    assert m['tieoff_candidates'] == 0 and m['tieoff_drivers'] == 0
    assert m['check_placement_violations'] is None
    assert "SPARE_CHECK_PLACEMENT_UNAVAILABLE: non-numeric result 'oops'" in out


def test_the_step_builds_the_same_plan_from_the_placed_database(monkeypatch):
    mod, reader, _dpl, _tcl = _odbpy(monkeypatch)
    for i in range(99):
        reader.block.insts[f'l{i}'] = _Inst(reader.block, _Master('nand2'), f'l{i}')
    plan = mod.plan_from_block(reader.block, reader.db, 0.02)
    # 100 logic cells (u0 inv + 99 nand2); taps and pads are not logic
    expected = sp.build_spare_cells_plan(
        100, 0.02, (0, 0, 100, 100), sp.discover_spare_cells(list(_PINS), {'inv', 'nand2'}),
        has_pad_ring=True, used_cells={'inv', 'nand2'})
    assert plan == expected and plan['count'] == 2


def test_the_step_cli_prefers_the_callers_plan(monkeypatch, tmp_path):
    mod, reader, _dpl, tcl = _odbpy(monkeypatch)
    plan = put(tmp_path / 'plan.json', {'count': 1, 'instances': [
        {'name': 'spare_inverter_0', 'cell': 'inv', 'llx': 1, 'lly': 1}]})
    reader.config = {'VIBEIC_SPARE_PLAN': str(plan), 'SYNTH_TIELO_CELL': 'tiel/ZN'}
    report = tmp_path / 'spare_cells.json'
    mod.cli.callback(reader=reader, report_path=str(report), output_nl='/o/nl.v',
                     output_pnl='/o/pnl.v')
    doc = json.loads(report.read_text())
    assert doc['plan_source'].startswith('VIBEIC_SPARE_PLAN') and doc['tied_off'] is True
    assert doc['measured']['inserted'] == 1
    assert 'write_verilog {/o/nl.v}' in tcl and 'write_verilog -include_pwr_gnd {/o/pnl.v}' in tcl
    mod2, reader2, _d, _t = _odbpy(monkeypatch)
    reader2.config = {'VIBEIC_SPARE_DENSITY': '0.02'}
    mod2.cli.callback(reader=reader2, report_path=str(report), output_nl='/o/a',
                      output_pnl='/o/b')
    assert json.loads(report.read_text())['plan_source'].startswith('built in-step')


# ================================================================ gates ====

def _placed_project(tmp_path, *, tamper=False, dpl_done=True):
    project = tmp_path / 'p'
    chain = project / 'phase3/librelane/15-floorplan'
    placed_def = ('VERSION 5.8 ;\nDESIGN chip_top ;\nCOMPONENTS 2 ;\n'
                  '    - u0 inv + PLACED ( 0 0 ) N ;\n    - s0 inv + FIXED ( 10 0 ) N ;\n'
                  'END COMPONENTS\nEND DESIGN\n')
    for step, folder in (('OpenROAD.DetailedPlacement', '22-openroad-detailedplacement'),
                         ('Vibeic.InsertSpareCells', '23-vibeic-insertsparecells')):
        put(chain / folder / 'vibeic_receipt.json', {'input': {'step': step}})
        if dpl_done or step != 'OpenROAD.DetailedPlacement':
            put(chain / folder / 'state_out.json', {'def': str(chain / folder / 'x.def')})
    state = chain / '23-vibeic-insertsparecells/state_out.json'
    write(chain / '23-vibeic-insertsparecells/x.def', placed_def)
    out = project / 'phase3/stage3/pnr'
    contract.handoff_to_direct(state, {'def': out / 'placed.def'},
                               project / 'reports/phase3/librelane_placement_handoff.json')
    write(out / 'librelane_spare_cells.log', 'SPARE_CHECK_PLACEMENT_VIOLATIONS 0\n')
    if tamper:
        write(out / 'placed.def', placed_def.replace('( 10 0 )', '( 11 0 )'))
    return project


def _legality(project):
    r = subprocess.run([sys.executable, str(PROGRAMS / 'placement_legality_check.py'),
                        str(project), '--json', str(project / 'out.json')],
                       capture_output=True, text=True)
    return r.returncode, json.loads((project / 'out.json').read_text())


def test_legality_reads_the_tools_placement_bound_by_sha(tmp_path):
    rc, doc = _legality(_placed_project(tmp_path / 'a'))
    rules = {f['rule'] for f in doc['findings']}
    assert rc == 0 and 'LIBRELANE_DETAILED_PLACEMENT_CLEAN' in rules
    assert doc['placer_legality_verdict'] == 'LEGAL'
    assert doc['librelane_placement']['detailed_placement'] == 'COMPLETED'
    rc, doc = _legality(_placed_project(tmp_path / 'b', tamper=True))
    assert rc == 1 and 'LIBRELANE_PLACEMENT_UNBOUND' in {f['rule'] for f in doc['findings']}
    rc, doc = _legality(_placed_project(tmp_path / 'c', dpl_done=False))
    assert rc == 1 and 'LIBRELANE_DETAILED_PLACEMENT_NOT_CLEAN' in {
        f['rule'] for f in doc['findings']}


def test_legality_on_the_direct_path_is_unchanged(tmp_path):
    project = tmp_path / 'p'
    write(project / 'phase3/stage3/pnr/placed.def',
          'VERSION 5.8 ;\nDESIGN d ;\nCOMPONENTS 1 ;\n    - u0 inv + PLACED ( 0 0 ) N ;\n'
          'END COMPONENTS\nEND DESIGN\n')
    rc, doc = _legality(project)
    assert rc == 0 and doc['librelane_placement'] is None
    assert not any(f['rule'].startswith('LIBRELANE') for f in doc['findings'])


def _clock_project(tmp_path, monkeypatch=None, *, port='clk', net=None,
                   cts=None, sdc=None):
    project = tmp_path / 'p'
    sdc_text = sdc or 'create_clock -name clk -period 24 [get_ports clk]\n'
    write(project / 'phase3/stage3/pnr/constraint.sdc', sdc_text)
    put(project / 'phase3/stage3/cts/clock_plan.json', {'clocks': [
        {'name': 'clk', 'period_ns': 24, 'source': 'clk'}]})
    if port is not False:
        put(project / 'phase3/librelane/15-config/OpenROAD.CTS.json',
            {'CLOCK_PORT': port, 'CLOCK_NET': net, 'meta': {'step': 'OpenROAD.CTS'}})
        put(project / 'phase3/librelane/15-config/design.json', {'CLOCK_PORT': 'other'})
    if cts is not None:
        write(project / 'phase3/stage3/cts/clock_tree.rpt', cts)
    if monkeypatch is not None:
        current_fixture(monkeypatch, project, sdc_text, preserve_plan=True)
    return project


def _clock_gate(project):
    r = subprocess.run([sys.executable, str(PROGRAMS / 'clock_plan_check.py'), str(project),
                        '--json', str(project / 'cp.json')], capture_output=True, text=True)
    doc = json.loads((project / 'cp.json').read_text())
    return r.returncode, {(f['severity'], f['rule']) for f in doc['findings']}


_CAL = PROGRAMS / 'calibration'


def test_the_gate_refuses_an_sdc_clock_librelane_is_not_given(tmp_path, monkeypatch):
    rc, rules = _clock_gate(_clock_project(tmp_path / 'ok', monkeypatch))
    assert rc == 0 and ('INFO', 'LIBRELANE_CLOCKS_MATCH_SDC') in rules
    rc, rules = _clock_gate(_clock_project(tmp_path / 'net', monkeypatch,
                                            port=[], net='clk'))
    assert rc == 0 and ('INFO', 'LIBRELANE_CLOCKS_MATCH_SDC') in rules
    rc, rules = _clock_gate(_clock_project(tmp_path / 'unset', monkeypatch,
                                            port=None))
    assert rc == 1 and ('FAIL', 'LIBRELANE_CLOCK_MISSING') in rules
    rc, rules = _clock_gate(_clock_project(tmp_path / 'extra', monkeypatch,
                                            port=['clk', 'clk_b']))
    assert rc == 1 and ('FAIL', 'LIBRELANE_CLOCK_UNCONSTRAINED') in rules


def test_the_gate_refuses_an_sdc_clock_cts_never_took_up(tmp_path, monkeypatch):
    sdc = (_CAL / 'cal_two_clocks.sdc').read_text()
    plan = [{'name': 'clk', 'period_ns': 20, 'source': 'clk'},
            {'name': 'clk2', 'period_ns': 30, 'source': 'clk2'}]
    seen = _clock_project(tmp_path / 'seen', monkeypatch, port=False, sdc=sdc,
                          cts=(_CAL / 'cts_clock_roots_seen_negative.log').read_text())
    current_record = json.loads(
        (seen / 'phase3/stage3/cts/clock_plan.json').read_text())['current']
    put(seen / 'phase3/stage3/cts/clock_plan.json',
        {'clocks': plan, 'current': current_record})
    rc, rules = _clock_gate(seen)
    assert rc == 0 and ('INFO', 'CTS_CLOCKS_SEEN') in rules
    dropped = _clock_project(tmp_path / 'dropped', monkeypatch, port=False, sdc=sdc,
                             cts=(_CAL / 'cts_clock_root_dropped_positive.log').read_text())
    current_record = json.loads(
        (dropped / 'phase3/stage3/cts/clock_plan.json').read_text())['current']
    put(dropped / 'phase3/stage3/cts/clock_plan.json',
        {'clocks': plan, 'current': current_record})
    rc, rules = _clock_gate(dropped)
    assert rc == 1 and ('FAIL', 'CTS_CLOCK_MISSING') in rules


def test_without_a_tool_side_the_gate_is_unchanged(tmp_path, monkeypatch):
    rc, rules = _clock_gate(_clock_project(tmp_path, monkeypatch, port=False))
    assert rc == 0 and not any(r.startswith(('LIBRELANE', 'CTS_')) for _s, r in rules)


def test_the_producer_invents_no_clock(tmp_path, monkeypatch):
    project = tmp_path / 'p'
    write(project / 'phase3/stage3/pnr/routed.def', 'VERSION 5.8 ;\nEND DESIGN\n')
    notes = []
    plan = project / 'phase3/stage3/cts/clock_plan.json'
    assert runner.emit_clock_plan(project, plan, project / 'phase3/stage3/pnr/routed.def',
                                  project / 'phase3/stage3/pnr', notes) is None
    assert not plan.exists() and 'no nominal clock is invented' in notes[-1]
    write(project / 'phase3/stage3/pnr/constraint.sdc',
          'create_clock -name core -period 7 [get_ports ck]\n')
    current_fixture(monkeypatch, project,
                    'create_clock -name core -period 7 [get_ports ck]\n',
                    publish=False)
    assert runner.emit_clock_plan(project, plan, project / 'phase3/stage3/pnr/routed.def',
                                  project / 'phase3/stage3/pnr', notes)
    doc = json.loads(plan.read_text())
    assert doc['clocks'] == [{'name': 'core', 'period_ns': 7.0, 'source': 'ck'}]
    assert 'buf_strategy' not in doc


# ================================================================== PPA ====

def test_placement_levers_are_admitted_only_when_the_producer_reads_them():
    import ppa_pnr_search_space as P
    runner_src = Path(runner.__file__).read_text()
    contract_src = Path(contract.__file__).read_text()
    switch = P.switch_levers(contract_src, runner_src)
    assert set(switch) == {P.SWITCH_PREFIX + k for k in contract.PLACEMENT_LEVERS}
    lines = contract_src.splitlines()
    for lit, line in switch.items():
        assert repr(lit[len(P.SWITCH_PREFIX):]) in lines[line - 1]
    unread = runner_src.replace('_ll.placement_levers(project)', '_ll.no_levers(project)')
    assert P.switch_levers(contract_src, unread) == {}
    space = P.build_space(P.cli_flags(runner_src), 'sha256:x', switch=switch)
    rows = {l['lever']: l for l in space['levers']}
    assert rows['pl_timing_driven']['admitted'] and \
        rows['pl_timing_driven']['citation']['path'] == P.CONTRACT_REL
    assert rows['cell_padding']['admitted'] is False       # still no direct flag
    assert P.audit_space(space) == []
    closed = P.build_space(P.cli_flags(runner_src), 'sha256:x', switch={})
    assert not {l['lever'] for l in closed['levers'] if l['admitted']} & {
        'pl_timing_driven', 'gpl_cell_padding'}


def test_a_lever_value_the_contract_refuses_is_not_searched(tmp_path, capsys):
    import ppa_pnr_search_space as P
    out = tmp_path / 's.json'
    assert P.main(['--json', str(out), '--values', 'pl_timing_driven=true,false']) == P.RC_PASS
    assert P.main(['--json', str(out), '--values', 'pl_target_density_pct=40,150']) == \
        P.RC_REFUSED
    assert 'LL_PLACEMENT_LEVER_INVALID' in capsys.readouterr().err


# ================================================================= dual ====

def test_the_direct_arm_stops_before_cts_and_writes_only_into_its_arm():
    out = runner._placement_direct_arm_tcl(_ll_deck().replace(
        'write_def /work/phase3/stage3/pnr/floorplan.def',
        'write_def /work/phase3/stage3/pnr/floorplan.def\nwrite_def /work/pnr/placed.def\n'
        'report_checks > /work/pnr/r.rpt\nread_def /work/pnr/padring.def'),
        '/work/pnr', '/work/arm')
    assert 'clock_tree_synthesis' not in out and 'detailed_route' not in out
    assert 'write_def /work/arm/placed.def' in out and 'write_def /work/pnr/' not in out
    assert '> /work/arm/r.rpt' in out and 'read_def /work/pnr/padring.def' in out
    assert 'write_verilog /work/arm/placed.v' in out
    assert 'DIRECT_ARM_CHECK_PLACEMENT_VIOLATIONS' in out and out.endswith('exit 0\n')
    with pytest.raises(ValueError, match='LL_PLACEMENT_SEAM_AMBIGUOUS'):
        runner._placement_direct_arm_tcl('read_lef x\n', '/a', '/b')


def _dual_fixture(tmp_path, monkeypatch, ll_ws, direct_ws, *, direct_violations=0,
                  ll_violations=0):
    project = tmp_path / 'p'
    out_dir = project / 'phase3/stage3/pnr'
    write(out_dir / 'constraint.sdc', 'create_clock -name clk -period 24 [get_ports clk]\n')
    put(out_dir / 'librelane_spare_cells.json',
        {'measured': {'check_placement_violations': ll_violations}})
    # the tool State carries its own re-written SDC (different bytes)
    ll_sdc = write(project / 'll/chip_top.sdc', '# written by write_sdc\ncreate_clock ...\n')
    ll_state = put(project / 'll/state_out.json', {'sdc': str(ll_sdc)})
    cfg = bridge._resolved(tmp_path, 'OpenROAD.STAMidPNR', ['odb', 'def', 'nl', 'sdc'])

    def docker(container, cmd, **k):
        arm = project / 'phase3/tool_arms/17/openroad'
        write(arm / 'placed.def', bridge.DEF_TEXT)
        write(arm / 'placed.v', 'module chip_top; endmodule\n')
        write(arm / 'openroad.log', f'DIRECT_ARM_CHECK_PLACEMENT_VIOLATIONS {direct_violations}\n')
        return 0, '', ''
    monkeypatch.setattr(runner, '_docker_exec', docker)
    def tool(cmd, **k):
        # only OpenROAD's DEF->ODB conversion writes a file, beside its own
        # Tcl in the bridge directory; `docker inspect` & co. answer "no
        # container" and write nothing (a blanket fake once wrote into cwd)
        tcl = next((Path(a) for a in cmd if str(a).endswith('.tcl')), None)
        if tcl is None or '-exit' not in cmd:
            return SimpleNamespace(returncode=1, stdout='', stderr='no container')
        write(tcl.parent / 'bridge.odb', 'odb')
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(contract.subprocess, 'run', tool)
    lanes = []

    def chain(project, image, triples, **k):
        lanes.append(k['lane'])
        assert json.loads(Path(triples[0][2]).read_text())['sdc'] == \
            str((out_dir / 'constraint.sdc').resolve())
        ws = ll_ws if k['lane'] == '17-dual-librelane' else direct_ws
        f = project / 'phase3/librelane' / k['lane'] / '01-openroad-stamidpnr'
        put(f / 'state_out.json', {'metrics': {'timing__setup__ws': ws,
                                               'timing__setup__tns': min(0.0, ws)}})
        return [f]
    monkeypatch.setattr(contract, 'run_chain', chain)
    sel = runner._select_placement_arm(project, 'img', 'c', out_dir,
                                       {'OpenROAD.STAMidPNR': cfg}, ll_state,
                                       _ll_deck(), [])
    return project, sel, lanes


def test_dual_selects_the_arm_the_same_instrument_measures_better(tmp_path, monkeypatch):
    project, sel, lanes = _dual_fixture(tmp_path / 'a', monkeypatch, 11.0, 9.5)
    assert sel['selection'] == 'librelane' and lanes == ['17-dual-librelane', '17-dual-openroad']
    arm = json.loads((project / 'phase3/tool_arms/17/openroad/gate.json').read_text())
    assert arm['metrics']['check_placement_violations'] == {'status': 'MEASURED', 'value': 0}
    assert arm['scope']['instrument'] == 'OpenROAD.STAMidPNR'
    assert arm['scope'] == json.loads(
        (project / 'phase3/tool_arms/17/librelane/gate.json').read_text())['scope']
    _p, sel, _l = _dual_fixture(tmp_path / 'b', monkeypatch, 9.0, 10.0)
    assert sel['selection'] == 'openroad'


def test_an_illegal_or_unmeasured_arm_selects_nothing(tmp_path, monkeypatch):
    _p, sel, _l = _dual_fixture(tmp_path / 'a', monkeypatch, 11.0, 9.5, ll_violations=2)
    assert sel['selection'] == 'UNDETERMINED' and sel['reason'] == 'LL_ARM_NOT_MEASURED'
    _p, sel, _l = _dual_fixture(tmp_path / 'b', monkeypatch, 9.0, 12.0, direct_violations=None)
    assert sel['selection'] == 'UNDETERMINED'


@pytest.mark.parametrize('selection,reason,ll_consumed', [
    ('librelane', None, True), ('openroad', None, False),
    # a measured, same-scope tie is the tool's (owner principle: use the tool)
    ('UNDETERMINED', 'LL_PARETO_TIE', True),
    # an unmeasured or mis-scoped comparison is not a tie: the incumbent stays
    ('UNDETERMINED', 'LL_ARM_NOT_MEASURED', False),
    ('UNDETERMINED', 'LL_ARM_SCOPE_MISMATCH', False)])
def test_the_dual_producer_routes_the_selected_arm(tmp_path, monkeypatch, selection, reason,
                                                   ll_consumed):
    monkeypatch.setattr(runner, '_select_placement_arm',
                        lambda *a, **k: {'selection': selection, 'reason': reason,
                                         'frontier': ['librelane', 'openroad']})
    project = tmp_path / 'project'
    orig = runner._prepare_librelane_floorplan_for_route

    def dual(*a, **k):
        k['placement']['mode'] = 'dual'
        return orig(*a, **k)
    monkeypatch.setattr(runner, '_prepare_librelane_floorplan_for_route', dual)
    _project, out_dir, _seen, result, consumer, _plan = _placement_producer(tmp_path, monkeypatch)
    assert result.status == 'PASS' and 'step 17 dual: selection=' in result.detail
    assert ('LIBRELANE_PLACEMENT_CONSUMED' in consumer) is ll_consumed
    receipt = project / 'reports/phase3/librelane_placement_handoff.json'
    assert receipt.is_file() is ll_consumed
    if not ll_consumed:
        assert 'read_def -floorplan_initialize' in consumer and 'global_placement' in consumer
        assert (project / 'phase3/tool_arms/17/librelane/librelane_placement_handoff.json').is_file()
        assert not (out_dir / 'librelane_spare_cells.log').exists()


def test_the_tool_arm_excludes_the_same_cell_families_as_the_direct_deck():
    """MEASURED on the spm copy: without it RepairDesignPostGPL chained six
    `dlyb_1` as fanout buffers and SS setup closed at -1.25 ns."""
    tcl = runner._dont_use_family_fallback_tcl()
    listed = tcl[tcl.index('foreach _du_pat {') + len('foreach _du_pat {'):]
    assert tuple(listed[:listed.index('}')].split()) == runner._DONT_USE_FAMILY_PATTERNS
    names = ['lib__dlyb_1', 'LIB__DLYA_2', 'lib__buf_1', 'lib__clkbuf_4', 'lib__clkdlybuf4s',
             'lib__probe_p_8', 'lib__lpflow_inputiso0n_1', 'lib__dffq_1', 'delay_cell']
    assert runner._dont_use_family_cells(names) == sorted(
        ['lib__dlyb_1', 'LIB__DLYA_2', 'lib__clkdlybuf4s', 'lib__probe_p_8',
         'lib__lpflow_inputiso0n_1', 'delay_cell'])


def test_the_placement_overlay_carries_the_excluded_families(tmp_path, monkeypatch):
    _p, _o, seen, result, _c, _plan = _placement_producer(
        tmp_path, monkeypatch,
        liberty_text='library(x) {\n cell (lib__buf_1) {\n }\n'
                     ' cell (lib__dlyb_1) {\n }\n}\n')
    assert result.status == 'PASS', result.detail
    config = seen['configs']['OpenROAD.GlobalPlacement']
    assert json.loads(config.read_text())['EXTRA_EXCLUDED_CELLS'] == ['lib__dlyb_1']
    source = json.loads(config.with_suffix('.provenance.json').read_text())['keys'][
        'EXTRA_EXCLUDED_CELLS']
    assert '_DONT_USE_FAMILY_PATTERNS' in source


def test_an_equal_measurement_is_a_tie_the_tool_wins(tmp_path, monkeypatch):
    """Both arms legal and equal on every objective: select_arms reports the
    tie, and step 17 routes the LibreLane placement."""
    _p, sel, _l = _dual_fixture(tmp_path / 'a', monkeypatch, 10.0, 10.0)
    assert sel['selection'] == 'UNDETERMINED' and sel['reason'] == 'LL_PARETO_TIE'
    assert runner._placement_arm_to_route(sel) == 'librelane'
    assert runner._placement_arm_to_route({'selection': 'openroad'}) == 'openroad'
    assert runner._placement_arm_to_route(
        {'selection': 'UNDETERMINED', 'reason': 'LL_ARM_NOT_MEASURED'}) == 'openroad'
