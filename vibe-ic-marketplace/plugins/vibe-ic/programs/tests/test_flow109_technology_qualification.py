"""D03 native config resolution and ciel pin controls (in the EDA image)."""
from __future__ import annotations

import json
from pathlib import Path

import ciel
import pytest
import flow109
import flow109_technology_qualification as d03
from programs.tests._hostpaths import require_repo


def _case(tmp_path: Path, monkeypatch):
    project = tmp_path / "project"
    config = project / "phase3/librelane/config.json"
    config.parent.mkdir(parents=True)
    rtl = project / "input.v"
    rtl.write_text("module neutral(input clk, input a, output y); assign y = a; endmodule\n")
    # Resolve the installed family/variant from ciel, never copy a design/PDK
    # fixture or infer a pin from a historic campaign record.
    candidates = [(f, v) for f in ciel.Family.by_name.values()
                  if (Path("/foss/pdks/ciel") / f.name / "versions").is_dir()
                  for v in ciel.Version.get_all_installed("/foss/pdks", f.name)
                  if (Path(v.get_dir("/foss/pdks")) / f.default_variant).is_dir()]
    assert candidates, "native controls require an installed ciel PDK"
    family, pin = candidates[0]
    config.write_text(json.dumps({"meta": {"version": 2, "flow": "Chip"},
        "DESIGN_NAME": "neutral", "PDK": family.default_variant,
        "VERILOG_FILES": [str(rtl)], "CLOCK_PORT": "clk", "CLOCK_PERIOD": 20}))
    monkeypatch.setenv("VIBEIC_EDA_IMAGE", "example.invalid/eda@sha256:" + "e" * 64)
    monkeypatch.setenv("VIBEIC_LIBRELANE_PDK_ROOT", pin.get_dir("/foss/pdks"))
    context = {"requested_step": "D03", "resolved_row": {"id": "D03"},
               "context_sha256": "a" * 64}
    return project, context, rtl


def test_checked_in_registry_routes_default_d03_to_adapter():
    registry = json.loads(require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "flow", "flow109.json").read_text())
    row = next(item for item in registry["rows"] if item["id"] == "D03")
    dispatch = row["profiles"][0]["dispatch"]
    assert dispatch["adapter"] == "flow109_technology_qualification"
    assert dispatch["acceptance_scope"] == "existing_native_component_only"
    assert row["metric_acceptance_status"] == "IMPLEMENTED"
    assert "librelane_contract" not in row["source_components"]


def test_current_native_config_and_installed_pin_pass(tmp_path, monkeypatch):
    project, context, _ = _case(tmp_path, monkeypatch)
    result = d03.execute(project, context)
    assert result["component_status"] == "PASS"
    assert result["native_started"] is True
    assert result["metric_acceptance_status"] == "IMPLEMENTED"
    assert result["delivery_accepted"] is False
    assert result["metrics"]["tool_deck_corner_binding"]["pdk"]["revision"]
    consumed = flow109._selected_step_result(project, context, result, d03)
    assert consumed["default_row_status"] == "PASS" and consumed["completed"]
    assert consumed["whole_flow_acceptance"] == "NOT_MEASURED"


def test_missing_selected_io_library_preserves_native_failure(tmp_path, monkeypatch):
    project, context, _ = _case(tmp_path, monkeypatch)
    path = project / "phase3/librelane/config.json"
    config = json.loads(path.read_text())
    config["PAD_LIBS"] = {"*": [str(project / "missing_io.lib")]}
    path.write_text(json.dumps(config))
    result = d03.execute(project, context)
    assert result["component_status"] == "FAIL"
    assert result["native_started"] is True
    assert "missing_io.lib" in result["checks"][0]["detail"]
    assert result["completed"] is False


def test_removed_input_cannot_reuse_previous_native_pass(tmp_path, monkeypatch):
    project, context, rtl = _case(tmp_path, monkeypatch)
    first = d03.execute(project, context)
    assert first["default_row_status"] == "PASS"
    rtl.unlink()
    result = d03.execute(project, context)
    assert result["component_status"] == "FAIL"
    assert result["native_started"] is True
    assert result["reason"] == "D03_NATIVE_RESOLUTION_FAILED"
    assert result["completed"] is False


def test_missing_installed_pin_authority_is_named(tmp_path, monkeypatch):
    project, context, _ = _case(tmp_path, monkeypatch)
    monkeypatch.setattr(ciel.Version, "get_all_installed", lambda *args: [])
    result = d03.execute(project, context)
    assert result["component_status"] == "NOT_MEASURED"
    assert result["native_started"] is True
    assert result["reason"] == "D03_CIEL_PIN_UNRESOLVED"
    assert result["completed"] is False


def test_missing_runtime_image_refuses_before_native_resolution(tmp_path, monkeypatch):
    project, context, _ = _case(tmp_path, monkeypatch)
    monkeypatch.delenv("VIBEIC_EDA_IMAGE")
    result = d03.execute(project, context)
    assert result["component_status"] == "NOT_MEASURED"
    assert result["native_started"] is False
    assert result["reason"] == "D03_RUNTIME_IMAGE_UNRESOLVED"


