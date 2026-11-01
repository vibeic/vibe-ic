import copy

import pytest

import analog_incremental_capture as capture
from test_analog_incremental_capture import _template


def split_storage(topology):
    out = copy.deepcopy(topology)
    devices = []
    for device in out['devices']:
        if device['name'] in ('store1', 'store2'):
            devices.extend([dict(device, name=device['name'] + '_u0'),
                            dict(device, name=device['name'] + '_u1', nets=list(reversed(device['nets'])))])
        else:
            devices.append(device)
    out['devices'] = devices
    return out


def test_parallel_storage_uses_identical_actual_transfer_and_reset_gates(tmp_path):
    _, _, topology = _template(tmp_path)
    assert capture._transfer_timing(split_storage(topology), 'xdut.reset_b') == \
        capture._transfer_timing(topology, 'xdut.reset_b')


@pytest.mark.parametrize('defect', ['different_nodes', 'base_and_units', 'duplicate_name', 'noncapacitor', 'shorted'])
def test_parallel_storage_cannot_hide_ambiguous_or_wrong_physical_endpoints(tmp_path, defect):
    _, _, topology = _template(tmp_path)
    topology = split_storage(topology)
    device = next(d for d in topology['devices'] if d['name'] == 'store1_u1')
    if defect == 'different_nodes':
        device['nets'][0] = 'unrelated_output'
    elif defect == 'base_and_units':
        topology['devices'].append(dict(device, name='store1'))
    elif defect == 'duplicate_name':
        topology['devices'].append(dict(device))
    elif defect == 'noncapacitor':
        device['role'] = 'res'
    else:
        for d in topology['devices']:
            if d['name'].startswith('store1_'):
                d['nets'] = ['sum1', 'sum1']
    with pytest.raises(ValueError, match='typed integrating capacitor'):
        capture._transfer_timing(topology, 'xdut.reset_b')
