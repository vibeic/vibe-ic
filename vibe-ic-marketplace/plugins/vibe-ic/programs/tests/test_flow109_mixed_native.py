"""Focused positive, wrong-value, restoration and stale-readset controls."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

import flow109_mixed_native as mixed


TEST_IMAGE = "registry.example/vibeic-eda@sha256:" + "a" * 64


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def context(step):
    return {"requested_step": step, "native_step_id": "flow109." + step,
            "context_sha256": "c" * 64,
            "resolved_row": {"id": step, "obligations": [
                {"id": item} for item in mixed.ROWS[step]["obligations"]],
                "profile": {"dispatch": {"adapter": "flow109_mixed_native"}}}}


def project(tmp_path, step, *, wrong=False):
    root = tmp_path / step
    source = root / "input.bin"
    geometry = root / "phase3/mixed_signal/top_merged.gds"
    authority = root / "input/flow109" / (step + ".json")
    source.parent.mkdir(parents=True)
    geometry.parent.mkdir(parents=True)
    authority.parent.mkdir(parents=True)
    source.write_bytes(b"current input\n")
    if step != "M07":
        geometry.write_bytes(b"current geometry\n")
    manifest = {
        "schema": mixed.INPUT_SCHEMA, "step_id": step,
        "scope": mixed.ROWS[step]["scope"], "top": "chip_top", "pdk": "gf180mcuD",
        "image": TEST_IMAGE,
        "input_sha256": {"input.bin": ("0" * 64 if wrong else sha(source))},
        **({"required_scenarios": ["functional"]} if step in ("M06", "M08") else {}),
        **({"d69_receipt": {"path": "reports/flow109/D69/current/component.json"}}
           if step == "M08" else {}),
        **({"m08_receipt": {"path": "reports/flow109/M08/current/component.json"}}
           if step == "M09" else {})}
    if step != "M07":
        manifest["geometry_sha256"] = sha(geometry)
    authority.write_text(json.dumps(manifest))
    return root


def install_fakes(monkeypatch):
    monkeypatch.setattr(mixed, "_runtime_image", lambda _project: TEST_IMAGE)
    monkeypatch.setattr(mixed, "_current_inputs",
                        lambda project, _step, _top, _manifest=None:
                        {"input.bin": sha(project / "input.bin")})
    monkeypatch.setattr(mixed, "operation_sources", lambda: {"programs/fake.py": "f" * 64})
    monkeypatch.setattr(mixed, "_final_parasitic_binding", lambda project, manifest: {
        "d69_receipt": manifest.get("d69_receipt"), "selected_corner": "nom_*",
        "final_geometry": {"path": "final.odb", "sha256": "1" * 64},
        "final_spefs": {"nom_*": {"path": "final.spef", "sha256": "2" * 64}},
        "fill_sensitive_parasitics": {"status": "PASS"}, "inputs": {}}, raising=False)
    monkeypatch.setattr(mixed, "_m09_prerequisites", lambda project, manifest: {
        "m08_completion": {"default_row_status": "PASS", "completed": True},
        "a19_packages": {"adc": {"signoff_sha256": "3" * 64}}, "inputs": {}}, raising=False)
    monkeypatch.setattr(mixed, "_semantic_pass",
                        lambda project, step, manifest: {
                            "step": step, "scope": manifest["scope"],
                            "geometry_sha256": sha(project / "phase3/mixed_signal/top_merged.gds"),
                            **({"final_parasitics": {"fill_sensitive_parasitics": {"status": "PASS"}}}
                               if step == "M08" else {})})
    monkeypatch.setattr(mixed, "_command_plan", lambda project, step, manifest, attempt: (
        [sys.executable, "-c",
         (("from pathlib import Path; Path(" + repr(str(project / "phase3/mixed_signal/top_merged.gds"))
           + ").write_bytes(b'producer geometry\\n'); ") if step == "M07" else "")
         + "print('producer')"],
        [[sys.executable, "-c", "print('consumer')"]]))


@pytest.mark.parametrize("step", tuple(mixed.ROWS))
def test_each_registered_row_needs_native_chain_then_current_consumer(monkeypatch, tmp_path, step):
    install_fakes(monkeypatch)
    root = project(tmp_path, step)
    component = mixed.execute(root, context(step))
    assert component["component_status"] == "PASS"
    result = mixed.consume_default_row_completion(root, context(step), component)
    assert result["default_row_status"] == "PASS"
    assert result["completed"] is True
    assert result["flow109_acceptance"] == "NOT_MEASURED"
    assert result["whole_ic_acceptance"] == "NOT_MEASURED"


def test_wrong_value_refuses_before_any_native_command_then_restoration_passes(monkeypatch, tmp_path):
    install_fakes(monkeypatch)
    calls = []
    original = mixed._run
    monkeypatch.setattr(mixed, "_run", lambda *args, **kwargs: calls.append(args) or original(*args, **kwargs))
    root = project(tmp_path, "M06", wrong=True)
    refused = mixed.execute(root, context("M06"))
    assert refused["component_status"] == "NOT_MEASURED"
    assert refused["reason"] == "MIXED_ROW_INPUT_STALE_OR_INCOMPLETE"
    assert calls == []
    authority = root / "input/flow109/M06.json"
    value = json.loads(authority.read_text())
    value["input_sha256"]["input.bin"] = sha(root / "input.bin")
    authority.write_text(json.dumps(value))
    restored = mixed.execute(root, context("M06"))
    assert restored["component_status"] == "PASS"
    assert len(calls) == 2


def test_manifest_image_must_match_runtime_resolution(monkeypatch, tmp_path):
    install_fakes(monkeypatch)
    calls = []
    monkeypatch.setattr(mixed, "_run", lambda *args, **kwargs: calls.append(args))
    root = project(tmp_path, "M07")
    monkeypatch.setattr(mixed, "_runtime_image",
                        lambda _project: "registry.example/vibeic-eda@sha256:" + "b" * 64)
    refused = mixed.execute(root, context("M07"))
    assert refused["component_status"] == "NOT_MEASURED"
    assert refused["reason"] == "MIXED_ROW_INPUT_INVALID"
    assert refused["native_started"] is False
    assert calls == []


def test_runtime_image_refusal_is_local_not_measured_before_native(monkeypatch, tmp_path):
    import librelane_contract as librelane

    root = project(tmp_path, "M07")
    calls = []
    monkeypatch.setattr(
        librelane, "resolve_image",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            librelane.Refusal("LL_IMAGE_NOT_RESOLVABLE", "no current image attestation")))
    monkeypatch.setattr(mixed, "_run", lambda *args, **kwargs: calls.append(args))

    refused = mixed.execute(root, context("M07"))
    assert refused["component_status"] == "NOT_MEASURED"
    assert refused["reason"] == "LL_IMAGE_NOT_RESOLVABLE"
    assert refused["detail"] == (
        "LL_IMAGE_NOT_RESOLVABLE: no current image attestation")
    assert refused["native_started"] is False
    assert calls == []


def test_changed_consumed_input_refuses_completion_without_replay(monkeypatch, tmp_path):
    install_fakes(monkeypatch)
    root = project(tmp_path, "M07")
    component = mixed.execute(root, context("M07"))
    (root / "input.bin").write_bytes(b"changed after native\n")
    result = mixed.consume_default_row_completion(root, context("M07"), component)
    assert result["default_row_status"] == "NOT_MEASURED"
    assert result["reason"] == "MIXED_ROW_INPUT_STALE_OR_INCOMPLETE"


def test_changed_native_log_refuses_completion(monkeypatch, tmp_path):
    install_fakes(monkeypatch)
    root = project(tmp_path, "M09")
    component = mixed.execute(root, context("M09"))
    log = next((root / "reports/flow109/M09").glob("*/command-00.log"))
    log.write_text("changed\n")
    result = mixed.consume_default_row_completion(root, context("M09"), component)
    assert result["default_row_status"] == "NOT_MEASURED"
    assert result["reason"] == "MIXED_ROW_COMPLETION_EVIDENCE_STALE"


def test_m07_first_assembly_invokes_producer_without_preexisting_output(monkeypatch, tmp_path):
    install_fakes(monkeypatch)
    root = project(tmp_path, "M07")
    merged = root / "phase3/mixed_signal/top_merged.gds"
    assert not merged.exists()
    component = mixed.execute(root, context("M07"))
    assert component["component_status"] == "PASS"
    assert component["native_started"] is True
    assert component["commands"][0]["returncode"] == 0
    assert merged.read_bytes() == b"producer geometry\n"


def test_m08_candidate_only_rc_cannot_complete_final_row(monkeypatch, tmp_path):
    install_fakes(monkeypatch)
    root = project(tmp_path, "M08")
    component = mixed.execute(root, context("M08"))
    assert component["component_status"] == "PASS"
    component["evidence"]["final_parasitics"]["fill_sensitive_parasitics"] = {
        "status": "NOT_MEASURED", "reason": "candidate-only RC"}
    receipt = root / component["receipt"]["path"]
    receipt.write_text(json.dumps(component))
    monkeypatch.setattr(mixed, "_semantic_pass", lambda *_args, **_kwargs: component["evidence"])
    result = mixed.consume_default_row_completion(root, context("M08"), component)
    assert result["default_row_status"] == "NOT_MEASURED"
    assert result["completed"] is False
    assert result["reason"] == "MIXED_ROW_FINAL_PARASITICS_NOT_QUALIFIED"


def test_m09_old_or_missing_m08_a19_refuses_before_signoff_launch(monkeypatch, tmp_path):
    import _mixed_signal_top_pv as top_pv
    import mixed_signal_m3_run as m3

    actual_current_inputs = mixed._current_inputs
    install_fakes(monkeypatch)
    calls = []
    original_run = mixed._run
    monkeypatch.setattr(mixed, "_run",
                        lambda *args, **kwargs: calls.append(args) or original_run(*args, **kwargs))
    monkeypatch.setattr(mixed, "_m09_prerequisites",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(
                            mixed.Refusal("MIXED_ROW_FINAL_AMS_NOT_COMPLETE", "old M08/A19")),
                        raising=False)
    monkeypatch.setattr(mixed, "_current_inputs", actual_current_inputs)
    root = project(tmp_path, "M09")
    monkeypatch.setattr(top_pv, "request",
                        lambda *_args: ({}, {"input.bin": sha(root / "input.bin")}))
    for name in (m3.RECEIPT, m3.DIR + "/merge.json", m3.DIR + "/top_lvs.json",
                 m3.DIR + "/power_domain_run.json"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
    expected = {"input.bin": sha(root / "input.bin")}
    expected.update({name: sha(root / name) for name in (
        m3.RECEIPT, m3.DIR + "/merge.json", m3.DIR + "/top_lvs.json",
        m3.DIR + "/power_domain_run.json")})
    authority = root / "input/flow109/M09.json"
    value = json.loads(authority.read_text())
    value["input_sha256"] = dict(sorted(expected.items()))
    authority.write_text(json.dumps(value))
    refused = mixed.execute(root, context("M09"))
    assert refused["component_status"] == "NOT_MEASURED"
    assert refused["reason"] == "MIXED_ROW_FINAL_AMS_NOT_COMPLETE"
    assert refused["native_started"] is False
    assert calls == []


def test_m08_final_reader_binds_selected_d69_spef_and_rejects_candidate(monkeypatch, tmp_path):
    import _mixed_signal_native as native
    import flow109_final_extract as final_extract

    root = tmp_path.resolve()
    paths = {}
    for name in ("d69.json", "final.odb", "filled.def", "final.spef", "candidate.spef", "chip.nl.v"):
        path = root / name
        path.write_text(name)
        paths[name] = {"path": name, "sha256": sha(path)}
    final = {"component_parasitics_current": True,
             "final_geometry": paths["final.odb"], "filled_def": paths["filled.def"],
             "final_spefs": {"nom_*": paths["final.spef"]},
             "adopted_views": {"netlist": paths["chip.nl.v"]},
             "fill_sensitive_parasitics": {"status": "NOT_MEASURED"}}
    monkeypatch.setattr(final_extract, "validate_final_parasitics", lambda *_args: final)
    monkeypatch.setattr(native, "contract", lambda *_args: {
        "si": {"spef": "final.spef"}, "digital": {"netlist": "chip.nl.v"}})
    manifest = {"top": "chip_top", "d69_receipt": paths["d69.json"]}
    bound = mixed._final_parasitic_binding(root, manifest)
    assert bound["selected_corner"] == "nom_*"
    assert bound["fill_sensitive_parasitics"]["status"] == "NOT_MEASURED"
    monkeypatch.setattr(native, "contract", lambda *_args: {
        "si": {"spef": "candidate.spef"}, "digital": {"netlist": "chip.nl.v"}})
    with pytest.raises(mixed.Refusal, match="MIXED_ROW_FINAL_PARASITICS_NOT_CONSUMED"):
        mixed._final_parasitic_binding(root, manifest)


def test_m09_reader_requires_current_m08_and_complete_current_a19(monkeypatch, tmp_path):
    import analog_hardmacro_check as hardmacro
    import analog_native_flow as analog
    import flow109

    root = tmp_path.resolve()
    (root / "reports/flow109/M08/current").mkdir(parents=True)
    (root / "reports/flow109/requests").mkdir(parents=True)
    (root / "reports/analog_native").mkdir(parents=True)
    (root / "phase3/analog/adc").mkdir(parents=True)
    m08 = root / "reports/flow109/M08/current/component.json"
    request = root / "reports/flow109/requests" / ("c" * 64 + ".json")
    input_view = root / "phase3/analog/adc/source.sp"
    signoff = root / "phase3/analog/adc/signoff.json"
    input_view.write_text("current analog source\n")
    m08.write_text(json.dumps({"context_sha256": "c" * 64}))
    request.write_text(json.dumps({"requested_step": "M08"}))
    deliverables = {suffix: "d" * 64 for suffix in ("gds", "lef", "lib", "v")}
    signoff.write_text(json.dumps({"block": "adc", "status": "PASS",
        "steps": [{"status": "PASS"}] * 18, "deliverables": deliverables,
        "native_package_summary": {"design_bound_blocks": ["adc"]}}))
    status = {"source_sha256": sha(Path(analog.__file__)), "steps": [{
        "step": "A19", "block": "adc", "status": "PASS",
        "producer_context": {"image": TEST_IMAGE,
                             "driver_sha256": sha(Path(analog.__file__))},
        "input_views": {str(input_view): sha(input_view)},
        "output_views": {str(signoff): sha(signoff)}}]}
    (root / "reports/analog_native/status.json").write_text(json.dumps(status))
    monkeypatch.setattr(flow109, "validate_execution_context", lambda value: value)
    monkeypatch.setattr(hardmacro, "_load_block_list", lambda _project: ["adc"])
    monkeypatch.setattr(hardmacro, "run_audit", lambda _project: SimpleNamespace(
        passed=True, summary={"design_bound_blocks": ["adc"]}))
    manifest = {"m08_receipt": {"path": str(m08.relative_to(root)), "sha256": sha(m08)}}

    monkeypatch.setattr(mixed, "consume_default_row_completion", lambda *_args: {
        "default_row_status": "NOT_MEASURED", "completed": False, "reason": "stale M08"})
    with pytest.raises(mixed.Refusal, match="MIXED_ROW_FINAL_AMS_NOT_COMPLETE"):
        mixed._m09_prerequisites(root, manifest)

    monkeypatch.setattr(mixed, "consume_default_row_completion", lambda *_args: {
        "default_row_status": "PASS", "completed": True})
    bound = mixed._m09_prerequisites(root, manifest, TEST_IMAGE)
    assert set(bound["a19_packages"]) == {"adc"}
    input_view.write_text("stale analog source\n")
    with pytest.raises(mixed.Refusal, match="MIXED_ROW_A19_VIEW_STALE"):
        mixed._m09_prerequisites(root, manifest, TEST_IMAGE)


def test_registry_dispatch_is_narrowly_scoped_to_assigned_rows():
    registry = json.loads((Path(__file__).parents[2] / "flow/flow109.json").read_text())
    rows = {row["id"]: row for row in registry["rows"]}
    for step in mixed.ROWS:
        dispatch = rows[step]["profiles"][0]["dispatch"]
        assert dispatch["adapter"] == "flow109_mixed_native"
        assert dispatch["native_step_id"] == "flow109." + step
    assert rows["M03"]["profiles"][0].get("dispatch", {}).get("adapter") != "flow109_mixed_native"
