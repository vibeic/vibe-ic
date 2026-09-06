#!/usr/bin/env python3
"""Regression for issue #2038: `restart-eda.sh` must clone BOTH Docker mount
declaration forms, refuse before destroying anything, and read the mounts back.

WHAT WENT WRONG. `docker inspect --format '{{range .HostConfig.Binds}}...'` was
the script's SOLE producer of mount arguments. A container created with
`--mount` records nothing in `.HostConfig.Binds` (it is null) and everything in
`.HostConfig.Mounts`, so that query returned an empty list and the replacement
container was created with NO mounts at all. Measured 2026-09-06 on a fleet
host: the container being replaced had `binds=0 mounts=2` (two writable binds);
what replaced it had `binds=0 mounts=0`. Cmd, user, workdir and the memory
ceiling were all carried over correctly — only the mounts were lost, and the
script printed `== OK: container image id matches` over the loss, because the
readback looked at the image id alone.

HOW THIS IS TESTED. Every case here drives the real script against a MOCKED
`docker` on PATH whose inspect output is synthetic, per the issue's explicit
instruction never to use a production container for the negative arm. The mock
derives its post-recreate `.Mounts` readback FROM the recorded `docker run`
argv, so a readback assertion is an assertion about what the script actually
asked docker for, not about a value the mock was told to print.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


def _find(rel):
    for up in Path(__file__).resolve().parents:
        c = up / rel
        if c.is_file():
            return c
    return None


SCRIPT = _find(Path("tools") / "vibeic-eda" / "restart-eda.sh")
pytestmark = pytest.mark.skipif(
    SCRIPT is None, reason="tools/vibeic-eda/restart-eda.sh not present")

IMAGE = "vibeic/vibeic-eda:mock"
TARGET_ID = "sha256:" + "a" * 64

#: A mocked `docker` CLI. It answers only the queries this script makes, keyed
#: off the go-template it is handed, and records every invocation.
FAKE_DOCKER = r'''#!/usr/bin/env python3
import json, os, sys

argv = sys.argv[1:]
state = json.load(open(os.environ["MOCK_STATE"]))
log = os.environ["MOCK_LOG"]
with open(log, "a") as fh:
    fh.write(json.dumps(argv) + "\n")


def out(s=""):
    sys.stdout.write(s + "\n")


def run_argv():
    for line in open(log):
        a = json.loads(line)
        if a and a[0] == "run":
            return a
    return None


def mounts_from_run():
    """Reconstruct the new container's normalized .Mounts from the run argv."""
    a = run_argv()
    if a is None or os.environ.get("MOCK_DROP_MOUNTS") == "1":
        return []
    res, i = [], 0
    while i < len(a):
        if a[i] == "-v":
            parts = a[i + 1].split(":")
            src, dst = parts[0], parts[1]
            opts = parts[2].split(",") if len(parts) > 2 else []
            res.append((dst, src, "false" if "ro" in opts else "true"))
            i += 2
        elif a[i] == "--tmpfs":
            res.append((a[i + 1], "", "true"))
            i += 2
        else:
            i += 1
    return res


verb = argv[0] if argv else ""
fmt = ""
if "--format" in argv:
    fmt = argv[argv.index("--format") + 1]

if verb == "image" and argv[1:2] == ["inspect"]:
    if "{{.Id}}" in fmt:
        out(os.environ.get("MOCK_TARGET_ID", ""))
    sys.exit(0)

if verb == "container" and argv[1:2] == ["inspect"]:
    sys.exit(0 if state.get("exists") else 1)

if verb == "inspect":
    created = run_argv() is not None
    if "{{range .Mounts}}" in fmt:
        for dst, src, rw in mounts_from_run():
            out("%s|%s|%s" % (dst, src, rw))
        sys.exit(0)
    if fmt.strip() == "{{.Image}}":
        out(os.environ.get("MOCK_NEW_IMAGE_ID",
                           os.environ.get("MOCK_TARGET_ID", "")))
        sys.exit(0)
    if not state.get("exists") and not created:
        sys.exit(1)
    hc = state.get("HostConfig", {})
    cfg = state.get("Config", {})
    if "{{.Config.Image}}" in fmt:
        out(cfg.get("Image", ""))
    elif "{{range .HostConfig.Binds}}" in fmt:
        for b in (hc.get("Binds") or []):
            out(b)
    elif "{{range .HostConfig.Mounts}}" in fmt:
        for m in (hc.get("Mounts") or []):
            prop = (m.get("BindOptions") or {}).get("Propagation", "")
            out("%s|%s|%s|%s|%s" % (m.get("Type", "bind"), m.get("Source", ""),
                                    m.get("Target", ""),
                                    "true" if m.get("ReadOnly") else "false",
                                    prop))
    elif "{{.Config.User}}" in fmt:
        out(cfg.get("User", ""))
    elif "{{.Config.WorkingDir}}" in fmt:
        out(cfg.get("WorkingDir", ""))
    elif "{{range .Config.Cmd}}" in fmt:
        for c in (cfg.get("Cmd") or []):
            out(c)
    sys.exit(0)

