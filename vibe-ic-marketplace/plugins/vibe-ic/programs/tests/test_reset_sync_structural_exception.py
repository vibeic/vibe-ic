from __future__ import annotations

import copy
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import reset_sync_structural_exception as S
import phase1_doc_one_shot_runner as D
import _path_layout as PL
import phase3_one_shot_runner as R
from _ppa import timing as T


LIBERTY = r'''
library(test) {
  cell ("DFFRN") {
    ff ("IQ", "IQN") { clear : "!RESET_B"; clocked_on : "CLK"; next_state : "D"; }
    pin ("CLK") { direction : input; }
    pin ("D") { direction : input; }
    pin ("RESET_B") { direction : input; }
    pin ("Q") { direction : output; function : "IQ"; }
  }
  cell ("BUF") {
    pin ("A") { direction : input; }
    pin ("X") { direction : output; function : "A"; }
  }
}
'''

NETLIST = r'''
module top(input clk_i, input clk_edn_i, input rst_n, output main_ok, output edn_ok);
  DFFRN u_main_0 (.CLK(clk_i), .D(1'b1), .RESET_B(rst_n), .Q(main_q0));
  DFFRN u_main_1 (.CLK(clk_i), .D(main_q0), .RESET_B(rst_n), .Q(main_ok));
  DFFRN u_edn_0 (.CLK(clk_edn_i), .D(1'b1), .RESET_B(rst_n), .Q(edn_q0));
  DFFRN u_edn_1 (.CLK(clk_edn_i), .D(edn_q0), .RESET_B(rst_n), .Q(edn_ok));
endmodule
'''


def _policies():
    return {'rst_n': [{
        'clock': clock, 'assertion': 'asynchronous', 'release': 'synchronous',
        'release_clock': clock, 'release_stages': 2,
        'deassertion_guard_ns': 'unknown', 'polarity': 'active_low',
        'deassertion_policy': 'structural_sync_release',
        'deassertion_policy_basis': [{'file': 'input/docs/spec.md',
                                      'line': 8, 'quote': 'no phase lock',
                                      'sha256': 'a' * 64}],
        'basis': [{'file': 'input/docs/spec.md', 'line': 4,
                   'quote': 'phase row', 'sha256': 'a' * 64}],
    } for clock in ('clk_i', 'clk_edn_i')]}


def test_exact_two_domain_release_chains_emit_only_endpoint_exceptions():
    text, report = S.build_structural_exception(NETLIST, LIBERTY, _policies())
    assert report['verdict'] == 'PASS'
    assert len(report['proven_domains']) == 2
    assert len(text.splitlines()) == 4
    assert all('-to [get_pins {' in line for line in text.splitlines())
    assert all('-from [get_ports {rst_n}]' in line for line in text.splitlines())
    assert 'set_case_analysis' not in text
    assert 'set_false_path -from [get_ports {rst_n}]\n' not in text


@pytest.mark.parametrize('mutation', [
    'extra_fanout', 'alias_fanout', 'clock', 'depth', 'chain', 'polarity',
    'policy', 'reset',
])
def test_changed_structure_or_contract_refuses(mutation):
    netlist = NETLIST
    policies = copy.deepcopy(_policies())
    if mutation == 'extra_fanout':
        netlist = netlist.replace('endmodule',
                                  'BUF u_bad (.A(rst_n), .X(bad));\nendmodule')
    elif mutation == 'alias_fanout':
        netlist = netlist.replace('endmodule',
                                  'wire leaked; assign leaked = rst_n;\nendmodule')
    elif mutation == 'clock':
        netlist = netlist.replace('.CLK(clk_edn_i), .D(edn_q0)',
                                  '.CLK(clk_i), .D(edn_q0)')
    elif mutation == 'depth':
        policies['rst_n'][0]['release_stages'] = 3
    elif mutation == 'chain':
        netlist = netlist.replace('.D(main_q0)', '.D(other_net)')
    elif mutation == 'polarity':
        policies['rst_n'][0]['polarity'] = 'active_high'
    elif mutation == 'policy':
        policies['rst_n'][0].pop('deassertion_policy')
    elif mutation == 'reset':
        policies = {'other_rst_n': policies.pop('rst_n')}
    with pytest.raises(S.StructuralResetRefusal):
        S.build_structural_exception(netlist, LIBERTY, policies)


def _current_project(tmp_path):
    fixture = (Path(__file__).parent /
               'fixtures/phase1_local/neutral_reset_domain_phases/reset.md')
    text = (fixture.read_text().replace('clk_aux_i', 'clk_edn_i')
            .replace('| 2 | 0.7 |', '| 2 | unspecified |')
            .replace('| 2 | 0.9 |', '| 2 | unspecified |')
            + '\nCurrent contract: rst_n deassertion is not phase-locked to any '
              'external clock; each domain uses its own release chain.\n')
    project = tmp_path / 'project'
    source = project / 'input/docs/reset.md'
    source.parent.mkdir(parents=True)
    source.write_text(text)
    extracted = {'reset.md': text}
    D.gen_l1_datasheet(project, extracted)
    D.gen_l8_timing_waveform(project, extracted)
    D.gen_l8_timing_waveform_doc(project, extracted)
    D.gen_l9_integration_spec(project, extracted, {})
    D._post_emit_typed_clock_domains(project)
    D._post_emit_sdc_constraints(project)
    D._post_emit_mirror_clock_resets_to_l9_v1_6_311(project)
    D._post_emit_l8_clock_reset_waveform(project)
    synth = PL.synth_dir(project)
    synth.mkdir(parents=True)
    mapped = synth / 'top_synth.v'
    mapped.write_text(NETLIST)
    (synth / PL.SYNTH_INPUTS_SIDECAR).write_text(
        '{"netlist":"top_synth.v"}')
    liberty = tmp_path / 'cells.lib'
    liberty.write_text(LIBERTY)
    return project, mapped, liberty


