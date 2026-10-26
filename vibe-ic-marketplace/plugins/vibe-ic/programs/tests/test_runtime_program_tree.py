import hashlib
import json
import os
import shutil
import subprocess
import sys
from types import ModuleType, SimpleNamespace
from pathlib import Path

import pytest

import runtime_program_tree as rpt


def _plugin(root: Path, version: str, child_text: str) -> Path:
    programs = root / "programs"
    programs.mkdir(parents=True)
    (programs / "runner.py").write_text("# runner\n")
    (programs / "first.py").write_text(
        "import time\ntime.sleep(0.2)\nprint('first-' + " + repr(version) + ")\n")
    (programs / "next.py").write_text(child_text)
    (programs / "final.py").write_text("print('final-' + " + repr(version) + ")\n")
    metadata = root / ".claude-plugin" / "plugin.json"
    metadata.parent.mkdir(parents=True)
    metadata.write_text(json.dumps({"name": "fixture", "version": version}))
    (root / "flow").mkdir()
    (root / "flow" / "flow.yaml").write_text("steps: []\n")
    # Runtime retention must not pay for or publish the test corpus.
    tests = programs / "tests"
    tests.mkdir()
    (tests / "large_fixture.bin").write_bytes(b"ignored")
    return programs


def _clear(monkeypatch):
    # Record the keys even when the parent process did not have them.  The
    # product code deliberately exports the retained tree for descendants;
    # pytest must restore that process state before an unrelated runner test.
    monkeypatch.setenv(rpt.ENV_ROOT, "")
    monkeypatch.setenv(rpt.ENV_MANIFEST, "")
    monkeypatch.delenv("PYTHONDONTWRITEBYTECODE", raising=False)
    monkeypatch.setattr(sys, "dont_write_bytecode", False)


def test_activation_keeps_python_cache_out_of_retained_source(
        tmp_path, monkeypatch):
    _clear(monkeypatch)
    programs = _plugin(tmp_path / "installed", "1.0.0", "print('A')\n")
    project = tmp_path / "project"
    project.mkdir()

    rpt.activate(project, programs, programs / "runner.py")

    assert sys.dont_write_bytecode is True
    assert os.environ["PYTHONDONTWRITEBYTECODE"] == "1"


def test_active_run_keeps_version_a_after_installed_tree_is_replaced(
        tmp_path, monkeypatch):
    _clear(monkeypatch)
    source = tmp_path / "installed-a"
    programs = _plugin(source, "1.0.0", "print('A')\n")
    project = tmp_path / "project"
    project.mkdir()

    tree = rpt.activate(project, programs, programs / "runner.py")
    first = tree.programs_dir / "first.py"
    retained_next = tree.programs_dir / "next.py"
    tree.verify_command([sys.executable, str(first)])
    active = subprocess.Popen([sys.executable, str(first)], stdout=subprocess.PIPE,
                              text=True)
    shutil.rmtree(source)
    replacement = tmp_path / "installed-b"
    _plugin(replacement, "2.0.0", "print('B')\n")

    tree.verify_command([sys.executable, str(retained_next)])
    next_run = subprocess.run([sys.executable, str(retained_next)],
                              capture_output=True, text=True, check=True)
    final = tree.programs_dir / "final.py"
    tree.verify_command([sys.executable, str(final)])
    final_run = subprocess.run([sys.executable, str(final)],
                               capture_output=True, text=True, check=True)
    assert active.communicate(timeout=2)[0].strip() == "first-1.0.0"
    assert next_run.stdout.strip() == "A"
    assert final_run.stdout.strip() == "final-1.0.0"
    launches = json.loads(tree.launch_path.read_text())
    assert launches["children"]["programs/next.py"]["sha256"] == hashlib.sha256(
        b"print('A')\n").hexdigest()
    receipt = json.loads((project / "reports/orchestrator/runtime_program_tree.json").read_text())
    assert receipt["plugin_version"] == "1.0.0"
    assert receipt["source_tree_sha256"] == tree.tree_sha256
    assert receipt["retained_programs_dir"] == str(tree.programs_dir)
    assert not (tree.programs_dir / "tests").exists()


@pytest.mark.parametrize("damage", ["remove", "mutate"])
def test_changed_retained_child_is_refused_before_launch(
        tmp_path, monkeypatch, damage):
    _clear(monkeypatch)
    source = tmp_path / "installed"
    programs = _plugin(source, "1.0.0", "print('A')\n")
    project = tmp_path / "project"
    project.mkdir()
    tree = rpt.activate(project, programs, programs / "runner.py")
    child = tree.programs_dir / "next.py"
    if damage == "remove":
        child.unlink()
        expected = "RUNTIME_CHILD_MISSING"
    else:
        child.write_text("print('changed')\n")
        expected = "RUNTIME_CHILD_CHANGED"
    with pytest.raises(rpt.RuntimeTreeError, match=expected):
        tree.verify_command([sys.executable, str(child)])


