"""A layout chain's VERILOG_FILES is the design's whole build closure (cmp3 D8).

THE DEFECT (lane fxport, subservient x gf180mcuD). `emit_config` emitted
VERILOG_FILES = `rtl/<L9 top_module>.v` + `chip_top_io.v`. A multi-file core
lost every other module (`subservient_core` and the rest), and the LibreLane
chain stopped at Yosys.JsonHeader on the first of them. Synthesis never had
that problem: it reads `_chip_synth_read.chip_rtl_files`, the one selection
the Step-5 proof shares, and records what it built in `chip_read_built.json`.

Now the chain reads that same selection plus the chip-top wrapper, and a
layout chain whose read differs from the recorded synthesis read refuses.
"""
import hashlib
import importlib
import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
contract = importlib.import_module('librelane_contract')
CSR = importlib.import_module('_chip_synth_read')
from test_t95_mig_front import design, put  # noqa: E402

RTL = 'phase2/stage1/rtl'
WRAPPER = 'phase3/stage3/pnr/chip_top_io.v'
BUILT = 'phase2/stage2/synth/chip_read_built.json'
#: A multi-file core: a package, the top, two submodules -- and the files
#: synthesis never reads (a testbench, an assertion file).
SOURCES = {
    'core_pkg.sv': 'package core_pkg; localparam int W = 4; endpackage\n',
    'core.v': 'module core(input clk, output q); core_sub u(.clk(clk), .q(q)); endmodule\n',
    'core_sub.v': 'module core_sub(input clk, output q); core_leaf l(.clk(clk), .q(q)); endmodule\n',
    'core_leaf.v': 'module core_leaf(input clk, output reg q); always @(posedge clk) q <= ~q; endmodule\n',
    'core_tb.v': 'module core_tb; core dut(); endmodule\n',
    'core_assertions.sv': 'module core_assertions; endmodule\n',
}
CLOSURE = ['core_pkg.sv', 'core.v', 'core_leaf.v', 'core_sub.v']


def project(tmp_path, wrapper=True):
    p = design(tmp_path, {'deliverable': 'DIE', 'top_cell': 'core'})
    for name, text in SOURCES.items():
        put(p / RTL / name, text)
    if wrapper:
        put(p / WRAPPER, 'module chip_top; core u_core(); endmodule\n')
    (tmp_path / 'pdkroot' / 'processA').mkdir(parents=True, exist_ok=True)
    return p


NETLIST = 'phase2/stage2/synth/core_synth.v'


def built_record(p, files, simulation=True, bind=True):
    """The record direct synthesis writes, bound (as it now is once the
    netlist exists) to the netlist that read produced."""
    put(p / NETLIST, 'module core(); endmodule // synthesised\n')
    put(p / BUILT, {'files': [{'name': n, 'sha256': hashlib.sha256(
        (p / RTL / n).read_bytes()).hexdigest()} for n in files],
        'define': {'simulation': simulation, 'verdict': 'test'}, 'top': 'core',
        'synthesis_id': 'this-synthesis'})
    if bind:
        CSR.bind_built_record_netlist(p, p / NETLIST, synthesis_id='this-synthesis',
                                      frontend='read_verilog_v2005')


@pytest.fixture
def resolver(monkeypatch):
    from _stated_eda_image import mock_docker_route
    mock_docker_route(monkeypatch)
    calls = []

    def run(cmd, **_kw):
        # Match the resolver's six explicit arguments, including image identity.
        values = cmd[cmd.index('-c') + 2:]
        assert len(values) == 6, values
        assert values[-1] == cmd[cmd.index('-c') - 1]
        design_json, requested, root = map(Path, values[:3])
        calls.append(json.loads(design_json.read_text()))
        for s in json.loads(requested.read_text()):
            put(root / f'{s}.json', {'meta': {'step': s}})
            put(root / f'{s}.views.json', {'step': s, 'inputs': [], 'outputs': []})
        put(root / 'flow_gates.json', {})
        return contract.subprocess.CompletedProcess(cmd, 0, '', '')

    monkeypatch.setattr(contract, 'image_capability', lambda *a, **k: {})
    monkeypatch.setattr(contract.subprocess, 'run', run)
    return calls


def resolve(tmp_path, p):
    contract.resolve_step_configs(p, 'img', 'processA', ['Yosys.JsonHeader'],
                                  pdk_root=tmp_path / 'pdkroot', folder='x-config')
    root = p / 'phase3/librelane/x-config'
    return (json.loads((root / 'design.json').read_text()),
            json.loads((root / 'design.provenance.json').read_text()))


def names(files):
    return [Path(str(f).removeprefix('dir::')).name for f in files]


# ── red on main ──────────────────────────────────────────────────────────────

def test_verilog_files_are_the_synthesis_read_plus_the_wrapper(tmp_path):
    p = project(tmp_path)
    result = contract.emit_config(p, 'processA', p / 'phase3/librelane/config.json')
    assert names(result['VERILOG_FILES']) == [*CLOSURE, 'chip_top_io.v']
    # ONE definition: exactly the files synthesis and the Step-5 proof read.
    assert names(result['VERILOG_FILES'])[:-1] == [
        f.name for f in CSR.chip_rtl_files(p / RTL)]
    sources = json.loads((p / 'phase3/librelane/config.provenance.json').read_text())
    assert 'chip_rtl_files' in sources['VERILOG_FILES']


