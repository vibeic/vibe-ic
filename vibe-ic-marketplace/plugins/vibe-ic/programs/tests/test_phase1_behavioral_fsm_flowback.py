#!/usr/bin/env python3
"""Regression tests for the plain-Phase-1 behavioral-FSM flow-back.

The semantic recognizer is tested in its family suite.  These tests pin the
production runner boundary: plain prose can reach that recognizer, while an
incomplete spec, ambiguous top, non-behavioral registry result, or authored RTL
still DEFERs without touching the project.
"""
import json
from pathlib import Path
import shutil
import sys

import pytest


HERE = Path(__file__).resolve().parent
PROGRAMS = HERE.parent
sys.path.insert(0, str(PROGRAMS))

import design_one_shot_runner as runner  # noqa: E402
import spec_artifact_registry as registry  # noqa: E402
import rtl_provenance  # noqa: E402


COMPLETE_DIRECTIONAL_FALL = (
    HERE / "fixtures" / "real_benchmark" /
    "directional_bump_fall_moore_prompt.md").read_text()


@pytest.fixture(autouse=True)
def _isolated_runner_session(monkeypatch):
    """Each unit case models one runner process and leaves no atexit target."""
    monkeypatch.setattr(runner, "_RTL_SESSION_OWNED", False)
    monkeypatch.setattr(runner, "_RTL_SESSION_PROJECT", None)


def _project(tmp_path, text=COMPLETE_DIRECTIONAL_FALL, source="input_doc"):
    source_dir = tmp_path / "phase1" / source
    source_dir.mkdir(parents=True)
    (source_dir / "design.md").write_text(text)
    return tmp_path


@pytest.mark.parametrize("source", ["input_doc", "input_prompt"])
def test_plain_phase1_prose_emits_behavioral_fsm(tmp_path, source):
    project = _project(tmp_path, source=source)

    result = runner._try_phase1_behavioral_fsm_rtl(project, 0.0)

    assert result is not None and result.status == "PASS"
    assert result.extras == {
        "deterministic_generator": "spec_artifact_registry",
        "artifact_type": "behavioral_fsm",
        "module": "TopModule",
        "program_first": True,
        "spec_source": "phase1_plain_prose",
        "spec_sources": [f"phase1/{source}/design.md"],
        "rtl_provenance": "generated",
    }
    out = project / "phase2" / "stage1" / "rtl" / "TopModule.v"
    assert result.output_files == [str(out)]
    rtl = out.read_text()
    assert "module TopModule(" in rtl
    assert "S_WALK_LEFT" in rtl and "S_FALL_RIGHT" in rtl
    assert "always @(posedge clk or posedge areset)" in rtl


def test_step_rtl_gen_calls_phase1_flowback_before_class_fallback(tmp_path):
    project = _project(tmp_path)

    result = runner.step_rtl_gen(project, "deliberately_unregistered_class")

    assert result.status == "PASS"
    assert result.extras["artifact_type"] == "behavioral_fsm"
    assert (project / "phase2" / "stage1" / "rtl" / "TopModule.v").is_file()


def test_incomplete_directional_semantics_defer_without_writing(tmp_path):
    incomplete = COMPLETE_DIRECTIONAL_FALL.replace(
        "Being bumped in the same cycle as ground\n"
        "disappears does not affect the walking direction. ",
        "")
    project = _project(tmp_path, incomplete)

    assert runner._try_phase1_behavioral_fsm_rtl(project, 0.0) is None
    assert not (project / "phase2" / "stage1" / "rtl").exists()


def test_conflicting_declared_module_names_defer(tmp_path):
    project = _project(
        tmp_path, COMPLETE_DIRECTIONAL_FALL + "\nModule name: OtherTop\n")

    assert runner._try_phase1_behavioral_fsm_rtl(project, 0.0) is None
    assert not (project / "phase2" / "stage1" / "rtl").exists()


def test_authored_rtl_guard_never_overwrites(tmp_path):
    project = _project(tmp_path)
    rtl_dir = project / "phase2" / "stage1" / "rtl"
    rtl_dir.mkdir(parents=True)
    authored = rtl_dir / "authored.sv"
    authored.write_text("module authored; endmodule\n")

    assert runner._try_phase1_behavioral_fsm_rtl(project, 0.0) is None
    assert authored.read_text() == "module authored; endmodule\n"
    assert sorted(p.name for p in rtl_dir.iterdir()) == ["authored.sv"]


@pytest.mark.parametrize("suffix", [".vhd", ".vhdl"])
def test_authored_vhdl_guard_never_adds_competing_verilog(tmp_path, suffix):
    project = _project(tmp_path)
    rtl_dir = project / "phase2" / "stage1" / "rtl"
    rtl_dir.mkdir(parents=True)
    authored = rtl_dir / f"authored{suffix}"
    authored.write_text("entity authored is end entity;\n")

    assert runner._try_phase1_behavioral_fsm_rtl(project, 0.0) is None
    assert authored.read_text() == "entity authored is end entity;\n"
    assert not (rtl_dir / "TopModule.v").exists()


