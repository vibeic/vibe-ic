#!/usr/bin/env python3
"""Smoke tests for tools/sync_opensource.sh.

Covers the v0.119.25 exclude-list fix: stray *.vcd / *.fst sim outputs
and host-specific package-lock.json must NOT be flagged as drift in
--check mode.

The tests construct a self-contained mini "marketplace" + "opensource_repo"
under tmp_path, run the script in --check mode, and assert the expected
exit code + drift count. They DO NOT run against the real repo.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent / "sync_opensource.sh"
assert SCRIPT.exists()


def _build_fake_root(tmp: Path):
    """Create the minimum directory structure the script expects:
       <tmp>/.git/                    — so `git rev-parse` works
       <tmp>/vibe-ic-marketplace/...
       <tmp>/mcp-eda-server/...
       <tmp>/opensource_repo/{vibe-ic-marketplace,mcp-eda-server}/..."""
    subprocess.run(["git", "init", "-q", str(tmp)], check=True,
                   stdout=subprocess.DEVNULL)
    for sub in ("vibe-ic-marketplace", "mcp-eda-server",
                "opensource_repo/vibe-ic-marketplace",
                "opensource_repo/mcp-eda-server"):
        (tmp / sub).mkdir(parents=True)


def _run_script(tmp: Path, *flags) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT), *flags],
        cwd=str(tmp),
        capture_output=True, text=True,
    )


def test_check_clean_zero_drift(tmp_path):
    _build_fake_root(tmp_path)
    # Identical content on both sides
    (tmp_path / "vibe-ic-marketplace" / "hello.py").write_text("# hi\n")
    (tmp_path / "opensource_repo" / "vibe-ic-marketplace" /
        "hello.py").write_text("# hi\n")
    r = _run_script(tmp_path, "--check")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "no drift" in r.stderr or "no drift" in r.stdout


def test_check_real_drift_reports(tmp_path):
    _build_fake_root(tmp_path)
    (tmp_path / "vibe-ic-marketplace" / "hello.py").write_text("# hi v2\n")
    (tmp_path / "opensource_repo" / "vibe-ic-marketplace" /
        "hello.py").write_text("# hi v1\n")
    r = _run_script(tmp_path, "--check")
    assert r.returncode == 1
    assert "drift" in r.stderr.lower() or "drift" in r.stdout.lower()


def test_vcd_files_excluded_from_drift(tmp_path):
    """v0.119.25: a stray .vcd (sim output) on either side must NOT
    register as drift."""
    _build_fake_root(tmp_path)
    (tmp_path / "vibe-ic-marketplace" / "hello.py").write_text("# hi\n")
    (tmp_path / "opensource_repo" / "vibe-ic-marketplace" /
        "hello.py").write_text("# hi\n")
    # Stray VCD only on root side
    (tmp_path / "vibe-ic-marketplace" / "tb_integration.vcd").write_text(
        "$dumpfile\n")
    r = _run_script(tmp_path, "--check")
    assert r.returncode == 0, \
        f"VCD must be excluded; got: {r.stdout}\n{r.stderr}"


def test_fst_files_excluded(tmp_path):
    """Same for GTKWave .fst dumps."""
    _build_fake_root(tmp_path)
    (tmp_path / "vibe-ic-marketplace" / "hello.py").write_text("# hi\n")
    (tmp_path / "opensource_repo" / "vibe-ic-marketplace" /
        "hello.py").write_text("# hi\n")
    (tmp_path / "vibe-ic-marketplace" / "wave.fst").write_text("FSTDUMP\n")
    r = _run_script(tmp_path, "--check")
    assert r.returncode == 0, r.stdout + r.stderr


def test_package_lock_excluded(tmp_path):
    """package-lock.json varies per host (npm version / timestamp);
    must not register as drift even when contents differ."""
    _build_fake_root(tmp_path)
    (tmp_path / "mcp-eda-server" / "package-lock.json").write_text(
        '{"v":1}\n')
    (tmp_path / "opensource_repo" / "mcp-eda-server" /
        "package-lock.json").write_text('{"v":2}\n')
    r = _run_script(tmp_path, "--check")
    assert r.returncode == 0, r.stdout + r.stderr


def test_pycache_excluded(tmp_path):
    """Existing exclude — keep covered to prevent regression."""
    _build_fake_root(tmp_path)
    py_cache = tmp_path / "vibe-ic-marketplace" / "__pycache__"
    py_cache.mkdir()
    (py_cache / "x.cpython-310.pyc").write_text("noise")
    r = _run_script(tmp_path, "--check")
    assert r.returncode == 0
