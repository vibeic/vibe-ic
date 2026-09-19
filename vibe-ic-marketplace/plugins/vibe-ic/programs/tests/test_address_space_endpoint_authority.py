import json,sys,os,importlib.util
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
if os.environ.get('ENDPOINT_BASE_RUNNER'):
 spec=importlib.util.spec_from_file_location('phase1_doc_one_shot_runner',os.environ['ENDPOINT_BASE_RUNNER'])
 D=importlib.util.module_from_spec(spec);sys.modules[spec.name]=D;spec.loader.exec_module(D)
else:
 import phase1_doc_one_shot_runner as D

HEADER='| Address | Name | R/W | Width | Description |\n|---|---|---|---|---|\n'

@pytest.mark.parametrize('text,expected',[
 ('# Register map\nAddress space 0x00-0xFF; unassigned selectors are reserved.\n'+HEADER+'| 0x00 | CONFIG | R/W | 32 | Configuration word |\n',{'CONFIG':0}),
 ('RAM window 0x1000-0x1FFF.\n',{}),
 ('# Register map\nAddress space 0x00-0xFF.\n'+HEADER+'| 0xFF | MEMMAP_HIGH_000000FF | RO | 32 | Explicitly declared status register |\n',{'MEMMAP_HIGH_000000FF':255}),
],ids=['namedfile_config','window_only','namedfile_explicit_endpoint'])
def test_only_declared_registers(tmp_path,text,expected):
 docs=tmp_path/'input/docs';docs.mkdir(parents=True);(docs/'registers.md').write_text(text)
 artifact=D.gen_l4_regmap(tmp_path,{'registers.md':text}).path
 rows=json.loads(artifact.read_text())['registers']
 got={r.get('name'):r.get('address_int') for r in rows}
 assert got==expected
 assert all(r.get('extraction_strategy')!='memmap_range_prose_v_orch' for r in rows)
