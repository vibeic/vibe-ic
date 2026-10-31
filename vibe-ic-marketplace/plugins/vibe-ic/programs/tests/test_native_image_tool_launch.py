"""Shared Docker tool launch contract, independent of any benchmark design."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import librelane_contract as contract


@pytest.mark.parametrize('entrypoint, prefix', [
    (None, []), (['/dockerstartup/scripts/ui_startup.sh'], ['--skip']),
])
def test_run_container_uses_the_image_launch_interface(monkeypatch, entrypoint, prefix):
    image = 'registry.invalid/tools@sha256:' + 'ab' * 32
    monkeypatch.setattr(contract._ce, 'no_container_route', lambda: False)
    monkeypatch.setattr(contract, '_provider_route_mismatch', lambda image: None)
    calls = []
    def docker(args, **kwargs):
        calls.append(args)
        if args[1:3] == ['image', 'inspect']:
            return subprocess.CompletedProcess(args, 0, json.dumps(entrypoint), '')
        assert args[1] == 'run' and '--name' in args
        assert args[args.index(image) + 1:] == [*prefix, 'yosys', '-V']
        return subprocess.CompletedProcess(args, 7, 'neutral tool output', '')
    monkeypatch.setattr(contract.subprocess, 'run', docker)
    result = contract.run_container(
        ['docker', 'run', '--rm', image, '--skip', 'yosys', '-V'],
        probe_deadline_s=3)
    assert len(calls) == 2
    assert result.returncode == 7 and result.stdout == 'neutral tool output'


@pytest.mark.parametrize('entrypoint, prefix', [
    (None, []), ([], []),
    (['/dockerstartup/scripts/ui_startup.sh'], ['--skip']),
])
@pytest.mark.parametrize('explicit_entrypoint', [False, True])
@pytest.mark.parametrize('user_option', [[], ['--user', '1000:1000'], ['-u', '1000:1000']])
def test_tool_enters_the_selected_images_environment(monkeypatch, entrypoint,
                                                    prefix, explicit_entrypoint, user_option):
    image = 'registry.invalid/tools@sha256:' + 'ab' * 32
    command = ['python3', '-c', 'print("neutral tool")']
    head = ['docker', 'run', '--rm', '--network', 'none',
            '--memory', '1g', '--memory-swap', '1g', '-v', '/data:/data:ro', *user_option]
    argv = ([*head, '--entrypoint', command[0], image, *command[1:]]
            if explicit_entrypoint else [*head, image, '--skip', *command])
    def inspect(args, **kw):
        assert args == ['docker', 'image', 'inspect', image, '--format',
                        '{{json .Config.Entrypoint}}']
        assert kw['timeout'] == 30
        return subprocess.CompletedProcess(args, 0, json.dumps(entrypoint), '')
    monkeypatch.setattr(contract.subprocess, 'run', inspect)
    assert contract._image_tool_argv(argv) == [*head, image, *prefix, *command]


@pytest.mark.parametrize('output, rc, expected', [
    ('["/unknown-entrypoint"]', 0, 'LL_IMAGE_ENTRYPOINT_UNSUPPORTED'),
    ('not json', 0, 'LL_IMAGE_ENTRYPOINT_UNAVAILABLE'),
    ('null', 1, 'LL_IMAGE_ENTRYPOINT_UNAVAILABLE'),
])
def test_unknown_image_authority_cannot_launch_a_tool(monkeypatch, output, rc, expected):
    monkeypatch.setattr(contract.subprocess, 'run', lambda args, **kw:
                        subprocess.CompletedProcess(args, rc, output, 'unavailable'))
    with pytest.raises(contract.Refusal, match=expected):
        contract._image_tool_argv(['docker', 'run', '--rm',
                                  'registry.invalid/tools@sha256:' + 'ab' * 32,
                                  '--skip', 'yosys', '-V'])
