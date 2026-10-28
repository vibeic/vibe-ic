"""RTL transaction/stamp source controls; no native design qualification."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import design_one_shot_runner as runner
import runtime_program_tree as runtime
from programs.tests._hostpaths import require_repo


@pytest.fixture
def retained_project(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "_RTL_SESSION_OWNED", False)
    monkeypatch.setattr(runner, "_RTL_SESSION_PROJECT", None)
    monkeypatch.setattr(runner, "_RTL_SESSION_BINDING", None)
    monkeypatch.setattr(runner, "_PHASE1_ACTIVE_PROJECT_BINDING", None)
    monkeypatch.delenv(runtime.ENV_ROOT, raising=False)
    monkeypatch.delenv(runtime.ENV_MANIFEST, raising=False)
    project = tmp_path / "project"
    rtl = project / "phase2/stage1/rtl"
    (rtl / "sub").mkdir(parents=True)
    (rtl / "unit.v").write_text('`include "sub/defs.svh"\nmodule unit; endmodule\n')
    (rtl / "sub/defs.svh").write_text("`define WIDTH 4\n")
    docs = project / "phase1/input_doc"
    docs.mkdir(parents=True)
    (docs / "design.md").write_text("Preserve the approved four-bit interface.\n")

    source = tmp_path / "installed"
    programs = source / "programs"
    programs.mkdir(parents=True)
    backing = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "programs")
    (programs / "producer.py").write_bytes((backing / "rtl_provenance.py").read_bytes())
    metadata = source / ".claude-plugin/plugin.json"
    metadata.parent.mkdir()
    metadata.write_text(json.dumps({"name": "neutral", "version": "1.0.0"}))
    tree = runtime.retain(project, programs)
    monkeypatch.setattr(runner, "_RUNTIME_PROGRAM_TREE", tree)
    historical = project / ".vibeic/runtime-program-trees" / ("0" * 64)
    payload = historical / "plugin/programs/landing_merge_verdict.py"
    payload.parent.mkdir(parents=True)
    payload.write_bytes((backing / "landing_merge_verdict.py").read_bytes())
    return project, tree, payload


def _dispatch_with_stamp(monkeypatch, *, after_stamp=None):
    def generate(project, _kind, _force, _started, binding, **_kwargs):
        rtl = project / "phase2/stage1/rtl/unit.v"
        rtl.write_text(rtl.read_text() + "// current deterministic output\n")
        runner._phase1_stamp_held_session(binding, generator="neutral-generator")
        if after_stamp is not None:
            after_stamp(project)
        return runner.StepResult("rtl_gen", "PASS", 0.0, "controlled generator edge")

    monkeypatch.setattr(runner, "_step_rtl_gen_bound", generate)


def test_stamp_reuses_owned_stage_and_keeps_all_runtime_and_header_bytes(
        retained_project, monkeypatch):
    project, tree, payload = retained_project
    original = payload.read_bytes()
    current = (tree.programs_dir / "producer.py").read_bytes()
    copied = []
    real_copy = runner._phase1_copy_entry_fd

    def observe_copy(src_fd, src_name, *args):
        if src_name == payload.name:
            copied.append((Path(os.readlink(f"/proc/self/fd/{src_fd}")) / src_name).read_bytes())
        return real_copy(src_fd, src_name, *args)

    monkeypatch.setattr(runner, "_phase1_copy_entry_fd", observe_copy)
    _dispatch_with_stamp(monkeypatch)
    result = runner.step_rtl_gen(project, "controlled-neutral-generator")
    assert result.status == "PASS"
    assert len(copied) == 1
    assert copied[0] == payload.read_bytes() == original
    assert (tree.programs_dir / "producer.py").read_bytes() == current
    tree.verify_tree()
    ledger = runner._rtl_prov.load_ledger(project)
    assert ledger["generator"] == "neutral-generator"
    assert set(ledger["files"]) == {"unit.v", "sub/defs.svh"}
    assert ledger["files"]["sub/defs.svh"] == runner._rtl_prov.sha256_file(
        project / "phase2/stage1/rtl/sub/defs.svh")


@pytest.mark.parametrize("target", ["source", "header", "current_runtime", "historical_runtime"])
def test_private_stamp_does_not_bypass_live_project_cas(
        retained_project, monkeypatch, target):
    project, tree, payload = retained_project
    paths = {
        "source": project / "phase1/input_doc/design.md",
        "header": project / "phase2/stage1/rtl/sub/defs.svh",
        "current_runtime": tree.programs_dir / "producer.py",
        "historical_runtime": payload,
    }
    victim = paths[target]
    original_rtl = (project / "phase2/stage1/rtl/unit.v").read_bytes()

    def external_change(_private):
        victim.write_bytes(victim.read_bytes() + b"\n// external writer\n")

    _dispatch_with_stamp(monkeypatch, after_stamp=external_change)
    result = runner.step_rtl_gen(project, "controlled-neutral-generator")
    assert result.status == "NOT_MEASURED"
    assert result.extras["output_refusal"]["reason"] == "PROJECT_CHANGED_BEFORE_RTL_COMMIT"
    assert (project / "phase2/stage1/rtl/unit.v").read_bytes() == original_rtl
    assert victim.read_bytes().endswith(b"// external writer\n")
    assert not runner._rtl_prov.ledger_path(project).exists()


def test_standalone_stamp_still_uses_an_isolated_transaction(
        retained_project, monkeypatch):
    project, tree, payload = retained_project
    stages = []
    snapshot = runner._phase1_snapshot_to_stage

    def observe_snapshot(binding, stage):
        stages.append(stage)
        return snapshot(binding, stage)

    monkeypatch.setattr(runner, "_phase1_snapshot_to_stage", observe_snapshot)
    binding = runner._Phase1ProjectBinding.open(project)
    try:
        # A caller cannot request the fast path merely by naming a private flag.
        binding.isolated_rtl_stage = True
        runner._phase1_stamp_held_session(binding, generator="standalone-origin")
    finally:
        binding.close()
    assert len(stages) == 1
    assert runner._rtl_prov.load_ledger(project)["generator"] == "standalone-origin"
    assert payload.is_file()
    tree.verify_tree()


@pytest.mark.parametrize("when", ["before", "during"])
def test_private_stamp_refuses_escaping_links_without_touching_foreign_bytes(
        retained_project, monkeypatch, tmp_path, when):
    project, _tree, _payload = retained_project
    foreign = tmp_path / "foreign.svh"
    foreign.write_text("foreign source must remain unchanged\n")
    original = foreign.read_bytes()
    if when == "before":
        (project / "phase2/stage1/rtl/escaped.svh").symlink_to(foreign)
    else:
        stamp = runner._rtl_prov.stamp

        def introduce_link(private, generator=None):
            answer = stamp(private, generator=generator)
            (private / "phase2/stage1/rtl/escaped.svh").symlink_to(foreign)
            return answer

        monkeypatch.setattr(runner._rtl_prov, "stamp", introduce_link)
    _dispatch_with_stamp(monkeypatch)
    result = runner.step_rtl_gen(project, "controlled-neutral-generator")
    assert result.status == "NOT_MEASURED"
    assert result.extras["output_refusal"]["reason"] == "RTL_PROVENANCE_SYMLINK_REFUSED"
    assert foreign.read_bytes() == original
    assert not runner._rtl_prov.ledger_path(project).exists()
