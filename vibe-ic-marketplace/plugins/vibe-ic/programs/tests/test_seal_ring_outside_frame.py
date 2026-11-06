"""Outside frames exercise the native producer, both adapters and its consumers."""
from __future__ import annotations

import importlib.util
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import _klayout_launch as KL
import _owner_declared as OD
import _tapeout_declaration as TD
import die_finishing_gen as DFG
import die_finishing_check as DFC
import general_precheck as GP


class NativeRunner:
    kind = 'test'
    detail = 'native neutral generator'
    calls = None

    def __init__(self):
        self.calls = []

    def covers(self, path):
        return True

    def exists(self, path):
        return Path(path).is_file()

    def cpath(self, path):
        return str(path)

    def klayout_bin(self):
        return 'klayout'

    def run_argv(self, argv, env, timeout=1800):
        self.calls.append(list(argv))
        if '-r' in argv:
            at = argv.index('-r')
            argv = [sys.executable, argv[at + 1], *argv[at + 2:]]
        cp = subprocess.run(list(map(str, argv)), capture_output=True, text=True,
                            env={**os.environ, **env})
        return cp.returncode, cp.stdout, cp.stderr

    def run(self, script, env, path_keys=(), timeout=1800):
        return self.run_argv([sys.executable, str(script)], env, timeout)


# Neutral technology: a 3 um edge box followed by a 5 um annular band.
GENERATOR = '''import json,sys,pya
args=sys.argv[1:]
if '-rd' in args:
    a=dict(v.split('=',1) for k,v in zip(args[::2],args[1::2]))
    src,dst=a['input'],a['output']
    w,h=float(a['height']),float(a['width'])
    x,y=float(a.get('offset_x',0)),float(a.get('offset_y',0))
else:
    a=dict(zip(args[::2],args[1::2]))
    src,dst=a['--input'],a['--output']
    w,h=float(a['--die-width']),float(a['--die-height'])
    x=y=0
ly=pya.Layout();ly.read(src);top=ly.top_cell()
settings=json.load(open(__file__+'.json'))
if settings.get('no_output'):
    sys.exit(0)
if settings.get('ignore_offset'):
    x=y=0
u=ly.dbu
box=lambda x0,y0,x1,y1:pya.Box(*[round(v/u) for v in (x0,y0,x1,y1)])
outer=pya.Region(box(x,y,x+w,y+h))
g=8 + (1 if settings.get('intrude') and x else 0)
inner=pya.Region(box(x+g,y+g,x+w-g,y+h-g))
physical=pya.Region(box(x+3,y+3,x+w-3,y+h-3))-inner
for poly in physical.each():top.shapes(ly.layer(18,0)).insert(poly)
# A PDK-owned boundary includes the otherwise blank edge box.
if not settings.get('no_boundary'):
    top.shapes(ly.layer(17,0)).insert(box(x,y,x+w,y+h))
options=pya.SaveLayoutOptions();options.gds2_write_timestamps=False
ly.write(dst,options)
'''


def fixture(tmp_path, monkeypatch, placement='outside', form='klayout-rd', **settings):
    pya = pytest.importorskip('pya')
    pnr = tmp_path / 'phase3/stage3/pnr'
    pnr.mkdir(parents=True)
    layout = pya.Layout();layout.dbu = 0.001
    top = layout.create_cell('neutral_top')
    top.shapes(layout.layer(7, 0)).insert(pya.Box(20000,20000,30000,30000))
    gds = pnr / 'neutral_top.gds'
    options=pya.SaveLayoutOptions();options.gds2_write_timestamps=False
    layout.write(str(gds),options)
    (pnr/'routed.def').write_text('VERSION 5.8 ;\nDESIGN neutral_top ;\n'
        'UNITS DISTANCE MICRONS 1000 ;\nDIEAREA ( 0 0 ) ( 120000 80000 ) ;\nEND DESIGN\n')
    doc = TD.blank_declaration()
    doc['answers'].update(deliverable='DIE', die_area_um=[0,0,120,80],
        die_origin_um=[0,0], seal_ring_required=True)
    if placement is not None:
        doc['answers']['seal_ring_placement'] = placement
    else:
        doc['answers'].pop('seal_ring_placement',None)
    OD.attest(doc)
    declaration = tmp_path/TD.DECLARATION_REL
    declaration.parent.mkdir(parents=True);declaration.write_text(json.dumps(doc))
    script=tmp_path/'neutral_seal.py';script.write_text(GENERATOR)
    Path(str(script)+'.json').write_text(json.dumps(settings))
    runner=NativeRunner()
    monkeypatch.setattr(KL,'find_runner',lambda *a,**k:runner)
    return gds,script,runner,form


