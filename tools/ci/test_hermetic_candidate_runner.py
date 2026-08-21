from __future__ import annotations

import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
RUNNER_PATH = HERE / "hermetic_candidate_runner.py"
SPEC = importlib.util.spec_from_file_location("hermetic_candidate_runner", RUNNER_PATH)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


FAKE_DOCKER = r'''#!/usr/bin/env python3
import json
import os
import shutil
import sys
import time
from pathlib import Path

IMAGE = "ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2e05781758f596d82bff61ad8a404ef0a7eae3d21ab8a9d55df0d01ff"
IMAGE_ID = "sha256:" + "1" * 64
CID = "2" * 64
PREFIX = "VIBEIC_PROGRESS "
root = Path(os.environ["FAKE_DOCKER_STATE"])
root.mkdir(parents=True, exist_ok=True)
args = sys.argv[1:]
with (root / "calls.jsonl").open("a", encoding="utf-8") as log:
    log.write(json.dumps(args, sort_keys=True) + "\n")

def fail(message, rc=1):
    print(message, file=sys.stderr)
    raise SystemExit(rc)

def container_path(name):
    if "-export-" in name:
        return root / "exporter.json"
    if "-provision-" in name:
        return root / "provisioner.json"
    return root / "container.json"

def load_container(name):
    path = container_path(name)
    if not path.exists():
        fail("Error: No such container: " + name)
    return json.loads(path.read_text(encoding="utf-8"))

def save_container(doc):
    container_path(doc["Name"].lstrip("/")).write_text(
        json.dumps(doc), encoding="utf-8")

if args[:2] == ["image", "inspect"]:
    print(json.dumps([{"Architecture": "amd64", "Id": IMAGE_ID,
                       "Os": "linux", "RepoDigests": [IMAGE]}]))
elif args[:2] == ["volume", "create"]:
    name = args[-1]
    label = args[args.index("--label") + 1].split("=", 1)[1]
    opts = {}
    for index, arg in enumerate(args):
        if arg == "--opt":
            key, value = args[index + 1].split("=", 1)
            opts[key] = value
    (root / "volume.json").write_text(json.dumps({
        "Driver": "local", "Labels": {"ai.vibeic.hermetic-run": label},
        "Mountpoint": "/var/lib/docker/volumes/" + name,
        "Name": name, "Options": opts, "Scope": "local",
    }), encoding="utf-8")
    print(name)
elif args[:2] == ["volume", "inspect"]:
    path = root / "volume.json"
    if not path.exists():
        fail("Error: No such volume: " + args[-1])
    print("[" + path.read_text(encoding="utf-8") + "]")
elif args[:2] == ["volume", "rm"]:
    path = root / "volume.json"
    if not path.exists():
        fail("Error: No such volume: " + args[-1])
    name = json.loads(path.read_text(encoding="utf-8"))["Name"]
    path.unlink()
    print(name)
elif args[:2] == ["container", "create"]:
    value_flags = {
        "--name", "--label", "--user", "--network", "--cap-drop",
        "--security-opt", "--restart", "--tmpfs", "--workdir", "--env",
        "--mount", "--entrypoint", "--platform",
    }
    boolean_flags = {"--pull=never", "--read-only"}
    values = {}
    repeated = {"--env": [], "--mount": []}
    i = 2
    while i < len(args) and args[i] != IMAGE:
        flag = args[i]
        if flag in boolean_flags:
            values[flag] = True
            i += 1
        elif flag in value_flags:
            value = args[i + 1]
            if flag in repeated:
                repeated[flag].append(value)
            else:
                values[flag] = value
            i += 2
        else:
            fail("unknown create option " + flag)
    if i >= len(args):
        fail("image missing")
    command = args[i + 1:]
    env = ["PATH=/usr/bin", *repeated["--env"]]
    mounts = []
    for raw in repeated["--mount"]:
        fields = {}
        flags = set()
        for part in raw.split(","):
            if "=" in part:
                key, value = part.split("=", 1)
                fields[key] = value
            else:
                flags.add(part)
        kind = fields["type"]
        destination = fields["dst"]
        if kind == "bind":
            mounts.append({
                "Destination": destination,
                "Mode": "ro" if "readonly" in flags else "rw",
                "Propagation": "rprivate", "RW": "readonly" not in flags,
                "Source": fields["src"], "Type": "bind",
            })
        else:
            mounts.append({
                "Destination": destination, "Driver": "local", "Mode": "z",
                "Name": fields["src"], "Propagation": "", "RW": True,
                "Source": "/var/lib/docker/volumes/" + fields["src"], "Type": "volume",
            })
            mounts[-1]["RW"] = "readonly" not in flags
    behavior = os.environ.get("FAKE_DOCKER_BEHAVIOR", "good")
    if behavior == "rw_bind":
        # A bind at the RIGHT destination that is READ-WRITE. `extra_mount`
        # adds a NEW destination and is caught by the unowned-bind branch;
        # this is the other shape, and it is the one that would let a candidate
        # arm write back into a host path the parent later trusts. Applied only
        # to the subject bind, so the provisioner passes and the refusal has to
        # come from the candidate profile itself.
        for item in mounts:
            if item["Destination"] == values["--workdir"]:
                item["Mode"] = "rw"
                item["RW"] = True
    if behavior == "extra_mount":
        mounts.append({
            "Destination": "/host", "Mode": "ro", "Propagation": "rprivate",
            "RW": False, "Source": "/", "Type": "bind",
        })
    user = values["--user"] if behavior != "wrong_user" else "0:0"
    doc = {
        "Config": {
            "AttachStdin": False, "Cmd": command, "Entrypoint": [values["--entrypoint"]],
            "Env": env, "Image": IMAGE,
            "Labels": {"ai.vibeic.hermetic-run": values["--label"].split("=", 1)[1]},
            "OpenStdin": False, "Tty": False, "User": user,
            "WorkingDir": values["--workdir"],
        },
        "HostConfig": {
            "AutoRemove": False, "Binds": None, "CapAdd": None,
            "CapDrop": [values["--cap-drop"]], "Devices": [],
            "NetworkMode": values["--network"], "Privileged": False,
            "PublishAllPorts": False, "ReadonlyRootfs": True,
            "RestartPolicy": {"MaximumRetryCount": 0, "Name": "no"},
            "SecurityOpt": ["no-new-privileges:true"],
            "Tmpfs": {"/tmp": values["--tmpfs"].split(":", 1)[1]},
        },
        "Id": CID, "Image": IMAGE_ID, "Mounts": mounts,
        "Name": "/" + values["--name"],
        "State": {
            "Dead": False, "Error": "", "ExitCode": 0, "OOMKilled": False,
            "Paused": False, "Pid": 0, "Restarting": False,
            "Running": False, "Status": "created",
        },
    }
    save_container(doc)
    (root / "evidence").mkdir(exist_ok=True)
    print(CID)
elif args[:2] == ["container", "inspect"]:
    print(json.dumps([load_container(args[-1])]))
elif args[:2] == ["container", "start"]:
    name = args[-1]
    doc = load_container(name)
    doc["State"].update({"Pid": 4242, "Running": True, "Status": "running"})
    save_container(doc)
    if "-export-" in name:
        source = root / "evidence"
        export_mount = next(item for item in doc["Mounts"]
                            if item["Destination"] == "/export")
        destination = Path(export_mount["Source"])
        for item in source.iterdir():
            target = destination / item.name
            if item.is_dir():
                shutil.copytree(item, target)
            else:
                shutil.copyfile(item, target)
        doc = load_container(name)
        doc["State"].update({
            "Dead": False, "Error": "", "ExitCode": 0, "OOMKilled": False,
            "Paused": False, "Pid": 0, "Restarting": False,
            "Running": False, "Status": "exited",
        })
        save_container(doc)
        raise SystemExit(0)
    if "-provision-" in name:
        (root / "evidence" / ".vibeic-volume-ready").touch()
        doc = load_container(name)
        doc["State"].update({
            "Dead": False, "Error": "", "ExitCode": 0, "OOMKilled": False,
            "Paused": False, "Pid": 0, "Restarting": False,
            "Running": False, "Status": "exited",
        })
        save_container(doc)
        raise SystemExit(0)
    cmd = doc["Config"]["Cmd"]
    command_index = next(index for index, item in enumerate(cmd[2:], 2)
                         if "=" not in item)
    env = dict(item.split("=", 1) for item in cmd[2:command_index])
    plan_mount = next(item for item in doc["Mounts"]
                      if item["Destination"] == "/input/progress-plan.json")
    plan = json.loads(Path(plan_mount["Source"]).read_text(encoding="utf-8"))
    common = {
        "nonce": env["VIBEIC_HERMETIC_PROGRESS_NONCE"], "schema": 1,
        "scope": plan["scope"], "total": len(plan["units"]),
    }
    behavior = os.environ.get("FAKE_DOCKER_BEHAVIOR", "good")
    def emit(row):
        print(PREFIX + json.dumps(row, sort_keys=True, separators=(",", ":")), flush=True)
    emit({**common, "seq": 0, "state": "start"})
    if behavior == "malformed":
        print(PREFIX + "{", flush=True)
        rc = 0
    elif behavior == "duplicate":
        print(PREFIX + '{"nonce":"x","nonce":"x"}', flush=True)
        rc = 0
    elif behavior == "nan":
        print(PREFIX + '{"completed":NaN}', flush=True)
        rc = 0
    elif behavior == "stall":
        while True:
            current = load_container(name)
            if current.get("Killed"):
                raise SystemExit(137)
            time.sleep(0.02)
    else:
        for index, unit in enumerate(plan["units"], 1):
            emit({**common, "completed": index, "seq": index,
                  "state": "checkpoint", "unit": unit})
        emit({**common, "completed": len(plan["units"]),
              "seq": len(plan["units"]) + 1, "state": "terminal"})
        (root / "evidence" / "result.txt").write_text("candidate evidence\n",
                                                       encoding="utf-8")
        rc = 7 if behavior == "exit7" else 0
    doc = load_container(name)
    doc["State"].update({
        "Dead": False, "Error": "", "ExitCode": rc,
        "OOMKilled": behavior == "oom", "Paused": False, "Pid": 0,
        "Restarting": behavior == "restarting", "Running": False,
        "Status": "exited",
    })
    save_container(doc)
    raise SystemExit(rc)
elif args[:2] == ["container", "cp"]:
    source = root / "evidence"
    destination = Path(args[-1])
    for item in source.iterdir():
        target = destination / item.name
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)
elif args[:2] == ["container", "kill"]:
    doc = load_container(args[-1])
    doc["Killed"] = True
    doc["State"].update({
        "ExitCode": 137, "Pid": 0, "Restarting": False,
        "Running": False, "Status": "exited",
    })
    save_container(doc)
    print(doc["Name"].lstrip("/"))
elif args[:2] == ["container", "rm"]:
    name = args[-1]
    path = container_path(name)
    if not path.exists():
        fail("Error: No such container: candidate")
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc["State"]["Running"] and "--force" not in args:
        fail("container is running")
    path.unlink()
    print(doc["Name"].lstrip("/"))
else:
    fail("unsupported fake Docker command: " + repr(args))
    '''


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True,
                      separators=(",", ":"))


