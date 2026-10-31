"""Retained native reports keep their full endpoint and model identities."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import drv_signoff_anchor as anchor
import drv_signoff_annotation as annotation
import drv_signoff_census as census
import drv_signoff_judge as judge


NET = '''Net supply
 Total capacitance: 0.0
 Number of drivers: 1
 Number of loads: 1
 Number of pins: 3

Driver pins
 src input port pin 0

Load pins
 fill/VPWR unknown (fill)

Other pins
 logic/VPWR power (logic)

'''


def test_other_pins_reconcile_without_becoming_loads(tmp_path):
    path = tmp_path / 'net.rpt'
    path.write_text(NET)
    net = census._nets(path)['supply']
    assert net['drivers'] == ['src']
    assert net['loads'] == ['fill/VPWR']
    assert net['other_pins'] == ['logic/VPWR']


@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'wrong_count'])
def test_other_pin_population_stays_strict(tmp_path, mutation):
    text = NET
    if mutation == 'missing':
        text = text.split('Other pins')[0]
    elif mutation == 'duplicate':
        text = text.replace(' logic/VPWR power (logic)', ' logic/VPWR power (logic)\n logic/VPWR power (logic)')
    else:
        text = text.replace('Number of pins: 3', 'Number of pins: 4')
    path = tmp_path / 'net.rpt'
    path.write_text(text)
    with pytest.raises(ValueError, match='pin count'):
        census._nets(path)


@pytest.mark.parametrize('master_class', ['CORE SPACER', 'CORE WELLTAP'])
def test_passive_core_supply_pin_needs_no_logic_model(master_class):
    pin = {'kind': 'pin', 'cell': 'physical', 'cell_pin': 'VDD',
           'direction': 'unknown', 'driver': False, 'clock': False}
    models = {('physical', 'VDD'): {'class': master_class, 'direction': 'INOUT', 'use': 'POWER'}}
    assert annotation._is_physical_pin(pin, models, set())


@pytest.mark.parametrize('mutation', ['logic_class', 'signal', 'clock', 'driver', 'mixed_master'])
def test_logic_or_clock_never_uses_passive_supply_exemption(mutation):
    pin = {'kind': 'pin', 'cell': 'physical', 'cell_pin': 'VDD',
           'direction': 'unknown', 'driver': False, 'clock': False}
    models = {('physical', 'VDD'): {'class': 'CORE SPACER', 'direction': 'INOUT', 'use': 'POWER'}}
    if mutation == 'logic_class':
        models[('physical', 'VDD')]['class'] = 'CORE'
    elif mutation == 'signal':
        models[('physical', 'VDD')]['use'] = 'SIGNAL'
    elif mutation == 'mixed_master':
        models[('physical', 'Z')] = {'class': 'CORE SPACER', 'direction': 'OUTPUT', 'use': 'SIGNAL'}
    else:
        pin[mutation] = True
    assert not annotation._is_physical_pin(pin, models, set())


def port_fixture(tmp_path, driver=True):
    (tmp_path / 'pin_census.tsv').write_text('bus\tport\tbidirect\t0\t\t\t\tbus\tinput\t0\t0\t0\tX\t0\n')
    report = 'Net bus\n Total capacitance: 0.0\n Number of drivers: %d\n Number of loads: 1\n Number of pins: 1\n\n' % driver
    if driver:
        report += 'Driver pins\n bus bidirect port pin 0\n\n'
    report += 'Load pins\n bus bidirect port pin 0\n\n'
    (tmp_path / 'net_census.rpt').write_text(report)
    (tmp_path / 'disabled_edges.rpt').write_text('')
    lib = tmp_path / 'cells.lib'
    lib.write_text('library (fixture) { time_unit : "1ns"; capacitive_load_unit (1,pf); }')
    return [{'name': 'fixture', 'path': str(lib)}], {k: [{'pin': 'bus'}] for k in judge.KINDS}


def test_bidirect_port_uses_independent_driver_and_load_proof(tmp_path):
    libs, rows = port_fixture(tmp_path)
    result = census.derive(tmp_path, libs, rows, allow_unproven=True)
    assert result['driver_pins'] == ['bus']
    assert result['population']['max_fanout'] == 1


def test_bidirect_port_missing_endpoint_refuses(tmp_path):
    libs, rows = port_fixture(tmp_path, driver=False)
    with pytest.raises(ValueError, match='independent net endpoint proof'):
        census.derive(tmp_path, libs, rows, allow_unproven=True)


def probe(root):
    return subprocess.run([sys.executable, '-c', anchor._IMAGE_PROBE, 'sky130A', 'sky130_fd_sc_hd'],
                          env={**os.environ, 'PDK_ROOT': str(root)}, capture_output=True, text=True)


def test_canonical_symlinked_nix_pdk_source(tmp_path):
    revision = 'b3' * 20
    store = tmp_path / ('store-vibeic-pdk-sky130A-' + revision) / 'sky130A'
    config = store / 'libs.tech/librelane/sky130_fd_sc_hd/config.tcl'
    config.parent.mkdir(parents=True)
    config.write_text('set ::env(SYNTH_MAX_FANOUT) 10\n')
    root = tmp_path / 'pdks'
    root.mkdir()
    (root / 'sky130A').symlink_to(store, target_is_directory=True)
    result = probe(root)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['pdk_commit'] == revision


def test_neighbor_pdk_cannot_replace_missing_canonical_source(tmp_path):
    config = tmp_path / 'neighbor/sky130A/libs.tech/librelane/sky130_fd_sc_hd/config.tcl'
    config.parent.mkdir(parents=True)
    config.write_text('neighbor')
    assert probe(tmp_path).returncode != 0


@pytest.mark.parametrize('instance', ['mprj', 'wrong', None])
def test_script_reader_binds_macro_instance_namespace(instance):
    command = 'read_spef {/child.spef}' if instance is None else 'read_spef -path {' + instance + '} {/child.spef}'
    expected = [('read_spef -path mprj', '/child.spef')]
    assert (judge._script_reads(command) == expected) == (instance == 'mprj')
