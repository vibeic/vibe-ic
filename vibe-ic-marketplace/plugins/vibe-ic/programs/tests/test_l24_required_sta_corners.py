import json
import pytest
import _audit_receipt as AR
import l24_signoff_evidence_backed_check as G


def fixture(tmp_path,change=None):
    p=tmp_path;native=p/'phase3/stage3/sta';native.mkdir(parents=True)
    docs=p/'phase1/generated_docs';docs.mkdir(parents=True)
    doc={'doc_name':'L24_SIGNOFF','fields':{'signoff_requirements':[{'check':'STA','stated':True,'requirement':'pass','corners':['SS','TT','FF'],'citation':{'document':'input/docs/spec.md','line':1}}]}}
    (docs/'L24_SIGNOFF.json').write_text(json.dumps(doc))
    paths=[]
    for corner in ['SS','TT','FF']:
        if change=='missing-'+corner:continue
        body=f'STA_BASIS: POST_ROUTE_SPEF\nSTA_SIGNOFF_CORNER: {corner}\nSTA_BASIS_LIBERTY: {corner}.lib\nSTA_BASIS_SPEF: design.spef\nworst slack max 0.2\nwns max 0\ntns max 0\nworst slack min 0.1\nwns min 0\n'
        if corner=='FF':
            if change=='prelayout':body=body.replace('POST_ROUTE_SPEF','PRE_LAYOUT')
            if change=='rc-only':body=body.replace('STA_SIGNOFF_CORNER: FF','STA_BASIS_CORNER: min')
            if change=='no-paths':body=body.replace('worst slack min 0.1','worst slack min INF')
            if change=='violated':body=body.replace('wns min 0','wns min -0.2').replace('worst slack min 0.1','worst slack min -0.2')
            if change=='unbound-liberty':body=body.replace('STA_BASIS_LIBERTY: FF.lib\n','')
        f=native/f'{corner}.rpt';f.write_text(body);paths.append(f)
    report={'program':'eda_report_audit:sta','passed':True,'findings':[],'subject':AR.subject_of(paths,relative_to=p)}
    if change=='wrong-producer':report['program']='unrelated'
    if change=='stale':paths[-1].write_text(paths[-1].read_text()+'changed\n')
    if change=='no-binding':report.pop('subject')
    out=p/'reports/phase3/sta/post_route_summary.json';out.parent.mkdir(parents=True);out.write_text(json.dumps(report))
    return p


def run(p):
    report=p/'gate.json';rc=G.main(['l24',str(p),'--json',str(report)])
    return rc,json.loads(report.read_text())


def test_all_required_process_corners_are_backed(tmp_path):
    rc,rep=run(fixture(tmp_path))
    assert rc==0 and rep['requirements'][0]['outcome']=='BACKED'


@pytest.mark.parametrize('case',['missing-SS','missing-FF','prelayout','rc-only','no-paths','violated','unbound-liberty','wrong-producer','stale','no-binding'])
def test_incomplete_or_unbound_corners_refuse_closure(tmp_path,case):
    rc,rep=run(fixture(tmp_path,case))
    assert rc==1 and rep['requirements'][0]['outcome']!='BACKED'


def test_no_corner_requirement_keeps_existing_sta_scope(tmp_path):
    p=fixture(tmp_path,'missing-FF');f=p/'phase1/generated_docs/L24_SIGNOFF.json';d=json.loads(f.read_text());d['fields']['signoff_requirements'][0]['corners']=[];f.write_text(json.dumps(d))
    rc,rep=run(p);assert rc==0 and rep['requirements'][0]['outcome']=='BACKED'
