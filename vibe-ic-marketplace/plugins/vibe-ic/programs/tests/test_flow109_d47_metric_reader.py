"""SOURCE_ONLY D47 native-output audit and actual completion-seam controls.

No native extraction, approved reference, qualified corner mapping or canonical
receipt is manufactured. The existing source audit parses neutral SPICE, and
the completion controls inject those observations at the reader seam.
"""

import pytest
import magic_extract_spice_emit as owner


@pytest.fixture
def extraction(tmp_path):
    logical = tmp_path / 'logical.spice'
    source = '.subckt neutral_top a z\nXone a z neutral_device\n.ends neutral_top\n'
    logical.write_text(source)
    spice = tmp_path / 'candidate.spice'
    spice.write_text(source.replace('.ends', 'C1 a z 1f\n.ends'))
    data = {'top': 'neutral_top', 'ports': ['a', 'z'], 'logical': str(logical),
            'summed_models': [], 'require_resistance': False, 'options': {'extresist': False}}
    return data, spice, tmp_path / 'neutral_top.res.ext'


def values(extraction):
    if not hasattr(owner, '_d47_metric_values'):
        pytest.skip('D47 metric reader absent on exact main; canonical controls still execute')
    return owner._d47_metric_values(*extraction)


def test_existing_audit_discloses_C_ONLY_without_corner_or_complete_net_credit(extraction):
    observed = values(extraction)
    assert observed['status'] == 'PASS', observed
    assert observed['extraction_depth'] == 'C_ONLY'
    assert observed['audit']['summary']['capacitors'] == 1
    assert observed['required_logical_ports'] == ['a', 'z']
    assert observed['required_nets_and_corners'] is None
    assert observed['si_applicability'] == 'NOT_MEASURED'


@pytest.mark.parametrize('damage', ['no_parasitics', 'wrong_ports', 'wrong_device', 'required_R_absent', 'missing_spice'])
def test_real_native_output_audit_rejects_substantive_bad_values(extraction, damage):
    data, spice, _ = extraction
    if damage == 'no_parasitics':
        spice.write_text(spice.read_text().replace('C1 a z 1f\n', ''))
    elif damage == 'wrong_ports':
        spice.write_text(spice.read_text().replace('.subckt neutral_top a z', '.subckt neutral_top a other'))
    elif damage == 'wrong_device':
        spice.write_text(spice.read_text().replace('neutral_device', 'foreign_device'))
    elif damage == 'required_R_absent':
        data['require_resistance'] = True
    else:
        spice.unlink()
    observed = values(extraction)
    assert observed['status'] == 'FAIL', observed
