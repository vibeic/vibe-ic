from pathlib import Path
import math
import json

import numpy as np
import pytest

from analog_native_waveform import NativeRaw, window_statistics,product_statistics
import gzip
import hashlib


def capture(path,times,values,title='native grid fixture'):
    matrix=np.column_stack([times,values,np.zeros(len(times))]).astype('<f8')
    header=(f'Title: {title}\nPlotname: Transient Analysis\nFlags: real\n'
            f'No. Variables: 3\nNo. Points: {len(times)}\nVariables:\n'
            '0 time time\n1 v(a) voltage\n2 v(b) voltage\nBinary:\n')
    path.write_bytes(header.encode()+matrix.tobytes());return NativeRaw(path)


@pytest.mark.parametrize('title',[
    'native grid fixture',
    '* tb_delta_sigma — stimulus for the a3 block netlist',
])
def test_utf8_native_title_preserves_binary_payload_and_math(tmp_path,title):
    path=tmp_path/'native.raw'
    raw=capture(path,[0,.1,1,2],[-1,-.8,1,3],title=title)
    before=path.read_bytes()
    assert raw.shape==(4,3)
    assert raw.row(-1)=={'time':2.,'a':3.,'b':0.,'0':0.}
    actual=window_statistics(raw,[0,2],[('a','b',1)])[0]
    assert actual['avg']==pytest.approx(1)
    assert actual['rms']==pytest.approx(math.sqrt(7/3))
    assert path.read_bytes()==before
    assert before.split(b'Binary:\n',1)[1]==np.column_stack([
        [0,.1,1,2],[-1,-.8,1,3],[0,0,0,0],
    ]).astype('<f8').tobytes()


def test_invalid_utf8_native_header_is_refused(tmp_path):
    path=tmp_path/'native.raw';capture(path,[0,1],[0,1])
    path.write_bytes(path.read_bytes().replace(b'native grid fixture',b'\xff'))
    with pytest.raises(UnicodeDecodeError):NativeRaw(path)


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


@pytest.mark.parametrize('title',['neutral native grid','native waveform — retained UTF-8'])
def test_gzip_binary_reader_preserves_bytes_dtype_shape_and_all_math(tmp_path,title):
    path=tmp_path/'plain.raw';plain=capture(path,[0,.1,1,2],[-1,-.8,1,3],title=title)
    original=path.read_bytes();stored=tmp_path/'native.raw.gz';stored.write_bytes(gzip.compress(original,mtime=0))
    raw=NativeRaw(stored,expected_raw_sha256=hashlib.sha256(original).hexdigest(),expected_raw_bytes=len(original))
    assert raw.names==plain.names and raw.shape==plain.shape and raw.values.dtype==plain.values.dtype
    assert not raw.values.flags.writeable and raw.values.tobytes()==plain.values.tobytes()
    assert raw.row(-1)==plain.row(-1)
    assert window_statistics(raw,[.25,1.25],[('a','0',1)])==window_statistics(plain,[.25,1.25],[('a','0',1)])
    assert product_statistics(raw,[0,2],('a','0',1),('a','0',1))==product_statistics(plain,[0,2],('a','0',1),('a','0',1))
    assert path.read_bytes()==original


@pytest.mark.parametrize('damage',['truncated_gzip','crc','trailing_payload','short_payload','raw_sha','raw_bytes',
                                  'complex','indices','utf8'])
def test_gzip_capture_corruption_or_identity_mismatch_cannot_be_measured(tmp_path,damage):
    path=tmp_path/'plain.raw';capture(path,[0,1],[0,1]);original=path.read_bytes()
    if damage=='trailing_payload':original+=b'\0'
    elif damage=='short_payload':original=original[:-1]
    elif damage=='complex':original=original.replace(b'Flags: real',b'Flags: real complex')
    elif damage=='indices':original=original.replace(b'1 v(a)',b'0 v(a)')
    elif damage=='utf8':original=original.replace(b'native grid fixture',b'\xff')
    data=gzip.compress(original,mtime=0)
    if damage=='truncated_gzip':data=data[:-5]
    elif damage=='crc':data=data[:-8]+bytes([data[-8]^1])+data[-7:]
    stored=tmp_path/'native.raw.gz';stored.write_bytes(data)
    identity={'expected_raw_sha256':'0'*64 if damage=='raw_sha' else hashlib.sha256(original).hexdigest(),
              'expected_raw_bytes':len(original)+1 if damage=='raw_bytes' else len(original)}
    with pytest.raises((OSError,ValueError,EOFError)):
        NativeRaw(stored,**identity)


