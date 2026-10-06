"""Bounded source snapshot controls for one Ultra bootstrap."""
from dataclasses import replace
import hashlib
from pathlib import Path

import pytest

import execution_modes as em
from execution_source_snapshot import SourceSnapshot, using
from programs.tests import test_execution_modes as H


def test_source_closure_accepts_mapping_tuple_and_set_path_contracts(tmp_path):
    entry = tmp_path / 'entry.py'
    helper = tmp_path / 'helper.py'
    entry.write_text('import helper\n')
    helper.write_text('value = 1\n')
    paths = (str(entry),)
    mapping = {str(entry): hashlib.sha256(entry.read_bytes()).hexdigest()}
    expected = {entry.resolve(), helper.resolve()}
    assert em._source_closure(paths) == expected
    assert em._source_closure(mapping) == expected
    assert em._source_closure({str(entry)}) == expected


def test_identical_registrations_share_one_snapshot_and_git_tree():
    snapshot = SourceSnapshot(em._REPO_ROOT, H.BASE)
    with using(snapshot):
        first = H.adapter('a')
        second = replace(first, arm_id='b')
        registry = em.Registry(snapshot=snapshot)
        registry.register(first)
        registry.register(second)
        registry.finalize()
    assert snapshot.stats['git_tree_reads'] == 1
    assert snapshot.stats['git_commands'] == 6
    assert snapshot.stats['closure_hits'] > 0
    assert snapshot.stats['final_reads'] == snapshot.stats['file_reads']


def test_finalization_rejects_a_file_changed_after_snapshot(tmp_path):
    snapshot = SourceSnapshot(em._REPO_ROOT, H.BASE)
    changed = tmp_path / 'worker.py'
    changed.write_text('value = 1\n')
    with using(snapshot):
        snapshot.read_bytes(changed)
        changed.write_text('value = 2\n')
        with pytest.raises(RuntimeError, match='SOURCE_AUTHORITY_DIRTY'):
            snapshot.finalize()


def test_snapshot_cannot_answer_for_a_different_source_commit():
    snapshot = SourceSnapshot(em._REPO_ROOT, H.BASE)
    with pytest.raises(RuntimeError, match='SOURCE_AUTHORITY_STALE'):
        snapshot.git_blobs(f'{snapshot.commit}^', (em._canonical_flow_path(),))


def test_snapshot_preserves_canonical_portfolio_gate_and_default_outcome():
    portfolio = em.load_portfolio()
    expected = tuple((row['id'], tuple(row['mandatory_gate_programs']),
                      tuple(row['current_default']['source']['programs']))
                     for row in portfolio['steps'])
    snapshot = SourceSnapshot(em._REPO_ROOT, H.BASE)
    with using(snapshot):
        em._validate_portfolio(portfolio, snapshot=snapshot)
        actual = tuple((row['id'], tuple(row['mandatory_gate_programs']),
                        tuple(row['current_default']['source']['programs']))
                       for row in portfolio['steps'])
        snapshot.finalize()
    assert actual == expected


def test_snapshot_identity_cache_is_bounded_to_one_transaction(tmp_path):
    source = tmp_path / 'worker.py'
    source.write_bytes(b'value = 1\n')
    tracked = em._canonical_flow_path()
    snapshot = SourceSnapshot(em._REPO_ROOT, H.BASE)
    for _ in range(3):
        first = snapshot.digest(source)
        snapshot.git_blobs(snapshot.commit, (tracked,))
        snapshot.verify_tracked(tracked)
    assert snapshot.stats['path_resolutions'] == 2
    assert snapshot.stats['digest_computations'] == 1
    assert snapshot.stats['digest_cache_hits'] == 2
    assert snapshot.stats['blob_computations'] == 1
    assert snapshot.stats['blob_cache_hits'] == 2
    snapshot.finalize()
    source.write_bytes(b'value = 2\n')
    fresh = SourceSnapshot(em._REPO_ROOT, H.BASE)
    assert fresh.digest(source) != first
    fresh.finalize()


