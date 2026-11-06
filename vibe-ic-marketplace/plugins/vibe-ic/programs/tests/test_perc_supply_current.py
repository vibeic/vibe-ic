"""Ruling #71: measured supply current, native authority, and low-margin IO load."""
import json
import pytest
from test_u22_perc_sweep_lef_class import _perc_project, _memo, _category


def current_project(tmp_path, power=0.002, *, em=True, width=True, rating=None, count_limit=None):
    project, pdk = _perc_project(tmp_path, limit=count_limit)
    root = project / 'input/pdk'
    lef = root / 'libs.ref/neutral_io/lef/io.lef'
    if width:
        text = lef.read_text()
        for pin in ('B', 'H', 'L'):
            text = text.replace(f' END {pin}\n',
                f'  PORT\n   LAYER conductor ;\n    RECT 0 0 10 10 ;\n  END\n END {pin}\n')
        lef.write_text(text)
    if em:
        tech = root / 'libs.ref/logic/techlef/native.tlef'
        tech.parent.mkdir(parents=True)
        tech.write_text('LAYER conductor\n TYPE ROUTING ;\n DCCURRENTDENSITY AVERAGE 1 ;\nEND conductor\n')
    if rating is not None:
        lib = root / 'libs.ref/neutral_io/lib/io.lib'
        lib.write_text('current_unit : "1A";\n' + lib.read_text().replace(
            ' is_pad : true;', f' is_pad : true;\n max_current : {rating};'))
    report = project / 'reports/phase3/ir_drop.rpt'
    report.parent.mkdir(parents=True)
    report.write_text(f'Net : upper\nTotal power : {power} W\nSupply voltage : 1.00 V\n')
    d = project / 'phase3/stage3/pnr/chip_top.def'
    d.write_text(d.read_text() + 'PINS 2 ;\n- clk + NET clk + DIRECTION INPUT ;\n- y + NET out + DIRECTION OUTPUT ;\nEND PINS\n')
    return project, pdk


def supply(project, pdk):
    return _category(_memo(project, pdk), 'io_supply_pad_sufficiency')


def test_under_limit_and_native_sources(tmp_path):
    p, pdk = current_project(tmp_path)
    row = supply(p, pdk)
    assert row['result'] == 'PASS'
    for item in row['domains'][0]['comparisons']:
        assert item['limit_A'] == pytest.approx(0.01)
        assert item['per_pad_current_A'] == pytest.approx(0.002)
        assert item['margin'] == pytest.approx(5)
        assert item['jmax']['source']['line'] == 3
        assert item['terminal']['source']['line'] > 0
        assert item['jmax']['temperature_basis'] == 'single PDK DC limit, no temperature table'






def test_io_library_rating_precedes_em(tmp_path):
    p, pdk = current_project(tmp_path, em=False, rating=0.008)
    row = supply(p, pdk)
    assert row['result'] == 'PASS'
    for item in row['domains'][0]['comparisons']:
        assert item['limit_A'] == pytest.approx(0.008)
        assert item['limit_basis'] == 'IO library rated current'


def test_low_margin_without_sdc_never_passes(tmp_path):
    p, pdk = current_project(tmp_path, power=0.006)
    assert supply(p, pdk)['result'] == 'NOT_MEASURED'


@pytest.mark.parametrize('load,result,current', [(1000, 'PASS', 0.007), (5000, 'FAIL', 0.011)])
def test_low_margin_adds_output_current(tmp_path, load, result, current):
    p, pdk = current_project(tmp_path, power=0.006)
    (p / 'phase3/stage3/pnr/constraint.sdc').write_text(
        f'create_clock -period 1000 [get_ports clk]\nset_load {load} [all_outputs]\n')
    row = supply(p, pdk)
    assert row['result'] == result
    for item in row['domains'][0]['comparisons']:
        assert item['per_pad_current_A'] == pytest.approx(current)
        assert item['switching']['output_load_pf'] == pytest.approx({'y': load})


def test_single_native_dc_limit_also_applies_to_declared_temperature(tmp_path):
    p, pdk = current_project(tmp_path)
    doc = p / 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json'
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(json.dumps({'maximum_operating_temperature_c': 125}))
    assert supply(p, pdk)['result'] == 'PASS'


