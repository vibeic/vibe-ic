"""Ordinary-source controls for the declared RTL content consumer, not scoring."""
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import pytest
import yaml
import comb_advanced_synth as emitter
import sequential_waveform_synth as waveform
from _hostpaths import require_repo


PROMPT = '''Module name: storage_unit
Implement a D latch using an always block.
Inputs: d and ena. Output: q.
module storage_unit(input d, input ena, output q);
endmodule
'''


WAVE_PROMPT = '''Module name: storage_unit
Implement the following sampled behavior.
 - input clock
 - input d
 - output sampled
 - output tracked
module storage_unit(input clock, input d, output sampled, output tracked);
endmodule
Time clock d sampled tracked
0ns 0 0 0 0
1ns 1 0 0 0
2ns 1 1 0 1
3ns 0 1 1 1
4ns 0 0 1 1
5ns 1 0 1 0
6ns 1 1 1 1
7ns 0 1 1 1
8ns 0 0 1 1
9ns 1 0 1 0
10ns 0 0 0 0
'''


def subject(tmp_path, shape='single'):
    project = tmp_path / 'project'
    path = project / 'input/phase1_prompt.md'
    path.parent.mkdir(parents=True)
    prompt = PROMPT if shape == 'single' else WAVE_PROMPT
    path.write_text(prompt)
    rtl = project / 'phase2/stage1/rtl/storage_unit.sv'
    rtl.parent.mkdir(parents=True)
    body = (emitter if shape == 'single' else waveform).synth(prompt, 'storage_unit')
    assert body is not None
    rtl.write_text(body)
    return project, rtl


def native_content(project):
    contract = yaml.safe_load(require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic',
        'flow', 'phase1_phase2_phase3.yaml').read_text())
    rows = contract.get('steps', contract.get('flow', {}).get('steps', []))
    step = next(row for row in rows if str(row['id']) == '1')
    gates = step['input_contracts']['original']['gate']['all_of']
    command = next(row['program_exit_zero'] for row in gates
        if row.get('program_exit_zero', '').startswith('flow_step_output_content_check '))
    words = shlex.split(command)
    script = Path(emitter.__file__).with_name(words[0] + '.py')
    return subprocess.run([sys.executable, str(script), *words[1:]], cwd=project,
        text=True, capture_output=True)


@pytest.mark.skipif(not shutil.which('verilator'), reason='native Verilator required')
@pytest.mark.parametrize('shape', ['single', 'clocked_pair'])
def test_declared_latch_passes_the_existing_native_content_consumer(tmp_path, shape):
    project, _ = subject(tmp_path, shape)
    observed = native_content(project)
    assert observed.returncode == 0, observed.stdout + observed.stderr


@pytest.mark.skipif(not shutil.which('verilator'), reason='native Verilator required')
def test_unintended_latch_is_still_rejected(tmp_path):
    project, rtl = subject(tmp_path)
    (project / 'input/phase1_prompt.md').write_text(
        'Module name: storage_unit\nMake q equal d when ena is high, and zero otherwise.\n')
    rtl.write_text('module storage_unit(input d,input ena,output reg q);\n'
                   'always @(*) if (ena) q=d; endmodule\n')
    observed = native_content(project)
    assert observed.returncode == 1, observed.stdout + observed.stderr
    assert 'LATCH' in observed.stdout + observed.stderr


@pytest.mark.skipif(not shutil.which('iverilog') or not shutil.which('vvp'),
                    reason='native Icarus required')
def test_generated_storage_tracks_and_holds_in_both_states(tmp_path):
    _, rtl = subject(tmp_path)
    tb = tmp_path / 'check.sv'
    tb.write_text('''module check;
reg d=0, ena=0; wire q;
storage_unit dut(.d(d),.ena(ena),.q(q));
initial begin
  ena=1; d=0; #1; if(q!==0) $fatal(1,"track zero");
  ena=0; d=1; #1; if(q!==0) $fatal(1,"hold zero");
  ena=1; #1; if(q!==1) $fatal(1,"track one");
  ena=0; d=0; #1; if(q!==1) $fatal(1,"hold one");
  $display("STORAGE_CHECK=PASS"); $finish;
end
endmodule
''')
    image = tmp_path / 'check.vvp'
    subprocess.run(['iverilog', '-g2012', '-s', 'check', '-o', str(image), str(rtl), str(tb)],
                   check=True, capture_output=True, text=True)
    observed = subprocess.run(['vvp', str(image)], capture_output=True, text=True)
    assert observed.returncode == 0, observed.stdout + observed.stderr
    assert 'STORAGE_CHECK=PASS' in observed.stdout
