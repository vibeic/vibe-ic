"""Pad-ring IO masters stay in the canonical feedback reopen contract."""
from types import SimpleNamespace

import pytest

import drc_feedback_repair as feedback
import phase3_one_shot_runner as runner


IMAGE = 'ghcr.io/vibeic/vibeic-eda@sha256:' + 'a' * 64


def _pdk():
    return runner.PdkConfig(
        name='test', liberty='/pdk/lib.lib', tech_lef='/pdk/tech.lef',
        cell_lef='/pdk/cell.lef', cell_gds='/pdk/cell.gds', site='core',
        drc_deck='/pdk/deck.drc', macro_lefs=['/pdk/existing.lef'])


def test_feedback_pdk_copy_merges_canonical_io_lefs_without_mutating_pdk(
        monkeypatch):
    pdk = _pdk()
    monkeypatch.setattr(
        runner, '_discover_padring_io_views',
        lambda _pdk, _container: (['/pdk/io/a.lef', '/pdk/existing.lef'],
                                  ['/pdk/io/a.gds']))

    feedback_pdk = runner._feedback_pdk_with_padring_io_views(pdk, 'eda')

    assert feedback_pdk is not pdk
    assert feedback_pdk.macro_lefs == ['/pdk/existing.lef', '/pdk/io/a.lef']
    assert pdk.macro_lefs == ['/pdk/existing.lef']


def test_feedback_pdk_copy_keeps_missing_io_view_fail_closed(monkeypatch):
    pdk = _pdk()
    monkeypatch.setattr(
        runner, '_discover_padring_io_views',
        lambda _pdk, _container: (_ for _ in ()).throw(
            ValueError('PADRING_IO_PHYSICAL_VIEWS_ABSENT')))

    with pytest.raises(ValueError, match='PADRING_IO_PHYSICAL_VIEWS_ABSENT'):
        runner._feedback_pdk_with_padring_io_views(pdk, 'eda')


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


def test_core_only_feedback_bypasses_pad_view_discovery(monkeypatch, tmp_path):
    pdk = _pdk()
    monkeypatch.setattr(runner, '_chip_path_requests_pad_ring',
                        lambda _project: False)
    def should_not_discover(*_args):
        raise AssertionError('core-only lane must not discover pad views')
    monkeypatch.setattr(runner, '_discover_padring_io_views', should_not_discover)

    resolved = runner._feedback_pdk_for_route(tmp_path, pdk, 'eda')

    assert resolved is pdk


def test_pad_ring_feedback_stays_fail_closed_when_views_are_missing(
        monkeypatch, tmp_path):
    pdk = _pdk()
    monkeypatch.setattr(runner, '_chip_path_requests_pad_ring',
                        lambda _project: True)
    monkeypatch.setattr(
        runner, '_discover_padring_io_views',
        lambda _pdk, _container: (_ for _ in ()).throw(
            ValueError('PADRING_IO_PHYSICAL_VIEWS_ABSENT')))

    with pytest.raises(ValueError, match='PADRING_IO_PHYSICAL_VIEWS_ABSENT'):
        runner._feedback_pdk_for_route(tmp_path, pdk, 'eda')


def test_pad_ring_discovery_refusal_writes_auditable_receipt(tmp_path):
    pdk = _pdk()
    receipt = runner._write_feedback_padring_discovery_refusal(
        tmp_path, 'unit', pdk, IMAGE,
        ValueError('PADRING_IO_PHYSICAL_VIEWS_ABSENT'))

    doc = __import__('json').loads(receipt.read_text())
    assert doc['status'] == 'REFUSED'
    assert doc['reason'] == 'PADRING_IO_VIEW_DISCOVERY_FAILED'
    assert 'PADRING_IO_PHYSICAL_VIEWS_ABSENT' in doc['detail']
    assert doc['source_def'].endswith('/phase3/stage3/pnr/unit.def')
    assert doc['image'] == IMAGE
    assert isinstance(doc['rules'], list)
