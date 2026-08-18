"""The landing pytest runtime cannot be shadowed by the subject checkout."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parents[1]
ENTRY = PROGRAMS / "trusted_pytest_entry.py"
IMAGE = ("ghcr.io/vibeic/vibeic-eda@sha256:"
         "66c33ff2e05781758f596d82bff61ad8a404ef0a7eae3d21ab8a9d55df0d01ff")


def test_isolated_entry_ignores_subject_pytest_and_progress_plugin(tmp_path):
    isolated_probe = subprocess.run(
        [sys.executable, "-I", "-c", "import pytest"],
        capture_output=True, text=True)
    if isolated_probe.returncode != 0:
        import pytest
        pytest.skip("host isolated interpreter has no image-owned pytest")
    (tmp_path / "pytest.py").write_text(
        "raise AssertionError('subject pytest shadow loaded')\n",
        encoding="utf-8")
    (tmp_path / "_pytest_progress_plugin.py").write_text(
        "raise AssertionError('subject progress shadow loaded')\n",
        encoding="utf-8")
    (tmp_path / "test_ok.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8")
    env = {key: value for key, value in os.environ.items()
           if key not in {"PYTHONPATH", "PYTHONHOME"}}
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"

    proc = subprocess.run(
        [sys.executable, "-I", str(ENTRY), "-q", "-p",
         "no:cacheprovider", "test_ok.py"],
        cwd=tmp_path, env=env, capture_output=True, text=True)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "1 passed" in proc.stdout


def test_nonisolated_entry_refuses_before_subject_collection(tmp_path):
    (tmp_path / "test_never.py").write_text(
        "raise AssertionError('subject collected')\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(ENTRY), "-q", "test_never.py"],
        cwd=tmp_path, capture_output=True, text=True)
    assert proc.returncode == 2
    assert "requires python3 -I" in proc.stderr


def test_pinned_hermetic_image_ignores_subject_module_shadows(tmp_path):
    import pytest
    available = subprocess.run(
        ["docker", "image", "inspect", IMAGE],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL)
    if available.returncode != 0:
        pytest.skip("exact hermetic landing image is not locally available")
    (tmp_path / "pytest.py").write_text(
        "raise AssertionError('subject pytest shadow loaded')\n",
        encoding="utf-8")
    (tmp_path / "_pytest_progress_plugin.py").write_text(
        "raise AssertionError('subject progress shadow loaded')\n",
        encoding="utf-8")
    (tmp_path / "test_ok.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8")
    tmp_path.chmod(0o755)
    for path in tmp_path.iterdir():
        path.chmod(0o644)
    repo = PROGRAMS.parents[3]
    proc = subprocess.run([
        "docker", "run", "--rm", "--network", "none", "--read-only",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--user", "65534:65534", "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=1073741824",
        "--entrypoint", "python3",
        "-v", f"{repo}:/runtime:ro", "-v", f"{tmp_path}:/subject:ro",
        "-w", "/subject", IMAGE, "-I",
        "/runtime/vibe-ic-marketplace/plugins/vibe-ic/programs/"
        "trusted_pytest_entry.py",
        "-q", "-p", "no:cacheprovider", "test_ok.py",
    ], stdin=subprocess.DEVNULL, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "1 passed" in proc.stdout