def test_descendant_reuses_a_but_new_run_after_upgrade_uses_b(
        tmp_path, monkeypatch):
    _clear(monkeypatch)
    project = tmp_path / "project"
    project.mkdir()
    a = _plugin(tmp_path / "installed-a", "1.0.0", "print('A')\n")
    tree_a = rpt.activate(project, a, a / "runner.py")

    b = _plugin(tmp_path / "installed-b", "2.0.0", "print('B')\n")
    inherited = rpt.activate(project, b, b / "runner.py")
    assert inherited.plugin_root == tree_a.plugin_root
    assert (inherited.programs_dir / "next.py").read_text() == "print('A')\n"

    _clear(monkeypatch)
    tree_b = rpt.activate(project, b, b / "runner.py")
    assert tree_b.plugin_root != tree_a.plugin_root
    assert tree_b.manifest["plugin_version"] == "2.0.0"
    assert (tree_b.programs_dir / "next.py").read_text() == "print('B')\n"


def test_live_installed_path_is_refused_after_retention(tmp_path, monkeypatch):
    _clear(monkeypatch)
    source = tmp_path / "installed"
    programs = _plugin(source, "1.0.0", "print('A')\n")
    project = tmp_path / "project"
    project.mkdir()
    tree = rpt.activate(project, programs, programs / "runner.py")
    with pytest.raises(rpt.RuntimeTreeError, match="LIVE_PLUGIN_PATH_AFTER_RETENTION"):
        tree.verify_command([sys.executable, str(programs / "next.py")])


@pytest.mark.parametrize("child_location", ["retained", "live"])
def test_backend_parameters_keep_active_retained_runner(
        tmp_path, monkeypatch, child_location):
    import execution_backend_producers as producers
    import librelane_contract as ll

    _clear(monkeypatch)
    programs = _plugin(tmp_path / "source", "1.0.0", "print('A')\n")
    (programs / "pad_ring_check.py").write_text("# verifier subject\n")
    project = tmp_path / "project"
    project.mkdir()
    tree = rpt.activate(project, programs, programs / "runner.py")
    pdk = SimpleNamespace(name="fixture")
    pdk_root = tmp_path / "pdk"
    pdk_root.mkdir()

    def runner_context(name, program_root):
        context = ModuleType(name)
        context.PROGRAMS_DIR = program_root
        context._RUNTIME_PROGRAM_TREE = tree if name == "__main__" else None
        context._producer_identity_now = lambda: tree.receipt()
        context._detect_pdk = lambda project, name: pdk
        context._host_staged_liberty = lambda pdk, staging: None
        context.set_invocation_provenance_sink = lambda project: None
        return context

    active = runner_context("__main__", tree.programs_dir)
    separate = runner_context("phase3_one_shot_runner", programs)
    monkeypatch.setitem(sys.modules, "__main__", active)
    monkeypatch.setitem(sys.modules, "phase3_one_shot_runner", separate)
    monkeypatch.setattr(ll, "pdk_root_resolution",
                        lambda *args, **kwargs: {"path": str(pdk_root)})
    selected, _, _, _ = producers._parameters(project, {
        "pdk_name": pdk.name, "image_id": "fixture-image",
        "pdk_root": str(pdk_root), "top": "fixture"})

    assert selected is active
    assert selected is not separate
    assert selected._RUNTIME_PROGRAM_TREE is tree
    assert selected.PROGRAMS_DIR == tree.programs_dir
    child = ((selected.PROGRAMS_DIR if child_location == "retained" else programs)
             / "pad_ring_check.py")
    command = [sys.executable, str(child), str(project)]
    if child_location == "live":
        with pytest.raises(rpt.RuntimeTreeError,
                           match="LIVE_PLUGIN_PATH_AFTER_RETENTION"):
            tree.verify_command(command)
    else:
        tree.verify_command(command)
        launch = json.loads(tree.launch_path.read_text())["children"]
        assert launch["programs/pad_ring_check.py"]["sha256"] == hashlib.sha256(
            child.read_bytes()).hexdigest()


def test_long_runner_entrypoints_activate_retention_before_work():
    programs = Path(__file__).resolve().parents[1]
    for name, later in (
            ("vibe_ic_one_shot_runner.py", "_runner_lock.acquire_or_reenter"),
            ("design_one_shot_runner.py", "_bootstrap_execution_policy"),
            ("phase3_one_shot_runner.py", "_runner_lock.acquire_or_reenter")):
        source = (programs / name).read_text()
        activation = source.rfind("_activate_runtime_program_tree(project)")
        assert activation > source.index("def main()")
        assert activation < source.find(later, activation)


def test_phase_dispatch_seams_verify_retained_children():
    programs = Path(__file__).resolve().parents[1]
    front = (programs / "vibe_ic_one_shot_runner.py").read_text()
    phase2 = (programs / "design_one_shot_runner.py").read_text()
    phase3 = (programs / "phase3_one_shot_runner.py").read_text()
    assert "_verify_runtime_command(command)\n        cp = subprocess.run(command" in front
    assert "_verify_runtime_command(cmd)\n    import _watchdog as _wd" in phase2
    assert "for name in (\"run\", \"run_best_effort\")" in phase3
    assert "_verify_runtime_command(command)\n        return subprocess.Popen" in phase3
