"""An ordinary functional endpoint needs its reasoned source decision only."""
import json
from types import SimpleNamespace

import pytest
import flow109
import _delivery_route
from test_flow109_selection import profile


@pytest.mark.parametrize("contract", [False, True])
def test_reasoned_non_scan_without_dft_contract_reaches_synthesis_owner(tmp_path, monkeypatch, contract):
    monkeypatch.setenv(flow109.CONTEXT_ENV, "")
    monkeypatch.delenv(flow109.ATTEMPT_ENV, raising=False)
    assert _delivery_route.admit(tmp_path, "ic") is None
    inp = tmp_path / "input"
    inp.mkdir(exist_ok=True)
    (inp / "feature-decisions.json").write_text(json.dumps({"dft": {
        "requires_scan": False, "reason": "Functional reusable core has no selected scan insertion architecture."}}))
    if contract:
        docs = inp / "docs"
        docs.mkdir()
        (docs / "L7_verification_plan.md").write_text(
            "The Plugin MUST declare `plugin_output/declaration.json` before authoring:\n"
            "| Field | Required | Example |\n|---|---|---|\n| `operating_mode` | Yes | functional |\n")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"features": profile()}))
    args = SimpleNamespace(flow="109", flow109_manifest=manifest,
        flow109_plan_only=False, execution_mode="default", entry_step="D22", exit_step="D22", container="")
    import design_one_shot_runner as producer
    import step_preflight
    import flow109_frontend as frontend
    from p0_tool_frontend_check import _top
    docs = tmp_path / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    (docs / 'L9_INTEGRATION_SPEC.json').write_text(json.dumps({'top_module': 'unit'}))
    (inp / 'project.json').write_text(json.dumps({'pdk': 'sky130A'}))
    def native(project, top, container, *args, **kwargs):
        assert top == _top(project) == 'unit'
        assert kwargs['pdk_name'] == 'sky130A'
        frontend.require_librelane_launch(project, 'Yosys.Synthesis')
        frontend.synthesis_fingerprint(project)
        raise RuntimeError('native producer reached')
    monkeypatch.setattr(producer, 'step_yosys_synth', native)
    monkeypatch.setattr(step_preflight, 'retained_call', lambda project, step, fn, *a, **kw: fn(*a, **{k:v for k,v in kw.items() if k != 'canonical_acceptance'}))
    with pytest.raises(RuntimeError, match='^native producer reached$'):
        flow109.prepare_front_door(args, tmp_path)
    plan = json.loads((tmp_path / "reports/flow109/plan.json").read_text())
    assert {"D23", "D24", "D36"}.isdisjoint(row["id"] for row in plan["rows"])
    assert not (tmp_path / "plugin_output/declaration.json").exists()


@pytest.mark.parametrize("damage", ["missing_reason", "scan_contract"])
def test_absent_or_conflicting_non_scan_intent_still_refuses(tmp_path, monkeypatch, damage):
    monkeypatch.setenv(flow109.CONTEXT_ENV, "")
    monkeypatch.delenv(flow109.ATTEMPT_ENV, raising=False)
    assert _delivery_route.admit(tmp_path, "ic") is None
    inp = tmp_path / "input"
    inp.mkdir(exist_ok=True)
    decision = {"requires_scan": False, "reason": "Functional reusable core has no selected scan insertion architecture."}
    if damage == "missing_reason": decision.pop("reason")
    (inp / "feature-decisions.json").write_text(json.dumps({"dft": decision}))
    if damage == "scan_contract":
        docs = inp / "docs"
        docs.mkdir()
        (docs / "L7_verification_plan.md").write_text(
            "The Plugin MUST declare `plugin_output/declaration.json` before authoring:\n"
            "| Field | Required | Example |\n|---|---|---|\n| `dft` | Yes | object |\n")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"features": profile()}))
    args = SimpleNamespace(flow="109", flow109_manifest=manifest,
        flow109_plan_only=False, execution_mode="default", entry_step="D22", exit_step="D22", container="")
    with pytest.raises(flow109.Flow109Error):
        flow109.prepare_front_door(args, tmp_path)
