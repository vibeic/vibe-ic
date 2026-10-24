import json
from pathlib import Path
import sys

import pytest

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


def test_producer_keeps_actual_source_stimulus_and_one_native_analysis(source_case):
    project,settings,work=source_case
    rec,bindings,deck=producer.prepare(project,'unit',settings,work)
    text=deck.read_text()
    assert 'v1 a 0 PWL(0 0 1n 1)' in text
    assert text.count('.control')==1 and '100u' not in text
    assert 'set num_threads=1' in text and f'run {work / "tran.raw"}' in text
    assert text.count('.tran ')==1 and '.temp 105' in text
    assert len(bindings)==1 and bindings[0][2]==1
    assert str(deck) in rec['inputs_before'] and str(project/'rc.spice') in rec['inputs_before']
    assert (work/'interface.sp').is_file() and (work/'post.sp').is_file()


def test_unbound_original_dut_include_is_refused(source_case):
    project,settings,work=source_case
    settings['testbench_dut']=str(project/'wrong.sp')
    with pytest.raises(ValueError,match='original DUT include'):
        producer.prepare(project,'unit',settings,work)


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