@pytest.fixture
def case(tmp_path: Path):
    subject = tmp_path / "subject"
    runtime = tmp_path / "runtime"
    corpus = tmp_path / "corpus"
    subject.mkdir()
    runtime.mkdir()
    corpus.mkdir()
    (subject / "candidate.py").write_text("print('candidate')\n", encoding="utf-8")
    (runtime / "candidate.py").write_text("#!/usr/bin/python3\n", encoding="utf-8")
    (runtime / "candidate.py").chmod(0o755)
    (corpus / "one.def").write_text("VERSION 5.8 ;\n", encoding="utf-8")
    selection = tmp_path / "selection.json"
    selection.write_text('{"schema":1}\n', encoding="utf-8")
    plan = tmp_path / "progress.json"
    plan.write_text(canonical({
        "schema": 1,
        "scope": "candidate-arm",
        "stall_grace_seconds": 1,
        "units": ["load", "check"],
    }) + "\n", encoding="utf-8")
    docker = tmp_path / "docker"
    docker.write_text(FAKE_DOCKER, encoding="utf-8")
    docker.chmod(0o755)
    state = tmp_path / "docker-state"
    output = tmp_path / "output"
    receipt = tmp_path / "receipt.json"
    return {
        "subject": subject, "runtime": runtime, "corpus": corpus,
        "selection": selection,
        "plan": plan, "docker": docker, "state": state, "output": output,
        "receipt": receipt,
    }


