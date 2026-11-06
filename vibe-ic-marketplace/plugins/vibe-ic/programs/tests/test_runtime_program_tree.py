import hashlib
import json
import os
import shutil
import subprocess
import sys
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


def _historical_fixture(tmp_path):
    """A neutral pre-companion producer envelope; no launch is performed."""
    import benchmark_dispatch as dispatch

    programs = _plugin(tmp_path / "source", "1.0.0", "print('A')\n")
    (programs / "phase1_gate_contract_check.py").write_text("# earlier gate owner\n")
    (programs / "runtime_program_tree.py").write_text(
        'SCHEMA = "vibeic_runtime_program_tree/1"\n')
    source = programs.parent
    files = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in source.rglob("*") if p.is_file() and "tests" not in p.parts}
    project = tmp_path / "project"
    root = project / ".vibeic/runtime-program-trees" / rpt._tree_hash(files)
    for rel in files:
        destination = root / "plugin" / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / rel, destination)
    manifest = dict(schema=rpt.SCHEMA, files=files,
                    source_tree_sha256=root.name,
                    retained_plugin_root=str(root / "plugin"),
                    source_plugin_root=str(source), plugin_version="1.0.0")
    path = root / "manifest.json"
    path.write_text(json.dumps(manifest))
    argv = [sys.executable, str(programs / "runner.py")]
    receipt = dict(project=str(project), argv=argv, reports_before={},
                   reports_after={"phase2_one_shot.json": {
                       "valid": True, "sha256": "issued-generation",
                       "runner_binding": {"producer": {
                           "path": str(root / "plugin/programs/runner.py")}}}},
                   source_before=dispatch._runner_source_snapshot(
                       argv, consumer=str(programs / "final.py")))
    return path, receipt


def test_historical_source_reader_accepts_old_proof_but_not_new_launch(tmp_path, monkeypatch):
    import benchmark_dispatch as dispatch

    manifest, receipt = _historical_fixture(tmp_path)
    try:
        observed = {"historical_match": dispatch._historical_runner_sources_match(receipt)}
    except ValueError as exc:
        observed = {"historical_match": False, "reason": str(exc)}
    assert observed["historical_match"] is True, observed
    historical = rpt.load_historical(manifest)
    assert not isinstance(historical, rpt.RuntimeProgramTree)
    assert not hasattr(historical, "verify_child")
    with pytest.raises(rpt.RuntimeTreeError, match="RUNTIME_COMPANION_DECLARATION_INVALID"):
        rpt._load_retained(manifest)
    monkeypatch.setenv(rpt.ENV_ROOT, str(historical.plugin_root))
    monkeypatch.setenv(rpt.ENV_MANIFEST, str(manifest))
    for launch in (rpt.retain, lambda project, source:
                   rpt.activate(project, source, source / "runner.py")):
        with pytest.raises(rpt.RuntimeTreeError, match="RUNTIME_COMPANION_DECLARATION_INVALID"):
            launch(Path(receipt["project"]), tmp_path / "source/programs")


@pytest.mark.parametrize("damage", [
    "retained-source", "manifest-file-hash", "tree-identity", "source-root",
    "receipt-source", "receipt-argv", "escaping-file"])
def test_historical_source_reader_rejects_integrity_or_receipt_drift(tmp_path, damage):
    import benchmark_dispatch as dispatch

    path, receipt = _historical_fixture(tmp_path)
    manifest = json.loads(path.read_text())
    if damage == "retained-source":
        (path.parent / "plugin/programs/runner.py").write_text("# drift\n")
    elif damage == "manifest-file-hash":
        manifest["files"]["programs/runner.py"] = "0" * 64
    elif damage == "tree-identity":
        manifest["source_tree_sha256"] = "0" * 64
    elif damage == "source-root":
        manifest["source_plugin_root"] = str(tmp_path / "foreign")
    elif damage == "receipt-source":
        receipt["source_before"]["runner"]["sha256"] = "0" * 64
    elif damage == "receipt-argv":
        receipt["argv"].append("--different-options")
    else:
        manifest["files"]["../outside"] = "0" * 64
    path.write_text(json.dumps(manifest))

    try:
        accepted = dispatch._historical_runner_sources_match(receipt)
    except ValueError:
        accepted = False
    assert accepted is False


def test_retained_proof_refuses_a_foreign_consumer_with_unchanged_live_bytes(tmp_path):
    import benchmark_dispatch as dispatch

    _, receipt = _historical_fixture(tmp_path)
    live = tmp_path / "foreign/programs/live.py"
    live.parent.mkdir(parents=True)
    live.write_text("# unchanged live bytes outside the retained tree\n")
    receipt["source_before"] = dispatch._runner_source_snapshot(
        receipt["argv"], consumer=str(live))
    assert dispatch._historical_runner_sources_match(receipt) is False


def test_retained_proof_still_accepts_the_running_consumer_outside_its_tree(tmp_path):
    import benchmark_dispatch as dispatch

    _, receipt = _historical_fixture(tmp_path)
    receipt["source_before"] = dispatch._runner_source_snapshot(receipt["argv"])
    assert dispatch._historical_runner_sources_match(receipt) is True


