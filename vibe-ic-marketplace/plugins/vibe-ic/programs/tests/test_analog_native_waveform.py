from pathlib import Path
import math
import json

import numpy as np
import pytest

from analog_native_waveform import NativeRaw, window_statistics,product_statistics


def capture(path,times,values):
    matrix=np.column_stack([times,values,np.zeros(len(times))]).astype('<f8')
    header=(f'Title: native grid fixture\nPlotname: Transient Analysis\nFlags: real\n'
            f'No. Variables: 3\nNo. Points: {len(times)}\nVariables:\n'
            '0 time time\n1 v(a) voltage\n2 v(b) voltage\nBinary:\n')
    path.write_bytes(header.encode()+matrix.tobytes());return NativeRaw(path)


def test_nonuniform_native_grid_is_time_integrated_not_point_averaged(tmp_path):
    raw=capture(tmp_path/'native.raw',[0,.1,1,2],[-1,-.8,1,3])
    actual=window_statistics(raw,[0,2],[('a','b',1)],chunk=2)[0]
    assert actual['avg']==pytest.approx(1)
    assert actual['abs_avg']==pytest.approx(1.25)
    assert actual['rms']==pytest.approx(math.sqrt(7/3))
    assert actual['peak_abs']==3 and actual['min']==-1
    assert actual['avg']!=np.mean(raw.values[:,1])


def test_window_boundaries_are_interpolated_and_ground_is_exact(tmp_path):
    raw=capture(tmp_path/'native.raw',[0,.1,1,2],[-1,-.8,1,3])
    actual=window_statistics(raw,[.25,1.25],[('a','0',1)],chunk=1)[0]
    assert actual['avg']==pytest.approx(.5)
    assert actual['abs_avg']==pytest.approx(.625)
    assert actual['rms']==pytest.approx(math.sqrt(7/12))
    assert actual['min']==pytest.approx(-.5) and actual['max']==pytest.approx(1.5)


@pytest.mark.parametrize('damage',['truncated','nonfinite','duplicate-time','window'])
def test_incomplete_or_invalid_native_capture_cannot_be_scored(tmp_path,damage):
    p=tmp_path/'native.raw';times=[0,.1,1,2];values=[-1,-.8,1,3]
    if damage=='duplicate-time':times[2]=times[1]
    if damage=='nonfinite':values[2]=float('nan')
    raw=capture(p,times,values)
    if damage=='truncated':
        p.write_bytes(p.read_bytes()[:-8])
        with pytest.raises(ValueError,match='payload'):NativeRaw(p)
    else:
        with pytest.raises(ValueError):window_statistics(raw,[0,3 if damage=='window' else 2],[('a','b',1)])


def test_binary_op_is_read_without_treating_it_as_a_transient(tmp_path):
    p=tmp_path/'op.raw'
    p.write_bytes(b'Title: native OP\nPlotname: Operating Point\nFlags: real\nNo. Variables: 1\nNo. Points: 1\nVariables:\n0 v(a) voltage\nBinary:\n'+np.array([1.2],dtype='<f8').tobytes())
    import analog_native_em as em
    assert em.read_op_capture(p)=={'a':1.2,'0':0.}
    with pytest.raises(ValueError,match='transient'):window_statistics(NativeRaw(p),[0,1],[('a','0',1)])


def test_actual_native_pwl_capture_matches_independent_integral_oracle(tmp_path):
    data=json.loads((Path(__file__).parent/'fixtures/native_interconnect_pwl.json').read_text())
    matrix=np.array(data['native_points']);names=data['variables']
    raw=capture(tmp_path/'native.raw',matrix[:,0],matrix[:,names.index('a')])
    result=window_statistics(raw,data['window_s'],[('a','b',1000)])[0]
    assert result['avg']==pytest.approx(data['independent_oracle']['avg_a'],rel=1e-12)
    assert result['rms']==pytest.approx(data['independent_oracle']['rms_a'],rel=1e-12)
    assert result['peak_abs']==pytest.approx(.001)
    assert result['avg']!=pytest.approx(float(np.mean(matrix[:,names.index('a')]))/1000,rel=1e-3)


def test_power_product_integrates_cross_term_and_interior_extremum(tmp_path):
    raw=capture(tmp_path/'native.raw',[0,.1,1,2],[-1,-.8,1,3])
    power=product_statistics(raw,[0,2],('a','0',1),('a','0',1))
    assert power['avg']==pytest.approx(7/3) and power['peak_abs']==9
    assert power['min']==pytest.approx(0)


def test_actual_native_supply_branch_identity_and_power_are_not_guessed(tmp_path):
    import analog_native_em as em
    data=json.loads((Path(__file__).parent/'fixtures/native_interconnect_pwl.json').read_text())
    matrix=np.array(data['native_points'],dtype='<f8');names=data['variables']
    header=(f'Title: native control\nPlotname: Transient Analysis\nFlags: real\nNo. Variables: {len(names)}\n'
            f'No. Points: {len(matrix)}\nVariables:\n'+''.join(f'{i} {name} voltage\n' for i,name in enumerate(names))+'Binary:\n')
    path=tmp_path/'native.raw';path.write_bytes(header.encode()+matrix.tobytes());raw=NativeRaw(path)
    source='v1 a 0 PWL(0 0 1u 1 1.5u 1)\nv0 b 0 0\n'
    result=em.supply_wave_statistics(raw,data['window_s'],source,{'a':'v1'},{'a':'a'})['a']
    assert result['current_a']['avg']==pytest.approx(.00071875,rel=1e-12)
    assert result['power_w']['avg']==pytest.approx(.000578125,rel=1e-12)
    assert result['power_w']['peak_abs']==pytest.approx(.001)
    with pytest.raises(ValueError,match='declared rail'):
        em.supply_wave_statistics(raw,data['window_s'],source,{'b':'v1'},{'b':'b'})
