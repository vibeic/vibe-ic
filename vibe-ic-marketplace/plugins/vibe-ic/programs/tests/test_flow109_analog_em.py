"""SOFTWARE/neutral native comparator controls; no PDK or ADC qualification.

Geometry/extraction/technology fixtures are TEST_ONLY. Actual OP/current and
ordinary execution provenance come solely from the production D58 entry.
"""
import hashlib,json,os,shutil
from pathlib import Path
from types import SimpleNamespace
import pytest
import flow109


def invoke(project):
    args=SimpleNamespace(flow='109',flow109_manifest=project/'manifest.json',flow109_plan_only=False,
                         execution_mode='default',entry_step='D58',exit_step='D58')
    try:
        rc=flow109.prepare_front_door(args,project)
        record=json.loads((project/'reports/flow109/components/D58.json').read_text())
    except flow109.Flow109Error as exc:rc,record=2,{'component_status':exc.code,'reason':str(exc)}
    (project.parent/'observed.json').write_text(json.dumps({'rc':rc,'record':record},indent=2))
    return rc,record


@pytest.fixture
def fresh(tmp_path):
    existing=os.environ.get('D58_EXISTING_CAPTURE')
    if existing:
        project=Path(existing)
        assert project.is_dir()
        return project
    src=Path(os.environ.get('D58_FRESH','/absent-explicit-neutral-input'))
    if not src.is_dir():pytest.skip('explicit neutral native input required')
    project=tmp_path/'project';shutil.copytree(src,project)
    # Absolute include/receipt subjects are produced for this actual project.
    settings=project/'native-settings.json';d=json.loads(settings.read_text())
    d['testbench_dut']=str(project/'phase3/analog/unit/unit.sp')
    settings.write_text(json.dumps(d))
    (project/'testbench.sp').write_text('* TEST_ONLY neutral current comparator\n.include "'+d['testbench_dut']+'"\nVdrive a 0 0.0001\nXdut a 0 unit\n.end\n')
    extract=project/'extraction.json';e=json.loads(extract.read_text())
    e['source_inputs_before']={str(project/'phase3/analog/unit/unit.gds'):hashlib.sha256((project/'phase3/analog/unit/unit.gds').read_bytes()).hexdigest()}
    raw=project/'extracted.sp';e['outputs']={str(raw):hashlib.sha256(raw.read_bytes()).hexdigest()};extract.write_text(json.dumps(e))
    config=project/'input/flow109/D58.json';c=json.loads(config.read_text());c['blocks'][0]['settings']['cases'][0]['native_settings']['sha256']=hashlib.sha256(settings.read_bytes()).hexdigest();config.write_text(json.dumps(c))
    source=project/'limits-source.json';s=json.loads(source.read_text());s['copy']=str(project/'TEST_ONLY_limits.pdf');source.write_text(json.dumps(s))
    return project


@pytest.fixture
def retained(tmp_path):
    p=Path(os.environ.get('D58_RETAINED','/absent-normal-retained-project'))
    if not p.is_dir():pytest.skip('normal producer has not emitted receipt')
    # Reopen the SAME original namespace; only the separate plan is varied.
    config=p/'input/flow109/D58.json';before=config.read_bytes()
    source=p/'limits-source.json';source_before=source.read_bytes()
    yield p
    config.write_bytes(before)
    source.write_bytes(source_before)


def change(project,edit):
    p=project/'input/flow109/D58.json';d=json.loads(p.read_text());edit(d);p.write_text(json.dumps(d))


def test_ordinary_entry_measures_actual_current_against_source_width_limits(fresh):
    rc,r=invoke(fresh)
    assert r['component_status']=='PASS',r
    if os.environ.get('D58_EXISTING_CAPTURE'):assert r['native_started'] is False
    case=r['blocks'][0]['cases'][0]
    assert case['status']=='PASS' and case['graded_segments']==1
    assert case['rating_context']['native_temperature_c']==105
    assert case['pg_voltage_ranges']['a']['max_v']==pytest.approx(.0001)
    assert rc==2 and r['completed'] is False and r['default_row_status']=='NOT_MEASURED'
    target=Path(os.environ['D58_BANK'])
    assert not target.exists()
    shutil.copytree(fresh,target)
    config=target/'input/flow109/D58.json'
    config.write_bytes(Path(r['retained_inputs']).read_bytes())
    (target/'retained-result.json').write_text(json.dumps(r,indent=2))


