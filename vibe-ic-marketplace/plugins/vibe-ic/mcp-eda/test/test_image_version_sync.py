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
import os
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


def _load():
    spec = importlib.util.spec_from_file_location("siv", TOOL)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


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
    m = _load()
    assert m.is_history("tools/vibeic-eda/FIX_STATUS.md")
    assert m.is_history("benchmark-data/ic/OSS_EDA_FORK_ROADMAP.md")
    assert not m.is_history("README.md")
    assert not m.is_history("docs/INSTALL.md")


# ---- issue #215: anchor-vs-reality — consistency is not correctness -----------
# The old check only compared pointers to the VERSION file. If VERSION was itself
# stale, the tree could be internally consistent yet consistently WRONG, and the
# check went GREEN — it even demanded a correct pointer be rolled back to the
# stale anchor. These lock in that VERSION is now checked against the newest
# PUBLISHED image tag (pinnable via env for offline / deterministic CI).


@_skip
def test_newest_published_tag_honors_override(monkeypatch):
    """The published-tag source must be pinnable (offline / CI / tests): a valid
    X.Y.Z override is used verbatim; empty / non-semver overrides degrade to
    (None, reason) rather than crash or silently claim a tag."""
    m = _load()
    monkeypatch.setenv(m.PUBLISHED_TAG_ENV, "9.9.9")
    tag, src = m.newest_published_tag()
    assert tag == "9.9.9" and "override" in src
    monkeypatch.setenv(m.PUBLISHED_TAG_ENV, "not-a-version")
    tag, src = m.newest_published_tag()
    assert tag is None and "X.Y.Z" in src
    monkeypatch.setenv(m.PUBLISHED_TAG_ENV, "")
    tag, src = m.newest_published_tag()
    assert tag is None and "empty" in src


@_skip
def test_stale_anchor_flagged_loudly(monkeypatch, capsys):
    """RED/GREEN control: a VERSION older than the newest published tag must FAIL
    and name BOTH values — internal pointer consistency cannot mask it."""
    m = _load()
    monkeypatch.setenv(m.PUBLISHED_TAG_ENV, "0.2.26")
    rc = m.check_anchor_vs_reality("0.2.23")
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "STALE ANCHOR" in out
    assert "0.2.23" in out and "0.2.26" in out


@_skip
def test_anchor_ok_when_equal_or_ahead(monkeypatch):
    """Equal is clean; VERSION ahead of the newest published tag is a legitimate
    unreleased bump, not a failure. A check that can never return clean is an alarm."""
    m = _load()
    monkeypatch.setenv(m.PUBLISHED_TAG_ENV, "0.2.26")
    assert m.check_anchor_vs_reality("0.2.26") == 0     # equal to published
    assert m.check_anchor_vs_reality("0.3.0") == 0      # ahead / unreleased


@_skip
def test_check_end_to_end_flags_stale_anchor():
    """--check must return non-zero when the (injected) published tag is newer than
    VERSION, EVEN THOUGH every in-tree pointer matches VERSION — the exact
    false-green issue #215 describes. 99.99.99 is used so the pin is unambiguously
    newer than any real VERSION."""
    env = dict(os.environ, VIBEIC_EDA_PUBLISHED_TAG="99.99.99")
    r = subprocess.run([sys.executable, str(TOOL), "--check"],
                       capture_output=True, text=True, env=env)
    assert r.returncode != 0, r.stdout
    assert "STALE ANCHOR" in r.stdout and "99.99.99" in r.stdout


@_skip
def test_check_end_to_end_passes_when_anchor_matches_published():
    """GREEN: with the published tag pinned to the current VERSION, --check is
    clean (pointers consistent AND anchor tracks reality). Not optional — a check
    that cannot return clean is an alarm, not a check (issue #215)."""
    v = (TOOL.parent / "VERSION").read_text().strip()
    env = dict(os.environ, VIBEIC_EDA_PUBLISHED_TAG=v)
    r = subprocess.run([sys.executable, str(TOOL), "--check"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout
    assert "anchor tracks reality" in r.stdout
