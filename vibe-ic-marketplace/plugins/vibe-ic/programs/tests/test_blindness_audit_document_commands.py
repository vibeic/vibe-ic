"""Document data is distinct from executed scorer code; unsupported code stays raw."""
import json
from pathlib import Path

import pytest

import blindness_audit as ba

COMMAND = 'python3 score_neutral.py --run neutral'
PLAN = '# Work plan\n\n1. Run benchmark_dispatch.py neutral --solve.\n2. Later use --score.\n'


def heredoc(body):
    return "python3 - <<'PY'\n" + body + "\nPY"


def wrapper(command):
    return 'text((await tools.exec_command(' + json.dumps({'cmd': command}) + ')).output);'


def audit(command):
    frame = {'type': 'custom_tool_call', 'name': 'exec', 'input': command}
    unread = []
    findings = ba.audit_text(json.dumps(frame), Path('/neutral-dataset'),
                             ['specification.md'], 'neutral.jsonl', uninspected=unread)
    assert unread == []
    return [f['kind'] for f in findings]


@pytest.mark.parametrize('wrap', [lambda x: x, wrapper])
def test_passive_document_literal_is_not_a_scorer_execution(wrap):
    command = heredoc("from pathlib import Path\nPath('/tmp/PLAN.md').write_text(" + repr(PLAN) + ")")
    assert audit(wrap(command)) == []


@pytest.mark.parametrize('command', [
    COMMAND,
    'bash -lc ' + repr(COMMAND),
    'cmd=' + repr(COMMAND) + '; eval "$cmd"',
    'python3 -c ' + repr('import os; os.system(' + repr(COMMAND) + ')'),
    'python3 -c ' + repr('import subprocess,sys;subprocess.run([sys.executable,"score_neutral.py"])'),
    heredoc('import subprocess\nsubprocess.run(' + repr(COMMAND) + ', shell=True)'),
    heredoc('import os\nlaunch=os.system\nlaunch(' + repr(COMMAND) + ')'),
    heredoc('import subprocess,sys\ncmd=[sys.executable,"score_neutral.py","--run","neutral"]\nlaunch=subprocess.run\nlaunch(cmd)'),
    heredoc('from subprocess import run as print\nprint(["python3","score_neutral.py"])'),
    heredoc('import json,subprocess\njson.dumps=subprocess.run\njson.dumps(["python3","score_neutral.py"])'),
    heredoc('import subprocess\nsubprocess.run(["python3","benchmark_dispatch.py","neutral","--score"])'),
    heredoc('from subprocess import run as launch\ncmd=' + repr(COMMAND) + '\nlaunch(cmd, shell=True)'),
    heredoc('command=' + repr(COMMAND) + '\nexec(command)'),
    heredoc('import runpy\nrunpy.run_path("/tmp/score_neutral.py")\n# ' + COMMAND),
])
@pytest.mark.parametrize('wrap', [lambda x: x, wrapper])
def test_real_scorer_commands_remain_blocked(command, wrap):
    assert audit(wrap(command)) == ['scorer-self-run']


@pytest.mark.parametrize('suffix', ['py', 'txt', 'md'])
@pytest.mark.parametrize('execution', ['python3', 'bash'])
def test_written_helper_executed_by_shell_is_not_inert(suffix, execution):
    path = '/tmp/helper.' + suffix
    command = heredoc('from pathlib import Path\nPath(' + repr(path) + ').write_text(' + repr(COMMAND) + ')')
    assert audit(command + '\n' + execution + ' ' + path) == ['scorer-self-run']
    assert audit(wrapper(command) + '\n' + wrapper(execution + ' ' + path)) == ['scorer-self-run']


@pytest.mark.parametrize('suffix', ['py', 'txt', 'md'])
def test_written_helper_executed_by_python_shellout_is_not_inert(suffix):
    path = '/tmp/helper.' + suffix
    body = ('from pathlib import Path\nimport subprocess\nPath(' + repr(path) + ').write_text('
            + repr(COMMAND) + ')\nlaunch=subprocess.run\nlaunch(["bash", ' + repr(path) + '])')
    assert audit(wrapper(heredoc(body))) == ['scorer-self-run']


def test_rebinding_passive_call_to_execution_does_not_hide_document():
    body = ('from pathlib import Path\nimport json\njson.dumps=exec\n'
            'command=' + repr(COMMAND) + '\njson.dumps(command)\n'
            "Path('/tmp/PLAN.md').write_text(" + repr(PLAN) + ')')
    assert audit(heredoc(body)) == ['scorer-self-run']


def test_real_repo_instructions_are_document_data():
    # Exercise a maintained repository artefact, not only fixtures authored here.
    from _hostpaths import repo_path
    source = repo_path('vibe-ic-marketplace/plugins/vibe-ic/skills/open-benchmark-methodology/SKILL.md')
    document = source.read_text()
    assert 'benchmark_dispatch.py' in document and '--score' in document
    command = heredoc("from pathlib import Path\nPath('/tmp/guide.md').write_text(" + repr(document) + ')')
    assert audit(wrapper(command)) == []
