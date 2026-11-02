"""Native-PDK producer selection, fallback and non-signoff controls."""
import json
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET
import pytest

import flow109_density_fill as fill
import metal_fill_config_gen as config
from test_flow109_gds_fill_dispatch import case,invoke,put


def native_case(project, broken=False):
    manifest=case(project)
    kit=project/'kit'
    script=kit/'libs.tech/klayout/tech/scripts/filler.py'
    script.parent.mkdir(parents=True)
    script.write_text('import pya\n'+('raise RuntimeError("native negative control")\n' if broken else
        'layout=pya.CellView.active().layout()\n'
        'layout.top_cell().shapes(layout.layer(77,22)).insert(pya.Box(0,0,100,100))\n'
        'layout.write(output_file)\n'))
    meta=project/'input/pdk.json'
    put(meta,{'name':'neutral','root':str(kit)})
    manifest['pdk']=fill._record(project,meta)
    # A native filler must not require a generated metal-only config.
    manifest.pop('rules')
    put(project/fill.INPUT,manifest)
    return script


def test_native_pdk_filler_precedes_generator(tmp_path):
    script=native_case(tmp_path)
    rc,result=invoke(tmp_path)
    assert result['component_status']=='PASS',result
    assert result['engine']['path']==str(script.resolve())
    assert result['execution']['returncode']==0
    assert result['measurements']['added_shapes']['77/22']>0
    assert result['measurements']['density_signoff']=='NOT_MEASURED'
    assert rc==2 and result['default_row_status']=='NOT_MEASURED'
    assert not result['completed']


def test_native_failure_does_not_fall_back_or_mint_pass(tmp_path):
    native_case(tmp_path,broken=True)
    rc,result=invoke(tmp_path)
    assert result['component_status']=='FAIL',result
    assert result['reason']=='D62_PDK_FILL_FAILED'
    assert result['execution']['returncode']!=0
    assert not result['completed'] and result['default_row_status']!='PASS'


def test_pdk_without_native_filler_uses_existing_generator(tmp_path):
    manifest=case(tmp_path)
    kit=tmp_path/'kit';kit.mkdir()
    pdk=tmp_path/'input/pdk.json';put(pdk,{'name':'neutral','root':str(kit)})
    manifest['pdk']=fill._record(tmp_path,pdk);put(tmp_path/fill.INPUT,manifest)
    rc,result=invoke(tmp_path)
    assert result['component_status']=='PASS',result
    assert result['engine']['path'].endswith('/metal_fill/metal_fill.py')
    assert result['emitter_result']['verdict']==result['verify_only']['verdict']=='PASS'
    assert rc==2 and result['default_row_status']=='NOT_MEASURED'


DECK='''chip_area = extent.sized(0.0).area
# Rule LIMIT.a: density
if (sample.area / chip_area) * 100 > 55
  extent.output('LIMIT.a', 'density too high')
end
# Rule FLOOR.a: density
if (other.area / chip_area) * 100 < 35
  extent.output('FLOOR.a', 'density too low')
end
'''

def test_max_only_density_has_no_fill_obligation():
    covered,gaps=config.density_rule_coverage(DECK,[])
    assert gaps=={'FLOOR.a':['other']}
    assert covered=={}


def test_max_symbol_is_check_only_but_min_symbol_keeps_obligation():
    deck='''chip_area = extent.sized(0.0).area
sample_area = sample.area
# Rule LIMIT.a: density
output_global(chip_area, sample_area, :max)
# Rule FLOOR.a: density
output_global(chip_area, sample_area, :min)
'''
    assert config.density_rule_coverage(deck,[])[1]=={'FLOOR.a':['sample']}


def test_max_words_in_comments_or_strings_do_not_exempt_minimum():
    deck=DECK.replace('density too low',':max').replace('# Rule FLOOR.a: density','# Rule FLOOR.a: max only :max')
    assert 'FLOOR.a' in config.density_rule_coverage(deck,[])[1]


def _density_shortfall(project, gds):
    # Native DRC returns rc=0 even for violations; grade actual RDB items.
    report=project/'density.lyrdb';deck=project/'density.drc'
    deck.write_text('source($input)\nreport("Density control", $report)\n'
                    'sample = input(999,0)\n'
                    'if sample.area / extent.area < 0.35\n'
                    '  extent.output("FLOOR.a", "minimum density shortfall")\nend\n')
    proc=subprocess.run(['klayout','-b','-r',str(deck),'-rd','input='+str(gds),'-rd','report='+str(report)],capture_output=True,text=True)
    assert proc.returncode==0,proc.stderr
    items=ET.parse(report).findall('.//items/item')
    assert items and all('FLOOR.a' in x.findtext('category','') for x in items)


def test_native_drc_minimum_shortfall_remains_failure(tmp_path):
    manifest=case(tmp_path)
    _density_shortfall(tmp_path,tmp_path/manifest['input_gds']['path'])


def test_native_filled_output_shortfall_does_not_gain_row_pass(tmp_path):
    native_case(tmp_path)
    rc,result=invoke(tmp_path)
    assert result['native_started'] is True,result
    assert result['execution']['returncode']==0
    assert result['default_row_status']=='NOT_MEASURED' and not result['completed']
    assert rc==2
    filled=tmp_path/result['outputs']['filled.gds']['path']
    _density_shortfall(tmp_path,filled)


