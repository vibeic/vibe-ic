#!/usr/bin/env python3
"""Wave 81 — tests for marketplace_version_sync_check.py.

Covers PASS, version-stale FAIL, version-ahead FAIL, --fix mode, and
the missing-field edge case.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = (
    Path(__file__).resolve().parents[2]
    / "programs"
    / "marketplace_version_sync_check.py"
)


def _make_marketplace(tmp_path: Path,
                      plugin_name: str,
                      mkt_version: str | None,
                      pj_version: str,
                      *,
                      include_version_field: bool = True) -> Path:
    """Build a fake marketplace tree under tmp_path/marketplace/.

    Layout:
        tmp_path/marketplace/.claude-plugin/marketplace.json
        tmp_path/marketplace/plugins/<name>/.claude-plugin/plugin.json
    """
    root = tmp_path / "marketplace"
    plugin_dir = root / "plugins" / plugin_name
    (plugin_dir / ".claude-plugin").mkdir(parents=True)
    (plugin_dir / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": plugin_name, "version": pj_version}, indent=2)
    )
    (root / ".claude-plugin").mkdir(parents=True)
    entry: dict = {
        "name": plugin_name,
        "source": f"./plugins/{plugin_name}",
    }
    if include_version_field and mkt_version is not None:
        entry["version"] = mkt_version
    (root / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps({"plugins": [entry]}, indent=2)
    )
    return root


def _run(marketplace_root: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG),
         "--marketplace-dir", str(marketplace_root), *extra],
        capture_output=True, text=True, timeout=30,
    )


def test_pass_when_versions_match(tmp_path):
    """marketplace.json plugins[].version == plugin.json.version → PASS."""
    root = _make_marketplace(tmp_path, "demo", "1.2.3", "1.2.3")
    r = _run(root)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "[PASS]" in r.stdout


def test_fail_when_marketplace_version_stale(tmp_path):
    """marketplace.json older than plugin.json (typical drift) → FAIL."""
    root = _make_marketplace(tmp_path, "demo", "0.120.0", "0.135.0")
    r = _run(root)
    assert r.returncode == 1, (r.stdout, r.stderr)
    assert "[FAIL]" in r.stdout
    assert "0.120.0" in r.stdout and "0.135.0" in r.stdout


def test_fail_when_marketplace_version_ahead(tmp_path):
    """marketplace.json ahead of plugin.json (shouldn't happen but is a
    drift) → FAIL too."""
    root = _make_marketplace(tmp_path, "demo", "2.0.0", "1.2.3")
    r = _run(root)
    assert r.returncode == 1, (r.stdout, r.stderr)
    assert "[FAIL]" in r.stdout


def test_fix_mode_repairs_drift(tmp_path):
    """--fix bumps marketplace.json to plugin.json.version and PASSes."""
    root = _make_marketplace(tmp_path, "demo", "0.120.0", "0.135.0")
    r = _run(root, "--fix")
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "[PASS_AFTER_FIX]" in r.stdout
    # marketplace.json now reflects 0.135.0
    mkt = json.loads(
        (root / ".claude-plugin" / "marketplace.json").read_text()
    )
    assert mkt["plugins"][0]["version"] == "0.135.0"
    # a follow-up plain run is now PASS
    r2 = _run(root)
    assert r2.returncode == 0


def test_no_version_field_is_skipped_not_failed(tmp_path):
    """marketplace.json entry without a version field is treated as
    'not pinned' and PASSes (matches the program's documented contract:
    'marketplace.json doesn't pin a version for this plugin — OK')."""
    root = _make_marketplace(
        tmp_path, "demo", None, "1.2.3", include_version_field=False
    )
    r = _run(root)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "[PASS]" in r.stdout
    assert "no version pinned" in r.stdout


# Wave 81 + v1.6.47: the version-field equality between plugin.json and
# marketplace.json is the ONLY drift surface enforced. The earlier
# v1.6.23 check that descriptions must open with `vX.Y.Z` was a
# CHANGELOG-narrative convention; v1.6.47 drops it (CHANGELOG itself
# is gone, descriptions are now purely functional and version-free).
