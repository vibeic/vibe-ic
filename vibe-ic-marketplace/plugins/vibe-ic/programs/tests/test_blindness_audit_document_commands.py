"""Document data is distinct from executed scorer code; unsupported code stays raw."""
import ast
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
    source = repo_path('vibe-ic-marketplace/plugins/vibe-ic/programs/blindness_audit.py')
    document = ast.get_docstring(ast.parse(source.read_text()))
    assert 'benchmark_dispatch' in document and '--score' in document
    command = heredoc("from pathlib import Path\nPath('/tmp/guide.md').write_text(" + repr(document) + ')')
    assert audit(wrapper(command)) == []


@pytest.mark.parametrize('suffix', ['py', 'txt', 'md'])
@pytest.mark.parametrize('payload', [COMMAND, 'import os; os.system(' + repr(COMMAND) + ')'])
def test_generated_helper_remains_visible_across_separate_tool_frames(suffix, payload):
    path = '/tmp/helper.' + suffix
    command = heredoc('from pathlib import Path\nPath(' + repr(path) + ').write_text(' + repr(payload) + ')')
    frames = [{'type': 'function_call', 'name': 'exec_command',
               'arguments': json.dumps({'cmd': cmd})}
              for cmd in [command, 'python3 ' + path]]
    findings = ba.audit_text('\n'.join(json.dumps(x) for x in frames),
                             Path('/neutral-dataset'), ['specification.md'], 'neutral.jsonl')
    assert [f['kind'] for f in findings] == ['scorer-self-run']


JS_PLAN = '# Work plan\n\nLater host command:\n```text\n' + COMMAND + '\n```\n'


def js_document(body=JS_PLAN, path='/tmp/PLAN.md', after='', lint=False):
    literal = body.replace('\\', '\\\\').replace('`', '\\`')
    return ('const root=load("output_root"), plugin=load("plugin_root");\n'
            'const document = `' + literal + '`;\n'
            'text(await tools.apply_patch("*** Begin Patch\\n*** Add File: " + '
            + json.dumps(path + '\n') + ' + document.split("\\n").map(line=>"+"+line).join("\\n") + "\\n*** End Patch"));\n'
            + (('text(await tools.exec_command({cmd:"python3 report_lint.py " + '
                + json.dumps(path) + ',workdir:plugin,max_output_tokens:2500,yield_time_ms:1000}));\n')
               if lint else '') + after)


def test_closed_js_template_report_is_data_not_scorer_execution():
    assert audit(js_document()) == []


@pytest.mark.parametrize('after', [
    'text(await tools.exec_command({cmd:"python3 score_neutral.py --run neutral"}));',
    'text(await tools.exec_command({cmd:document}));',
    'unknown_sink(document);',
    'document += "extra";',
])
def test_js_document_execution_or_unknown_flow_keeps_scorer_visible(after):
    assert audit(js_document(after=after)) == ['scorer-self-run']


def test_dynamic_js_interpolation_keeps_actual_execution_visible():
    body = JS_PLAN + '${await tools.exec_command({cmd:"python3 score_neutral.py --run neutral"})}'
    assert audit(js_document(body)) == ['scorer-self-run']


@pytest.mark.parametrize('suffix', ['py', 'txt', 'md'])
@pytest.mark.parametrize('execution', ['python3', 'bash', 'read_exec', 'python_flag'])
def test_js_written_helper_execution_across_transcripts_is_visible(tmp_path, suffix, execution):
    import subprocess
    import sys
    path = '/tmp/helper.' + suffix
    write = {'type': 'custom_tool_call', 'name': 'exec', 'input': js_document(COMMAND, path)}
    command = ('python3 -c ' + repr('exec(open(' + repr(path) + ').read())')
               if execution == 'read_exec' else ('python3 -X dev ' + path)
               if execution == 'python_flag' else execution + ' ' + path)
    launch = {'type': 'function_call', 'name': 'exec_command', 'arguments': json.dumps({'cmd': command})}
    transcript_a = tmp_path / 'a-write.jsonl'; transcript_b = tmp_path / 'b-execute.jsonl'
    transcript_a.write_text(json.dumps(write) + '\n'); transcript_b.write_text(json.dumps(launch) + '\n')
    report = tmp_path / 'findings.json'; coverage = tmp_path / 'coverage.json'
    result = subprocess.run([sys.executable, ba.__file__, '--dataset', '/neutral-dataset',
        '--json', str(report), '--coverage-json', str(coverage), str(transcript_a), str(transcript_b)],
        capture_output=True, text=True)
    assert result.returncode == ba.EXIT_VIOLATION, result.stdout + result.stderr
    assert [x['kind'] for x in json.loads(report.read_text())] == ['scorer-self-run']
    census = json.loads(coverage.read_text())
    assert (census['transcripts'], census['tool_calls'], census['inspected_tool_calls']) == (2, 2, 2)