@pytest.mark.parametrize("suffix", [".vhd", ".vhdl"])
def test_force_regen_preserves_vhdl_before_emitting_verilog(tmp_path, suffix):
    project = _project(tmp_path)
    rtl_dir = project / "phase2" / "stage1" / "rtl"
    rtl_dir.mkdir(parents=True)
    authored = rtl_dir / f"authored{suffix}"
    authored.write_text("entity authored is end entity;\n")

    result = runner._try_phase1_behavioral_fsm_rtl(
        project, 0.0, force_regen=True)

    assert result is not None and result.status == "PASS"
    assert not authored.exists()
    assert (rtl_dir / "TopModule.v").is_file()
    backups = list((project / "phase2" / "stage1").glob(
        "rtl.authored_backup.*"))
    assert len(backups) == 1
    assert (backups[0] / f"authored{suffix}").read_text() == (
        "entity authored is end entity;\n")


def test_non_behavioral_registry_result_is_not_a_broad_plain_prose_path(
        tmp_path, monkeypatch):
    project = _project(tmp_path)
    monkeypatch.setattr(
        registry, "generate",
        lambda _text, top: ("truth_table", f"module {top}; endmodule\n"))

    assert runner._try_phase1_behavioral_fsm_rtl(project, 0.0) is None
    assert not (project / "phase2" / "stage1" / "rtl").exists()


def test_generated_ldoc_cannot_complete_incomplete_raw_prose(tmp_path):
    interface_only = COMPLETE_DIRECTIONAL_FALL.split(
        "Create a Moore state machine", 1)[0] + COMPLETE_DIRECTIONAL_FALL.split(
            "module TopModule", 1)[1]
    project = _project(tmp_path, interface_only)
    generated = project / "phase1" / "generated_docs"
    generated.mkdir(parents=True)
    (generated / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps({"summary": COMPLETE_DIRECTIONAL_FALL}))

    assert runner._try_phase1_behavioral_fsm_rtl(project, 0.0) is None
    assert not (project / "phase2" / "stage1" / "rtl").exists()


def test_symlinked_plain_source_cannot_relabel_generated_l9_as_program_first(
        tmp_path):
    """An L9-derived prose file is not operator input through a symlink alias."""
    project = _project(tmp_path)
    generated = project / "phase1" / "generated_docs"
    generated.mkdir(parents=True)
    l9_generated = generated / "L9_AI_GENERATED.md"
    l9_generated.write_text(COMPLETE_DIRECTIONAL_FALL)
    source = project / "phase1" / "input_doc" / "design.md"
    source.unlink()
    source.symlink_to(l9_generated)

    assert runner._gather_phase1_plain_spec_text(project) == ("", [])
    assert runner._try_phase1_behavioral_fsm_rtl(project, 0.0) is None
    assert not (project / "phase2" / "stage1" / "rtl").exists()


def test_symlinked_phase1_ancestor_cannot_relabel_external_l9_as_program_first(
        tmp_path):
    project = _project(tmp_path / "project")
    shutil.rmtree(project / "phase1")
    generated_root = tmp_path / "external_generated_root"
    input_doc = generated_root / "input_doc"
    input_doc.mkdir(parents=True)
    (input_doc / "L9_AI_GENERATED.md").write_text(COMPLETE_DIRECTIONAL_FALL)
    (project / "phase1").symlink_to(generated_root, target_is_directory=True)

    assert runner._gather_phase1_plain_spec_text(project) == ("", [])
    assert runner._try_phase1_behavioral_fsm_rtl(project, 0.0) is None
    assert not (project / "phase2" / "stage1" / "rtl").exists()


def test_symlinked_input_root_cannot_cross_the_source_boundary(tmp_path):
    project = _project(tmp_path / "project")
    shutil.rmtree(project / "phase1" / "input_doc")
    external = tmp_path / "external_input_doc"
    external.mkdir()
    (external / "design.md").write_text(COMPLETE_DIRECTIONAL_FALL)
    (project / "phase1" / "input_doc").symlink_to(
        external, target_is_directory=True)

    assert runner._gather_phase1_plain_spec_text(project) == ("", [])


def test_symlinked_descendant_invalidates_the_whole_source_tree(tmp_path):
    project = _project(tmp_path / "project")
    external = tmp_path / "external_descendant"
    external.mkdir()
    (external / "L9_AI_GENERATED.md").write_text(COMPLETE_DIRECTIONAL_FALL)
    (project / "phase1" / "input_doc" / "nested").symlink_to(
        external, target_is_directory=True)

    assert runner._gather_phase1_plain_spec_text(project) == ("", [])


