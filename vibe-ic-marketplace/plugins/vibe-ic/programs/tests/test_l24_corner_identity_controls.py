import json
import pytest
import _audit_receipt as AR
from test_l24_required_sta_corners import fixture,run


@pytest.mark.parametrize('case',['missing-TT','path-binding','escape','nan'])
def test_additional_identity_and_measurement_refusals(tmp_path,case):
    p=fixture(tmp_path,'missing-TT' if case=='missing-TT' else None)
    f=p/'reports/phase3/sta/post_route_summary.json';d=json.loads(f.read_text())
    if case=='path-binding':d['subject']['basis']='path'
    elif case=='escape':
        external=p.parent/(p.name+'-outside.rpt');external.write_text((p/'phase3/stage3/sta/FF.rpt').read_text())
        d['subject']=AR.subject_of([external],relative_to=p)
    elif case=='nan':
        native=p/'phase3/stage3/sta/FF.rpt';native.write_text(native.read_text().replace('worst slack min 0.1','worst slack min NaN'))
        d['subject']=AR.subject_of(sorted((p/'phase3/stage3/sta').glob('*.rpt')),relative_to=p)
    f.write_text(json.dumps(d))
    rc,rep=run(p);assert rc==1 and rep['requirements'][0]['outcome']!='BACKED'