def test_legacy_proof_without_a_retained_tree_keeps_live_source_check(tmp_path):
    import benchmark_dispatch as dispatch

    _, receipt = _historical_fixture(tmp_path)
    binding = receipt["reports_after"]["phase2_one_shot.json"]["runner_binding"]
    binding["producer"]["path"] = str(tmp_path / "source/programs/runner.py")
    assert dispatch._historical_runner_sources_match(receipt) is True
    runner = tmp_path / "source/programs/runner.py"
    runner.write_text(runner.read_text() + "# drift\n")
    assert dispatch._historical_runner_sources_match(receipt) is False


@pytest.mark.parametrize("damage,expected", [
    ("unmanifested-asset", "RUNTIME_SOURCE_UNMANIFESTED"),
    ("missing-asset", "RUNTIME_COMPANION_MISSING"),
    ("missing-api", "RUNTIME_COMPANION_DECLARATION_INVALID"),
    ("unknown-schema", "RUNTIME_SOURCE_MANIFEST_SCHEMA"),
])
def test_historical_same_schema_cannot_hide_a_current_companion_contract(
        tmp_path, monkeypatch, damage, expected):
    import phase1_gate_contract_check as contract

    _clear(monkeypatch)
    programs = _gate_plugin(tmp_path / "source")
    shutil.copy2(Path(rpt.__file__), programs / "runtime_program_tree.py")
    tree = rpt.retain(tmp_path / "project", programs)
    manifest = json.loads(tree.manifest_path.read_text())
    rel = contract.companion_assets()[0]
    if damage in {"unmanifested-asset", "missing-asset"}:
        del manifest["files"][rel]
        if damage == "missing-asset":
            (tree.plugin_root / rel).unlink()
    elif damage == "missing-api":
        rel = "programs/phase1_gate_contract_check.py"
        (tree.plugin_root / rel).write_text("# pretending to be a pre-companion owner\n")
        manifest["files"][rel] = hashlib.sha256((tree.plugin_root / rel).read_bytes()).hexdigest()
    else:
        manifest["schema"] = "vibeic_runtime_program_tree/0"
    # Re-address this synthetic adversary so a bad hash cannot mask the
    # companion-contract check. Real archived source is never changed.
    manifest["source_tree_sha256"] = rpt._tree_hash(manifest["files"])
    moved = tree.manifest_path.parent.with_name(manifest["source_tree_sha256"])
    if moved != tree.manifest_path.parent:
        shutil.move(tree.manifest_path.parent, moved)
    manifest["retained_plugin_root"] = str(moved / "plugin")
    path = moved / "manifest.json"
    path.write_text(json.dumps(manifest))

    with pytest.raises(rpt.RuntimeTreeError, match=expected):
        rpt.load_historical(path)


def _gate_plugin(root):
    """Stage the shipped gate contract and its declared product backing."""
    import phase1_gate_contract_check as contract

    programs = _plugin(root, "1.0.0", "print('A')\n")
    shipped = Path(contract.__file__).parent
    names = ["phase1_gate_contract_check", "_progress_run", "_watchdog",
             "_structural_absence", "_specrtl_common", *contract.DEFAULT_GATES]
    for name in names:
        shutil.copy2(shipped / f"{name}.py", programs / f"{name}.py")
    for gate in contract.DEFAULT_GATES:
        name = f"test_{gate}.py"
        shutil.copy2(shipped / "tests" / name, programs / "tests" / name)
    shutil.copy2(shipped.parent / "flow" / "phase1_phase2_phase3.yaml",
                 root / "flow" / "phase1_phase2_phase3.yaml")
    return programs


def _run_gate_contract(tree):
    child = tree.programs_dir / "phase1_gate_contract_check.py"
    tree.verify_command([sys.executable, str(child), "--json"])
    return subprocess.run([sys.executable, "-B", str(child), "--json"],
                          capture_output=True, text=True)


def test_retained_gate_contract_consumes_shipped_pytest_backing(
        tmp_path, monkeypatch):
    _clear(monkeypatch)
    programs = _gate_plugin(tmp_path / "installed")
    tree = rpt.retain(tmp_path / "project", programs)

    result = _run_gate_contract(tree)
    report = json.loads(result.stdout)
    assert report["total_errors"] == 0, report
    assert result.returncode == 0, result.stderr
    assert not (tree.programs_dir / "tests" / "large_fixture.bin").exists()
    import phase1_gate_contract_check as contract
    for rel in contract.companion_assets():
        data = (programs.parent / rel).read_bytes()
        assert (tree.plugin_root / rel).read_bytes() == data
        assert tree.manifest["files"][rel] == hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize("damage", ["remove", "mutate"])
