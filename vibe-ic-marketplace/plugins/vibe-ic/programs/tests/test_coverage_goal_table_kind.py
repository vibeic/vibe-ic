import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from phase1_doc_one_shot_runner import _harvest_test_cases_from_input_tables as harvest

def test_original_coverage_goals_are_not_vectors():
 text=(Path(__file__).resolve().parents[2]/'tests/phase1_fixtures/coverage_goal_table_local/verification_plan.md').read_text()
 rows=harvest({'verification_plan.md':text});assert len(rows)==4
 assert all(r['kind']=='coverage_goal' for r in rows)
 assert all('100%' in r['expected'] and r['stimulus'] for r in rows)

def test_neutral_acceptance_scope_table():
 text='| Test category | Pass criterion | Scope |\n|---|---|---|\n| Random lengths | 99% PASS | 500 independent lengths |\n'
 rows=harvest({'verification_plan.md':text});assert len(rows)==1
 assert rows[0]['kind']=='coverage_goal' and rows[0]['expected']=='99% PASS'

def test_concrete_input_and_result_remain_vector():
 text='| Test | Input | Expected |\n|---|---|---|\n| Arithmetic example | 0x01 | 0x02 |\n'
 row=harvest({'verification_plan.md':text})[0]
 assert row['kind']=='functional_vector' and row['stimulus']=='0x01' and row['expected']=='0x02'

def test_percent_output_is_not_coverage_goal():
 text='| Test | Input | Expected |\n|---|---|---|\n| Duty output | control=1 | 100% PASS |\n'
 row=harvest({'verification_plan.md':text})[0];assert row['kind']=='functional_vector'
