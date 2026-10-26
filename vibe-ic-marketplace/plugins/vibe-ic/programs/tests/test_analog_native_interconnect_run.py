import json
import gzip
import os
from pathlib import Path
import sys
import importlib.util
import types

import pytest

# The separately owned EM residual is intentionally absent on this source base.
# This module-level placeholder exposes no behavior; focused storage tests below
# exercise only this task's producer and canonical waveform consumer.
if importlib.util.find_spec('analog_native_em') is None:
    sys.modules['analog_native_em']=types.ModuleType('analog_native_em')
import analog_native_interconnect_run as producer


def put(path,text):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text);return path


@pytest.fixture
def source_case(tmp_path):
    project=tmp_path/'project';b=project/'phase3/analog/unit'
    source=put(b/'unit.sp','.subckt unit a b\nRcore a b 1\n.ends unit\n')
    put(b/'topology.json',json.dumps({'ports':['a','b']}))
    raw=put(project/'rc.spice','.subckt unit__em a b\nR0 a b 1\n.ends unit__em\n')
    h={'reader_resistance_offset_ohm':0,'zero_resistance':'ideal-equivalence','resist_scale':1000}
    r={'node_a':'a','node_b':'b','resistance_ohm':1,'ext_resistance_value':1,'ideal_short':False}
    geom=put(project/'geometry.jsonl',json.dumps(h)+'\n'+json.dumps(r)+'\n')
    tb=put(project/'source.sp',f'.include "{source}"\nv1 a 0 PWL(0 0 1n 1)\nxdut a b unit\n.control\ntran 1n 100u\n.endc\n.end\n')
    binary=put(project/'selected-ngspice','selected native binary fixture')
    receipt=put(project/'extract.json','{}')
    settings={'spice':str(raw),'geometry':str(geom),'testbench':str(tb),'model_view':str(source),
              'ngspice_bin':str(binary),'native_subckt':'unit__em','testbench_dut':str(source),
              'extraction_receipt':str(receipt),'analysis':{'kind':'TRAN','step_s':1e-9,
              'stop_s':2e-6,'start_s':0,'temperature_c':105,'window_s':[1e-6,2e-6]}}
    work=project/'study';work.mkdir();producer.write(work/'settings.json',settings)
    return project,settings,work


def test_producer_keeps_actual_source_stimulus_and_one_native_analysis(source_case,monkeypatch):
    project,settings,work=source_case
    monkeypatch.setattr(producer.em,'bind_native_resistors',
        lambda header,rows,text:[(['R0','a','b','1'],rows[0],1.0)],raising=False)
    rec,bindings,deck=producer.prepare(project,'unit',settings,work)
    text=deck.read_text()
    assert 'v1 a 0 PWL(0 0 1n 1)' in text
    assert text.count('.control')==1 and '100u' not in text
    assert 'set num_threads=1' in text and 'run tran.raw\n' in text
    assert text.count('.tran ')==1 and '.temp 105' in text
    assert len(bindings)==1 and bindings[0][2]==1
    assert str(deck) in rec['inputs_before'] and str(project/'rc.spice') in rec['inputs_before']
    assert (work/'interface.sp').is_file() and (work/'post.sp').is_file()


def test_unbound_original_dut_include_is_refused(source_case):
    project,settings,work=source_case
    settings['testbench_dut']=str(project/'wrong.sp')
    with pytest.raises(ValueError,match='original DUT include'):
        producer.prepare(project,'unit',settings,work)


@pytest.mark.parametrize('kind,filename',[('TRAN','tran.raw'),('OP','op.raw')])
def test_native_run_filename_preserves_uppercase_space_work_directory(source_case,kind,filename):
    project,settings,_=source_case
    work=project/'MixedCase with spaces';work.mkdir()
    settings['analysis']['kind']=kind
    producer.write(work/'settings.json',settings)
    rec,_,deck=producer.prepare(project,'unit',settings,work)
    control=deck.read_text().split('.control\n',1)[1]
    assert 'run '+filename+'\n' in control
    assert str(work) not in control
    assert Path(rec['deck']).parent==work