def invoke(case, *, behavior="good", command=None):
    env = dict(os.environ)
    env["FAKE_DOCKER_STATE"] = str(case["state"])
    env["FAKE_DOCKER_BEHAVIOR"] = behavior
    cmd = [
        sys.executable, str(RUNNER_PATH), "run",
        "--docker-bin", str(case["docker"]),
        "--subject", str(case["subject"]),
        "--runtime", str(case["runtime"]),
        "--overlay", "candidate.py",
        "--env", "GATEKEEPER_BENCHMARK_DATA_SHA=" + "b" * 40,
        "--env", "GATEKEEPER_VERIFY_ARM=A1",
        "--env", "VIBEIC_PYTEST_PROGRESS_FILE=/evidence/pytest-progress.jsonl",
        "--env", "VIBEIC_PYTEST_PROGRESS_NONCE=" + "d" * 64,
        "--corpus", str(case["corpus"]),
        "--selection", str(case["selection"]),
        "--progress-plan", str(case["plan"]),
        "--output-dir", str(case["output"]),
        "--receipt", str(case["receipt"]),
        "--", *(command or ["/subject/candidate.py"]),
    ]
    return subprocess.run(cmd, env=env, text=True, capture_output=True)


def calls(case):
    return [json.loads(line) for line in
            (case["state"] / "calls.jsonl").read_text(encoding="utf-8").splitlines()]