def test_retained_normal_producer_without_new_native(retained):
    rc,r=invoke(retained)
    assert r['component_status']=='PASS',r
    assert r['native_started'] is False and rc==2


@pytest.mark.parametrize('damage',['missing_limits','missing_geometry','missing_launch','foreign_image','missing_required_case','missing_temperature','changed_current','changed_width','changed_limit'])
def test_unbound_or_incomplete_current_geometry_conditions_do_not_PASS(retained,damage):
    def edit(d):
        s=d['blocks'][0]['settings'];c=s['cases'][0]
        if damage=='missing_limits':s['limits_source']='absent.pdf-receipt.json'
        elif damage=='missing_geometry':c['geometry']='absent-geometry.jsonl'
        elif damage=='missing_launch':c['launch']['path']=str(retained/'absent-launch.json')
        elif damage=='missing_required_case':s['required_cases'].append('declared-extra-mission')
        elif damage=='changed_limit':
            pdf=retained/'changed.pdf';pdf.write_bytes(b'not the bound source PDF');s['limits_source']='limits-source.json';m=json.loads((retained/'limits-source.json').read_text());m['copy']=str(pdf);(retained/'limits-source.json').write_text(json.dumps(m))
        else:
            original=Path(c['receipt']);rec=json.loads(original.read_text());copy=retained/'TEST_ONLY-modified-receipt.json'
            if damage=='foreign_image':rec['native_launch']['image']='sha256:'+'f'*64
            elif damage=='missing_temperature':rec['source_binding']['conditions'].pop('temperature_c',None);rec['analysis']['temperature_c']=None
            elif damage=='changed_width':
                g=retained/'TEST_ONLY-geometry.jsonl';lines=Path(c['geometry']).read_text().splitlines();row=json.loads(lines[1]);row['width_grid']=1;lines[1]=json.dumps(row);g.write_text('\n'.join(lines)+'\n');c['geometry']=str(g)
            elif damage=='changed_current':
                source=next(p for p in rec['outputs'] if p.endswith('/currents.jsonl'));q=retained/'TEST_ONLY-current.jsonl';q.write_text(Path(source).read_text().replace('0.000', '1.000'));rec['outputs'].pop(source);rec['outputs'][str(q)]=hashlib.sha256(q.read_bytes()).hexdigest()
            if damage!='changed_width':
                copy.write_text(json.dumps(rec));c['receipt']=str(copy)
    change(retained,edit);_,r=invoke(retained)
    assert r['component_status']=='NOT_MEASURED',r
    assert r['completed'] is False
    text=json.dumps(r)
    expected={'missing_limits':'D58_MEASURED_INPUT_FOREIGN_OR_ABSENT',
              'missing_geometry':'D58_MEASURED_INPUT_FOREIGN_OR_ABSENT',
              'missing_launch':'D58_ORIGINAL_LAUNCH_ABSENT_OR_STALE',
              'foreign_image':'FLOW109_D23_ORIGINAL_LAUNCH',
              'missing_required_case':'declared mission cases absent',
              'missing_temperature':'D58_ORIGINAL_RECEIPT_CHANGED',
              'changed_current':'D58_ORIGINAL_RECEIPT_CHANGED',
              'changed_width':'D58_CURRENT_GEOMETRY_OR_EXTRACTION_UNBOUND',
              'changed_limit':'foundry limit PDF differs from source receipt'}
    assert expected[damage] in text,text
    if damage=='missing_required_case':
        assert r['blocks'][0]['cases'][0]['status']=='PASS'
        assert r['blocks'][0]['cases'][1]['missing_cases']==['declared-extra-mission']