@pytest.mark.parametrize('mutation', ['parent_alias', 'leaf_alias', 'deleted'])
def test_snapshot_finalization_rechecks_original_path_target(tmp_path, mutation):
    first = tmp_path / 'first'
    second = tmp_path / 'second'
    first.mkdir(); second.mkdir()
    for directory in (first, second):
        (directory / 'worker.py').write_bytes(b'identical bytes\n')
    alias = tmp_path / 'alias'
    alias.symlink_to(first, target_is_directory=True)
    source = alias / 'worker.py'
    snapshot = SourceSnapshot(em._REPO_ROOT, H.BASE)
    original = snapshot.read_bytes(source)
    snapshot.digest(source)
    if mutation == 'parent_alias':
        alias.unlink(); alias.symlink_to(second, target_is_directory=True)
    else:
        (first / 'worker.py').unlink()
        if mutation == 'leaf_alias':
            (first / 'worker.py').symlink_to(second / 'worker.py')
    # Cached transaction bytes are provisional; unchanged contents must not
    # hide a changed path target or permit finalization after deletion.
    assert snapshot.read_bytes(source) == original
    with pytest.raises(RuntimeError, match='SOURCE_AUTHORITY_(DIRTY|UNAVAILABLE)'):
        snapshot.finalize()


@pytest.mark.parametrize('reader', ['modes', 'catalog'])
def test_snapshot_import_resolution_is_shared_across_seed_sets(tmp_path, reader):
    import execution_provider_catalog as catalog
    closure = em._source_closure if reader == 'modes' else catalog.source_closure
    counter = 'local_import_' if reader == 'modes' else 'provider_import_'
    entry = tmp_path / 'entry.py'
    helper = tmp_path / 'helper.py'
    entry.write_text('import helper\n')
    helper.write_text('value = 1\n')
    snapshot = SourceSnapshot(em._REPO_ROOT, H.BASE)
    with using(snapshot):
        expected = {entry, helper}
        assert closure((str(entry),)) == expected
        misses = snapshot.stats[counter + 'misses']
        assert closure((str(entry), str(helper))) == expected
        assert snapshot.stats[counter + 'misses'] == misses
        assert snapshot.stats[counter + 'hits'] >= 2
        snapshot.finalize()


@pytest.mark.parametrize('reader', ['modes', 'catalog'])
@pytest.mark.parametrize('mutation', ['new_local', 'leaf_alias', 'parent_alias'])
def test_snapshot_import_cache_rejects_changed_negative_resolution(tmp_path, mutation, reader):
    import execution_provider_catalog as catalog
    closure = em._source_closure if reader == 'modes' else catalog.source_closure
    entry = tmp_path / 'entry.py'
    if mutation == 'parent_alias':
        first = tmp_path / 'first'; first.mkdir()
        second = tmp_path / 'second'; second.mkdir()
        alias = tmp_path / 'late'; alias.symlink_to(first, target_is_directory=True)
        entry.write_text('import late.worker\n')
    else:
        entry.write_text('import snapshot_fresh_local_module\n')
    snapshot = SourceSnapshot(em._REPO_ROOT, H.BASE)
    with using(snapshot):
        assert closure((str(entry),)) == {entry}
        if mutation == 'new_local':
            (tmp_path / 'snapshot_fresh_local_module.py').write_text('value = 1\n')
        elif mutation == 'leaf_alias':
            (tmp_path / 'snapshot_fresh_local_module.py').symlink_to(tmp_path / 'missing.py')
        else:
            alias.unlink(); alias.symlink_to(second, target_is_directory=True)
        assert closure((str(entry),)) == {entry}
        with pytest.raises(RuntimeError, match='SOURCE_AUTHORITY_DIRTY'):
            snapshot.finalize()


def test_catalog_import_resolution_without_snapshot_remains_live(tmp_path):
    import execution_provider_catalog as catalog
    entry = tmp_path / 'entry.py'
    text = 'import snapshot_fresh_local_module\n'
    entry.write_text(text)
    assert catalog._local_imports(str(entry), text) == ()
    helper = tmp_path / 'snapshot_fresh_local_module.py'
    helper.write_text('value = 1\n')
    assert catalog._local_imports(str(entry), text) == (helper,)
