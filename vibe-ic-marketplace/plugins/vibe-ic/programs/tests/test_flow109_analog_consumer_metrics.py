"""SOURCE_ONLY consumer regressions; no native job or qualification is run.

Existing native-format unit fixtures exercise real parsers and grading. Reader
edge injections exercise the canonical completion seam, never claim a native
receipt, approval, model qualification, physical coverage or row PASS.
"""
import json

import pytest
import analog_native_em as power
import em_current_density_check as em
import ir_drop_budget_check as ir
from test_analog_native_em import measured_case, grade, put, TABLE, TECH

IDS = {'D48':['base_36.si_required_windows','base_36.coupling_noise_delay_bounds'],
       'D56':['base_40.power_activity_coverage','base_40.per_mode_rail_average_peak_power'],
       'D57':['base_33.rail_source_coverage','base_33.static_dynamic_ir_limits'],
       'D58':['base_34.em_current_lifetime_limits','base_34.current_temperature_model_coverage']}




















def test_em_late_mapping_gap_preserves_earlier_measured_DC_violation(measured_case):
    project,setting,paths=measured_case
    # Change the actual source OP voltage and matching current above the source limit.
    paths['capture'].write_text(paths['capture'].read_text().replace('0 0.0001','0 0.01'))
    mapping=json.loads(paths['currents'].read_text());mapping.update(voltage_v=[.01,0],current_a=.01/1.0005)
    paths['currents'].write_text(json.dumps(mapping)+'\n'+json.dumps(dict(mapping,spice_resistor='foreign'))+'\n')
    try: result,_=grade(project,setting)
    except ValueError as exc:result={'status':'NOT_MEASURED','reason':str(exc)}
    assert result['status']=='FAIL', result
    assert result['violations'][0]['material']=='metal2'


def test_em_successful_native_segments_are_exposed_for_coverage(measured_case):
    result,_=grade(*measured_case[:2])
    actual=result.get('interconnect_results',[])
    assert len(actual)==1 and actual[0]['status']=='PASS', result
    assert actual[0]['material']=='metal2'




def test_em_aggregate_late_required_population_error_keeps_measured_failure(measured_case,monkeypatch):
    project,setting,paths=measured_case
    paths['capture'].write_text(paths['capture'].read_text().replace('0 0.0001','0 0.01'))
    mapping=json.loads(paths['currents'].read_text());mapping.update(voltage_v=[.01,0],current_a=.01/1.0005)
    put(paths['currents'],json.dumps(mapping)+'\n')
    pdf=put(project/'source-only.pdf','SOURCE_ONLY document-conversion edge; not qualification\n')
    source=put(project/'source-limits.json',{'copy':str(pdf)})
    monkeypatch.setattr(power,'_limit_document_text',lambda *args:(TABLE,{}))
    monkeypatch.setattr(power,'read_technology',lambda *args:(TECH,{}))
    result=power.run(project,'unit',{'limits_source':str(source),'magic_tech':'source-only.tech',
        'cases':[dict(setting,name='op0')],'required_cases':[1,'absent']})
    assert result['cases'][0]['status']=='FAIL', result
    assert result['status']=='FAIL', result


@pytest.mark.parametrize('sign', [-1,1])
def test_supply_power_integrates_actual_voltage_times_signed_current(tmp_path,sign):
    import numpy as np
    path=tmp_path/'supply.raw'
    times=np.array([0.,.1,1.,2.])
    matrix=np.stack([times,1.+times,sign*.001*(1.+times)],axis=1).astype('<f8')
    path.write_bytes(b'Title: SOURCE_ONLY supply integration fixture\nPlotname: Transient Analysis\nFlags: real\nNo. Variables: 3\nNo. Points: 4\nVariables:\n0 time time\n1 v(vdd) voltage\n2 i(vfeed) current\nBinary:\n'+matrix.tobytes())
    stats=power.supply_wave_statistics(power.NativeRaw(path),[0,2],'Vfeed vdd 0 PWL(0 1 2 3)\n',{'vdd':'Vfeed'},{'vdd':'vdd'})['vdd']
    assert stats['power_w']['avg']==pytest.approx(-sign*.001*13/3)
    assert stats['power_w']['peak_abs']==pytest.approx(.009)
    assert stats['power_w']['avg']!=pytest.approx(stats['voltage_v']['avg']*stats['current_a']['avg'])
