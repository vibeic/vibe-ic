"""Production Default inputs and tool handoff, without a mode controller."""
import json
from pathlib import Path
from types import SimpleNamespace
import subprocess

import pytest
import design_one_shot_runner as D
import librelane_contract as LC
import phase3_one_shot_runner as P3
from test_t91_step2_verilator_lint_gate import _design, _runner, put, NEG


def _lint(tmp_path, monkeypatch, *, target="pdkA"):
    project, src, calls, tool = _design(tmp_path, "librelane", NEG, 0, 1)
    # Ordinary Phase 2 has declared inputs but no mode switch.
    (project / "phase3/librelane_switch.json").unlink()
    (project / "input/project.json").unlink()
    put(project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json",
        {"doc_id": "L19", "fields": {"pdk_target": target}})
    monkeypatch.setattr(LC, "resolve_image", lambda *_: "img")
    monkeypatch.setattr(LC, "pdk_root_resolution", lambda *a, **k:
                        {"path": str(tmp_path / "pdkroot")})
    runner, step = _runner(monkeypatch, tool)
    return project, src, calls, step


def test_step2_default_uses_phase2_declared_pdk_and_normal_gate(tmp_path, monkeypatch):
    project, src, calls, step = _lint(tmp_path, monkeypatch)
    row = step(project)
    assert row is not None and row.status == "PASS", row
    cfg = project / "phase3/librelane/step2/lint_config.json"
    assert json.loads(cfg.read_text())["PDK"] == "pdkA"
    assert "L19" in json.loads(cfg.with_suffix(".provenance.json").read_text())["PDK"]
    assert any("librelane.steps" in c for c in calls)
    gate = json.loads((project / "reports/phase2/lint/verilator_lint_gate.json").read_text())
    assert gate["file_set"]["linted"] == [str(src.resolve())]
    assert row.extras["spec_conformance_tool_ports_rc"] is not None


@pytest.mark.parametrize("damage", ["missing", "conflict", "malformed", "untyped", "switch_conflict"])
def test_step2_bad_pdk_input_refuses_before_native_launch(tmp_path, monkeypatch, damage):
    project, _, calls, step = _lint(tmp_path, monkeypatch)
    target = project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"
    if damage == "missing":
        target.unlink()
    elif damage == "conflict":
        put(project / "input/project.json", {"pdk": "otherPDK"})
    elif damage == "malformed":
        target.write_text("{")
    elif damage == "untyped":
        put(target, {"fields": {"pdk_target": {"name": "pdkA"}}})
    else:
        put(project / "phase3/librelane_switch.json", {"pdk": "otherPDK"})
    row = step(project)
    assert row is not None and row.status == "FAIL", row
    assert "LL_PHASE2_PDK" in row.detail
    assert calls == []


def test_step2_project_input_is_an_existing_declared_source(tmp_path, monkeypatch):
    project, _, _, step = _lint(tmp_path, monkeypatch)
    (project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json").unlink()
    put(project / "input/project.json", {"pdk": "pdkA"})
    assert step(project).status == "PASS"


def test_step2_staged_pdk_cannot_mask_conflicting_l19(tmp_path, monkeypatch):
    project, _, calls, step = _lint(tmp_path, monkeypatch)
    put(project / 'phase1/pdk_staging_read.json', {'adopted_pdk_target': 'otherPDK'})
    assert step(project).status == 'FAIL'
    assert calls == []












def test_frontdoor_passes_the_selected_pdk_to_phase2():
    import vibe_ic_one_shot_runner as frontdoor
    common = dict(top_name="top", container="eda", max_rtl_repair_retries=3,
                  lec_max_completed_rungs=None, skip_hardware=True,
                  skip_phase3=False, skip_analog=True, entry_step="9", exit_step="14")
    argv = frontdoor._phase2_runner_argv(Path("/project"), pdk="secondaryKitD", **common)
    assert argv[argv.index("--pdk") + 1] == "secondaryKitD"
    assert "--pdk" not in frontdoor._phase2_runner_argv(Path("/project"), **common)


@pytest.mark.parametrize("primary,alternates,selected,expected", [
    ("primaryKit", ["secondaryKit"], "secondaryKitD", "secondaryKitD"),
    ("primaryKitA", [], "primaryKitB", "LL_PHASE2_PDK_CONFLICT"),
    ("custom_kit_q7", [], "custom_kit_q7", "custom_kit_q7"),
    ("primaryKit", [], "unrelatedKit", "LL_PHASE2_PDK_CONFLICT"),
    ("primaryKit", ["untyped alternate"], "primaryKit", "LL_PHASE2_PDK_INVALID"),
])
def test_selected_pdk_preserves_declaration_refusals(tmp_path, primary, alternates,
                                                   selected, expected):
    put(tmp_path / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json", {
        "fields": {"pdk_target": primary, "pdk_target_alternates": alternates}})
    if expected.startswith("LL_"):
        with pytest.raises(LC.Refusal) as exc:
            LC.phase2_pdk(tmp_path, selected=selected)
        assert exc.value.code == expected
    else:
        assert LC.phase2_pdk(tmp_path, selected=selected)[0] == expected


def test_phase2_pdk_uses_adopted_target_not_staged_family_as_second_declaration(
        tmp_path):
    """The Phase-1 staging record preserves provenance, not two targets."""
    put(tmp_path / "phase1/pdk_staging_read.json", {
        "staged_identifier": "gf180mcu",
        "adopted_pdk_target": "gf180mcuD",
        "adopted_evidence_source": "command_line",
    })
    put(tmp_path / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json", {
        "fields": {
            "pdk_target": "gf180mcuD",
            "pdk_target_alternates": ["gf180mcu"],
        }
    })

    assert LC.phase2_pdk(tmp_path, selected="gf180mcuD")[0] == "gf180mcuD"
