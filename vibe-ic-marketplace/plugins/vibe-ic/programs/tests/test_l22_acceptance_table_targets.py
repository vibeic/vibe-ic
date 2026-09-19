import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from l22_coverage_goal_emit import run

def emit(tmp_path,text,existing=None):
 d=tmp_path/'input/docs';d.mkdir(parents=True);(d/'verification_plan.md').write_text(text)
 f=tmp_path/'phase1/generated_docs/L22_VERIFICATION_PLAN.json';f.parent.mkdir(parents=True);f.write_text(json.dumps({'fields':{'coverage_goals':existing or []},'extraction_status':'NOT_YET_EXTRACTED'}))
 report=run(tmp_path);return json.loads(f.read_text())['fields']['coverage_goals'],report

def test_original_acceptance_targets(tmp_path):
 text=(Path(__file__).resolve().parents[2]/'tests/phase1_fixtures/acceptance_targets_local/verification_plan.md').read_text()
 goals,_=emit(tmp_path,text)
 assert len(goals)==5
 g=next(x for x in goals if x['name']=='NIST FIPS-180-4 functional')
 assert g['target_pct']==100 and g['criterion']=='100% PASS'
 assert g['source_columns']['absolute fallback']=='4 official + 1000 random'
 assert g['signoff_gate'] is True
 assert all(g['kind']=='coverage_goal' and 'measured' not in g and 'passed' not in g for g in goals)
 assert next(g for g in goals if g['name']=='Mode switch')['source_columns']['範圍']=='INIT SHA-256 → INIT SHA-224 → INIT SHA-256 順序測試'

def test_neutral_scoped_targets_stay_distinct(tmp_path):
 text='| Metric | Acceptance criterion | Population | Sign-off gate |\n|---|---|---|---|\n| Arithmetic | 99% PASS | 40 inputs | yes |\n| Arithmetic | 99% PASS | 20 other inputs | no |\n'
 goals,_=emit(tmp_path,text);assert len(goals)==2
 assert [g['target_pct'] for g in goals]==[99,99]
 assert [g['source_columns']['Population'] for g in goals]==['40 inputs','20 other inputs']
 assert [g['signoff_gate'] for g in goals]==[True,False]

def test_observed_and_nonpercentage_not_promoted(tmp_path):
 text='| Metric | Measured | Population |\n|---|---|---|\n| Arithmetic | 100% PASS | 40 inputs |\n\n| Metric | Acceptance criterion | Population |\n|---|---|---|\n| Delay | < 4 ns | 2 corners |\n| Invalid | 101% PASS | 5 inputs |\n'
 goals,_=emit(tmp_path,text);assert goals==[]

def test_existing_numeric_goal_preserved(tmp_path):
 original={'name':'custom target','target_pct':88,'source':'owner input'}
 goals,_=emit(tmp_path,'No new targets.',[original]);assert goals==[original]
