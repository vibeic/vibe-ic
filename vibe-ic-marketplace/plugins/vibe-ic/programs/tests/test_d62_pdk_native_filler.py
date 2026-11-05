"""Native-PDK producer selection, fallback and non-signoff controls."""
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET
import pytest

import metal_fill_config_gen as config
from test_flow109_gds_fill_dispatch import case










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
