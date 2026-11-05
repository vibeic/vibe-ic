import json
import pytest
import flow109


@pytest.mark.parametrize('declared', [True, False])
def test_ordinary_non_scan_admission_reaches_native_proof_refusal(tmp_path, declared):
    (tmp_path/'input').mkdir()
    if declared:
        (tmp_path/'input/feature-decisions.json').write_text(json.dumps({'dft':{
            'requires_scan':False,
            'reason':'Functional hard macro delivery has no scan architecture or ATPG requirement.'}}))
    result=tmp_path/'reports/flow109/default_rows/D25.json'
    result.parent.mkdir(parents=True)
    result.write_text(json.dumps({'step_id':'D25','default_row_status':'FAIL','completed':False}))
    expected='FLOW109_D25_RESULT_NOT_ACCEPTED' if declared else 'FLOW109_DFT_INTENT_MISSING'
    with pytest.raises(flow109.Flow109Error,match=expected):
        flow109.dft_preroute_admission(tmp_path,{'features':{'requires_dft':False,'requires_scan':False}})
