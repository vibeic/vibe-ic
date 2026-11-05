"""Bounded source snapshot controls for one Ultra bootstrap."""






















def test_catalog_import_resolution_without_snapshot_remains_live(tmp_path):
    import execution_provider_catalog as catalog
    entry = tmp_path / 'entry.py'
    text = 'import snapshot_fresh_local_module\n'
    entry.write_text(text)
    assert catalog._local_imports(str(entry), text) == ()
    helper = tmp_path / 'snapshot_fresh_local_module.py'
    helper.write_text('value = 1\n')
    assert catalog._local_imports(str(entry), text) == (helper,)
