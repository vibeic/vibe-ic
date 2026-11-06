"""Native security properties on a synthesized logical implementation."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest
import flow_engine as engine
import flow_native_adapters as adapters


def row_tool(analog=False):
    row = engine.read_json(engine.TABLE)['steps'][98]
    return row, engine.choose_tool(row['tool'], {'has_digital': not analog, 'has_analog': analog})


@pytest.mark.parametrize('analog', [False, True])
def test_implemented_security_selects_implemented_decks(tmp_path, monkeypatch, analog):
    root = tmp_path / 'phase3/stage3/formal/security'
    root.mkdir(parents=True)
    deck = root / 'scan_access.sby'
    deck.write_text('')
    def formal(project, directory, tool, commands):
        assert tool['properties'] == [deck]
        return {'ran': True, 'exit_code': 0, 'metrics': {'unproved_required_properties': 0},
                'detail': 'Native SBY PASS'}
    monkeypatch.setattr(adapters, 'formal', formal)
    row, tool = row_tool(analog)
    result = adapters.execute(tmp_path, tmp_path / 'step', tool, {})
    assert result['metrics']['scan_debug_access_violations'] == 0
    assert 'final_analog_security_targets' not in result['metrics']
    checks = engine.measure(row['checks'], result['metrics'], {},
        {'requires_security': True, 'digital_physical': not analog, 'analog_physical': analog, 'assembly_only': False, 'child_has_digital': False, 'child_has_analog': False}, tmp_path)
    assert engine.evaluate(engine.ToolResult(**result), checks) == ('NOT_MEASURED' if analog else 'PASS')


def test_implemented_security_does_not_reuse_rtl_or_generic_decks(tmp_path, monkeypatch):
    root = tmp_path / 'phase2/stage1/formal/security'
    root.mkdir(parents=True)
    (root / 'scan_access.sby').write_text('')
    (root.parent / 'reset.sby').write_text('')
    monkeypatch.setattr(adapters, 'formal', lambda *args: pytest.fail('Wrong proof input'))
    _, tool = row_tool()
    result = adapters.execute(tmp_path, tmp_path / 'step', tool, {})
    assert not result['ran'] and not result['metrics']


def subject(project, bypass=False):
    docs = project / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    (docs / 'L9_INTEGRATION_SPEC.json').write_text(json.dumps({'top_module': 'access'}))
    source = project / 'phase2/stage1/rtl/access.v'
    source.parent.mkdir(parents=True)
    source.write_text('module access(input auth, scan_en, secret, output scan_out);\n'
        + ('assign scan_out=scan_en & secret;\n' if bypass else
           'assign scan_out=auth & scan_en & secret;\n') + 'endmodule\n')
    implemented = project / 'phase3/stage3/synth/access.v'
    implemented.parent.mkdir(parents=True)
    completed = subprocess.run(['yosys', '-Q', '-T', '-p',
        f'read_verilog {source}; synth -top access; write_verilog -noattr {implemented}'],
        capture_output=True, text=True)
    (implemented.parent / 'synthesis.log').write_text(completed.stdout + completed.stderr)
    assert completed.returncode == 0, completed.stderr
    root = project / 'phase3/stage3/formal/security'
    root.mkdir(parents=True)
    harness = root / 'proof.sv'
    harness.write_text('module proof;\n(* anyseq *) reg auth, scan_en, secret;\n'
        'wire scan_out; access dut(auth,scan_en,secret,scan_out);\n'
        'always @* begin if(!auth) assert(!scan_out); cover(auth && scan_en && secret); end\n'
        'endmodule\n')
    deck = root / 'scan_access.sby'
    deck.write_text('[options]\nmode prove\ndepth 4\n[engines]\nsmtbmc yices\n'
        '[script]\nread_verilog -formal -sv access.v proof.sv\nprep -top proof\n'
        f'[files]\n{implemented}\n{harness}\n')
    return implemented


@pytest.mark.parametrize('bypass', [False, True])
@pytest.mark.skipif(not all(shutil.which(name) for name in ('yosys', 'sby', 'yices-smt2')),
                    reason='Native synthesis and formal tools required')
def test_actual_synthesized_access_proof_and_counterexample(tmp_path, bypass):
    implemented = subject(tmp_path, bypass)
    row, tool = row_tool()
    result = adapters.execute(tmp_path, tmp_path / 'step', tool, {})
    assert result['metrics']['scan_debug_access_violations'] == int(bypass), result
    checks = engine.measure(row['checks'], result['metrics'], {},
        {'requires_security': True, 'digital_physical': True, 'analog_physical': False, 'assembly_only': False, 'child_has_digital': False, 'child_has_analog': False}, tmp_path)
    assert engine.evaluate(engine.ToolResult(**result), checks) == ('FAIL' if bypass else 'PASS')
    assert implemented.is_file()