@pytest.mark.parametrize('command', [
    '"python3 " + "score_neutral.py --run neutral"',
    '"python3 score_\\u006eeutral.py --run neutral"',
])
def test_js_resolved_command_argv_is_not_hidden_by_document_elision(command):
    assert audit(js_document(after='text(await tools.exec_command({cmd:' + command + '}));')) == ['scorer-self-run']


@pytest.mark.parametrize('command', [
    'sh /tmp/helper.md; echo ok',
    'sh /tmp/he""lper.md',
    "sh /tmp/he''lper.md",
    'sh /tmp/helper.md;\necho "unterminated',
    'sh -- /tmp/helper.md; echo ok',
    'python3 lint_report.py /tmp/helper.md; sh /tmp/helper.md',
    'python3 lint_report.py /tmp/helper.md && sh /tmp/helper.md',
    'python3 lint_report.py /tmp/helper.md\nsh /tmp/helper.md',
    'python3.12 /tmp/helper.md',
    '/usr/bin/python3.12 /tmp/helper.md',
    'env -i python3.12 -X dev /tmp/helper.md; echo ok',
    'sh${IFS}/tmp/helper.md',
    'sh /tmp/helper.md$IFS',
    'sh /tmp/`printf helper`.md',
    'sh /tmp/$(printf helper).md',
])
def test_shell_execution_linkage_never_makes_a_written_document_passive(tmp_path, command):
    import subprocess
    import sys
    write = {'type': 'custom_tool_call', 'name': 'exec', 'input': js_document(COMMAND, '/tmp/helper.md')}
    launch = {'type': 'function_call', 'name': 'exec_command', 'arguments': json.dumps({'cmd': command})}
    a = tmp_path / 'a.jsonl'; b = tmp_path / 'b.jsonl'; report = tmp_path / 'findings.json'
    a.write_text(json.dumps(write) + '\n'); b.write_text(json.dumps(launch) + '\n')
    result = subprocess.run([sys.executable, ba.__file__, '--dataset', '/neutral-dataset',
        '--json', str(report), str(a), str(b)], capture_output=True, text=True)
    assert result.returncode == ba.EXIT_VIOLATION, result.stdout + result.stderr
    assert [x['kind'] for x in json.loads(report.read_text())] == ['scorer-self-run']


@pytest.mark.parametrize('path,command', [
    ('/tmp/helper;note.md', 'sh "/tmp/helper;note.md"'),
])
def test_quoted_script_paths_and_read_exec_keep_the_written_helper_visible(path, command):
    frames = [{'type': 'custom_tool_call', 'name': 'exec', 'input': js_document(COMMAND, path)},
              {'type': 'function_call', 'name': 'exec_command', 'arguments': json.dumps({'cmd': command})}]
    findings = ba.audit_text('\n'.join(json.dumps(x) for x in frames), Path('/neutral-dataset'),
                             ['specification.md'], 'neutral.jsonl')
    assert [x['kind'] for x in findings] == ['scorer-self-run']



def test_real_repo_instructions_as_js_patch_data_are_not_a_scorer_run():
    from _hostpaths import repo_path
    source = repo_path('vibe-ic-marketplace/plugins/vibe-ic/programs/blindness_audit.py')
    document = ast.get_docstring(ast.parse(source.read_text()))
    assert audit(js_document(document)) == []


