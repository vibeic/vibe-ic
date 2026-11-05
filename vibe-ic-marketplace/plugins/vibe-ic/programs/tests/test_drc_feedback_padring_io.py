"""Pad-ring IO masters stay in the canonical feedback reopen contract."""
from types import SimpleNamespace


import drc_feedback_repair as feedback


IMAGE = 'ghcr.io/vibeic/vibeic-eda@sha256:' + 'a' * 64








def test_local_antenna_command_reads_feedback_io_lef(monkeypatch, tmp_path):
    project = tmp_path / 'project'
    scratch = project / 'scratch'
    scratch.mkdir(parents=True)
    source = project / 'routed.def'
    source.write_text('DESIGN unit ;\n')
    seen = {}

    def fake_run(argv, *, cwd, env, capture_output, text, check):
        seen.update(argv=argv, cwd=cwd, env=env)
        return SimpleNamespace(
            returncode=0,
            stdout='[INFO ANT-0002] Found 0 net violations.\n'
                    '[INFO ANT-0001] Found 0 pin violations.\n',
            stderr='')

    monkeypatch.setattr(feedback._ce, 'no_container_route', lambda: True)
    monkeypatch.setattr(feedback.subprocess, 'run', fake_run)
    io_lef = '/pdk/io/pad.lef'
    assert feedback._antenna_baseline(
        IMAGE, project, [io_lef], source, scratch) == (0, 0)
    script = (scratch / 'antenna.tcl').read_text()
    assert f'read_lef {{{io_lef}}}' in script
    assert seen['argv'][0] == 'openroad'
    assert 'docker' not in seen['argv']