def test_fake_docker_exact_profile_lifecycle_and_canonical_receipt(case):
    proc = invoke(case)
    assert proc.returncode == 0, proc.stderr
    assert (case["output"] / "result.txt").read_text() == "candidate evidence\n"
    assert (case["output"] / "runner-stdout.bin").is_file()
    assert (case["output"] / "runner-stderr.bin").is_file()
    receipt = runner.strict_load_receipt(case["receipt"])
    assert receipt["image"]["reference"] == runner.IMAGE
    assert receipt["image"]["platform"] == "linux/amd64"
    assert receipt["container"]["user"] == "65534:65534"
    assert receipt["container"]["network"] == "none"
    assert receipt["container"]["read_only_rootfs"] is True
    assert receipt["container"]["cap_drop"] == ["ALL"]
    assert receipt["container"]["no_new_privileges"] is True
    assert receipt["container"]["launcher"] == ["/usr/bin/env", "-i", "--"]
    process_env = dict(item.split("=", 1)
                       for item in receipt["container"]["process_environment"])
    assert process_env["GATEKEEPER_RUNTIME_ROOT"] == "/runtime"
    assert process_env["VIBEIC_REQUIRE_TRUSTED_PYTEST_ENTRY"] == "1"
    assert process_env["GATEKEEPER_VERIFY_ARM"] == "A1"
    assert process_env["GATEKEEPER_BENCHMARK_DATA_SHA"] == "b" * 40
    assert process_env["VIBE_IC_BENCHMARK_DATA"] == "/corpus"
    assert process_env["VIBEIC_PYTEST_PROGRESS_FILE"] == \
        "/evidence/pytest-progress.jsonl"
    assert process_env["VIBEIC_PYTEST_PROGRESS_NONCE"] == "d" * 64
    assert "STARTUPDIR" not in process_env
    assert "PYTHONPATH" not in process_env
    assert "GATEKEEPER_HYGIENE_REPORT" not in process_env
    assert receipt["result"] == {
        "attach_exit_code": 0, "dead": False, "exit_code": 0,
        "oom_killed": False, "pid": 0, "pid_dead": True,
        "restarting": False, "running": False, "status": "exited",
    }
    assert receipt["cleanup"] == {
        "container_absent": True, "exporter_absent": True,
        "provisioner_absent": True,
        "volume_absent": True,
    }
    assert receipt["progress"]["completed"] == 2
    assert receipt["inputs"]["overlays"] == [{
        "destination": "/subject/candidate.py",
        "path": "candidate.py",
        "source_file": receipt["inputs"]["overlays"][0]["source_file"],
    }]
    overlay_mount = next(
        row for row in receipt["container"]["mounts"]
        if row["role"] == "runtime_overlay:candidate.py")
    assert overlay_mount["destination"] == "/subject/candidate.py"
    assert overlay_mount["read_only"] is True
    artifacts = {row["path"]: row for row in receipt["artifacts"]["files"]}
    assert artifacts["result.txt"] == {
        "mode": "100644", "path": "result.txt",
        "sha256": "bb3f2f5d2e170589f3cf7241d41e4b8ba07ce70ad92dd1f3f5795e0e87262f1f",
        "size": 19,
    }
    assert artifacts["runner-stdout.bin"] == {
        "mode": "100644", "path": "runner-stdout.bin",
        **receipt["streams"]["stdout"],
    }
    assert artifacts["runner-stderr.bin"] == {
        "mode": "100644", "path": "runner-stderr.bin",
        **receipt["streams"]["stderr"],
    }
    raw = case["receipt"].read_bytes()
    assert raw == runner._canonical(receipt) + b"\n"

    history = calls(case)
    def candidate_call(row):
        return (any(value.startswith("vibeic-candidate-") for value in row)
                and not any("-export-" in value or "-provision-" in value
                            for value in row))

    create = next(row for row in history
                  if row[:2] == ["container", "create"] and candidate_call(row))
    for flag in ("--pull=never", "--read-only", "--cap-drop", "--security-opt",
                 "--network", "--user", "--tmpfs"):
        assert flag in create
    start_index = next(i for i, row in enumerate(history)
                       if row[:2] == ["container", "start"] and candidate_call(row))
    stopped_inspect_index = next(i for i, row in enumerate(history[start_index + 1:],
                                                        start_index + 1)
                                 if row[:2] == ["container", "inspect"])
    exporter_create_index = next(
        i for i, row in enumerate(history)
        if row[:2] == ["container", "create"] and
        any("vibeic-candidate-export-" in value for value in row))
    exporter_start_index = next(
        i for i, row in enumerate(history)
        if row[:2] == ["container", "start"] and
        any("vibeic-candidate-export-" in value for value in row))
    rm_index = next(i for i, row in enumerate(history)
                    if row[:2] == ["container", "rm"] and
                    any("vibeic-candidate-export-" in value for value in row))
    absent_index = next(i for i, row in enumerate(history[rm_index + 1:], rm_index + 1)
                        if row[:2] == ["container", "inspect"])
    assert (start_index < stopped_inspect_index < exporter_create_index
            < exporter_start_index < rm_index < absent_index)
    assert not (case["state"] / "container.json").exists()
    assert not (case["state"] / "exporter.json").exists()
    assert not (case["state"] / "provisioner.json").exists()
    assert not (case["state"] / "volume.json").exists()

    verify = subprocess.run(
        [sys.executable, str(RUNNER_PATH), "verify-receipt", str(case["receipt"])],
        text=True, capture_output=True,
    )
    assert verify.returncode == 0, verify.stderr
    assert verify.stdout.strip() == receipt["receipt_sha256"]


