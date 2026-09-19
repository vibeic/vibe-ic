"""Neutral input-derived producer contract; native executor is a CPU test double."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
import phase3_one_shot_runner as p3

@pytest.fixture
def scene(tmp_path, monkeypatch):
    docs=tmp_path/'input/docs'; docs.mkdir(parents=True)
    (docs/'timing.md').write_text('STA sign-off must pass SS, TT and FF corners.\n')
    pnr=tmp_path/'phase3/stage3/pnr';pnr.mkdir(parents=True)
    (pnr/'dut_pnr.v').write_text('module dut(input clk); endmodule\n')
    (pnr/'constraint.sdc').write_text('create_clock -period 12 [get_ports clk]\n')
    spef=tmp_path/'dut.spef';spef.write_text('*SPEF "IEEE 1481-1998"\n')
    libs=tmp_path/'input/pdk/liberty';libs.mkdir(parents=True)
    by={}
    for c in ['ss','tt','ff']:
        f=libs/f'core__{c}_25C_1v00.lib';f.write_text('library(core) {}');by[c.upper()]=str(f)
    ios=[]
    for c in ['ss','tt','ff']:
        f=tmp_path/f'io__{c}_25C_1v00.lib';f.write_text('library(io) {}');ios.append(str(f))
    record=tmp_path/'reports/phase3/io_pad_chip_top.json';record.parent.mkdir(parents=True)
    record.write_text(json.dumps({'io_library_liberty':ios}))
    monkeypatch.setattr(p3,'_resolve_signoff_corner_libs',lambda *a:by)
    monkeypatch.setattr(p3,'_to_container_path',lambda x,*a:str(x))
    monkeypatch.setattr(p3,'_sta_link_top',lambda *a:'dut')
    monkeypatch.setattr(p3,'_discover_aocv_table',lambda *a:None)
    calls=[]; mode={'rc':0,'omit':False,'negative':False,'omit_census':False}
    def run(container,cmd,**kw):
        text=Path(kw['marker']).read_text();calls.append(text)
        out=Path(kw['outputs'][0]);out.parent.mkdir(parents=True,exist_ok=True)
        # Only emulate native reports for sections actually requested by Tcl.
        import re
        sections=re.findall(r'=== (SETUP|HOLD) corner: process=(\w+)',text)
        if not sections:
            out.write_text('worst slack max 1.0\n');return mode['rc'],'',''
        content=''
        for role,corner in sections:
            if mode['omit'] and role=='HOLD':continue
            val=-1 if mode['negative'] else 1
            content+=f'=== {role} corner: process={corner} ===\nworst slack {"max" if role=="SETUP" else "min"} {val}\n'
            # The composed producer also requires the native linked/annotation census.
            # This remains a CPU double; omission must still fail closed.
            if role == 'SETUP' and 'STA_LINK_CENSUS' in text and not mode['omit_census']:
                content += ('STA_LINK_INSTANCE neutral_cell neutral_library/master\n'
                            'STA_LINK_CENSUS total=1 linked=1 missing=0\n'
                            'Found 0 unannotated drivers.\n'
                            'Found 0 partially unannotated drivers.\n')
        with out.open('w' if len(calls)==1 else 'a') as f:f.write(content)
        return mode['rc'],'',''
    monkeypatch.setattr(p3,'_docker_exec',run)
    pdk=SimpleNamespace(liberty=by['TT'],macro_libs=[])
    rpt=tmp_path/'phase3/stage3/sta/sta_spef_based.rpt'
    def emit():return p3._emit_spef_sta(tmp_path,'dut',pdk,'fixture',spef,rpt,[])
    return locals()

def test_all_declared_process_roles_and_input_binding(scene):
    s=scene;assert s['emit']()
    text='\n'.join(s['calls'])
    for c in ['SS','TT','FF']:
        for role in ['SETUP','HOLD']:assert f'=== {role} corner: process={c}' in text
        assert f'read_liberty {{{s["by"][c]}}}' in text
        assert f'io__{c.lower()}_25C_1v00.lib' in text
    for marker in ['STA_BASIS_NETLIST:','STA_BASIS_SDC:','STA_BASIS_SPEF:','STA_BASIS_IO_LIBERTY:']:
        assert marker in text
    assert 'report_worst_slack -min' in text and 'report_worst_slack -max' in text

@pytest.mark.parametrize('missing',['core','io','sdc','spef','netlist'])
def test_missing_declared_input_refused(scene,missing):
    s=scene
    if missing=='core':s['by'].pop('TT')
    elif missing=='io':s['record'].write_text(json.dumps({'io_library_liberty':s['ios'][:1]}))
    else:{'sdc':s['pnr']/'constraint.sdc','spef':s['spef'],'netlist':s['pnr']/'dut_pnr.v'}[missing].unlink()
    assert not s['emit']();assert not s['calls']

def test_missing_hold_native_output_refused(scene):
    scene['mode']['omit']=True
    assert not scene['emit']()

def test_nonzero_native_rc_refused(scene):
    scene['mode']['rc']=1
    assert not scene['emit']()

def test_negative_measurement_preserved(scene):
    scene['mode']['negative']=True
    assert scene['emit']()
    assert '-1' in scene['rpt'].read_text()

def test_ambiguous_io_refused(scene):
    s=scene;other=s['tmp_path']/'duplicate/io__tt_25C_1v00.lib';other.parent.mkdir();other.write_text('library(io) {}')
    s['record'].write_text(json.dumps({'io_library_liberty':s['ios']+[str(other)]}))
    assert not s['emit']();assert not s['calls']


def test_complete_timing_without_native_census_still_refused(scene):
    scene['mode']['omit_census'] = True
    assert not scene['emit']()
    assert not scene['rpt'].exists()