@pytest.mark.parametrize('method',['gear','trap'])
def test_explicit_standard_method_controls_effective_deck_and_metadata(source_case,method):
    project,settings,work=source_case
    tb=Path(settings['testbench'])
    tb.write_text('.options method=trap reltol=1e-6 vntol=1e-8 abstol=1e-15\n'+tb.read_text())
    settings['native_options']=['klu=1','method='+method,'maxord=2']
    rec,_,deck=producer.prepare(project,'unit',settings,work)
    text=deck.read_text()
    assert rec['solver']['method']==method
    assert text.rfind('.options method='+method)>text.index('.options method=trap reltol=1e-6')
    assert '.options klu=1' in text and '.options maxord=2' in text
    assert 'reltol=1e-6 vntol=1e-8 abstol=1e-15' in text
    assert 'v1 a 0 PWL(0 0 1n 1)' in text and text.count('.tran ')==1


@pytest.mark.parametrize('option',['method=euler','method=1','method=gear maxord=2',
                                  'method=gear;gshunt=1','method=gear\n.options gshunt=1'])
def test_unsupported_method_and_option_injection_refused(source_case,option):
    project,settings,work=source_case
    settings['native_options']=[option]
    with pytest.raises(ValueError,match='method=gear'):
        producer.prepare(project,'unit',settings,work)
    assert not (work/'op.sp').exists()


def test_execution_command_is_durable_before_metadata_processing(tmp_path):
    result=producer.execute([sys.executable,'-c','print("native transport control")'],tmp_path,'',{},
                            3,tmp_path/'native.log')
    assert result['returncode']==0
    journal=json.loads((tmp_path/'native-command.json').read_text())
    assert journal['argv']==result['argv']
    assert 'native transport control' in (tmp_path/'native.log').read_text()


@pytest.mark.parametrize('fatal',[False,True])
def test_run_retains_native_environment_and_terminal_failure_without_serializing_scanner_sets(source_case,monkeypatch,fatal):
    import numpy as np
    project,settings,work=source_case
    settings.update(analysis={'kind':'OP','temperature_c':105},timeout_s=10,
                    environment={'PDK':'declared_process','PDK_ROOT':'/native/pdks'})
    producer.write(work/'settings.json',settings)
    monkeypatch.setattr(producer,'native_hashes',lambda *a:{})
    def execute(command,directory,container,environment,seconds,log,capture,budget):
        assert environment['PDK']=='declared_process' and environment['OMP_NUM_THREADS']=='1'
        (work/'native.log').write_text(';;RESIDUAL_FAIL actual solver refusal\n' if fatal else
                                     'Doing analysis at TEMP = 105\nNo. of Data Rows : 1\n')
        if not fatal:
            capture.write_bytes(b'Title: native OP\nPlotname: Operating Point\nFlags: real\nNo. Variables: 2\nNo. Points: 1\nVariables:\n0 v(a) voltage\n1 v(b) voltage\nBinary:\n'+np.array([.001,0],dtype='<f8').tobytes())
        return {'argv':list(map(str,command)),'returncode':1 if fatal else 0,'capture_budget_exceeded':False}
    monkeypatch.setattr(producer,'execute',execute)
    result=producer.run(project,'unit',settings,work,'native')
    assert result['status']==('FAIL' if fatal else 'PASS')
    assert (work/'native-execution.json').is_file()
    saved=json.loads((work/'command.json').read_text())
    assert saved['returncode']==(1 if fatal else 0)
    if not fatal:assert saved['measured_segments']==1


@pytest.mark.parametrize('fatal,expected',[(False,'NOT_MEASURED'),(True,'FAIL')])
def test_bounded_stop_is_incomplete_but_actual_residual_failure_stays_fail(source_case,monkeypatch,fatal,expected):
    project,settings,work=source_case
    settings.update(analysis={'kind':'OP','temperature_c':105},timeout_s=10)
    producer.write(work/'settings.json',settings)
    monkeypatch.setattr(producer,'native_hashes',lambda *a:{})
    def execute(*args):
        (work/'native.log').write_text(';;RESIDUAL_FAIL actual solver refusal\n' if fatal else
                                     'Simulation interrupted.\n')
        # A vanished source still cannot demote an actual native refusal.
        (project/'phase3/analog/unit/unit.sp').unlink()
        return {'argv':[],'returncode':124,'capture_budget_exceeded':True}
    monkeypatch.setattr(producer,'execute',execute)
    result=producer.run(project,'unit',settings,work,'native')
    assert result['status']==expected and result['unchanged'] is False
    assert (work/'native-execution.json').is_file()


