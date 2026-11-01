"""Docker option operands must not obscure or impersonate the image token."""
import importlib
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import librelane_contract as contract
from _hostpaths import require_repo


@pytest.mark.parametrize('option,value', [
    ('--pids-limit', '512'),
    ('--ulimit', 'nofile=1024:2048'),
    ('--security-opt', 'no-new-privileges'),
    ('--mount', 'type=bind,src=/data,dst=/data'),
    ('--env', 'NEUTRAL=1'),
    ('--env-file', '/data/env'),
    ('--memory-reservation', '128m'),
    ('--name', 'registry.invalid/option-operand'),
    ('--platform', 'linux/amd64'),
    ('--cpu-count', '2'),
    ('-m', '256m'),
    ('-w', '/work'),
    ('--cpus', '4'),
])
@pytest.mark.parametrize('typed', [False, True])
def test_value_options_preserve_the_exact_image_token(option, value, typed):
    image = object() if typed else 'registry.invalid/tools@sha256:' + 'ab' * 32
    argv = ['docker', 'run', '--rm', '--network', 'none', option, value,
            image, '--skip', 'bash', '-lc', 'echo --pids-limit']
    assert contract._container_image_arg(argv) is image


@pytest.mark.parametrize('prefix', [
    ['--unknown-value', 'registry.invalid/plausible-image'],
    ['--unknown-value=512'],
    ['--pids-limit'],
])
def test_ambiguous_image_refuses_before_any_launch(monkeypatch, prefix):
    monkeypatch.setenv(contract.LOCAL_PROVIDER_ROUTE_ENV, 'LOCAL')

    def forbidden(*args, **kwargs):
        pytest.fail('an ambiguous image reached a launch backend')

    monkeypatch.setattr(contract, '_run_local', forbidden)
    monkeypatch.setattr(contract.subprocess, 'run', forbidden)
    with pytest.raises(contract.Refusal, match='LL_LOCAL_IMAGE_UNRESOLVABLE'):
        contract.run_container(
            ['docker', 'run', *prefix, 'local://librelane@sha256:' + 'ab' * 32,
             '--skip', 'bash'], probe_deadline_s=1)


def test_missing_value_or_image_stays_unresolvable():
    assert contract._container_image_arg(['docker', 'run', '--pids-limit']) is None
    assert contract._container_image_arg(['docker', 'run', '--pids-limit', '512']) is None


def test_real_cvc_producer_reaches_the_selected_local_backend(tmp_path, monkeypatch):
    producer = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic',
                            'programs', 'phase3_one_shot_runner.py')
    runner = importlib.import_module(producer.stem)
    top = 'neutral_top'
    extracted = tmp_path / f'phase3/stage3/extracted/{top}.sp'
    adopted = tmp_path / f'phase3/stage3/pnr/{top}_pnr.v'
    extracted.parent.mkdir(parents=True)
    adopted.parent.mkdir(parents=True)
    extracted.write_text(f'.subckt {top} VDD VSS\n.ends\n')
    adopted.write_text(f'module {top}; endmodule\n')
    monkeypatch.setattr(runner, '_pdk_dir_of', lambda pdk: '/pdk/current')
    monkeypatch.setattr(runner, '_pdk_std_cell_library', lambda pdk: 'cells')
    monkeypatch.setattr(runner, '_design_supply_nets', lambda pdk: ({'VDD'}, {'VSS'}))
    monkeypatch.setenv(contract.LOCAL_PROVIDER_ROUTE_ENV, 'LOCAL')
    image = contract.LocalProviderIdentity(
        'local://librelane@sha256:' + 'ab' * 32, librelane_root=None,
        pdk_root='/pdk', pdk=None, source_sha256='cd' * 32,
        pdk_root_sha256=None, executable=sys.executable,
        executable_sha256='ef' * 32, source_kind='fixture', network_mode='none',
        network_namespace='fixture', network_helper=None, network_helper_sha256=None)
    calls = []

    def tool_edge(argv, **kwargs):
        calls.append(argv)
        assert contract._container_image_arg(argv) is image
        assert argv[argv.index('--pids-limit') + 1] == '512'
        assert kwargs['provider'] is image and kwargs['supervised'] is True
        return subprocess.CompletedProcess(argv, 23, '', 'fixture tool failure')

    monkeypatch.setattr(contract, '_run_local', tool_edge)
    category = runner._native_cvc_category(tmp_path, top, SimpleNamespace(), image)
    assert category['note'] == 'native CVC invocation failed; report is not evidence'
    assert category['native_rc'] == 23
    assert len(calls) == 1
    assert not (tmp_path / 'reports/phase3/cvc_native/result.json').exists()