def run(project, item, module=DFG):
    gds,script,runner,form=item
    return module.run(project,str(gds),str(script),form,'neutral',None,None,
        sys.executable,None,None,None,None,True,None)


def base_module():
    # The control uses the pinned base implementation at the same project path.
    base=os.environ.get('SEAL_BASE_PROGRAMS')
    if not base:
        pytest.skip('byte control requires explicit SEAL_BASE_PROGRAMS')
    spec=importlib.util.spec_from_file_location('seal_control_base',Path(base)/'die_finishing_gen.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('placement',[None,'inside'])
@pytest.mark.parametrize('no_boundary',[False,True])
def test_inside_and_absent_argv_and_report_are_byte_identical_to_base(tmp_path,monkeypatch,placement,no_boundary):
    item=fixture(tmp_path,monkeypatch,placement=placement,form='pya-cli',no_boundary=no_boundary)
    # Both successful and failing inside results are byte controls.
    original=item[0].read_bytes();old=run(tmp_path,item,base_module())
    report=tmp_path/DFG._REPORT_REL;before=report.read_bytes()
    item[0].write_bytes(original)
    current=run(tmp_path,item)
    assert current['seal_ring']['state']==('PASS' if no_boundary else 'FAIL')
    assert current['seal_ring']['argv']==old['seal_ring']['argv']
    assert report.read_bytes()==before


def test_outside_measures_edge_box_plus_band_and_offsets_both_axes(tmp_path,monkeypatch):
    item=fixture(tmp_path,monkeypatch)
    result=run(tmp_path,item);seal=result['seal_ring']
    argv=seal.get('argv',[])
    assert 'offset_x=-8.000000' in argv and 'offset_y=-8.000000' in argv,seal
    assert seal['state']=='PASS',seal
    assert seal['frame']['g_um']==8
    assert seal['frame']['declared_die_um']==[0,0,120,80]
    assert seal['frame']['grown_frame_um']==[-8,-8,128,88]
    assert seal['ring_check']['ring_extent']['inner']['um']==[0,0,120,80]
    assert seal['ring_check']['ring_extent']['outer']['um']==[-8,-8,128,88]
    assert 'width=96.000000' in argv and 'height=136.000000' in argv
    assert 'DIEAREA ( -8000 -8000 ) ( 128000 88000 )' in (tmp_path/DFG._DEF_REL).read_text()
    assert DFC.evaluate(tmp_path)['verdict']=='PASS'


def test_generic_cli_merges_only_the_offset_ring_without_moving_core(tmp_path,monkeypatch):
    item=fixture(tmp_path,monkeypatch,form='pya-cli')
    seal=run(tmp_path,item)['seal_ring']
    assert seal['state']=='PASS',seal
    assert seal['ring_check']['ring_extent']['outer']['um']==[-8,-8,128,88]
    pya=pytest.importorskip('pya');layout=pya.Layout();layout.read(str(item[0]))
    assert str(layout.top_cell().dbbox())=='(-8,-8;128,88)'
    core=pya.Region(layout.top_cell().begin_shapes_rec(layout.layer(7,0)))
    assert core.bbox()==pya.Box(20000,20000,30000,30000)


def test_unknown_g_is_named_not_measured_and_emits_no_finished_def(tmp_path,monkeypatch):
    item=fixture(tmp_path,monkeypatch,no_output=True)
    original=item[0].read_bytes();seal=run(tmp_path,item)['seal_ring']
    assert seal['state']=='NOT_MEASURED',seal
    assert seal['rule']=='SEAL_RING_FOOTPRINT_NOT_MEASURED'
    assert item[0].read_bytes()==original
    assert not (tmp_path/DFG._DEF_REL).exists()


@pytest.mark.parametrize('damage,rule',[('ignore_offset','SEAL_RING_DIE_EXTENT_MISMATCH'),
                                      ('intrude','SEAL_RING_INNER_EDGE_INSIDE_DIE')])
def test_extent_guard_rejects_wrong_grown_frame_or_intruding_inner_edge(tmp_path,monkeypatch,damage,rule):
    item=fixture(tmp_path,monkeypatch,**{damage:True})
    original=item[0].read_bytes();seal=run(tmp_path,item)['seal_ring']
    assert seal['state']=='FAIL',seal
    assert seal.get('rule')==rule,seal
    assert not (tmp_path/DFG._DEF_REL).exists()
    assert item[0].read_bytes()==original








def test_precheck_size_and_origin_accept_the_measured_finished_frame(tmp_path,monkeypatch):
    # This is the actual size/origin consumer's observable verdict.
    step=next(s for s in GP.LADDER if s.step_id=='KLayout.CheckSize');ev=GP._blank(step)
    geom={'bbox_um':[-8,-8,128,88],'width_um':136,'height_um':96,'dbu_um':0.001,
          'bbox_complete':True,'bbox_cycles':[],'bbox_missing_cells':[]}
    kw={}
    if 'finished_frame' in inspect.signature(GP._step_size).parameters:
        kw['finished_frame']=[-8,-8,128,88]
    GP._step_size(ev,geom,'DIE',[0,0],[0,0,120,80],**kw)
    assert ev.verdict==GP.PASS,ev.evidence
    assert ev.measured['declared_area_um']==[0,0,120,80]


def test_finished_def_consumer_refuses_the_old_inside_extent(tmp_path,monkeypatch):
    item=fixture(tmp_path,monkeypatch);seal=run(tmp_path,item)['seal_ring']
    assert seal['state']=='PASS',seal
    finished=tmp_path/DFG._DEF_REL
    text=finished.read_text().replace('DIEAREA ( -8000 -8000 ) ( 128000 88000 )',
                                    'DIEAREA ( 0 0 ) ( 120000 80000 )')
    finished.write_text(text)
    assert DFC.evaluate(tmp_path)['verdict']=='FAIL'


def test_legacy_declaration_without_placement_still_validates():
    doc = TD.blank_declaration()
    doc['answers'].pop('seal_ring_placement', None)
    assert TD.validate(doc) == []


def test_registered_choices_are_read_from_the_actual_question_inventory():
    from _hostpaths import require_repo
    flow=require_repo('vibe-ic-marketplace','plugins','vibe-ic','flow','phase1_phase2_phase3.yaml')
    import yaml
    row=next(r for r in yaml.safe_load(flow.read_text())['steps'] if str(r['id'])=='26.5ic')
    assert 'die_finishing_gen' in row['programs']
    question=next((q for q in TD.QUESTIONS if q.key=='seal_ring_placement'),None)
    assert question is not None
    assert set(question.choices)=={'inside','outside'}


def test_general_precheck_consumes_the_finished_outer_frame(tmp_path,monkeypatch):
    item=fixture(tmp_path,monkeypatch);seal=run(tmp_path,item)['seal_ring']
    assert seal['state']=='PASS',seal
    (tmp_path/'phase3/librelane_switch.json').write_text(json.dumps({
        'steps':{s:'direct' for s in ['26','31','34','37']}}))
    monkeypatch.setattr(GP._pdkauth,'resolve_volume',lambda *a,**k:(None,'neutral size-only test',[]))
    result=GP.evaluate(tmp_path,layout=item[0],runner=lambda *a:(2,'unrelated instrument absent',''))
    size=next(s for s in result.steps if s.step_id=='KLayout.CheckSize')
    assert size.verdict==GP.PASS,size.evidence
    assert size.measured['expected_area_um']==[-8,-8,128,88]
    assert size.measured['declared_area_um']==[0,0,120,80]


def test_changed_footprint_measurement_is_refused_by_the_consumer(tmp_path,monkeypatch):
    item=fixture(tmp_path,monkeypatch);seal=run(tmp_path,item)['seal_ring']
    assert seal['state']=='PASS',seal
    measurement=Path(seal['frame']['g_basis']['measurement'])
    measurement.write_text('{}')
    result=DFC.evaluate(tmp_path)
    assert result['verdict']=='FAIL'
    assert 'SEAL_RING_FOOTPRINT_MEASUREMENT_CHANGED' in result['reason']
