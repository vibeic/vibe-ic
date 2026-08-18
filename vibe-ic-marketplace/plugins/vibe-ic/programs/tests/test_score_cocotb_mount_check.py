"""Regression: score_cocotb_mcp.py must refuse to docker-exec when --mount-root
doesn't correspond to an actual bind mount on the container.

Captured from v0.1.53 CVDP Shape-D run (Bucket A, R1): a wrong --mount-root
silently produced TESTS=0 PASS=0 FAIL=0 SKIP=0 with the real error
('cd: /foss/designs/...: No such file or directory') buried in log_tail.
The added _validate_mount() raises SystemExit BEFORE docker exec when the
host path isn't actually mounted.
"""
import importlib.util
import json
from pathlib import Path
import pytest

SCRIPT = (Path(__file__).resolve().parents[2]
          / "benchmark" / "score_cocotb_mcp.py")


def _load_module():
    spec = importlib.util.spec_from_file_location("score_cocotb_mcp", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_module_loads():
    """The script must remain importable as a module (no top-level side effects)."""
    mod = _load_module()
    assert hasattr(mod, "_validate_mount")
    assert hasattr(mod, "_container_mounts")
    assert hasattr(mod, "_docker_path")


def test_validate_mount_accepts_exact_match(monkeypatch):
    """_validate_mount returns silently when mount_host exactly matches a docker mount source."""
    mod = _load_module()
    monkeypatch.setattr(mod, "_container_mounts",
                        lambda c: [(Path("/srv/designs"), "/foss/designs")])
    # Exact source match
    mod._validate_mount("vibeic-eda", Path("/srv/designs"), "/foss/designs")


def test_validate_mount_accepts_parent_relationship(monkeypatch):
    """If mount_host is UNDER an actual source, accept (so the dest path resolves)."""
    mod = _load_module()
    monkeypatch.setattr(mod, "_container_mounts",
                        lambda c: [(Path("/srv/designs"), "/foss/designs")])
    # mount_host /srv/designs/subdir is under the actual source — but the
    # _docker_path translation wouldn't be right. The validator's contract is:
    # mount_host must BE the source (exact) or have the source as an ancestor.
    # The "/srv/designs" is an ancestor of "/srv/designs/sub", so this passes.
    mod._validate_mount("vibeic-eda", Path("/srv/designs/sub"), "/foss/designs")


def test_validate_mount_rejects_unmounted_path(monkeypatch):
    """The actual CVDP-run scenario: --mount-root /home/x/vibe-ic but container mounts /home/x/AI_IC_design."""
    mod = _load_module()
    monkeypatch.setattr(mod, "_container_mounts",
                        lambda c: [(Path("/home/x/AI_IC_design"), "/foss/designs")])
    with pytest.raises(SystemExit) as ei:
        mod._validate_mount("vibeic-eda", Path("/home/x/vibe-ic"), "/foss/designs")
    msg = str(ei.value)
    assert "NOT an actual bind mount" in msg
    assert "/home/x/AI_IC_design" in msg
    assert "/foss/designs" in msg


def test_validate_mount_rejects_wrong_destination(monkeypatch):
    """Source matches but dest doesn't — must reject (paths won't resolve)."""
    mod = _load_module()
    monkeypatch.setattr(mod, "_container_mounts",
                        lambda c: [(Path("/srv/designs"), "/some/other/dest")])
    with pytest.raises(SystemExit) as ei:
        mod._validate_mount("vibeic-eda", Path("/srv/designs"), "/foss/designs")
    assert "NOT an actual bind mount" in str(ei.value)


def test_validate_mount_rejects_no_mounts(monkeypatch):
    """Container with no mounts at all is unusable."""
    mod = _load_module()
    monkeypatch.setattr(mod, "_container_mounts", lambda c: [])
    with pytest.raises(SystemExit) as ei:
        mod._validate_mount("vibeic-eda", Path("/srv/designs"), "/foss/designs")
    assert "no bind mounts" in str(ei.value)


def test_container_mounts_parses_docker_inspect_output(monkeypatch):
    """_container_mounts must parse `docker inspect` JSON correctly."""
    mod = _load_module()
    fake_output = json.dumps([{
        "Mounts": [
            {"Source": "/host/path/a", "Destination": "/foss/designs"},
            {"Source": "/host/path/b", "Destination": "/foss/eda"},
            {"Source": "", "Destination": "/foss/skip"},  # skip empty source
        ]
    }])
    monkeypatch.setattr(mod.subprocess, "check_output",
                        lambda *a, **kw: fake_output)
    result = mod._container_mounts("vibeic-eda")
    assert (Path("/host/path/a"), "/foss/designs") in result
    assert (Path("/host/path/b"), "/foss/eda") in result
    # Empty Source should be dropped
    assert len(result) == 2
