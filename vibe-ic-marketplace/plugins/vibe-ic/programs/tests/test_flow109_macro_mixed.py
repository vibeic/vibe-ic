"""D08/M03/M04 actual producer/consumer chain and reverse controls."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import flow109
import flow109_macro_mixed as rows
from _hostpaths import require_repo


def _ref(project, path):
    path = Path(path)
    return {"path": str(path.relative_to(project)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _write_manifest(project, step, inputs, **extra):
    path = project / f"input/flow109/{step}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": rows.SCHEMA, "step_id": step,
                                "inputs": [_ref(project, p) for p in inputs], **extra}, indent=2))
    return path


def _contexts():
    features = next(row["features"] for row in flow109.load_registry()["reference_profiles"]
                    if row["name"] == "Mixed hard-IP")
    features = {**features, "uses_macros": True, "has_power_intent": True}
    plan = flow109.resolve_plan(features)
    return {step: flow109.execution_context(plan, step, step)
            for step in ("D08", "M03", "M04")}


def _fixture(root):
    import pya
    source = require_repo("vibe-ic-marketplace/plugins/vibe-ic/programs/tests/fixtures/m2_placed")
    project = root / "project"
    shutil.copytree(source, project)
    macro = project / "phase3/analog/hardmacro/plain"
    macro.mkdir(parents=True)
    (macro / "plain.v").write_text("module plain(input A, output Y); endmodule\n")
    (macro / "plain.lef").write_text(
        "VERSION 5.8 ;\nMACRO plain\n CLASS BLOCK ;\n ORIGIN 0 0 ;\n"
        " SIZE 0.4 BY 0.4 ;\n PIN A\n  DIRECTION INPUT ;\n END A\n"
        " PIN Y\n  DIRECTION OUTPUT ;\n END Y\nEND plain\nEND LIBRARY\n")
    (macro / "plain_tt.lib").write_text(
        "library (plain_tt) { cell (plain) { pin(A) { direction : input; }"
        " pin(Y) { direction : output; function : \"A\"; } } }\n")
    ml = pya.Layout(); ml.dbu = 0.001
    mc = ml.create_cell("plain")
    mc.shapes(ml.layer(1, 0)).insert(pya.Box(0, 0, 400, 400))
    ml.write(str(macro / "plain.gds"))
    pnr = project / "phase3/stage3/pnr"
    digital = pya.Layout(); digital.dbu = 0.001
    top = digital.create_cell("boundary")
    for index, name in enumerate(("plain", "shift_cell", "clamp_cell", "plain")):
        cell = digital.cell(name) or digital.create_cell(name)
        if cell.is_empty():
            cell.shapes(digital.layer(1, 0)).insert(pya.Box(0, 0, 500, 500))
        top.insert(pya.CellInstArray(cell.cell_index(), pya.Trans((index + 1) * 1000, 1000)))
    digital.write(str(pnr / "boundary.gds"))
    # The existing M2 producer discovers this declaration at the Phase-3 path.
    analog = project / "phase3/analog/analog_block_list.json"
    analog.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(project / "phase1/analog/analog_block_list.json", analog)
    return project, macro


def test_registered_rows_use_only_the_bounded_adapter():
    contexts = _contexts()
    for step, context in contexts.items():
        dispatch = flow109.source_owned_native_dispatch(context["resolved_row"])
        assert dispatch["adapter"] == "flow109_macro_mixed"
        assert dispatch["native_step_id"] == "flow109." + step
        assert dispatch["acceptance_scope"] == "existing_native_component_only"


def test_actual_macro_merge_power_domain_chain_and_controls(tmp_path):
    project, macro = _fixture(tmp_path)
    contexts = _contexts()
    views = sorted(macro.iterdir())
    _write_manifest(project, "D08", views)
    d08 = rows.execute(project, contexts["D08"])
    assert d08["component_status"] == "PASS", d08
    assert d08["flow109_acceptance"] == "NOT_MEASURED"

    m03_inputs = views + [project / "phase3/stage3/pnr/boundary.gds",
                          project / "phase3/stage3/pnr/routed.def"]
    _write_manifest(project, "M03", m03_inputs, top="boundary", pdk=None,
                    predecessor=d08["receipt"])
    m03 = rows.execute(project, contexts["M03"])
    assert m03["component_status"] == "PASS", json.dumps(m03, indent=2)
    assert m03["physical_lvs_endpoint"] == "NOT_MEASURED"

    m04_inputs = [project / "phase3/mixed_signal/top_merged.gds",
                  project / "phase2/stage2/constraints/boundary.upf",
                  project / "phase3/stage3/pnr/boundary_pnr.v",
                  project / "phase3/stage3/pnr/routed.def",
                  project / "input/pdk/liberty/neutral.lib"]
    manifest = _write_manifest(project, "M04", m04_inputs, top="boundary",
                               predecessor=m03["receipt"])
    m04 = rows.execute(project, contexts["M04"])
    assert m04["component_status"] == "PASS", m04
    assert len(m04["consumers"]) == 5

    # Wrong source value reaches the actual producer and stays a measured FAIL.
    upf = project / "phase2/stage2/constraints/boundary.upf"
    original = upf.read_text()
    upf.write_text(original.replace(" -voltage 1.8", ""))
    body = json.loads(manifest.read_text())
    for record in body["inputs"]:
        if record["path"].endswith("boundary.upf"):
            record["sha256"] = hashlib.sha256(upf.read_bytes()).hexdigest()
    manifest.write_text(json.dumps(body, indent=2))
    wrong = rows.execute(project, contexts["M04"])
    assert wrong["component_status"] == "FAIL", wrong

    # Source-only restoration must re-enter the same producer and consumers.
    upf.write_text(original)
    body = json.loads(manifest.read_text())
    for record in body["inputs"]:
        if record["path"].endswith("boundary.upf"):
            record["sha256"] = hashlib.sha256(upf.read_bytes()).hexdigest()
    manifest.write_text(json.dumps(body, indent=2))
    restored = rows.execute(project, contexts["M04"])
    assert restored["component_status"] == "PASS", restored

    # Missing owner view refuses before the checklist can reuse its prior PASS.
    liberty = macro / "plain_tt.lib"
    original_liberty = liberty.read_bytes()
    liberty.unlink()
    missing = rows.execute(project, contexts["D08"])
    assert missing["component_status"] == "NOT_MEASURED"
    assert missing["reason"] == "D08_STALE_OR_MISSING_INPUT"
    liberty.write_bytes(original_liberty)
    assert rows.execute(project, contexts["D08"])["component_status"] == "PASS"

    # A changed view without a new owner record is stale, never a fresh FAIL/PASS.
    liberty.write_text(liberty.read_text() + "// stale\n")
    stale = rows.execute(project, contexts["D08"])
    assert stale["component_status"] == "NOT_MEASURED"
    assert stale["reason"] == "D08_STALE_OR_MISSING_INPUT"


def test_m03_missing_klayout_cannot_reuse_old_merge_receipt(tmp_path, monkeypatch):
    project, macro = _fixture(tmp_path)
    contexts = _contexts()
    views = sorted(macro.iterdir())
    _write_manifest(project, "D08", views)
    d08 = rows.execute(project, contexts["D08"])
    assert d08["component_status"] == "PASS", d08
    inputs = views + [project / "phase3/stage3/pnr/boundary.gds",
                      project / "phase3/stage3/pnr/routed.def"]
    _write_manifest(project, "M03", inputs, top="boundary", pdk=None,
                    predecessor=d08["receipt"])
    positive = rows.execute(project, contexts["M03"])
    assert positive["component_status"] == "PASS", positive
    receipt = project / "phase3/mixed_signal/m1_merge_receipt.json"
    old_sha = hashlib.sha256(receipt.read_bytes()).hexdigest()

    real_tool_ok = rows.m1._tool_ok
    monkeypatch.setattr(rows.m1, "_tool_ok",
                        lambda container, tool: False if tool == "klayout"
                        else real_tool_ok(container, tool))
    refused = rows.execute(project, contexts["M03"])
    assert hashlib.sha256(receipt.read_bytes()).hexdigest() == old_sha
    assert refused["component_status"] == "NOT_MEASURED", refused
    assert refused["reason"] == "M03_NATIVE_MERGE_NOT_MEASURED"


def test_m03_mixed_hard_ip_uses_a17_views_when_d08_is_not_selected(tmp_path):
    project, macro = _fixture(tmp_path)
    features = next(row["features"] for row in flow109.load_registry()["reference_profiles"]
                    if row["name"] == "Mixed hard-IP")
    plan = flow109.resolve_plan(features)
    selected = {row["id"] for row in plan["rows"]}
    assert "A17" in selected and "M03" in selected and "D08" not in selected
    context = flow109.execution_context(plan, "M03", "M03")
    inputs = sorted(macro.iterdir()) + [project / "phase3/stage3/pnr/boundary.gds",
                                        project / "phase3/stage3/pnr/routed.def"]
    _write_manifest(project, "M03", inputs, top="boundary", pdk=None)
    result = rows.execute(project, context)
    assert result["component_status"] == "PASS", result
    assert result["native_merge"]["path"].endswith("m1_merge_receipt.json")
    assert result["flow109_acceptance"] == "NOT_MEASURED"


def test_m03_selected_d08_stale_receipt_still_refuses(tmp_path):
    project, macro = _fixture(tmp_path)
    context = _contexts()["M03"]
    receipt_path = project / "reports/flow109/components/D08.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps({"schema": rows.SCHEMA, "step_id": "D08",
                                        "component_status": "PASS",
                                        "flow109_acceptance": "NOT_MEASURED"}))
    predecessor = _ref(project, receipt_path)
    inputs = sorted(macro.iterdir()) + [project / "phase3/stage3/pnr/boundary.gds",
                                        project / "phase3/stage3/pnr/routed.def"]
    _write_manifest(project, "M03", inputs, top="boundary", pdk=None,
                    predecessor=predecessor)
    receipt_path.write_text(receipt_path.read_text() + "\n")
    result = rows.execute(project, context)
    assert result["component_status"] == "NOT_MEASURED", result
    assert result["reason"] == "M03_PREDECESSOR_STALE"