if verb in ("top", "ps", "images"):
    sys.exit(0)
if verb in ("rename", "stop", "start", "rm"):
    sys.exit(0)
if verb == "run":
    out("deadbeef")
    sys.exit(int(os.environ.get("MOCK_RUN_RC", "0")))
sys.exit(0)
'''


class Harness:
    def __init__(self, tmp_path, state):
        self.dir = tmp_path
        self.bin = tmp_path / "bin"
        self.bin.mkdir(parents=True, exist_ok=True)
        fake = self.bin / "docker"
        fake.write_text(FAKE_DOCKER)
        fake.chmod(0o755)
        self.state = tmp_path / "state.json"
        self.state.write_text(json.dumps(state))
        self.log = tmp_path / "docker.log"
        self.log.write_text("")

    def run(self, script=None, **env_extra):
        env = {
            "PATH": f"{self.bin}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "MOCK_STATE": str(self.state),
            "MOCK_LOG": str(self.log),
            "MOCK_TARGET_ID": TARGET_ID,
            "VIBEIC_DOCKER_MEMORY": "8g",
            "HOME": str(self.dir),
        }
        env.update({k: str(v) for k, v in env_extra.items()})
        return subprocess.run(
            ["bash", str(script or SCRIPT), IMAGE],
            capture_output=True, text=True, env=env, timeout=180)

    def calls(self):
        return [json.loads(l) for l in self.log.read_text().splitlines() if l]

    def run_argv(self):
        return next((c for c in self.calls() if c and c[0] == "run"), None)

    def mount_args(self):
        a = self.run_argv() or []
        return [a[i + 1] for i, tok in enumerate(a) if tok == "-v"]


def _state(binds=None, mounts=None, exists=True):
    return {
        "exists": exists,
        "HostConfig": {"Binds": binds, "Mounts": mounts},
        "Config": {"Image": "vibeic/vibeic-eda:old", "User": "1000",
                   "WorkingDir": "/foss/designs",
                   "Cmd": ["--skip", "sleep", "infinity"]},
    }


# --- the defect itself ------------------------------------------------------

def test_structured_mounts_are_cloned(tmp_path):
    """`--mount`-declared bind mounts (Binds null) must reach the new container.

    This is the exact shape the issue names, with the source pointed at a real
    directory so the preflight has something to validate.
    """
    src = tmp_path / "work"
    src.mkdir()
    h = Harness(tmp_path, _state(binds=None, mounts=[
        {"Type": "bind", "Source": str(src), "Target": "/work",
         "ReadOnly": True}]))
    r = h.run()
    assert r.returncode == 0, r.stderr
    assert h.mount_args() == [f"{src}:/work:ro"], (h.run_argv(), r.stdout)


def test_issue_literal_shape_refuses_rather_than_recreating_bare(tmp_path):
    """The issue's literal `/work` source does not exist on this host.

    The honest outcome is a REFUSAL at preflight — never a silent recreate with
    an empty mount array, which is what the old script did.
    """
    h = Harness(tmp_path, _state(binds=None, mounts=[
        {"Type": "bind", "Source": "/work", "Target": "/work",
         "ReadOnly": True}]))
    r = h.run()
    assert r.returncode == 4, (r.returncode, r.stdout, r.stderr)
    assert "does not exist" in r.stderr
    assert h.run_argv() is None


def test_legacy_binds_are_still_cloned(tmp_path):
    """The pre-existing form must keep working — this fix adds, never replaces."""
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(); b.mkdir()
    h = Harness(tmp_path, _state(
        binds=[f"{a}:{a}", f"{b}:/foss/designs"], mounts=None))
    r = h.run()
    assert r.returncode == 0, r.stderr
    assert h.mount_args() == [f"{a}:{a}", f"{b}:/foss/designs"]


def test_mixed_forms_deduplicate_by_destination(tmp_path):
    """A destination declared in both forms produces ONE argument, not two."""
    a, x, y = tmp_path / "a", tmp_path / "x", tmp_path / "y"
    for p in (a, x, y):
        p.mkdir()
    h = Harness(tmp_path, _state(
        binds=[f"{a}:/dst"],
        mounts=[{"Type": "bind", "Source": str(x), "Target": "/dst"},
                {"Type": "bind", "Source": str(y), "Target": "/other"}]))
    r = h.run()
    assert r.returncode == 0, r.stderr
    assert h.mount_args() == [f"{a}:/dst", f"{y}:/other"]


def test_propagation_is_retained(tmp_path):
    src = tmp_path / "p"
    src.mkdir()
    h = Harness(tmp_path, _state(binds=None, mounts=[
        {"Type": "bind", "Source": str(src), "Target": "/p", "ReadOnly": False,
         "BindOptions": {"Propagation": "rshared"}}]))
    r = h.run()
    assert r.returncode == 0, r.stderr
    assert h.mount_args() == [f"{src}:/p:rshared"]


# --- readback: an image-id match is not a successful recreate ---------------

def test_readback_catches_dropped_mounts_and_rolls_back(tmp_path):
    """If the mounts are gone after recreate, the script must FAIL, not print OK.

    `MOCK_DROP_MOUNTS=1` makes the mock report an empty `.Mounts` while the
    image id still matches — precisely the state that reached a host on
    2026-09-06 under an `== OK: container image id matches` line.
    """
    src = tmp_path / "work"
    src.mkdir()
    h = Harness(tmp_path, _state(binds=[f"{src}:/work"], mounts=None))
    r = h.run(MOCK_DROP_MOUNTS="1")
    assert r.returncode == 3, (r.returncode, r.stdout, r.stderr)
    assert "readback failed" in r.stderr
    assert "/work" in r.stderr
    assert "OK: all" not in r.stdout
    # the rollback container was renamed back into place
    assert any(c[:1] == ["rename"] and c[-1] == "vibeic-eda"
               for c in h.calls()), h.calls()


def test_readback_catches_readonly_downgrade(tmp_path):
    """A mount that comes back writable when it was declared read-only is a
    settings mismatch, not a success."""
    src = tmp_path / "work"
    src.mkdir()
    st = _state(binds=None, mounts=[
        {"Type": "bind", "Source": str(src), "Target": "/work",
         "ReadOnly": True}])
    h = Harness(tmp_path, st)
    # Mutate the mock so the readback reports RW=true for a declared-ro mount.
    fake = h.bin / "docker"
    fake.write_text(fake.read_text().replace(
        '"false" if "ro" in opts else "true"', '"true"'))
    r = h.run()
    assert r.returncode == 3, (r.returncode, r.stdout, r.stderr)
    assert "RW=true" in r.stderr


# --- ordering: refusals must precede destruction ---------------------------

def test_preflight_refusal_leaves_the_original_container_untouched(tmp_path):
    h = Harness(tmp_path, _state(binds=None, mounts=[
        {"Type": "bind", "Source": str(tmp_path / "absent"),
         "Target": "/gone"}]))
    r = h.run()
    assert r.returncode == 4, (r.returncode, r.stderr)
    # #2038's acceptance is explicit: an invalid preflight must not REMOVE or
    # STOP the original container. `stop` was missing from this list until the
    # issue's wording was re-read against it.
    verbs = [c[0] for c in h.calls()]
    for destructive in ("rm", "rename", "stop", "run", "kill"):
        assert destructive not in verbs, (destructive, verbs)


def test_old_container_is_kept_until_readback_passes(tmp_path):
    """The old container is renamed aside, not destroyed, and only removed once
    the replacement has passed readback."""
    src = tmp_path / "work"
    src.mkdir()
    h = Harness(tmp_path, _state(binds=[f"{src}:/work"], mounts=None))
    r = h.run()
    assert r.returncode == 0, r.stderr
    calls = h.calls()
    rename_i = next(i for i, c in enumerate(calls) if c[0] == "rename")
    run_i = next(i for i, c in enumerate(calls) if c[0] == "run")
    # the LAST rollback `rm` is the post-readback cleanup; an earlier one is
    # the pre-clean of a stale same-name leftover.
    rm_i = max(i for i, c in enumerate(calls)
               if c[0] == "rm" and c[-1].startswith("vibeic-eda-rollback-"))
    assert rename_i < run_i < rm_i, calls


def test_memory_ceiling_flags_are_preserved(tmp_path):
    src = tmp_path / "work"
    src.mkdir()
    h = Harness(tmp_path, _state(binds=[f"{src}:/work"], mounts=None))
    r = h.run(VIBEIC_DOCKER_MEMORY="7g")
    assert r.returncode == 0, r.stderr
    a = h.run_argv()
    assert "--memory" in a and a[a.index("--memory") + 1] == "7g"
    assert "--memory-swap" in a and a[a.index("--memory-swap") + 1] == "7g"


def test_cmd_user_and_workdir_are_preserved(tmp_path):
    src = tmp_path / "work"
    src.mkdir()
    h = Harness(tmp_path, _state(binds=[f"{src}:/work"], mounts=None))
    r = h.run()
    assert r.returncode == 0, r.stderr
    a = h.run_argv()
    assert a[a.index("-u") + 1] == "1000"
    assert a[a.index("-w") + 1] == "/foss/designs"
    assert a[-3:] == ["--skip", "sleep", "infinity"]


def test_failed_docker_run_restores_the_previous_container(tmp_path):
    src = tmp_path / "work"
    src.mkdir()
    h = Harness(tmp_path, _state(binds=[f"{src}:/work"], mounts=None))
    r = h.run(MOCK_RUN_RC="1")
    assert r.returncode == 6, (r.returncode, r.stderr)
    assert "rolled back" in r.stderr


# --- the FRESH-container branch: no existing container to clone ------------
#
# This is the FIRST-INSTALL path, and it was rewritten by the same change (its
# two canonical binds now go through `add_mount` like every other declaration).
# Nothing exercised it: every case above sets `exists=True`, and the older
# pinned-default test file never mentions DESIGNS_DIR at all. A break here
# would land on a new user's very first run, which is the worst place to find
# out, so the branch gets the same treatment as the clone path.

class TestFreshContainerBranch:
    def _fresh(self, tmp_path, designs=None, **env):
        h = Harness(tmp_path, _state(exists=False))
        if designs is not None:
            env["DESIGNS_DIR"] = str(designs)
        return h, h.run(**env)

    def test_canonical_designs_binds_are_emitted(self, tmp_path):
        designs = tmp_path / "designs"
        designs.mkdir()
        h, r = self._fresh(tmp_path, designs)
        assert r.returncode == 0, r.stderr
        assert h.mount_args() == [f"{designs}:{designs}", f"{designs}:/foss/designs"]

    def test_canonical_user_workdir_and_cmd(self, tmp_path):
        designs = tmp_path / "designs"
        designs.mkdir()
        h, r = self._fresh(tmp_path, designs)
        assert r.returncode == 0, r.stderr
        a = h.run_argv()
        assert a[a.index("-w") + 1] == "/foss/designs"
        assert a[-3:] == ["--skip", "sleep", "infinity"]

    def test_readback_still_checks_the_fresh_mounts(self, tmp_path):
        """The fresh branch must not be exempt from the mount readback."""
        designs = tmp_path / "designs"
        designs.mkdir()
        h, r = self._fresh(tmp_path, designs, MOCK_DROP_MOUNTS="1")
        assert r.returncode == 3, (r.returncode, r.stdout, r.stderr)
        assert "readback failed" in r.stderr

    def test_no_rollback_rename_when_there_was_nothing_to_roll_back(self, tmp_path):
        designs = tmp_path / "designs"
        designs.mkdir()
        h, r = self._fresh(tmp_path, designs)
        assert r.returncode == 0, r.stderr
        assert not any(c[0] == "rename" for c in h.calls()), h.calls()

    def test_missing_designs_dir_is_refused(self, tmp_path):
        h, r = self._fresh(tmp_path)          # neither env var set
        assert r.returncode == 1, (r.returncode, r.stderr)
        assert "DESIGNS_DIR" in r.stderr
        assert h.run_argv() is None

    def test_relative_designs_dir_is_refused(self, tmp_path):
        h = Harness(tmp_path, _state(exists=False))
        r = h.run(DESIGNS_DIR="relative/path")
        assert r.returncode == 1, (r.returncode, r.stderr)
        assert "absolute path" in r.stderr
        assert h.run_argv() is None

    def test_nonexistent_designs_dir_is_refused_and_never_created(self, tmp_path):
        """docker would create a missing bind source root-owned — the phantom
        directory bug. The refusal must come first, and must not mkdir it."""
        absent = tmp_path / "not_there"
        h, r = self._fresh(tmp_path, absent)
        assert r.returncode == 1, (r.returncode, r.stderr)
        assert "does not exist" in r.stderr
        assert not absent.exists(), "the refusal created the directory it refused"
        assert h.run_argv() is None
        verbs = [c[0] for c in h.calls()]
        for destructive in ("rm", "rename", "stop", "run", "kill"):
            assert destructive not in verbs, (destructive, verbs)
