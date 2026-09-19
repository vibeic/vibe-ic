import pytest
from sta_annotation_population import classify
BODY='STA_LINK_INSTANCE cell lib/master\nSTA_LINK_CENSUS total=1 linked=1 missing=0\nFound 1 unannotated drivers.\n cell/P\nFound 0 partially unannotated drivers.\n'
@pytest.mark.parametrize('statements',[
'- a ( cell P ) + USE POWER ;\n- b ( cell P ) + USE POWER ;',
'- a ( cell P ) + USE POWER ;\n- b ( cell P ) + USE GROUND ;',
'- a ( cell P ) + USE POWER + USE SIGNAL ;'])
def test_conflicting_typed_authority_refused(tmp_path,statements):
 f=tmp_path/'d.def';count=statements.count(';');f.write_text(f'NETS {count} ;\n{statements}\nEND NETS\n')
 assert not classify(BODY,f)['complete']