def storage_run(source_case,monkeypatch,*,scratch=False,fatal=False,after_capture=None):
    import numpy as np
    project,settings,work=source_case
    settings.update(analysis={'kind':'OP','temperature_c':105},timeout_s=10,compress_raw=True)
    ram=project/'host-ram';ram.mkdir();monkeypatch.setattr(producer,'RAW_RAM_ROOT',ram)
    if scratch:
        target=project/'visible-native-scratch';target.mkdir();settings['raw_scratch_dir']=str(target)
    producer.write(work/'settings.json',settings)
    monkeypatch.setattr(producer,'native_hashes',lambda container,paths:{p:producer.sha(p) for p in paths})
    original=(b'Title: binary native OP\nPlotname: Operating Point\nFlags: real\nNo. Variables: 2\n'
              b'No. Points: 1\nVariables:\n0 v(a) voltage\n1 v(b) voltage\nBinary:\n'
              +np.array([.001,0],dtype='<f8').tobytes())
    def execute(command,directory,container,environment,seconds,log,capture,budget):
        assert command[command.index('-r')+1]==work/'op.raw'
        assert 'run op.raw\n' in (work/'op.sp').read_text()
        assert capture.is_symlink() is scratch
        capture.write_bytes(original)
        (work/'native.log').write_text(';;RESIDUAL_FAIL actual solver refusal\n' if fatal else
                                     'Doing analysis at TEMP = 105\nNo. of Data Rows : 1\n')
        if after_capture:after_capture(capture)
        return {'argv':list(map(str,command)),'returncode':1 if fatal else 0,'capture_budget_exceeded':False}
    monkeypatch.setattr(producer,'execute',execute)
    return producer.run(project,'unit',settings,work,'native'),original


@pytest.mark.parametrize('scratch',[False,True])
def test_completed_raw_is_losslessly_stored_and_current_before_owned_scratch_cleanup(source_case,monkeypatch,scratch):
    project,_,work=source_case
    record,original=storage_run(source_case,monkeypatch,scratch=scratch)
    assert record['status']=='PASS' and record['measured_segments']==1
    metadata=record['native_raw'];stored=Path(metadata['stored_path'])
    assert stored==work/'op.raw.gz' and gzip.decompress(stored.read_bytes())==original
    assert metadata['raw_sha256']==__import__('hashlib').sha256(original).hexdigest()
    assert metadata['raw_bytes']==len(original) and metadata['sha256']==producer.sha(stored)
    assert record['outputs'][str(stored)]==metadata['sha256']
    assert not os.path.lexists(work/'op.raw') and not list((project/'host-ram').iterdir())
    if scratch:assert not list((project/'visible-native-scratch').iterdir())
    saved=json.loads((work/'command.json').read_text())
    assert saved==record and json.loads((work/'raw-storage-cleanup.json').read_text())['ram_removed']
    from analog_native_waveform import native_capture,NativeRaw
    selected,identity=native_capture(saved,transient=False)
    assert NativeRaw(selected,**identity).row()=={'a':.001,'b':0.,'0':0.}


@pytest.mark.parametrize('fatal',[False,True])
def test_ssd_copy_failure_preserves_verified_ram_archive_and_native_failure_precedence(source_case,monkeypatch,fatal):
    project,_,work=source_case
    original_copy=producer.shutil.copyfileobj
    def fail_ssd(source,target,*args):
        if str(getattr(target,'name','')).endswith('.gz.copy'):raise OSError('bounded SSD full control')
        return original_copy(source,target,*args)
    monkeypatch.setattr(producer.shutil,'copyfileobj',fail_ssd)
    record,original=storage_run(source_case,monkeypatch,scratch=True,fatal=fatal)
    assert record['status']==('FAIL' if fatal else 'NOT_MEASURED')
    recovery=json.loads((work/'raw-storage-ram.json').read_text())
    ram=Path(recovery['ram_gzip'])
    assert gzip.decompress(ram.read_bytes())==original
    assert producer._gzip_identity(ram)==(recovery['raw_sha256'],len(original))
    assert not (work/'raw-storage-cleanup.json').exists() and not (work/'op.raw.gz').exists()
    assert 'SSD full' in record['raw_storage_error']
    assert (work/'native-execution.json').is_file() and (work/'command.json').is_file()