def test_retained_companion_damage_is_refused_before_gate_launch(
        tmp_path, monkeypatch, damage):
    import phase1_gate_contract_check as contract

    _clear(monkeypatch)
    programs = _gate_plugin(tmp_path / "installed")
    tree = rpt.retain(tmp_path / "project", programs)
    asset = tree.plugin_root / contract.companion_assets()[0]
    if damage == "remove":
        asset.unlink()
        expected = "RUNTIME_COMPANION_MISSING"
    else:
        asset.write_text("# altered retained backing\n")
        expected = "RUNTIME_COMPANION_CHANGED"
    with pytest.raises(rpt.RuntimeTreeError, match=expected):
        _run_gate_contract(tree)
    assert not tree.launch_path.exists()
    with pytest.raises(rpt.RuntimeTreeError, match="RUNTIME_SOURCE_(MISSING|CHANGED)"):
        rpt.retain(tmp_path / "project", programs)


def test_companion_selection_uses_the_source_versions_gate_declaration(
        tmp_path, monkeypatch):
    import phase1_gate_contract_check as contract

    _clear(monkeypatch)
    programs = _gate_plugin(tmp_path / "installed")
    owner = programs / "phase1_gate_contract_check.py"
    owner.write_text(owner.read_text().replace(
        "DEFAULT_GATES = [", 'DEFAULT_GATES = ["neutral_gate",', 1))
    shutil.copy2(programs / f"{contract.DEFAULT_GATES[0]}.py",
                 programs / "neutral_gate.py")
    (programs / "tests" / "test_neutral_gate.py").write_text("# neutral backing\n")
    flow = programs.parent / "flow" / "phase1_phase2_phase3.yaml"
    flow.write_text(flow.read_text() + "\n# neutral_gate\n")

    tree = rpt.retain(tmp_path / "project", programs)

    assert "programs/tests/test_neutral_gate.py" in tree.manifest["files"]
    result = _run_gate_contract(tree)
    assert json.loads(result.stdout)["total_errors"] == 0, result.stdout
    assert result.returncode == 0, result.stderr


def test_companion_update_changes_bundle_identity_and_reuses_complete_bundle(
        tmp_path, monkeypatch):
    import phase1_gate_contract_check as contract

    _clear(monkeypatch)
    programs = _gate_plugin(tmp_path / "installed")
    program_sources = {p.name: p.read_bytes() for p in programs.glob("*.py")}
    first = rpt.retain(tmp_path / "project", programs)
    rel = contract.companion_assets()[0]
    original = (first.plugin_root / rel).read_bytes()
    (programs.parent / rel).write_bytes(original + b"\n# next asset version\n")
    _clear(monkeypatch)

    second = rpt.retain(tmp_path / "project", programs)
    _clear(monkeypatch)
    repeated = rpt.retain(tmp_path / "project", programs)

    assert {p.name: p.read_bytes() for p in programs.glob("*.py")} == program_sources
    assert first.tree_sha256 != second.tree_sha256
    assert first.plugin_root != second.plugin_root
    assert (first.plugin_root / rel).read_bytes() == original
    assert (second.plugin_root / rel).read_bytes() == (programs.parent / rel).read_bytes()
    assert repeated.plugin_root == second.plugin_root
    assert _run_gate_contract(repeated).returncode == 0


def test_incomplete_cached_bundle_is_refused_and_fresh_retention_is_complete(
        tmp_path, monkeypatch):
    import phase1_gate_contract_check as contract

    _clear(monkeypatch)
    programs = _gate_plugin(tmp_path / "installed")
    project = tmp_path / "project"
    tree = rpt.retain(project, programs)
    manifest = dict(tree.manifest)
    manifest["files"] = {rel: digest for rel, digest in manifest["files"].items()
                         if rel not in contract.companion_assets()}
    legacy_sha = rpt._tree_hash(manifest["files"])
    legacy = tree.manifest_path.parent.with_name(legacy_sha)
    shutil.move(tree.manifest_path.parent, legacy)
    manifest["source_tree_sha256"] = legacy_sha
    manifest["retained_plugin_root"] = str(legacy / "plugin")
    for rel in contract.companion_assets():
        (legacy / "plugin" / rel).unlink()
    legacy_manifest = legacy / "manifest.json"
    legacy_manifest.write_text(json.dumps(manifest))
    original_manifest = legacy_manifest.read_bytes()
    monkeypatch.setenv(rpt.ENV_ROOT, str(legacy / "plugin"))
    monkeypatch.setenv(rpt.ENV_MANIFEST, str(legacy_manifest))
    with pytest.raises(rpt.RuntimeTreeError, match="RUNTIME_COMPANION_MISSING"):
        rpt.retain(project, programs)
    _clear(monkeypatch)

    fresh = rpt.retain(project, programs)

    assert fresh.plugin_root != legacy / "plugin"
    assert legacy_manifest.read_bytes() == original_manifest
    assert _run_gate_contract(fresh).returncode == 0


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




_STEP23_SIGNOFF_PROGRAMS = (
    ("sta_signoff", "sta_report_check.py"),
    ("sta_corner", "post_route_signoff_corner_check.py"),
    ("sta_record", "sta_corner_record_completeness_check.py"),
    ("sta_architectural_residual", "sta_architectural_residual_check.py"),
    ("drv_signoff", "drv_signoff_judge.py"),
)








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
