#!/usr/bin/env python3
"""Fool-proof gate: the `vibeic-eda:X.Y.Z` tag in the install docs must equal the
VERSION source of truth (`tools/vibeic-eda/VERSION`). Drift means users pull a
stale / nonexistent image, so a mismatch FAILS the plugin test suite.

The check is delegated to the repo tool `tools/vibeic-eda/sync_image_version.py`,
which also carries the repo-wide `ghcr.io/...` drift net. All tests SKIP cleanly
when that tool is absent (installed plugin ships no repo-root tools/) so CI in the
packaged plugin stays green.
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


def _find_tool():
    for up in Path(__file__).resolve().parents:
        c = up / "tools" / "vibeic-eda" / "sync_image_version.py"
        if c.is_file():
            return c
    return None


TOOL = _find_tool()
_skip = pytest.mark.skipif(TOOL is None, reason="tools/vibeic-eda/sync_image_version.py not present")


@_skip
def test_install_docs_in_sync_with_version_file():
    r = subprocess.run([sys.executable, str(TOOL), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, f"vibeic-eda image-version drift:\n{r.stdout}\n{r.stderr}"


@_skip
def test_bump_dry_run_is_nondestructive():
    before = (TOOL.parent / "VERSION").read_text()
    r = subprocess.run([sys.executable, str(TOOL), "--bump", "patch", "--dry-run"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "would write VERSION" in r.stdout
    assert (TOOL.parent / "VERSION").read_text() == before, "dry-run must not mutate VERSION"


@_skip
def test_next_version_rollover():
    spec = importlib.util.spec_from_file_location("siv", TOOL)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert m.next_version("0.2.12", "patch") == "0.2.13"
    assert m.next_version("0.2.99", "patch") == "0.3.0"      # patch 0..99 rollover
    assert m.next_version("0.9.99", "patch") == "0.10.0"
    assert m.next_version("0.2.12", "minor") == "0.3.0"
    assert m.next_version("0.2.12", "major") == "1.0.0"


@_skip
def test_history_globs_exclude_changelog_and_roadmap():
    """The classifier must treat status/roadmap docs as history (never bumped),
    else it would rewrite 'shipped in vibeic-eda:0.2.5' prose."""
    spec = importlib.util.spec_from_file_location("siv", TOOL)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert m.is_history("tools/vibeic-eda/FIX_STATUS.md")
    assert m.is_history("benchmark-data/ic/OSS_EDA_FORK_ROADMAP.md")
    assert not m.is_history("README.md")
    assert not m.is_history("docs/INSTALL.md")