def test_gzip_uses_actual_native_pwl_fixture_and_independent_oracle(tmp_path):
    data=json.loads((Path(__file__).parent/'fixtures/native_interconnect_pwl.json').read_text())
    matrix=np.array(data['native_points']);names=data['variables']
    path=tmp_path/'native.raw';capture(path,matrix[:,0],matrix[:,names.index('a')])
    original=path.read_bytes();stored=path.with_suffix('.raw.gz');stored.write_bytes(gzip.compress(original))
    result=window_statistics(NativeRaw(stored,expected_raw_sha256=hashlib.sha256(original).hexdigest(),
                                     expected_raw_bytes=len(original)),data['window_s'],[('a','b',1000)])[0]
    assert result['avg']==pytest.approx(data['independent_oracle']['avg_a'],rel=1e-12)
    assert result['rms']==pytest.approx(data['independent_oracle']['rms_a'],rel=1e-12)


def test_gzip_binary_op_preserves_real_op_reader_and_plot_refusal(tmp_path):
    import analog_native_em as em
    path=tmp_path/'op.raw.gz'
    original=b'Title: native OP\nPlotname: Operating Point\nFlags: real\nNo. Variables: 1\nNo. Points: 1\nVariables:\n0 v(a) voltage\nBinary:\n'+np.array([1.2],dtype='<f8').tobytes()
    path.write_bytes(gzip.compress(original))
    identity={'expected_raw_sha256':hashlib.sha256(original).hexdigest(),'expected_raw_bytes':len(original)}
    assert em.read_op_capture(path,**identity)=={'a':1.2,'0':0.}
    with pytest.raises(ValueError,match='transient'):window_statistics(NativeRaw(path,**identity),[0,1],[('a','0',1)])


def _bound_op_capture(tmp_path):
    executed=tmp_path/'op.raw';stored=tmp_path/'op.raw.gz'
    original=(b'Title: native OP\nPlotname: Operating Point\nFlags: real\nNo. Variables: 1\n'
              b'No. Points: 1\nVariables:\n0 v(a) voltage\nBinary:\n'+
              np.array([1.2],dtype='<f8').tobytes())
    stored.write_bytes(gzip.compress(original,mtime=0))
    compressed_sha=hashlib.sha256(stored.read_bytes()).hexdigest()
    record={'argv':['ngspice','-r',str(executed)],'outputs':{str(stored):compressed_sha},
            'native_raw':{'executed_path':str(executed),'stored_path':str(stored),
            'encoding':'gzip','sha256':compressed_sha,
            'raw_sha256':hashlib.sha256(original).hexdigest(),'raw_bytes':len(original)}}
    return record,stored,original


def _replay_value(record):
    try:
        selected,identity=__import__('analog_native_waveform').native_capture(record,transient=False)
        return NativeRaw(selected,**identity).row()['a']
    except (OSError,EOFError,ValueError):
        return 'REFUSED'


def test_manifest_bound_gzip_replays_the_exact_original_capture(tmp_path):
    record,_,_=_bound_op_capture(tmp_path)
    assert _replay_value(record)==1.2


def test_legacy_plain_capture_remains_accepted_only_at_its_receipted_identity(tmp_path):
    _,stored,original=_bound_op_capture(tmp_path);plain=tmp_path/'op.raw';plain.write_bytes(original)
    record={'outputs':{str(plain):hashlib.sha256(original).hexdigest()}}
    assert _replay_value(record)==1.2
    plain.write_bytes(original[:-1])
    assert _replay_value(record)=='REFUSED'


@pytest.mark.parametrize('damage',['missing','truncated','crc','stale_archive','raw_source','argv_source'])
def test_capture_identity_counterexamples_fail_closed(tmp_path,damage):
    record,stored,original=_bound_op_capture(tmp_path)
    if damage=='missing':
        stored.unlink()
    elif damage in ('truncated','crc'):
        data=stored.read_bytes()
        stored.write_bytes(data[:-5] if damage=='truncated' else data[:-8]+bytes([data[-8]^1])+data[-7:])
        digest=hashlib.sha256(stored.read_bytes()).hexdigest()
        record['native_raw']['sha256']=digest;record['outputs'][str(stored)]=digest
    elif damage=='stale_archive':
        stored.write_bytes(gzip.compress(original,mtime=1))
    elif damage=='raw_source':
        record['native_raw']['raw_sha256']='0'*64
    else:
        record['argv']=['ngspice','-r',str(tmp_path/'other.raw')]
    assert _replay_value(record)=='REFUSED'
