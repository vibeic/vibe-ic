import subprocess

import pytest
import _cdc_netlist as native


def test_unsupported_host_yosys_uses_declared_image_for_systemverilog(tmp_path, monkeypatch):
    project = tmp_path / 'project'
    project.mkdir()
    source = project / 'rtl.sv'
    source.write_text('module top; endmodule\n')
    calls = []

    def run(argv, **kwargs):
        calls.append(list(argv))
        if argv[0] == '/usr/bin/yosys':
            return subprocess.CompletedProcess(argv, 1, '',
                'ERROR: No such command: read_slang')
        return subprocess.CompletedProcess(argv, 1, '', 'fallback failure control')

    monkeypatch.setattr(native.shutil, 'which', lambda _name: '/usr/bin/yosys')
    monkeypatch.setattr(native.subprocess, 'run', run)
    with pytest.raises(native.Refusal, match='CDC_NETLIST_BUILD_FAILED'):
        native.build(project, [source], 'top', image='declared-image')
    assert calls[0] == ['/usr/bin/yosys', '-p', 'read_slang -help']
    assert calls[1][:2] == ['docker', 'run']
    assert calls[1][calls[1].index('--entrypoint') + 1] == 'yosys'
    assert 'declared-image' in calls[1]