def test_missing_cases_is_not_zero_current_PASS(retained):
    change(retained,lambda d:d['blocks'][0]['settings'].update(cases=[]))
    _,r=invoke(retained)
    assert r['component_status']=='NOT_MEASURED'


def limits_pdf(path, current_ma, temperature):
    """Actual TEST_ONLY PDF source; same existing parser, no pdftotext mock."""
    lines=['TEST_ONLY comparator, no process qualification','2.15 Maximum Current Densities',
           f'(11 years @{temperature} C)',f'Metal2 IMAXM2 mA {current_ma} A.v w = 0.2 ... 0.3 um',
           '2.16 Layer Thickness']
    stream='BT /F1 10 Tf 40 760 Td '+' 0 -16 Td '.join('('+s+') Tj' for s in lines)+' ET'
    objects=['<< /Type /Catalog /Pages 2 0 R >>','<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
             '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
             '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
             f'<< /Length {len(stream)} >>\nstream\n{stream}\nendstream']
    data=b'%PDF-1.4\n';offsets=[]
    for i,obj in enumerate(objects,1):
        offsets.append(len(data));data+=f'{i} 0 obj\n{obj}\nendobj\n'.encode()
    start=len(data)
    data+=('xref\n0 6\n0000000000 65535 f \n'+''.join(f'{n:010d} 00000 n \n' for n in offsets)+f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n').encode()
    path.write_bytes(data)


def lower_limit(project,temperature=105):
    pdf=project/'TEST_ONLY-lower-limit.pdf';limits_pdf(pdf,.01,temperature)
    source=project/'TEST_ONLY-lower-source.json'
    source.write_text(json.dumps({'copy':str(pdf),'sha256':hashlib.sha256(pdf.read_bytes()).hexdigest(),
                                  'scope':'TEST_ONLY comparator source, no PDK qualification'}))
    change(project,lambda d:d['blocks'][0]['settings'].update(limits_source=str(source)))


def test_bound_native_current_above_changed_explicit_source_limit_is_FAIL(retained):
    lower_limit(retained)
    _,r=invoke(retained)
    assert r['component_status']=='FAIL',r
    case=r['blocks'][0]['cases'][0]
    assert case['violations'][0]['current_mA']==pytest.approx(.1/1.0005)
    assert case['violations'][0]['limit_mA']==.01
    assert r['default_row_status']=='FAIL'
    assert r['flow109_acceptance']=='FAIL'
    assert r['whole_flow_acceptance']=='NOT_MEASURED'


def test_source_rating_other_temperature_is_unmeasured_not_qualified_PASS(retained):
    lower_limit(retained,temperature=125)
    # Use an under-limit source to isolate temperature qualification.
    pdf=retained/'TEST_ONLY-temperature.pdf';limits_pdf(pdf,.6,125)
    src=retained/'TEST_ONLY-temperature-source.json';src.write_text(json.dumps({'copy':str(pdf),'sha256':hashlib.sha256(pdf.read_bytes()).hexdigest()}))
    change(retained,lambda d:d['blocks'][0]['settings'].update(limits_source=str(src)))
    _,r=invoke(retained)
    assert r['component_status']=='NOT_MEASURED',r
    case=r['blocks'][0]['cases'][0]
    assert case['numeric_status']=='PASS'
    assert case['rating_context']['qualification_status']=='NOT_MEASURED'


def test_qualified_earlier_violation_survives_later_missing_original_provenance(retained):
    lower_limit(retained)
    def edit(d):
        s=d['blocks'][0]['settings'];c=dict(s['cases'][0]);c['name']='later-case';c['launch']={'path':str(retained/'absent-launch'),'sha256':'0'*64};s['cases'].append(c);s['required_cases'].append('later-case')
    change(retained,edit);_,r=invoke(retained)
    assert r['component_status']=='FAIL',r
    assert r['blocks'][0]['cases'][0]['status']=='FAIL'
    assert any(c['status']=='NOT_MEASURED' for c in r['blocks'][0]['cases'])


def test_real_installed_converter_refuses_invalid_pdf_bytes(tmp_path):
    import analog_native_em as em
    import subprocess
    bad=tmp_path/'invalid.pdf';bad.write_bytes(b'TEST_ONLY invalid PDF, not a limit document')
    with pytest.raises(subprocess.CalledProcessError):
        em._limit_document_text(bad,hashlib.sha256(bad.read_bytes()).hexdigest(),tmp_path)


def test_real_conversion_rejects_source_changed_after_tool_read(tmp_path,monkeypatch):
    import analog_native_em as em
    pdf=tmp_path/'source.pdf';limits_pdf(pdf,.6,105)
    digest=hashlib.sha256(pdf.read_bytes()).hexdigest();original=em.subprocess.run
    def convert_then_mutate(*args,**kwargs):
        result=original(*args,**kwargs)
        pdf.write_bytes(pdf.read_bytes()+b'\n% TEST_ONLY late mutation\n')
        return result
    monkeypatch.setattr(em.subprocess,'run',convert_then_mutate)
    with pytest.raises(ValueError,match='limit PDF or extraction executable changed'):
        em._limit_document_text(pdf,digest,tmp_path)


@pytest.mark.parametrize('prior_status,limit_ma,expected_status',[
    ('FAIL',.01,'FAIL'),('PASS',.6,'NOT_MEASURED')])
def test_actual_grade_late_pdf_loss_preserves_failure_only(
        retained,tmp_path,monkeypatch,prior_status,limit_ma,expected_status):
    """Actual converter/grader first; remove only the writable TEST_ONLY PDF."""
    import analog_native_em as em
    import uuid
    identity=uuid.uuid4().hex
    pdf=retained/'input'/('TEST_ONLY-late-pdf-loss-'+identity+'.pdf')
    source=pdf.with_suffix('.source.json')
    limits_pdf(pdf,limit_ma,105)
    source.write_text(json.dumps({'copy':str(pdf),
        'sha256':hashlib.sha256(pdf.read_bytes()).hexdigest(),
        'scope':'TEST_ONLY late loss of review-copy PDF; no process qualification'}))
    change(retained,lambda d:d['blocks'][0]['settings'].update(limits_source=str(source)))
    real_run=em.run;observed=[]
    def grade_then_remove(*args,**kwargs):
        answer=real_run(*args,**kwargs)
        assert answer['status']==prior_status,answer
        assert answer['cases'][0]['rating_context']['qualification_status']=='PASS'
        (tmp_path/'actual_grade_before_pdf_loss.json').write_text(json.dumps(answer,indent=2))
        observed.append(answer['status'])
        pdf.unlink()
        return answer
    monkeypatch.setattr(em,'run',grade_then_remove)
    args=SimpleNamespace(flow='109',flow109_manifest=retained/'manifest.json',
        flow109_plan_only=False,execution_mode='default',entry_step='D58',exit_step='D58')
    rc=flow109.prepare_front_door(args,retained)
    result=json.loads((retained/'reports/flow109/components/D58.json').read_text())
    (tmp_path/'actual_ordinary_result.json').write_text(json.dumps({'rc':rc,'result':result},indent=2))
    assert observed==[prior_status] and not pdf.exists()
    assert result['component_status']==expected_status,result
    assert result['default_row_status']==expected_status
    assert result['flow109_acceptance']==expected_status
    assert result['native_started'] is False
    assert result['whole_flow_acceptance']=='NOT_MEASURED'
    assert rc==(1 if prior_status=='FAIL' else 2)
    block=result['blocks'][0]
    assert pdf.name in json.dumps(block)
    if prior_status=='FAIL':
        assert block['cases'][0]['status']=='FAIL'
        assert block['cases'][0]['violations'][0]['current_mA']==pytest.approx(.1/1.0005)
        assert block['input_provenance']['status']=='NOT_MEASURED'
        assert block['input_provenance']['reason']=='D58_LIMIT_SOURCE_CHANGED'
