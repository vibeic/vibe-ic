"""Run-local registry configuration reaches the existing selection readers."""
import json

import pdk_family_identity as identity






def test_explicit_registry_path_precedes_environment(tmp_path, monkeypatch):
    selected = tmp_path / 'selected.json'
    explicit = tmp_path / 'explicit.json'
    selected.write_text(json.dumps({'pdks': [{'name': 'selected-kit'}]}))
    expected = {'pdks': [{'name': 'explicit-kit'}]}
    explicit.write_text(json.dumps(expected))
    monkeypatch.setenv('VIBEIC_PDK_REGISTRY', str(selected))
    assert identity.load_registry(explicit) == expected