def test_natural_candidate_failure_is_recorded_not_norecord(case):
    proc = invoke(case, behavior="exit7")
    assert proc.returncode == 1, proc.stderr
    receipt = runner.strict_load_receipt(case["receipt"])
    assert receipt["result"]["exit_code"] == 7
    assert receipt["result"]["attach_exit_code"] == 7
    assert receipt["cleanup"]["container_absent"] is True


@pytest.mark.parametrize("behavior", ["malformed", "duplicate", "nan"])
def test_malformed_progress_is_norecord_and_cleanup_is_owned(case, behavior):
    proc = invoke(case, behavior=behavior)
    assert proc.returncode == 2
    assert "[NORECORD]" in proc.stderr
    assert not case["receipt"].exists()
    assert not case["output"].exists()
    assert not (case["state"] / "container.json").exists()
    assert not (case["state"] / "volume.json").exists()
    assert not any("vibeic-candidate-export-" in value
                   for row in calls(case) for value in row)


def test_semantic_stall_has_no_total_runtime_verdict_and_cleans(case):
    proc = invoke(case, behavior="stall")
    assert proc.returncode == 2
    assert "semantic progress stalled" in proc.stderr
    assert "no elapsed-runtime verdict" in proc.stderr
    assert not case["receipt"].exists()
    assert not (case["state"] / "container.json").exists()
    assert not (case["state"] / "exporter.json").exists()
    assert not (case["state"] / "provisioner.json").exists()
    assert not (case["state"] / "volume.json").exists()


@pytest.mark.parametrize("behavior", ["wrong_user", "extra_mount"])
def test_profile_drift_refuses_before_candidate_start(case, behavior):
    proc = invoke(case, behavior=behavior)
    assert proc.returncode == 2
    assert not any(row[:2] == ["container", "start"] for row in calls(case))
    assert not (case["state"] / "container.json").exists()
    assert not (case["state"] / "provisioner.json").exists()
    assert not (case["state"] / "volume.json").exists()


def test_a_read_write_subject_bind_refuses_before_the_candidate_starts(case):
    """The arm's subject bind must be READ-ONLY, and that must be enforced.

    Nothing exercised this branch before. It is the property that makes a
    candidate arm structurally unable to pre-write the base wave's artifacts:
    the parent's run directory is not mounted into the arm at all, and every
    bind it does get is read-only. `wrong_user`/`extra_mount` above cannot
    reach it -- they perturb every container, so the evidence-volume
    provisioner refuses first and the candidate profile is never inspected.
    """
    proc = invoke(case, behavior="rw_bind")
    assert proc.returncode == 2
    # Refusing for the wrong reason is not a pass: name the owning branch.
    assert "subject bind is not exact/read-only" in proc.stderr, proc.stderr
    started = [row[-1] for row in calls(case)
               if row[:2] == ["container", "start"]]
    assert started, "the provisioner never ran, so this is not the branch above"
    assert not any("-provision-" not in name and "-export-" not in name
                   for name in started), started
    assert not case["receipt"].exists()


