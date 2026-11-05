"""Run-local registry configuration reaches the existing selection readers."""
import json

import pytest
import pdk_family_identity as identity
import phase3_one_shot_runner as backend


def test_configured_registry_reaches_existing_backend_and_family_reader(tmp_path, monkeypatch):
    target = 'example-kit-r2'
    entry = {'name': target, 'site': 'example_site'}
    registry = tmp_path / 'registry.json'
    registry.write_text(json.dumps({'pdks': [entry]}))
    monkeypatch.setenv('VIBEIC_PDK_REGISTRY', str(registry))
    monkeypatch.setattr(backend._pdk_registry_entry, '_cache', {})
    try:
        backend._assert_pdk_name_resolvable(target)
        observed = target
    except ValueError as exc:
        observed = str(exc)
    assert observed == target
    assert backend._pdk_registry_entry(target) == entry
    assert identity.canonical_entry(target, exact_distribution=True) == (target, entry)
    with pytest.raises(ValueError, match='unknown PDK'):
        backend._assert_pdk_name_resolvable(target + '-other')


@pytest.mark.parametrize('content', [None, '{broken'])
def test_unreadable_config_does_not_substitute_bundled_registry(tmp_path, monkeypatch, content):
    registry = tmp_path / 'registry.json'
    if content is not None:
        registry.write_text(content)
    monkeypatch.setenv('VIBEIC_PDK_REGISTRY', str(registry))
    monkeypatch.setattr(backend._pdk_registry_entry, '_cache', {})
    assert backend._known_pdk_names() == sorted(backend._PDK_NAMED_BRANCHES)
    assert identity.load_registry() == {}


def test_explicit_registry_path_precedes_environment(tmp_path, monkeypatch):
    selected = tmp_path / 'selected.json'
    explicit = tmp_path / 'explicit.json'
    selected.write_text(json.dumps({'pdks': [{'name': 'selected-kit'}]}))
    expected = {'pdks': [{'name': 'explicit-kit'}]}
    explicit.write_text(json.dumps(expected))
    monkeypatch.setenv('VIBEIC_PDK_REGISTRY', str(selected))
    assert identity.load_registry(explicit) == expected