def test_a_chain_matching_the_recorded_synthesis_read_says_so(tmp_path, resolver):
    p = project(tmp_path)
    built_record(p, CLOSURE)
    config, sources = resolve(tmp_path, p)
    assert names(config['VERILOG_FILES']) == [*CLOSURE, 'chip_top_io.v']
    assert BUILT in sources['VERILOG_FILES'], sources['VERILOG_FILES']


@pytest.mark.parametrize('recorded', [CLOSURE[:-1], [*CLOSURE, 'core_tb.v']])
def test_a_chain_whose_read_differs_from_synthesis_is_refused(tmp_path, resolver, recorded):
    p = project(tmp_path)
    built_record(p, recorded)
    with pytest.raises(contract.Refusal, match='LL_LAYOUT_RTL_NOT_THE_SYNTHESISED_READ'):
        resolve(tmp_path, p)
    assert resolver == []


def test_an_edited_file_after_synthesis_is_refused(tmp_path, resolver):
    p = project(tmp_path)
    built_record(p, CLOSURE)
    put(p / RTL / 'core_sub.v', SOURCES['core_sub.v'] + '// edited after synthesis\n')
    with pytest.raises(contract.Refusal, match='core_sub.v'):
        resolve(tmp_path, p)


# ── controls: green on main and on the fix ───────────────────────────────────

def test_no_wrapper_emits_no_verilog_files(tmp_path):
    p = project(tmp_path, wrapper=False)
    result = contract.emit_config(p, 'processA', p / 'phase3/librelane/config.json')
    assert 'VERILOG_FILES' not in result


def test_emit_config_itself_never_refuses_on_an_older_synthesis_record(tmp_path):
    """Synthesis emits its config through emit_config BEFORE it writes the
    new record, so a re-run after an RTL edit must not be refused there."""
    p = project(tmp_path)
    built_record(p, CLOSURE[:1])
    contract.emit_config(p, 'processA', p / 'phase3/librelane/config.json')


# ── review_wave2 D7D8 minors: the comparison never skips silently, never
#    compares a stale record, and carries synthesis's define decision ────────

def test_no_synthesis_record_is_disclosed_not_skipped_silently(tmp_path, resolver):
    p = project(tmp_path)
    config, sources = resolve(tmp_path, p)
    assert 'NOT_MEASURED' in sources['VERILOG_FILES'], sources['VERILOG_FILES']
    assert 'no chip_read_built.json' in sources['VERILOG_FILES']
    assert 'VERILOG_DEFINES not carried' in sources['VERILOG_FILES']
    assert 'VERILOG_DEFINES' not in config


def test_an_unbound_record_is_not_compared(tmp_path, resolver):
    p = project(tmp_path)
    built_record(p, CLOSURE[:-1], bind=False)
    config, sources = resolve(tmp_path, p)
    assert 'bound to no netlist' in sources['VERILOG_FILES'], sources['VERILOG_FILES']


def test_a_record_of_an_earlier_netlist_is_not_compared(tmp_path, resolver):
    """Direct synthesis wrote and bound the record; a later LibreLane
    synthesis (which writes no record) replaced the netlist after an RTL
    repair. The old record describes a netlist that is gone: it must not
    refuse the chain over the repaired RTL, and the skip is disclosed."""
    p = project(tmp_path)
    built_record(p, CLOSURE)
    put(p / RTL / 'core_sub.v', SOURCES['core_sub.v'] + '// repaired\n')
    put(p / NETLIST, 'module core(); endmodule // re-synthesised by LibreLane\n')
    config, sources = resolve(tmp_path, p)
    assert 'NOT_MEASURED' in sources['VERILOG_FILES']
    assert 'that netlist is now' in sources['VERILOG_FILES'], sources['VERILOG_FILES']


@pytest.mark.parametrize('simulation, defines', [(True, ['SIMULATION']), (False, [])])
def test_the_chain_carries_the_synthesis_define_decision(tmp_path, resolver,
                                                          simulation, defines):
    p = project(tmp_path)
    built_record(p, CLOSURE, simulation=simulation)
    config, sources = resolve(tmp_path, p)
    assert config['VERILOG_DEFINES'] == defines
    assert resolver[-1]['VERILOG_DEFINES'] == defines
    assert BUILT + '.define.simulation' in sources['VERILOG_DEFINES']


def test_a_record_without_a_define_decision_is_refused(tmp_path, resolver):
    p = project(tmp_path)
    built_record(p, CLOSURE)
    rec = json.loads((p / BUILT).read_text())
    rec.pop('define')
    put(p / BUILT, rec)
    with pytest.raises(contract.Refusal, match='LL_SYNTHESIS_DEFINE_UNRECORDED'):
        resolve(tmp_path, p)
    assert resolver == []