@pytest.mark.parametrize("behavior", ["oom", "restarting"])
def test_oom_or_restart_cannot_be_misreported_as_natural_exit(case, behavior):
    proc = invoke(case, behavior=behavior)
    assert proc.returncode == 2
    assert "dead-PID exit" in proc.stderr
    assert not case["receipt"].exists()


def test_receipt_duplicate_nan_noncanonical_and_digest_tamper_refuse(case, tmp_path):
    proc = invoke(case)
    assert proc.returncode == 0, proc.stderr
    raw = case["receipt"].read_bytes()
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_bytes(raw.replace(b'"schema":1', b'"schema":1,"schema":1', 1))
    with pytest.raises(ValueError, match="duplicate"):
        runner.strict_load_receipt(duplicate)
    nan = tmp_path / "nan.json"
    nan.write_bytes(raw.replace(b'"schema":1', b'"schema":NaN', 1))
    with pytest.raises(ValueError, match="non-finite"):
        runner.strict_load_receipt(nan)
    pretty = tmp_path / "pretty.json"
    pretty.write_text(json.dumps(json.loads(raw), indent=2), encoding="utf-8")
    with pytest.raises(ValueError, match="not canonical"):
        runner.strict_load_receipt(pretty)
    tampered = tmp_path / "tampered.json"
    doc = json.loads(raw)
    doc["result"]["exit_code"] = 1
    tampered.write_bytes(runner._canonical(doc) + b"\n")
    with pytest.raises(ValueError):
        runner.strict_load_receipt(tampered)


