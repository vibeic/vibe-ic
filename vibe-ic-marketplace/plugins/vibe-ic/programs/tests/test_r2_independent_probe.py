"""Current L9 subject regressions from the independent R2 review."""
import json

import _plugin_tree  # noqa: F401
import pytest
import synth_handoff_netlist_check as H
from test_default_frontend_r2 import _produce, put


def test_current_l9_top_drift_cannot_credit_old_handoff(tmp_path, monkeypatch):
    project, _, _ = _produce(tmp_path, monkeypatch)
    l9 = project / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    doc = json.loads(l9.read_text())
    doc["top_module"] = "other_current_top"
    put(l9, doc)
    report = H.bound_handoff(project)
    assert report["verdict"] == "FAIL", report


@pytest.mark.parametrize('shape', ['flat', 'fields'])
def test_supported_current_l9_subject_keeps_valid_handoff_credit(tmp_path, monkeypatch, shape):
    project, _, _ = _produce(tmp_path, monkeypatch)
    l9 = project / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json'
    if shape == 'fields':
        put(l9, {'doc_id': 'L9', 'fields': json.loads(l9.read_text())})
    assert H.bound_handoff(project)['verdict'] == 'PASS'
    import phase3_one_shot_runner as P3
    assert P3.pnr_input_netlist(project, 'top')[0].read_bytes() == (
        project / 'phase2/stage2/synth/netlist.v').read_bytes()


@pytest.mark.parametrize('damage', ['missing', 'malformed', 'fields_drift'])
def test_unreadable_or_changed_canonical_l9_subject_cannot_credit_handoff(tmp_path, monkeypatch, damage):
    project, _, _ = _produce(tmp_path, monkeypatch)
    l9 = project / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json'
    if damage == 'missing':
        l9.unlink()
    elif damage == 'malformed':
        l9.write_text('{')
    else:
        put(l9, {'top_module': 'top', 'fields': {'top_module': 'other_current_top'}})
    assert H.bound_handoff(project)['verdict'] == 'FAIL'