@pytest.mark.parametrize('launch', [
    'text(await tools.exec_command({cmd:"sh /tmp/he"+"lper.md"}));',
    'const part="hel"; text(await tools.exec_command({cmd:"sh /tmp/"+part+"per.md"}));',
    'text(await tools.exec_command(load("unknown_command")));',
    'text(await tools.exec_command({cmd:"sh /tmp/he"+"*per.md"}));',
])
def test_other_js_command_context_cannot_hide_helper_execution(launch):
    frames = [{'type': 'custom_tool_call', 'name': 'exec', 'input': js_document(COMMAND, '/tmp/helper.md')},
              {'type': 'custom_tool_call', 'name': 'exec', 'input': launch}]
    findings = ba.audit_text('\n'.join(json.dumps(x) for x in frames), Path('/neutral-dataset'),
                             ['specification.md'], 'neutral.jsonl')
    assert [x['kind'] for x in findings] == ['scorer-self-run']


@pytest.mark.parametrize('command', [
    'node /tmp/helper.md',
    '/usr/bin/node /tmp/helper.md',
    'env -i node /tmp/helper.md',
    'perl /tmp/helper.md',
    'ruby /tmp/helper.md',
    'arbitrary_launcher /tmp/helper.md',
    'python3 report_lint.py /tmp/helper.md',
    'node /tmp/he*per.md',
])
def test_unproven_external_consumers_cannot_make_written_code_passive(tmp_path, command):
    import subprocess
    import sys
    payload = 'require("child_process").execSync("' + COMMAND + '");\n'
    write = {'type': 'custom_tool_call', 'name': 'exec', 'call_id': 'write-neutral-document',
             'input': js_document(payload, '/tmp/helper.md', lint=True)}
    launch = {'type': 'function_call', 'name': 'exec_command', 'call_id': 'execute-neutral-document',
              'arguments': json.dumps({'cmd': command})}
    a = tmp_path / 'a-write.jsonl'; b = tmp_path / 'b-execute.jsonl'
    report = tmp_path / 'findings.json'; coverage = tmp_path / 'coverage.json'
    a.write_text(json.dumps(write) + '\n'); b.write_text(json.dumps(launch) + '\n')
    result = subprocess.run([sys.executable, ba.__file__, '--dataset', '/neutral-dataset',
        '--json', str(report), '--coverage-json', str(coverage), str(a), str(b)],
        capture_output=True, text=True)
    assert result.returncode == ba.EXIT_VIOLATION, result.stdout + result.stderr
    assert [x['kind'] for x in json.loads(report.read_text())] == ['scorer-self-run']
    census = json.loads(coverage.read_text())
    assert (census['transcripts'], census['tool_calls'], census['inspected_tool_calls']) == (2, 2, 2)


def test_purported_linter_is_not_proof_of_passive_document_consumption():
    assert audit(js_document(lint=True)) == ['scorer-self-run']


@pytest.mark.parametrize('command', ['echo safe', 'unknown_consumer encoded_input',
    'node -e "require(Buffer.from(\"encoded\",\"base64\").toString())"'])
def test_unproven_context_never_grants_passive_data_credit(command):
    # Even unrelated-looking text cannot prove what an arbitrary consumer does.
    frames = [{'type': 'custom_tool_call', 'name': 'exec',
               'input': js_document(COMMAND, '/tmp/helper.md')},
              {'type': 'function_call', 'name': 'exec_command',
               'arguments': json.dumps({'cmd': command})}]
    findings = ba.audit_text('\n'.join(json.dumps(x) for x in frames),
        Path('/neutral-dataset'), ['specification.md'], 'neutral.jsonl')
    assert [x['kind'] for x in findings] == ['scorer-self-run']


def test_duplicate_closed_write_only_frames_retain_every_call_identity():
    script = js_document()
    frames = [{'type': 'custom_tool_call', 'name': 'exec',
               'call_id': call_id, 'input': script}
              for call_id in ['first-write', 'same-write-again']]
    coverage = []
    findings = ba.audit_text('\n'.join(json.dumps(x) for x in frames),
        Path('/neutral-dataset'), ['specification.md'], 'neutral.jsonl', coverage=coverage)
    assert findings == []
    assert [(x['call_id'], x['inspected']) for x in coverage] == [
        ('first-write', True), ('same-write-again', True)]