def test_signal_cleanup_removes_owned_container_and_volume(case):
    env = dict(os.environ)
    env["FAKE_DOCKER_STATE"] = str(case["state"])
    env["FAKE_DOCKER_BEHAVIOR"] = "stall"
    cmd = [
        sys.executable, str(RUNNER_PATH), "run",
        "--docker-bin", str(case["docker"]), "--subject", str(case["subject"]),
        "--runtime", str(case["runtime"]), "--overlay", "candidate.py",
        "--env", "GATEKEEPER_BENCHMARK_DATA_SHA=" + "b" * 40,
        "--env", "GATEKEEPER_VERIFY_ARM=A1",
        "--env", "VIBEIC_PYTEST_PROGRESS_FILE=/evidence/pytest-progress.jsonl",
        "--env", "VIBEIC_PYTEST_PROGRESS_NONCE=" + "d" * 64,
        "--corpus", str(case["corpus"]), "--selection", str(case["selection"]),
        "--progress-plan", str(case["plan"]), "--output-dir", str(case["output"]),
        "--receipt", str(case["receipt"]), "--", "/subject/candidate.py",
    ]
    proc = subprocess.Popen(cmd, env=env, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        path = case["state"] / "container.json"
        if path.exists():
            try:
                if json.loads(path.read_text())["State"]["Running"]:
                    break
            except (json.JSONDecodeError, KeyError):
                pass
        time.sleep(0.02)
    else:
        proc.kill()
        pytest.fail("fake candidate did not reach running state")
    proc.send_signal(signal.SIGTERM)
    stdout, stderr = proc.communicate()
    assert proc.returncode == 128 + signal.SIGTERM, (stdout, stderr)
    assert not (case["state"] / "container.json").exists()
    assert not (case["state"] / "volume.json").exists()
    assert not case["receipt"].exists()


def test_host_home_and_symlink_inputs_are_never_mounted(case, tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(runner, "_home_path", lambda: fake_home.resolve())
    inside = fake_home / "subject"
    inside.mkdir()
    args = type("Args", (), {
        "command": ["--", "/subject/candidate.py"], "output_dir": case["output"],
        "receipt": case["receipt"], "subject": inside, "corpus": case["corpus"],
        "runtime": case["runtime"], "overlay": ["candidate.py"],
        "env": ["GATEKEEPER_BENCHMARK_DATA_SHA=" + "b" * 40,
                "GATEKEEPER_VERIFY_ARM=A1"],
        "selection": case["selection"], "progress_plan": case["plan"],
        "docker_bin": str(case["docker"]),
    })()
    with pytest.raises(runner.Refusal, match="host HOME"):
        runner.run(args)
    link = tmp_path / "selection-link"
    link.symlink_to(case["selection"])
    # resolve() intentionally points to the safe target, so tree inputs instead
    # carry the special-path refusal exercised below.
    (case["subject"] / "escape").symlink_to("/etc/passwd")
    with pytest.raises(runner.Refusal, match="non-regular|symlink/special"):
        runner._tree_digest(case["subject"], "subject")


def test_overlay_manifest_is_sorted_regular_and_present_in_both_trees(case):
    (case["runtime"] / "z.py").write_text("#!/usr/bin/python3\n")
    (case["runtime"] / "z.py").chmod(0o755)
    (case["subject"] / "z.py").write_text("candidate bytes\n")
    with pytest.raises(runner.Refusal, match="sorted unique"):
        runner._overlay_paths(
            ["z.py", "candidate.py"], case["runtime"], case["subject"])
    with pytest.raises(runner.Refusal, match="missing"):
        runner._overlay_paths(["missing.py"], case["runtime"], case["subject"])
    (case["runtime"] / "linked.py").symlink_to("candidate.py")
    (case["subject"] / "linked.py").write_text("candidate bytes\n")
    with pytest.raises(runner.Refusal, match="not regular"):
        runner._overlay_paths(["linked.py"], case["runtime"], case["subject"])


def test_reviewed_environment_is_arm_conditional_and_path_bound():
    test = [
        "GATEKEEPER_BENCHMARK_DATA_SHA=" + "b" * 40,
        "GATEKEEPER_VERIFY_ARM=A1",
        "VIBEIC_PYTEST_PROGRESS_FILE=/evidence/pytest-progress.jsonl",
        "VIBEIC_PYTEST_PROGRESS_NONCE=" + "d" * 64,
    ]
    assert runner._reviewed_process_env(test) == {
        "GATEKEEPER_BENCHMARK_DATA_SHA": "b" * 40,
        "GATEKEEPER_VERIFY_ARM": "A1",
        "VIBEIC_PYTEST_PROGRESS_FILE": "/evidence/pytest-progress.jsonl",
        "VIBEIC_PYTEST_PROGRESS_NONCE": "d" * 64,
    }
    with pytest.raises(runner.Refusal, match="missing"):
        runner._reviewed_process_env(["GATEKEEPER_VERIFY_ARM=A1"])
    with pytest.raises(runner.Refusal, match="excess"):
        runner._reviewed_process_env(sorted(test + [
            "GATEKEEPER_HYGIENE_REPORT=/evidence/hygiene.json",
        ]))
    land = [
        "GATEKEEPER_BASE=" + "a" * 40,
        "GATEKEEPER_BENCHMARK_DATA_SHA=" + "b" * 64,
        "GATEKEEPER_HYGIENE_PROGRESS=/evidence/hygiene-progress.jsonl",
        "GATEKEEPER_HYGIENE_REPORT=/evidence/hygiene.json",
        "GATEKEEPER_VERIFY_ARM=B2",
        "GATEKEEPER_VERSION_BY_GATEKEEPER=1",
        "VIBEIC_LANDING_PROGRESS_NONCE=" + "c" * 64,
    ]
    assert set(runner._reviewed_process_env(land)) == runner._LAND_REVIEWED_ENV_NAMES
    land_fixed = runner._fixed_process_env("B2")
    assert land_fixed["GATEKEEPER_NO_STAMP"] == "1"
    assert land_fixed["GATEKEEPER_SKIP_TARGETED_TESTS"] == "1"
    assert land_fixed["VIBE_IC_BENCHMARK_DATA"] == "/corpus"
    assert land_fixed["VIBEIC_LANDING_COMPLETION"] == \
        "/evidence/landing-completion.json"
    assert land_fixed["VIBEIC_LANDING_PROGRESS"] == \
        "/evidence/landing-progress.jsonl"
    assert land_fixed["GIT_CONFIG_COUNT"] == "2"
    assert land_fixed["GIT_CONFIG_GLOBAL"] == "/dev/null"
    assert land_fixed["GIT_CONFIG_KEY_0"] == "safe.directory"
    assert land_fixed["GIT_CONFIG_NOSYSTEM"] == "1"
    assert land_fixed["GIT_CONFIG_VALUE_0"] == "/subject"
    assert land_fixed["GIT_CONFIG_KEY_1"] == "safe.directory"
    assert land_fixed["GIT_CONFIG_VALUE_1"] == "/corpus"
    assert land_fixed["GIT_NO_REPLACE_OBJECTS"] == "1"
    assert "PYTHONPATH" not in land_fixed
    bad_version = list(land)
    bad_version[5] = "GATEKEEPER_VERSION_BY_GATEKEEPER=2"
    with pytest.raises(runner.Refusal, match="must be 0 or 1"):
        runner._reviewed_process_env(bad_version)
    active_version = list(land)
    active_version[5] = "GATEKEEPER_VERSION_BY_GATEKEEPER=0"
    assert runner._reviewed_process_env(active_version)[
        "GATEKEEPER_VERSION_BY_GATEKEEPER"] == "0"
    bad_base = list(land)
    bad_base[0] = "GATEKEEPER_BASE=refs/heads/main"
    with pytest.raises(runner.Refusal, match="full lowercase object digest"):
        runner._reviewed_process_env(bad_base)
    with pytest.raises(runner.Refusal, match="not in the reviewed allowlist"):
        runner._reviewed_process_env(sorted(land + [
            "GATEKEEPER_BENCHMARK_MEASUREMENT_RECORD=/input/measurement.json",
        ]))
    bad = list(land)
    bad[2] = "GATEKEEPER_HYGIENE_PROGRESS=/tmp/leak"
    with pytest.raises(runner.Refusal, match="under evidence"):
        runner._reviewed_process_env(bad)


def test_live_exact_image_capability_and_profile(tmp_path):
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker CLI unavailable")
    available = subprocess.run(
        [docker, "image", "inspect", runner.IMAGE],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if available.returncode != 0:
        pytest.skip("exact digest-pinned image unavailable")
    subject = tmp_path / "subject"
    runtime = tmp_path / "runtime"
    corpus = tmp_path / "corpus"
    subject.mkdir()
    runtime.mkdir()
    corpus.mkdir()
    (subject / "input.txt").write_text("subject\n")
    (corpus / "input.def").write_text("VERSION 5.8 ;\n")
    selection = tmp_path / "selection.json"
    selection.write_text("{}\n")
    plan = tmp_path / "progress.json"
    plan.write_text(canonical({
        "schema": 1, "scope": "live", "stall_grace_seconds": 30,
        "units": ["write"],
    }) + "\n")
    output = tmp_path / "output"
    receipt = tmp_path / "receipt.json"
    script = r'''#!/bin/sh
set -eu
test "$GATEKEEPER_RUNTIME_ROOT" = /runtime
test "$VIBEIC_REQUIRE_TRUSTED_PYTEST_ENTRY" = 1
test "$GATEKEEPER_VERIFY_ARM" = A1
test "$VIBE_IC_BENCHMARK_DATA" = /corpus
test "$GATEKEEPER_BENCHMARK_DATA_SHA" = bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
test -z "${STARTUPDIR+x}"
printf 'VIBEIC_PROGRESS {"nonce":"%s","schema":1,"scope":"live","seq":0,"state":"start","total":1}\n' "$VIBEIC_HERMETIC_PROGRESS_NONCE"
printf 'candidate evidence\n' > "$VIBEIC_HERMETIC_EVIDENCE_PATH/result.txt"
printf 'VIBEIC_PROGRESS {"completed":1,"nonce":"%s","schema":1,"scope":"live","seq":1,"state":"checkpoint","total":1,"unit":"write"}\n' "$VIBEIC_HERMETIC_PROGRESS_NONCE"
printf 'VIBEIC_PROGRESS {"completed":1,"nonce":"%s","schema":1,"scope":"live","seq":2,"state":"terminal","total":1}\n' "$VIBEIC_HERMETIC_PROGRESS_NONCE"
'''
    (subject / "run.sh").write_text("#!/bin/sh\nexit 99\n")
    (runtime / "run.sh").write_text(script)
    (runtime / "run.sh").chmod(0o755)
    proc = subprocess.run([
        sys.executable, str(RUNNER_PATH), "run", "--docker-bin", docker,
        "--subject", str(subject), "--runtime", str(runtime),
        "--overlay", "run.sh", "--corpus", str(corpus),
        "--env", "GATEKEEPER_BENCHMARK_DATA_SHA=" + "b" * 40,
        "--env", "GATEKEEPER_VERIFY_ARM=A1",
        "--env", "VIBEIC_PYTEST_PROGRESS_FILE=/evidence/pytest-progress.jsonl",
        "--env", "VIBEIC_PYTEST_PROGRESS_NONCE=" + "d" * 64,
        "--selection", str(selection), "--progress-plan", str(plan),
        "--output-dir", str(output), "--receipt", str(receipt),
        "--", "/subject/run.sh",
    ], text=True, capture_output=True)
    assert proc.returncode == 0, proc.stderr
    assert (output / "result.txt").read_text() == "candidate evidence\n"
    assert (output / "runner-stdout.bin").is_file()
    loaded = runner.strict_load_receipt(receipt)
    assert loaded["image"]["reference"] == runner.IMAGE
    assert loaded["cleanup"] == {
        "container_absent": True, "exporter_absent": True,
        "provisioner_absent": True,
        "volume_absent": True,
    }
