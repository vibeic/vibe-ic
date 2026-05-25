#!/usr/bin/env python3
"""Tests for tools/mcp_eda_sync_check.py — Wave 82 dual-tree sync gate.

Covers four cases:
  1. no_drift_pass    — both trees identical → PASS
  2. drift_fail       — root has extra file → FAIL
  3. file_missing_fail — plugin missing a file present in root → FAIL
  4. version_mismatch_fail — same path, different content → FAIL

Tests construct two synthetic trees under tmp_path; they DO NOT touch
the real mcp-eda-server tree.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "mcp_eda_sync_check.py"
assert SCRIPT.exists()


def _seed_tree(root: Path) -> None:
    """Create a minimal mcp-eda-like layout."""
    (root / "src" / "devices").mkdir(parents=True)
    (root / "test").mkdir()
    (root / "src" / "index.js").write_text("// index\n")
    (root / "src" / "devices" / "manifest.json").write_text("{}\n")
    (root / "test" / "smoke.test.js").write_text("describe('x', ()=>{});\n")
    (root / "INSTALL_GUIDE.md").write_text("# install\n")
    (root / "package.json").write_text('{"name":"mcp-eda"}\n')


def _run(root: Path, plugin: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT),
         "--root", str(root),
         "--plugin", str(plugin)],
        capture_output=True, text=True,
    )


# 1. no_drift_pass
def test_no_drift_pass(tmp_path):
    root = tmp_path / "root"
    plugin = tmp_path / "plugin"
    _seed_tree(root)
    shutil.copytree(root, plugin)
    r = _run(root, plugin)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


# 2. drift_fail (extra file in root)
def test_drift_fail_extra_in_root(tmp_path):
    root = tmp_path / "root"
    plugin = tmp_path / "plugin"
    _seed_tree(root)
    shutil.copytree(root, plugin)
    (root / "src" / "extra.js").write_text("// extra\n")
    r = _run(root, plugin)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL" in r.stdout
    assert "only in root" in r.stdout
    assert "extra.js" in r.stdout


# 3. file_missing_fail (plugin missing a file)
def test_file_missing_fail(tmp_path):
    root = tmp_path / "root"
    plugin = tmp_path / "plugin"
    _seed_tree(root)
    shutil.copytree(root, plugin)
    (plugin / "INSTALL_GUIDE.md").unlink()
    r = _run(root, plugin)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL" in r.stdout
    assert "INSTALL_GUIDE.md" in r.stdout


# 4. version_mismatch_fail (same path, different content)
def test_version_mismatch_fail(tmp_path):
    root = tmp_path / "root"
    plugin = tmp_path / "plugin"
    _seed_tree(root)
    shutil.copytree(root, plugin)
    (plugin / "package.json").write_text('{"name":"mcp-eda","version":"0.2"}\n')
    r = _run(root, plugin)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL" in r.stdout
    assert "differ" in r.stdout
    assert "package.json" in r.stdout


# 5. exempt files (node_modules / __pycache__ / package-lock.json) are ignored.
def test_exempt_node_modules_and_caches_pass(tmp_path):
    root = tmp_path / "root"
    plugin = tmp_path / "plugin"
    _seed_tree(root)
    shutil.copytree(root, plugin)
    # Only-in-root build artefacts must NOT count as drift.
    (root / "node_modules").mkdir()
    (root / "node_modules" / "junk.js").write_text("//\n")
    (root / "package-lock.json").write_text('{"lockfile":1}\n')
    (root / "src" / "__pycache__").mkdir()
    (root / "src" / "__pycache__" / "x.pyc").write_text("garbage")
    r = _run(root, plugin)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout
