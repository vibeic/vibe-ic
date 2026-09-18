"""Input-derived reset semantics; no RTL, oracle, or full Phase1 run."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import phase1_doc_one_shot_runner as D
import l9_l19_contract_carrythrough as C
import l8_clock_reset_waveform_emit as W

CASES=[
 ('original_comparison','| `reset_n` | **同步 reset, active-LOW**(注意:active-LOW,與先前 pilot 的 active-HIGH 相反!)|','reset_n','synchronous','active_low'),
 ('opposite_comparison','| `reset` | synchronous reset, active-HIGH (unlike the previous pilot active-LOW) |','reset','synchronous','active_high'),
 ('async_low','reset_n is asynchronous active-low (unlike the previous synchronous active-high pilot).','reset_n','asynchronous','active_low'),
 ('async_high','reset is asynchronous active-high.','reset','asynchronous','active_high'),
 ('later_declaration','reset_n is an input.\n'+('unrelated text\n'*40)+'reset_n: 同步 reset, active-LOW.','reset_n','synchronous','active_low'),
 ('explicit_over_name','reset_n is synchronous active-high.','reset_n','synchronous','active_high'),
 ('other_port','scan_reset is asynchronous active-high.\nreset_n is synchronous active-low.','reset_n','synchronous','active_low'),
 ('history_first','Previously reset_n was asynchronous active-high.\nreset_n is synchronous active-low.','reset_n','synchronous','active_low'),
]
@pytest.mark.parametrize('case,text,name,sync,polarity',CASES,ids=[x[0] for x in CASES])
def test_reset_producer_and_waveform(case,text,name,sync,polarity):
 l9={'ports':[{'name':name}]}
 D._v1_6_369_emit_reset_domains(l9,{'L2.md':text})
 row=l9['reset_domains'][0]
 assert (row['sync'],row['polarity'])==(sync,polarity)
 projected=W._project({'clocks':[{'name':'clk','period_ns':10}]},l9)
 assert projected['resets'][0]['sync']==sync
 assert projected['resets'][0]['polarity']==polarity
 # Multi-port input is deliberately checked only through the per-port producer.
 if case!='other_port':
  result=C._l9_contract([{'layer':'L2','source':'input/docs/L2.md','status':'','text':'# Reset\n'+text}])
  values=[x['normalized'] for x in result['reset_boot']['normalized_semantics']]
  assert values==[sync+' '+polarity.replace('_','-')]

def test_verbatim_intake_fixture():
 text=(Path(__file__).resolve().parents[2]/'tests/phase1_fixtures/reset_historical_comparison/reset.md').read_text()
 l9={'ports':[{'name':'reset_n'}]}
 D._v1_6_369_emit_reset_domains(l9,{'L2.md':text})
 assert l9['reset_domains'][0]['sync']=='synchronous'
 result=C._l9_contract([{'layer':'L2','source':'input/docs/L2.md','status':'','text':text}])
 values=[x['normalized'] for x in result['reset_boot']['normalized_semantics']]
 assert 'synchronous active-low' in values
 assert 'synchronous active-high' not in values