def test_current_project_application_binds_source_netlist_and_liberty(tmp_path):
    project, mapped, liberty = _current_project(tmp_path)
    text, report = S.apply_current_project(
        project, liberty, 'create_clock -period 10 [get_ports clk_i]\n')
    assert report['mapped_netlist'] == str(mapped.relative_to(project))
    assert report['netlist_sha256'] == S._sha(mapped.read_bytes())
    assert report['liberty_sha256'] == S._sha(liberty.read_bytes())
    assert len(report['proven_domains']) == 2
    assert text.count('set_false_path') == 4
    mapped.write_text(NETLIST.replace('.D(main_q0)', '.D(other_net)'))
    with pytest.raises(S.StructuralResetRefusal,
                       match='RESET_SYNC_CHAIN_LINK_MISMATCH'):
        S.apply_current_project(project, liberty, text)


def test_native_opensta_reads_only_the_proven_pin_scoped_exceptions(tmp_path):
    sta = shutil.which('sta')
    assert sta, 'the EDA image must provide OpenSTA'
    exception, _ = S.build_structural_exception(NETLIST, LIBERTY, _policies())
    liberty = tmp_path / 'cells.lib'
    netlist = tmp_path / 'top.v'
    sdc = tmp_path / 'top.sdc'
    script = tmp_path / 'read.tcl'
    liberty.write_text(LIBERTY)
    netlist.write_text(NETLIST)
    sdc.write_text('create_clock -name clk_i -period 10 [get_ports clk_i]\n'
                   'create_clock -name clk_edn_i -period 12 [get_ports clk_edn_i]\n'
                   + exception)
    script.write_text(f'read_liberty {{{liberty}}}\nread_verilog {{{netlist}}}\n'
                      f'link_design top\nread_sdc {{{sdc}}}\n'
                      'puts RESET_SYNC_SDC_OK\nexit\n')
    run = subprocess.run([sta, '-no_init', '-exit', str(script)],
                         capture_output=True, text=True, timeout=120)
    output = run.stdout + run.stderr
    assert run.returncode == 0 and 'RESET_SYNC_SDC_OK' in output, output
    assert 'Error:' not in output and 'STA-' not in output, output


def test_canonical_step7_receipt_binds_current_structural_proof(tmp_path):
    project, mapped, liberty = _current_project(tmp_path)
    pdk = SimpleNamespace(name='test', liberty=str(liberty))
    record = T.emit_step7_asic_sdc(R, project, 'top', pdk, '')
    proof = record['structural_reset_exception']
    assert proof['verdict'] == 'PASS'
    assert proof['mapped_netlist'] == str(mapped.relative_to(project))
    deck = (project / record['path']).read_text()
    assert deck.count('set_false_path') == 4
    assert record['inputs']['@mapped_synth_netlist'] == str(
        mapped.relative_to(project))
    mapped.write_text(NETLIST.replace('.D(main_q0)', '.D(other_net)'))
    accepted, why = T.read_step7_asic_sdc(R, project, 'top', pdk)
    assert accepted is None
    assert '@mapped_synth_netlist' in why or str(mapped.relative_to(project)) in why


def test_canonical_step7_blocks_before_sta_without_mapped_proof(tmp_path):
    project, mapped, liberty = _current_project(tmp_path)
    mapped.unlink()
    pdk = SimpleNamespace(name='test', liberty=str(liberty))
    with pytest.raises(S.StructuralResetRefusal,
                       match='RESET_SYNC_MAPPED_NETLIST_ABSENT'):
        T.emit_step7_asic_sdc(R, project, 'top', pdk, '')
    assert not list(PL.constraints_dir(project).glob('*.sdc'))
    assert not (PL.constraints_dir(project) / T.ASIC_SDC_RECORD).exists()


def test_source_admission_does_not_require_mapped_netlist(tmp_path):
    project, mapped, liberty = _current_project(tmp_path)
    mapped.unlink()
    policies = S.admit_current_project_source(project)
    assert len(policies['rst_n']) == 2
    assert all(row['deassertion_policy'] == 'structural_sync_release'
               for row in policies['rst_n'])






@pytest.mark.parametrize('expression,active_low', [('!RESET_B', True), ('RESET_B', False)])
def test_liberty_boolean_negation_is_material_to_structural_proof(expression, active_low):
    liberty = LIBERTY.replace('!RESET_B', expression)
    assert S._liberty_ffs(liberty)['DFFRN']['clear'] == expression
    policies = copy.deepcopy(_policies())
    for policy in policies['rst_n']:
        policy['polarity'] = 'active_low' if active_low else 'active_high'
    _, report = S.build_structural_exception(NETLIST, liberty, policies)
    assert report['verdict'] == 'PASS'
    for policy in policies['rst_n']:
        policy['polarity'] = 'active_high' if active_low else 'active_low'
    with pytest.raises(S.StructuralResetRefusal):
        S.build_structural_exception(NETLIST, liberty, policies)
    with pytest.raises(S.StructuralResetRefusal):
        S.build_structural_exception(NETLIST, LIBERTY.replace('!RESET_B', 'RESET_B & ENABLE'), policies)