def _native_bundle_case(tmp_path, monkeypatch):
    """Real installed image inputs, neutral design; never a PDK substitute."""
    import os
    root = Path(os.environ['PDK_ROOT']).resolve()
    candidates = [(family, family.default_variant) for family in ciel.Family.by_name.values()
                  if (root / family.default_variant / '.config/nodeinfo.json').is_file()]
    assert candidates, 'control requires a real bundled PDK source declaration'
    family, variant = candidates[0]
    project = tmp_path / 'neutral_native'
    config = project / 'phase3/librelane/config.json'
    config.parent.mkdir(parents=True)
    rtl = project / 'neutral.v'
    rtl.write_text('module neutral(input clk, input a, output y); assign y=a; endmodule\n')
    config.write_text(json.dumps({'meta': {'version': 2, 'flow': 'Classic'},
        'DESIGN_NAME': 'neutral', 'PDK': variant, 'VERILOG_FILES': [str(rtl)],
        'CLOCK_PORT': 'clk', 'CLOCK_PERIOD': 20}))
    monkeypatch.setenv('VIBEIC_LIBRELANE_PDK_ROOT', str(root))
    # Exact image is supplied by the actual host launch, not invented by tests.
    assert '@sha256:' in os.environ['VIBEIC_EDA_IMAGE']
    context = {'requested_step': 'D03', 'resolved_row': {'id': 'D03'},
               'context_sha256': 'b' * 64}
    return project, context, rtl


def test_native_bundle_uses_real_config_and_declared_revision(tmp_path, monkeypatch):
    project, context, _ = _native_bundle_case(tmp_path, monkeypatch)
    result = d03.execute(project, context)
    assert result['component_status'] == 'PASS', result
    pin = result['metrics']['tool_deck_corner_binding']['pdk']
    assert pin['authority'] == 'installed_pdk_revision'
    assert pin['revision_record']['resolved'] is True
    assert pin['source_files'] and pin['reader_source']
    assert all(Path(x['path']).is_file() for x in pin['source_files'])
    assert 'ciel_installed_pin' not in result['metrics']['required_capability_qualifications']
    consumed = flow109._selected_step_result(project, context, result, d03)
    assert consumed['default_row_status'] == 'PASS' and consumed['completed']
    assert consumed['whole_flow_acceptance'] == 'NOT_MEASURED'


def test_native_bundle_missing_rtl_preserves_real_sdk_failure(tmp_path, monkeypatch):
    project, context, rtl = _native_bundle_case(tmp_path, monkeypatch)
    rtl.unlink()
    result = d03.execute(project, context)
    assert result['component_status'] == 'FAIL', result
    assert result['reason'] == 'D03_NATIVE_RESOLUTION_FAILED'
    assert result['native_started'] and not result['completed']


@pytest.mark.parametrize('damage', ['missing', 'placeholder', 'malformed', 'other_variant', 'conflict'])
def test_pin_reader_refuses_bad_metadata(tmp_path, damage):
    """SOFTWARE metadata controls, no native PDK or qualification claim."""
    root = tmp_path / 'bundle'
    tree = root / 'unit_variant'
    source = tree / '.config/nodeinfo.json'
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps({'node': 'unit_variant', 'commit': {'open_pdks': '1' * 40}}))
    if damage == 'missing':
        source.unlink()
    elif damage == 'placeholder':
        source.write_text(json.dumps({'node': 'unit_variant', 'commit': {'open_pdks': 'NOT_A_REVISION'}}))
    elif damage == 'malformed':
        source.write_text('{broken')
    elif damage == 'other_variant':
        source.write_text(json.dumps({'node': 'other_variant', 'commit': {'open_pdks': '1' * 40}}))
    else:
        (tree / 'SOURCES').write_text('open_pdks ' + '2' * 40 + '\n')
    with pytest.raises(d03.D03Refusal) as refusal:
        d03._installed_pin(root, 'unit_variant', 'unit_family')
    assert refusal.value.code in {'D03_PDK_PIN_AUTHORITY_INVALID', 'D03_INSTALLED_PDK_PIN_UNRESOLVED'}


def test_missing_ciel_registration_cannot_fall_back_to_metadata(tmp_path, monkeypatch):
    root = tmp_path / 'ciel' / 'unit_family' / 'versions' / ('1' * 40)
    source = root / 'unit_variant/.config/nodeinfo.json'
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps({'node': 'unit_variant', 'commit': {'open_pdks': '1' * 40}}))
    monkeypatch.setattr(ciel.Version, 'get_all_installed', lambda *a: [])
    with pytest.raises(d03.D03Refusal) as refusal:
        d03._installed_pin(root, 'unit_variant', 'unit_family')
    assert refusal.value.code == 'D03_CIEL_PIN_UNRESOLVED'
