#!/usr/bin/env python3
"""Regression for a retained-child receipt invalidating its own RTL commit."""
import hashlib
import json
from pathlib import Path
import sys

import pytest


HERE = Path(__file__).resolve().parent
PROGRAMS = HERE.parent
sys.path.insert(0, str(PROGRAMS))

import design_one_shot_runner as runner  # noqa: E402
import rtl_provenance  # noqa: E402
import runtime_program_tree as rpt  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_runner_session(monkeypatch):
    monkeypatch.setattr(runner, "_RTL_SESSION_OWNED", False)
    monkeypatch.setattr(runner, "_RTL_SESSION_PROJECT", None)
    monkeypatch.setattr(runner, "_RTL_SESSION_BINDING", None)
    monkeypatch.setattr(runner, "_RUNTIME_PROGRAM_TREE", None)


def _project(root: Path) -> Path:
    docs = root / "phase1" / "generated_docs"
    docs.mkdir(parents=True)
    (docs / "L2_FRS.json").write_text(json.dumps({
        "ic_name": "neutral_serial",
        "frs_sections": [{
            "content": (
                "serial-parallel multiplier: p = (x * y) mod 2^N; "
                "synchronous active-high reset")
        }],
    }) + "\n")
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "neutral_serial",
        "top_ports": [
            {"name": "clk", "direction": "input", "width": 1},
            {"name": "rst", "direction": "input", "width": 1},
            {"name": "x", "direction": "input", "width": "size-1:0",
             "width_symbolic": "size-1:0", "msb": "size-1", "lsb": "0"},
            {"name": "y", "direction": "input", "width": 1},
            {"name": "p", "direction": "output", "width": 1},
        ],
    }) + "\n")
    return root


def _bind_child_receipt(project: Path) -> tuple[rpt.RuntimeProgramTree, str, str]:
    plugin_root = PROGRAMS.parent
    # The ordinary arithmetic producer calls this declaration consumer before
    # returning its generated RTL.  Binding that real child is enough to
    # reproduce the transaction/receipt collision without copying the whole
    # plugin into every unit-test project.
    child = PROGRAMS / "spec_declaration_emit.py"
    rel = str(child.relative_to(plugin_root))
    digest = hashlib.sha256(child.read_bytes()).hexdigest()
    files = {rel: digest}
    tree_sha = rpt._tree_hash(files)
    retained = project / ".vibeic" / "runtime-program-trees" / tree_sha
    tree = rpt.RuntimeProgramTree(
        plugin_root=plugin_root,
        programs_dir=PROGRAMS,
        manifest_path=retained / "manifest.json",
        launch_path=retained / "launches.json",
        source_root=plugin_root,
        manifest={
            "schema": rpt.SCHEMA,
            "plugin_version": "test",
            "source_tree_sha256": tree_sha,
            "files": files,
        },
    )
    retained.mkdir(parents=True)
    tree.manifest_path.write_text(json.dumps(tree.manifest) + "\n")
    runner._RUNTIME_PROGRAM_TREE = tree
    return tree, rel, digest


def test_retained_child_receipt_does_not_refuse_its_own_rtl_commit(tmp_path):
    project = _project(tmp_path / "project")
    tree, rel, digest = _bind_child_receipt(project)

    result = runner.step_rtl_gen(project, "digital_arithmetic_primitive")

    assert result.status == "PASS", result.detail
    rtl = project / "phase2" / "stage1" / "rtl" / "neutral_serial.v"
    assert rtl.is_file() and rtl.stat().st_size > 0
    assert rtl_provenance.classify(project)[0] == rtl_provenance.GENERATED
    launches = json.loads(tree.launch_path.read_text())
    row = launches["children"][rel]
    assert row["sha256"] == digest
    assert row["launch_count"] == 1


def test_external_project_mutation_still_refuses_rtl_commit(tmp_path, monkeypatch):
    project = _project(tmp_path / "project")
    tree, rel, digest = _bind_child_receipt(project)
    real_verify = runner._verify_runtime_command
    injected = False

    def _verify_then_mutate(command):
        nonlocal injected
        real_verify(command)
        if not injected:
            injected = True
            (project / "external-mutation.txt").write_text("foreign write\n")

    monkeypatch.setattr(runner, "_verify_runtime_command", _verify_then_mutate)

    result = runner.step_rtl_gen(project, "digital_arithmetic_primitive")

    assert injected
    assert result.status == "NOT_MEASURED"
    assert result.extras["output_refusal"]["reason"] == (
        "PROJECT_CHANGED_BEFORE_RTL_COMMIT")
    assert not (project / "phase2" / "stage1" / "rtl").exists()
    launches = json.loads(tree.launch_path.read_text())
    assert launches["children"][rel]["sha256"] == digest
