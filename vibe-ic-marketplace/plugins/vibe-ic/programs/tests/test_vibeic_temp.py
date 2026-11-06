import json
import os
from pathlib import Path
import re
import subprocess
import sys
from types import SimpleNamespace

import pytest

import vibeic_temp as temp


@pytest.fixture
def root(tmp_path, monkeypatch):
    path = tmp_path / "temporary-root"
    monkeypatch.setenv("VIBEIC_TMP", str(path))
    temp.configure()
    return path


def test_default_is_in_the_users_home(tmp_path, monkeypatch):
    monkeypatch.delenv("VIBEIC_TMP", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert temp.root() == tmp_path / "vibe-ic-temp"
    assert Path(temp.gettempdir()).parent == tmp_path / "vibe-ic-temp/tmp"


def test_override_and_child_tool_use_one_root(root):
    assert temp.root() == root
    output = subprocess.check_output([sys.executable, "-c",
        "import json,os,tempfile;print(json.dumps([os.environ['TMPDIR'],tempfile.gettempdir()]))"], text=True)
    assert json.loads(output) == [str(temp.scratch())] * 2


def test_explicit_legacy_scratch_directory_is_relocated(root, tmp_path):
    old = tmp_path / "project-work"
    old.mkdir()
    work = Path(temp.mkdtemp(prefix="unit-", dir=old))
    assert work.is_relative_to(root / "tmp")
    assert not list(old.iterdir())
    with temp.TemporaryDirectory(dir=old) as directory:
        assert Path(directory).is_relative_to(root / "tmp")
    with temp.NamedTemporaryFile(mode="w+", dir=old) as file:
        assert Path(file.name).is_relative_to(root / "tmp")


def test_atomic_project_publication_remains_on_destination_filesystem(root, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    destination = project / "result.txt"
    with temp.atomic_file(mode="w", dir=project, delete=False) as staged:
        staged.write("native result\n")
    assert Path(staged.name).parent == project
    os.replace(staged.name, destination)
    assert destination.read_text() == "native result\n"


def test_run_names_are_unique_and_have_date_caller_and_purpose(root):
    first = temp.new_run("neutral", "tool")
    second = temp.new_run("neutral", "tool")
    assert first != second
    assert first.parent == root / "runs"
    assert re.fullmatch(r"\d{8}-\d{4}-neutral-tool-p[0-9]+-[A-Za-z0-9_]+", first.name)
    assert first.is_dir() and second.is_dir()


def test_listing_and_cleanup_touch_only_selected_run(root, tmp_path):
    chosen = temp.new_run("neutral", "chosen", owner_pid=999999999)
    kept = temp.new_run("neutral", "kept", owner_pid=999999999)
    (chosen / "result").write_bytes(b"tool")
    (kept / "result").write_bytes(b"keep")
    rows = {row["name"]: row for row in temp.list_runs()}
    assert rows["runs/" + chosen.name]["bytes"] == 4
    assert rows["runs/" + chosen.name]["date"]
    outside = tmp_path / "outside"
    outside.mkdir()
    link = root / "runs/linked"
    link.symlink_to(outside, target_is_directory=True)
    for name in ("../outside", str(outside), "linked"):
        with pytest.raises(ValueError):
            temp.delete_runs([name])
    temp.delete_runs([chosen.name])
    assert not chosen.exists()
    assert kept.is_dir() and outside.is_dir() and link.is_symlink()


def test_native_adapter_work_is_relocated_without_moving_project(root, tmp_path, monkeypatch):
    import flow_native_adapters as adapters
    project = tmp_path / "project"
    project.mkdir()
    directory = project / "steps/unit"
    calls = []
    def execute(project, work, tool, commands, **kwargs):
        calls.append((project, work))
        (work / "tool.log").write_text("native output\n")
        return commands.result()
    monkeypatch.setitem(sys.modules, "flow_native_analog", SimpleNamespace(execute=execute))
    adapters.execute(project, directory, {"adapter": "analog", "step": "analog_specifications"}, {})
    assert calls[0][0] == project
    assert calls[0][1].is_relative_to(root)
    assert not list(directory.iterdir())


def test_container_mount_resolves_root_symlink_and_preserves_guest_path(root, tmp_path, monkeypatch):
    backing = tmp_path / "disk"
    backing.mkdir()
    linked = tmp_path / "linked-root"
    linked.symlink_to(backing, target_is_directory=True)
    monkeypatch.setenv("VIBEIC_TMP", str(linked))
    flags = temp.docker_mounts()
    assert flags[:2] == ["-v", f"{backing}:{linked}"]
    assert f"TMPDIR={temp.scratch()}" in flags


@pytest.mark.parametrize("raises", [False, True])
def test_execution_cleans_scratch_and_run_on_success_and_exception(root, raises):
    def invoke():
        with temp.execution("neutral", "cleanup") as work:
            (work.tmp / "tool.tmp").write_text("scratch")
            (work.run / "tool.log").write_text("native result")
            paths.extend([work.tmp, work.run])
            if raises:
                raise RuntimeError("native failure")
    paths = []
    if raises:
        with pytest.raises(RuntimeError, match="native failure"):
            invoke()
    else:
        invoke()
    assert all(not path.exists() for path in paths)


def test_results_are_copied_before_run_is_removed(root, tmp_path):
    destination = tmp_path / "project/results"
    with temp.execution("neutral", "publish") as work:
        (work.run / "native.log").write_text("actual tool result\n")
        with temp.NamedTemporaryFile(mode="w", delete=False) as log:
            log.write("tool diagnostic\n")
        published = work.publish(destination)
        assert published == destination
        assert (destination / "native.log").read_text() == "actual tool result\n"
        copied_log = Path(work.mapping[log.name])
        assert copied_log.read_text() == "tool diagnostic\n"
    assert not work.tmp.exists()
    assert not work.run.exists()
    assert destination.is_dir()


def test_explicit_keep_preserves_run_but_always_cleans_scratch(root):
    with temp.execution("neutral", "keep", keep=True) as work:
        (work.run / "native.log").write_text("retained\n")
    assert work.run.is_dir()
    assert not work.tmp.exists()
    assert (work.run / "native.log").read_text() == "retained\n"


def test_run_cleanup_error_still_cleans_scratch_and_restores_environment(root, monkeypatch):
    previous = os.environ["TMPDIR"]
    remove = temp._remove
    def deny_run(path):
        if path == work.run:
            raise PermissionError("run cleanup failed")
        remove(path)
    with pytest.raises(PermissionError, match="run cleanup failed"):
        with temp.execution("neutral", "cleanup-error") as work:
            monkeypatch.setattr(temp, "_remove", deny_run)
    monkeypatch.setattr(temp, "_remove", remove)
    remove(work.run)
    assert not work.tmp.exists()
    assert os.environ["TMPDIR"] == previous


def test_process_exit_removes_owned_tmp(root):
    environment = dict(os.environ)
    environment.pop("VIBEIC_EXEC_TMP", None)
    environment.pop("VIBEIC_RUN_DIR", None)
    environment["PYTHONPATH"] = str(Path(temp.__file__).parent)
    output = subprocess.check_output([sys.executable, "-c",
        "import vibeic_temp;print(vibeic_temp.gettempdir())"], text=True, env=environment)
    assert not Path(output.strip()).exists()


def test_old_leftovers_cleanup_preserves_active_and_recent_runs(root):
    import time
    old = temp.new_run("neutral", "old", owner_pid=999999999)
    recent = temp.new_run("neutral", "recent", owner_pid=999999999)
    active = temp.new_run("neutral", "active")
    timestamp = time.time() - 90000
    os.utime(old, (timestamp, timestamp))
    os.utime(active, (timestamp, timestamp))
    removed = temp.delete_runs([], older_than_day=True)
    assert str(old) in removed
    assert not old.exists()
    assert recent.is_dir() and active.is_dir()


def test_public_runner_copies_native_reports_and_rewrites_paths_before_cleanup(root, tmp_path, monkeypatch):
    import flow_engine as engine
    project = tmp_path / "project"
    project.mkdir()
    temporary = []
    def command(current_project, directory, tool):
        work = temp.current_run()
        temporary.extend([work, temp.scratch()])
        report = work / "native.log"
        report.write_text("native tool output\n")
        return engine.ToolResult(True, 0, reports=[str(report)])
    monkeypatch.setattr(engine, "command_tool", command)
    row = {"name": "unit", "title": "Unit", "when": "always", "legacy_id": {},
           "tool": {"kind": "command", "argv": ["neutral"]}, "checks": []}
    route = {"entry_step": "unit", "verify_through": "unit", "delivery_target": "rtl", "input_contract": "structured"}
    result = engine.run(project, table={"steps": [row]}, route=route)
    report = Path(result["steps"][0]["reports"][0])
    assert report.is_relative_to(project / "reports/native")
    assert report.read_text() == "native tool output\n"
    saved = json.loads((project / "steps/unit/result.json").read_text())
    assert saved["reports"] == [str(report)]
    assert all(not path.exists() for path in temporary)


@pytest.mark.parametrize("fails", [False, True])
def test_mcp_bridge_owns_and_cleans_its_execution_on_exit(root, fails):
    if not __import__("shutil").which("node"):
        pytest.skip("node is unavailable")
    module = Path(temp.__file__).parents[1] / "mcp-eda/src/temp_paths.mjs"
    code = "const m=await import(process.argv[1]); console.log(JSON.stringify(m.configureTemp()));"
    if fails:
        code += "throw Error('neutral failure');"
    result = subprocess.run(["node", "--input-type=module", "-e", code, module.as_uri()],
                            text=True, capture_output=True)
    record = json.loads(result.stdout)
    assert result.returncode == (1 if fails else 0)
    assert not Path(record["TMPDIR"]).exists()
    assert not Path(record["VIBEIC_RUN_DIR"]).exists()


@pytest.mark.parametrize("code", [0, 7])
def test_standalone_command_inherits_managed_tmp_and_cleans_it(root, code):
    source = "import os,tempfile;print(tempfile.gettempdir());raise SystemExit(" + str(code) + ")"
    completed = subprocess.run([sys.executable, temp.__file__, "exec", "--", sys.executable, "-c", source],
                               capture_output=True, text=True)
    assert completed.returncode == code
    path = Path(completed.stdout.strip())
    assert path.parent == root / "tmp"
    assert not path.exists()


def test_publication_preserves_resolved_paths_with_a_linked_root(tmp_path, monkeypatch):
    actual = tmp_path / "storage"
    actual.mkdir()
    linked = tmp_path / "temporary-root"
    linked.symlink_to(actual, target_is_directory=True)
    monkeypatch.setenv("VIBEIC_TMP", str(linked))
    destination = tmp_path / "project/native"
    with temp.execution("neutral", "linked") as work:
        data = work.run.resolve() / "native.log"
        data.write_text("native result\n")
        (work.run / "result.json").write_text(json.dumps({"report": str(data)}))
        (work.run / "result.json").chmod(0o444)
        with temp.NamedTemporaryFile(mode="w", delete=False) as file:
            file.write("native scratch result\n")
        scratch_file = Path(file.name).resolve()
        (work.run / "scratch.json").write_text(json.dumps({"report": str(scratch_file)}))
        work.publish(destination)
    assert not work.run.exists() and not work.tmp.exists()
    for name in ('result.json', 'scratch.json'):
        path = Path(json.loads((destination / name).read_text())["report"])
        assert path.is_file() and path.is_relative_to(destination)


def test_cleanup_removes_read_only_owned_tool_folders(root):
    with temp.execution("neutral", "read-only") as work:
        folder = work.tmp / "tool"
        folder.mkdir()
        (folder / "native.log").write_text("native result\n")
        folder.chmod(0o555)
    assert not work.tmp.exists()


def test_watchdog_job_stamp_uses_the_execution_scratch(root):
    import _docker_watchdog as watchdog
    assert Path(watchdog.new_job_pidfile()).parent == temp.scratch()


def test_copy_failure_preserves_uncopied_results_and_cleans_scratch(root, tmp_path, monkeypatch):
    def fail_copy(*args, **kwargs):
        raise OSError("destination unavailable")
    monkeypatch.setattr(temp.shutil, "copytree", fail_copy)
    with pytest.raises(OSError, match="destination unavailable"):
        with temp.execution("neutral", "copy-error", destination=tmp_path / "project/results") as work:
            (work.run / "native.log").write_text("uncopied result\n")
    assert not work.tmp.exists()
    assert (work.run / "native.log").read_text() == "uncopied result\n"
    temp._remove(work.run)


def test_analog_window_copies_native_reports_before_cleanup(root, tmp_path, monkeypatch):
    import analog_native_flow as analog
    project = tmp_path / "project"
    paths = []
    def native(*args, **kwargs):
        run = temp.current_run()
        paths.extend([run, temp.scratch()])
        report = run / "native.log"
        report.write_text("native output\n")
        return {"outputs": [str(report)]}
    monkeypatch.setattr(analog, "_run_window", native)
    result = analog.run_window(project, SimpleNamespace())
    report = Path(result["outputs"][0])
    assert report.is_relative_to(project / "reports/analog_native")
    assert report.read_text() == "native output\n"
    assert all(not path.exists() for path in paths)


@pytest.mark.parametrize("cache_name", ["work/flow/chip/sizing.json", "generated/cache.json", "cache.json"])
def test_later_step_reads_retained_project_reference_after_cleanup(root, tmp_path, monkeypatch, cache_name):
    import flow_engine as engine
    project = tmp_path / "project"
    cache = project / cache_name
    paths = []
    def command(current_project, directory, tool):
        if tool["argv"] == ["produce"]:
            run = temp.current_run()
            paths.extend([run, temp.scratch()])
            state = run / "core_inputs/native/state_out.json"
            state.parent.mkdir(parents=True)
            state.write_text(json.dumps({"native": "retained"}))
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({"state_out": str(state)}))
            source = project / "input/source.json"
            source.parent.mkdir()
            source.write_text(cache.read_text())
            return engine.ToolResult(True, 0)
        state = Path(json.loads(cache.read_text())["state_out"])
        assert state.is_relative_to(project / "reports/native")
        assert json.loads(state.read_text()) == {"native": "retained"}
        return engine.ToolResult(True, 0, metrics={"retained_state_read": 1})
    monkeypatch.setattr(engine, "command_tool", command)
    def run(name):
        row = {"name": name, "title": name, "when": "always", "legacy_id": {},
               "tool": {"kind": "command", "argv": [name]}, "checks": []}
        route = {"entry_step": name, "verify_through": name, "delivery_target": "rtl", "input_contract": "structured"}
        return engine.run(project, table={"steps": [row]}, route=route)
    run("produce")
    assert all(not path.exists() for path in paths)
    source = json.loads((project / "input/source.json").read_text())
    assert source["state_out"].startswith(str(paths[0]))
    result = run("consume")
    assert result["steps"][0]["metrics"]["retained_state_read"] == 1
