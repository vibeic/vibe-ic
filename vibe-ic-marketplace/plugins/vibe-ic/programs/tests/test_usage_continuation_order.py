from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from readme_usage_sequence_extractor import extract_usage_sequence_from_readme as extract

def test_neutral_continuation_and_repeat():
 text='1. write DATA = 7\n2. write MODE = 0\n   write START = 1\n3. poll READY until READY = 1\n4. repeat 1-3\n'
 seqs=extract(text);assert len(seqs)==1;steps=seqs[0]['steps']
 assert [s['action'] for s in steps]==['write DATA = 7','write MODE = 0','write START = 1','poll READY until READY = 1','repeat 1-3']
 assert [s['step'] for s in steps]==list(range(1,6))
 assert steps[-1]['repeat_steps']=='1-4' and steps[-1]['next_state']=='step 1'
 assert steps[-1]['source_repeat_steps']=='1-3'

def test_original_prompt_order_and_repeat():
 text=(Path(__file__).resolve().parents[2]/'tests/phase1_fixtures/usage_continuation_local/register_usage.md').read_text()
 seqs=extract(text);assert len(seqs)==1;steps=seqs[0]['steps'];assert len(steps)==8
 assert 'write ADDR_CTRL bit0 = 1' in steps[3]['action'] and 'OR bit1 = 1' in steps[3]['action']
 assert steps[4]['action_type']=='poll' and steps[6]['action_type']=='read'
 assert steps[7]['repeat_steps']=='2-7' and steps[7]['next_state']=='step 2'
 assert steps[7]['source_repeat_steps']=='2-6'

def test_continuations_do_not_satisfy_numbered_floor():
 assert extract('1. write DATA = 1\n   write MODE = 0\n   write START = 1\n')==[]

def test_unindented_prose_keeps_sequences_separate():
 block='1. write DATA = 1\n2. poll READY until READY = 1\n3. read RESULT\n'
 seqs=extract(block+'Unrelated discussion\n'+block)
 assert len(seqs)==2 and all(len(s['steps'])==3 for s in seqs)

def test_noncommand_indented_prose_not_promoted():
 block='1. write DATA = 1\n2. poll READY until READY = 1\n3. read RESULT\n'
 seqs=extract(block+'   This explains the register layout.\n'+block)
 assert len(seqs)==2 and all(len(s['steps'])==3 for s in seqs)