def test_incomplete_context_disables_write_only_document_elision(tmp_path, monkeypatch):
    write = tmp_path / 'write.jsonl'; unreadable = tmp_path / 'unreadable.jsonl'
    write.write_text(json.dumps({'type': 'custom_tool_call', 'name': 'exec',
        'call_id': 'write-only', 'input': js_document()}) + '\n')
    unreadable.write_text('unknown retained transcript')
    real_read = Path.read_text
    def read(path, *args, **kwargs):
        if path == unreadable:
            raise PermissionError('neutral unreadable context')
        return real_read(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', read)
    report = tmp_path / 'findings.json'
    rc = ba.main(['--dataset', '/neutral-dataset', '--json', str(report),
                  str(write), str(unreadable)])
    assert rc == ba.EXIT_VIOLATION
    assert [x['kind'] for x in json.loads(report.read_text())] == ['scorer-self-run']


@pytest.mark.parametrize('wrap', [lambda x: x, wrapper])
@pytest.mark.parametrize('command', ['node /tmp/helper.md', 'arbitrary_launcher /tmp/helper.md',
    'python3 report_lint.py /tmp/helper.md', 'node /tmp/he*per.md'])
def test_python_document_write_cannot_hide_later_unknown_execution(tmp_path, wrap, command):
    import subprocess
    import sys
    payload = 'const child = require("child_process");\nchild.execSync("' + COMMAND + '");\n'
    write_command = heredoc('from pathlib import Path\nPath("/tmp/helper.md").write_text(' + repr(payload) + ')')
    write = {'type': 'custom_tool_call', 'name': 'exec', 'call_id': 'python-writer',
             'input': wrap(write_command)}
    launch = {'type': 'function_call', 'name': 'exec_command', 'call_id': 'later-consumer',
              'arguments': json.dumps({'cmd': command})}
    a = tmp_path / 'a-write.jsonl'; b = tmp_path / 'b-consume.jsonl'
    report = tmp_path / 'findings.json'; coverage = tmp_path / 'coverage.json'
    a.write_text(json.dumps(write) + '\n'); b.write_text(json.dumps(launch) + '\n')
    result = subprocess.run([sys.executable, ba.__file__, '--dataset', '/neutral-dataset',
        '--json', str(report), '--coverage-json', str(coverage), str(a), str(b)],
        capture_output=True, text=True)
    assert result.returncode == ba.EXIT_VIOLATION, result.stdout + result.stderr
    assert [x['kind'] for x in json.loads(report.read_text())] == ['scorer-self-run']
    census = json.loads(coverage.read_text())
    assert (census['transcripts'], census['tool_calls'], census['inspected_tool_calls']) == (2, 2, 2)


def test_exact_retained_python_writer_node_counter_uses_actual_cli(tmp_path):
    import hashlib
    import subprocess
    import sys
    frames = [{'type': 'function_call', 'name': 'exec_command', 'call_id': 'write-python-document', 'arguments': '{"cmd": "python3 - <<\'PY\'\\nfrom pathlib import Path\\nPath(\'/tmp/helper.md\').write_text(\'let command = \\"python3 score_neutral.py --run neutral\\";\\\\nrequire(\\"child_process\\").execSync(command);\\\\n\')\\nPY"}'}, {'type': 'function_call', 'name': 'exec_command', 'call_id': 'node-exec-document', 'arguments': '{"cmd": "node /tmp/helper.md"}'}]
    encoded = '\n'.join(json.dumps(x) for x in frames)
    assert hashlib.sha256(encoded.encode()).hexdigest() == 'b910c5442e9f972542735664d116c67ae0ed784325aa91cc052bcd475f166e0b'
    a = tmp_path / 'write.jsonl'; b = tmp_path / 'launch.jsonl'
    a.write_text(json.dumps(frames[0]) + '\n'); b.write_text(json.dumps(frames[1]) + '\n')
    report = tmp_path / 'findings.json'; coverage = tmp_path / 'coverage.json'
    result = subprocess.run([sys.executable, ba.__file__, '--dataset', '/neutral-dataset',
        '--json', str(report), '--coverage-json', str(coverage), str(a), str(b)],
        capture_output=True, text=True)
    assert result.returncode == ba.EXIT_VIOLATION, result.stdout + result.stderr
    assert [x['kind'] for x in json.loads(report.read_text())] == ['scorer-self-run']
    census = json.loads(coverage.read_text())
    assert (census['transcripts'], census['tool_calls'], census['inspected_tool_calls']) == (2, 2, 2)
    assert [x['call_id'] for x in census['calls']] == ['write-python-document', 'node-exec-document']
