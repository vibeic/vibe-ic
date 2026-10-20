"""Issue #2863: drive both shipped restart scripts with an inert Docker CLI.

The fake records every Docker request and never operates on a real container.
RESTART_EDA_OLD_SCRIPT selects saved, unmodified script bytes for the measured
red arm; the normal arm runs the repository and packaged files directly.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[5]
COPIES = (
    REPO / "tools/vibeic-eda/restart-eda.sh",
    REPO / "vibe-ic-marketplace/plugins/vibe-ic/tools/vibeic-eda/restart-eda.sh",
)
IMAGE = "example.invalid/vibeic-eda:fixture"
ID = "sha256:" + "a" * 64

# Deliberately a Docker CLI, not a duplicate guard implementation. Any change
# in restart-eda.sh's control flow is visible in the recorded argv and rc.
FAKE_DOCKER = r'''#!/usr/bin/env python3
import json, os, sys
argv = sys.argv[1:]
with open(os.environ["MOCK_LOG"], "a") as f:
    f.write(json.dumps(argv) + "\n")
verb = argv[0] if argv else ""
fmt = argv[argv.index("--format") + 1] if "--format" in argv else ""
if verb == "image" and argv[1:2] == ["inspect"]:
    print(os.environ["MOCK_IMAGE_ID"])
    sys.exit(0)
if verb == "container" and argv[1:2] == ["inspect"]:
    sys.exit(0)
if verb == "top":
    if os.environ["MOCK_TOP_STATUS"] != "0":
        sys.stderr.write("Couldn't find PID field in ps output\n")
        sys.exit(int(os.environ["MOCK_TOP_STATUS"]))
    sys.stdout.write(os.environ["MOCK_TOP_OUTPUT"])
    sys.exit(0)
if verb == "inspect":
    if fmt == "{{.Config.Image}}": print("example.invalid/vibeic-eda:old")
    elif fmt == "{{.Config.User}}": print("1000")
    elif fmt == "{{.Config.WorkingDir}}": print("/work")
    elif fmt == "{{.Image}}": print(os.environ["MOCK_IMAGE_ID"])
    elif "{{range .Config.Cmd}}" in fmt: print("--skip\nsleep\ninfinity")
    elif "{{range .Mounts}}" in fmt:
        # Read back the actual installer-generated mounts, including the
        # serving bundle. The busy guard's idle path must reach this check.
        calls = [json.loads(line) for line in open(os.environ["MOCK_LOG"])]
        created = next((c for c in calls if c[:1] == ["run"]), [])
        for i, word in enumerate(created):
            if word == "-v":
                parts = created[i + 1].split(":")
                opts = parts[2].split(",") if len(parts) > 2 else []
                print(parts[1] + "|" + parts[0] + "|" +
                      ("false" if "ro" in opts else "true"))
    sys.exit(0)
if verb == "run":
    print("fixture-new-container")
    sys.exit(0)
if verb in ("rm", "rename", "stop", "start", "ps", "images"):
    sys.exit(0)
sys.stderr.write("unexpected Docker request: %r\n" % argv)
sys.exit(98)
'''


def _run(tmp_path: Path, script: Path, *, top: str, top_rc: int = 0,
         force: bool = False):
    old = os.environ.get("RESTART_EDA_OLD_SCRIPT")
    if old:
        # Preserve the old script bytes exactly; only provide the real script's
        # external memory helper in an isolated installed-layout fixture.
        source_bytes = Path(old).read_bytes()
        installed = tmp_path / "old-plugin/tools/vibeic-eda/restart-eda.sh"
        installed.parent.mkdir(parents=True)
        installed.write_bytes(source_bytes)
        program = tmp_path / "old-plugin/programs/_docker_memory.py"
        program.parent.mkdir(parents=True)
        program.write_text("#!/usr/bin/env python3\nprint('--memory=8g')\n")
        script = installed
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake = fake_bin / "docker"
    fake.write_text(FAKE_DOCKER)
    fake.chmod(0o755)
    log = tmp_path / "docker.log"
    env = dict(os.environ)
    env.update({
        "PATH": f"{fake_bin}:{env.get('PATH', '/usr/bin:/bin')}",
        "MOCK_LOG": str(log),
        "MOCK_IMAGE_ID": ID,
        "MOCK_TOP_STATUS": str(top_rc),
        "MOCK_TOP_OUTPUT": top,
        "VIBEIC_DOCKER_MEMORY": "8g",
        "HOME": str(tmp_path),
        "FORCE": "1" if force else "0",
    })
    result = subprocess.run(["bash", str(script), IMAGE], env=env,
                            capture_output=True, text=True, timeout=30)
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    return result, calls


def _destructive(calls):
    return [c for c in calls if c and c[0] in
            {"rm", "rename", "stop", "start", "run", "kill"}]


@pytest.mark.parametrize("script", COPIES, ids=("repository", "packaged"))
def test_failed_process_readback_refuses_before_recreation(tmp_path, script):
    result, calls = _run(tmp_path, script, top="", top_rc=1)
    assert result.returncode == 2, (result.stdout, result.stderr, calls)
    assert "readback" in result.stderr.lower()
    assert _destructive(calls) == []
    assert [c for c in calls if c and c[0] == "top"]


@pytest.mark.parametrize("script", COPIES, ids=("repository", "packaged"))
def test_live_vvp_refuses_before_recreation(tmp_path, script):
    result, calls = _run(tmp_path, script,
                         top="PID COMMAND\n241 vvp simulation.vvp\n")
    assert result.returncode == 2, (result.stdout, result.stderr, calls)
    assert "vvp" in result.stderr
    assert _destructive(calls) == []


@pytest.mark.parametrize("script", COPIES, ids=("repository", "packaged"))
def test_live_yosys_still_refuses_before_recreation(tmp_path, script):
    result, calls = _run(tmp_path, script,
                         top="PID COMMAND\n242 yosys -s synth.ys\n")
    assert result.returncode == 2, (result.stdout, result.stderr, calls)
    assert "yosys" in result.stderr
    assert _destructive(calls) == []


@pytest.mark.parametrize("script", COPIES, ids=("repository", "packaged"))
@pytest.mark.parametrize("top", (
    "",
    "COMMAND\nsleep infinity\n",
    "PID COMMAND\nnot-a-pid sleep infinity\n",
    "PID COMMAND\n",
))
def test_malformed_process_readback_refuses_before_recreation(tmp_path, script,
                                                               top):
    result, calls = _run(tmp_path, script, top=top)
    assert result.returncode == 2, (result.stdout, result.stderr, calls)
    assert "readback" in result.stderr.lower()
    assert _destructive(calls) == []


@pytest.mark.parametrize("script", COPIES, ids=("repository", "packaged"))
def test_idle_process_allows_preserved_recreation(tmp_path, script):
    result, calls = _run(tmp_path, script,
                         top="PID COMMAND\n243 sleep infinity\n")
    assert result.returncode == 0, (result.stdout, result.stderr, calls)
    assert any(c[0] == "rename" for c in calls)
    assert any(c[0] == "run" for c in calls)
    assert any(c[0] == "stop" for c in calls)


@pytest.mark.parametrize("script", COPIES, ids=("repository", "packaged"))
@pytest.mark.parametrize("top,top_rc", (
    ("PID COMMAND\n244 vvp simulation.vvp\n", 0),
    ("", 1),
))
def test_explicit_force_retains_override(tmp_path, script, top, top_rc):
    result, calls = _run(tmp_path, script, top=top, top_rc=top_rc, force=True)
    assert result.returncode == 0, (result.stdout, result.stderr, calls)
    assert "FORCE=1" in (result.stdout + result.stderr)
    assert any(c[0] == "run" for c in calls)