@pytest.mark.parametrize("link_kind", ["out_of_root", "broken"])
def test_out_of_root_and_broken_source_symlinks_fail_closed(
        tmp_path, link_kind):
    project = _project(tmp_path / "project")
    source_dir = project / "phase1" / "input_doc"
    target = tmp_path / (
        "external_L9.md" if link_kind == "out_of_root" else "missing_L9.md")
    if link_kind == "out_of_root":
        target.write_text(COMPLETE_DIRECTIONAL_FALL)
    (source_dir / f"{link_kind}.md").symlink_to(target)

    assert runner._gather_phase1_plain_spec_text(project) == ("", [])


def test_provenance_stamp_makes_second_process_idempotent(tmp_path):
    project = _project(tmp_path)
    first = runner._try_phase1_behavioral_fsm_rtl(project, 0.0)
    assert first is not None and first.status == "PASS"
    assert rtl_provenance.classify(project)[0] == rtl_provenance.GENERATED

    # Model a fresh interpreter: only the on-disk provenance proof survives.
    runner._RTL_SESSION_OWNED = False
    runner._RTL_SESSION_PROJECT = None
    second = runner._try_phase1_behavioral_fsm_rtl(project, 0.0)
    assert second is not None and second.status == "PASS"
    assert second.extras["idempotent"] is True
    assert second.extras["rtl_provenance"] == rtl_provenance.GENERATED


def test_success_claims_session_with_non_capturing_atexit_callback(
        tmp_path, monkeypatch):
    registered = []
    monkeypatch.setattr(runner.atexit, "register", registered.append)
    project = _project(tmp_path)

    result = runner._try_phase1_behavioral_fsm_rtl(project, 0.0)

    assert result is not None and result.status == "PASS"
    assert registered == [runner._finalize_rtl_provenance]
    assert runner._RTL_SESSION_OWNED is True
    assert runner._RTL_SESSION_PROJECT == project


def test_runner_owned_later_file_is_included_by_exit_stamp(tmp_path):
    """Aliases/wrappers added after generation remain generated next run."""
    project = _project(tmp_path)
    result = runner._try_phase1_behavioral_fsm_rtl(project, 0.0)
    assert result is not None and result.status == "PASS"

    rtl_dir = project / "phase2" / "stage1" / "rtl"
    (rtl_dir / "runner_alias.v").write_text(
        "module runner_alias; endmodule\n")
    assert rtl_provenance.classify(project)[0] == rtl_provenance.AUTHORED

    runner._finalize_rtl_provenance()

    verdict, _why, evidence = rtl_provenance.classify(project)
    assert verdict == rtl_provenance.GENERATED
    assert evidence["file_count"] == 2
    assert set(rtl_provenance.load_ledger(project)["files"]) == {
        "TopModule.v", "runner_alias.v"}


def test_eco_reentry_keeps_deterministic_path_before_exit_stamp(tmp_path):
    """An alias added mid-run is runner-owned, not a reason to defer to AI."""
    project = _project(tmp_path)
    first = runner._try_phase1_behavioral_fsm_rtl(project, 0.0)
    assert first is not None and first.status == "PASS"

    rtl_dir = project / "phase2" / "stage1" / "rtl"
    alias = rtl_dir / "runner_alias.v"
    alias.write_text("module runner_alias; endmodule\n")
    assert rtl_provenance.classify(project)[0] == rtl_provenance.AUTHORED

    second = runner._try_phase1_behavioral_fsm_rtl(project, 0.0)

    assert second is not None and second.status == "PASS"
    assert second.extras["rtl_provenance"] == "session_owned"
    assert second.extras["idempotent"] is True
    assert alias.is_file()


def test_force_regen_updates_changed_generator_owned_rtl(tmp_path):
    project = _project(tmp_path)
    first = runner._try_phase1_behavioral_fsm_rtl(project, 0.0)
    assert first is not None and first.status == "PASS"
    source = project / "phase1" / "input_doc" / "design.md"
    source.write_text(COMPLETE_DIRECTIONAL_FALL.replace("bump_left", "hit_left"))

    held = runner._try_phase1_behavioral_fsm_rtl(project, 0.0)
    assert held is not None and held.status == "WAIVED"
    forced = runner._try_phase1_behavioral_fsm_rtl(
        project, 0.0, force_regen=True)
    assert forced is not None and forced.status == "PASS"
    rtl = (project / "phase2" / "stage1" / "rtl" / "TopModule.v").read_text()
    assert "hit_left" in rtl and "bump_left" not in rtl
    assert list((project / "phase2" / "stage1").glob("rtl.authored_backup.*"))
