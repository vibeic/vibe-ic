from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from readme_usage_sequence_extractor import extract_usage_sequence_from_readme as extract

def test_repeat_end_includes_last_continuation():
 seq=extract('1. write DATA = 1\n2. read STATUS\n   write ACK = 1\n3. repeat 1-2\n')[0]
 assert seq['steps'][-1]['repeat_steps']=='1-3'
 assert seq['steps'][2]['source_step']==2

def test_unresolved_repeat_does_not_assert_local_target():
 seq=extract('1. write DATA = 1\n   write START = 1\n2. poll READY until READY = 1\n3. repeat 1-9\n')[0]
 step=seq['steps'][-1]
 assert step['source_repeat_steps']=='1-9'
 assert 'repeat_steps' not in step and 'next_state' not in step

def test_unindented_action_is_not_continuation():
 text='1. write DATA = 1\n2. read STATUS\n3. poll READY until READY = 1\nwrite ACK = 1\n'
 seq=extract(text)[0]
 assert len(seq['steps'])==3 and all('source_step' not in x for x in seq['steps'])
