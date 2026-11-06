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


def test_a_tool_step_invocation_is_unchanged_by_the_plugin(tmp_path, monkeypatch):
    p, state, cfg = bridge._chain_fixture(tmp_path)
    calls = []
    monkeypatch.setattr(contract, 'image_capability', lambda *a: None)
    monkeypatch.setattr(contract.subprocess, 'run', bridge._tool(calls))
    contract.run_chain(p, 'img', [('OpenROAD.STAMidPNR', cfg, state)], pdk_root='/pdk')
    assert not any('PYTHONPATH=' in str(a) for a in calls[0])


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
        'pdk_target': 'gf180mcuD',
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
    m = 'PNR_STAGE:'
    return (f"read_lef /pdk/tech.lef\nread_lef /pdk/cells.lef\nread_liberty /pdk/tt.lib\n"
            f"read_verilog /work/core.v\n# chip top\nread_verilog /work/chip_top_io.v\n\n"
            f"link_design chip_top\nread_sdc /work/constraint.sdc\nset_wire_rc -signal -layer M2\n"
            f"# <<<PNR_RESUME_ELIDE_BEGIN>>>\n# Everything between this sentinel and ...\n"
            f"# checkpoint.\n"
            f'puts "{m} padring_ingest"\nread_def -floorplan_initialize /work/padring.def\n'
            f'puts "{m} placement"\nglobal_placement -density 0.3\n'
            f"write_def /work/placed.def\nplace_inst -name spare_inverter_0 -cell inv\n"
            f"detailed_placement\nrepair_design\n"
            f'puts "{m} cts"\nclock_tree_synthesis\nwrite_def /work/post_cts.def\n'
            f'puts "{m} detailed_route"\ndetailed_route\n'
            f"# <<<PNR_RESUME_ELIDE_END>>>\n"
            f'puts "{m} postroute_spef_extract"\nwrite_def /work/routed.def\n')


def test_the_direct_deck_resumes_at_cts_on_the_tools_placed_def():
    out = contract.placement_consumer_tcl(_full_deck(), '/work/placed.def',
                                          'PNR_STAGE:', 'AFTER_LOAD_STATE\n')
    # the tech/cell LEFs stay: CTS and route use the direct flow's own tech
    assert out.count('read_lef ') == 2 and 'read_liberty /pdk/tt.lib' in out
    assert 'read_verilog' not in out and 'link_design' not in out
    load = out.index('read_def /work/placed.def')
    assert out.index('read_liberty') < load < out.index('read_sdc')
    # floorplan..pre-CTS work is gone; the session state is restored first
    for gone in ('floorplan_initialize', 'global_placement', 'place_inst', 'repair_design'):
        assert gone not in out
    assert out.index('AFTER_LOAD_STATE') < out.index('clock_tree_synthesis')
    assert out.count('# <<<PNR_RESUME_ELIDE_BEGIN>>>') == 1
    assert out.index('# <<<PNR_RESUME_ELIDE_BEGIN>>>') < out.index('librelane_placement_ingest')
    assert out.endswith('write_def /work/routed.def\n')
    with pytest.raises(ValueError, match='LL_PLACEMENT_SEAM_AMBIGUOUS'):
        contract.placement_consumer_tcl(_full_deck() + _full_deck(), '/w/p.def',
                                        'PNR_STAGE:')
    with pytest.raises(ValueError, match='LL_PLACEMENT_SEAM_AMBIGUOUS'):
        contract.placement_consumer_tcl(_full_deck().replace('link_design', 'foo'),
                                        '/w/p.def', 'PNR_STAGE:')


# ============================================================== runner ====


def test_the_runner_and_the_custom_step_build_one_plan():
    """Ported, not copied: the runner's names bind to `_spare_plan`."""
    cells = ['lib__inv_1', 'lib__nand2_1', 'lib__nor2_1', 'lib__mux2_1', 'lib__a21oi_1',
             'lib__o21ai_1', 'lib__dffq_1', 'lib__dffrnq_1']
    cmap = sp.discover_spare_cells(cells, used_cells={'lib__dffq_1'})
    assert cmap['dff'] == 'lib__dffrnq_1'           # an unused variant is preferred
    plan = sp.build_spare_cells_plan(300, 0.02, (0, 0, 100, 100), cmap, has_pad_ring=True)
    assert plan['count'] == 6 and sum(plan['types'].values()) == 6
    assert plan['instances'][0]['name'] == 'spare_inverter_0'
    assert plan['spare_pads'] and plan['tied_off'] is False


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