def test_ram_compression_failure_keeps_original_native_raw_and_recovery_journal(source_case,monkeypatch):
    _,_,work=source_case
    def fail(*args):raise OSError('bounded RAM write control')
    monkeypatch.setattr(producer.shutil,'copyfileobj',fail)
    record,original=storage_run(source_case,monkeypatch,scratch=True)
    assert record['status']=='NOT_MEASURED' and (work/'op.raw').read_bytes()==original
    journal=json.loads((work/'raw-storage-start.json').read_text())
    assert journal['phase']=='COMPRESSING' and Path(journal['real_native_path']).read_bytes()==original
    assert not (work/'raw-storage-ram.json').exists()


@pytest.mark.parametrize('fatal',[False,True])
def test_truncated_ram_archive_is_bounded_and_never_removes_original_raw(source_case,monkeypatch,fatal):
    _,_,work=source_case;identity=producer._gzip_identity
    def truncated(path):
        path.write_bytes(path.read_bytes()[:-5])
        return identity(path)
    monkeypatch.setattr(producer,'_gzip_identity',truncated)
    record,original=storage_run(source_case,monkeypatch,scratch=True,fatal=fatal)
    assert record['status']==('FAIL' if fatal else 'NOT_MEASURED')
    assert (work/'op.raw').read_bytes()==original
    assert (work/'raw-storage-start.json').is_file() and not (work/'raw-storage-ram.json').exists()
    assert 'raw_storage_error' in record


@pytest.mark.parametrize('replacement',['alias','target'])
def test_changed_owned_alias_or_target_is_refused_without_deleting_foreign_bytes(source_case,monkeypatch,replacement):
    project,_,work=source_case;foreign=project/'foreign.raw';foreign.write_bytes(b'foreign bytes')
    def replace(capture):
        if replacement=='alias':capture.unlink();capture.symlink_to(foreign)
        else:
            target=capture.resolve();target.unlink();target.symlink_to(foreign)
    record,_=storage_run(source_case,monkeypatch,scratch=True,after_capture=replace)
    assert record['status']=='NOT_MEASURED' and foreign.read_bytes()==b'foreign bytes'
    assert 'changed' in record['raw_storage_error']
    assert not (work/'op.raw.gz').exists()


@pytest.mark.parametrize('options',[
    {'compress_raw':1},{'compress_raw':'true'},{'raw_scratch_dir':'scratch'},
    {'compress_raw':True,'raw_scratch_dir':'missing'},
    {'compress_raw':True,'raw_scratch_dir':False},
])
def test_invalid_raw_storage_setting_refuses_before_native(source_case,monkeypatch,options):
    project,settings,work=source_case;settings.update(options)
    monkeypatch.setattr(producer,'execute',lambda *args:pytest.fail('native must not execute'))
    with pytest.raises(ValueError):producer.run(project,'unit',settings,work,'native')
    assert not (work/'native-execution.json').exists()


def test_native_scratch_must_be_visible_and_existing_target_is_never_overwritten(tmp_path,monkeypatch):
    scratch=tmp_path/'scratch';scratch.mkdir();work=tmp_path/'work';work.mkdir();capture=work/'op.raw'
    monkeypatch.setattr(producer,'native_hashes',lambda *args:{})
    with pytest.raises(ValueError,match='not visible'):producer._capture_target(capture,scratch,'native')
    assert capture.is_symlink() and capture.resolve().is_file()
    with pytest.raises(ValueError,match='already exists'):producer._capture_target(capture,scratch,'native')


def test_owned_storage_losslessly_retains_a_real_in_repo_artifact(tmp_path,monkeypatch):
    from _hostpaths import require_repo
    source=require_repo('vibe-ic-marketplace','plugins','vibe-ic','programs',
                        'analog_a7_post_layout_emit.py')
    monkeypatch.setattr(producer,'RAW_RAM_ROOT',tmp_path/'ram');producer.RAW_RAM_ROOT.mkdir()
    work=tmp_path/'work';work.mkdir();capture=work/'op.raw'
    state=producer._capture_target(capture,None,'');original=source.read_bytes();capture.write_bytes(original)
    metadata,compressed,state=producer._store_raw(state,work)
    assert gzip.decompress(Path(metadata['stored_path']).read_bytes())==original
    assert metadata['raw_sha256']==__import__('hashlib').sha256(original).hexdigest()
    assert metadata['raw_bytes']==len(original)
    producer._cleanup_raw_storage((metadata,compressed,state),work)
    assert json.loads((work/'raw-storage-cleanup.json').read_text())['ram_removed'] is True