def test_zero_power_needs_no_switching_residual(tmp_path):
    p, pdk = current_project(tmp_path, power=0)
    assert supply(p, pdk)['result'] == 'PASS'


def test_replaced_count_ratio_cannot_override_current_evidence(tmp_path):
    p, pdk = current_project(tmp_path, count_limit={
        'max_signal_pads_per_power_pad': 1, 'max_signal_pads_per_ground_pad': 1})
    assert supply(p, pdk)['result'] == 'PASS'  # #71, despite two signals per pad


def test_psm_current_is_divided_by_each_rail_population(tmp_path):
    p, pdk = current_project(tmp_path, power=0.004)
    d = p / 'phase3/stage3/pnr/chip_top.def'
    d.write_text(d.read_text().replace('COMPONENTS 5 ;', 'COMPONENTS 7 ;').replace(
        'END COMPONENTS', '- h2 neutral_io__hi ;\n- l2 neutral_io__lo ;\nEND COMPONENTS'))
    row = supply(p, pdk)
    assert row['result'] == 'PASS'
    assert len(row['domains'][0]['comparisons']) == 4
    assert all(item['per_pad_current_A'] == pytest.approx(0.002)
               for item in row['domains'][0]['comparisons'])


@pytest.mark.parametrize('load', ['set_load 1 [get_ports missing]',
                                 'set_load $unreadable [all_outputs]'])
def test_low_margin_incomplete_output_load_is_not_measured(tmp_path, load):
    p, pdk = current_project(tmp_path, power=0.006)
    (p / 'phase3/stage3/pnr/constraint.sdc').write_text(
        'create_clock -period 1000 [get_ports clk]\n' + load + '\n')
    assert supply(p, pdk)['result'] == 'NOT_MEASURED'


def test_unreadable_rated_current_unit_cannot_fall_back_to_em(tmp_path):
    p, pdk = current_project(tmp_path, rating=0.008)
    lib = p / 'input/pdk/libs.ref/neutral_io/lib/io.lib'
    lib.write_text(lib.read_text().replace('current_unit : "1A";', ''))
    assert supply(p, pdk)['result'] == 'NOT_MEASURED'


@pytest.mark.parametrize('pin_kind', ['pin', 'pg_pin'])
def test_supply_bond_rating_precedes_looser_em_limit(tmp_path, pin_kind):
    p, pdk = current_project(tmp_path, power=0.002, rating=0.001)
    lib = p / 'input/pdk/libs.ref/neutral_io/lib/io.lib'
    lib.write_text(lib.read_text().replace(' pin (', f' {pin_kind} ('))
    row = supply(p, pdk)
    assert row['result'] == 'FAIL'
    for item in row['domains'][0]['comparisons']:
        assert item['limit_A'] == pytest.approx(0.001)
        assert item['per_pad_current_A'] == pytest.approx(0.002)
        assert item['limit_basis'] == 'IO library rated current'


def test_conditional_sdc_load_override_uses_native_final_load(tmp_path):
    p, pdk = current_project(tmp_path, power=0.006)
    (p / 'phase3/stage3/pnr/constraint.sdc').write_text(
        'create_clock -period 1000 [get_ports clk]\n'
        'set_load 1000 [all_outputs]\n'
        'if {1} {set_load 5000 [all_outputs]}\n')
    row = supply(p, pdk)
    assert row['result'] == 'FAIL'
    for item in row['domains'][0]['comparisons']:
        assert item['per_pad_current_A'] == pytest.approx(0.011)
        assert item['switching']['output_load_pf'] == pytest.approx({'y': 5000})


def test_native_final_load_can_replace_a_larger_prior_load(tmp_path):
    p, pdk = current_project(tmp_path, power=0.006)
    (p / 'phase3/stage3/pnr/constraint.sdc').write_text(
        'create_clock -period 1000 [get_ports clk]\n'
        'set_load 5000 [all_outputs]\n'
        'set cap 1000\nforeach port [all_outputs] {set_load $cap $port}\n')
    row = supply(p, pdk)
    assert row['result'] == 'PASS'
    for item in row['domains'][0]['comparisons']:
        assert item['per_pad_current_A'] == pytest.approx(0.007)
        assert item['switching']['output_load_pf'] == pytest.approx({'y': 1000})
        assert 'OpenSTA' in item['switching']['native_log']