def test_native_kit_cannot_silently_use_odb_fallback_without_a_stream(tmp_path,monkeypatch):
    native_case(tmp_path)
    manifest=json.loads((tmp_path/fill.INPUT).read_text());manifest.pop('input_gds')
    put(tmp_path/fill.INPUT,manifest)
    called=[]
    monkeypatch.setattr(fill,'prepare',lambda *a:called.append('odb'))
    context={'requested_step':'D62','native_step_id':'flow109.D62','context_sha256':'neutral',
             'resolved_row':{'profile':{'id':'odb'}}}
    result=fill.execute(tmp_path,context)
    assert called==[]
    assert result['reason']=='D62_GDS_INPUT_UNBOUND'
    assert result['component_status']=='NOT_MEASURED' and not result['native_started']


def test_mixed_upper_and_lower_checks_still_require_fill():
    deck=DECK.replace('if (sample.area / chip_area) * 100 > 55',
        'if (sample.area / chip_area) * 100 > 55 || (sample.area / chip_area) * 100 < 35')
    assert 'LIMIT.a' in config.density_rule_coverage(deck,[])[1]


def test_unrelated_comparison_is_not_density_direction():
    deck='''chip_area = extent.sized(0.0).area
# Rule FLOOR.a: opaque density checker
if enabled > 0
  check_density(sample.area / chip_area)
end
'''
    assert config.density_rule_coverage(deck,[])[1]=={'FLOOR.a':['sample']}


def test_one_rule_with_multiple_blocks_is_not_max_only():
    deck=DECK.replace('FLOOR.a','LIMIT.a')
    assert 'LIMIT.a' in config.density_rule_coverage(deck,[])[1]


DIRECTION_CASES=json.loads((Path(__file__).parent/'fixtures/d62_direction_cases.json').read_text())
@pytest.mark.parametrize('case',DIRECTION_CASES,ids=[c['case'] for c in DIRECTION_CASES])
def test_reviewed_density_bound_cases(case):
    covered,gaps=config.density_rule_coverage(case['deck'],[])
    assert covered=={}
    assert ('LIMIT.a' not in gaps) is case['check_only']


@pytest.mark.parametrize('body,check_only',[
    ('if 35 > (sample.area / chip_area) * 100\nend',False),
    ('if -(sample.area / chip_area) > -0.35\nend',False),
    ('inverse = 1 - sample.area / chip_area\nif inverse > 0.65\nend',False),
    ('flag = !(sample.area / chip_area >= 0.35) || false',False),
    ('if (sample.area / chip_area) > 0.55 && check_density(sample.area / chip_area)\nend',False),
    ('if (sample.area / chip_area) == 0.35\nend',False),
    ('if 0.55 < sample.area / chip_area\nend',True),
    ('unless 0.35 <= sample.area / chip_area\nend',False),
    ('d = sample.area / chip_area\nif d * 100 > 55\nend',True),
    ('if sample.area / chip_area > 0.55\nend\nopaque_check()',False),
    ('if sample.area / chip_area > 0.55\nend\nx = table[sample.area / chip_area]',False),
    ('if sample.area / chip_area * 1e309 > 55\nend',False),
])
def test_all_density_checks_have_a_proven_direction(body,check_only):
    deck='chip_area = extent.sized(0.0).area\n# Rule LIMIT.a: density\n'+body+'\n'
    assert ('LIMIT.a' not in config.density_rule_coverage(deck,[])[1]) is check_only


@pytest.mark.parametrize('body',[
    "if sample.area / chip_area >= 0.35\n"
    "  logger.info('minimum density satisfied')\n"
    "else\n"
    "  extent.output('FLOOR.a', 'minimum density below original 35 percent')\n"
    "end\n",
    "if sample.area / chip_area >= 0.35\n  next\nend\n"
    "extent.output('FLOOR.a', 'minimum density below original 35 percent')\n",
    "next if sample.area / chip_area >= 0.35\n"
    "extent.output('FLOOR.a', 'minimum density below original 35 percent')\n",
    "if sample.area / chip_area >= 0.35\n  logger.info('satisfied')\n"
    "elsif enabled\n  extent.output('FLOOR.a', 'too low')\nend\n",
    "unless sample.area / chip_area < 0.35\n  logger.info('satisfied')\n"
    "else\n  extent.output('FLOOR.a', 'too low')\nend\n",
    "break if sample.area / chip_area >= 0.35\n"
    "extent.output('FLOOR.a', 'too low')\n",
    "return if sample.area / chip_area >= 0.35\n"
    "extent.output('FLOOR.a', 'too low')\n",
],ids=['if_else','block_next','postfix_next','elsif','unless_else','break','return'])
def test_unproven_report_control_flow_keeps_density_obligation(body):
    deck='chip_area = extent.sized(0.0).area\n# Rule FLOOR.a: density\n'+body
    covered,gaps=config.density_rule_coverage(deck,[])
    assert covered=={}
    assert gaps=={'FLOOR.a':['sample']}
    assert config.density_check_only_rules(deck)==[]
    assert 'FLOOR.a' in config.density_coverage_refusal(gaps)
