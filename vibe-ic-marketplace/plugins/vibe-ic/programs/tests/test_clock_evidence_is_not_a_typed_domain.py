"""Clock provenance must neither fail nor satisfy the typed-domain gate."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

import phase1_doc_one_shot_runner as runner


PROG = Path(__file__).resolve().parents[1] / 'l8_clock_domains_typed_check.py'
HEAD = ('The block clock operates at 31.25 MHz.\n'
        'The auxiliary reference runs at 10 MHz.\n')
TABLE = ('| Instance | Clock port | Top clock pin |\n'
         '|---|---|---|\n'
         '| lane_a | clk | i_clk0 |\n'
         '| lane_b | clk | i_clk1 |\n')


def run_gate(project):
    return subprocess.run([sys.executable, str(PROG), str(project)],
                          capture_output=True, text=True)


@pytest.mark.parametrize('table', [TABLE, ''], ids=['with_table', 'without_table'])
def test_landing_neutral_input_passes_typed_clock_check(tmp_path, table):
    text = HEAD + table
    source = tmp_path / 'input/docs/clock_contract.txt'
    source.parent.mkdir(parents=True)
    source.write_text(text)
    docs = tmp_path / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    (docs / 'L1_DATASHEET.json').write_text(json.dumps({'pin_table': [
        {'name': 'i_clk0', 'mode': 'input'},
        {'name': 'i_clk1', 'mode': 'input'}]}))
    extracted = {source.name: text}
    runner.gen_l8_timing_waveform(tmp_path, extracted)
    runner.gen_l9_integration_spec(tmp_path, extracted, {})
    runner._post_emit_typed_clock_domains(tmp_path)
    runner._post_emit_mirror_clock_resets_to_l9_v1_6_311(tmp_path)
    result = run_gate(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '[PASS]' in result.stdout


@pytest.mark.parametrize('metadata', ['extraction_evidence', 'provenance'])
@pytest.mark.parametrize('real_clocks,quoted_clocks,expected', [
    ([{'name': 'clk0', 'freq_mhz': 31.25, 'role': 'master'}],
     [{'literal': 'a quoted clock row'}], 0),
    ([], [{'name': 'clk0', 'freq_mhz': 31.25, 'role': 'master'}], 1),
    ([{'name': 'clk0'}],
     [{'name': 'clk0', 'freq_mhz': 31.25, 'role': 'master'}], 1),
], ids=['evidence_cannot_fail', 'evidence_cannot_supply', 'evidence_cannot_type'])
def test_provenance_is_not_a_clock_contract(tmp_path, metadata, real_clocks,
                                          quoted_clocks, expected):
    source = tmp_path / 'input/docs/clock_contract.txt'
    source.parent.mkdir(parents=True)
    source.write_text(HEAD)
    docs = tmp_path / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    (docs / 'L8_RTL_CONSTANTS.json').write_text(json.dumps({
        'clock_domains': real_clocks,
    }))
    (docs / 'L9_INTEGRATION_SPEC.json').write_text(json.dumps({
        metadata: {'clocks': quoted_clocks},
    }))
    result = run_gate(tmp_path)
    assert result.returncode == expected, result.stdout + result.stderr
    assert ('[PASS]' if expected == 0 else '[FAIL]') in result.stdout
